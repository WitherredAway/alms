"""Database backup & restore (NFR-03, Admin use case 'Backup & Restore System Database')."""
import os
import shutil
import sqlite3
import tempfile

from flask import current_app

from .db import today

KEEP_DAILY = 7


def backup_dir():
    d = current_app.config.get("BACKUP_DIR") or os.path.join(os.path.dirname(current_app.config["DATABASE"]), "backups")
    os.makedirs(d, exist_ok=True)
    return d


def snapshot_to(path):
    src = sqlite3.connect(current_app.config["DATABASE"])
    dst = sqlite3.connect(path)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()


def automatic_backup():
    path = os.path.join(backup_dir(), f"alms-auto-{today().isoformat()}.db")
    if not os.path.exists(path):
        snapshot_to(path)
    autos = sorted(f for f in os.listdir(backup_dir()) if f.startswith("alms-auto-"))
    for old in autos[:-KEEP_DAILY]:
        os.remove(os.path.join(backup_dir(), old))


def list_backups():
    d = backup_dir()
    out = []
    for f in sorted(os.listdir(d), reverse=True):
        if f.endswith(".db"):
            p = os.path.join(d, f)
            out.append({"name": f, "size_kb": round(os.path.getsize(p) / 1024, 1), "mtime": os.path.getmtime(p)})
    return out


def make_download_copy():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    snapshot_to(path)
    return path


def restore_from(path):
    """Replace the live database with the uploaded/selected file (validated by caller)."""
    # Safety snapshot before overwriting.
    snapshot_to(os.path.join(backup_dir(), f"alms-pre-restore-{today().isoformat()}.db"))
    src = sqlite3.connect(path)
    dst = sqlite3.connect(current_app.config["DATABASE"])
    with dst:
        src.backup(dst)
    src.close()
    dst.close()


def copy_named_backup(name):
    safe = os.path.basename(name)
    p = os.path.join(backup_dir(), safe)
    if not os.path.isfile(p):
        return None
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    shutil.copyfile(p, tmp)
    return tmp
