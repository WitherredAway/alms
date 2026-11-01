"""Reports & Audit (FR-07)."""
import csv
import io
from datetime import timedelta

from flask import Blueprint, Response, render_template, request

from ..auth import staff_required
from ..db import get_db, setting_float, today
from ..services import overdue_days

bp = Blueprint("reports", __name__, url_prefix="/reports")

TABS = [
    ("overview", "Overview"),
    ("active", "Active loans"),
    ("overdue", "Overdue"),
    ("frequency", "Circulation frequency"),
    ("lost", "Lost & damaged"),
    ("fines", "Fines & collections"),
    ("dues", "Members with dues"),
]


def _range():
    days = request.args.get("days", 30, type=int)
    days = days if days in (7, 30, 90, 365) else 30
    return days, (today() - timedelta(days=days - 1)).isoformat()


def build(tab):
    db = get_db()
    t = today()
    rate = setting_float("fine_per_day")
    days, since = _range()
    if tab == "active":
        rows = db.execute(
            """SELECT l.id, c.barcode, b.title, u.member_code, u.name, l.issue_date, l.due_date, l.renewals
               FROM loans l JOIN copies c ON c.id = l.copy_id JOIN books b ON b.id = c.book_id JOIN users u ON u.id = l.user_id
               WHERE l.status = 'active' ORDER BY l.due_date"""
        ).fetchall()
        head = ["Loan #", "Barcode", "Title", "Member ID", "Member", "Issued", "Due", "Renewals", "Status"]
        data = [[*r, f"Overdue {overdue_days(r['due_date'])}d" if overdue_days(r["due_date"]) else "On time"] for r in rows]
        return head, data, None
    if tab == "overdue":
        rows = db.execute(
            """SELECT c.barcode, b.title, u.member_code, u.name, u.phone, l.due_date
               FROM loans l JOIN copies c ON c.id = l.copy_id JOIN books b ON b.id = c.book_id JOIN users u ON u.id = l.user_id
               WHERE l.status = 'active' AND l.due_date < ? ORDER BY l.due_date""",
            (t.isoformat(),),
        ).fetchall()
        head = ["Barcode", "Title", "Member ID", "Member", "Phone", "Due", "Days overdue", "Fine accrued (₹)"]
        data = [[*r, overdue_days(r["due_date"]), overdue_days(r["due_date"]) * rate] for r in rows]
        return head, data, None
    if tab == "frequency":
        rows = db.execute(
            """SELECT b.title, b.author, b.category, COUNT(l.id) AS loans,
                      COUNT(DISTINCT l.user_id) AS borrowers
               FROM loans l JOIN copies c ON c.id = l.copy_id JOIN books b ON b.id = c.book_id
               WHERE l.issue_date >= ? GROUP BY b.id ORDER BY loans DESC, b.title LIMIT 50""",
            (since,),
        ).fetchall()
        head = ["Title", "Author", "Category", "Times issued", "Unique borrowers"]
        data = [list(r) for r in rows]
        chart = {"labels": [r["title"][:28] for r in rows[:10]], "values": [r["loans"] for r in rows[:10]]}
        return head, data, chart
    if tab == "lost":
        rows = db.execute(
            """SELECT c.barcode, b.title, b.isbn, c.status,
                      (SELECT u.member_code || ' ' || u.name FROM loans l JOIN users u ON u.id = l.user_id
                        WHERE l.copy_id = c.id ORDER BY l.id DESC LIMIT 1) AS last_borrower,
                      (SELECT l.return_date FROM loans l WHERE l.copy_id = c.id ORDER BY l.id DESC LIMIT 1) AS last_date
               FROM copies c JOIN books b ON b.id = c.book_id WHERE c.status IN ('lost','damaged','discarded') ORDER BY c.status, b.title"""
        ).fetchall()
        head = ["Barcode", "Title", "ISBN", "Status", "Last borrower", "Recorded on"]
        return head, [list(r) for r in rows], None
    if tab == "fines":
        rows = db.execute(
            """SELECT f.receipt_no, f.paid_at, u.member_code, u.name, f.reason, f.method, f.amount, f.status
               FROM fines f JOIN users u ON u.id = f.user_id
               WHERE f.status IN ('paid','waived') AND f.paid_at >= ? ORDER BY f.paid_at DESC""",
            (since,),
        ).fetchall()
        head = ["Receipt", "Date", "Member ID", "Member", "Reason", "Method", "Amount (₹)", "Status"]
        return head, [list(r) for r in rows], None
    if tab == "dues":
        rows = db.execute(
            """SELECT u.member_code, u.name, u.email, u.phone,
                      COALESCE((SELECT SUM(amount) FROM fines f WHERE f.user_id = u.id AND f.status='unpaid'),0) AS unpaid,
                      (SELECT COUNT(*) FROM loans l WHERE l.user_id = u.id AND l.status='active' AND l.due_date < ?) AS overdue,
                      COALESCE((SELECT SUM(julianday(?) - julianday(l.due_date)) FROM loans l
                                WHERE l.user_id = u.id AND l.status='active' AND l.due_date < ?),0) AS od_days
               FROM users u WHERE u.role IN ('student','faculty')""",
            (t.isoformat(), t.isoformat(), t.isoformat()),
        ).fetchall()
        head = ["Member ID", "Member", "Email", "Phone", "Unpaid fines (₹)", "Overdue books", "Accruing (₹)", "Total due (₹)"]
        data = [
            [r["member_code"], r["name"], r["email"], r["phone"], r["unpaid"], r["overdue"], r["od_days"] * rate, r["unpaid"] + r["od_days"] * rate]
            for r in rows if r["unpaid"] or r["overdue"]
        ]
        data.sort(key=lambda x: -x[-1])
        return head, data, None
    return None, None, None


def overview():
    db = get_db()
    days, since = _range()
    t = today()
    d0 = t - timedelta(days=days - 1)
    by_day = dict(db.execute("SELECT issue_date, COUNT(*) FROM loans WHERE issue_date >= ? GROUP BY issue_date", (since,)).fetchall())
    labels, values = [], []
    step = 1 if days <= 30 else 7
    d = d0
    while d <= t:
        span = [d + timedelta(days=i) for i in range(step) if d + timedelta(days=i) <= t]
        labels.append(d.strftime("%d %b"))
        values.append(sum(by_day.get(x.isoformat(), 0) for x in span))
        d += timedelta(days=step)
    q = lambda sql, *a: db.execute(sql, a).fetchone()[0]
    summary = {
        "issued": q("SELECT COUNT(*) FROM loans WHERE issue_date >= ?", since),
        "returned": q("SELECT COUNT(*) FROM loans WHERE return_date >= ? AND status='returned'", since),
        "late_returns": q("SELECT COUNT(*) FROM loans WHERE return_date >= ? AND return_date > due_date", since),
        "collected": q("SELECT COALESCE(SUM(amount),0) FROM fines WHERE status='paid' AND paid_at >= ?", since),
        "waived": q("SELECT COALESCE(SUM(amount),0) FROM fines WHERE status='waived' AND paid_at >= ?", since),
        "outstanding": q("SELECT COALESCE(SUM(amount),0) FROM fines WHERE status='unpaid'"),
        "active_members": q("SELECT COUNT(DISTINCT user_id) FROM loans WHERE issue_date >= ?", since),
        "holds_placed": q("SELECT COUNT(*) FROM holds WHERE placed_at >= ?", since),
    }
    cats = db.execute(
        """SELECT b.category, COUNT(*) n FROM loans l JOIN copies c ON c.id = l.copy_id JOIN books b ON b.id = c.book_id
           WHERE l.issue_date >= ? GROUP BY b.category ORDER BY n DESC""",
        (since,),
    ).fetchall()
    status = db.execute("SELECT status, COUNT(*) FROM copies GROUP BY status").fetchall()
    return {
        "summary": summary,
        "trend": {"labels": labels, "values": values},
        "cats": {"labels": [c[0] for c in cats], "values": [c[1] for c in cats]},
        "status": {"labels": [s[0].replace("_", " ") for s in status], "values": [s[1] for s in status]},
    }


@bp.route("/")
@staff_required
def index():
    tab = request.args.get("tab", "overview")
    if tab not in dict(TABS):
        tab = "overview"
    days, _ = _range()
    if tab == "overview":
        return render_template("reports/index.html", tabs=TABS, tab=tab, days=days, ov=overview())
    head, data, chart = build(tab)
    if request.args.get("export") == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(head)
        w.writerows(data)
        return Response(
            "\ufeff" + buf.getvalue(), mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=alms-{tab}-{today().isoformat()}.csv"},
        )
    return render_template("reports/index.html", tabs=TABS, tab=tab, days=days, head=head, data=data, chart=chart)
