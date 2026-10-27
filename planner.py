"""The shared planner: a checklist where every task has a date.

Tasks are stored in the same database as the letters (see db.py), in a table
called "tasks". Dates are saved as YYYY-MM-DD text, so sorting by date works.
"""
import os
import re
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from db import engine

# Render's servers run on UTC, so "today" is worked out in your own timezone.
# Change it by setting a TIMEZONE environment variable (for example "Asia/Manila").
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Manila"))
SAFE_ID = re.compile(r"^[A-Za-z0-9]+$")
MAX_TITLE = 200


def today():
    return datetime.now(TZ).date()


def _init():
    """Creates the tasks table the first time the site starts."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                due TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                added_by TEXT NOT NULL,
                created TEXT NOT NULL
            )
        """))


_init()


# ---------- Dates ----------

def _label(d, t):
    """Heading for a day: Today, Tomorrow, Yesterday, or 'Saturday, Nov 1'."""
    if d == t:
        return "Today"
    if d == t + timedelta(days=1):
        return "Tomorrow"
    if d == t - timedelta(days=1):
        return "Yesterday"
    year = f", {d.year}" if d.year != t.year else ""
    return f"{d.strftime('%A, %b')} {d.day}{year}"


def _short(d, t):
    year = f", {d.year}" if d.year != t.year else ""
    return f"{d.strftime('%b')} {d.day}{year}"


# ---------- What main.py uses ----------

def board():
    """Everything the planner page needs: open tasks grouped by day, plus the done ones."""
    t = today()
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, title, due, done, added_by FROM tasks ORDER BY due ASC, created ASC"
        )).mappings().all()

    days = {}    # date -> open tasks, kept in date order
    done = []
    for r in rows:
        try:
            d = date.fromisoformat(r["due"])
        except ValueError:
            continue
        item = {
            "id": r["id"],
            "title": r["title"],
            "by": r["added_by"],
            "done": bool(r["done"]),
            "date_label": _short(d, t),
        }
        if item["done"]:
            done.append((d, item))
        else:
            days.setdefault(d, []).append(item)

    done.sort(key=lambda pair: pair[0], reverse=True)   # most recent first
    groups = [
        {"label": _label(d, t), "late": d < t, "tasks": tasks}
        for d, tasks in days.items()
    ]
    return {
        "groups": groups,
        "done": [item for _, item in done],
        "open_count": sum(len(g["tasks"]) for g in groups),
        "done_count": len(done),
    }


def add_task(title, due, who):
    title = " ".join(title.split())[:MAX_TITLE]
    if not title:
        return False
    try:
        d = date.fromisoformat(due)
    except ValueError:
        d = today()
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO tasks (id, title, due, done, added_by, created)
                    VALUES (:id, :title, :due, 0, :who, :created)"""),
            {
                "id": uuid.uuid4().hex,
                "title": title,
                "due": d.isoformat(),
                "who": who,
                "created": datetime.now().isoformat(),
            },
        )
    return True


def toggle_task(task_id):
    if not SAFE_ID.match(task_id):
        return
    with engine.begin() as conn:
        conn.execute(text("UPDATE tasks SET done = 1 - done WHERE id = :id"), {"id": task_id})


def delete_task(task_id):
    if not SAFE_ID.match(task_id):
        return
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tasks WHERE id = :id"), {"id": task_id})


def clear_done():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tasks WHERE done = 1"))