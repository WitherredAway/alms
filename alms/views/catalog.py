"""Catalog Management (FR-02) and inventory maintenance."""
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..auth import admin_required, staff_required
from ..db import get_db, now_ts
from ..services import allocate_free_copies, audit
from .main import categories, search_books

bp = Blueprint("catalog", __name__, url_prefix="/catalog")

FIELDS = ("isbn", "title", "author", "publisher", "year", "category", "shelf")


def next_barcode(db):
    row = db.execute("SELECT MAX(CAST(SUBSTR(barcode, 3) AS INTEGER)) FROM copies WHERE barcode LIKE 'BC%'").fetchone()
    return (row[0] or 100000) + 1


def add_copies(db, book_id, n):
    start = next_barcode(db)
    codes = []
    for i in range(n):
        code = f"BC{start + i}"
        db.execute("INSERT INTO copies(book_id, barcode, added_at) VALUES (?, ?, ?)", (book_id, code, now_ts()))
        codes.append(code)
    return codes


def validate(form, book_id=None):
    data = {k: (form.get(k) or "").strip() for k in FIELDS}
    errors = []
    data["isbn"] = re.sub(r"[\s-]", "", data["isbn"])
    if not re.fullmatch(r"\d{9}[\dXx]|\d{13}", data["isbn"]):
        errors.append("ISBN must be 10 or 13 digits.")
    if not data["title"]:
        errors.append("Title is required.")
    if not data["author"]:
        errors.append("Author is required.")
    if data["year"]:
        if not data["year"].isdigit() or not (1000 <= int(data["year"]) <= 2100):
            errors.append("Year must be a 4-digit number.")
    data["year"] = int(data["year"]) if data["year"].isdigit() else None
    dup = get_db().execute("SELECT id FROM books WHERE isbn = ? AND id IS NOT ?", (data["isbn"], book_id)).fetchone()
    if dup:
        errors.append("A book with this ISBN already exists.")
    return data, errors


@bp.route("/")
@staff_required
def index():
    q = request.args.get("q", "")
    cat = request.args.get("category", "")
    books = search_books(q, cat, limit=1000)
    return render_template("catalog/index.html", books=books, q=q, category=cat, categories=categories())


@bp.route("/new", methods=["GET", "POST"])
@staff_required
def new():
    db = get_db()
    if request.method == "POST":
        data, errors = validate(request.form)
        try:
            n = int(request.form.get("copies", "1"))
        except ValueError:
            n = 0
        if not 1 <= n <= 50:
            errors.append("Number of copies must be between 1 and 50.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("catalog/form.html", book=data, is_new=True, categories=categories(), copies=n)
        bid = db.execute(
            "INSERT INTO books(isbn, title, author, publisher, year, category, shelf, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (*[data[k] for k in FIELDS], now_ts()),
        ).lastrowid
        codes = add_copies(db, bid, n)
        audit("BOOK_ADD", f"'{data['title']}' ISBN {data['isbn']} with {n} copies ({codes[0]}–{codes[-1]})", g.user["id"])
        db.commit()
        flash(f"Added '{data['title']}' with {n} copies. Barcodes {codes[0]}–{codes[-1]} assigned.", "success")
        return redirect(url_for("main.book_detail", book_id=bid))
    return render_template("catalog/form.html", book={}, is_new=True, categories=categories(), copies=1)


@bp.route("/<int:book_id>/edit", methods=["GET", "POST"])
@staff_required
def edit(book_id):
    db = get_db()
    book = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if not book:
        abort(404)
    if request.method == "POST":
        data, errors = validate(request.form, book_id)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("catalog/form.html", book=dict(data, id=book_id), is_new=False, categories=categories())
        db.execute(
            "UPDATE books SET isbn=?, title=?, author=?, publisher=?, year=?, category=?, shelf=? WHERE id = ?",
            (*[data[k] for k in FIELDS], book_id),
        )
        audit("BOOK_EDIT", f"#{book_id} '{data['title']}'", g.user["id"])
        db.commit()
        flash("Book details updated.", "success")
        return redirect(url_for("main.book_detail", book_id=book_id))
    return render_template("catalog/form.html", book=book, is_new=False, categories=categories())


@bp.route("/<int:book_id>/copies", methods=["POST"])
@staff_required
def add_copies_view(book_id):
    db = get_db()
    book = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if not book:
        abort(404)
    try:
        n = int(request.form.get("n", "1"))
    except ValueError:
        n = 0
    if not 1 <= n <= 50:
        flash("Enter between 1 and 50 copies.", "danger")
        return redirect(url_for("main.book_detail", book_id=book_id))
    codes = add_copies(db, book_id, n)
    audit("COPY_ADD", f"'{book['title']}' +{n} ({', '.join(codes)})", g.user["id"])
    allocate_free_copies(book_id, g.user["id"])
    db.commit()
    flash(f"Added {n} copy/copies: {', '.join(codes)}.", "success")
    return redirect(url_for("main.book_detail", book_id=book_id))


@bp.route("/copy/<int:copy_id>/status", methods=["POST"])
@staff_required
def copy_status(copy_id):
    db = get_db()
    copy = db.execute(
        "SELECT c.*, b.title FROM copies c JOIN books b ON b.id = c.book_id WHERE c.id = ?", (copy_id,)
    ).fetchone()
    if not copy:
        abort(404)
    new = request.form.get("status")
    if new not in ("available", "damaged", "discarded", "lost"):
        abort(400)
    if copy["status"] in ("loaned", "on_hold"):
        flash("Copies that are on loan or on the hold shelf cannot be changed here. Return or cancel first.", "danger")
    else:
        db.execute("UPDATE copies SET status = ? WHERE id = ?", (new, copy_id))
        audit("COPY_STATUS", f"{copy['barcode']} '{copy['title']}' {copy['status']} → {new}", g.user["id"])
        if new == "available":
            allocate_free_copies(copy["book_id"], g.user["id"])
        db.commit()
        flash(f"Copy {copy['barcode']} marked as {new}.", "success")
    return redirect(url_for("main.book_detail", book_id=copy["book_id"]))


@bp.route("/<int:book_id>/delete", methods=["POST"])
@admin_required
def delete(book_id):
    db = get_db()
    book = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if not book:
        abort(404)
    used = db.execute(
        "SELECT COUNT(*) FROM loans l JOIN copies c ON c.id = l.copy_id WHERE c.book_id = ?", (book_id,)
    ).fetchone()[0]
    if used:
        flash("This title has circulation history and cannot be deleted. Mark its copies as discarded instead.", "danger")
        return redirect(url_for("main.book_detail", book_id=book_id))
    db.execute("DELETE FROM holds WHERE book_id = ?", (book_id,))
    db.execute("DELETE FROM copies WHERE book_id = ?", (book_id,))
    db.execute("DELETE FROM books WHERE id = ?", (book_id,))
    audit("BOOK_DELETE", f"'{book['title']}' ISBN {book['isbn']}", g.user["id"])
    db.commit()
    flash(f"Deleted '{book['title']}'.", "success")
    return redirect(url_for("catalog.index"))


@bp.route("/labels")
@staff_required
def labels():
    db = get_db()
    book_id = request.args.get("book", type=int)
    sql = "SELECT c.barcode, b.title, b.shelf FROM copies c JOIN books b ON b.id = c.book_id WHERE c.status NOT IN ('discarded','lost')"
    args = []
    if book_id:
        sql += " AND b.id = ?"
        args.append(book_id)
    rows = db.execute(sql + " ORDER BY c.barcode LIMIT 400", args).fetchall()
    return render_template("catalog/labels.html", rows=rows)
