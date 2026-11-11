"""The shared movie checklist, with saved reviews.

Movies and reviews are stored in the same database as the letters (see db.py),
in two tables: "movie_items" and "movie_reviews". A movie can have as many
reviews as you like, from both of you.
"""
import logging
import re
import uuid
from datetime import datetime

from sqlalchemy import inspect, text

import planner
from db import engine

log = logging.getLogger(__name__)

SAFE_ID = re.compile(r"^[A-Za-z0-9]+$")
MAX_TITLE = 120
MAX_COMMENT = 600


def _init():
    """Creates the tables the first time the site starts."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS movie_items (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                added_by TEXT NOT NULL,
                watched INTEGER NOT NULL DEFAULT 0,
                created TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS movie_reviews (
                id TEXT PRIMARY KEY,
                movie_id TEXT NOT NULL,
                author TEXT NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT NOT NULL,
                created TEXT NOT NULL
            )
        """))
    try:
        _import_old()
    except Exception:
        log.exception("Couldn’t copy the old movie list")


def _import_old():
    """One time only: copies movies (and any single review) from the old "movies" table."""
    insp = inspect(engine)
    if "movies" not in insp.get_table_names():
        return
    with engine.connect() as conn:
        if conn.execute(text("SELECT COUNT(*) FROM movie_items")).scalar():
            return

    cols = {c["name"] for c in insp.get_columns("movies")}
    if "title" not in cols:
        return

    def pick(*names):
        return next((n for n in names if n in cols), None)

    c_who = pick("added_by", "who", "owner")
    c_done = pick("watched", "done")
    c_made = pick("created")
    c_rate = pick("rating")
    c_note = pick("comment", "review", "note")

    wanted = []
    for name in ("title", c_who, c_done, c_made, c_rate, c_note):
        if name and name not in wanted:
            wanted.append(name)

    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT {', '.join(wanted)} FROM movies")).mappings().all()

    now = datetime.now().isoformat()
    with engine.begin() as conn:
        for r in rows:
            title = " ".join(str(r["title"] or "").split())[:MAX_TITLE]
            if not title:
                continue
            who = str(r[c_who]) if c_who and r[c_who] else "Us"
            made = str(r[c_made]) if c_made and r[c_made] else now
            movie_id = uuid.uuid4().hex

            rating = 0
            if c_rate and r[c_rate]:
                try:
                    rating = int(r[c_rate])
                except (TypeError, ValueError):
                    rating = 0
            has_review = 1 <= rating <= 5
            watched = 1 if (c_done and r[c_done]) or has_review else 0

            conn.execute(
                text("""INSERT INTO movie_items (id, title, added_by, watched, created)
                        VALUES (:id, :title, :who, :watched, :created)"""),
                {"id": movie_id, "title": title, "who": who, "watched": watched, "created": made},
            )
            if has_review:
                comment = str(r[c_note] or "") if c_note else ""
                conn.execute(
                    text("""INSERT INTO movie_reviews (id, movie_id, author, rating, comment, created)
                            VALUES (:id, :movie_id, :author, :rating, :comment, :created)"""),
                    {
                        "id": uuid.uuid4().hex,
                        "movie_id": movie_id,
                        "author": who,
                        "rating": rating,
                        "comment": comment.strip()[:MAX_COMMENT],
                        "created": made,
                    },
                )


_init()


def _date(iso):
    try:
        when = datetime.fromisoformat(iso)
        return f"{when.strftime('%b')} {when.day}, {when.year}"
    except (TypeError, ValueError):
        return ""


# ---------- What main.py uses ----------

def board():
    """Everything the movie page needs: movies to watch, and watched ones with their reviews."""
    with engine.connect() as conn:
        films = conn.execute(text(
            "SELECT id, title, added_by, watched FROM movie_items ORDER BY created DESC"
        )).mappings().all()
        reviews = conn.execute(text(
            "SELECT id, movie_id, author, rating, comment, created FROM movie_reviews ORDER BY created ASC"
        )).mappings().all()

    by_movie = {}
    for r in reviews:
        by_movie.setdefault(r["movie_id"], []).append({
            "id": r["id"],
            "author": r["author"],
            "rating": int(r["rating"]),
            "comment": r["comment"],
            "date": _date(r["created"]),
        })

    todo, watched = [], []
    for f in films:
        item = {"id": f["id"], "title": f["title"], "by": f["added_by"]}
        if f["watched"]:
            revs = by_movie.get(f["id"], [])
            item["reviews"] = revs
            item["count"] = len(revs)
            if revs:
                avg = sum(r["rating"] for r in revs) / len(revs)
                item["avg_round"] = int(avg + 0.5)
                item["avg_text"] = f"{avg:.1f}".removesuffix(".0")
            watched.append(item)
        else:
            todo.append(item)

    return {
        "todo": todo,
        "watched": watched,
        "todo_count": len(todo),
        "watched_count": len(watched),
    }


def add_movie(title, who):
    title = " ".join(title.split())[:MAX_TITLE]
    if not title:
        return False
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO movie_items (id, title, added_by, watched, created)
                    VALUES (:id, :title, :who, 0, :created)"""),
            {
                "id": uuid.uuid4().hex,
                "title": title,
                "who": who,
                "created": datetime.now(planner.TZ).isoformat(),
            },
        )
    return True


def toggle_movie(movie_id):
    if not SAFE_ID.match(movie_id):
        return
    with engine.begin() as conn:
        conn.execute(text("UPDATE movie_items SET watched = 1 - watched WHERE id = :id"), {"id": movie_id})


def delete_movie(movie_id):
    """Deletes the movie and every review written about it."""
    if not SAFE_ID.match(movie_id):
        return
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM movie_reviews WHERE movie_id = :id"), {"id": movie_id})
        conn.execute(text("DELETE FROM movie_items WHERE id = :id"), {"id": movie_id})


def add_review(movie_id, who, rating, comment):
    """Adds one more review. Returns None when it worked, or a message saying what to fix."""
    if not SAFE_ID.match(movie_id):
        return "That movie couldn’t be found."
    try:
        stars = int(rating)
    except (TypeError, ValueError):
        stars = 0
    if stars not in range(1, 6):
        return "Pick a star rating first."
    comment = comment.strip()[:MAX_COMMENT]

    with engine.begin() as conn:
        found = conn.execute(
            text("SELECT 1 FROM movie_items WHERE id = :id"), {"id": movie_id}
        ).first()
        if not found:
            return "That movie couldn’t be found."
        conn.execute(
            text("""INSERT INTO movie_reviews (id, movie_id, author, rating, comment, created)
                    VALUES (:id, :movie_id, :author, :rating, :comment, :created)"""),
            {
                "id": uuid.uuid4().hex,
                "movie_id": movie_id,
                "author": who,
                "rating": stars,
                "comment": comment,
                "created": datetime.now(planner.TZ).isoformat(),
            },
        )
    return None


def delete_review(review_id, who):
    """You can only delete your own reviews."""
    if not SAFE_ID.match(review_id):
        return
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM movie_reviews WHERE id = :id AND author = :who"),
            {"id": review_id, "who": who},
        )