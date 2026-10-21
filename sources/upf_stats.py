"""UPF Statistics, Probability and Machine Learning group seminars, read from the group's own page
https://www.upf.edu/web/statistics-group/seminars ("Full Schedule" table, plus the "Forthcoming
Seminars" links that carry titles once announced). BSE lists each talk 2-3 weeks ahead; this adds the rest.
"""
import datetime as dt
import re

from collect import get, text_lines, local_iso, MONTHS

URL = "https://www.upf.edu/web/statistics-group/seminars"
SOURCE = "UPF Statistics seminars"
DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]{3,})\.?\s+(\d{4})")
NO_TITLE = {"", "-", "–", "—", "tba", "tbd", "tbc", "title tba", "title tbd"}
CANCEL = r"cancel+ed|cancelad[oa]|cancel·la(?:t|da)|anul·la(?:t|da)"
CANCEL_RE = re.compile(rf"(?i)\b(?:{CANCEL})\b")
# a title cell that is really a logistics note ("Moved to 15:00, room 40.010"), not a talk title
LOGISTICS_RE = re.compile(r"(?i)^\W*(?:moved|rescheduled|postponed|note|room|time|venue|online|zoom|special)\b")
RANGE_RE = re.compile(r"(?i)\b(\d{1,2})(?:[:.h](\d\d)|h)?\s*([ap])?\.?m?\.?\s*(?:-|–|—|to)\s*"
                      r"(\d{1,2})(?:[:.h](\d\d)|h)?\s*(?:([ap])\.?m\b\.?)?")
ROOM_RE = re.compile(r"(?i)\broom\s+(\d[\d.]*\d)")


def _month(name):
    return MONTHS.get(name.lower()) or MONTHS.get(name.lower()[:3])


def _cell(fragment):
    return " ".join(text_lines(fragment)).strip()


def _title(s):
    return "" if s.strip().lower() in NO_TITLE else s.strip()


def _h24(h, ap):
    if ap and ap.lower() == "p" and h < 12:
        return h + 12
    if ap and ap.lower() == "a" and h == 12:
        return 0
    return h


def _clock(s):
    """(hh, mm, eh, em) from a range like '1-2pm', '12:30-1:30pm', '11am-12pm' or '13:00-14:00';
    (hh, mm, None, None) from a single '15:00' or '3pm'; None if no explicit time."""
    s = ROOM_RE.sub(" ", s)  # 'room 20.17' is not a clock
    m = RANGE_RE.search(s)
    if m:
        h1, m1, a1, h2, m2, a2 = m.groups()
        if a1 or a2 or m1 or m2 or "h" in m.group(0).lower():  # bare '1-2' could be anything
            eh = _h24(int(h2), a2)
            hh = _h24(int(h1), a1)
            if not a1 and a2 and a2.lower() == "p" and hh + 12 <= eh:  # '1-2pm' -> 13-14, '11-12pm' -> 11-12
                hh += 12
            mm, em = int(m1 or 0), int(m2 or 0)
            if 0 <= hh < 24 and 0 <= eh < 24 and mm < 60 and em < 60 and (eh, em) > (hh, mm):
                return hh, mm, eh, em
    m = re.search(r"(?i)\b(\d{1,2})[:.h](\d\d)\b|\b(\d{1,2})\s*([ap])\.?m\b", s)
    if m:
        hh = int(m.group(1)) if m.group(1) else _h24(int(m.group(3)), m.group(4))
        mm = int(m.group(2) or 0)
        if hh < 24 and mm < 60:
            return hh, mm, None, None
    return None


def _defaults(page_text):
    """Time and room from 'Unless otherwise noted, seminars take place on Thursdays, 1-2pm, room 20.179'.
    The time is read only from that sentence (so the room number is never taken for a clock)."""
    m = re.search(r"(?i)otherwise noted(.{0,160})", page_text)
    if not m:
        return None, ""
    r = ROOM_RE.search(m.group(1))
    return _clock(m.group(1)), (r.group(1) if r else "")


def _schedule_table(page):
    m = re.search(r'(?is)<table[^>]*class="[^"]*\bseminar-table\b[^"]*"[^>]*>.*?</table>', page)
    if m:
        return m.group(0)
    m = re.search(r"(?is)Full Schedule.*?(<table.*?</table>)", page)
    return m.group(1) if m else None


def _year_from_today(mo, d):
    """Forthcoming items carry no year: take the first date on or after a week ago."""
    floor = dt.date.today() - dt.timedelta(days=7)
    for y in (floor.year, floor.year + 1):
        try:
            if dt.date(y, mo, d) >= floor:
                return y
        except ValueError:
            continue
    return None


def _forthcoming(page):
    """(y, mo, d) -> (speaker, affil, title, detail url) from the 'Forthcoming Seminars' links."""
    out = {}
    for href, inner in re.findall(r'<a[^>]+href="([^"]*/asset_publisher/[^"]*/content/[^"]*)"[^>]*>(.*?)</a>',
                                  page, re.S):
        m = re.match(r"^(\d{1,2})\s+([A-Za-z]{3,})\.?\s*:\s*([^()]+?)\s*\(((?:[^()]|\([^()]*\))*)\)\s*,?\s*(.*)$",
                     _cell(inner))
        if not m or not _month(m.group(2)):
            continue
        d, mo = int(m.group(1)), _month(m.group(2))
        y = _year_from_today(mo, d)
        if y:
            url = href.replace("www.upf.edu:443", "www.upf.edu")
            out[(y, mo, d)] = (m.group(3), m.group(4), _title(m.group(5)), url)
    return out


def collect(start, end):
    page = get(URL)
    if page is None or ("Just a moment" in page and "Full Schedule" not in page):
        raise RuntimeError(f"no usable page at {URL} (missing or a bot challenge)")
    table = _schedule_table(page)
    if table is None:  # markup changed: fail loudly so the collector keeps the last good data
        raise RuntimeError(f"no 'Full Schedule' table found at {URL}")
    default_clock, room = _defaults(" ".join(text_lines(page)))
    upcoming = _forthcoming(page)

    rows = []  # (y, mo, d, speaker, affil, title, canceled, clock, location, notes)
    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", table):
        cells = [_cell(c) for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", tr)]
        if len(cells) < 2:
            continue
        m = DATE_RE.search(cells[0])
        speaker = cells[1]
        if not m or not _month(m.group(2)) or not speaker or re.match(r"(?i)tb[acd]\b", speaker):
            continue
        affil = cells[2] if len(cells) > 2 else ""
        title = _title(cells[3]) if len(cells) > 3 else ""
        cancel_only = bool(re.fullmatch(rf"(?i)\W*(?:{CANCEL})\W*", title))
        canceled = bool(CANCEL_RE.search(cells[0]) or CANCEL_RE.search(speaker) or cancel_only)
        speaker = re.sub(rf"(?i)\s*[(\[\-–—:]*\s*\b(?:{CANCEL})\b\s*[)\]]*", "", speaker).strip(" -–—:")
        if not speaker:
            continue
        # per-row exceptions: a time after the date, or a logistics note in the title cell
        extra = cells[0][m.end():]
        notes, location = [], ""
        if cancel_only:
            title = ""
        elif LOGISTICS_RE.match(title):
            notes.append(title)
            extra, title = extra + " " + title, ""
        clock = _clock(extra) if extra.strip() else None
        r = ROOM_RE.search(extra)
        if r:
            location = f"Room {r.group(1)}"
        rows.append((int(m.group(3)), _month(m.group(2)), int(m.group(1)), speaker, affil, title, canceled,
                     clock, location, notes))

    # forthcoming items missing from the table
    known = {(y, mo, d) for y, mo, d, *_ in rows}
    for (y, mo, d), (speaker, affil, title, _) in upcoming.items():
        if (y, mo, d) not in known and not re.match(r"(?i)tb[acd]\b", speaker):
            rows.append((y, mo, d, speaker, affil, title, False, None, "", []))

    room_note = (f"Usually room {room} (rooms vary); check nearer the date" if room
                 else "Room varies; check nearer the date")
    events, seen = [], set()
    for y, mo, d, speaker, affil, title, canceled, clock, location, notes in rows:
        clock = clock or default_clock
        try:
            if clock:
                iso = local_iso(y, mo, d, clock[0], clock[1])
                iso_end = local_iso(y, mo, d, clock[2], clock[3]) if clock[2] is not None else None
            else:
                iso, iso_end = local_iso(y, mo, d), None
        except ValueError:
            continue
        key = (iso[:10], speaker.lower())
        if not (start <= iso[:10] <= end) or key in seen:
            continue
        seen.add(key)
        info = upcoming.get((y, mo, d))
        if info and not title:
            title = info[2]
        events.append({
            "inst": "UPF", "host": "UPF Statistics, Probability and Machine Learning group",
            "series": "UPF Statistics Seminar", "kind": "seminar", "field": "Econometrics & statistics",
            "internal": False, "canceled": canceled,
            "start": iso, "end": iso_end, "all_day": not clock,
            "talks": [{"speaker": speaker, "affil": affil, "title": title, "note": ""}],
            "location": location, "campus": "Ciutadella campus",
            "notes": notes + ([] if location else [room_note]),
            "mode": "", "url": info[3] if info else URL, "source": SOURCE,
        })
    return sorted(events, key=lambda e: e["start"])
