from datetime import timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..auth import home_for, login_required, staff_required
from ..db import get_db, set_setting, setting_int, today
from ..services import STAFF_ROLES, audit, available_copies, hold_position

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    if g.user:
        return redirect(home_for(g.user))
    return redirect(url_for("auth.login"))


@bp.route("/dashboard")
@staff_required
def dashboard():
    db = get_db()
    t = today()
    q = lambda sql, *a: db.execute(sql, a).fetchone()[0]
    stats = {
        "titles": q("SELECT COUNT(*) FROM books"),
        "copies": q("SELECT COUNT(*) FROM copies WHERE status NOT IN ('discarded','lost')"),
        "available": q("SELECT COUNT(*) FROM copies WHERE status = 'available'"),
        "active": q("SELECT COUNT(*) FROM loans WHERE status = 'active'"),
        "overdue": q("SELECT COUNT(*) FROM loans WHERE status = 'active' AND due_date < ?", t.isoformat()),
        "holds_waiting": q("SELECT COUNT(*) FROM holds WHERE status = 'waiting'"),
        "holds_ready": q("SELECT COUNT(*) FROM holds WHERE status = 'ready'"),
        "members": q("SELECT COUNT(*) FROM users WHERE role IN ('student','faculty') AND active = 1"),
        "unpaid": q("SELECT COALESCE(SUM(amount),0) FROM fines WHERE status = 'unpaid'"),
        "issued_today": q("SELECT COUNT(*) FROM loans WHERE issue_date = ?", t.isoformat()),
        "returned_today": q("SELECT COUNT(*) FROM loans WHERE return_date = ?", t.isoformat()),
        "collected_30": q(
            "SELECT COALESCE(SUM(amount),0) FROM fines WHERE status = 'paid' AND paid_at >= ?",
            (t - timedelta(days=30)).isoformat(),
        ),
    }
    days = [t - timedelta(days=i) for i in range(29, -1, -1)]
    issued = dict(db.execute(
        "SELECT issue_date, COUNT(*) FROM loans WHERE issue_date >= ? GROUP BY issue_date", (days[0].isoformat(),)
    ).fetchall())
    returned = dict(db.execute(
        "SELECT return_date, COUNT(*) FROM loans WHERE return_date >= ? GROUP BY return_date", (days[0].isoformat(),)
    ).fetchall())
    trend = {
        "labels": [d.strftime("%d %b") for d in days],
        "issued": [issued.get(d.isoformat(), 0) for d in days],
        "returned": [returned.get(d.isoformat(), 0) for d in days],
    }
    cats = db.execute(
        """SELECT b.category, COUNT(*) n FROM loans l JOIN copies c ON c.id = l.copy_id JOIN books b ON b.id = c.book_id
           GROUP BY b.category ORDER BY n DESC"""
    ).fetchall()
    overdue = db.execute(
        """SELECT l.*, u.name, u.member_code, b.title, c.barcode FROM loans l JOIN users u ON u.id = l.user_id
           JOIN copies c ON c.id = l.copy_id JOIN books b ON b.id = c.book_id
           WHERE l.status = 'active' AND l.due_date < ? ORDER BY l.due_date LIMIT 8""",
        (t.isoformat(),),
    ).fetchall()
    ready = db.execute(
        """SELECT h.*, u.name, u.member_code, b.title, c.barcode FROM holds h JOIN users u ON u.id = h.user_id
           JOIN books b ON b.id = h.book_id LEFT JOIN copies c ON c.id = h.copy_id
           WHERE h.status = 'ready' ORDER BY h.expires_at"""
    ).fetchall()
    activity = db.execute(
        "SELECT a.*, u.name FROM audit_log a LEFT JOIN users u ON u.id = a.actor_id ORDER BY a.id DESC LIMIT 8"
    ).fetchall()
    return render_template(
        "dashboard.html", stats=stats, trend=trend, cats=[dict(c) for c in cats], overdue=overdue, ready=ready, activity=activity
    )


def search_books(qtext, category="", available_only=False, limit=200):
    db = get_db()
    sql = """SELECT b.*,
                SUM(CASE WHEN c.status = 'available' THEN 1 ELSE 0 END) AS available,
                SUM(CASE WHEN c.status IN ('available','loaned','on_hold') THEN 1 ELSE 0 END) AS total,
                (SELECT COUNT(*) FROM holds h WHERE h.book_id = b.id AND h.status = 'waiting') AS queue,
                (SELECT MIN(l.due_date) FROM loans l JOIN copies c2 ON c2.id = l.copy_id
                    WHERE c2.book_id = b.id AND l.status = 'active') AS next_due
             FROM books b LEFT JOIN copies c ON c.book_id = b.id WHERE 1=1"""
    args = []
    qtext = (qtext or "").strip()
    if qtext:
        like = f"%{qtext}%"
        digits = qtext.replace("-", "").replace(" ", "")
        sql += " AND (b.title LIKE ? OR b.author LIKE ? OR b.isbn LIKE ? OR b.publisher LIKE ?)"
        args += [like, like, f"%{digits}%", like]
    if category:
        sql += " AND b.category = ?"
        args.append(category)
    sql += " GROUP BY b.id"
    if available_only:
        sql += " HAVING available > 0"
    sql += " ORDER BY b.title LIMIT ?"
    args.append(limit)
    return db.execute(sql, args).fetchall()


def categories():
    return [r[0] for r in get_db().execute("SELECT DISTINCT category FROM books WHERE category IS NOT NULL ORDER BY 1")]


@bp.route("/opac")
def opac():
    q = request.args.get("q", "")
    cat = request.args.get("category", "")
    avail = request.args.get("available") == "1"
    books = search_books(q, cat, avail)
    if request.args.get("partial"):
        return render_template("opac/_results.html", books=books, q=q)
    return render_template("opac/search.html", books=books, q=q, category=cat, available=avail, categories=categories())


@bp.route("/book/<int:book_id>")
def book_detail(book_id):
    db = get_db()
    book = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if not book:
        abort(404)
    copies = db.execute(
        """SELECT c.*, l.due_date, l.id AS loan_id, u.name AS borrower, u.member_code AS borrower_code
           FROM copies c LEFT JOIN loans l ON l.copy_id = c.id AND l.status = 'active'
           LEFT JOIN users u ON u.id = l.user_id WHERE c.book_id = ? ORDER BY c.barcode""",
        (book_id,),
    ).fetchall()
    queue = db.execute(
        """SELECT h.*, u.name, u.member_code FROM holds h JOIN users u ON u.id = h.user_id
           WHERE h.book_id = ? AND h.status IN ('waiting','ready') ORDER BY h.status = 'waiting', h.placed_at, h.id""",
        (book_id,),
    ).fetchall()
    my_hold = my_loan = None
    if g.user:
        my_hold = db.execute(
            "SELECT * FROM holds WHERE book_id = ? AND user_id = ? AND status IN ('waiting','ready')", (book_id, g.user["id"])
        ).fetchone()
        if my_hold:
            my_hold = dict(my_hold, position=hold_position(my_hold))
        my_loan = db.execute(
            "SELECT l.* FROM loans l JOIN copies c ON c.id = l.copy_id WHERE c.book_id = ? AND l.user_id = ? AND l.status = 'active'",
            (book_id, g.user["id"]),
        ).fetchone()
    history_count = db.execute(
        "SELECT COUNT(*) FROM loans l JOIN copies c ON c.id = l.copy_id WHERE c.book_id = ?", (book_id,)
    ).fetchone()[0]
    return render_template(
        "opac/book.html", book=book, copies=copies, queue=queue, available=available_copies(book_id),
        my_hold=my_hold, my_loan=my_loan, history_count=history_count,
    )


@bp.route("/notifications")
@login_required
def notifications():
    db = get_db()
    channel = request.args.get("channel", "")
    staff = g.user["role"] in STAFF_ROLES
    scope = request.args.get("scope", "all" if staff else "mine")
    sql = "SELECT n.*, u.name, u.member_code, u.email, u.phone FROM notifications n JOIN users u ON u.id = n.user_id WHERE 1=1"
    args = []
    if not staff or scope == "mine":
        sql += " AND n.user_id = ?"
        args.append(g.user["id"])
    if channel:
        sql += " AND n.channel = ?"
        args.append(channel)
    rows = db.execute(sql + " ORDER BY n.id DESC LIMIT 300", args).fetchall()
    db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0", (g.user["id"],))
    db.commit()
    return render_template("notifications.html", rows=rows, channel=channel, scope=scope, staff=staff)


@bp.route("/receipt/<receipt_no>")
@login_required
def receipt(receipt_no):
    db = get_db()
    fines = db.execute(
        """SELECT f.*, u.name, u.member_code, s.name AS staff_name FROM fines f JOIN users u ON u.id = f.user_id
           LEFT JOIN users s ON s.id = f.handled_by WHERE f.receipt_no = ?""",
        (receipt_no,),
    ).fetchall()
    if not fines:
        abort(404)
    if g.user["role"] not in STAFF_ROLES and fines[0]["user_id"] != g.user["id"]:
        abort(403)
    return render_template("receipt.html", fines=fines, receipt_no=receipt_no, total=sum(f["amount"] for f in fines))


@bp.route("/simulate-date", methods=["POST"])
@staff_required
def simulate_date():
    action = request.form.get("action")
    offset = setting_int("date_offset")
    if action == "reset":
        offset = 0
    else:
        try:
            offset += int(request.form.get("days", "0"))
        except ValueError:
            pass
    offset = max(0, min(offset, 3650))
    db = get_db()
    set_setting("date_offset", offset)
    audit("SIMULATE_DATE", f"Offset set to +{offset} day(s)", g.user["id"])
    db.commit()
    from ..services import daily_sweep

    daily_sweep()
    flash(
        f"System date is now {today().strftime('%d %b %Y')}" + (f" (simulated +{offset} days)." if offset else " (real date)."),
        "info",
    )
    nxt = request.form.get("next") or url_for("main.dashboard")
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("main.dashboard"))
