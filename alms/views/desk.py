"""Librarian Circulation Desk (FR-04, FR-05, FR-06; Use Case 6.2; Sequence diagram)."""
from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from ..auth import staff_required
from ..db import get_db, today
from ..services import (
    CirculationError, cancel_hold, find_copy, find_member, issue_book, mark_lost, member_status,
    pay_fines, place_hold, renew_loan, return_book, waive_fine,
)

bp = Blueprint("desk", __name__, url_prefix="/desk")


def _back(default):
    nxt = request.form.get("next") or request.args.get("next")
    return redirect(nxt if nxt and nxt.startswith("/") and not nxt.startswith("//") else default)


@bp.route("/")
@staff_required
def index():
    return render_template(
        "desk/index.html",
        tab=request.args.get("tab", "issue"),
        member_code=request.args.get("member", ""),
        barcode=request.args.get("barcode", ""),
    )


@bp.route("/member-panel")
@staff_required
def member_panel():
    member = find_member(request.args.get("code", ""))
    if not member:
        return render_template("desk/_member_panel.html", status=None, code=request.args.get("code", ""))
    return render_template("desk/_member_panel.html", status=member_status(member["id"]))


@bp.route("/copy-info")
@staff_required
def copy_info():
    copy = find_copy(request.args.get("barcode", ""))
    if not copy:
        return jsonify(found=False)
    db = get_db()
    loan = db.execute(
        "SELECT l.due_date, u.name, u.member_code FROM loans l JOIN users u ON u.id = l.user_id WHERE l.copy_id = ? AND l.status = 'active'",
        (copy["id"],),
    ).fetchone()
    hold = db.execute(
        "SELECT u.name, u.member_code, h.expires_at FROM holds h JOIN users u ON u.id = h.user_id WHERE h.copy_id = ? AND h.status = 'ready'",
        (copy["id"],),
    ).fetchone()
    return jsonify(
        found=True, title=copy["title"], author=copy["author"], status=copy["status"], book_id=copy["book_id"],
        loan=dict(loan) if loan else None, hold=dict(hold) if hold else None,
    )


@bp.route("/issue", methods=["POST"])
@staff_required
def issue():
    code = request.form.get("member_code", "")
    barcode = request.form.get("barcode", "")
    try:
        loan_id = issue_book(code, barcode, g.user["id"])
    except CirculationError as e:
        flash(str(e), "danger")
        return redirect(url_for("desk.index", tab="issue", member=code, barcode=barcode))
    flash("Book issued successfully. Confirmation sent to the member via Email/SMS.", "success")
    return redirect(url_for("desk.slip", loan_id=loan_id))


@bp.route("/slip/<int:loan_id>")
@staff_required
def slip(loan_id):
    loan = get_db().execute(
        """SELECT l.*, u.name, u.member_code, u.department, b.title, b.author, b.isbn, c.barcode, s.name AS staff_name
           FROM loans l JOIN users u ON u.id = l.user_id JOIN copies c ON c.id = l.copy_id
           JOIN books b ON b.id = c.book_id LEFT JOIN users s ON s.id = l.issued_by WHERE l.id = ?""",
        (loan_id,),
    ).fetchone()
    if not loan:
        abort(404)
    return render_template("desk/slip.html", loan=loan)


@bp.route("/return", methods=["POST"])
@staff_required
def return_view():
    barcode = request.form.get("barcode", "")
    condition = request.form.get("condition", "good")
    try:
        result = return_book(barcode, g.user["id"], condition)
    except CirculationError as e:
        flash(str(e), "danger")
        return redirect(url_for("desk.index", tab="return", barcode=barcode))
    return render_template("desk/return_result.html", r=result, status=member_status(result["loan"]["user_id"]))


@bp.route("/renew/<int:loan_id>", methods=["POST"])
@staff_required
def renew(loan_id):
    try:
        new_due = renew_loan(loan_id, g.user["id"])
        flash(f"Loan renewed. New due date: {new_due.strftime('%d %b %Y')}.", "success")
    except CirculationError as e:
        flash(str(e), "danger")
    return _back(url_for("desk.loans"))


@bp.route("/lost/<int:loan_id>", methods=["POST"])
@staff_required
def lost(loan_id):
    try:
        mark_lost(loan_id, g.user["id"])
        flash("Book marked as lost and replacement charge added to the member's account.", "warning")
    except CirculationError as e:
        flash(str(e), "danger")
    return _back(url_for("desk.loans"))


@bp.route("/hold", methods=["POST"])
@staff_required
def hold():
    code = request.form.get("member_code", "")
    book_id = request.form.get("book_id", type=int)
    member = find_member(code)
    if not member:
        flash(f"No member found with ID '{code}'.", "danger")
        return _back(url_for("main.book_detail", book_id=book_id))
    try:
        hid, pos = place_hold(member["id"], book_id, g.user["id"])
    except CirculationError as e:
        flash(str(e), "danger")
        return _back(url_for("main.book_detail", book_id=book_id))
    flash(f"Hold placed for {member['name']} — position #{pos} in queue.", "success")
    return redirect(url_for("desk.hold_receipt", hold_id=hid))


@bp.route("/hold-receipt/<int:hold_id>")
@staff_required
def hold_receipt(hold_id):
    return _hold_receipt(hold_id)


def _hold_receipt(hold_id):
    from ..services import hold_position

    h = get_db().execute(
        """SELECT h.*, u.name, u.member_code, b.title, b.author, b.isbn FROM holds h JOIN users u ON u.id = h.user_id
           JOIN books b ON b.id = h.book_id WHERE h.id = ?""",
        (hold_id,),
    ).fetchone()
    if not h:
        abort(404)
    if g.user["role"] not in ("librarian", "admin") and h["user_id"] != g.user["id"]:
        abort(403)
    return render_template("desk/hold_receipt.html", h=h, position=hold_position(h))


@bp.route("/hold/<int:hold_id>/cancel", methods=["POST"])
@staff_required
def hold_cancel(hold_id):
    try:
        cancel_hold(hold_id, g.user["id"])
        flash("Hold cancelled.", "info")
    except CirculationError as e:
        flash(str(e), "danger")
    return _back(url_for("desk.holds"))


@bp.route("/loans")
@staff_required
def loans():
    db = get_db()
    flt = request.args.get("filter", "all")
    q = request.args.get("q", "").strip()
    sql = """SELECT l.*, u.name, u.member_code, b.title, b.id AS book_id, c.barcode FROM loans l
             JOIN users u ON u.id = l.user_id JOIN copies c ON c.id = l.copy_id JOIN books b ON b.id = c.book_id
             WHERE l.status = 'active'"""
    args = []
    t = today().isoformat()
    if flt == "overdue":
        sql += " AND l.due_date < ?"
        args.append(t)
    elif flt == "due_soon":
        sql += " AND l.due_date >= ? AND julianday(l.due_date) - julianday(?) <= 3"
        args += [t, t]
    if q:
        sql += " AND (u.name LIKE ? OR u.member_code LIKE ? OR b.title LIKE ? OR c.barcode LIKE ?)"
        args += [f"%{q}%"] * 4
    rows = db.execute(sql + " ORDER BY l.due_date", args).fetchall()
    from ..services import accrued_fine, overdue_days

    rows = [dict(r, overdue_days=overdue_days(r["due_date"]), accrued=accrued_fine(r)) for r in rows]
    return render_template("desk/loans.html", rows=rows, filter=flt, q=q)


@bp.route("/holds")
@staff_required
def holds():
    rows = get_db().execute(
        """SELECT h.*, u.name, u.member_code, b.title, c.barcode FROM holds h JOIN users u ON u.id = h.user_id
           JOIN books b ON b.id = h.book_id LEFT JOIN copies c ON c.id = h.copy_id
           WHERE h.status IN ('waiting','ready') ORDER BY h.status = 'waiting', b.title, h.placed_at, h.id"""
    ).fetchall()
    from ..services import hold_position

    rows = [dict(r, position=hold_position(r)) for r in rows]
    return render_template("desk/holds.html", rows=rows)


@bp.route("/fines/<int:user_id>")
@staff_required
def fines(user_id):
    status = member_status(user_id)
    if not status:
        abort(404)
    history = get_db().execute(
        "SELECT * FROM fines WHERE user_id = ? AND status != 'unpaid' ORDER BY COALESCE(paid_at, created_at) DESC", (user_id,)
    ).fetchall()
    return render_template("desk/fines.html", status=status, history=history)


@bp.route("/fines/<int:user_id>/pay", methods=["POST"])
@staff_required
def pay(user_id):
    ids = [int(x) for x in request.form.getlist("fine_id") if x.isdigit()]
    try:
        receipt = pay_fines(user_id, ids, "cash", g.user["id"])
    except CirculationError as e:
        flash(str(e), "danger")
        return redirect(url_for("desk.fines", user_id=user_id))
    flash(f"Payment recorded. Receipt {receipt} generated.", "success")
    return redirect(url_for("main.receipt", receipt_no=receipt))


@bp.route("/fines/waive/<int:fine_id>", methods=["POST"])
@staff_required
def waive(fine_id):
    fine = get_db().execute("SELECT user_id FROM fines WHERE id = ?", (fine_id,)).fetchone()
    if not fine:
        abort(404)
    try:
        waive_fine(fine_id, g.user["id"], request.form.get("note", "").strip())
        flash("Fine waived.", "info")
    except CirculationError as e:
        flash(str(e), "danger")
    return redirect(url_for("desk.fines", user_id=fine["user_id"]))
