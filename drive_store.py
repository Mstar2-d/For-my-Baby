"""Photo storage for the gallery.

Uses Google Drive when the three GOOGLE_* environment variables are set.
Otherwise photos are saved in a local "uploads" folder (handy for testing).
"""
import io
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

FOLDER_NAME = "Dear You Gallery"   # the folder created in Google Drive
MAX_MB = 10                        # biggest file accepted
MAX_SIDE = 1600                    # photos are shrunk so the longest side is this many pixels
LOCAL_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent)) / "uploads"
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")

Image.MAX_IMAGE_PIXELS = 60_000_000


class BadImage(Exception):
    """The file isn't a usable photo."""


def drive_enabled():
    keys = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")
    return all(os.environ.get(k) for k in keys)


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


def _new_name(uploader):
    # Name format: 20261026143000_Maryan_a1b2c3.jpg
    # (date, who uploaded it, random part), so no database is needed.
    who = re.sub(r"[^A-Za-z]", "", uploader) or "x"
    return f"{datetime.now():%Y%m%d%H%M%S}_{who}_{uuid.uuid4().hex[:6]}.jpg"


def _info(photo_id, name):
    try:
        stamp, who, _ = Path(name).stem.split("_", 2)
        when = datetime.strptime(stamp, "%Y%m%d%H%M%S")
        date = f"{when.strftime('%b')} {when.day}, {when.year}"
    except ValueError:
        who, date = "", ""
    return {"id": photo_id, "by": who, "date": date}


# ---------- Google Drive ----------

_service = None
_folder_id = None


def _drive():
    global _service
    if _service is None:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=None,
            refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            token_uri="https://oauth2.googleapis.com/token",
            scopes=["https://www.googleapis.com/auth/drive.file"],
        )
        _service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _service


def _folder():
    """Finds the gallery folder in Drive, or creates it the first time."""
    global _folder_id
    if _folder_id:
        return _folder_id
    query = (
        f"name = '{FOLDER_NAME}' and trashed = false "
        "and mimeType = 'application/vnd.google-apps.folder'"
    )
    found = _drive().files().list(q=query, fields="files(id)", pageSize=1).execute()
    files = found.get("files", [])
    if files:
        _folder_id = files[0]["id"]
    else:
        meta = {"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"}
        _folder_id = _drive().files().create(body=meta, fields="id").execute()["id"]
    return _folder_id


# ---------- What main.py uses ----------

def list_photos():
    """Newest first."""
    if drive_enabled():
        result = _drive().files().list(
            q=f"'{_folder()}' in parents and trashed = false",
            fields="files(id,name)",
            orderBy="name desc",
            pageSize=200,
        ).execute()
        return [_info(f["id"], f["name"]) for f in result.get("files", [])]

    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    names = sorted((p.name for p in LOCAL_DIR.glob("*.jpg")), reverse=True)
    return [_info(n, n) for n in names]


def save_photo(data, uploader):
    jpeg = prepare(data)
    name = _new_name(uploader)

    if drive_enabled():
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(io.BytesIO(jpeg), mimetype="image/jpeg")
        meta = {"name": name, "parents": [_folder()]}
        _drive().files().create(body=meta, media_body=media, fields="id").execute()
    else:
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        (LOCAL_DIR / name).write_bytes(jpeg)


def get_photo(photo_id):
    """Returns the photo's bytes, or None if it doesn't exist."""
    if not SAFE_ID.match(photo_id):
        return None
    if drive_enabled():
        return _drive().files().get_media(fileId=photo_id).execute()

    path = LOCAL_DIR / photo_id
    if photo_id.endswith(".jpg") and path.is_file():
        return path.read_bytes()
    return None


def delete_photo(photo_id):
    if not SAFE_ID.match(photo_id):
        return
    if drive_enabled():
        _drive().files().delete(fileId=photo_id).execute()
    else:
        path = LOCAL_DIR / photo_id
        if photo_id.endswith(".jpg") and path.is_file():
            path.unlink()