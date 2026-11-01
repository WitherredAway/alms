from datetime import timedelta

import pytest

from alms.db import set_setting, today
from alms.services import (
    CirculationError, cancel_hold, issue_book, mark_lost, member_status, pay_fines, place_hold,
    renew_loan, return_book, waive_fine,
)
from conftest import available_barcode, loaned_barcode, uid

STAFF = None


def staff(db):
    return uid(db, "LIB001")


def test_issue_sets_14_day_due_date_and_decrements_stock(db):
    bc = available_barcode(db, "Higher Engineering Mathematics")
    before = db.execute("SELECT COUNT(*) FROM copies WHERE status='available'").fetchone()[0]
    loan_id = issue_book("STU006", bc, staff(db))
    loan = db.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()
    assert loan["due_date"] == (today() + timedelta(days=14)).isoformat()
    assert db.execute("SELECT status FROM copies WHERE barcode = ?", (bc,)).fetchone()[0] == "loaned"
    assert db.execute("SELECT COUNT(*) FROM copies WHERE status='available'").fetchone()[0] == before - 1
    assert db.execute("SELECT COUNT(*) FROM notifications WHERE ref = ?", (f"issue:{loan_id}",)).fetchone()[0] == 2


def test_issue_blocked_by_overdue_loan(db):
    with pytest.raises(CirculationError, match="overdue"):
        issue_book("STU002", available_barcode(db, "Atomic Habits"), staff(db))


def test_issue_blocked_by_unpaid_fine(db):
    with pytest.raises(CirculationError, match="Unpaid fines"):
        issue_book("STU003", available_barcode(db, "Atomic Habits"), staff(db))


def test_issue_blocked_by_quota(db):
    with pytest.raises(CirculationError, match="quota"):
        issue_book("STU004", available_barcode(db, "Atomic Habits"), staff(db))


def test_faculty_has_higher_quota(db):
    st = member_status(uid(db, "FAC001"))
    assert st["quota"] == 5 and st["eligible"]


def test_cannot_issue_copy_reserved_for_someone_else(db):
    bc = db.execute("SELECT c.barcode FROM holds h JOIN copies c ON c.id = h.copy_id WHERE h.status='ready'").fetchone()[0]
    with pytest.raises(CirculationError, match="reserved"):
        issue_book("STU006", bc, staff(db))
    issue_book("STU005", bc, staff(db))
    assert db.execute("SELECT status FROM holds WHERE copy_id = (SELECT id FROM copies WHERE barcode=?) ORDER BY id DESC", (bc,)).fetchone()[0] == "fulfilled"


def test_on_time_return_restocks_without_fine(db):
    bc = loaned_barcode(db, "STU001", "Introduction to Algorithms")
    r = return_book(bc, staff(db))
    assert r["fine"] == 0 and r["hold"] is None
    assert db.execute("SELECT status FROM copies WHERE barcode = ?", (bc,)).fetchone()[0] == "available"


def test_late_return_assesses_fine_per_day(db):
    bc = loaned_barcode(db, "STU002", "Digital Design")
    r = return_book(bc, staff(db))
    assert r["overdue_days"] == 6 and r["fine"] == 30
    st = member_status(uid(db, "STU002"))
    assert st["unpaid_total"] == 30 and not st["eligible"]


def test_fine_rate_is_configurable(db):
    set_setting("fine_per_day", "10")
    r = return_book(loaned_barcode(db, "STU002", "Digital Design"), staff(db))
    assert r["fine"] == 60


def test_return_routes_copy_to_hold_queue_fifo_and_notifies(db):
    bc = loaned_barcode(db, "STU001", "Clean Code")
    r = return_book(bc, staff(db))
    assert r["hold"]["member_code"] == "STU005"
    assert db.execute("SELECT status FROM copies WHERE barcode = ?", (bc,)).fetchone()[0] == "on_hold"
    hold = db.execute("SELECT * FROM holds WHERE id = ?", (r["hold"]["id"],)).fetchone()
    assert hold["status"] == "ready"
    assert db.execute("SELECT COUNT(*) FROM notifications WHERE ref = ?", (f"holdready:{hold['id']}",)).fetchone()[0] == 2


def test_damaged_return_withdraws_copy(db):
    bc = loaned_barcode(db, "STU001", "Introduction to Algorithms")
    return_book(bc, staff(db), condition="damaged")
    assert db.execute("SELECT status FROM copies WHERE barcode = ?", (bc,)).fetchone()[0] == "damaged"


def test_pay_fine_unblocks_member(db):
    u = uid(db, "STU003")
    ids = [r[0] for r in db.execute("SELECT id FROM fines WHERE user_id=? AND status='unpaid'", (u,))]
    receipt = pay_fines(u, ids, "cash", staff(db))
    assert receipt.startswith("RCPT-")
    assert member_status(u)["eligible"]


def test_waive_fine(db):
    u = uid(db, "STU003")
    fid = db.execute("SELECT id FROM fines WHERE user_id=? AND status='unpaid'", (u,)).fetchone()[0]
    waive_fine(fid, staff(db), "test")
    assert member_status(u)["eligible"]


def test_hold_only_when_no_copies_available(db):
    with pytest.raises(CirculationError, match="available"):
        place_hold(uid(db, "STU006"), db.execute("SELECT id FROM books WHERE title='Atomic Habits'").fetchone()[0], None)
    book = db.execute("SELECT id FROM books WHERE title='Clean Code'").fetchone()[0]
    _, pos = place_hold(uid(db, "STU006"), book, None)
    assert pos == 3
    with pytest.raises(CirculationError, match="already exists"):
        place_hold(uid(db, "STU006"), book, None)


def test_cancel_ready_hold_passes_copy_to_next(db):
    book = db.execute("SELECT id FROM books WHERE title='Clean Code'").fetchone()[0]
    return_book(loaned_barcode(db, "STU001", "Clean Code"), staff(db))
    first = db.execute("SELECT id FROM holds WHERE book_id=? AND status='ready'", (book,)).fetchone()[0]
    cancel_hold(first, None)
    nxt = db.execute("SELECT u.member_code FROM holds h JOIN users u ON u.id=h.user_id WHERE h.book_id=? AND h.status='ready'", (book,)).fetchone()[0]
    assert nxt == "STU010"


def test_renew_rules(db):
    lid = db.execute("SELECT l.id FROM loans l JOIN users u ON u.id=l.user_id WHERE u.member_code='STU004' AND l.status='active' LIMIT 1").fetchone()[0]
    old = db.execute("SELECT due_date FROM loans WHERE id=?", (lid,)).fetchone()[0]
    new_due = renew_loan(lid, None)
    assert (new_due - __import__("datetime").date.fromisoformat(old)).days == 14
    with pytest.raises(CirculationError, match="Maximum"):
        renew_loan(lid, None)
    # Title with a waiting hold cannot be renewed
    clean = db.execute("SELECT l.id FROM loans l JOIN copies c ON c.id=l.copy_id JOIN books b ON b.id=c.book_id WHERE b.title='Clean Code' AND l.status='active'").fetchone()[0]
    with pytest.raises(CirculationError, match="reserved"):
        renew_loan(clean, None)
    od = db.execute("SELECT l.id FROM loans l JOIN users u ON u.id=l.user_id WHERE u.member_code='STU002' AND l.status='active'").fetchone()[0]
    with pytest.raises(CirculationError, match="Overdue"):
        renew_loan(od, None)


def test_mark_lost_charges_replacement(db):
    lid = db.execute("SELECT l.id, l.user_id FROM loans l JOIN users u ON u.id=l.user_id WHERE u.member_code='STU002' AND l.status='active'").fetchone()
    mark_lost(lid[0], None)
    assert member_status(lid[1])["unpaid_total"] == 500 + 30


def test_simulated_date_makes_loans_overdue(db):
    u = uid(db, "STU001")
    assert member_status(u)["eligible"]
    set_setting("date_offset", "20")
    st = member_status(u)
    assert not st["eligible"] and st["accruing_total"] > 0
