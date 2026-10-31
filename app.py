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
              "Furniture", "Internet / Wi-Fi", "Security", "Other"]
# The life cycle of a complaint, in order. The warden moves a complaint along these steps.
STATUSES = ["Submitted", "Assigned", "In Progress", "Resolved"]
# Normal or Urgent. Urgent is meant only for water, electricity or safety problems.
PRIORITIES = ["Normal", "Urgent"]
# A complaint still open after this many days is flagged "Overdue" (auto-escalation)
OVERDUE_DAYS = {"Normal": 3, "Urgent": 1}

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
    role TEXT NOT NULL CHECK (role IN ('student','warden')),
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
    resolved_at TEXT
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
# the categories, a default warden account and some sample staff.
# INSERT OR IGNORE skips rows that already exist.
# The ? marks are placeholders: values are passed separately, which prevents SQL injection.
def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    for c in CATEGORIES:
        db.execute("INSERT OR IGNORE INTO categories(name) VALUES (?)", (c,))
    # Create the default warden login only if no warden exists yet (the password is stored hashed).
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
    return redirect(url_for("admin_dashboard" if g.user["role"] == "warden" else "student_dashboard"))


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
    if request.method == "POST":
        title = request.form["title"].strip()
        desc = request.form["description"].strip()
        cat_id = request.form.get("category_id", type=int)
        priority = request.form.get("priority", "Normal")
        if not title or not desc or not cat_id or priority not in PRIORITIES:
            flash("Please fill in all required fields.", "error")
            return render_template("new_complaint.html", cats=cats, priorities=PRIORITIES)
        photo_name = None
        f = request.files.get("photo")
        # The photo is optional. Check the file extension, then save it with a random prefix so two
        # files never clash. secure_filename removes dangerous characters from the file name.
        if f and f.filename:
            ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
            if ext not in ALLOWED_EXT:
                flash("Photo must be a PNG, JPG, GIF or WEBP image.", "error")
                return render_template("new_complaint.html", cats=cats, priorities=PRIORITIES)
            photo_name = secrets.token_hex(8) + "_" + secure_filename(f.filename)
            f.save(os.path.join(UPLOAD_DIR, photo_name))
        ts = now()
        # Save the complaint. cur.lastrowid is the new complaint id (used for the history row and the redirect).
        cur = db.execute(
            """INSERT INTO complaints(student_id, category_id, title, description, photo, priority, status, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (g.user["id"], cat_id, title, desc, photo_name, priority, "Submitted", ts))
        db.execute("INSERT INTO history(complaint_id, status, note, at) VALUES (?,?,?,?)",
                   (cur.lastrowid, "Submitted", "Complaint registered by student", ts))
        db.commit()
        flash(f"Complaint #{cur.lastrowid} submitted.", "ok")
        return redirect(url_for("view_complaint", cid=cur.lastrowid))
    return render_template("new_complaint.html", cats=cats, priorities=PRIORITIES)


# Complaint detail page. <int:cid> in the URL becomes the cid argument, e.g. /complaint/9.
# LEFT JOIN keeps the complaint even if no staff member is assigned yet.
# A student may open only their own complaints (else 403); the warden may open any.
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
@app.route("/admin")
@login_required("warden")
def admin_dashboard():
    db = get_db()
    status = request.args.get("status", "")
    cat = request.args.get("category", type=int)
    block = request.args.get("block", "").strip().upper()
    room = request.args.get("room", "").strip()
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
    if room:
        sql += " AND u.room_no=?"; args.append(room)
    if prio in PRIORITIES:
        sql += " AND c.priority=?"; args.append(prio)
    sql += " ORDER BY (c.status='Resolved'), (c.priority='Urgent') DESC, c.id DESC"
    rows = db.execute(sql, args).fetchall()
    cats = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    totals = {s: db.execute("SELECT COUNT(*) FROM complaints WHERE status=?", (s,)).fetchone()[0] for s in STATUSES}
    overdue = sum(1 for r in db.execute("SELECT * FROM complaints").fetchall() if is_overdue(r))
    return render_template("admin_dashboard.html", complaints=rows, cats=cats, totals=totals,
                           overdue=overdue, priorities=PRIORITIES,
                           f=dict(status=status, category=cat, block=block, room=room, priority=prio))


# Warden updates a complaint: assign staff, change status, add a note.
# Rules: choosing staff on a Submitted complaint makes it Assigned; a complaint cannot move forward without staff.
# resolved_at is saved only when the status becomes Resolved.
# Every change is written to the history table, which is what the Progress Timeline shows.
@app.route("/admin/complaint/<int:cid>/update", methods=["POST"])
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
@app.route("/admin/staff", methods=["GET", "POST"])
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
@app.route("/admin/stats")
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
