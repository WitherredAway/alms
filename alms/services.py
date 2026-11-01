"""Core circulation business rules (FR-04, FR-05, FR-06)."""
from datetime import timedelta

from .db import get_db, now_ts, parse_date, setting, setting_float, setting_int, today


class CirculationError(Exception):
    pass


MEMBER_ROLES = ("student", "faculty")
STAFF_ROLES = ("librarian", "admin")


def audit(action, details="", actor_id=None, db=None):
    db = db or get_db()
    db.execute(
        "INSERT INTO audit_log(ts, actor_id, action, details) VALUES (?, ?, ?, ?)",
        (now_ts(db), actor_id, action, details),
    )


def notify(user_id, subject, body, channels=("email", "sms"), ref=None, db=None):
    """Simulated Email/SMS gateway: messages are stored and shown in the Notification Gateway outbox."""
    db = db or get_db()
    if ref and db.execute("SELECT 1 FROM notifications WHERE ref = ? AND user_id = ?", (ref, user_id)).fetchone():
        return
    ts = now_ts(db)
    for ch in channels:
        db.execute(
            "INSERT INTO notifications(user_id, channel, subject, body, ref, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, ch, subject, body, ref, ts),
        )


def rupees(amount):
    amount = float(amount or 0)
    return f"₹{amount:,.0f}" if amount == int(amount) else f"₹{amount:,.2f}"


def quota_for(user):
    if user["role"] == "faculty":
        return setting_int("quota_faculty")
    return setting_int("quota_student")


def overdue_days(due_date, on_date=None):
    on_date = on_date or today()
    return max(0, (on_date - parse_date(due_date)).days)


def accrued_fine(loan, on_date=None):
    return overdue_days(loan["due_date"], on_date) * setting_float("fine_per_day")


def member_status(user_id):
    """Query Member Profile & Active Loans (Activity diagram step 2)."""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        return None
    loans = db.execute(
        """SELECT l.*, c.barcode, b.title, b.author, b.id AS book_id FROM loans l
           JOIN copies c ON c.id = l.copy_id JOIN books b ON b.id = c.book_id
           WHERE l.user_id = ? AND l.status = 'active' ORDER BY l.due_date""",
        (user_id,),
    ).fetchall()
    loans = [dict(l, overdue_days=overdue_days(l["due_date"]), accrued=accrued_fine(l)) for l in loans]
    unpaid = db.execute(
        "SELECT * FROM fines WHERE user_id = ? AND status = 'unpaid' ORDER BY created_at", (user_id,)
    ).fetchall()
    unpaid_total = sum(f["amount"] for f in unpaid)
    accruing_total = sum(l["accrued"] for l in loans)
    holds = db.execute(
        """SELECT h.*, b.title, b.author FROM holds h JOIN books b ON b.id = h.book_id
           WHERE h.user_id = ? AND h.status IN ('waiting','ready') ORDER BY h.placed_at""",
        (user_id,),
    ).fetchall()
    holds = [dict(h, position=hold_position(h)) for h in holds]
    quota = quota_for(user) if user["role"] in MEMBER_ROLES else 0
    reasons = []
    if not user["active"]:
        reasons.append("Membership is inactive")
    if user["role"] not in MEMBER_ROLES:
        reasons.append("Staff accounts cannot borrow")
    if unpaid_total > 0:
        reasons.append(f"Unpaid fines of {rupees(unpaid_total)}")
    if accruing_total > 0:
        n = sum(1 for l in loans if l["overdue_days"] > 0)
        reasons.append(f"{n} overdue book(s) accruing {rupees(accruing_total)} — return and pay first")
    if quota and len(loans) >= quota:
        reasons.append(f"Borrowing quota reached ({len(loans)}/{quota})")
    return {
        "user": user,
        "loans": loans,
        "unpaid_fines": unpaid,
        "unpaid_total": unpaid_total,
        "accruing_total": accruing_total,
        "balance": unpaid_total + accruing_total,
        "holds": holds,
        "quota": quota,
        "eligible": not reasons,
        "reasons": reasons,
    }


def hold_position(hold):
    if hold["status"] != "waiting":
        return 0
    db = get_db()
    return db.execute(
        "SELECT COUNT(*) FROM holds WHERE book_id = ? AND status = 'waiting' AND (placed_at < ? OR (placed_at = ? AND id <= ?))",
        (hold["book_id"], hold["placed_at"], hold["placed_at"], hold["id"]),
    ).fetchone()[0]


def find_member(code):
    code = (code or "").strip()
    return get_db().execute(
        "SELECT * FROM users WHERE UPPER(member_code) = UPPER(?) OR LOWER(email) = LOWER(?)", (code, code)
    ).fetchone()


def find_copy(barcode):
    return get_db().execute(
        """SELECT c.*, b.title, b.author, b.isbn FROM copies c JOIN books b ON b.id = c.book_id
           WHERE UPPER(c.barcode) = UPPER(?)""",
        ((barcode or "").strip(),),
    ).fetchone()


def issue_book(member_code, barcode, staff_id):
    """Scan-to-issue (FR-04). Returns the new loan id."""
    db = get_db()
    member = find_member(member_code)
    if not member:
        raise CirculationError(f"No member found with ID '{member_code}'.")
    copy = find_copy(barcode)
    if not copy:
        raise CirculationError(f"No book copy found with barcode '{barcode}'.")
    status = member_status(member["id"])
    if not status["eligible"]:
        raise CirculationError("Issue blocked: " + "; ".join(status["reasons"]) + ".")

    hold_to_fulfil = None
    if copy["status"] == "on_hold":
        hold_to_fulfil = db.execute(
            "SELECT * FROM holds WHERE copy_id = ? AND status = 'ready'", (copy["id"],)
        ).fetchone()
        if not hold_to_fulfil or hold_to_fulfil["user_id"] != member["id"]:
            raise CirculationError("This copy is reserved on the hold shelf for another member.")
    elif copy["status"] == "loaned":
        raise CirculationError("This copy is already on loan. Return it first or place a hold.")
    elif copy["status"] != "available":
        raise CirculationError(f"This copy cannot be issued (status: {copy['status']}).")
    elif db.execute(
        "SELECT 1 FROM loans l JOIN copies c ON c.id = l.copy_id WHERE l.user_id = ? AND c.book_id = ? AND l.status = 'active'",
        (member["id"], copy["book_id"]),
    ).fetchone():
        raise CirculationError("Member already has a copy of this title on loan.")

    issue_date = today()
    due = issue_date + timedelta(days=setting_int("loan_days"))
    cur = db.execute(
        "INSERT INTO loans(copy_id, user_id, issued_by, issue_date, due_date) VALUES (?, ?, ?, ?, ?)",
        (copy["id"], member["id"], staff_id, issue_date.isoformat(), due.isoformat()),
    )
    loan_id = cur.lastrowid
    db.execute("UPDATE copies SET status = 'loaned' WHERE id = ?", (copy["id"],))
    if hold_to_fulfil:
        db.execute("UPDATE holds SET status = 'fulfilled' WHERE id = ?", (hold_to_fulfil["id"],))
    else:
        # A member collecting a title they had queued for also clears their waiting hold.
        db.execute(
            "UPDATE holds SET status = 'fulfilled' WHERE user_id = ? AND book_id = ? AND status = 'waiting'",
            (member["id"], copy["book_id"]),
        )
    notify(
        member["id"],
        "Book issued",
        f"'{copy['title']}' (copy {copy['barcode']}) has been issued to you. Due date: {due.strftime('%d %b %Y')}.",
        ref=f"issue:{loan_id}",
    )
    audit("ISSUE", f"{copy['barcode']} '{copy['title']}' to {member['member_code']} due {due}", staff_id)
    db.commit()
    return loan_id


def _assign_copy_to_next_hold(copy_id, book_id, title, actor_id=None):
    """Return path of the Activity diagram: route a returned copy to the hold queue."""
    db = get_db()
    nxt = db.execute(
        "SELECT h.*, u.member_code FROM holds h JOIN users u ON u.id = h.user_id WHERE h.book_id = ? AND h.status = 'waiting' ORDER BY h.placed_at, h.id LIMIT 1",
        (book_id,),
    ).fetchone()
    if not nxt:
        db.execute("UPDATE copies SET status = 'available' WHERE id = ?", (copy_id,))
        return None
    t = today()
    expires = t + timedelta(days=setting_int("hold_pickup_days"))
    db.execute(
        "UPDATE holds SET status = 'ready', copy_id = ?, ready_at = ?, expires_at = ? WHERE id = ?",
        (copy_id, t.isoformat(), expires.isoformat(), nxt["id"]),
    )
    db.execute("UPDATE copies SET status = 'on_hold' WHERE id = ?", (copy_id,))
    notify(
        nxt["user_id"],
        "Your reserved book is ready",
        f"'{title}' is now waiting for you at the circulation desk. Please collect it by {expires.strftime('%d %b %Y')}.",
        ref=f"holdready:{nxt['id']}",
    )
    audit("HOLD_READY", f"'{title}' reserved for {nxt['member_code']} until {expires}", actor_id)
    return nxt


def return_book(barcode, staff_id, condition="good"):
    """Check-in return verification (FR-04) + overdue fine computation (FR-06)."""
    db = get_db()
    copy = find_copy(barcode)
    if not copy:
        raise CirculationError(f"No book copy found with barcode '{barcode}'.")
    loan = db.execute(
        "SELECT l.*, u.member_code, u.name FROM loans l JOIN users u ON u.id = l.user_id WHERE l.copy_id = ? AND l.status = 'active'",
        (copy["id"],),
    ).fetchone()
    if not loan:
        raise CirculationError("This copy is not currently on loan.")
    t = today()
    days = overdue_days(loan["due_date"], t)
    fine_amount = days * setting_float("fine_per_day")
    db.execute("UPDATE loans SET status = 'returned', return_date = ? WHERE id = ?", (t.isoformat(), loan["id"]))
    fine_id = None
    if fine_amount > 0:
        fine_id = db.execute(
            "INSERT INTO fines(user_id, loan_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (loan["user_id"], loan["id"], fine_amount, f"Overdue {days} day(s): {copy['title']}", now_ts()),
        ).lastrowid
        notify(
            loan["user_id"],
            "Overdue fine assessed",
            f"'{copy['title']}' was returned {days} day(s) late. A fine of {rupees(fine_amount)} has been added to your account.",
            ref=f"fine:{fine_id}",
        )
    hold = None
    if condition == "damaged":
        db.execute("UPDATE copies SET status = 'damaged' WHERE id = ?", (copy["id"],))
    else:
        hold = _assign_copy_to_next_hold(copy["id"], copy["book_id"], copy["title"], staff_id)
    notify(
        loan["user_id"],
        "Book returned",
        f"Thank you! '{copy['title']}' has been checked in on {t.strftime('%d %b %Y')}.",
        channels=("email",),
        ref=f"return:{loan['id']}",
    )
    audit(
        "RETURN",
        f"{copy['barcode']} '{copy['title']}' from {loan['member_code']}"
        + (f", {days}d late, fine {rupees(fine_amount)}" if fine_amount else "")
        + (", marked DAMAGED" if condition == "damaged" else ""),
        staff_id,
    )
    db.commit()
    return {"loan": loan, "copy": copy, "overdue_days": days, "fine": fine_amount, "fine_id": fine_id, "hold": hold}


def renew_loan(loan_id, actor_id):
    db = get_db()
    loan = db.execute(
        "SELECT l.*, c.book_id, b.title FROM loans l JOIN copies c ON c.id = l.copy_id JOIN books b ON b.id = c.book_id WHERE l.id = ?",
        (loan_id,),
    ).fetchone()
    if not loan or loan["status"] != "active":
        raise CirculationError("Loan not found or not active.")
    if overdue_days(loan["due_date"]) > 0:
        raise CirculationError("Overdue loans cannot be renewed. Please return the book and pay the fine.")
    if loan["renewals"] >= setting_int("max_renewals"):
        raise CirculationError("Maximum number of renewals reached for this loan.")
    if db.execute("SELECT 1 FROM holds WHERE book_id = ? AND status = 'waiting'", (loan["book_id"],)).fetchone():
        raise CirculationError("Another member has reserved this title, so it cannot be renewed.")
    new_due = parse_date(loan["due_date"]) + timedelta(days=setting_int("loan_days"))
    db.execute(
        "UPDATE loans SET due_date = ?, renewals = renewals + 1 WHERE id = ?", (new_due.isoformat(), loan_id)
    )
    notify(
        loan["user_id"],
        "Loan renewed",
        f"'{loan['title']}' has been renewed. New due date: {new_due.strftime('%d %b %Y')}.",
        ref=f"renew:{loan_id}:{loan['renewals'] + 1}",
    )
    audit("RENEW", f"Loan #{loan_id} '{loan['title']}' new due {new_due}", actor_id)
    db.commit()
    return new_due


def mark_lost(loan_id, actor_id):
    db = get_db()
    loan = db.execute(
        "SELECT l.*, c.barcode, b.title FROM loans l JOIN copies c ON c.id = l.copy_id JOIN books b ON b.id = c.book_id WHERE l.id = ?",
        (loan_id,),
    ).fetchone()
    if not loan or loan["status"] != "active":
        raise CirculationError("Loan not found or not active.")
    t = today()
    days = overdue_days(loan["due_date"], t)
    overdue = days * setting_float("fine_per_day")
    fee = setting_float("lost_book_fee")
    db.execute("UPDATE loans SET status = 'lost', return_date = ? WHERE id = ?", (t.isoformat(), loan_id))
    db.execute("UPDATE copies SET status = 'lost' WHERE id = ?", (loan["copy_id"],))
    db.execute(
        "INSERT INTO fines(user_id, loan_id, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        (loan["user_id"], loan_id, fee + overdue, f"Lost book replacement: {loan['title']}" + (f" (+{days}d overdue)" if days else ""), now_ts()),
    )
    notify(
        loan["user_id"],
        "Book marked as lost",
        f"'{loan['title']}' has been recorded as lost. A charge of {rupees(fee + overdue)} has been added to your account.",
        ref=f"lost:{loan_id}",
    )
    audit("LOST", f"{loan['barcode']} '{loan['title']}' charged {rupees(fee + overdue)}", actor_id)
    db.commit()


def place_hold(user_id, book_id, actor_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    book = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if not user or not book:
        raise CirculationError("Member or book not found.")
    if user["role"] not in MEMBER_ROLES or not user["active"]:
        raise CirculationError("Only active members can place holds.")
    if db.execute(
        "SELECT 1 FROM holds WHERE user_id = ? AND book_id = ? AND status IN ('waiting','ready')", (user_id, book_id)
    ).fetchone():
        raise CirculationError("A hold for this title already exists for this member.")
    if db.execute(
        "SELECT 1 FROM loans l JOIN copies c ON c.id = l.copy_id WHERE l.user_id = ? AND c.book_id = ? AND l.status = 'active'",
        (user_id, book_id),
    ).fetchone():
        raise CirculationError("Member already has this title on loan.")
    if available_copies(book_id) > 0:
        raise CirculationError("Copies are available on the shelf — the book can be borrowed directly.")
    hid = db.execute(
        "INSERT INTO holds(book_id, user_id, placed_at) VALUES (?, ?, ?)", (book_id, user_id, now_ts())
    ).lastrowid
    pos = hold_position(db.execute("SELECT * FROM holds WHERE id = ?", (hid,)).fetchone())
    notify(
        user_id,
        "Hold placed",
        f"You are #{pos} in the queue for '{book['title']}'. We will notify you when a copy is returned.",
        ref=f"hold:{hid}",
    )
    audit("HOLD", f"'{book['title']}' for {user['member_code']} (queue #{pos})", actor_id)
    db.commit()
    return hid, pos


def cancel_hold(hold_id, actor_id):
    db = get_db()
    hold = db.execute(
        "SELECT h.*, b.title FROM holds h JOIN books b ON b.id = h.book_id WHERE h.id = ?", (hold_id,)
    ).fetchone()
    if not hold or hold["status"] not in ("waiting", "ready"):
        raise CirculationError("Hold not found or already closed.")
    db.execute("UPDATE holds SET status = 'cancelled' WHERE id = ?", (hold_id,))
    if hold["status"] == "ready" and hold["copy_id"]:
        _assign_copy_to_next_hold(hold["copy_id"], hold["book_id"], hold["title"], actor_id)
    audit("HOLD_CANCEL", f"Hold #{hold_id} '{hold['title']}'", actor_id)
    db.commit()
    return hold


def available_copies(book_id):
    return get_db().execute(
        "SELECT COUNT(*) FROM copies WHERE book_id = ? AND status = 'available'", (book_id,)
    ).fetchone()[0]


def _receipt_no():
    db = get_db()
    n = db.execute("SELECT COUNT(*) FROM fines WHERE receipt_no IS NOT NULL").fetchone()[0] + 1
    return f"RCPT-{today().strftime('%Y%m%d')}-{n:04d}"


def pay_fines(user_id, fine_ids, method, actor_id, reference=""):
    """Process fine payment (cash at desk or simulated online). Returns receipt number."""
    db = get_db()
    if not fine_ids:
        raise CirculationError("Select at least one fine to pay.")
    placeholders = ",".join("?" * len(fine_ids))
    fines = db.execute(
        f"SELECT * FROM fines WHERE id IN ({placeholders}) AND user_id = ? AND status = 'unpaid'",
        (*fine_ids, user_id),
    ).fetchall()
    if not fines:
        raise CirculationError("No unpaid fines selected.")
    receipt = _receipt_no()
    ts = now_ts()
    for f in fines:
        db.execute(
            "UPDATE fines SET status = 'paid', paid_at = ?, method = ?, receipt_no = ?, handled_by = ? WHERE id = ?",
            (ts, method, receipt, actor_id, f["id"]),
        )
    total = sum(f["amount"] for f in fines)
    notify(
        user_id,
        "Payment received",
        f"We received {rupees(total)} via {method}{(' (ref ' + reference + ')') if reference else ''}. Receipt no. {receipt}.",
        ref=f"pay:{receipt}",
    )
    audit("FINE_PAID", f"{receipt} {rupees(total)} via {method} for user #{user_id}", actor_id)
    db.commit()
    return receipt


def waive_fine(fine_id, actor_id, note=""):
    db = get_db()
    fine = db.execute("SELECT * FROM fines WHERE id = ? AND status = 'unpaid'", (fine_id,)).fetchone()
    if not fine:
        raise CirculationError("Fine not found or already settled.")
    db.execute(
        "UPDATE fines SET status = 'waived', paid_at = ?, handled_by = ?, method = ? WHERE id = ?",
        (now_ts(), actor_id, "waiver" + (f": {note}" if note else ""), fine_id),
    )
    notify(fine["user_id"], "Fine waived", f"A fine of {rupees(fine['amount'])} ({fine['reason']}) has been waived by library staff.", ref=f"waive:{fine_id}")
    audit("FINE_WAIVED", f"Fine #{fine_id} {rupees(fine['amount'])} {note}", actor_id)
    db.commit()


def allocate_free_copies(book_id, actor_id=None):
    """When new copies are added, route them to any waiting holds."""
    db = get_db()
    book = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    while True:
        if not db.execute("SELECT 1 FROM holds WHERE book_id = ? AND status = 'waiting'", (book_id,)).fetchone():
            break
        copy = db.execute(
            "SELECT id FROM copies WHERE book_id = ? AND status = 'available' LIMIT 1", (book_id,)
        ).fetchone()
        if not copy:
            break
        _assign_copy_to_next_hold(copy["id"], book_id, book["title"], actor_id)


def daily_sweep(force=False):
    """Runs once per (simulated) day: expire uncollected holds, send due-soon/overdue alerts,
    and take the automated daily database backup (NFR-03)."""
    db = get_db()
    t = today()
    if not force and setting("last_sweep") == t.isoformat():
        return False
    expired = db.execute(
        "SELECT h.*, b.title FROM holds h JOIN books b ON b.id = h.book_id WHERE h.status = 'ready' AND h.expires_at < ?",
        (t.isoformat(),),
    ).fetchall()
    for h in expired:
        db.execute("UPDATE holds SET status = 'expired' WHERE id = ?", (h["id"],))
        notify(h["user_id"], "Hold expired", f"Your hold on '{h['title']}' expired because it was not collected in time.", ref=f"holdexp:{h['id']}")
        audit("HOLD_EXPIRED", f"Hold #{h['id']} '{h['title']}'")
        _assign_copy_to_next_hold(h["copy_id"], h["book_id"], h["title"])
    loans = db.execute(
        "SELECT l.*, b.title FROM loans l JOIN copies c ON c.id = l.copy_id JOIN books b ON b.id = c.book_id WHERE l.status = 'active'"
    ).fetchall()
    rate = setting_float("fine_per_day")
    for l in loans:
        due = parse_date(l["due_date"])
        days_left = (due - t).days
        if 0 <= days_left <= 2:
            notify(l["user_id"], "Due date reminder", f"'{l['title']}' is due on {due.strftime('%d %b %Y')}. Renew or return it to avoid fines.", ref=f"duesoon:{l['id']}:{l['due_date']}")
        elif days_left < 0:
            days = -days_left
            # One overdue notice per week overdue.
            week = (days - 1) // 7
            notify(
                l["user_id"],
                "Overdue notice",
                f"'{l['title']}' is {days} day(s) overdue. Current fine: {rupees(days * rate)} (₹{rate:g}/day). Borrowing is blocked until resolved.",
                ref=f"overdue:{l['id']}:{week}",
            )
    from .backup import automatic_backup

    automatic_backup()
    from .db import set_setting

    set_setting("last_sweep", t.isoformat())
    db.commit()
    return True
