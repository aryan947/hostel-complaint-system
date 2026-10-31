# Hostel Complaint Management & Tracking System

B.Tech CSBS (Second Year, Sem III) Field Project / PBL, TKIET, Warana.
Stack: **Python Flask + SQLite + HTML/CSS/JS + Chart.js**

## Run it
```bash
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000

(Optional) load sample data for the demo: `python seed_demo.py`
Chart.js loads from a CDN, so the Statistics page needs internet.

## Logins
| Role | Username | Password |
|---|---|---|
| Warden | `warden` | `warden123` |
| Student | register on the site (or `prn101` / `student123` after seed_demo.py) |

Change the warden password and set a `SECRET_KEY` environment variable before real use.

## Features
**Website:** public landing page (hero, live stats, how it works, features) at `/`, split login/register pages, mobile friendly.

**Student:** register / login, file a complaint (category, priority, description, optional photo),
track status with a progress timeline, confirm the fix and rate it (or reopen if not fixed).

**Warden:** dashboard with filters (status, category, priority, block, room), assign maintenance
staff, update status with notes, manage staff, statistics (by category, status, average resolution
time, rooms with repeated complaints, average rating), automatic **Overdue** flag
(Urgent after 1 day, Normal after 3 days).

## Workflow
Submitted -> Assigned -> In Progress -> Resolved -> student confirms (or reopens)

## Project structure
```
app.py            Flask routes, database, business logic
seed_demo.py      optional sample data
templates/        HTML pages (Jinja2)
static/style.css  styling
uploads/          complaint photos
hostel.db         SQLite database (created on first run)
```

## Database tables
users, categories, staff, complaints, history (status timeline), feedback

## Suggested demo flow
1. Student registers and files "Fan not working" (Urgent) with a photo.
2. Warden filters Electrical, assigns an electrician, sets In Progress, then Resolved.
3. Student sees the timeline, confirms the fix and rates it.
4. Warden opens Statistics.

## Possible extensions
Email/SMS notifications, anonymous complaints, password reset, deployment on PythonAnywhere / Render.
