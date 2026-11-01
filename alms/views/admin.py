"""Administrator module (Use Case 6.3): members, settings, audit, backup & restore."""
import os
import re
import secrets
import tempfile

from flask import Blueprint, abort, after_this_request, flash, g, redirect, render_template, request, send_file, url_for

from .. import backup as bk
from ..auth import admin_required, hash_password, staff_required
from ..db import DEFAULT_SETTINGS, get_db, is_valid_alms_db, now_ts, set_setting, setting, today
from ..services import MEMBER_ROLES, audit, member_status

bp = Blueprint("admin", __name__)

ROLE_PREFIX = {"student": "STU", "faculty": "FAC", "librarian": "LIB", "admin": "ADM"}


def next_code(db, role):
    pre = ROLE_PREFIX[role]
    rows = db.execute("SELECT member_code FROM users WHERE member_code LIKE ?", (pre + "%",)).fetchall()
    nums = [int(r[0][3:]) for r in rows if r[0][3:].isdigit()]
    return f"{pre}{(max(nums) + 1 if nums else 1):03d}"


def allowed_roles():
    return ("student", "faculty", "librarian", "admin") if g.user["role"] == "admin" else MEMBER_ROLES


@bp.route("/members")
@staff_required
def members():
    db = get_db()
    q = request.args.get("q", "").strip()
    role = request.args.get("role", "")
    sql = """SELECT u.*,
                (SELECT COUNT(*) FROM loans l WHERE l.user_id = u.id AND l.status = 'active') AS active_loans,
                (SELECT COUNT(*) FROM loans l WHERE l.user_id = u.id AND l.status = 'active' AND l.due_date < ?) AS overdue,
                (SELECT COALESCE(SUM(amount),0) FROM fines f WHERE f.user_id = u.id AND f.status = 'unpaid') AS unpaid
             FROM users u WHERE 1=1"""
    args = [today().isoformat()]
    if q:
        sql += " AND (u.name LIKE ? OR u.member_code LIKE ? OR u.email LIKE ? OR u.phone LIKE ?)"
        args += [f"%{q}%"] * 4
    if role:
        sql += " AND u.role = ?"
        args.append(role)
    rows = db.execute(sql + " ORDER BY CASE u.role WHEN 'admin' THEN 0 WHEN 'librarian' THEN 1 WHEN 'faculty' THEN 2 ELSE 3 END, u.member_code", args).fetchall()
    return render_template("admin/members.html", rows=rows, q=q, role=role)


def _validate_user(form, user_id=None):
    data = {k: (form.get(k) or "").strip() for k in ("name", "email", "phone", "department", "role")}
    errors = []
    if not data["name"]:
        errors.append("Name is required.")
    if data["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", data["email"]):
        errors.append("Email address looks invalid.")
    if data["role"] not in allowed_roles():
        errors.append("You are not allowed to assign that role.")
    if data["email"] and get_db().execute(
        "SELECT 1 FROM users WHERE LOWER(email) = LOWER(?) AND id IS NOT ?", (data["email"], user_id)
    ).fetchone():
        errors.append("Another account already uses this email.")
    return data, errors


@bp.route("/members/new", methods=["GET", "POST"])
@staff_required
def member_new():
    db = get_db()
    if request.method == "POST":
        data, errors = _validate_user(request.form)
        pw = request.form.get("password", "").strip()
        if pw and len(pw) < 6:
            errors.append("Password must be at least 6 characters.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("admin/member_form.html", u=data, is_new=True, roles=allowed_roles())
        pw = pw or secrets.token_urlsafe(6)
        code = next_code(db, data["role"])
        uid = db.execute(
            "INSERT INTO users(member_code, name, email, phone, department, role, password_hash, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (code, data["name"], data["email"], data["phone"], data["department"], data["role"], hash_password(pw), now_ts()),
        ).lastrowid
        audit("MEMBER_ADD", f"{code} {data['name']} ({data['role']})", g.user["id"])
        db.commit()
        flash(f"Account created. Member ID: {code} · Temporary password: {pw}", "success")
        return redirect(url_for("admin.member_detail", user_id=uid))
    return render_template("admin/member_form.html", u={"role": "student"}, is_new=True, roles=allowed_roles())


def _load_editable(user_id):
    u = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not u:
        abort(404)
    if u["role"] not in allowed_roles():
        abort(403)
    return u


@bp.route("/members/<int:user_id>")
@staff_required
def member_detail(user_id):
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not u:
        abort(404)
    history = db.execute(
        """SELECT l.*, b.title, b.id AS book_id, c.barcode FROM loans l JOIN copies c ON c.id = l.copy_id
           JOIN books b ON b.id = c.book_id WHERE l.user_id = ? AND l.status != 'active' ORDER BY l.issue_date DESC LIMIT 50""",
        (user_id,),
    ).fetchall()
    return render_template(
        "admin/member_detail.html", u=u, status=member_status(user_id), history=history,
        editable=u["role"] in allowed_roles(),
    )


@bp.route("/members/<int:user_id>/edit", methods=["GET", "POST"])
@staff_required
def member_edit(user_id):
    u = _load_editable(user_id)
    db = get_db()
    if request.method == "POST":
        data, errors = _validate_user(request.form, user_id)
        if u["id"] == g.user["id"] and data["role"] != u["role"]:
            errors.append("You cannot change your own role.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("admin/member_form.html", u=dict(data, id=user_id, member_code=u["member_code"]), is_new=False, roles=allowed_roles())
        db.execute(
            "UPDATE users SET name=?, email=?, phone=?, department=?, role=? WHERE id = ?",
            (data["name"], data["email"], data["phone"], data["department"], data["role"], user_id),
        )
        audit("MEMBER_EDIT", f"{u['member_code']} {data['name']}", g.user["id"])
        db.commit()
        flash("Account updated.", "success")
        return redirect(url_for("admin.member_detail", user_id=user_id))
    return render_template("admin/member_form.html", u=u, is_new=False, roles=allowed_roles())


@bp.route("/members/<int:user_id>/toggle", methods=["POST"])
@staff_required
def member_toggle(user_id):
    u = _load_editable(user_id)
    if u["id"] == g.user["id"]:
        flash("You cannot deactivate your own account.", "danger")
        return redirect(url_for("admin.member_detail", user_id=user_id))
    db = get_db()
    db.execute("UPDATE users SET active = ? WHERE id = ?", (0 if u["active"] else 1, user_id))
    audit("MEMBER_" + ("DEACTIVATE" if u["active"] else "ACTIVATE"), u["member_code"], g.user["id"])
    db.commit()
    flash(f"Account {'deactivated' if u['active'] else 'reactivated'}.", "info")
    return redirect(url_for("admin.member_detail", user_id=user_id))


@bp.route("/members/<int:user_id>/reset-password", methods=["POST"])
@staff_required
def member_reset_password(user_id):
    u = _load_editable(user_id)
    pw = secrets.token_urlsafe(6)
    db = get_db()
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(pw), user_id))
    audit("PASSWORD_RESET", u["member_code"], g.user["id"])
    db.commit()
    flash(f"Temporary password for {u['member_code']}: {pw}", "warning")
    return redirect(url_for("admin.member_detail", user_id=user_id))


SETTINGS_FORM = [
    ("library_name", "Library name", "text", None),
    ("fine_per_day", "Overdue fine per day (₹)", "number", (0, 1000)),
    ("loan_days", "Loan period (days)", "number", (1, 120)),
    ("max_renewals", "Max renewals per loan", "number", (0, 10)),
    ("quota_student", "Borrowing quota — students", "number", (1, 50)),
    ("quota_faculty", "Borrowing quota — faculty", "number", (1, 50)),
    ("hold_pickup_days", "Hold pickup window (days)", "number", (1, 30)),
    ("lost_book_fee", "Lost book replacement fee (₹)", "number", (0, 100000)),
]


@bp.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def settings():
    db = get_db()
    if request.method == "POST":
        errors = []
        changes = []
        for key, label, kind, rng in SETTINGS_FORM:
            val = request.form.get(key, "").strip()
            if kind == "number":
                try:
                    num = float(val)
                except ValueError:
                    errors.append(f"{label}: must be a number.")
                    continue
                if not rng[0] <= num <= rng[1]:
                    errors.append(f"{label}: must be between {rng[0]} and {rng[1]}.")
                    continue
                val = f"{num:g}"
            elif not val:
                errors.append(f"{label}: required.")
                continue
            if val != setting(key):
                changes.append(f"{key}: {setting(key)} → {val}")
                set_setting(key, val)
        set_setting("show_demo_logins", "1" if request.form.get("show_demo_logins") else "0")
        if errors:
            db.rollback()
            for e in errors:
                flash(e, "danger")
        else:
            if changes:
                audit("SETTINGS", "; ".join(changes), g.user["id"])
            db.commit()
            flash("Settings saved." if changes else "No changes.", "success")
        return redirect(url_for("admin.settings"))
    values = {k: setting(k) for k in DEFAULT_SETTINGS}
    return render_template("admin/settings.html", form=SETTINGS_FORM, values=values)


@bp.route("/admin/audit")
@staff_required
def audit_log():
    db = get_db()
    action = request.args.get("action", "")
    q = request.args.get("q", "").strip()
    sql = "SELECT a.*, u.name, u.member_code FROM audit_log a LEFT JOIN users u ON u.id = a.actor_id WHERE 1=1"
    args = []
    if action:
        sql += " AND a.action = ?"
        args.append(action)
    if q:
        sql += " AND (a.details LIKE ? OR u.name LIKE ?)"
        args += [f"%{q}%"] * 2
    rows = db.execute(sql + " ORDER BY a.id DESC LIMIT 500", args).fetchall()
    actions = [r[0] for r in db.execute("SELECT DISTINCT action FROM audit_log ORDER BY 1")]
    return render_template("admin/audit.html", rows=rows, actions=actions, action=action, q=q)


@bp.route("/admin/backup")
@admin_required
def backup():
    return render_template("admin/backup.html", backups=bk.list_backups(), backup_dir=bk.backup_dir())


def _send_temp(path, name):
    @after_this_request
    def _cleanup(resp):
        try:
            os.remove(path)
        except OSError:
            pass
        return resp

    return send_file(path, as_attachment=True, download_name=name, mimetype="application/x-sqlite3")


@bp.route("/admin/backup/download")
@admin_required
def backup_download():
    name = request.args.get("name")
    if name:
        path = bk.copy_named_backup(name)
        if not path:
            abort(404)
        return _send_temp(path, os.path.basename(name))
    path = bk.make_download_copy()
    audit("BACKUP_DOWNLOAD", "", g.user["id"])
    get_db().commit()
    return _send_temp(path, f"alms-backup-{today().isoformat()}.db")


@bp.route("/admin/backup/create", methods=["POST"])
@admin_required
def backup_create():
    name = f"alms-manual-{today().isoformat()}-{secrets.token_hex(2)}.db"
    get_db().commit()
    bk.snapshot_to(os.path.join(bk.backup_dir(), name))
    audit("BACKUP_CREATE", name, g.user["id"])
    get_db().commit()
    flash(f"Backup {name} created.", "success")
    return redirect(url_for("admin.backup"))


@bp.route("/admin/backup/restore", methods=["POST"])
@admin_required
def backup_restore():
    from ..db import close_db

    name = request.form.get("name")
    tmp = None
    if name:
        tmp = bk.copy_named_backup(name)
        if not tmp:
            abort(404)
    else:
        f = request.files.get("file")
        if not f or not f.filename:
            flash("Choose a backup file to restore.", "danger")
            return redirect(url_for("admin.backup"))
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        f.save(tmp)
    try:
        if not is_valid_alms_db(tmp):
            flash("That file is not a valid ALMS database backup.", "danger")
            return redirect(url_for("admin.backup"))
        actor = g.user["member_code"]
        close_db()
        bk.restore_from(tmp)
    finally:
        os.remove(tmp)
    db = get_db()
    audit("BACKUP_RESTORE", f"Restored {'from ' + name if name else 'from uploaded file'} by {actor}")
    db.commit()
    flash("Database restored successfully. Please sign in again if your account changed.", "success")
    return redirect(url_for("admin.backup"))


@bp.route("/admin/reset-demo", methods=["POST"])
@admin_required
def reset_demo():
    from ..seed import seed_demo

    seed_demo()
    from flask import session

    session.clear()
    flash("Demo data has been reset. Sign in again (all demo passwords: demo123).", "info")
    return redirect(url_for("auth.login"))
