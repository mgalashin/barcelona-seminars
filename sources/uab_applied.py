"""UAB Department of Applied Economics: departmental seminar (/ca/economia-aplicada/seminarisdepartament),
Applied Lunch seminar (/ca/economia-aplicada/appliedlunchca) and job-market talks (/ca/economia-aplicada/seminarisjm).
Static CMS pages with one accordion per academic year; each talk is 'Name (Affil)' / "Title" / 'October 1st 2026, at 15:00, Room'."""
import re

from collect import get, text_lines, split_affil, local_iso, MONTHS

BASE = "https://www.uab.cat/ca/economia-aplicada/"
PAGES = [  # slug, series, required (a 404 raises so the collector keeps yesterday's data)
    ("seminarisdepartament", "UAB Applied Economics Seminar", True),
    ("appliedlunchca", "UAB Applied Lunch Seminar", True),
    ("seminarisjm", "UAB Job Market Seminar", False),
]
MONTH_RE = "january|february|march|april|may|june|july|august|september|october|november|december"
DATE = re.compile(rf"(?i)\b({MONTH_RE})\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(\d{{4}})"
                  r"(?:\s*,?\s*at\s*(\d{1,2})[:.h](\d{2}))?\s*,?\s*(.*)$")
TERM = re.compile(r"(?i)^((fall|spring|winter|autumn) term \d{4}|job market \d{4}\s*-\s*\d{4})$")
# flags on the speaker or date line (or a title that is just the flag), so a paper about "debt cancellation" is safe
CANCELED = re.compile(r"(?i)\W*\b(cancel|anul·?l|suspended|susp[eè]s|postponed|ajornat|aplazad)")
COAUTHORS = re.compile(r"(?i)\s*\((?:joint\s+)?(with\s+[^()]+)\)\s*\.?$")
REHEARSAL = re.compile(r"(?i)\brehears")  # '[Job Market Rehearsal]' tag on the speaker line -> internal
ONLINE = re.compile(r"(?i)on[- ]?line|zoom|virtual|teams")
ROOM = re.compile(r"(?i)\b(sala|seminari|aula|room|graus)\b")  # a physical room next to an online keyword -> hybrid


def blocks(raw, y0):
    """(heading, html) for each year accordion whose heading mentions year y0 or later."""
    raw = re.split(r"(?i)</main>", raw)[0]  # drop the site map / footer after the last accordion
    for part in re.split(r'(?i)<h\d[^>]*class="acordio-titol"[^>]*>', raw)[1:]:
        head, body = (re.split(r"(?i)</h\d>", part, maxsplit=1) + [""])[:2]
        years = [int(y) for y in re.findall(r"\b(20\d\d)\b", " ".join(text_lines(head)))]
        if not years or max(years) >= y0:
            yield body


def clean_title(t):
    t = t.strip().strip("“”\"'‘’ ").rstrip(".").strip().strip("“”\"' ")
    return "" if t.upper() in ("TBC", "TBA", "TBD", "") else t


def talks_in(body):
    """Yield (speaker_line, title_line, date_match) for each talk in an accordion body."""
    body = re.sub(r'(?is)<p[^>]*class="titol"[^>]*>.*?</p>', "\n", body)
    buf = []
    for ln in text_lines(body):
        if TERM.match(ln):
            continue
        m = None
        for m in DATE.finditer(ln):
            pass
        if not m:
            buf.append(ln)
            continue
        prefix = ln[:m.start()].strip()
        if prefix:
            title, speaker = prefix, (buf[-1] if buf else "")
        elif len(buf) >= 2:
            title, speaker = buf[-1], buf[-2]
        elif buf and buf[-1].endswith(")"):
            title, speaker = "", buf[-1]
        else:
            title, speaker = (buf[-1] if buf else ""), ""
        buf = []
        yield speaker, title, m


def collect(start, end):
    out, seen = [], set()
    for slug, series, required in PAGES:
        url = BASE + slug
        raw = get(url)
        if raw is None:
            if required:
                raise RuntimeError(f"{url} returned 404")
            continue
        if required and 'class="acordio-titol"' not in raw:  # this CMS serves an empty template with HTTP 200
            raise RuntimeError(f"{url}: no year accordions found")
        for body in blocks(raw, int(start[:4])):
            for speaker, title, m in talks_in(body):
                try:
                    y, mo, d = int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))
                    if m.group(4):
                        iso = local_iso(y, mo, d, int(m.group(4)), int(m.group(5)))
                    else:
                        iso = local_iso(y, mo, d)
                except (KeyError, ValueError):
                    continue
                if not (start <= iso[:10] <= end):
                    continue
                notes = []
                for extra in re.findall(r"\[([^\]]+)\]", speaker):
                    notes.append(extra.strip()[:1].upper() + extra.strip()[1:])
                raw_speaker = speaker  # keep the bracket tags for the internal/canceled flags
                speaker = re.sub(r"\s*\[[^\]]*\]", "", speaker)
                name, affil = split_affil(speaker)
                note = ""
                c = COAUTHORS.search(title)
                if c:
                    note, title = f"({c.group(1).strip()})", title[:c.start()]
                title = clean_title(title)
                if not name and not title:
                    continue
                room = m.group(6).strip(" ,.;")
                mode = ("Hybrid" if ROOM.search(room) else "Online") if ONLINE.search(room) else ""
                key = (series, iso, name.lower())
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "inst": "UAB", "host": "UAB Department of Applied Economics", "series": series,
                    "kind": "seminar", "field": "Applied & policy",
                    "internal": bool(REHEARSAL.search(raw_speaker) or re.match(r"(?i)rehearsal\b", title)),
                    "canceled": bool(CANCELED.search(raw_speaker + " " + m.group(0)) or (len(title) < 30 and CANCELED.match(title))),
                    "start": iso, "end": None, "all_day": "T" not in iso,
                    "talks": [{"speaker": name, "affil": affil, "title": title, "note": note}],
                    "location": room, "campus": "" if mode == "Online" else "Bellaterra campus",
                    "notes": notes, "mode": mode,
                    "url": url, "source": "UAB Applied Economics seminars",
                })
    return out
