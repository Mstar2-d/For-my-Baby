"""The series and episode tracker on the Movies page.

Series are looked up on TVmaze (a free TV database), so the seasons and the
number of episodes are the real ones, not typed by hand. Series and episodes are
saved in the same database as the letters (see db.py), in two tables:
"series_shows" and "series_eps".
"""
import json
import logging
import re
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime

from sqlalchemy import text

import planner
from db import engine

log = logging.getLogger(__name__)

API = "https://api.tvmaze.com"
SAFE_ID = re.compile(r"^[A-Za-z0-9]+$")


class LookupFailed(Exception):
    """The TV database couldn't be reached, or didn't know that show."""


def _init():
    """Creates the tables the first time the site starts."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS series_shows (
                id TEXT PRIMARY KEY,
                tvmaze_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                year TEXT NOT NULL,
                network TEXT NOT NULL,
                added_by TEXT NOT NULL,
                created TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS series_eps (
                id TEXT PRIMARY KEY,
                show_id TEXT NOT NULL,
                tvmaze_ep INTEGER NOT NULL,
                season INTEGER NOT NULL,
                number INTEGER NOT NULL,
                name TEXT NOT NULL,
                airdate TEXT NOT NULL,
                watched INTEGER NOT NULL DEFAULT 0
            )
        """))


_init()


# ---------- Talking to TVmaze ----------

def _get(path):
    request = urllib.request.Request(
        API + path,
        headers={"User-Agent": "dear-you-site/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as error:
        log.warning("TVmaze lookup failed for %s: %s", path, error)
        raise LookupFailed(path) from error


def _meta(show):
    """'2019 · Netflix · Ended'"""
    bits = []
    year = (show.get("premiered") or "")[:4]
    if year:
        bits.append(year)
    network = (show.get("network") or {}).get("name") or (show.get("webChannel") or {}).get("name")
    if network:
        bits.append(network)
    if show.get("status"):
        bits.append(show["status"])
    return " · ".join(bits)


def _pretty(iso):
    try:
        d = date.fromisoformat(iso)
        return f"{d.strftime('%b')} {d.day}, {d.year}"
    except (TypeError, ValueError):
        return ""


def search(query):
    """Up to six matching series, for the 'pick the right one' list."""
    data = _get("/search/shows?q=" + urllib.parse.quote(query))
    with engine.connect() as conn:
        added = {r[0] for r in conn.execute(text("SELECT tvmaze_id FROM series_shows"))}
    results = []
    for item in data[:6]:
        show = item.get("show") or {}
        if not show.get("id"):
            continue
        image = (show.get("image") or {}).get("medium") or ""
        if image.startswith("http://"):
            image = "https://" + image[7:]
        results.append({
            "id": show["id"],
            "title": show.get("name") or "",
            "meta": _meta(show),
            "image": image,
            "added": show["id"] in added,
        })
    return results


def _fetch_show(tvmaze_id):
    """The show's details and its regular episodes (specials are left out)."""
    data = _get(f"/shows/{int(tvmaze_id)}?embed=episodes")
    info = {
        "title": (data.get("name") or "").strip() or "Untitled",
        "status": data.get("status") or "",
        "year": (data.get("premiered") or "")[:4],
        "network": (data.get("network") or {}).get("name")
        or (data.get("webChannel") or {}).get("name")
        or "",
    }
    episodes = []
    for e in (data.get("_embedded") or {}).get("episodes") or []:
        if e.get("number") is None or e.get("season") is None:
            continue
        if e.get("type", "regular") != "regular":
            continue
        episodes.append({
            "tvmaze_ep": e["id"],
            "season": int(e["season"]),
            "number": int(e["number"]),
            "name": (e.get("name") or "").strip() or f"Episode {e['number']}",
            "airdate": e.get("airdate") or "",
        })
    episodes.sort(key=lambda x: (x["season"], x["number"]))
    return info, episodes


# ---------- What main.py uses ----------

def board():
    """Every series with its seasons, episodes and progress."""
    today = planner.today().isoformat()
    with engine.connect() as conn:
        shows = conn.execute(text(
            "SELECT id, title, status, year, network FROM series_shows ORDER BY created DESC"
        )).mappings().all()
        rows = conn.execute(text(
            "SELECT id, show_id, season, number, name, airdate, watched "
            "FROM series_eps ORDER BY show_id, season, number"
        )).mappings().all()

    by_show = {}
    for r in rows:
        by_show.setdefault(r["show_id"], []).append(r)

    result = []
    for s in shows:
        seasons = {}
        aired = watched = 0
        up_next = None
        episodes = by_show.get(s["id"], [])

        for e in episodes:
            is_aired = bool(e["airdate"]) and e["airdate"] <= today
            is_watched = bool(e["watched"])
            item = {
                "id": e["id"],
                "number": e["number"],
                "code": f"S{e['season']}E{e['number']}",
                "name": e["name"],
                "aired": is_aired,
                "watched": is_watched,
                "when": _pretty(e["airdate"]) if is_aired else (
                    f"Airs {_pretty(e['airdate'])}" if e["airdate"] else "Date to be announced"
                ),
            }
            seasons.setdefault(e["season"], []).append(item)
            if is_aired:
                aired += 1
                if is_watched:
                    watched += 1
                elif up_next is None:
                    up_next = item

        season_list = []
        for number in sorted(seasons):
            eps = seasons[number]
            s_aired = sum(1 for x in eps if x["aired"])
            s_watched = sum(1 for x in eps if x["aired"] and x["watched"])
            season_list.append({
                "number": number,
                "episodes": eps,
                "total": len(eps),
                "aired": s_aired,
                "watched": s_watched,
                "complete": s_aired > 0 and s_watched == s_aired,
            })

        done = aired > 0 and watched == aired
        result.append({
            "id": s["id"],
            "title": s["title"],
            "meta": " · ".join(x for x in (s["year"], s["network"], s["status"]) if x),
            "total": len(episodes),
            "aired": aired,
            "watched": watched,
            "upcoming": len(episodes) - aired,
            "percent": round(watched * 100 / aired) if aired else 0,
            "next": up_next,
            "done": done,
            "done_text": "Finished" if s["status"] == "Ended" else "Caught up",
            "seasons": season_list,
        })
    return result


def add_show(tvmaze_id, who):
    """Returns None when it worked, or a message saying what went wrong."""
    try:
        tv_id = int(tvmaze_id)
    except (TypeError, ValueError):
        return "That series couldn’t be found."

    with engine.connect() as conn:
        if conn.execute(text("SELECT 1 FROM series_shows WHERE tvmaze_id = :t"), {"t": tv_id}).first():
            return "That series is already on your list."

    try:
        info, episodes = _fetch_show(tv_id)
    except LookupFailed:
        return "Couldn’t reach the TV database right now. Please try again in a moment."
    if not episodes:
        return "That series has no episodes listed yet, so there’s nothing to track."

    show_id = uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO series_shows (id, tvmaze_id, title, status, year, network, added_by, created)
                    VALUES (:id, :tv, :title, :status, :year, :network, :who, :created)"""),
            {
                "id": show_id, "tv": tv_id, "title": info["title"], "status": info["status"],
                "year": info["year"], "network": info["network"], "who": who,
                "created": datetime.now(planner.TZ).isoformat(),
            },
        )
        conn.execute(
            text("""INSERT INTO series_eps (id, show_id, tvmaze_ep, season, number, name, airdate, watched)
                    VALUES (:id, :show, :ep, :season, :number, :name, :airdate, 0)"""),
            [
                {
                    "id": uuid.uuid4().hex, "show": show_id, "ep": e["tvmaze_ep"],
                    "season": e["season"], "number": e["number"],
                    "name": e["name"], "airdate": e["airdate"],
                }
                for e in episodes
            ],
        )
    return None


def refresh_show(show_id):
    """Looks for new episodes. Returns a message saying what happened."""
    if not SAFE_ID.match(show_id):
        return "That series couldn’t be found."
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT tvmaze_id FROM series_shows WHERE id = :id"), {"id": show_id}
        ).first()
    if not row:
        return "That series couldn’t be found."

    try:
        info, episodes = _fetch_show(row[0])
    except LookupFailed:
        return "Couldn’t reach the TV database right now. Please try again in a moment."
    if not episodes:
        return "The TV database returned no episodes, so nothing was changed."

    added = removed = 0
    with engine.begin() as conn:
        known = {
            r[0]: r[1]
            for r in conn.execute(
                text("SELECT tvmaze_ep, id FROM series_eps WHERE show_id = :s"), {"s": show_id}
            )
        }
        for e in episodes:
            if e["tvmaze_ep"] in known:
                conn.execute(
                    text("""UPDATE series_eps SET season = :season, number = :number,
                            name = :name, airdate = :airdate WHERE id = :id"""),
                    {
                        "id": known[e["tvmaze_ep"]], "season": e["season"], "number": e["number"],
                        "name": e["name"], "airdate": e["airdate"],
                    },
                )
            else:
                conn.execute(
                    text("""INSERT INTO series_eps (id, show_id, tvmaze_ep, season, number, name, airdate, watched)
                            VALUES (:id, :show, :ep, :season, :number, :name, :airdate, 0)"""),
                    {
                        "id": uuid.uuid4().hex, "show": show_id, "ep": e["tvmaze_ep"],
                        "season": e["season"], "number": e["number"],
                        "name": e["name"], "airdate": e["airdate"],
                    },
                )
                added += 1

        # Episodes the database no longer lists are removed, unless you ticked them
        current = {e["tvmaze_ep"] for e in episodes}
        for tv_ep, ep_id in known.items():
            if tv_ep not in current:
                removed += conn.execute(
                    text("DELETE FROM series_eps WHERE id = :id AND watched = 0"), {"id": ep_id}
                ).rowcount

        conn.execute(
            text("""UPDATE series_shows SET title = :title, status = :status,
                    year = :year, network = :network WHERE id = :id"""),
            {"id": show_id, **info},
        )

    bits = []
    if added:
        bits.append(f"{added} new {'episode' if added == 1 else 'episodes'} added")
    if removed:
        bits.append(f"{removed} {'episode' if removed == 1 else 'episodes'} removed")
    return (", ".join(bits) + ".") if bits else "Already up to date."


def toggle_episode(ep_id):
    """Ticks or unticks one episode. Episodes that haven't aired yet can't be ticked."""
    if not SAFE_ID.match(ep_id):
        return
    today = planner.today().isoformat()
    with engine.begin() as conn:
        conn.execute(
            text("""UPDATE series_eps SET watched = 1 - watched
                    WHERE id = :id AND airdate != '' AND airdate <= :today"""),
            {"id": ep_id, "today": today},
        )


def mark_next(show_id):
    """Ticks the first aired episode that isn't watched yet."""
    if not SAFE_ID.match(show_id):
        return
    today = planner.today().isoformat()
    with engine.begin() as conn:
        row = conn.execute(
            text("""SELECT id FROM series_eps
                    WHERE show_id = :s AND watched = 0 AND airdate != '' AND airdate <= :today
                    ORDER BY season, number LIMIT 1"""),
            {"s": show_id, "today": today},
        ).first()
        if row:
            conn.execute(text("UPDATE series_eps SET watched = 1 WHERE id = :id"), {"id": row[0]})


def mark_season(show_id, season, watched):
    if not SAFE_ID.match(show_id):
        return
    today = planner.today().isoformat()
    with engine.begin() as conn:
        conn.execute(
            text("""UPDATE series_eps SET watched = :w
                    WHERE show_id = :s AND season = :season AND airdate != '' AND airdate <= :today"""),
            {"w": 1 if watched else 0, "s": show_id, "season": season, "today": today},
        )


def delete_show(show_id):
    if not SAFE_ID.match(show_id):
        return
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM series_eps WHERE show_id = :s"), {"s": show_id})
        conn.execute(text("DELETE FROM series_shows WHERE id = :s"), {"s": show_id})