"""Public Google Calendar (.ics) feeds: a generic iCalendar reader plus a FEEDS list.

Feeds: UB Economic Theory seminars (sites.google.com/view/ubtecoseminars), UAB Department of Business
research seminars (sites.google.com/view/seminars-business-uab), Bellaterra Applied Working Group (uabufae.eu).
"""
import datetime as dt
import re
from zoneinfo import ZoneInfo

from collect import get, text_lines, local_iso

SOURCE = "Google Calendar feeds"
MAD = ZoneInfo("Europe/Madrid")
UTC = dt.timezone.utc
GCAL = "https://calendar.google.com/calendar/ical/{}/public/basic.ics"
UB_THEORY = "https://sites.google.com/view/ubtecoseminars/"

# Each feed: the ICS url, defaults for every event, and ordered `rules`. A rule applies when its optional
# `match` regex matches the start of SUMMARY (the matched text is then removed) and its optional `weekday`
# (Monday = 0) equals the event's; the first rule that applies wins. `skip: True` drops the event, any
# other key overrides the feed default. Without a matching rule the feed defaults are used as they are.
FEEDS = [
    {
        "ics": GCAL.format("f75c70b204be2267a21bd58d1035478b4d43bd02503de72f815e3d66dad46771%40group.calendar.google.com"),
        "url": UB_THEORY + "home", "inst": "UB", "host": "UB Economic Theory group",
        "series": "Economic Theory Seminar", "kind": "seminar", "field": "Micro & theory",
        # the series' site: "Unless otherwise specified, all seminars take place in room 2302 (Avinguda Diagonal 696)"
        "location": "Room 2302, Av. Diagonal 696", "campus": "Diagonal campus", "no_titles": True,
        "rules": [
            {"match": r"External(?: Seminar)?\s*:"},
            {"match": r"Internal(?: Seminar)?\s*:", "series": "Economic Theory Internal Seminar",
             "internal": True, "url": UB_THEORY + "thursday-seminars"},
            {"weekday": 3, "series": "Economic Theory Internal Seminar",  # Thursdays are the internal ones
             "internal": True, "url": UB_THEORY + "thursday-seminars"},
        ],
    },
    {
        "ics": GCAL.format("seminars.business.uab%40gmail.com"),
        "url": "https://sites.google.com/view/seminars-business-uab/upcoming-seminars",
        "inst": "UAB", "host": "UAB Department of Business", "series": "UAB Business Research Seminar",
        "kind": "seminar", "field": "Management", "campus": "Bellaterra campus", "no_titles": True,
        "rules": [{"match": r"Seminar\s*:?\s+(?=[A-Z])"}],  # 2025-26 style "Seminar Name (Affil)"
    },
    {
        "ics": GCAL.format("tn10eo2jiref6n2gm38vbfdaok%40group.calendar.google.com"),
        "url": "https://uabufae.eu/seminars/applied-seminars", "inst": "UAB",
        "host": "UAB economics and IAE-CSIC", "series": "Bellaterra Applied Working Group",
        "kind": "workshop", "field": "Applied & policy", "campus": "Bellaterra campus", "no_titles": True,
        "rules": [
            {"match": r"(?i)Applied Working Group\s*:\s*PhD evaluation", "skip": True},
            {"match": r"(?i)Applied Working Group\s*:"},
            {"skip": True},  # "Applied Seminar:" rows: the BSE feed carries that series
        ],
    },
]

INST_NAMES = {"UAB": {"universitat autònoma de barcelona", "universitat autonoma de barcelona", "uab"},
              "UB": {"universitat de barcelona", "university of barcelona", "ub"}}
NOT_A_NAME = re.compile(r"(?i)\b(presentation|evaluation|tba|tbd|tbc|to be (announced|confirmed)|meeting|session|"
                        r"workshop|seminars?|conference|lecture|group|progress|students?|phd|break|holiday|"
                        r"reserved|room|party|course|exam)\b")
ROOMISH = re.compile(r"(?i)^(seminar|seminari|sala|room|aula|classroom)\s+\S+(\s*\(\d{1,2}(?::\d\d)?\s*h\))?$")
ONLINE = re.compile(r"(?i)\b(online|on-line|zoom|teams|google meet|virtual|webinar)\b")
_CX = r"(?:cancell?ed|cancelad[oa]|cancel·lat|anul·lat)"
CANCEL = re.compile(rf"(?i)^\s*[\[(]?\s*{_CX}\s*[\])]?\s*[:\-–—]?\s*|\s*[-–—:(\[]\s*{_CX}\s*[\])]?\s*$")
WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


# ---------------------------------------------------------------- iCalendar parsing

def unescape(s):
    return re.sub(r"\\([\\,;nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), s or "").strip()


def parse_ics(raw):
    """VEVENTs as {NAME: [(params, value), ...]} with folded lines joined; every occurrence is kept."""
    raw = re.sub(r"\r?\n[ \t]", "", raw)
    events = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", raw, re.S):
        ev = {}
        for ln in block.splitlines():
            m = re.match(r"([A-Za-z-]+)((?:;[^:]*)?):(.*)$", ln.strip())
            if m:
                ev.setdefault(m.group(1).upper(), []).append((m.group(2), m.group(3)))
        events.append(ev)
    return events


def prop(ev, name):
    return ev.get(name, [("", "")])[0]


def ics_time(params, value):
    """-> aware datetime (in the value's own zone) or a date for all-day values; None if unreadable."""
    value = value.strip()
    if re.fullmatch(r"\d{8}", value):
        return dt.date(int(value[:4]), int(value[4:6]), int(value[6:]))
    m = re.fullmatch(r"(\d{8})T(\d{6})(Z?)", value)
    if not m:
        return None
    t = dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    if m.group(3):
        return t.replace(tzinfo=UTC)
    tz = re.search(r"TZID=\"?([^;:\"]+)", params or "")
    try:
        zone = ZoneInfo(tz.group(1)) if tz else MAD
    except Exception:
        zone = MAD
    return t.replace(tzinfo=zone)


def key_of(t):
    """Comparable key for matching RECURRENCE-ID / EXDATE values to occurrences."""
    if t is None:
        return ""
    return t.isoformat() if not isinstance(t, dt.datetime) else t.astimezone(UTC).isoformat()


def shift(t, days):
    """Add whole days in wall-clock time (keeps 12:15 at 12:15 across DST changes)."""
    if not isinstance(t, dt.datetime):
        return t + dt.timedelta(days=days)
    return (t.replace(tzinfo=None) + dt.timedelta(days=days)).replace(tzinfo=t.tzinfo)


def occurrences(ev, t0, last_day):
    """Start times of a VEVENT: just DTSTART, or its DAILY/WEEKLY RRULE expansion up to `last_day`."""
    rrule = prop(ev, "RRULE")[1]
    if not rrule:
        return [t0]
    r = dict(p.split("=", 1) for p in rrule.upper().split(";") if "=" in p)
    if r.get("FREQ") not in ("DAILY", "WEEKLY"):
        return [t0]  # MONTHLY/YEARLY rules are not expanded
    interval = int(r.get("INTERVAL") or 1)
    count = int(r["COUNT"]) if r.get("COUNT", "").isdigit() else None
    until = ics_time("", r["UNTIL"]) if r.get("UNTIL") else None
    if isinstance(until, dt.datetime) and isinstance(t0, dt.datetime):
        until_ok = lambda t: t <= until
    elif until is not None:
        until_day = until.astimezone(MAD).date() if isinstance(until, dt.datetime) else until
        until_ok = lambda t: (t.date() if isinstance(t, dt.datetime) else t) <= until_day
    else:
        until_ok = lambda t: True
    day0 = t0.date() if isinstance(t0, dt.datetime) else t0
    if r["FREQ"] == "DAILY":
        offsets, step = [0], interval
    else:
        days = [WEEKDAYS[d[-2:]] for d in r.get("BYDAY", "").split(",") if d[-2:] in WEEKDAYS] or [day0.weekday()]
        offsets, step = sorted(d - day0.weekday() for d in set(days)), 7 * interval  # relative to DTSTART's week
    out = []
    for k in range(2000):
        for off in offsets:
            t = shift(t0, k * step + off)
            if off < 0 and k == 0:
                continue  # weekdays before DTSTART in its first week
            if not until_ok(t) or (count is not None and len(out) >= count):
                return out
            out.append(t)
        if day0 + dt.timedelta(days=k * step) > last_day:
            break
    return out


def instances(events, last_day):
    """(VEVENT, start, end) for every occurrence: RRULEs expanded, EXDATEs dropped, RECURRENCE-ID
    overrides replacing the occurrence they move; cancelled overrides are dropped."""
    overridden = {(prop(e, "UID")[1], key_of(ics_time(*prop(e, "RECURRENCE-ID"))))
                  for e in events if "RECURRENCE-ID" in e}
    out = []
    for ev in events:
        t0 = ics_time(*prop(ev, "DTSTART"))
        if t0 is None:
            continue
        t1 = ics_time(*prop(ev, "DTEND")) if "DTEND" in ev else None
        dur = (t1 - t0) if t1 is not None and type(t1) is type(t0) else None
        if "RECURRENCE-ID" in ev:
            if prop(ev, "STATUS")[1].upper() != "CANCELLED":
                out.append((ev, t0, t1))
            continue
        uid = prop(ev, "UID")[1]
        exdates = {key_of(ics_time(params, v)) for params, value in ev.get("EXDATE", []) for v in value.split(",")}
        try:
            starts = occurrences(ev, t0, last_day)
        except (ValueError, KeyError):
            starts = [t0]  # unreadable RRULE: keep the first occurrence
        for t in starts:
            if key_of(t) in exdates or (uid, key_of(t)) in overridden:
                continue
            out.append((ev, t, t + dur if dur is not None else None))
    return out


# ---------------------------------------------------------------- SUMMARY / DESCRIPTION

def first_parens(s):
    """Index of the first '(' and its matching ')', or None."""
    i = s.find("(")
    depth = 0
    for j in range(max(i, 0), len(s)):
        depth += {"(": 1, ")": -1}.get(s[j], 0)
        if i >= 0 and depth == 0:
            return i, j
    return None


def looks_like_name(s):
    words = s.split()
    return (2 <= len(words) <= 6 and s[:1].isupper() and not re.search(r"[\d/]", s)
            and not NOT_A_NAME.search(s) and not re.search(r"\b(the|of|and|for|in|on|to|with|from|an?|is)\b|^The\b", s))


def parse_summary(s):
    """'Name (Affil) - Title', 'Name (Affil): Title', 'Name (Affil) - Seminar E2 (15h)', 'presentation Name',
    'Label: Name', 'A (X) & B (Y)' -> (speaker, affil, title, note, room). Text with no person goes to note."""
    s = re.sub(r"(?i)^(?:presentation|talk|presentaci[óo]n?)\s+(?:by\s+)?(?=[A-Z])", "", s.strip()).strip()
    who, affil, rest, note = s, "", "", ""
    p = first_parens(s)
    if p and s[:p[0]].strip() and not NOT_A_NAME.search(s[:p[0]].split(":")[-1]) and not re.search(r"\d", s[:p[0]]):
        who, affil, rest = s[:p[0]].strip().split(": ")[-1], s[p[0] + 1:p[1]].strip(), s[p[1] + 1:]
        if re.match(r"(?i)(joint )?with\b", affil):  # "Name (with X and Y) (Affil)"
            note, affil = f"({affil})", ""
            q = first_parens(rest)
            if q and not rest[:q[0]].strip():
                affil, rest = rest[q[0] + 1:q[1]].strip(), rest[q[1] + 1:]
        names, affils = [who], [affil]
        while m := re.match(r"^\s*(?:&|and|,)\s*([^()&,]+?)\s*\(([^()]*)\)", rest):  # "A (X) & B (Y)"
            names.append(m.group(1))
            affils.append(m.group(2))
            rest = rest[m.end():]
        who, affil = " & ".join(names), " / ".join(dict.fromkeys(a for a in affils if a))
    else:
        m = re.match(r"^(.+?)\s*(?:\s[-–—]\s|:\s)\s*(.+)$", s)
        if m and looks_like_name(m.group(1)):
            who, rest = m.group(1), m.group(2)
        elif m and looks_like_name(m.group(2)):  # "Label: Name"
            who = m.group(2)
        elif not looks_like_name(s):
            return "", "", "", s, ""
    parts = [x.strip() for x in re.split(r"\s+[-–—]\s+|^\s*[-–—:]\s*", rest) if x.strip()]
    room = ""
    while parts and ROOMISH.match(parts[-1]):
        room = re.sub(r"\s*\(.*\)$", "", parts.pop())
    title = " - ".join(parts).strip().strip("\"“”'").strip()
    if re.fullmatch(r"(?i)tb[acd]|to be (announced|confirmed)", title):
        title = ""
    return who.strip(" ,;:"), affil, title.rstrip("."), note, room


def from_description(desc):
    """(title, coauthor note) from a DESCRIPTION: a quoted line or 'Title: ...', and 'with X and Y'."""
    lines = [ln for ln in text_lines(desc) if not re.search(r"(?i)https?://|^more info", ln)]
    title = note = ""
    for ln in lines:
        m = re.match(r"(?i)^(?:title|t[íi]tol|t[íi]tulo)\s*:\s*(.+)$", ln) or re.match(r'^["“](.{8,}?)["”]', ln)
        if m and not title:
            title = m.group(1).strip().strip("\"“”").rstrip(".")
        m = re.search(r"(?:\(|\b[Jj]oint (?:work )?|^)[Ww]ith ([A-Z][^.;:()]{2,120})", ln)
        if m and not note:
            note = f"(with {m.group(1).strip()})"
    return title, note


def clean_location(loc, room, inst):
    parts = [x.strip() for x in loc.split(",") if x.strip()]
    parts = [x for x in parts if x.lower() not in INST_NAMES.get(inst, set())]
    if room and not any(room.lower() in x.lower() for x in parts):
        parts.insert(0, room)
    return ", ".join(parts)


# ---------------------------------------------------------------- feeds -> events

def feed_events(raw, feed, start, end):
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    out = []
    for ev, t, t_end in instances(parse_ics(raw), last):
        try:
            if isinstance(t, dt.datetime):
                t = t.astimezone(MAD)
                t_end = t_end.astimezone(MAD) if isinstance(t_end, dt.datetime) else None
            day = t.date() if isinstance(t, dt.datetime) else t
            if not first <= day <= last:
                continue
            summary = unescape(prop(ev, "SUMMARY")[1])
            canceled = prop(ev, "STATUS")[1].upper() == "CANCELLED" or bool(CANCEL.search(summary))
            summary = CANCEL.sub(" ", summary).strip()
            rule = {}
            for r in feed.get("rules", []):
                m = re.match(r["match"], summary) if r.get("match") else None
                if (not r.get("match") or m) and r.get("weekday", day.weekday()) == day.weekday():
                    rule = r
                    if m:
                        summary = summary[m.end():].strip()
                    break
            if rule.get("skip") or not summary.strip(" :-"):
                continue  # filtered out, or an empty slot ("External Seminar:" with no name)
            e = {k: v for k, v in {**feed, **rule}.items() if k not in ("ics", "rules", "match", "weekday")}
            speaker, affil, title, note, room = parse_summary(summary)
            d_title, d_note = from_description(unescape(prop(ev, "DESCRIPTION")[1]))
            talks = []
            if speaker:
                talks = [{"speaker": speaker, "affil": affil, "title": title or d_title, "note": note or d_note}]
            notes = [note] if note and not speaker else []
            loc = clean_location(unescape(prop(ev, "LOCATION")[1]), room, e["inst"]) or e.get("location", "")
            mode = "Hybrid" if re.search(r"(?i)hybrid|h[íi]brid", summary + " " + loc) else \
                "Online" if ONLINE.search(loc) else ""
            url = prop(ev, "URL")[1].strip()
            timed = isinstance(t, dt.datetime)
            last_day = (t_end - dt.timedelta(days=1)) if not timed and isinstance(t_end, dt.date) else None
            e.update({
                "kind": e.get("kind", "seminar"), "field": e.get("field", "Other"),
                "internal": bool(e.get("internal", False)), "canceled": canceled,
                "start": local_iso(t.year, t.month, t.day, t.hour, t.minute) if timed else t.isoformat(),
                "end": (local_iso(t_end.year, t_end.month, t_end.day, t_end.hour, t_end.minute) if timed and t_end
                        else last_day.isoformat() if last_day and last_day > t else None),
                "all_day": not timed, "talks": talks, "location": loc, "campus": e.get("campus", ""),
                "notes": notes, "mode": mode, "url": url if url.startswith("http") else e.get("url", ""),
                "source": SOURCE,
            })
            e["no_titles"] = bool(e.get("no_titles")) and not any(x["title"] for x in talks)
            out.append(e)
        except Exception:
            continue  # one unreadable VEVENT must not sink the feed
    return out


def collect(start, end):
    out, seen = [], set()
    for feed in FEEDS:
        raw = get(feed["ics"])
        if not raw or "BEGIN:VCALENDAR" not in raw:
            raise RuntimeError(f"no calendar at {feed['ics']}")
        for e in feed_events(raw, feed, start, end):
            key = (e["inst"], e["series"], e["start"], tuple(t["speaker"].lower() for t in e["talks"]))
            if key not in seen:
                seen.add(key)
                out.append(e)
    return sorted(out, key=lambda e: e["start"])
