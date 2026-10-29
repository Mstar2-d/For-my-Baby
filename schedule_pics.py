"""Pictures of your school schedule, shown on the dashboard.

Pictures are shrunk to a readable size, saved as JPEGs, and stored in the same
database as the letters (see db.py), in a table called "schedule_pics".
"""
import io
import re
import uuid
from datetime import datetime

from PIL import Image, ImageOps
from sqlalchemy import text

import planner
from db import engine

MAX_MB = 10        # biggest file accepted
MAX_SIDE = 2400    # the longest side is shrunk to this many pixels (big enough to read a timetable)
SAFE_ID = re.compile(r"^[A-Za-z0-9]+$")

Image.MAX_IMAGE_PIXELS = 60_000_000


class BadImage(Exception):
    """The file isn't a usable picture."""


def _init():
    """Creates the table the first time the site starts."""
    binary = "BYTEA" if engine.dialect.name == "postgresql" else "BLOB"
    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS schedule_pics (
                id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                label TEXT NOT NULL,
                created TEXT NOT NULL,
                data {binary} NOT NULL
            )
        """))


_init()


def prepare(data):
    """Checks the file is a real JPG/PNG/WebP, fixes its rotation,
    shrinks it, and returns it as a JPEG."""
    if not data or len(data) > MAX_MB * 1024 * 1024:
        raise BadImage("empty or too big")
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in ("JPEG", "PNG", "WEBP"):
            raise BadImage("unsupported type")
        img = ImageOps.exif_transpose(img).convert("RGB")
    except BadImage:
        raise
    except Exception as e:
        raise BadImage("not an image") from e

    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()


def _date(iso):
    try:
        when = datetime.fromisoformat(iso)
        return f"{when.strftime('%b')} {when.day}, {when.year}"
    except ValueError:
        return ""


def list_pics(owner=None):
    """Newest first. Pass a name to see only that person's pictures.
    Doesn't load the pictures themselves, only their details."""
    sql = "SELECT id, owner, label, created FROM schedule_pics"
    params = {}
    if owner:
        sql += " WHERE owner = :owner"
        params["owner"] = owner
    sql += " ORDER BY created DESC"
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [
        {"id": r["id"], "owner": r["owner"], "label": r["label"], "date": _date(r["created"])}
        for r in rows
    ]


def save_pic(data, owner, label):
    jpeg = prepare(data)
    label = " ".join(label.split())[:60]
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO schedule_pics (id, owner, label, created, data)
                    VALUES (:id, :owner, :label, :created, :data)"""),
            {
                "id": uuid.uuid4().hex,
                "owner": owner,
                "label": label,
                "created": datetime.now(planner.TZ).isoformat(),
                "data": jpeg,
            },
        )


def get_pic(pic_id):
    """Returns the picture's bytes, or None if it doesn't exist."""
    if not SAFE_ID.match(pic_id):
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT data FROM schedule_pics WHERE id = :id"), {"id": pic_id}
        ).first()
    return bytes(row[0]) if row else None


def delete_pic(pic_id):
    if not SAFE_ID.match(pic_id):
        return
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM schedule_pics WHERE id = :id"), {"id": pic_id})