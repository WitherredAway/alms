"""Student / Member self-service portal (Use Case 6.1)."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..auth import login_required, member_required
from ..db import get_db
from ..services import CirculationError, cancel_hold, member_status, pay_fines, place_hold, renew_loan

bp = Blueprint("member", __name__, url_prefix="/me")


@bp.route("/")
@member_required
def home():
    db = get_db()
    notes = db.execute(
        "SELECT * FROM notifications WHERE user_id = ? AND channel = 'email' ORDER BY id DESC LIMIT 5", (g.user["id"],)
    ).fetchall()
    return render_template("member/home.html", status=member_status(g.user["id"]), notes=notes)


@bp.route("/history")
@member_required
def history():
    rows = get_db().execute(
        """SELECT l.*, b.title, b.author, b.id AS book_id, c.barcode,
                  (SELECT SUM(amount) FROM fines f WHERE f.loan_id = l.id) AS fine
           FROM loans l JOIN copies c ON c.id = l.copy_id JOIN books b ON b.id = c.book_id
           WHERE l.user_id = ? ORDER BY l.issue_date DESC, l.id DESC""",
        (g.user["id"],),
    ).fetchall()
    fines = get_db().execute("SELECT * FROM fines WHERE user_id = ? ORDER BY created_at DESC", (g.user["id"],)).fetchall()
    return render_template("member/history.html", rows=rows, fines=fines)


@bp.route("/renew/<int:loan_id>", methods=["POST"])
@member_required
def renew(loan_id):
    loan = get_db().execute("SELECT user_id FROM loans WHERE id = ?", (loan_id,)).fetchone()
    if not loan or loan["user_id"] != g.user["id"]:
        abort(403)
    try:
        new_due = renew_loan(loan_id, g.user["id"])
        flash(f"Renewed! New due date: {new_due.strftime('%d %b %Y')}.", "success")
    except CirculationError as e:
        flash(str(e), "danger")
    return redirect(url_for("member.home"))


@bp.route("/hold/<int:book_id>", methods=["POST"])
@member_required
def hold(book_id):
    try:
        hid, pos = place_hold(g.user["id"], book_id, g.user["id"])
        flash(f"Hold placed — you are #{pos} in the queue. We'll notify you by Email/SMS when it's ready.", "success")
        return redirect(url_for("member.hold_receipt", hold_id=hid))
    except CirculationError as e:
        flash(str(e), "danger")
    return redirect(url_for("main.book_detail", book_id=book_id))


@bp.route("/hold-receipt/<int:hold_id>")
@member_required
def hold_receipt(hold_id):
    from .desk import _hold_receipt

    return _hold_receipt(hold_id)


@bp.route("/hold/<int:hold_id>/cancel", methods=["POST"])
@member_required
def hold_cancel(hold_id):
    h = get_db().execute("SELECT user_id FROM holds WHERE id = ?", (hold_id,)).fetchone()
    if not h or h["user_id"] != g.user["id"]:
        abort(403)
    try:
        cancel_hold(hold_id, g.user["id"])
        flash("Hold cancelled.", "info")
    except CirculationError as e:
        flash(str(e), "danger")
    return redirect(url_for("member.home"))


@bp.route("/pay", methods=["GET", "POST"])
@member_required
def pay():
    status = member_status(g.user["id"])
    if request.method == "POST":
        ids = [int(x) for x in request.form.getlist("fine_id") if x.isdigit()]
        method = request.form.get("method", "upi")
        ref = request.form.get("upi_id", "").strip() if method == "upi" else request.form.get("card", "")[-4:]
        if method == "upi" and "@" not in ref:
            flash("Enter a valid UPI ID (e.g. name@okaxis).", "danger")
            return render_template("member/pay.html", status=status)
        if method == "card" and not (ref.isdigit() and len(ref) == 4):
            flash("Enter a valid card number.", "danger")
            return render_template("member/pay.html", status=status)
        label = "online (UPI)" if method == "upi" else "online (card)"
        try:
            receipt = pay_fines(g.user["id"], ids, label, g.user["id"], ref if method == "upi" else f"card ••••{ref}")
        except CirculationError as e:
            flash(str(e), "danger")
            return redirect(url_for("member.pay"))
        flash("Payment successful (simulated gateway).", "success")
        return redirect(url_for("main.receipt", receipt_no=receipt))
    return render_template("member/pay.html", status=status)


@bp.route("/card")
@login_required
def card():
    return render_template("member/card.html", user=g.user)
