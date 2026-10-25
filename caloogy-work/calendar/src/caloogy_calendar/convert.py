"""Turning other calendars' events (Feishu / Lark JSON, Google-style JSON, .ics) into Caloogy events, and back.

A Caloogy event lives on one day, in local wall-clock time:
    {date: "YYYY-MM-DD", start: "HH:MM" | None, end: "HH:MM" | None, title, location, attendees, meeting_url}
no start = an all-day / untimed item. So a timed event that crosses midnight becomes one piece per day, and an
all-day event that spans several days becomes one untimed item per day.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Iterable

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None  # type: ignore

DEFAULT_MINUTES = 30          # what the calendar draws for an event with a start but no end
MAX_SPAN_DAYS = 62            # longer all-day / multi-day events are cut here


class ConvertError(ValueError):
    pass


def local_zone(name: str | None = None) -> tzinfo:
    if name:
        if ZoneInfo is None:
            raise ConvertError("--tz needs Python 3.9+")
        try:
            return ZoneInfo(name)
        except Exception:
            raise ConvertError(f"Unknown time zone: {name}")
    return datetime.now().astimezone().tzinfo or timezone.utc


# ---------------------------------------------------------------- reading one time value

def _zone_or(name: Any, fallback: tzinfo) -> tzinfo:
    if isinstance(name, str) and name and ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return fallback


def parse_when(v: Any, tz: tzinfo, src_tz: tzinfo | None = None) -> datetime | date | None:
    """A point in time (aware datetime) or a whole day (date). None when it can't be read."""
    if v is None or v == "":
        return None
    if isinstance(v, dict):
        zone = _zone_or(v.get("timezone") or v.get("timeZone") or v.get("tzid"), src_tz or tz)
        for key in ("timestamp", "dateTime", "datetime", "date_time", "time"):
            if v.get(key) not in (None, ""):
                return parse_when(v[key], tz, zone)
        if v.get("date"):
            return parse_when(str(v["date"]), tz, zone)
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\d{9,13}", v.strip())):
        n = float(v)
        if n > 1e12:
            n /= 1000.0
        return datetime.fromtimestamp(n, tz=timezone.utc)
    if not isinstance(v, str):
        return None
    s = v.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return date.fromisoformat(s)
    if re.fullmatch(r"\d{8}", s):                                   # ICS VALUE=DATE
        return date(int(s[:4]), int(s[4:6]), int(s[6:]))
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?(Z?)", s)   # ICS date-time
    if m:
        dt = datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5]), int(m[6] or 0))
        return dt.replace(tzinfo=timezone.utc) if m[7] else dt.replace(tzinfo=src_tz or tz)
    s2 = s.replace(" ", "T", 1) if re.match(r"\d{4}-\d{2}-\d{2} \d", s) else s
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    s2 = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s2)              # +0800 -> +08:00
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=src_tz or tz)


# ---------------------------------------------------------------- one foreign event -> Caloogy pieces

def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return None


def _text(v: Any, limit: int) -> str | None:
    if v is None:
        return None
    if isinstance(v, dict):
        v = _first(v, "name", "display_name", "displayName", "address", "title")
    if not isinstance(v, str):
        v = str(v)
    v = " ".join(v.split())
    return v[:limit] or None


def _attendees(v: Any) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        v = re.split(r"[,，;；]", v)
    out = []
    for a in v if isinstance(v, list) else []:
        if isinstance(a, dict):
            if a.get("is_organizer") and a.get("type") == "resource":
                continue
            a = _first(a, "display_name", "displayName", "name", "email", "user_id")
        name = _text(a, 100)
        if name:
            name = re.sub(r"[,，;；]", " ", name).strip()
            if name and name not in out:
                out.append(name)
    return out[:100]


def _meeting_url(e: dict) -> str | None:
    for v in (e.get("meeting_url"), (e.get("vchat") or {}).get("meeting_url") if isinstance(e.get("vchat"), dict) else None,
              e.get("hangoutLink"), e.get("url")):
        if isinstance(v, str) and re.match(r"^https?://\S+$", v) and ")" not in v:
            return v[:500]
    return None


def hhmm(t: time | datetime) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def to_caloogy(e: dict, tz: tzinfo, all_day_end: str = "inclusive") -> list[dict]:
    """Pieces of one event, each on one day. [] for cancelled / unreadable ones.
    all_day_end: whether an all-day event's end date is the last day ("inclusive", Feishu) or the day after
    ("exclusive", ICS / Google)."""
    if not isinstance(e, dict):
        return []
    status = str(e.get("status") or "").lower()
    if status in ("cancelled", "canceled", "removed"):
        return []
    title = _text(_first(e, "summary", "title", "name", "subject", "text"), 500) or "(No title)"
    if re.match(r"^\d{1,2}:\d{2}", title):                    # a leading time would be read as the event's time
        title = "· " + title
    extra = {
        "location": _text(_first(e, "location", "place"), 300),
        "attendees": _attendees(_first(e, "attendees", "participants")),
        "meeting_url": _meeting_url(e),
    }
    zone = _zone_or(e.get("timezone") or e.get("timeZone"), tz)
    start = parse_when(_first(e, "start", "start_time", "startTime", "dtstart", "begin"), tz, zone)
    end = parse_when(_first(e, "end", "end_time", "endTime", "dtend", "finish"), tz, zone)
    # an explicit {date, start: "HH:MM"} (our own export format) — keep as is
    if isinstance(e.get("date"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["date"]) and not isinstance(start, datetime):
        s = e.get("start") if isinstance(e.get("start"), str) and re.fullmatch(r"\d{1,2}:\d{2}", e["start"]) else None
        en = e.get("end") if s and isinstance(e.get("end"), str) and re.fullmatch(r"\d{1,2}:\d{2}", e["end"]) else None
        pad = lambda x: f"{int(x.split(':')[0]):02d}:{x.split(':')[1]}" if x else None
        return [{"date": e["date"], "start": pad(s), "end": pad(en), "title": title, **extra}]
    if start is None:
        return []

    if not isinstance(start, datetime):                       # all-day
        last = end if isinstance(end, date) and not isinstance(end, datetime) else start
        if all_day_end == "exclusive" and last > start:
            last -= timedelta(days=1)
        last = min(max(last, start), start + timedelta(days=MAX_SPAN_DAYS - 1))
        days = (last - start).days + 1
        return [{"date": (start + timedelta(days=i)).isoformat(), "start": None, "end": None, "title": title, **extra}
                for i in range(days)]

    s = start.astimezone(tz)
    if isinstance(end, datetime):
        en = end.astimezone(tz)
    elif isinstance(end, date):
        en = datetime.combine(end, time(0), tz)
    else:
        en = None
    if en is None or en <= s:
        return [{"date": s.date().isoformat(), "start": hhmm(s), "end": None, "title": title, **extra}]
    pieces = []
    day = s.date()
    while len(pieces) < MAX_SPAN_DAYS:
        day_end = datetime.combine(day + timedelta(days=1), time(0), tz)
        a = s if day == s.date() else datetime.combine(day, time(0), tz)
        b = min(en, day_end)
        if b > a:
            pieces.append({"date": day.isoformat(), "start": hhmm(a),
                           "end": "24:00" if b >= day_end else hhmm(b), "title": title, **extra})
        if en <= day_end:
            break
        day += timedelta(days=1)
    return pieces


# ---------------------------------------------------------------- whole inputs

def events_in(data: Any) -> list[dict]:
    """The list of events inside whatever JSON a tool printed: a list, or {events | items | data | ...: [...]}."""
    if isinstance(data, list):
        out: list[dict] = []
        for x in data:
            # some tools group by day: [{date, events: [...]}]
            if isinstance(x, dict) and isinstance(x.get("events"), list) and not _first(x, "summary", "title"):
                out.extend(events_in(x["events"]))
            elif isinstance(x, dict):
                out.append(x)
        return out
    if isinstance(data, dict):
        for k in ("events", "items", "data", "results", "list", "event_list", "instances"):
            if k in data:
                found = events_in(data[k])
                if found or isinstance(data[k], list):
                    return found
        if _first(data, "summary", "title", "start", "start_time"):
            return [data]
    return []


def unfold_ics(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def ics_unescape(v: str) -> str:
    return re.sub(r"\\([,;\\nN])", lambda m: "\n" if m[1] in "nN" else m[1], v)


def events_from_ics(text: str, tz: tzinfo) -> tuple[list[dict], int]:
    """(events as dicts parse_when understands, number of recurring events skipped)"""
    out: list[dict] = []
    cur: dict | None = None
    skipped = 0
    for line in unfold_ics(text):
        if line == "BEGIN:VEVENT":
            cur = {}
            continue
        if line == "END:VEVENT":
            if cur is not None:
                if cur.pop("_rrule", False):
                    skipped += 1
                else:
                    out.append(cur)
            cur = None
            continue
        if cur is None or ":" not in line:
            continue
        head, value = line.split(":", 1)
        name, *params = head.split(";")
        p = dict(x.split("=", 1) for x in params if "=" in x)
        name = name.upper()
        if name in ("DTSTART", "DTEND"):
            if p.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
                cur["start" if name == "DTSTART" else "end"] = value
            else:
                cur["start" if name == "DTSTART" else "end"] = {"datetime": value, "timezone": p.get("TZID")}
        elif name == "SUMMARY":
            cur["summary"] = ics_unescape(value)
        elif name == "LOCATION":
            cur["location"] = ics_unescape(value)
        elif name == "STATUS":
            cur["status"] = value
        elif name == "URL":
            cur["url"] = value
        elif name == "RRULE":
            cur["_rrule"] = True
        elif name == "ATTENDEE":
            cur.setdefault("attendees", []).append(p.get("CN", "").strip('"') or value.replace("mailto:", ""))
    return out, skipped


def load_foreign(text: str, tz: tzinfo, all_day_end: str | None = None) -> tuple[list[dict], dict]:
    """Caloogy pieces from a JSON or ICS document; plus counts {events, skipped_recurring}."""
    stripped = text.lstrip()
    if stripped.startswith("BEGIN:VCALENDAR") or stripped.startswith("BEGIN:VEVENT"):
        raw, skipped = events_from_ics(text, tz)
        mode = all_day_end or "exclusive"
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ConvertError(f"Not JSON or ICS: {e}")
        if isinstance(data, dict) and (data.get("ok") is False or (data.get("error") and not events_in(data))):
            err = data.get("error")
            msg = err.get("message") if isinstance(err, dict) else err
            raise ConvertError(f"The input is an error from the other tool, not events: {msg or data}")
        raw, skipped = events_in(data), 0
        mode = all_day_end or "inclusive"
    pieces = [p for e in raw for p in to_caloogy(e, tz, mode)]
    return pieces, {"events": len(raw), "skipped_recurring": skipped}


def key_of(ev: dict) -> tuple[str, str, str]:
    """What makes two events "the same" for syncing: day, start, title (the calendar's own duplicate rule)."""
    return (ev.get("date") or "", ev.get("start") or "", " ".join(str(ev.get("title") or "").split()).casefold())


# ---------------------------------------------------------------- Caloogy -> other calendars

def iso_range(ev: dict, tz: tzinfo) -> tuple[str | None, str | None]:
    """ISO 8601 start / end with offset for a timed event (end defaults to +30 min, 24:00 = next midnight)."""
    if not ev.get("start"):
        return None, None
    d = date.fromisoformat(ev["date"])
    h, m = map(int, ev["start"].split(":"))
    s = datetime.combine(d, time(h, m), tz)
    if ev.get("end"):
        eh, em = map(int, ev["end"].split(":"))
        e = datetime.combine(d, time(0), tz) + timedelta(hours=eh, minutes=em)
    else:
        e = s + timedelta(minutes=DEFAULT_MINUTES)
    return s.isoformat(timespec="minutes"), e.isoformat(timespec="minutes")


def export_event(ev: dict, tz: tzinfo) -> dict:
    s, e = iso_range(ev, tz)
    return {
        "id": ev.get("id"), "title": ev.get("title"), "date": ev.get("date"),
        "start": ev.get("start"), "end": ev.get("end"), "all_day": not ev.get("start"),
        "start_iso": s, "end_iso": e, "done": bool(ev.get("done")),
        "location": ev.get("location"), "attendees": ev.get("attendees") or [], "meeting_url": ev.get("meeting_url"),
    }


def ics_escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def to_ics(events: Iterable[dict], tz: tzinfo) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Caloogy//caloogy-calendar//EN", "CALSCALE:GREGORIAN"]
    for ev in events:
        out += ["BEGIN:VEVENT", f"UID:{ev.get('id')}@calendar.caloogy.com", f"DTSTAMP:{stamp}",
                f"SUMMARY:{ics_escape(ev.get('title') or '')}"]
        if ev.get("start"):
            s, e = iso_range(ev, tz)
            for k, v in (("DTSTART", s), ("DTEND", e)):
                out.append(f"{k}:{datetime.fromisoformat(v).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
        else:
            d = date.fromisoformat(ev["date"])
            out += [f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}"]
        if ev.get("location"):
            out.append(f"LOCATION:{ics_escape(ev['location'])}")
        if ev.get("meeting_url"):
            out.append(f"URL:{ev['meeting_url']}")
        out.append("END:VEVENT")
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"
