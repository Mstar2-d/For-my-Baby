"""Our movie checklist: films we mean to watch together, each with a star rating
and a short comment.

Movies live in their own table called "movies" in the same database as the
letters (see db.py). This is kept separate from the planner on purpose.
"""
import re
import uuid
from datetime import datetime

from sqlalchemy import inspect, text

from db import engine

SAFE_ID = re.compile(r"^[A-Za-z0-9]+$")
MAX_TITLE = 200
MAX_STARS = 5
MAX_COMMENT = 300


def _init():
    """Creates the movies table the first time the site starts."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS movies (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                added_by TEXT NOT NULL,
                watched INTEGER NOT NULL DEFAULT 0,
                rating INTEGER NOT NULL DEFAULT 0,
                comment TEXT NOT NULL DEFAULT '',
                created TEXT NOT NULL
            )
        """))

    # Lists made before comments existed need the column added.
    existing = {c["name"] for c in inspect(engine).get_columns("movies")}
    if "comment" not in existing:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE movies ADD COLUMN comment TEXT NOT NULL DEFAULT ''"))


_init()


def _movie(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "by": row["added_by"],
        "watched": bool(row["watched"]),
        "rating": int(row["rating"] or 0),
        "comment": row["comment"] or "",
    }


# ---------- What main.py uses ----------

def board():
    """Everything the movies page needs: the watchlist and the watched ones."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, title, added_by, watched, rating, comment FROM movies ORDER BY created ASC"
        )).mappings().all()

    movies = [_movie(r) for r in rows]
    to_watch = [m for m in movies if not m["watched"]]
    watched = [m for m in movies if m["watched"]]
    watched.reverse()   # most recently added first
    return {
        "to_watch": to_watch,
        "watched": watched,
        "to_watch_count": len(to_watch),
        "watched_count": len(watched),
    }


def add_movie(title, who):
    title = " ".join(title.split())[:MAX_TITLE]
    if not title:
        return False
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO movies (id, title, added_by, watched, rating, created)
                    VALUES (:id, :title, :who, 0, 0, :created)"""),
            {
                "id": uuid.uuid4().hex,
                "title": title,
                "who": who,
                "created": datetime.now().isoformat(),
            },
        )
    return True


def toggle_movie(movie_id):
    """Marks a movie watched, or puts it back on the watchlist."""
    if not SAFE_ID.match(movie_id):
        return
    with engine.begin() as conn:
        conn.execute(text("UPDATE movies SET watched = 1 - watched WHERE id = :id"), {"id": movie_id})


def save_review(movie_id, rating, comment):
    """Sets the 0-5 star rating and the comment on a movie."""
    if not SAFE_ID.match(movie_id):
        return
    try:
        stars = int(rating)
    except (TypeError, ValueError):
        stars = 0
    stars = max(0, min(MAX_STARS, stars))
    comment = (comment or "").strip()[:MAX_COMMENT]
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE movies SET rating = :rating, comment = :comment WHERE id = :id"),
            {"id": movie_id, "rating": stars, "comment": comment},
        )


def delete_movie(movie_id):
    if not SAFE_ID.match(movie_id):
        return
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM movies WHERE id = :id"), {"id": movie_id})


def clear_watched():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM movies WHERE watched = 1"))
