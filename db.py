"""Letter storage in a SQLite file.

The file is called letters.db. It is saved in the folder named by the
DATA_DIR environment variable, or next to this file if DATA_DIR isn't set.
On Render, point DATA_DIR at a Persistent Disk so the file survives redeploys.
"""
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
DB_FILE = DATA_DIR / "letters.db"
OLD_JSON = Path(__file__).with_name("letters.json")


def _connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


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
    with closing(_connect()) as conn, conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS letters (
                id TEXT PRIMARY KEY,
                to_name TEXT NOT NULL,
                sender TEXT NOT NULL,
                body TEXT NOT NULL,
                written TEXT NOT NULL,
                created TEXT NOT NULL
            )
        """)
        _import_old_letters(conn)


def _import_old_letters(conn):
    """One time only: moves letters from the old letters.json into the database."""
    if not OLD_JSON.exists():
        return
    if conn.execute("SELECT COUNT(*) FROM letters").fetchone()[0]:
        return
    try:
        old = json.loads(OLD_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    base = datetime.now()
    for i, letter in enumerate(old):   # the old file is newest first
        conn.execute(
            """INSERT INTO letters (id, to_name, sender, body, written, created)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                letter["id"],
                letter.get("to", ""),
                letter.get("sender", ""),
                letter.get("body", ""),
                letter.get("date", ""),
                (base - timedelta(seconds=i)).isoformat(),
            ),
        )


def load_letters():
    """All letters, newest first."""
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM letters ORDER BY created DESC").fetchall()
    return [_letter(r) for r in rows]


def get_letter(letter_id):
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM letters WHERE id = ?", (letter_id,)).fetchone()
    return _letter(row) if row else None


def save_letter(letter):
    """Updates the letter if it exists, otherwise adds it as a new one."""
    with closing(_connect()) as conn, conn:
        updated = conn.execute(
            """UPDATE letters
               SET to_name = ?, sender = ?, body = ?, written = ?
               WHERE id = ?""",
            (letter["to"], letter["sender"], letter["body"], letter["date"], letter["id"]),
        ).rowcount
        if not updated:
            conn.execute(
                """INSERT INTO letters (id, to_name, sender, body, written, created)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    letter["id"],
                    letter["to"],
                    letter["sender"],
                    letter["body"],
                    letter["date"],
                    datetime.now().isoformat(),
                ),
            )


def delete_letter(letter_id):
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM letters WHERE id = ?", (letter_id,))