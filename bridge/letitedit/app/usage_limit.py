"""Was a turn of the AI stopped by its plan's usage limit, and when does the limit reset?

The editor asks this when a New video turn ends with an error or with words about a limit: a limit is waited out (the
window carries on by itself at the reset time plus a minute), not a failure. The wording is what the installed AIs
print (Claude Code: "You've hit your 5-hour limit · resets 3pm", "You've hit your weekly limit · resets Nov 14, 9am",
older "Claude AI usage limit reached|<epoch>"; Codex: "You've hit your usage limit. ... try again at 3:05 PM.").

    python usage_limit.py < {"text": "...", "engine": "claude"|"codex", "now": <epoch, optional>}
    -> {"limit": bool, "kind": "session"|"weekly"|"model"|"usage", "resets_at": <epoch>|null, "carry_at": <epoch>,
        "words": "<one plain sentence for the card and the chat>", "line": "<the AI's own line>"}
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys

# The AI's own sentences about a limit (ai_clis.LIMIT, narrowed to plan limits: a model's "rate limit" retry or a
# context limit is not a usage limit).
LIMIT = re.compile(r"hit your [\w' -]*limit|usage limit|limit reached|reached your [\w -]*limit|out of usage|"
                   r"limit will reset|quota exceeded|exceeded your [\w ]*quota", re.I)
NOT_A_PLAN_LIMIT = re.compile(r"context limit|prompt is too long|size limit|recursion limit|budget limit|spend limit|"
                              r"rate limit(?:ed)?(?! reached)", re.I)
WEEKLY = re.compile(r"weekly|seven[_ ]day|7-day", re.I)
SESSION = re.compile(r"5-hour|five[_ ]hour|session limit", re.I)
MODEL = re.compile(r"(opus|sonnet|fable) limit", re.I)
CARRY_DELAY_S = 60            # the reset plus a minute
RETRY_S = 30 * 60             # no reset time given: try again every 30 minutes
MONTHS = {m: i for i, m in enumerate(('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), 1)}
DAYS = {d: i for i, d in enumerate(('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'))}
TIME = r"(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?"
ZONE = r"(?:\s*\(([A-Za-z_]+/[A-Za-z_]+(?:/[A-Za-z_]+)?|UTC)\))?"


def _zone(name):
    if not name:
        return None
    if name.upper() == 'UTC':
        return dt.timezone.utc
    try:
        import zoneinfo
        return zoneinfo.ZoneInfo(name)
    except Exception:  # noqa: BLE001 - no time-zone database: the PC's own clock is the best guess
        return None


def _clock(hour, minute, ampm):
    hour, minute = int(hour), int(minute or 0)
    if ampm:
        ampm = ampm.replace('.', '').lower()
        if hour == 12:
            hour = 0
        if ampm == 'pm':
            hour += 12
    return (hour, minute) if 0 <= hour < 24 and 0 <= minute < 60 else None


def _duration(text):
    total = 0.0
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(d|days?|h|hrs?|hours?|m|mins?|minutes?|s|secs?|seconds?)\b", text, re.I):
        unit = unit[0].lower()
        total += float(amount) * {'d': 86400, 'h': 3600, 'm': 60, 's': 1}[unit]
    return total or None


def reset_time(line, now):
    """The epoch the limit resets at, from the AI's own words, or None."""
    epoch = re.search(r"\|(\d{10})\b", line)
    if epoch:
        return float(epoch.group(1))
    rel = re.search(r"(?:resets?|try again|available again)\s+in\s+([\d.]+\s*[a-z]+(?:[\s,]+(?:and\s+)?[\d.]+\s*[a-z]+)*)", line, re.I)
    if rel:
        seconds = _duration(rel.group(1))
        if seconds:
            return now + seconds
    when = re.search(r"(?:resets?(?:\s+at)?|reset at|try again at|available again at|until)\s+(.{1,60})", line, re.I)
    if not when:
        return None
    words = when.group(1)
    found = re.search(TIME + ZONE, words, re.I)
    # "Nov 14, 9am" / "14 Nov 2026 9:05 AM" / "Friday 9am" / "tomorrow at 3pm" / "3pm (America/Los_Angeles)"
    clock = None
    for match in re.finditer(TIME + ZONE, words, re.I):
        if match.group(2) or match.group(3):          # 3:05 or 3pm: a time, not a day of the month
            found, clock = match, _clock(match.group(1), match.group(2), match.group(3))
            break
    if not clock:
        return None
    zone = _zone(found.group(4)) if found.group(4) else None
    base = dt.datetime.fromtimestamp(now, zone) if zone else dt.datetime.fromtimestamp(now).astimezone()
    month_day = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b", words, re.I) or None
    day_month = re.search(r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?:\s+(\d{4}))?", words, re.I)
    weekday = re.search(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", words, re.I)
    target = base.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
    if month_day or day_month:
        if month_day:
            month, day, year = MONTHS[month_day.group(1).lower()], int(month_day.group(2)), base.year
        else:
            month, day = MONTHS[day_month.group(2).lower()], int(day_month.group(1))
            year = int(day_month.group(3) or base.year)
        try:
            target = target.replace(year=year, month=month, day=day)
        except ValueError:
            return None
        if target < base - dt.timedelta(days=1) and not (day_month and day_month.group(3)):
            target = target.replace(year=year + 1)
    elif weekday:
        ahead = (DAYS[weekday.group(1).lower()] - base.weekday()) % 7
        target = target + dt.timedelta(days=ahead)
        if target <= base:
            target += dt.timedelta(days=7)
    elif re.search(r"\btomorrow\b", words, re.I):
        target += dt.timedelta(days=1)
    elif target <= base:
        target += dt.timedelta(days=1)
    return target.timestamp()


def _said(when, now):
    local = dt.datetime.fromtimestamp(when).astimezone()
    clock = local.strftime('%I:%M %p').lstrip('0').replace('AM', 'am').replace('PM', 'pm')
    today = dt.datetime.fromtimestamp(now).astimezone().date()
    if local.date() == today:
        return f'at {clock}'
    if local.date() == today + dt.timedelta(days=1):
        return f'tomorrow at {clock}'
    if (local.date() - today).days < 7:
        return f"on {local.strftime('%A')} at {clock}"
    return f"on {local.strftime('%A')} {local.day} {local.strftime('%B')} at {clock}"


def read(text, engine='claude', now=None):
    import time
    now = time.time() if now is None else float(now)
    lines = [ln.strip() for ln in (text or '').splitlines() if ln.strip()]
    line = next((ln for ln in lines if LIMIT.search(ln) and not NOT_A_PLAN_LIMIT.search(ln)), '')
    if not line:
        return {'limit': False}
    nearby = ' '.join(lines[max(0, lines.index(line) - 1):lines.index(line) + 3])
    kind = 'weekly' if WEEKLY.search(nearby) else 'session' if SESSION.search(nearby) else (
        'model' if MODEL.search(nearby) else 'usage')
    resets = reset_time(nearby, now)
    if resets is not None and resets < now - 60:
        resets = None                                 # a time already gone by is no reset time
    plan = 'Your ChatGPT plan' if engine == 'codex' else 'Your Claude plan'
    what = {'weekly': "weekly usage limit", 'session': "5-hour usage limit",
            'model': "usage limit for this model"}.get(kind, 'usage limit')
    if resets is not None:
        words = (f"{plan}'s {what} was reached. It resets {_said(resets, now)}. "
                 "letitedit will carry on by itself then; keep letitedit open.")
        carry = resets + CARRY_DELAY_S
    else:
        words = (f"{plan}'s {what} was reached, and it didn't say when it resets. "
                 "letitedit will try again every 30 minutes; keep letitedit open.")
        carry = now + RETRY_S
    return {'limit': True, 'kind': kind, 'resets_at': resets, 'carry_at': carry, 'words': words, 'line': line[:200]}


def main():
    data = json.loads(sys.stdin.buffer.read().decode('utf-8', 'replace') or '{}')
    print(json.dumps(read(data.get('text') or '', data.get('engine') or 'claude', data.get('now'))))


if __name__ == '__main__':
    main()
