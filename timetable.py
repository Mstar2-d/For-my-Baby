"""The shared school schedule.

Classes are stored in the same database as the letters (see db.py), in a table
called "classes". Times are saved as HH:MM text (24-hour), so sorting works.
"Today" and "Now" use the planner's timezone (the TIMEZONE environment variable).
"""
import re
import uuid
from datetime import datetime

from sqlalchemy import text

import planner
from db import engine

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SAFE_ID = re.compile(r"^[A-Za-z0-9]+$")


def _init():
    """Creates the classes table the first time the site starts."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS classes (
                id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                weekday INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                subject TEXT NOT NULL,
                room TEXT NOT NULL,
                notes TEXT NOT NULL,
                created TEXT NOT NULL
            )
        """))


_init()


# ---------- Checking what was typed ----------

def _clean(day, start, end, subject, room, notes):
    """Returns (values, None) if everything is fine, or (None, message) if not."""
    subject = " ".join(subject.split())[:80]
    room = " ".join(room.split())[:40]
    notes = " ".join(notes.split())[:200]
    if not subject:
        return None, "Write the subject first."

    try:
        weekday = int(day)
    except ValueError:
        weekday = -1
    if weekday not in range(7):
        return None, "Pick a day."

    try:
        begins = datetime.strptime(start[:5], "%H:%M")
        ends = datetime.strptime(end[:5], "%H:%M")
    except ValueError:
        return None, "Pick a start and an end time."
    if ends <= begins:
        return None, "The end time has to be after the start time."

    return {
        "weekday": weekday,
        "start": begins.strftime("%H:%M"),
        "end": ends.strftime("%H:%M"),
        "subject": subject,
        "room": room,
        "notes": notes,
    }, None


def _label(hhmm):
    """'13:05' becomes '1:05 PM'."""
    return datetime.strptime(hhmm, "%H:%M").strftime("%I:%M %p").lstrip("0")


# ---------- What main.py uses ----------

def board(who=None):
    """Everything the dashboard needs. Pass a name to see only that person's classes."""
    t = planner.today()
    now = datetime.now(planner.TZ).strftime("%H:%M")
    today_index = t.weekday()

    sql = "SELECT id, owner, weekday, start_time, end_time, subject, room, notes FROM classes"
    params = {}
    if who:
        sql += " WHERE owner = :who"
        params["who"] = who
    sql += " ORDER BY weekday ASC, start_time ASC, owner ASC"

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    by_day = {i: [] for i in range(7)}
    for r in rows:
        if r["weekday"] not in by_day:
            continue
        by_day[r["weekday"]].append({
            "id": r["id"],
            "owner": r["owner"],
            "weekday": r["weekday"],
            "start": r["start_time"],
            "end": r["end_time"],
            "start_label": _label(r["start_time"]),
            "end_label": _label(r["end_time"]),
            "subject": r["subject"],
            "room": r["room"],
            "notes": r["notes"],
            "status": "",
        })

    # Today's classes: done, happening now, or coming up (next one per person)
    todays = by_day[today_index]
    has_next = set()
    for c in todays:
        if c["end"] <= now:
            c["status"] = "done"
        elif c["start"] <= now:
            c["status"] = "now"
        elif c["owner"] not in has_next:
            c["status"] = "next"
            has_next.add(c["owner"])

    days = []
    for i, name in enumerate(DAYS):
        if i >= 5 and not by_day[i] and i != today_index:
            continue    # weekends only show up when something is on them
        days.append({
            "index": i,
            "name": name,
            "today": i == today_index,
            "classes": by_day[i],
        })

    return {
        "days": days,
        "today": {
            "index": today_index,
            "name": DAYS[today_index],
            "date": f"{t.strftime('%b')} {t.day}",
            "classes": todays,
        },
        "total": len(rows),
    }


def add_class(owner, day, start, end, subject, room, notes):
    """Returns None when it worked, or a message saying what to fix."""
    values, error = _clean(day, start, end, subject, room, notes)
    if error:
        return error
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO classes
                    (id, owner, weekday, start_time, end_time, subject, room, notes, created)
                    VALUES (:id, :owner, :weekday, :t_start, :t_end, :subject, :room, :notes, :created)"""),
            {
                "id": uuid.uuid4().hex,
                "owner": owner,
                "weekday": values["weekday"],
                "t_start": values["start"],
                "t_end": values["end"],
                "subject": values["subject"],
                "room": values["room"],
                "notes": values["notes"],
                "created": datetime.now().isoformat(),
            },
        )
    return None


def update_class(class_id, owner, day, start, end, subject, room, notes):
    """Returns None when it worked, or a message saying what to fix."""
    if not SAFE_ID.match(class_id):
        return "That class couldn’t be found."
    values, error = _clean(day, start, end, subject, room, notes)
    if error:
        return error
    with engine.begin() as conn:
        conn.execute(
            text("""UPDATE classes
                    SET owner = :owner, weekday = :weekday, start_time = :t_start,
                        end_time = :t_end, subject = :subject, room = :room, notes = :notes
                    WHERE id = :id"""),
            {
                "id": class_id,
                "owner": owner,
                "weekday": values["weekday"],
                "t_start": values["start"],
                "t_end": values["end"],
                "subject": values["subject"],
                "room": values["room"],
                "notes": values["notes"],
            },
        )
    return None


def delete_class(class_id):
    if not SAFE_ID.match(class_id):
        return
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM classes WHERE id = :id"), {"id": class_id})