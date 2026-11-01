import re

import pytest

from alms import create_app
from alms.db import get_db


@pytest.fixture
def app(tmp_path):
    app = create_app({"DATA_DIR": str(tmp_path), "TESTING": True})
    with app.app_context():
        yield app


@pytest.fixture
def db(app):
    return get_db()


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_from(client):
    html = client.get("/login").get_data(as_text=True)
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)


@pytest.fixture
def login(client):
    def _login(code, password="demo123"):
        with client.session_transaction() as s:
            s.clear()
        tok = csrf_from(client)
        resp = client.post("/login", data={"username": code, "password": password, "_csrf": tok})
        with client.session_transaction() as s:
            client.csrf = s.get("_csrf")
        return resp

    return _login


def uid(db, code):
    return db.execute("SELECT id FROM users WHERE member_code = ?", (code,)).fetchone()["id"]


def available_barcode(db, title):
    return db.execute(
        "SELECT c.barcode FROM copies c JOIN books b ON b.id = c.book_id WHERE b.title = ? AND c.status = 'available' LIMIT 1",
        (title,),
    ).fetchone()["barcode"]


def loaned_barcode(db, code, title):
    return db.execute(
        """SELECT c.barcode FROM loans l JOIN copies c ON c.id = l.copy_id JOIN books b ON b.id = c.book_id
           JOIN users u ON u.id = l.user_id WHERE u.member_code = ? AND b.title = ? AND l.status = 'active'""",
        (code, title),
    ).fetchone()["barcode"]
