from conftest import uid


def test_bcrypt_password_storage(db):
    h = db.execute("SELECT password_hash FROM users WHERE member_code='STU001'").fetchone()[0]
    assert h.startswith("$2b$") and "demo123" not in h


def test_login_and_role_redirects(client, login):
    assert login("STU001").headers["Location"].endswith("/me/")
    assert login("LIB001").headers["Location"].endswith("/dashboard")
    assert login("STU001", "wrong").status_code == 200


def test_rbac(client, login):
    login("STU001")
    assert client.get("/desk/").status_code == 403
    assert client.get("/admin/settings").status_code == 403
    login("LIB001")
    assert client.get("/desk/").status_code == 200
    assert client.get("/admin/settings").status_code == 403
    login("ADM001")
    assert client.get("/admin/settings").status_code == 200


def test_csrf_required(client, login):
    login("LIB001")
    assert client.post("/desk/issue", data={"member_code": "STU001", "barcode": "BC100001"}).status_code == 400


def test_issue_through_desk(client, login, db):
    login("LIB001")
    bc = db.execute("SELECT barcode FROM copies WHERE status='available' LIMIT 1").fetchone()[0]
    r = client.post("/desk/issue", data={"member_code": "STU006", "barcode": bc, "_csrf": client.csrf})
    assert r.status_code == 302 and "/desk/slip/" in r.headers["Location"]
    assert client.get(r.headers["Location"]).status_code == 200


def test_opac_search(client):
    html = client.get("/opac?q=Tagore&partial=1").get_data(as_text=True)
    assert "Gitanjali" in html and "Clean Code" not in html
    isbn = client.get("/opac?q=Gitanjali&partial=1").get_data(as_text=True)
    assert "1 result" in isbn


def test_member_online_payment(client, login, db):
    login("STU003")
    fid = db.execute("SELECT id FROM fines WHERE user_id=? AND status='unpaid'", (uid(db, "STU003"),)).fetchone()[0]
    r = client.post("/me/pay", data={"fine_id": fid, "method": "upi", "upi_id": "rohan@okaxis", "_csrf": client.csrf})
    assert r.status_code == 302 and "/receipt/" in r.headers["Location"]


def test_csv_export(client, login):
    login("ADM001")
    r = client.get("/reports/?tab=overdue&export=csv")
    assert r.mimetype == "text/csv" and "Days overdue" in r.get_data(as_text=True)


def test_backup_and_restore(client, login, db):
    login("ADM001")
    assert client.post("/admin/backup/create", data={"_csrf": client.csrf}).status_code == 302
    data = client.get("/admin/backup/download").data
    assert data[:15] == b"SQLite format 3"


def test_return_result_shows_title_and_barcode(client, login):
    login("LIB001")
    html = client.post("/desk/return", data={"barcode": "BC100001", "_csrf": client.csrf}).get_data(as_text=True)
    assert "Clean Code" in html and "BC100001" in html and "STU005" in html
