"""Demo dataset. All dates are relative to the (simulated) current date so the demo always looks fresh."""
import random
from datetime import timedelta

from .auth import hash_password
from .db import DEFAULT_SETTINGS, get_db, set_setting, today

DEMO_PASSWORD = "demo123"

BOOKS = [
    # title, author, publisher, year, category, copies
    ("Clean Code", "Robert C. Martin", "Prentice Hall", 2008, "Computer Science", 1),
    ("Introduction to Algorithms", "Thomas H. Cormen et al.", "MIT Press", 2009, "Computer Science", 4),
    ("Design Patterns", "Erich Gamma et al.", "Addison-Wesley", 1994, "Computer Science", 2),
    ("The Pragmatic Programmer", "Andrew Hunt, David Thomas", "Addison-Wesley", 2019, "Computer Science", 2),
    ("Operating System Concepts", "Abraham Silberschatz", "Wiley", 2018, "Computer Science", 3),
    ("Computer Networks", "Andrew S. Tanenbaum", "Pearson", 2010, "Computer Science", 3),
    ("Database System Concepts", "Abraham Silberschatz", "McGraw-Hill", 2019, "Computer Science", 3),
    ("Software Engineering: A Practitioner's Approach", "Roger S. Pressman", "McGraw-Hill", 2014, "Computer Science", 4),
    ("Artificial Intelligence: A Modern Approach", "Stuart Russell, Peter Norvig", "Pearson", 2020, "Computer Science", 2),
    ("Let Us C", "Yashavant Kanetkar", "BPB Publications", 2020, "Computer Science", 5),
    ("Head First Java", "Kathy Sierra, Bert Bates", "O'Reilly", 2005, "Computer Science", 3),
    ("Python Crash Course", "Eric Matthes", "No Starch Press", 2019, "Computer Science", 3),
    ("Structure and Interpretation of Computer Programs", "Harold Abelson, Gerald Sussman", "MIT Press", 1996, "Computer Science", 1),
    ("The C Programming Language", "Brian Kernighan, Dennis Ritchie", "Prentice Hall", 1988, "Computer Science", 2),
    ("Computer Organization and Design", "David Patterson, John Hennessy", "Morgan Kaufmann", 2013, "Computer Science", 2),
    ("Higher Engineering Mathematics", "B.S. Grewal", "Khanna Publishers", 2017, "Mathematics", 6),
    ("Advanced Engineering Mathematics", "Erwin Kreyszig", "Wiley", 2011, "Mathematics", 3),
    ("Discrete Mathematics and Its Applications", "Kenneth H. Rosen", "McGraw-Hill", 2018, "Mathematics", 3),
    ("Linear Algebra Done Right", "Sheldon Axler", "Springer", 2015, "Mathematics", 2),
    ("Probability and Statistics for Engineers", "Ronald E. Walpole", "Pearson", 2016, "Mathematics", 2),
    ("Concepts of Physics Vol. 1", "H.C. Verma", "Bharati Bhawan", 2019, "Physics", 5),
    ("Fundamentals of Physics", "David Halliday, Robert Resnick", "Wiley", 2013, "Physics", 3),
    ("A Brief History of Time", "Stephen Hawking", "Bantam", 1988, "Physics", 2),
    ("The Feynman Lectures on Physics", "Richard Feynman", "Basic Books", 2011, "Physics", 1),
    ("Engineering Chemistry", "Jain & Jain", "Dhanpat Rai", 2015, "Chemistry", 4),
    ("Organic Chemistry", "Paula Bruice", "Pearson", 2016, "Chemistry", 2),
    ("Principles of Electronics", "V.K. Mehta", "S. Chand", 2014, "Electronics", 4),
    ("Digital Design", "M. Morris Mano", "Pearson", 2012, "Electronics", 3),
    ("Microelectronic Circuits", "Adel Sedra, Kenneth Smith", "Oxford", 2014, "Electronics", 2),
    ("Signals and Systems", "Alan V. Oppenheim", "Pearson", 1996, "Electronics", 2),
    ("Principles of Economics", "N. Gregory Mankiw", "Cengage", 2020, "Economics", 3),
    ("Indian Economy", "Ramesh Singh", "McGraw-Hill", 2021, "Economics", 3),
    ("Thinking, Fast and Slow", "Daniel Kahneman", "Farrar, Straus and Giroux", 2011, "Psychology", 2),
    ("Atomic Habits", "James Clear", "Avery", 2018, "Self-Help", 3),
    ("The Discovery of India", "Jawaharlal Nehru", "Penguin", 2004, "History", 2),
    ("India After Gandhi", "Ramachandra Guha", "Picador", 2008, "History", 2),
    ("Sapiens: A Brief History of Humankind", "Yuval Noah Harari", "Harper", 2015, "History", 3),
    ("Wings of Fire", "A.P.J. Abdul Kalam", "Universities Press", 1999, "Biography", 4),
    ("The Story of My Experiments with Truth", "M.K. Gandhi", "Navajivan", 1927, "Biography", 2),
    ("Steve Jobs", "Walter Isaacson", "Simon & Schuster", 2011, "Biography", 2),
    ("Gitanjali", "Rabindranath Tagore", "Macmillan", 1913, "Literature", 2),
    ("The God of Small Things", "Arundhati Roy", "IndiaInk", 1997, "Literature", 2),
    ("Midnight's Children", "Salman Rushdie", "Jonathan Cape", 1981, "Literature", 1),
    ("The White Tiger", "Aravind Adiga", "Atlantic", 2008, "Literature", 2),
    ("Malgudi Days", "R.K. Narayan", "Indian Thought", 1943, "Literature", 3),
    ("To Kill a Mockingbird", "Harper Lee", "J.B. Lippincott", 1960, "Literature", 2),
    ("1984", "George Orwell", "Secker & Warburg", 1949, "Literature", 3),
    ("Pride and Prejudice", "Jane Austen", "T. Egerton", 1813, "Literature", 2),
    ("The Alchemist", "Paulo Coelho", "HarperCollins", 1993, "Literature", 3),
    ("Harry Potter and the Philosopher's Stone", "J.K. Rowling", "Bloomsbury", 1997, "Literature", 3),
    ("The Hobbit", "J.R.R. Tolkien", "George Allen & Unwin", 1937, "Literature", 2),
    ("Godaan", "Munshi Premchand", "Saraswati Press", 1936, "Literature", 1),
    ("Engineering Mechanics", "S.S. Bhavikatti", "New Age", 2016, "Mechanical", 3),
    ("Thermodynamics: An Engineering Approach", "Yunus Cengel", "McGraw-Hill", 2014, "Mechanical", 2),
    ("Strength of Materials", "R.K. Bansal", "Laxmi Publications", 2010, "Mechanical", 3),
    ("Basic Civil Engineering", "M.S. Palanichamy", "McGraw-Hill", 2012, "Civil", 2),
    ("Principles of Management", "Harold Koontz", "McGraw-Hill", 2012, "Management", 2),
    ("Business Communication", "Meenakshi Raman", "Oxford", 2012, "Management", 2),
    ("Environmental Studies", "Erach Bharucha", "Universities Press", 2013, "Environment", 4),
    ("Indian Polity", "M. Laxmikanth", "McGraw-Hill", 2019, "Law & Polity", 3),
]

SHELF_PREFIX = {
    "Computer Science": "CS", "Mathematics": "MA", "Physics": "PH", "Chemistry": "CH", "Electronics": "EC",
    "Economics": "EN", "Psychology": "PS", "Self-Help": "SH", "History": "HI", "Biography": "BI",
    "Literature": "LT", "Mechanical": "ME", "Civil": "CV", "Management": "MG", "Environment": "EV",
    "Law & Polity": "LP",
}

USERS = [
    # code, name, email, phone, dept, role
    ("ADM001", "Dr. Suresh Menon", "admin@alms.edu", "+91 98450 10001", "Library Administration", "admin"),
    ("LIB001", "Kavita Rao", "kavita.rao@alms.edu", "+91 98450 20001", "Circulation Desk", "librarian"),
    ("LIB002", "Arjun Nair", "arjun.nair@alms.edu", "+91 98450 20002", "Circulation Desk", "librarian"),
    ("STU001", "Aarav Sharma", "aarav.sharma@student.alms.edu", "+91 90000 00001", "B.Tech CSE", "student"),
    ("STU002", "Priya Patel", "priya.patel@student.alms.edu", "+91 90000 00002", "B.Tech ECE", "student"),
    ("STU003", "Rohan Gupta", "rohan.gupta@student.alms.edu", "+91 90000 00003", "B.Tech ME", "student"),
    ("STU004", "Ananya Reddy", "ananya.reddy@student.alms.edu", "+91 90000 00004", "B.Tech CSE", "student"),
    ("STU005", "Kabir Singh", "kabir.singh@student.alms.edu", "+91 90000 00005", "B.Sc Physics", "student"),
    ("STU006", "Ishita Banerjee", "ishita.b@student.alms.edu", "+91 90000 00006", "BA English", "student"),
    ("STU007", "Vivaan Joshi", "vivaan.joshi@student.alms.edu", "+91 90000 00007", "B.Com", "student"),
    ("STU008", "Diya Kulkarni", "diya.k@student.alms.edu", "+91 90000 00008", "B.Tech Civil", "student"),
    ("STU009", "Aditya Verma", "aditya.verma@student.alms.edu", "+91 90000 00009", "BBA", "student"),
    ("STU010", "Sneha Das", "sneha.das@student.alms.edu", "+91 90000 00010", "B.Tech CSE", "student"),
    ("STU011", "Rahul Mehta", "rahul.mehta@student.alms.edu", "+91 90000 00011", "B.Tech ECE", "student"),
    ("STU012", "Meera Pillai", "meera.pillai@student.alms.edu", "+91 90000 00012", "MBA", "student"),
    ("FAC001", "Dr. Meera Iyer", "meera.iyer@alms.edu", "+91 98450 30001", "Dept. of Computer Science", "faculty"),
    ("FAC002", "Prof. Rajesh Kumar", "rajesh.kumar@alms.edu", "+91 98450 30002", "Dept. of Physics", "faculty"),
]

TABLES_IN_DELETE_ORDER = ["notifications", "audit_log", "fines", "holds", "loans", "copies", "books", "users", "settings"]


def isbn13(n):
    core = f"97881{n:07d}"
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core))
    return core + str((10 - total % 10) % 10)


def seed_demo():
    db = get_db()
    for t in TABLES_IN_DELETE_ORDER:
        db.execute(f"DELETE FROM {t}")
    db.execute("DELETE FROM sqlite_sequence") if db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'"
    ).fetchone() else None
    for k, v in DEFAULT_SETTINGS.items():
        set_setting(k, v, db)

    t = today(db)
    rng = random.Random(42)
    pw = hash_password(DEMO_PASSWORD)

    def ts(d, hour=10, minute=0):
        return f"{d.isoformat()} {hour:02d}:{minute:02d}:00"

    uid = {}
    for code, name, email, phone, dept, role in USERS:
        created = t - timedelta(days=200)
        uid[code] = db.execute(
            "INSERT INTO users(member_code, name, email, phone, department, role, password_hash, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (code, name, email, phone, dept, role, pw, ts(created)),
        ).lastrowid

    book_ids, copies_by_book = {}, {}
    barcode_n = 100001
    shelf_counter = {}
    for i, (title, author, pub, year, cat, n) in enumerate(BOOKS, start=1):
        pre = SHELF_PREFIX[cat]
        shelf_counter[pre] = shelf_counter.get(pre, 0) + 1
        shelf = f"{pre}-{(shelf_counter[pre] - 1) // 4 + 1:02d}-{chr(65 + (shelf_counter[pre] - 1) % 4)}"
        bid = db.execute(
            "INSERT INTO books(isbn, title, author, publisher, year, category, shelf, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (isbn13(i * 37), title, author, pub, year, cat, shelf, ts(t - timedelta(days=200))),
        ).lastrowid
        book_ids[title] = bid
        copies_by_book[bid] = []
        for _ in range(n):
            cid = db.execute(
                "INSERT INTO copies(book_id, barcode, added_at) VALUES (?,?,?)",
                (bid, f"BC{barcode_n}", ts(t - timedelta(days=200))),
            ).lastrowid
            copies_by_book[bid].append(cid)
            barcode_n += 1

    librarian = uid["LIB001"]

    def free_copy(title):
        bid = book_ids[title]
        row = db.execute(
            "SELECT id FROM copies WHERE book_id = ? AND status = 'available' ORDER BY id LIMIT 1", (bid,)
        ).fetchone()
        return row["id"]

    # Historical, already-returned loans so the reports have something to show.
    titles = list(book_ids)
    weights = [rng.randint(1, 10) for _ in titles]
    members = [c for c in uid if c.startswith(("STU", "FAC"))]
    receipt_n = 0
    for _ in range(170):
        title = rng.choices(titles, weights)[0]
        cid = rng.choice(copies_by_book[book_ids[title]])
        member = rng.choice(members)
        issue = t - timedelta(days=rng.randint(16, 120))
        due = issue + timedelta(days=14)
        late = rng.random() < 0.18
        ret = due + timedelta(days=rng.randint(1, 9)) if late else issue + timedelta(days=rng.randint(2, 14))
        if ret >= t:
            continue
        lid = db.execute(
            "INSERT INTO loans(copy_id, user_id, issued_by, issue_date, due_date, return_date, status) VALUES (?,?,?,?,?,?, 'returned')",
            (cid, uid[member], librarian, issue.isoformat(), due.isoformat(), ret.isoformat()),
        ).lastrowid
        if late:
            days = (ret - due).days
            receipt_n += 1
            db.execute(
                "INSERT INTO fines(user_id, loan_id, amount, reason, created_at, status, paid_at, method, receipt_no, handled_by) VALUES (?,?,?,?,?, 'paid', ?, ?, ?, ?)",
                (uid[member], lid, days * 5, f"Overdue {days} day(s): {title}", ts(ret), ts(ret, 11),
                 rng.choice(["cash", "online (UPI)"]), f"RCPT-{ret.strftime('%Y%m%d')}-{receipt_n:04d}", librarian),
            )

    def active_loan(code, title, issued_days_ago, renewals=0):
        cid = free_copy(title)
        issue = t - timedelta(days=issued_days_ago)
        due = issue + timedelta(days=14 * (1 + renewals))
        db.execute(
            "INSERT INTO loans(copy_id, user_id, issued_by, issue_date, due_date, renewals) VALUES (?,?,?,?,?,?)",
            (cid, uid[code], librarian, issue.isoformat(), due.isoformat(), renewals),
        )
        db.execute("UPDATE copies SET status = 'loaned' WHERE id = ?", (cid,))
        return cid

    # STU001 Aarav — eligible; holds the only copy of 'Clean Code' (due in 2 days); Kabir is waiting for it.
    active_loan("STU001", "Clean Code", 12)
    active_loan("STU001", "Introduction to Algorithms", 5)
    # STU002 Priya — overdue by 6 days → blocked, fine accruing.
    active_loan("STU002", "Digital Design", 20)
    # STU003 Rohan — returned late earlier, unpaid fine → blocked.
    past_issue = t - timedelta(days=30)
    cid = copies_by_book[book_ids["Engineering Mechanics"]][0]
    lid = db.execute(
        "INSERT INTO loans(copy_id, user_id, issued_by, issue_date, due_date, return_date, status) VALUES (?,?,?,?,?,?, 'returned')",
        (cid, uid["STU003"], librarian, past_issue.isoformat(), (past_issue + timedelta(days=14)).isoformat(),
         (past_issue + timedelta(days=23)).isoformat()),
    ).lastrowid
    db.execute(
        "INSERT INTO fines(user_id, loan_id, amount, reason, created_at) VALUES (?,?,?,?,?)",
        (uid["STU003"], lid, 45, "Overdue 9 day(s): Engineering Mechanics", ts(past_issue + timedelta(days=23))),
    )
    # STU004 Ananya — quota reached (3/3).
    active_loan("STU004", "Operating System Concepts", 3)
    active_loan("STU004", "Computer Networks", 4)
    active_loan("STU004", "Database System Concepts", 6)
    # The Feynman Lectures (1 copy) is on loan to FAC002; SICP (1 copy) is on the hold shelf for Kabir.
    active_loan("FAC001", "Design Patterns", 8)
    active_loan("FAC001", "Artificial Intelligence: A Modern Approach", 2)
    active_loan("FAC002", "The Feynman Lectures on Physics", 10)
    active_loan("STU006", "Midnight's Children", 9)
    active_loan("STU006", "Gitanjali", 1)
    active_loan("STU007", "Principles of Economics", 7)
    active_loan("STU008", "Basic Civil Engineering", 13)
    active_loan("STU009", "Atomic Habits", 11, renewals=1)
    active_loan("STU010", "Python Crash Course", 3)
    active_loan("STU010", "The Pragmatic Programmer", 16)  # overdue 2 days
    active_loan("STU011", "Signals and Systems", 6)

    # Holds (FR-05)
    db.execute(
        "INSERT INTO holds(book_id, user_id, placed_at) VALUES (?,?,?)",
        (book_ids["Clean Code"], uid["STU005"], ts(t - timedelta(days=3), 14)),
    )
    db.execute(
        "INSERT INTO holds(book_id, user_id, placed_at) VALUES (?,?,?)",
        (book_ids["Clean Code"], uid["STU010"], ts(t - timedelta(days=2), 9)),
    )
    db.execute(
        "INSERT INTO holds(book_id, user_id, placed_at) VALUES (?,?,?)",
        (book_ids["The Feynman Lectures on Physics"], uid["STU005"], ts(t - timedelta(days=4), 16)),
    )
    sicp_copy = copies_by_book[book_ids["Structure and Interpretation of Computer Programs"]][0]
    db.execute("UPDATE copies SET status = 'on_hold' WHERE id = ?", (sicp_copy,))
    db.execute(
        "INSERT INTO holds(book_id, user_id, placed_at, status, copy_id, ready_at, expires_at) VALUES (?,?,?, 'ready', ?, ?, ?)",
        (book_ids["Structure and Interpretation of Computer Programs"], uid["STU005"], ts(t - timedelta(days=9)),
         sicp_copy, (t - timedelta(days=1)).isoformat(), (t + timedelta(days=2)).isoformat()),
    )

    # Lost & damaged inventory for the reports.
    lost_copy = copies_by_book[book_ids["The White Tiger"]][1]
    lost_issue = t - timedelta(days=50)
    lid = db.execute(
        "INSERT INTO loans(copy_id, user_id, issued_by, issue_date, due_date, return_date, status) VALUES (?,?,?,?,?,?, 'lost')",
        (lost_copy, uid["STU012"], librarian, lost_issue.isoformat(), (lost_issue + timedelta(days=14)).isoformat(),
         (lost_issue + timedelta(days=20)).isoformat()),
    ).lastrowid
    db.execute("UPDATE copies SET status = 'lost' WHERE id = ?", (lost_copy,))
    receipt_n += 1
    db.execute(
        "INSERT INTO fines(user_id, loan_id, amount, reason, created_at, status, paid_at, method, receipt_no, handled_by) VALUES (?,?,?,?,?, 'paid', ?, 'cash', ?, ?)",
        (uid["STU012"], lid, 530, "Lost book replacement: The White Tiger (+6d overdue)",
         ts(lost_issue + timedelta(days=20)), ts(lost_issue + timedelta(days=20), 12),
         f"RCPT-{(lost_issue + timedelta(days=20)).strftime('%Y%m%d')}-{receipt_n:04d}", librarian),
    )
    db.execute(
        "UPDATE copies SET status = 'damaged' WHERE id = ?", (copies_by_book[book_ids["Let Us C"]][4],)
    )

    # A few historic notifications so the gateway outbox isn't empty.
    def note(code, subject, body, days_ago, channels=("email", "sms")):
        for ch in channels:
            db.execute(
                "INSERT INTO notifications(user_id, channel, subject, body, created_at, is_read) VALUES (?,?,?,?,?,1)",
                (uid[code], ch, subject, body, ts(t - timedelta(days=days_ago), 9)),
            )

    note("STU005", "Hold placed", "You are #1 in the queue for 'Clean Code'. We will notify you when a copy is returned.", 3)
    note("STU005", "Your reserved book is ready",
         f"'Structure and Interpretation of Computer Programs' is now waiting for you at the circulation desk. Please collect it by {(t + timedelta(days=2)).strftime('%d %b %Y')}.", 1)
    note("STU003", "Overdue fine assessed", "'Engineering Mechanics' was returned 9 day(s) late. A fine of ₹45 has been added to your account.", 7)

    db.execute(
        "INSERT INTO audit_log(ts, actor_id, action, details) VALUES (?,?,?,?)",
        (ts(t, 8), uid["ADM001"], "SEED", "Demo dataset loaded"),
    )
    db.commit()
