import os
import sqlite3
from datetime import date, datetime, timedelta

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    member_code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    department TEXT,
    role TEXT NOT NULL CHECK (role IN ('student','faculty','librarian','admin')),
    password_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY,
    isbn TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    publisher TEXT,
    year INTEGER,
    category TEXT,
    shelf TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_books_title ON books(title);
CREATE INDEX IF NOT EXISTS idx_books_author ON books(author);
CREATE TABLE IF NOT EXISTS copies (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    barcode TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'available'
        CHECK (status IN ('available','loaned','on_hold','damaged','lost','discarded')),
    added_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_copies_book ON copies(book_id);
CREATE TABLE IF NOT EXISTS loans (
    id INTEGER PRIMARY KEY,
    copy_id INTEGER NOT NULL REFERENCES copies(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    issued_by INTEGER REFERENCES users(id),
    issue_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    return_date TEXT,
    renewals INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','returned','lost'))
);
CREATE INDEX IF NOT EXISTS idx_loans_user ON loans(user_id, status);
CREATE INDEX IF NOT EXISTS idx_loans_copy ON loans(copy_id, status);
CREATE TABLE IF NOT EXISTS holds (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    placed_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'waiting'
        CHECK (status IN ('waiting','ready','fulfilled','cancelled','expired')),
    copy_id INTEGER REFERENCES copies(id),
    ready_at TEXT,
    expires_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_holds_book ON holds(book_id, status);
CREATE TABLE IF NOT EXISTS fines (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    loan_id INTEGER REFERENCES loans(id),
    amount REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unpaid' CHECK (status IN ('unpaid','paid','waived')),
    paid_at TEXT,
    method TEXT,
    receipt_no TEXT,
    handled_by INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_fines_user ON fines(user_id, status);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    channel TEXT NOT NULL CHECK (channel IN ('email','sms','app')),
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    ref TEXT,
    created_at TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_notif_ref ON notifications(ref);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    actor_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    details TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "library_name": "Central Library",
    "fine_per_day": "5",
    "loan_days": "14",
    "max_renewals": "1",
    "quota_student": "3",
    "quota_faculty": "5",
    "hold_pickup_days": "3",
    "lost_book_fee": "500",
    "date_offset": "0",
    "last_sweep": "",
    "show_demo_logins": "1",
}

REQUIRED_TABLES = {"users", "books", "copies", "loans", "holds", "fines", "notifications", "audit_log", "settings"}


def connect(path):
    conn = sqlite3.connect(path, detect_types=0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_schema(conn):
    conn.executescript(SCHEMA)
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    conn.commit()


def is_valid_alms_db(path):
    try:
        conn = sqlite3.connect(path)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        return REQUIRED_TABLES.issubset(names)
    except sqlite3.DatabaseError:
        return False


def setting(key, db=None):
    db = db or get_db()
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key)


def setting_int(key, db=None):
    return int(float(setting(key, db)))


def setting_float(key, db=None):
    return float(setting(key, db))


def set_setting(key, value, db=None):
    db = db or get_db()
    db.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def today(db=None):
    return date.today() + timedelta(days=setting_int("date_offset", db))


def now_ts(db=None):
    t = datetime.now().time().replace(microsecond=0)
    return f"{today(db).isoformat()} {t.isoformat()}"


def parse_date(s):
    return date.fromisoformat(s[:10])


def db_path_dir():
    return os.path.dirname(current_app.config["DATABASE"])
