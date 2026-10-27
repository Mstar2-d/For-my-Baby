"""Letter storage.

Uses the Postgres database in the DATABASE_URL environment variable (Neon).
If it isn't set, it uses a local file called letters.db, which is fine for
testing on your own computer but is erased on Render when it redeploys.
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

OLD_JSON = Path(__file__).with_name("letters.json")


def _database_url():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///" + str(Path(__file__).with_name("letters.db"))
    # Neon gives "postgres://" or "postgresql://".
    # SQLAlchemy needs to be told to use the psycopg driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


engine = create_engine(_database_url(), pool_pre_ping=True, pool_recycle=300)


def _letter(row):
    """Turns a database row into the dictionary the pages already use."""
    return {
        "id": row["id"],
        "to": row["to_name"],
        "sender": row["sender"],
        "body": row["body"],
        "date": row["written"],
    }


def init_db():
    """Creates the table the first time, and copies in old letters.json if there is one."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS letters (
                id TEXT PRIMARY KEY,
                to_name TEXT NOT NULL,
                sender TEXT NOT NULL,
                body TEXT NOT NULL,
                written TEXT NOT NULL,
                created TEXT NOT NULL
            )
        """))
    _import_old_letters()


def _import_old_letters():
    """One time only: moves letters from an old letters.json into the database."""
    if not OLD_JSON.exists():
        return
    with engine.begin() as conn:
        if conn.execute(text("SELECT COUNT(*) FROM letters")).scalar():
            return
        try:
            old = json.loads(OLD_JSON.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        base = datetime.now()
        for i, letter in enumerate(old):   # the old file is newest first
            conn.execute(
                text("""INSERT INTO letters (id, to_name, sender, body, written, created)
                        VALUES (:id, :to, :sender, :body, :date, :created)"""),
                {
                    "id": letter["id"],
                    "to": letter.get("to", ""),
                    "sender": letter.get("sender", ""),
                    "body": letter.get("body", ""),
                    "date": letter.get("date", ""),
                    "created": (base - timedelta(seconds=i)).isoformat(),
                },
            )


def load_letters():
    """All letters, newest first."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM letters ORDER BY created DESC")).mappings().all()
    return [_letter(r) for r in rows]


def get_letter(letter_id):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM letters WHERE id = :id"), {"id": letter_id}
        ).mappings().first()
    return _letter(row) if row else None


def save_letter(letter):
    """Updates the letter if it exists, otherwise adds it as a new one."""
    params = {
        "id": letter["id"],
        "to": letter["to"],
        "sender": letter["sender"],
        "body": letter["body"],
        "date": letter["date"],
        "created": datetime.now().isoformat(),
    }
    with engine.begin() as conn:
        updated = conn.execute(
            text("""UPDATE letters
                    SET to_name = :to, sender = :sender, body = :body, written = :date
                    WHERE id = :id"""),
            params,
        ).rowcount
        if not updated:
            conn.execute(
                text("""INSERT INTO letters (id, to_name, sender, body, written, created)
                        VALUES (:id, :to, :sender, :body, :date, :created)"""),
                params,
            )


def delete_letter(letter_id):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM letters WHERE id = :id"), {"id": letter_id})