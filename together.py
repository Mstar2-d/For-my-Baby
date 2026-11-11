"""The day counter and the monthsary / anniversary banners.

The start date is June 15, 2026. To use a different date, set a START_DATE
environment variable in Render (for example 2025-06-15), or change the date below.
"""
import calendar
import os
from datetime import date

import planner

DEFAULT_START = date(2026, 6, 15)

# False: the start date itself is day 0, so tomorrow is day 1.
# True:  the start date is day 1.
COUNT_START_DAY = False


def _start_date():
    raw = os.environ.get("START_DATE", "").strip()
    try:
        return date.fromisoformat(raw) if raw else DEFAULT_START
    except ValueError:
        return DEFAULT_START


START_DATE = _start_date()


def _add_months(d, n):
    """The same day, n months later (a short month uses its last day)."""
    index = d.month - 1 + n
    year = d.year + index // 12
    month = index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _full_months(today):
    """How many whole months have passed since the start date."""
    months = (today.year - START_DATE.year) * 12 + today.month - START_DATE.month
    if today.day < START_DATE.day:
        months -= 1
    return max(months, 0)


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _in_days(n):
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    return f"in {n} days"


def info():
    """Everything the dashboard needs to show the counter and the banner."""
    today = planner.today()
    since = f"{START_DATE.strftime('%b')} {START_DATE.day}, {START_DATE.year}"

    # Before the start date: count down instead
    if today < START_DATE:
        to_go = (START_DATE - today).days
        return {
            "started": False,
            "since": since,
            "to_go_text": _plural(to_go, "day"),
            "banner": None,
        }

    days = (today - START_DATE).days + (1 if COUNT_START_DAY else 0)
    months = _full_months(today)
    leftover = (today - _add_months(START_DATE, months)).days
    years = months // 12

    # The banner: only on the day itself
    banner = None
    if months >= 1 and today == _add_months(START_DATE, months):
        if months % 12 == 0:
            banner = {
                "kind": "anniversary",
                "text": "Happy Anniversary!!",
                "sub": f"{_plural(years, 'year')} together",
            }
        else:
            banner = {
                "kind": "monthsary",
                "text": "Happy Monthsary!!",
                "sub": f"{_plural(months, 'month')} together",
            }

    # What comes next
    next_date = _add_months(START_DATE, months + 1)
    next_in = (next_date - today).days
    next_name = "anniversary" if (months + 1) % 12 == 0 else "monthsary"

    return {
        "started": True,
        "since": since,
        "days": days,
        "days_text": f"{days:,}",
        "unit": "day" if days == 1 else "days",
        "breakdown": f"{_plural(months, 'month')} · {_plural(leftover, 'day')}",
        "next_text": f"Next {next_name} {_in_days(next_in)}",
        "banner": banner,
    }