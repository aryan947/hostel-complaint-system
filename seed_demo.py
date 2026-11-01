"""Optional: fill the database with sample students and complaints for demos.
Run once:  python seed_demo.py
Demo student login:  sagar / student123, pratik / student123, aryan / student123
Warden: warden / warden123
"""
import pandas as pd
from werkzeug.security import generate_password_hash
import app as A

# Read data from Excel file
import os
excel_file = os.path.join(os.path.dirname(__file__), "hostel_complaints.xlsx")
df = pd.read_excel(excel_file)

# Filter out empty rows and notes
df = df.dropna(subset=['Title'])

db = A.sqlite3.connect(A.DB_PATH)
db.row_factory = A.sqlite3.Row

# Create students from Excel data
students_map = {
    "Amruta": ("amruta", "B", "101", "Amrut@00"),
    "Sanika": ("sanika", "A", "204", "S@nika10"),
    "Prachi": ("prachi", "C", "301", "Pr@chi11"),
}

for name, (username, block, room, password) in students_map.items():
    db.execute("INSERT OR IGNORE INTO users(name, username, role, block, room_no, password_hash) VALUES (?,?,?,?,?,?)",
               (name, username, "student", block, room, generate_password_hash(password)))

# Get category IDs
category_ids = {r["name"]: r["id"] for r in db.execute("SELECT * FROM categories").fetchall()}

# Get staff IDs
staff_ids = {r["name"]: r["id"] for r in db.execute("SELECT * FROM staff").fetchall()}

# Get student IDs
student_ids = {r["name"]: r["id"] for r in db.execute("SELECT * FROM users WHERE role='student'").fetchall()}

# Map Excel student names to new student accounts
student_name_mapping = {
    "Sagar More": "Amruta",
    "Pratik Shinde": "Prachi",
    "Aryan Patil": "Sanika",
}

# Process each complaint from Excel
for _, row in df.iterrows():
    title = row['Title']
    category = row['Category']
    student_name = row['Student']
    block = row['Block']
    room = row['Room']
    priority = row['Priority']
    status = row['Status']
    assigned_to = row['Assigned To']
    filed_on = row['Filed On']

    # Skip if category not found
    if category not in category_ids:
        continue

    # Get student ID (map Excel names to new student accounts)
    mapped_name = student_name_mapping.get(student_name, student_name)
    student_id = student_ids.get(mapped_name)
    if not student_id:
        continue

    # Get category ID
    category_id = category_ids[category]

    # Get staff ID if assigned
    assigned_staff_id = None
    if assigned_to and assigned_to != "-":
        assigned_staff_id = staff_ids.get(assigned_to)

    # Parse date
    if pd.notna(filed_on):
        if isinstance(filed_on, str):
            # Excel format is "YYYY-MM-DD HH:MM", add ":00" for seconds
            if len(filed_on) == 16:
                created_at = filed_on + ":00"
            else:
                created_at = filed_on
        else:
            created_at = filed_on.strftime("%Y-%m-%d %H:%M:%S")
    else:
        from datetime import datetime
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Set resolved_at based on status
    resolved_at = None
    if status == "Resolved":
        from datetime import datetime, timedelta
        # Assume resolved after some hours
        created_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
        resolved_dt = created_dt + timedelta(hours=24)
        resolved_at = resolved_dt.strftime("%Y-%m-%d %H:%M:%S")

    # Generate description based on title
    descriptions = {
        "Fan not working": "Ceiling fan has stopped running.",
        "Tap leaking": "Bathroom tap drips all day.",
        "Bathroom not cleaned": "Not cleaned for 3 days.",
        "Mess food quality": "Food was stale at dinner.",
        "Broken chair": "Study chair leg is broken.",
        "Wi-Fi very slow": "Internet drops every few minutes.",
        "Tube light flickering": "Light flickers constantly.",
        "No hot water": "Geyser not heating.",
    }
    description = descriptions.get(title, f"Issue with {title}")

    # Insert complaint
    cur = db.execute("""INSERT INTO complaints(student_id, category_id, title, description, priority, status,
                        assigned_to, created_at, resolved_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                     (student_id, category_id, title, description, priority, status, assigned_staff_id, created_at, resolved_at))

    # Add history
    db.execute("INSERT INTO history(complaint_id, status, note, at) VALUES (?,?,?,?)",
               (cur.lastrowid, "Submitted", "Complaint registered by student", created_at))

    if assigned_staff_id:
        db.execute("INSERT INTO history(complaint_id, status, note, at) VALUES (?,?,?,?)",
                   (cur.lastrowid, "Assigned", f"Assigned to {assigned_to}", created_at))

    if status == "Resolved":
        db.execute("INSERT INTO history(complaint_id, status, note, at) VALUES (?,?,?,?)",
                   (cur.lastrowid, "Resolved", "Work completed", resolved_at))

db.commit()
print("Demo data added from Excel file.")
