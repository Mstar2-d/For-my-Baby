import hmac
import os
import random
import uuid
from datetime import datetime
from functools import wraps

from flask import (
    Flask, Response, abort, flash, redirect, render_template, request, session, url_for,
)

import db
import drive_store
import movies
import planner

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local-dev-key-change-me")
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024   # total size of one upload

HER_NAME = "Mariah"
MY_NAME = "Maryan"
MAX_REPLY = 2000   # longest reply, in characters

# The password decides who gets in.
# On Render, set WRITER_PASSWORD and READER_PASSWORD so they aren't in your code.
PASSWORDS = {
    os.environ.get("WRITER_PASSWORD", "maryan123"): "writer",   # Maryan writes the letters
    os.environ.get("READER_PASSWORD", "mariah123"): "reader",   # Mariah reads the letters
}

# Writing prompts: edit or add your own
SPARKS = [
    "Tell her about the first moment you knew.",
    "Write about a small thing she does that no one else notices.",
    "Describe how your day feels different when she’s in it.",
    "Remember a night you never want to forget.",
    "Say the thing you’re always too shy to say out loud.",
    "Tell her what you’re looking forward to, together.",
    "Thank her for something she doesn’t know changed you.",
]

# Creates the letters and replies tables the first time the site starts
db.init_db()


def long_date():
    d = datetime.now()
    return f"{d.strftime('%A, %B')} {d.day}, {d.year}"


def short_date():
    d = datetime.now()
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def role_for_password(password):
    """Returns 'writer' or 'reader' if the password matches, otherwise None."""
    match = None
    for saved, role in PASSWORDS.items():
        # Check every password so the response time doesn't give hints
        if hmac.compare_digest(password.encode(), saved.encode()):
            match = role
    return match


def login_required(view):
    """Lets in anyone who is logged in (Maryan or Mariah)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") not in ("writer", "reader"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(role):
    """Only lets the given role in. Everyone else is sent where they belong."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            current = session.get("role")
            if current is None:
                return redirect(url_for("login"))
            if current != role:
                return redirect(url_for("home"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def who_is_logged_in():
    return MY_NAME if session.get("role") == "writer" else HER_NAME


def form_letter():
    return {
        "id": request.form.get("id", ""),
        "to": HER_NAME,      # always Mariah, whatever the form sends
        "sender": MY_NAME,   # always Maryan, whatever the form sends
        "body": request.form.get("body", ""),
    }


def page(letter=None, sealed=False, message=None):
    letter = letter or {"id": "", "to": HER_NAME, "sender": MY_NAME, "body": ""}
    return render_template(
        "index.html",
        letter=letter,
        letters=db.load_letters(),
        replies=db.replies_for(letter["id"]) if letter.get("id") else [],
        counts=db.reply_counts(),
        sealed=sealed,
        message=message,
        today=long_date(),
        words=len(letter["body"].split()),
        me=MY_NAME,
        her=HER_NAME,
    )


# ---------- Login ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("role") in ("writer", "reader"):
        return redirect(url_for("home"))

    error = None
    if request.method == "POST":
        role = role_for_password(request.form.get("password", ""))
        if role:
            session.clear()
            session["role"] = role
            return redirect(url_for("home"))
        error = "That password doesn’t match. Try again."

    return render_template("login.html", error=error)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
def home():
    role = session.get("role")
    if role == "reader":
        return redirect(url_for("read_list"))
    if role != "writer":
        return redirect(url_for("login"))
    return page(sealed=request.args.get("sealed") == "1")


# ---------- Reader (Mariah) ----------

@app.get("/read")
@role_required("reader")
def read_list():
    return render_template(
        "read.html",
        letters=db.load_letters(),
        letter=None,
        replies=[],
        counts=db.reply_counts(),
        her=HER_NAME,
        me=MY_NAME,
    )


@app.get("/read/<letter_id>")
@role_required("reader")
def read_letter(letter_id):
    letter = db.get_letter(letter_id)
    if not letter:
        return redirect(url_for("read_list"))
    return render_template(
        "read.html",
        letters=db.load_letters(),
        letter=letter,
        replies=db.replies_for(letter_id),
        counts=db.reply_counts(),
        her=HER_NAME,
        me=MY_NAME,
    )


@app.post("/reply/<letter_id>")
@role_required("reader")
def send_reply(letter_id):
    if not db.get_letter(letter_id):
        return redirect(url_for("read_list"))
    body = request.form.get("body", "").strip()[:MAX_REPLY]
    if body:
        db.add_reply(letter_id, body, short_date())
    else:
        flash("Write your reply first.")
    return redirect(url_for("read_letter", letter_id=letter_id, _anchor="replies"))


@app.post("/reply/delete/<letter_id>/<reply_id>")
@role_required("reader")
def remove_reply(letter_id, reply_id):
    db.delete_reply(letter_id, reply_id)
    return redirect(url_for("read_letter", letter_id=letter_id, _anchor="replies"))


# ---------- Writer (Maryan) ----------

@app.get("/letter/<letter_id>")
@role_required("writer")
def open_letter(letter_id):
    letter = db.get_letter(letter_id)
    if not letter:
        return redirect(url_for("home"))
    letter["to"] = HER_NAME
    letter["sender"] = MY_NAME
    return page(letter)


@app.post("/save")
@role_required("writer")
def save_letter():
    letter = form_letter()
    if not letter["body"].strip():
        return page(letter, message="Write a few words before sealing")

    letter["id"] = letter["id"] or uuid.uuid4().hex[:10]
    letter["date"] = short_date()
    db.save_letter(letter)

    # Back to a blank page so you can write the next letter
    return redirect(url_for("home", sealed=1))


@app.post("/spark")
@role_required("writer")
def spark():
    letter = form_letter()
    prompt = random.choice(SPARKS)
    prefix = letter["body"].rstrip() + "\n\n" if letter["body"].strip() else ""
    letter["body"] = prefix + prompt + " "
    return page(letter)


@app.post("/delete/<letter_id>")
@role_required("writer")
def delete_letter(letter_id):
    db.delete_letter(letter_id)
    return redirect(url_for("home"))


# ---------- Database check (temporary: delete this when you're done testing) ----------

@app.get("/dbcheck")
@role_required("writer")
def dbcheck():
    return f"Database: {db.engine.dialect.name} | Letters: {len(db.load_letters())}"


# ---------- Planner (Maryan and Mariah) ----------

@app.get("/planner")
@login_required
def planner_page():
    return render_template(
        "planner.html",
        board=planner.board(),
        today=planner.today().isoformat(),
    )


@app.post("/planner/add")
@login_required
def planner_add():
    added = planner.add_task(
        request.form.get("title", ""),
        request.form.get("due", ""),
        who_is_logged_in(),
    )
    if not added:
        flash("Write the task first.")
    return redirect(url_for("planner_page"))


@app.post("/planner/toggle/<task_id>")
@login_required
def planner_toggle(task_id):
    planner.toggle_task(task_id)
    return redirect(url_for("planner_page"))


@app.post("/planner/delete/<task_id>")
@login_required
def planner_delete(task_id):
    planner.delete_task(task_id)
    return redirect(url_for("planner_page"))


@app.post("/planner/clear-done")
@login_required
def planner_clear():
    planner.clear_done()
    return redirect(url_for("planner_page"))


# ---------- Movie checklist (Maryan and Mariah) ----------

@app.get("/movies")
@login_required
def movies_page():
    return render_template("movies.html", board=movies.board())


@app.post("/movies/add")
@login_required
def movies_add():
    if not movies.add_movie(request.form.get("title", ""), who_is_logged_in()):
        flash("Write the movie first.")
    return redirect(url_for("movies_page"))


@app.post("/movies/toggle/<movie_id>")
@login_required
def movie_toggle(movie_id):
    movies.toggle_movie(movie_id)
    return redirect(url_for("movies_page"))


@app.post("/movies/review/<movie_id>")
@login_required
def movie_review(movie_id):
    movies.save_review(
        movie_id,
        request.form.get("rating", "0"),
        request.form.get("comment", ""),
    )
    return redirect(url_for("movies_page"))


@app.post("/movies/delete/<movie_id>")
@login_required
def movie_delete(movie_id):
    movies.delete_movie(movie_id)
    return redirect(url_for("movies_page"))


@app.post("/movies/clear-watched")
@login_required
def movie_clear():
    movies.clear_watched()
    return redirect(url_for("movies_page"))


# ---------- Gallery (Maryan and Mariah) ----------

@app.get("/gallery")
@login_required
def gallery():
    try:
        photos = drive_store.list_photos()
    except Exception:
        app.logger.exception("Could not load the gallery")
        photos = []
        flash("Couldn’t reach the gallery right now. Please try again in a moment.")
    return render_template("gallery.html", photos=photos)


@app.post("/gallery/upload")
@login_required
def upload_photos():
    who = who_is_logged_in()
    caption = request.form.get("caption", "")
    files = [f for f in request.files.getlist("photos") if f and f.filename]
    if not files:
        flash("Choose at least one photo first.")
        return redirect(url_for("gallery"))

    added = skipped = 0
    for f in files:
        try:
            drive_store.save_photo(f.read(), who, caption)
            added += 1
        except drive_store.BadImage:
            skipped += 1
        except Exception:
            app.logger.exception("Photo upload failed")
            flash("Couldn’t save to the gallery. Please try again in a moment.")
            return redirect(url_for("gallery"))

    if added:
        flash(f"{added} {'photo' if added == 1 else 'photos'} added.")
    if skipped:
        flash(f"{skipped} skipped. Only JPG, PNG or WebP photos up to {drive_store.MAX_MB} MB work.")
    return redirect(url_for("gallery"))


@app.post("/gallery/caption/<photo_id>")
@login_required
def caption_photo(photo_id):
    try:
        drive_store.set_caption(photo_id, request.form.get("caption", ""))
    except Exception:
        app.logger.exception("Could not save a caption")
        flash("Couldn’t save that caption. Please try again.")
    return redirect(url_for("gallery"))


@app.get("/photo/<photo_id>")
@login_required
def photo(photo_id):
    try:
        data = drive_store.get_photo(photo_id)
    except Exception:
        app.logger.exception("Could not load a photo")
        data = None
    if data is None:
        abort(404)
    response = Response(data, mimetype="image/jpeg")
    response.headers["Cache-Control"] = "private, max-age=86400"
    return response


@app.post("/gallery/delete/<photo_id>")
@login_required
def delete_photo(photo_id):
    try:
        drive_store.delete_photo(photo_id)
    except Exception:
        app.logger.exception("Could not delete a photo")
        flash("Couldn’t delete that photo. Please try again.")
    return redirect(url_for("gallery"))


@app.errorhandler(413)
def too_big(error):
    flash("That upload is too large. Try fewer photos at a time.")
    return redirect(url_for("gallery"))


if __name__ == "__main__":
    app.run(debug=True)