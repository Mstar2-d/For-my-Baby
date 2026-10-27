"""Photo storage for the gallery, inside the same database as the letters.

Photos are shrunk to a sensible size, saved as JPEGs, and stored in a table
called "photos" in the database that db.py already uses (Neon on Render).
Google Drive is not used.
"""
import io
import re
import uuid
from datetime import datetime

from PIL import Image, ImageOps
from sqlalchemy import inspect, text

from db import engine

MAX_MB = 10        # biggest file accepted
MAX_SIDE = 1600    # photos are shrunk so the longest side is this many pixels
MAX_CAPTION = 300  # longest caption kept
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")

Image.MAX_IMAGE_PIXELS = 60_000_000


class BadImage(Exception):
    """The file isn't a usable photo."""


def _init():
    """Creates the photos table the first time the site starts."""
    binary = "BYTEA" if engine.dialect.name == "postgresql" else "BLOB"
    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS photos (
                id TEXT PRIMARY KEY,
                uploader TEXT NOT NULL,
                created TEXT NOT NULL,
                caption TEXT NOT NULL DEFAULT '',
                data {binary} NOT NULL
            )
        """))

    # Galleries made before captions existed need the column added.
    existing = {c["name"] for c in inspect(engine).get_columns("photos")}
    if "caption" not in existing:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE photos ADD COLUMN caption TEXT NOT NULL DEFAULT ''"))


_init()


# ---------- Preparing a photo ----------

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
    img.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


def _date(iso):
    try:
        when = datetime.fromisoformat(iso)
        return f"{when.strftime('%b')} {when.day}, {when.year}"
    except ValueError:
        return ""


# ---------- What main.py uses ----------

def list_photos():
    """Newest first. Doesn't load the pictures themselves, only their details."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, uploader, created, caption FROM photos ORDER BY created DESC LIMIT 200"
        )).mappings().all()
    return [{
        "id": r["id"],
        "by": r["uploader"],
        "date": _date(r["created"]),
        "caption": r["caption"] or "",
    } for r in rows]


def _clean_caption(caption):
    return (caption or "").strip()[:MAX_CAPTION]


def save_photo(data, uploader, caption=""):
    jpeg = prepare(data)
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO photos (id, uploader, created, caption, data)
                    VALUES (:id, :who, :created, :caption, :data)"""),
            {
                "id": uuid.uuid4().hex,
                "who": uploader,
                "created": datetime.now().isoformat(),
                "caption": _clean_caption(caption),
                "data": jpeg,
            },
        )


def set_caption(photo_id, caption):
    """Adds or changes the caption on an existing photo."""
    if not SAFE_ID.match(photo_id):
        return
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE photos SET caption = :caption WHERE id = :id"),
            {"id": photo_id, "caption": _clean_caption(caption)},
        )


def get_photo(photo_id):
    """Returns the photo's bytes, or None if it doesn't exist."""
    if not SAFE_ID.match(photo_id):
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT data FROM photos WHERE id = :id"), {"id": photo_id}
        ).first()
    return bytes(row[0]) if row else None


def delete_photo(photo_id):
    if not SAFE_ID.match(photo_id):
        return
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM photos WHERE id = :id"), {"id": photo_id})