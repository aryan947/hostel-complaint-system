"""Hostel Complaint Management & Tracking System
B.Tech CSBS - Field Project / PBL
Stack: Flask + SQLite + Chart.js
"""
# HOW TO READ THIS FILE (beginner guide)
# 1. Top of file: imports, settings and the database tables (SCHEMA).
# 2. Helper functions: database connection, login check, overdue check.
# 3. Routes: each @app.route(...) is one web page or action.
#    Public pages -> login/register -> student pages -> warden pages -> errors.
# 4. Last lines: create the database and start the server.
# Flow of one request: Browser -> Flask route (this file) -> SQLite database -> HTML template -> Browser.
# Comments starting with # are ignored by Python; they are only notes for humans.
import os
import secrets
import sqlite3
from datetime import datetime
from functools import wraps

# Flask gives us the web-app tools:
#  Flask (the app itself), render_template (fill an HTML page), request (data the user sent),
#  session (remember the logged-in user), redirect/url_for (go to another page),
#  flash (one-time message), abort (show an error page), g (temporary storage for one request).
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# ---------- Settings: file locations and fixed lists ----------
# __file__ is this file; BASE_DIR is its folder, so the paths work on any computer.
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "hostel.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
# Only these image types may be uploaded as a complaint photo.
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}

# Complaint categories (saved into the database the first time the app runs).
CATEGORIES = ["Electrical", "Water & Plumbing", "Cleanliness", "Food / Mess",
              "Furniture", "Internet / Wi-Fi", "Security", "Staff Behavior", "Other"]
# The life cycle of a complaint, in order. The warden moves a complaint along these steps.
STATUSES = ["Submitted", "Assigned", "In Progress", "Resolved", "Escalated"]
# Normal or Urgent. Urgent is meant only for water, electricity or safety problems.
PRIORITIES = ["Normal", "Urgent"]
# A complaint still open after this many days is flagged "Overdue" (auto-escalation)
OVERDUE_DAYS = {"Normal": 3, "Urgent": 1}
# User roles in hierarchy: Admin -> Rector -> Warden -> Student
ROLES = ["student", "warden", "rector", "admin"]
# Complaint target types
TARGET_TYPES = ["facility", "staff", "warden", "rector"]

# Create the Flask application. Every @app.route below is attached to this object.
app = Flask(__name__)
# SECRET_KEY signs the login cookie so nobody can fake it. Use a real secret in deployment.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-in-production")
app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024  # 3 MB uploads

# SCHEMA is SQL text that creates our 6 tables:
#  users, categories, staff, complaints, history, feedback.
# REFERENCES = foreign key (e.g. complaints.student_id points to users.id).
# NOT NULL / UNIQUE / CHECK are rules the database enforces for us.
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('student','warden','rector','admin')),
    block TEXT,
    room_no TEXT,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    skill TEXT NOT NULL,
    phone TEXT
);
CREATE TABLE IF NOT EXISTS complaints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES users(id),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    photo TEXT,
    priority TEXT NOT NULL DEFAULT 'Normal',
    status TEXT NOT NULL DEFAULT 'Submitted',
    assigned_to INTEGER REFERENCES staff(id),
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    target_type TEXT DEFAULT 'facility',
    target_id INTEGER,
    is_anonymous INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER NOT NULL REFERENCES complaints(id),
    status TEXT NOT NULL,
    note TEXT,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER NOT NULL UNIQUE REFERENCES complaints(id),
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    fixed INTEGER NOT NULL,
    comment TEXT,
    at TEXT NOT NULL
);
"""


# ---------- database helpers ----------
# get_db() opens the SQLite database once per request and reuses it.
# g is Flask's temporary storage that lasts for one request.
# row_factory = sqlite3.Row lets us read a column by name, e.g. row["status"].
# PRAGMA foreign_keys = ON makes SQLite enforce the REFERENCES rules.
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


# Runs automatically at the end of every request and closes the database connection.
@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Current date and time as text, e.g. 2026-10-10 20:05:00 (the format stored in the database).
def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# init_db() runs once when the app starts: it creates the tables if missing and adds
# the categories, default accounts (admin, rector, warden) and some sample staff.
# INSERT OR IGNORE skips rows that already exist.
# The ? marks are placeholders: values are passed separately, which prevents SQL injection.
def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    for c in CATEGORIES:
        db.execute("INSERT OR IGNORE INTO categories(name) VALUES (?)", (c,))
    # Create default admin account
    if not db.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        db.execute(
            "INSERT INTO users(name, username, role, password_hash) VALUES (?,?,?,?)",
            ("System Admin", "admin", "admin", generate_password_hash("Admin@123")))
    # Create default rector account
    if not db.execute("SELECT 1 FROM users WHERE role='rector'").fetchone():
        db.execute(
            "INSERT INTO users(name, username, role, password_hash) VALUES (?,?,?,?)",
            ("Hostel Rector", "rector", "rector", generate_password_hash("Rector@123")))
    # Create default warden login only if no warden exists yet (the password is stored hashed).
    if not db.execute("SELECT 1 FROM users WHERE role='warden'").fetchone():
        db.execute(
            "INSERT INTO users(name, username, role, password_hash) VALUES (?,?,?,?)",
            ("Hostel Warden", "warden", "warden", generate_password_hash("warden123")))
    if not db.execute("SELECT 1 FROM staff").fetchone():
        db.executemany("INSERT INTO staff(name, skill, phone) VALUES (?,?,?)", [
            ("Ramesh Patil", "Electrician", "9000000001"),
            ("Suresh Jadhav", "Plumber", "9000000002"),
            ("Anita More", "Housekeeping", "9000000003"),
            ("Vijay Kamble", "Carpenter", "9000000004"),
        ])
    db.commit()
    db.close()

    # Load sample data from Excel if it exists and database is empty
    load_sample_data()


def load_sample_data():
    """Load sample data from Excel file if available and database has no students."""
    try:
        import pandas as pd
        excel_file = os.path.join(BASE_DIR, "hostel_complaints.xlsx")
        if not os.path.exists(excel_file):
            return

        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row

        # Check if we already have students
        if db.execute("SELECT 1 FROM users WHERE role='student'").fetchone():
            db.close()
            return

        # Create students
        students_map = {
            "Amruta": ("amruta", "B", "101", "Amrut@00"),
            "Sanika": ("sanika", "A", "204", "S@nika10"),
            "Prachi": ("prachi", "C", "301", "Pr@chi11"),
        }

        for name, (username, block, room, password) in students_map.items():
            db.execute("INSERT OR IGNORE INTO users(name, username, role, block, room_no, password_hash) VALUES (?,?,?,?,?,?)",
                       (name, username, "student", block, room, generate_password_hash(password)))

        # Create default warden account
        db.execute("INSERT OR IGNORE INTO users(name, username, role, password_hash) VALUES (?,?,?,?)",
                   ("Hostel Warden", "warden", "warden", generate_password_hash("warden123")))

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

        # Read Excel data
        df = pd.read_excel(excel_file)
        df = df.dropna(subset=['Title'])

        from datetime import datetime, timedelta

        # Process each complaint from Excel
        for _, row in df.iterrows():
            title = row['Title']
            category = row['Category']
            student_name = row['Student']
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
                    if len(filed_on) == 16:
                        created_at = filed_on + ":00"
                    else:
                        created_at = filed_on
                else:
                    created_at = filed_on.strftime("%Y-%m-%d %H:%M:%S")
            else:
                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Set resolved_at based on status
            resolved_at = None
            if status == "Resolved":
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
        db.close()
    except Exception as e:
        print(f"Could not load sample data: {e}")


# ---------- auth ----------
# Runs before EVERY request. If a user_id is stored in the session (set at login),
# load that user from the database into g.user so every page knows who is logged in.
@app.before_request
def load_user():
    g.user = None
    uid = session.get("user_id")
    if uid:
        g.user = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


# login_required is a DECORATOR. Writing @login_required("warden") above a route means:
#  1) not logged in        -> send to the login page
#  2) logged in, wrong role -> error 403 (Forbidden)
#  3) otherwise            -> run the page function normally.
# This is how student pages and warden pages are kept separate.
def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if g.user is None:
                flash("Please log in first.", "warn")
                return redirect(url_for("login"))
            if role and g.user["role"] != role:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def is_overdue(row):
    """True if an unresolved complaint has exceeded its allowed days."""
    if row["status"] == "Resolved":
        return False
    # age = how long ago the complaint was filed; compare its days with the limit for its priority.
    age = datetime.now() - datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
    return age.days >= OVERDUE_DAYS.get(row["priority"], 3)


# Make is_overdue and STATUSES usable inside the HTML templates (Jinja2).
app.jinja_env.globals.update(is_overdue=is_overdue, STATUSES=STATUSES)


def public_stats():
    """Aggregate numbers only (no personal data) for the public landing page."""
    db = get_db()
    # COUNT(*) counts rows and AVG() averages them. julianday() turns a date into a number,
    # so (resolved - created) * 24 gives the hours taken to resolve a complaint.
    total = db.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
    resolved = db.execute("SELECT COUNT(*) FROM complaints WHERE status='Resolved'").fetchone()[0]
    avg_hrs = db.execute("""SELECT ROUND(AVG((julianday(resolved_at)-julianday(created_at))*24),1)
                            FROM complaints WHERE resolved_at IS NOT NULL""").fetchone()[0]
    rating = db.execute("SELECT ROUND(AVG(rating),1) FROM feedback").fetchone()[0]
    students = db.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0]
    return dict(total=total, resolved=resolved, avg_hrs=avg_hrs, rating=rating, students=students)


# ---------- public pages ----------
# @app.route(url) links a URL to the function below it.
# Visitors who are not logged in see the home page; logged-in users go to their own dashboard.
@app.route("/")
def index():
    if g.user is None:
        return render_template("home.html", st=public_stats(), categories=CATEGORIES)
    # Redirect to appropriate dashboard based on role
    role = g.user["role"]
    if role == "admin":
        return redirect(url_for("admin_dashboard"))
    elif role == "rector":
        return redirect(url_for("rector_dashboard"))
    elif role == "warden":
        return redirect(url_for("warden_dashboard"))
    else:  # student
        return redirect(url_for("student_dashboard"))


@app.route("/home")
def home():
    return render_template("home.html", st=public_stats(), categories=CATEGORIES)


# Registration: GET shows the empty form, POST handles the submitted form.
# request.form[...] reads what the user typed. The password is saved only as a hash.
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        username = request.form["username"].strip().lower()
        block = request.form["block"].strip().upper()
        room = request.form["room_no"].strip()
        pw = request.form["password"]
        if not all([name, username, block, room, pw]):
            flash("All fields are required.", "error")
        elif len(pw) < 6:
            flash("Password must be at least 6 characters.", "error")
        else:
            try:
                get_db().execute(
                    "INSERT INTO users(name, username, role, block, room_no, password_hash) VALUES (?,?,?,?,?,?)",
                    (name, username, "student", block, room, generate_password_hash(pw)))
                get_db().commit()
                flash("Registration successful. Please log in.", "ok")
                return redirect(url_for("login"))
            # username is UNIQUE in the table, so registering the same PRN twice raises IntegrityError.
            except sqlite3.IntegrityError:
                flash("That username / PRN is already registered.", "error")
    return render_template("register.html")


# Login: find the user by username, then check_password_hash compares the typed password
# with the stored hash. On success session["user_id"] remembers the user (signed cookie).
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = get_db().execute("SELECT * FROM users WHERE username=?",
                                (request.form["username"].strip().lower(),)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form["password"]):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("index"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


# Logout: clearing the session makes the app forget the user.
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- student ----------
# Student dashboard: shows only THIS student's complaints (WHERE c.student_id = logged-in user).
# JOIN brings in the category name from the categories table.
# counts = number of complaints in each status (the four boxes at the top of the page).
@app.route("/student")
@login_required("student")
def student_dashboard():
    rows = get_db().execute(
        """SELECT c.*, cat.name AS category FROM complaints c
           JOIN categories cat ON cat.id = c.category_id
           WHERE c.student_id=? ORDER BY c.id DESC""", (g.user["id"],)).fetchall()
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    return render_template("student_dashboard.html", complaints=rows, counts=counts)


# New complaint: check the form, optionally save the photo, insert the complaint,
# and write the first line of its history ("Submitted").
@app.route("/complaint/new", methods=["GET", "POST"])
@login_required("student")
def new_complaint():
    db = get_db()
    cats = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    wardens = db.execute("SELECT * FROM users WHERE role='warden'").fetchall()
    if request.method == "POST":
        title = request.form["title"].strip()
        desc = request.form["description"].strip()
        cat_id = request.form.get("category_id", type=int)
        priority = request.form.get("priority", "Normal")
        target_type = request.form.get("target_type", "facility")
        target_id = request.form.get("target_id", type=int) if target_type != "facility" else None
        is_anonymous = 1 if request.form.get("anonymous") else 0

        if not title or not desc or not cat_id or priority not in PRIORITIES:
            flash("Please fill in all required fields.", "error")
            return render_template("new_complaint.html", cats=cats, priorities=PRIORITIES, wardens=wardens)

        photo_name = None
        f = request.files.get("photo")
        # The photo is optional. Check the file extension, then save it with a random prefix so two
        # files never clash. secure_filename removes dangerous characters from the file name.
        if f and f.filename:
            ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
            if ext not in ALLOWED_EXT:
                flash("Photo must be a PNG, JPG, GIF or WEBP image.", "error")
                return render_template("new_complaint.html", cats=cats, priorities=PRIORITIES, wardens=wardens)
            photo_name = secrets.token_hex(8) + "_" + secure_filename(f.filename)
            f.save(os.path.join(UPLOAD_DIR, photo_name))

        ts = now()
        # Auto-escalate complaints about wardens
        status = "Escalated" if target_type == "warden" else "Submitted"

        # Save the complaint. cur.lastrowid is the new complaint id (used for the history row and the redirect).
        cur = db.execute(
            """INSERT INTO complaints(student_id, category_id, title, description, photo, priority, status, created_at, target_type, target_id, is_anonymous)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (g.user["id"], cat_id, title, desc, photo_name, priority, status, ts, target_type, target_id, is_anonymous))

        note = "Complaint registered by student"
        if is_anonymous:
            note += " (Anonymous)"
        if target_type == "warden":
            note += " - Escalated to Rector"

        db.execute("INSERT INTO history(complaint_id, status, note, at) VALUES (?,?,?,?)",
                   (cur.lastrowid, status, note, ts))
        db.commit()
        flash(f"Complaint #{cur.lastrowid} submitted.", "ok")
        return redirect(url_for("view_complaint", cid=cur.lastrowid))
    return render_template("new_complaint.html", cats=cats, priorities=PRIORITIES, wardens=wardens)


# Complaint detail page. <int:cid> in the URL becomes the cid argument, e.g. /complaint/9.
# LEFT JOIN keeps the complaint even if no staff member is assigned yet.
# A student may open only their own complaints (else 403); the warden may open any
# EXCEPT complaints about themselves (which are escalated to rector).
@app.route("/complaint/<int:cid>")
@login_required()
def view_complaint(cid):
    db = get_db()
    c = db.execute(
        """SELECT c.*, cat.name AS category, u.name AS student, u.block, u.room_no,
                  s.name AS staff_name, s.skill AS staff_skill, s.phone AS staff_phone
           FROM complaints c
           JOIN categories cat ON cat.id=c.category_id
           JOIN users u ON u.id=c.student_id
           LEFT JOIN staff s ON s.id=c.assigned_to
           WHERE c.id=?""", (cid,)).fetchone()
    if c is None:
        abort(404)
    if g.user["role"] == "student" and c["student_id"] != g.user["id"]:
        abort(403)
    # Warden cannot see complaints about themselves
    if g.user["role"] == "warden" and c["target_type"] == "warden" and c["target_id"] == g.user["id"]:
        abort(403)
    hist = db.execute("SELECT * FROM history WHERE complaint_id=? ORDER BY id", (cid,)).fetchall()
    fb = db.execute("SELECT * FROM feedback WHERE complaint_id=?", (cid,)).fetchone()
    staff = db.execute("SELECT * FROM staff ORDER BY name").fetchall() if g.user["role"] == "warden" else []
    return render_template("complaint_detail.html", c=c, hist=hist, fb=fb, staff=staff)


# Student feedback after a complaint is Resolved.
# "Yes, fixed" -> save rating and comment, history shows the confirmation.
# "No" -> the complaint is REOPENED (status back to In Progress) so the warden sees it again.
@app.route("/complaint/<int:cid>/feedback", methods=["POST"])
@login_required("student")
def give_feedback(cid):
    db = get_db()
    c = db.execute("SELECT * FROM complaints WHERE id=? AND student_id=?", (cid, g.user["id"])).fetchone()
    if c is None:
        abort(404)
    if c["status"] != "Resolved" or db.execute("SELECT 1 FROM feedback WHERE complaint_id=?", (cid,)).fetchone():
        flash("Feedback cannot be submitted for this complaint.", "error")
        return redirect(url_for("view_complaint", cid=cid))
    rating = request.form.get("rating", type=int)
    fixed = request.form.get("fixed") == "yes"
    if rating not in range(1, 6):
        flash("Please choose a rating from 1 to 5.", "error")
        return redirect(url_for("view_complaint", cid=cid))
    ts = now()
    db.execute("INSERT INTO feedback(complaint_id, rating, fixed, comment, at) VALUES (?,?,?,?,?)",
               (cid, rating, int(fixed), request.form.get("comment", "").strip(), ts))
    if not fixed:  # student says the problem still exists -> reopen
        db.execute("UPDATE complaints SET status='In Progress', resolved_at=NULL WHERE id=?", (cid,))
        db.execute("DELETE FROM feedback WHERE complaint_id=?", (cid,))
        db.execute("INSERT INTO history(complaint_id, status, note, at) VALUES (?,?,?,?)",
                   (cid, "In Progress", "Reopened: student reported the problem is not fixed", ts))
        flash("Complaint reopened for the warden.", "warn")
    else:
        db.execute("INSERT INTO history(complaint_id, status, note, at) VALUES (?,?,?,?)",
                   (cid, "Resolved", "Student confirmed the fix and gave feedback", ts))
        flash("Thank you for your feedback.", "ok")
    db.commit()
    return redirect(url_for("view_complaint", cid=cid))


# Serves the uploaded photos, only to logged-in users.
@app.route("/uploads/<path:filename>")
@login_required()
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ---------- warden / admin ----------
# Warden dashboard with filters. The SQL is built step by step: each filter chosen adds an AND condition.
# The ? placeholders and the args list keep user input out of the SQL text (safe from SQL injection).
# ORDER BY puts unresolved complaints first, then Urgent first, then newest first.
@app.route("/warden")
@login_required("warden")
def warden_dashboard():
    db = get_db()
    status = request.args.get("status", "")
    cat = request.args.get("category", type=int)
    block = request.args.get("block", "").strip().upper()
    room = request.args.get("room", "").strip()
    prio = request.args.get("priority", "")
    # Warden cannot see complaints about themselves
    sql = """SELECT c.*, cat.name AS category, u.name AS student, u.block, u.room_no, s.name AS staff_name
             FROM complaints c
             JOIN categories cat ON cat.id=c.category_id
             JOIN users u ON u.id=c.student_id
             LEFT JOIN staff s ON s.id=c.assigned_to
             WHERE (c.target_type != 'warden' OR c.target_id IS NULL OR c.target_id != ?)"""
    args = [g.user["id"]]
    if status in STATUSES:
        sql += " AND c.status=?"; args.append(status)
    if cat:
        sql += " AND c.category_id=?"; args.append(cat)
    if block:
        sql += " AND u.block=?"; args.append(block)
    if room:
        sql += " AND u.room_no=?"; args.append(room)
    if prio in PRIORITIES:
        sql += " AND c.priority=?"; args.append(prio)
    sql += " ORDER BY (c.status='Resolved'), (c.priority='Urgent') DESC, c.id DESC"
    rows = db.execute(sql, args).fetchall()
    cats = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    totals = {s: db.execute("SELECT COUNT(*) FROM complaints WHERE status=?", (s,)).fetchone()[0] for s in STATUSES}
    overdue = sum(1 for r in db.execute("SELECT * FROM complaints").fetchall() if is_overdue(r))
    return render_template("warden_dashboard.html", complaints=rows, cats=cats, totals=totals,
                           overdue=overdue, priorities=PRIORITIES,
                           f=dict(status=status, category=cat, block=block, room=room, priority=prio))


# Warden updates a complaint: assign staff, change status, add a note.
# Rules: choosing staff on a Submitted complaint makes it Assigned; a complaint cannot move forward without staff.
# resolved_at is saved only when the status becomes Resolved.
# Every change is written to the history table, which is what the Progress Timeline shows.
@app.route("/warden/complaint/<int:cid>/update", methods=["POST"])
@login_required("warden")
def update_complaint(cid):
    db = get_db()
    c = db.execute("SELECT * FROM complaints WHERE id=?", (cid,)).fetchone()
    if c is None:
        abort(404)
    status = request.form.get("status", c["status"])
    staff_id = request.form.get("staff_id", type=int)
    note = request.form.get("note", "").strip()
    if status not in STATUSES:
        abort(400)
    if staff_id and status == "Submitted":
        status = "Assigned"
    if status in ("Assigned", "In Progress", "Resolved") and not (staff_id or c["assigned_to"]):
        flash("Assign a staff member before moving the complaint forward.", "error")
        return redirect(url_for("view_complaint", cid=cid))
    staff_id = staff_id or c["assigned_to"]
    ts = now()
    resolved_at = ts if status == "Resolved" else None
    db.execute("UPDATE complaints SET status=?, assigned_to=?, resolved_at=? WHERE id=?",
               (status, staff_id, resolved_at, cid))
    changed = status != c["status"] or staff_id != c["assigned_to"] or note
    if changed:
        label = note
        if staff_id != c["assigned_to"]:
            sname = db.execute("SELECT name FROM staff WHERE id=?", (staff_id,)).fetchone()["name"]
            label = f"Assigned to {sname}" + (f". {note}" if note else "")
        db.execute("INSERT INTO history(complaint_id, status, note, at) VALUES (?,?,?,?)",
                   (cid, status, label or "Status updated by warden", ts))
    db.commit()
    flash("Complaint updated.", "ok")
    return redirect(url_for("view_complaint", cid=cid))


# Maintenance staff page: GET shows the list (open_jobs = unresolved complaints per staff member),
# POST adds a new staff member.
@app.route("/warden/staff", methods=["GET", "POST"])
@login_required("warden")
def manage_staff():
    db = get_db()
    if request.method == "POST":
        name, skill = request.form["name"].strip(), request.form["skill"].strip()
        if name and skill:
            db.execute("INSERT INTO staff(name, skill, phone) VALUES (?,?,?)",
                       (name, skill, request.form.get("phone", "").strip()))
            db.commit()
            flash("Staff member added.", "ok")
        else:
            flash("Name and skill are required.", "error")
        return redirect(url_for("manage_staff"))
    staff = db.execute(
        """SELECT s.*, (SELECT COUNT(*) FROM complaints c WHERE c.assigned_to=s.id AND c.status!='Resolved') AS open_jobs
           FROM staff s ORDER BY s.name""").fetchall()
    return render_template("staff.html", staff=staff)


# Statistics page. Each query feeds one box or chart: complaints by category, by status,
# average hours to resolve, rooms with more than one complaint (HAVING n>1), average rating, overdue count.
# dict(r) turns database rows into dictionaries so the template can pass them to Chart.js.
@app.route("/warden/stats")
@login_required("warden")
def stats():
    db = get_db()
    by_cat = db.execute("""SELECT cat.name, COUNT(c.id) AS n FROM categories cat
                           LEFT JOIN complaints c ON c.category_id=cat.id GROUP BY cat.id ORDER BY n DESC""").fetchall()
    by_status = {s: db.execute("SELECT COUNT(*) FROM complaints WHERE status=?", (s,)).fetchone()[0] for s in STATUSES}
    avg_res = db.execute("""SELECT cat.name, ROUND(AVG((julianday(c.resolved_at)-julianday(c.created_at))*24),1) AS hrs
                            FROM complaints c JOIN categories cat ON cat.id=c.category_id
                            WHERE c.resolved_at IS NOT NULL GROUP BY cat.id ORDER BY hrs DESC""").fetchall()
    hot_rooms = db.execute("""SELECT u.block, u.room_no, COUNT(*) AS n FROM complaints c
                              JOIN users u ON u.id=c.student_id
                              GROUP BY u.block, u.room_no HAVING n>1 ORDER BY n DESC LIMIT 8""").fetchall()
    summary = db.execute("""SELECT COUNT(*) AS total,
                                   ROUND(AVG((julianday(resolved_at)-julianday(created_at))*24),1) AS avg_hrs
                            FROM complaints""").fetchone()
    rating = db.execute("SELECT ROUND(AVG(rating),1) AS r, COUNT(*) AS n FROM feedback").fetchone()
    overdue = sum(1 for r in db.execute("SELECT * FROM complaints").fetchall() if is_overdue(r))
    return render_template("stats.html", by_cat=[dict(r) for r in by_cat], by_status=by_status,
                           avg_res=[dict(r) for r in avg_res], hot_rooms=hot_rooms,
                           summary=summary, rating=rating, overdue=overdue)


# ---------- Admin ----------
# Admin dashboard: manage all users (students, wardens, rectors), view system-wide statistics
@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    db = get_db()
    # Get all users with their roles
    users = db.execute("SELECT * FROM users ORDER BY role, name").fetchall()
    # Count users by role
    role_counts = {role: db.execute("SELECT COUNT(*) FROM users WHERE role=?", (role,)).fetchone()[0] for role in ROLES}
    # System-wide statistics
    total_complaints = db.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
    total_resolved = db.execute("SELECT COUNT(*) FROM complaints WHERE status='Resolved'").fetchone()[0]
    total_staff = db.execute("SELECT COUNT(*) FROM staff").fetchone()[0]
    return render_template("admin_dashboard.html", users=users, role_counts=role_counts,
                           total_complaints=total_complaints, total_resolved=total_resolved,
                           total_staff=total_staff, roles=ROLES)


# Admin creates a new user (warden, rector, or student)
@app.route("/admin/user/new", methods=["GET", "POST"])
@login_required("admin")
def create_user():
    if request.method == "POST":
        name = request.form["name"].strip()
        username = request.form["username"].strip().lower()
        role = request.form["role"]
        block = request.form.get("block", "").strip().upper()
        room = request.form.get("room_no", "").strip()
        password = request.form["password"]
        if not all([name, username, role, password]):
            flash("Name, username, role, and password are required.", "error")
        elif role not in ROLES:
            flash("Invalid role.", "error")
        elif role == "student" and not (block and room):
            flash("Block and room number are required for students.", "error")
        elif len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
        else:
            try:
                get_db().execute(
                    "INSERT INTO users(name, username, role, block, room_no, password_hash) VALUES (?,?,?,?,?,?)",
                    (name, username, role, block, room, generate_password_hash(password)))
                get_db().commit()
                flash(f"{role.capitalize()} account created successfully.", "ok")
                return redirect(url_for("admin_dashboard"))
            except sqlite3.IntegrityError:
                flash("That username is already taken.", "error")
    return render_template("create_user.html", roles=ROLES)


# Admin deletes a user
@app.route("/admin/user/<int:uid>/delete", methods=["POST"])
@login_required("admin")
def delete_user(uid):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        abort(404)
    if user["role"] == "admin":
        flash("Cannot delete admin account.", "error")
        return redirect(url_for("admin_dashboard"))
    # Delete user
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    flash(f"User {user['name']} deleted.", "ok")
    return redirect(url_for("admin_dashboard"))


# ---------- Rector ----------
# Rector dashboard: view all complaints across all blocks, manage wardens, escalate issues
@app.route("/rector")
@login_required("rector")
def rector_dashboard():
    db = get_db()
    # View all complaints with filters
    status = request.args.get("status", "")
    cat = request.args.get("category", type=int)
    block = request.args.get("block", "").strip().upper()
    prio = request.args.get("priority", "")
    sql = """SELECT c.*, cat.name AS category, u.name AS student, u.block, u.room_no, s.name AS staff_name
             FROM complaints c
             JOIN categories cat ON cat.id=c.category_id
             JOIN users u ON u.id=c.student_id
             LEFT JOIN staff s ON s.id=c.assigned_to WHERE 1=1"""
    args = []
    if status in STATUSES:
        sql += " AND c.status=?"; args.append(status)
    if cat:
        sql += " AND c.category_id=?"; args.append(cat)
    if block:
        sql += " AND u.block=?"; args.append(block)
    if prio in PRIORITIES:
        sql += " AND c.priority=?"; args.append(prio)
    sql += " ORDER BY (c.status='Resolved'), (c.priority='Urgent') DESC, c.id DESC"
    rows = db.execute(sql, args).fetchall()
    cats = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    totals = {s: db.execute("SELECT COUNT(*) FROM complaints WHERE status=?", (s,)).fetchone()[0] for s in STATUSES}
    overdue = sum(1 for r in db.execute("SELECT * FROM complaints").fetchall() if is_overdue(r))
    # Get all wardens
    wardens = db.execute("SELECT * FROM users WHERE role='warden'").fetchall()
    return render_template("rector_dashboard.html", complaints=rows, cats=cats, totals=totals,
                           overdue=overdue, priorities=PRIORITIES, wardens=wardens,
                           f=dict(status=status, category=cat, block=block, priority=prio))


# Rector can view any complaint details
@app.route("/rector/complaint/<int:cid>")
@login_required("rector")
def rector_view_complaint(cid):
    db = get_db()
    c = db.execute(
        """SELECT c.*, cat.name AS category, u.name AS student, u.block, u.room_no,
                  s.name AS staff_name, s.skill AS staff_skill, s.phone AS staff_phone
           FROM complaints c
           JOIN categories cat ON cat.id=c.category_id
           JOIN users u ON u.id=c.student_id
           LEFT JOIN staff s ON s.id=c.assigned_to
           WHERE c.id=?""", (cid,)).fetchone()
    if c is None:
        abort(404)
    hist = db.execute("SELECT * FROM history WHERE complaint_id=? ORDER BY id", (cid,)).fetchall()
    fb = db.execute("SELECT * FROM feedback WHERE complaint_id=?", (cid,)).fetchone()
    return render_template("rector_complaint_detail.html", c=c, hist=hist, fb=fb)


# Friendly error pages: 403 = not allowed, 404 = page not found, 413 = file too large.
@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403, msg="You do not have access to this page."), 403


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, msg="Page not found."), 404


@app.errorhandler(413)
def too_large(_e):
    return render_template("error.html", code=413, msg="Photo is too large (max 3 MB)."), 413


# Create the database and the default data as soon as this file is loaded.
init_db()

# Runs only when you start this file directly (python app.py).
# debug=True reloads on changes and shows errors: fine for a demo, but turn it off in real use.
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
