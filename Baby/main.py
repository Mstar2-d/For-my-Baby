import hmac
import json
import random
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = "change-this-to-a-long-random-text"

DATA = Path(__file__).with_name("letters.json")
HER_NAME = "Mariah"
MY_NAME = "Maryan"

# The password decides who gets in
PASSWORDS = {
    "maryan123": "writer",   # Maryan writes the letters
    "mariah123": "reader",   # Mariah reads the letters
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


def load_letters():
    try:
        return json.loads(DATA.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_letters(letters):
    DATA.write_text(json.dumps(letters, ensure_ascii=False, indent=2), encoding="utf-8")


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
        letters=load_letters(),
        sealed=sealed,
        message=message,
        today=long_date(),
        words=len(letter["body"].split()),
        me=MY_NAME,
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
    return render_template("read.html", letters=load_letters(), letter=None, her=HER_NAME, me=MY_NAME)


@app.get("/read/<letter_id>")
@role_required("reader")
def read_letter(letter_id):
    letters = load_letters()
    for letter in letters:
        if letter["id"] == letter_id:
            return render_template("read.html", letters=letters, letter=letter, her=HER_NAME, me=MY_NAME)
    return redirect(url_for("read_list"))


# ---------- Writer (Maryan) ----------

@app.get("/letter/<letter_id>")
@role_required("writer")
def open_letter(letter_id):
    for letter in load_letters():
        if letter["id"] == letter_id:
            letter["to"] = HER_NAME
            letter["sender"] = MY_NAME
            return page(letter)
    return redirect(url_for("home"))


@app.post("/save")
@role_required("writer")
def save_letter():
    letter = form_letter()
    letter["to"] = HER_NAME
    letter["sender"] = MY_NAME
    if not letter["body"].strip():
        return page(letter, message="Write a few words before sealing")

    letters = load_letters()
    letter_id = letter["id"] or uuid.uuid4().hex[:10]
    record = {**letter, "id": letter_id, "date": short_date()}

    for i, existing in enumerate(letters):
        if existing["id"] == letter_id:
            letters[i] = record
            break
    else:
        letters.insert(0, record)

    save_letters(letters)
    # Back to a blank page so you can write the next letter
    return redirect(url_for("home", sealed=1))


@app.post("/spark")
@role_required("writer")
def spark():
    letter = form_letter()
    letter["to"] = HER_NAME
    letter["sender"] = MY_NAME
    prompt = random.choice(SPARKS)
    prefix = letter["body"].rstrip() + "\n\n" if letter["body"].strip() else ""
    letter["body"] = prefix + prompt + " "
    return page(letter)


@app.post("/delete/<letter_id>")
@role_required("writer")
def delete_letter(letter_id):
    save_letters([l for l in load_letters() if l["id"] != letter_id])
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)