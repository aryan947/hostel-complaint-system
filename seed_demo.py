"""Optional: fill the database with sample students and complaints for demos.
Run once:  python seed_demo.py
Demo student login:  prn101 / student123   (warden: warden / warden123)
"""
import random
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
import app as A

random.seed(7)
db = A.sqlite3.connect(A.DB_PATH)
db.row_factory = A.sqlite3.Row
students = [("Aryan Patil", "prn101", "A", "204"), ("Rohan Desai", "prn102", "A", "205"),
            ("Sagar More", "prn103", "B", "110"), ("Omkar Jadhav", "prn104", "B", "112"),
            ("Pratik Shinde", "prn105", "C", "301")]
for n, u, b, r in students:
    db.execute("INSERT OR IGNORE INTO users(name, username, role, block, room_no, password_hash) VALUES (?,?,?,?,?,?)",
               (n, u, "student", b, r, generate_password_hash("student123")))
samples = [
    (1, "Fan not working", "Ceiling fan has stopped running."), (2, "Tap leaking", "Bathroom tap drips all day."),
    (3, "Bathroom not cleaned", "Not cleaned for 3 days."), (4, "Mess food quality", "Food was stale at dinner."),
    (5, "Broken chair", "Study chair leg is broken."), (6, "Wi-Fi very slow", "Internet drops every few minutes."),
    (1, "Tube light flickering", "Light flickers constantly."), (2, "No hot water", "Geyser not heating."),
]
uids = [r["id"] for r in db.execute("SELECT id FROM users WHERE role='student'")]
staff = [r["id"] for r in db.execute("SELECT id FROM staff")]
for cat, title, desc in samples:
    sid = random.choice(uids)
    created = datetime.now() - timedelta(days=random.randint(0, 6), hours=random.randint(0, 20))
    status = random.choice(A.STATUSES)
    ts = created.strftime("%Y-%m-%d %H:%M:%S")
    assigned = random.choice(staff) if status != "Submitted" else None
    resolved = (created + timedelta(hours=random.randint(4, 60))).strftime("%Y-%m-%d %H:%M:%S") if status == "Resolved" else None
    cur = db.execute("""INSERT INTO complaints(student_id, category_id, title, description, priority, status,
                        assigned_to, created_at, resolved_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                     (sid, cat, title, desc, random.choice(A.PRIORITIES), status, assigned, ts, resolved))
    db.execute("INSERT INTO history(complaint_id, status, note, at) VALUES (?,?,?,?)",
               (cur.lastrowid, "Submitted", "Complaint registered by student", ts))
    if assigned:
        db.execute("INSERT INTO history(complaint_id, status, note, at) VALUES (?,?,?,?)",
                   (cur.lastrowid, "Assigned", "Assigned to maintenance staff", ts))
    if resolved:
        db.execute("INSERT INTO history(complaint_id, status, note, at) VALUES (?,?,?,?)",
                   (cur.lastrowid, "Resolved", "Work completed", resolved))
db.commit()
print("Demo data added.")
