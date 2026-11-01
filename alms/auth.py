"""Authentication & Role-Based Access Control (FR-01, NFR-02)."""
import functools
import secrets

import bcrypt
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from .db import get_db
from .services import audit

bp = Blueprint("auth", __name__)


def hash_password(pw):
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=10)).decode()


def check_password(pw, hashed):
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def login_required(view):
    @functools.wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.full_path))
        return view(*a, **kw)

    return wrapped


def roles_required(*roles):
    def deco(view):
        @functools.wraps(view)
        @login_required
        def wrapped(*a, **kw):
            if g.user["role"] not in roles:
                abort(403)
            return view(*a, **kw)

        return wrapped

    return deco


staff_required = roles_required("librarian", "admin")
admin_required = roles_required("admin")
member_required = roles_required("student", "faculty")


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def load_user():
    uid = session.get("uid")
    g.user = None
    if uid:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ? AND active = 1", (uid,)).fetchone()
        if g.user is None:
            session.clear()


def check_csrf():
    if request.method == "POST":
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
        if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
            abort(400, "Invalid or missing CSRF token. Please reload the page and try again.")


def home_for(user):
    if user["role"] in ("librarian", "admin"):
        return url_for("main.dashboard")
    return url_for("member.home")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(home_for(g.user))
    db = get_db()
    if request.method == "POST":
        ident = request.form.get("username", "").strip()
        pw = request.form.get("password", "")
        user = db.execute(
            "SELECT * FROM users WHERE UPPER(member_code) = UPPER(?) OR LOWER(email) = LOWER(?)", (ident, ident)
        ).fetchone()
        if user and check_password(pw, user["password_hash"]):
            if not user["active"]:
                flash("This account has been deactivated. Please contact the library.", "danger")
            else:
                session.clear()
                session["uid"] = user["id"]
                csrf_token()
                audit("LOGIN", f"{user['member_code']} ({user['role']})", user["id"])
                db.commit()
                nxt = request.args.get("next", "")
                if nxt.startswith("/") and not nxt.startswith("//") and not nxt.startswith("/login"):
                    return redirect(nxt)
                return redirect(home_for(user))
        else:
            audit("LOGIN_FAILED", f"identifier '{ident[:40]}'")
            db.commit()
            flash("Invalid user ID / email or password.", "danger")
    demo = None
    if db.execute("SELECT value FROM settings WHERE key='show_demo_logins'").fetchone()["value"] == "1":
        demo = db.execute(
            """SELECT member_code, name, role FROM users WHERE member_code IN
               ('ADM001','LIB001','STU001','STU002','STU003','STU004','STU005','FAC001') ORDER BY
               CASE role WHEN 'admin' THEN 0 WHEN 'librarian' THEN 1 WHEN 'faculty' THEN 3 ELSE 2 END, member_code"""
        ).fetchall()
    return render_template("login.html", demo=demo)


@bp.route("/logout", methods=["POST"])
def logout():
    if g.user:
        audit("LOGOUT", g.user["member_code"], g.user["id"])
        get_db().commit()
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "details":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip()
            phone = request.form.get("phone", "").strip()
            if not name:
                flash("Name is required.", "danger")
            else:
                db.execute("UPDATE users SET name = ?, email = ?, phone = ? WHERE id = ?", (name, email, phone, g.user["id"]))
                audit("PROFILE_UPDATE", g.user["member_code"], g.user["id"])
                db.commit()
                flash("Profile updated.", "success")
        elif action == "password":
            cur, new, confirm = (request.form.get(k, "") for k in ("current", "new", "confirm"))
            if not check_password(cur, g.user["password_hash"]):
                flash("Current password is incorrect.", "danger")
            elif len(new) < 6:
                flash("New password must be at least 6 characters.", "danger")
            elif new != confirm:
                flash("New passwords do not match.", "danger")
            else:
                db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new), g.user["id"]))
                audit("PASSWORD_CHANGE", g.user["member_code"], g.user["id"])
                db.commit()
                flash("Password changed.", "success")
        return redirect(url_for("auth.profile"))
    return render_template("profile.html")
