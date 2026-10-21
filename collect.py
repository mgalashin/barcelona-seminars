#!/usr/bin/env python3
"""Collect Barcelona economics seminars for one academic year and render the page.

Sources
  BSE events calendar (JSON feed) -> UPF (DEE, CREI), UAB (UFAE, IAE-CSIC), BSE-wide
  UB School of Economics activities list (HTML)
  IESE Research Seminars blog (HTML)
  Esade GREF events page (HTML)

Usage
  python3 collect.py                 # academic year starting 1 Sep of the current cycle
  python3 collect.py --year 2027     # academic year 2027-28

  python3 collect.py --fail IESE     # test: treat IESE as down and keep its last good events

Writes data/seminars.json (also the fallback store for the next run) and the static site in docs/
(index.html built from page_template.html, plus seminars.json).
"""
import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.error
import unicodedata
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
MAD = ZoneInfo("Europe/Madrid")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/json;q=0.9",
           "Accept-Language": "en-US,en;q=0.9"}

MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october november december".split(), 1)}
MONTHS.update({k[:3]: v for k, v in MONTHS.items()})


# ---------------------------------------------------------------- helpers

def get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:  # timeouts, resets
            last = e
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def text_lines(fragment):
    """HTML fragment -> list of clean non-empty text lines (one per <br>/<p>)."""
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", fragment or "")
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ")
    out = []
    for ln in s.split("\n"):
        ln = re.sub(r"\s+", " ", ln).strip()
        if ln:
            out.append(ln)
    return out


def split_affil(s):
    """'Name (Affiliation)' -> (name, affiliation)."""
    s = s.strip().strip(",;:").strip()
    m = re.match(r"^(.*?)\s*\((.+)\)\s*$", s)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return s, ""


def local_iso(y, mo, d, hh=None, mm=None):
    if hh is None:
        return dt.date(y, mo, d).isoformat()
    return dt.datetime(y, mo, d, hh, mm, tzinfo=MAD).isoformat()


FIELDS = [
    ("Finance", r"\bfinance\b|asset pric|banking|corporate fin"),
    ("Management", r"management"),
    ("Econometrics & statistics", r"statist|econometr"),
    ("Economic history", r"histor"),
    ("Macro & international", r"macro|international|growth|monetary|steg"),
    ("Micro & theory", r"micro|theory|game|behavio|experiment|beat|industrial organi|axiomatic|auction|"
                       r"mechanism design|matching"),
    ("Applied & policy", r"applied|labou?r|\beale\b|public|\bieb\b|iperg|aqr|irea|development|politic|health|"
                         r"urban|regional|iae|welfare|energy|environment|gov"),
]


def field_of(*texts):
    t = " ".join(x for x in texts if x).lower()
    for name, pat in FIELDS:
        if re.search(pat, t):
            return name
    return "Other"


def kind_of(*texts):
    t = " ".join(x for x in texts if x).lower()
    if re.search(r"thesis defen[cs]e", t):
        return "defence"
    if re.search(r"trobada|welcome|community session|networking", t):
        return "community"
    if re.search(r"conference|congress|eale", t):
        return "conference"
    if re.search(r"workshop|working group|meeting", t) and "lunch workshop" not in t:
        return "workshop"
    if re.search(r"lecture|anniversary|keynote|colloquium", t):
        return "lecture"
    if re.search(r"seminar|lunch|microlab|brown bag|game theory|dynamics", t):
        return "seminar"
    return "other"


# ---------------------------------------------------------------- BSE (UPF + UAB)

BSE_GROUPS = {
    "UPF-DEE Events Calendar": ("UPF", "UPF Dept. of Economics and Business"),
    "CREI Events Calendar": ("UPF", "CREI"),
    "UFAE Events Calendar": ("UAB", "UAB Department of Economics"),
    "IAE Events Calendar": ("UAB", "IAE-CSIC"),
    "Barcelona School of Economics Events Calendar": ("BSE", "Barcelona School of Economics"),
}
BSE_FEED = ("https://events.bse.eu/live/json/v2/events"
            "/exclude_group/Programs%20Office/exclude_group/Admissions"
            "/exclude_group/Summer%20School/exclude_group/Summer%20Forum"
            "/start_date/{start}/end_date/{end}/max/1000"
            "/response_fields/location,tags,summary,description,event_types,group_title,status")


NOTE_LINE = re.compile(r"(?i)^([-*]|room\b|time\b|register|cancel|program|detailed program|note\b|"
                       r"this seminar|followed by|welcome speech|https?://)")
NAME_COLON_TITLE = re.compile(r"^([A-ZÀ-Ý][\w.'’-]+(?: [\w.'’-]+){0,4}):\s+(.{8,})$")


def looks_like_speaker(ln):
    if re.match(r"^[^“”\"]{2,100}\([^()]{2,120}\)\s*$", ln):
        return True  # 'Name (Affiliation)'
    if ln.isupper() and ln not in ("TBA", "TBC", "TBD"):
        return False  # 'DETAILED PROGRAM'
    return bool(re.match(r"^[A-ZÀ-Ý][\w.'’/&-]*(?:\s+[\w.'’/&-]+){0,7}$", ln)) and len(ln) <= 60


def parse_talks(lines):
    """BSE summaries: 'Speaker (Affil)' line followed by a '“Title”' line, possibly repeated.
    Returns (talks, notes, canceled)."""
    talks, notes, canceled = [], [], False

    def add(spk, title="", note=""):
        name, affil = split_affil(spk) if spk else ("", "")
        talks.append({"speaker": name, "affil": affil, "title": title, "note": note})

    pending = None
    for ln in lines:
        if ln.lower() in ("and", "&"):
            continue
        if re.match(r"(?i)^cancel", ln):
            canceled = True
        if NOTE_LINE.match(ln):
            notes.append(ln.strip("-* ").strip())
            continue
        nc = NAME_COLON_TITLE.match(ln)
        if nc and not pending and "“" not in ln:  # 'Name: Title' without quotes
            add(nc.group(1), nc.group(2).strip().rstrip("."))
            continue
        q = re.search(r"[“”\"](.+?)[“”\"]", ln) or re.match(r"^[“”\"](.+)$", ln)  # also unclosed or reversed quotes
        if q:
            before = ln[:q.start()].strip().rstrip(":").strip()
            after = ln[q.end():].strip().lstrip(",.").strip()
            spk = before or pending
            if not spk:  # quoted text with nobody attached, e.g. '“Brown Bag” seminar'
                notes.append(ln)
                continue
            add(spk, q.group(1).strip().strip("”\"").rstrip("."), after)
            pending = None
        elif pending:  # unquoted line after a speaker is the title ('TBA', 'Title: TBA', plain titles)
            add(pending, re.sub(r"(?i)^title:\s*", "", ln))
            pending = None
        elif looks_like_speaker(ln):
            pending = ln
        else:
            notes.append(ln)
    if pending:
        add(pending)
    return talks, notes, canceled


def collect_bse(start, end):
    rows, page, pages = [], 1, 1
    while page <= pages:
        raw = get(BSE_FEED.format(start=start, end=end) + f"?page={page}")
        d = json.loads(raw)
        pages = d["meta"]["total_pages"]
        rows += d["data"]
        page += 1
    out, seen = [], set()
    for e in rows:
        key = (e["id"], e["date_ts"])  # repeating events share an id across dates
        if key in seen or e.get("group_title") not in BSE_GROUPS:
            continue
        seen.add(key)
        inst, host = BSE_GROUPS[e["group_title"]]
        title = html.unescape(e["title"]).strip()
        types = e.get("event_types") or []
        lines = text_lines(e.get("summary"))
        talks, notes, canceled = parse_talks(lines)
        canceled = canceled or bool(e.get("is_canceled")) or bool(re.search(r"cancel", title, re.I))
        series = re.sub(r"(?i)^cancel+ed:\s*|\s*-?\s*cancel+ed\s*-?\s*", "", title).strip(" -")
        series = re.sub(r"^MicroLab\s*-\s*.+$", "MicroLab", series)
        if series == "MicroLab" and not talks:  # 'MicroLab - Name' with an empty summary
            talks = [{"speaker": title.split(" - ", 1)[-1], "affil": "", "title": "", "note": ""}]
        kind = kind_of(series, " ".join(types).replace("Seminars", "seminar"))
        if "Lectures" in types and kind == "seminar":
            kind = "lecture"
        internal = bool(re.search(r"internal", title, re.I)) or "internal" in (e.get("tags") or [])
        field = field_of(series)
        if field == "Other":
            field = field_of(" ".join(e.get("tags") or []))
        if field == "Other" and len(talks) == 1:  # a one-off lecture: go by its title
            field = field_of(talks[0]["title"])
        out.append({
            "inst": inst, "host": host, "series": series, "kind": kind,
            "field": field,
            "internal": internal, "canceled": canceled,
            "start": e["date_iso"], "end": e.get("date2_iso"),
            "all_day": bool(e.get("is_all_day")) or e["date_iso"].endswith("T00:00:00" + e["date_iso"][-6:]),
            "talks": talks,
            "location": re.sub(r",(?=[^\s\d])", ", ", re.sub(r"\s+", " ", e.get("location") or e.get("location_title") or "")).strip(),
            # BSE's is_online flags a Zoom link; with a room listed it is a hybrid session
            "notes": notes, "mode": ("Hybrid" if e.get("location") else "Online") if e.get("is_online") else "",
            "url": e["url"], "source": "BSE events calendar",
        })
    return out


# ---------------------------------------------------------------- UB

UB_LIST = "https://www.ub.edu/school-economics/activities/{page}?view={view}"
UB_CARD = re.compile(
    r'<h2 class="pb-1\.5[^"]*">\s*(?P<date>[^<]+?)\s*</h2>\s*'
    r'<p class="mt-5 activity-title">(?P<title>.*?)</p>\s*'
    r'<div class="mt-4 richeditor-content-sm">(?P<body>.*?)</div>\s*'
    r'<div class="flex flex-col-reverse.*?<a class="flex" href="(?P<url>[^"]+)"', re.S)


def parse_ub_date(s):
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})(?:\s*-\s*(\d{1,2}):(\d{2}))?", s.strip())
    if not m:
        return None
    mo, d, y = MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
    if m.group(4):
        return local_iso(y, mo, d, int(m.group(4)), int(m.group(5)))
    return local_iso(y, mo, d)


def collect_ub(start, end):
    cards = []
    for view in ("upcoming", "past"):
        for p in range(1, 40):
            page = "" if p == 1 else f"page/{p}/"
            raw = get(UB_LIST.format(page=page, view=view))
            found = list(UB_CARD.finditer(raw or ""))
            if not found:
                break
            cards += found
            dates = [parse_ub_date(c.group("date")) or "" for c in found]
            if view == "past" and min(dates)[:10] < start:
                break
            if view == "upcoming" and max(dates)[:10] > end:
                break
    out, seen = [], set()
    for c in cards:
        iso = parse_ub_date(c.group("date"))
        if not iso or not (start <= iso[:10] <= end):
            continue
        url = c.group("url")
        if (url, iso) in seen:
            continue
        seen.add((url, iso))
        title = " ".join(text_lines(c.group("title")))
        lines = text_lines(c.group("body"))
        speakers, series, mode, rest = [], "", "", []
        series_words = r"(?i)seminar|activity|workshop|lecture|conference|session|meeting|colloquium|" \
                       r"game theory|dynamics|thesis defen"
        for ln in lines:
            if re.fullmatch(r"(?i)(in person|online|hybrid)(\s*[/&+]\s*(in person|online|hybrid))?", ln):
                mode = ln.title()
                continue
            name, affil = split_affil(ln)
            m = re.match(r"^(.*?),\s*(.*\bseminar\b.*)$", name, re.I)  # 'Name, X Seminar (Affil)'
            if m:
                speakers.append((m.group(1), affil))
                series = series or m.group(2)
            elif re.search(series_words, ln) and not (affil and len(name.split()) <= 4 and
                                                      not re.search(series_words, name)):
                if not series:
                    series = re.sub(r"\s*\([A-Z-]{2,10}\)$", "", ln)  # drop '(IMHOS)'-style acronyms
            elif affil:
                speakers.append((name, affil))
            else:
                rest.append(ln)
        talks = [{"speaker": ", ".join(n for n, _ in speakers),
                  "affil": "; ".join(dict.fromkeys(a for _, a in speakers if a)),
                  "title": title, "note": " ".join(rest)}]
        series_clean = re.sub(r"(?i)\s+activity$", "", series).strip() if series else ""
        series_clean = re.sub(r"(?i)\bseminar$", "Seminar", series_clean)
        series_clean = re.sub(r"(?i)^phd thesis defen[cs]e$", "PhD thesis defence", series_clean)
        if series_clean and series_clean.lower() == series_clean.lower().strip() and series_clean.islower():
            series_clean = series_clean.capitalize()
        field = field_of(series_clean)
        if field == "Other":
            field = field_of(title)
        out.append({
            "inst": "UB", "host": "UB School of Economics", "series": series_clean or "UB School of Economics",
            "kind": kind_of(series, title) if series or re.search(r"(?i)lecture|anniversary", title) else "other",
            "field": field,
            "internal": bool(re.search(r"(?i)phd students", series)),
            "canceled": bool(re.search(r"(?i)cancel", title + series)),
            "start": iso, "end": None, "all_day": "T" not in iso,
            "talks": talks, "location": "", "notes": [], "mode": mode,
            "url": url, "source": "UB School of Economics activities",
        })
    return out


# ---------------------------------------------------------------- IESE

IESE_URL = "https://blog.iese.edu/financeseminars/seminars/"


def collect_iese(start, end):
    raw = get(IESE_URL) or ""
    lines = text_lines(raw)
    y0 = int(start[:4])
    label = f"ACADEMIC YEAR {y0}-{y0 + 1}"
    try:
        i = next(k for k, ln in enumerate(lines) if ln.upper().startswith(label))
    except StopIteration:
        return [], None
    block = []
    for ln in lines[i + 1:]:
        if ln.upper().startswith("ACADEMIC YEAR"):
            break
        block.append(ln)
    out, pending, latest = [], None, None
    for k, ln in enumerate(block):
        m = re.match(r"([A-Za-z]+)\s+(\d{1,2})\s*,\s*(\d{4})(?:\s*@\s*(\d{1,2}):(\d{2})h?)?", ln)
        if m and pending:
            mo, d, y = MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
            iso = local_iso(y, mo, d, int(m.group(4)), int(m.group(5))) if m.group(4) else local_iso(y, mo, d)
            room = ""
            if k + 1 < len(block) and block[k + 1].lower().startswith("room"):
                room = block[k + 1].split(":", 1)[-1].strip()
            name, _, affil = pending.partition(",")
            if start <= iso[:10] <= end:
                out.append({
                    "inst": "IESE", "host": "IESE Business School", "series": "IESE Economics & Finance Seminar",
                    "kind": "seminar", "field": "Finance", "internal": False,
                    "canceled": "cancel" in ln.lower(),
                    "start": iso, "end": None, "all_day": "T" not in iso,
                    "talks": [{"speaker": name.strip(), "affil": affil.strip(), "title": "", "note": ""}],
                    "location": f"Room {room}" if room and room.lower() != "tbd" else "",
                    "notes": [], "mode": "", "url": IESE_URL, "source": "IESE Research Seminars",
                })
            pending = None
        elif not ln.lower().startswith("room"):
            pending = ln
    return out, label


# ---------------------------------------------------------------- Esade

ESADE_URL = "https://www.esade.edu/faculty-research/en/group-research-economics-finance/events"
ESADE_CARD = re.compile(
    r'<a href="(?P<url>/faculty-research/en/group-research-economics-finance/event/[^"]+)"[^>]*rel="bookmark">\s*'
    r'<div class="bottom">\s*<h3>(?P<title>.*?)</h3>\s*(?:<div class="authors">(?P<authors>.*?)</div>)?'
    r'.*?<time class="post-subtitle__date" datetime="(?P<dt>[^"]+)"', re.S)


def collect_esade(start, end):
    raw = get(ESADE_URL) or ""
    out = []
    stamps = re.findall(r'class="post-subtitle__date" datetime="(\d{4}-\d{2}-\d{2})', raw)
    latest = max(stamps) if stamps else None  # newest seminar date listed anywhere on the page
    for c in ESADE_CARD.finditer(raw):
        d = c.group("dt").strip()  # '2025-11-19 12:30'
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?", d)
        if not m:
            continue
        y, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        iso = local_iso(y, mo, dd, int(m.group(4)), int(m.group(5))) if m.group(4) else local_iso(y, mo, dd)
        if not (start <= iso[:10] <= end):
            continue
        title = " ".join(text_lines(c.group("title")))
        authors = " ".join(text_lines(c.group("authors") or ""))
        out.append({
            "inst": "Esade", "host": "Esade economics and finance group", "series": "Esade Economics and Finance Seminar", "kind": "seminar",
            "field": field_of(title) if field_of(title) != "Other" else "Finance",
            "internal": False, "canceled": False, "start": iso, "end": None, "all_day": "T" not in iso,
            "talks": [{"speaker": authors, "affil": "", "title": title, "note": ""}],
            "location": "Esade Pedralbes campus", "notes": [], "mode": "",
            "url": "https://www.esade.edu" + c.group("url"), "source": "Esade GREF events",
        })
    return out, latest


# ---------------------------------------------------------------- IEB (UB)
# IEB posts more than the UB School of Economics list carries: its work-in-progress (IWIP) series,
# workshops, colloquia and symposia. Its regular seminars duplicate UB's list and are merged away.

IEB_URL = "https://ieb.ub.edu/en/events/"
IEB_CARD = re.compile(r'<div class="(?:grid-col )?dmach-grid-item[^"]*post_id_(\d+)[^"]*"[^>]*>')


def parse_ieb_time(s):
    m = re.search(r"(\d{1,2})(?:[.:h](\d{2}))?\s*h?(?:\s*-\s*(\d{1,2})(?:[.:h](\d{2}))?)?", s or "")
    if not m:
        return None, None
    return (int(m.group(1)), int(m.group(2) or 0)), ((int(m.group(3)), int(m.group(4) or 0)) if m.group(3) else None)


def collect_ieb(start, end):
    cards = {}
    for page in range(1, 12):
        raw = get(IEB_URL if page == 1 else f"{IEB_URL}page/{page}/")
        found = list(IEB_CARD.finditer(raw or ""))
        if not found:
            break
        dates = []
        for k, m in enumerate(found):
            chunk = raw[m.start():found[k + 1].start() if k + 1 < len(found) else m.start() + 15000]
            lines = [x for x in text_lines(chunk) if x.strip(" :")]
            # the date is three lines: day, month name, year
            for i in range(len(lines) - 2):
                if re.fullmatch(r"\d{1,2}", lines[i]) and lines[i + 1].lower() in MONTHS and re.fullmatch(r"20\d\d", lines[i + 2]):
                    day = dt.date(int(lines[i + 2]), MONTHS[lines[i + 1].lower()], int(lines[i]))
                    dates.append(day.isoformat())
                    link = re.search(r'href="(https://ieb\.ub\.edu/[^"]*events/[^"]+)"', chunk)
                    cards.setdefault(m.group(1), (lines[:i], day, link.group(1) if link else ""))
                    break
        if dates and min(dates) < start:
            break
    out = []
    for pid, (lines, day, link) in cards.items():
        if not (start <= day.isoformat() <= end) or len(lines) < 2:
            continue
        cat, title, rest = lines[0], lines[1], lines[2:]
        hora = next((k for k, x in enumerate(rest) if x.lower().startswith("hora")), None)
        tstr, venue = "", ""
        if hora is not None:
            after = rest[hora].split(":", 1)[1].strip() if ":" in rest[hora] else ""
            tstr = after or (rest[hora + 1] if hora + 1 < len(rest) else "")
            venue_i = hora + (1 if after else 2)
            venue = rest[venue_i] if venue_i < len(rest) else ""
        elif rest:
            venue = rest[0]
        t0, t1 = parse_ieb_time(tstr)
        iso = local_iso(day.year, day.month, day.day, *t0) if t0 else day.isoformat()
        iso_end = local_iso(day.year, day.month, day.day, *t1) if t1 else None
        title = re.sub(r"^SEMINAR:\s*", "", title)
        catl = cat.lower()
        talks, series, no_titles = [], title, False
        if "seminar" in catl and "iwip" not in catl and "(" in title:
            series = "IEB Seminar"
        elif "iwip" in catl:
            series, no_titles = "IEB IWIP Seminar", True
        if series in ("IEB Seminar", "IEB IWIP Seminar"):
            q = re.search(r"[“\"](.+?)[”\"]", title)
            who = (title[:q.start()] if q else title).strip(" –-")
            name, affil = split_affil(who)
            talks = [{"speaker": name, "affil": affil, "title": q.group(1).strip() if q else "", "note": ""}]
        if "workshop" in catl:
            kind = "workshop"
        elif "conference" in catl and "coloqui" in title.lower():
            kind = "lecture"
        elif "conference" in catl or "symposium" in catl:
            kind = "conference"
        elif series.startswith("IEB"):
            kind = "seminar"
        else:
            kind = kind_of(title)
        on_campus = bool(re.search(r"(?i)\broom\b|facultat d.economia|faculty of econom|seminar room", venue))
        out.append({
            "inst": "UB", "host": "Institut d'Economia de Barcelona (IEB)", "series": series, "kind": kind,
            # IEB works on public, urban and energy economics: its events are applied unless the series says otherwise
            "field": field_of(series) if series.startswith("IEB") else ("Other" if kind == "other" else "Applied & policy"),
            "internal": bool(re.search(r"(?i)ph\.?d[- ]students?", title)),
            "canceled": bool(re.search(r"(?i)cancel", title)),
            "start": iso, "end": iso_end, "all_day": t0 is None,
            "talks": talks, "location": venue, "campus": "Diagonal campus" if on_campus else "",
            "notes": [], "mode": "", "no_titles": no_titles,
            "url": link or f"https://ieb.ub.edu/?p={pid}", "source": "IEB events",
        })
    return out


# ---------------------------------------------------------------- merging sources

def _surnames(e):
    out = set()
    for t in e.get("talks", []):
        for person in re.split(r",|&| and ", t.get("speaker") or ""):
            words = re.findall(r"[^\W\d_]{3,}", person.lower())
            if words:
                out.add(words[-1])
    return out


def _long_words(e):
    text = " ".join([e.get("series", "")] + [t.get("title", "") for t in e.get("talks", [])])
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return {w for w in re.findall(r"[a-z]{8,}", text)}


def merge_duplicates(events, secondary):
    """Drop events from `secondary` sources that another source already lists (same day, and the same
    speaker, or the same start time when neither names a speaker). A dropped duplicate's room fills
    an empty location on the kept event."""
    kept = [e for e in events if e["source"] not in secondary]
    by_day = {}
    for e in kept:
        by_day.setdefault(e["start"][:10], []).append(e)
    for e in events:
        if e["source"] not in secondary:
            continue
        twin = None
        for p in by_day.get(e["start"][:10], []):
            same_person = _surnames(p) & _surnames(e)
            same_slot = p["start"] == e["start"] and (not _surnames(p) or not _surnames(e))
            if same_person or same_slot:
                twin = p
                break
        if twin is None and not _surnames(e):
            # the same speakerless event (a colloquium, say) listed a few days apart by two sources,
            # in different languages: same time of day, same institution, a long word in common
            for p in kept:
                if (p["inst"] == e["inst"] and not _surnames(p) and p["start"][10:] == e["start"][10:]
                        and abs((dt.date.fromisoformat(p["start"][:10]) - dt.date.fromisoformat(e["start"][:10])).days) <= 3
                        and _long_words(p) & _long_words(e)):
                    twin = p
                    break
        if twin is None:
            kept.append(e)
            by_day.setdefault(e["start"][:10], []).append(e)
        elif not twin.get("location") and e.get("location"):
            twin["location"] = e["location"]
    return kept


# ---------------------------------------------------------------- main

SOURCES = [
    # key, display name, url, collector, the "source" label carried by each event
    ("BSE", "BSE events calendar", "https://events.bse.eu/all", collect_bse,
     "BSE events calendar"),
    ("UB", "UB School of Economics activities", "https://www.ub.edu/school-economics/activities/", collect_ub,
     "UB School of Economics activities"),
    ("IESE", "IESE Research Seminars", IESE_URL, collect_iese, "IESE Research Seminars"),
    ("Esade", "Esade economics and finance events", ESADE_URL, collect_esade, "Esade GREF events"),
    # after UB, so UB's own entries win and IEB only adds what UB's list lacks
    ("IEB", "IEB events", IEB_URL, collect_ieb, "IEB events"),
]

# Sources that each live in sources/<module>.py, all secondary: they mostly add series the main
# listings above lack, and anything those listings already have is merged away.
#   key, display name, url, module, the "source" label its events carry
EXTRA_SOURCES = [
    ("UAB-AE", "UAB Applied Economics seminars", "https://www.uab.cat/ca/economia-aplicada/seminarisdepartament",
     "uab_applied", "UAB Applied Economics seminars"),
    ("GCAL", "Google Calendar feeds", "https://sites.google.com/view/ubtecoseminars/home",
     "gcal", "Google Calendar feeds"),
    ("CREI", "CREI events", "https://crei.cat/conferences/", "crei", "CREI events"),
    ("UB-MISC", "UB department and group pages", "https://sites.google.com/view/ubmacro",
     "ub_misc", "UB department and group pages"),
    ("UAB-UHE", "UAB Economic History seminars", "https://www.uab.cat/en/economics-economic-history/uhe/research/seminars",
     "uab_history", "UAB Economic History seminars"),
    ("UPF-STATS", "UPF Statistics seminars", "https://www.upf.edu/web/statistics-group/seminars",
     "upf_stats", "UPF Statistics seminars"),
]
SECONDARY = {"IEB events"} | {s[4] for s in EXTRA_SOURCES}  # dropped when another source already lists them

# one line per source for the page's Sources section
ABOUT = {
    "BSE": "UPF Economics and Business, CREI, UAB economics (Bellaterra series, MicroLab), IAE-CSIC and school-wide lectures.",
    "UB": "IEB, AQR-IREA, IPERG, Economic Theory, Game Theory, Economic History and the International Macro History Online Seminar, plus thesis defences.",
    "IESE": "Economics and finance seminars. Speakers and dates only, no paper titles.",
    "Esade": "Seminars of Esade's Group for Research in Economics and Finance.",
    "IEB": "The Institut d'Economia de Barcelona's work-in-progress (IWIP) seminars, workshops, colloquia and symposia.",
    "UAB-AE": "UAB Department of Applied Economics: departmental seminar, applied lunch seminar and job-market talks.",
    "GCAL": "Public calendars of the UB Economic Theory group, the UAB Department of Business and the Bellaterra Applied Working Group.",
    "CREI": "CREI Lectures in Macroeconomics and CREI conferences.",
    "UB-MISC": "UB macro workshop and the actuarial and financial mathematics seminar.",
    "UAB-UHE": "UAB Economic History Unit research seminars.",
    "UPF-STATS": "UPF Statistics, Probability and Machine Learning group seminars.",
}


def all_sources():
    """The built-in sources plus every extra module that exists. Modules import this file's helpers,
    so they are loaded here, after those are defined."""
    import importlib
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    out = list(SOURCES)
    for key, name, url, module, label in EXTRA_SOURCES:
        try:
            mod = importlib.import_module(f"sources.{module}")
        except ModuleNotFoundError:
            continue  # not written (e.g. a site with no scriptable listing)
        out.append((key, name, url, mod.collect, label))
    return out


def load_previous(start, end):
    """Last good run, used when a source is down. Only reused within the same academic year."""
    try:
        prev = json.loads((HERE / "data" / "seminars.json").read_text())
    except (OSError, ValueError):
        return [], {}
    if prev.get("meta", {}).get("window") != [start, end]:
        return [], {}
    return prev.get("events", []), {s.get("key"): s for s in prev["meta"].get("sources", [])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, help="first calendar year of the academic year (default: current)")
    ap.add_argument("--fail", action="append", default=[], metavar="KEY",
                    help="pretend a source (by key, e.g. UB or GCAL) is down, to test the fallback")
    args = ap.parse_args()
    now = dt.datetime.now(MAD).isoformat(timespec="minutes")
    today = dt.datetime.now(MAD).date()
    y0 = args.year or (today.year if today.month >= 8 else today.year - 1)
    start, end = f"{y0}-09-01", f"{y0 + 1}-07-31"

    prev_events, prev_sources = load_previous(start, end)
    events, sources = [], []

    for key, name, url, fn, label in all_sources():
        before = prev_sources.get(key, {})
        error = None
        try:
            if key in args.fail:
                raise RuntimeError("simulated failure (--fail)")
            res = fn(start, end)
            extra = None
            if isinstance(res, tuple):
                res, extra = res
            if not res and before.get("count"):
                # a source that had events yesterday and none today has most likely changed its markup
                error = f"returned 0 events (had {before['count']})"
        except Exception as e:
            error = str(e)
        if error is None:
            events.extend(res)
            sources.append({"key": key, "name": name, "url": url, "count": len(res), "ok": True,
                            "last_ok": now, "error": "", "extra": extra, "about": ABOUT.get(key, "")})
            print(f"{name}: {len(res)}", file=sys.stderr)
        else:
            kept = [e for e in prev_events if e.get("source") == label]
            events.extend(kept)
            sources.append({"key": key, "name": name, "url": url, "count": len(kept), "ok": False,
                            "last_ok": before.get("last_ok"), "error": error, "extra": before.get("extra"),
                            "about": ABOUT.get(key, "")})
            print(f"{name}: FAILED ({error}); kept {len(kept)} events from {before.get('last_ok')}",
                  file=sys.stderr)

    raw_count = len(events)
    events = merge_duplicates(events, SECONDARY)
    print(f"merged {raw_count - len(events)} duplicate events", file=sys.stderr)
    campus = {"UPF": "Ciutadella campus", "UAB": "Bellaterra campus", "UB": "Diagonal campus",
              "IESE": "Pedralbes campus", "Esade": "Pedralbes campus"}
    events.sort(key=lambda e: (e["start"], e["inst"], e["series"]))
    for i, e in enumerate(events):
        e["id"] = i
        if "campus" not in e:  # a collector may set it, e.g. off-campus IEB venues get none
            e["campus"] = campus.get(e["inst"], "")
    meta = {
        "collected_at": now,
        "window": [start, end],
        "academic_year": f"{y0}–{str(y0 + 1)[2:]}",
        "sources": sources,
    }
    payload = {"meta": meta, "events": events}
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    (HERE / "data").mkdir(exist_ok=True)
    (HERE / "data" / "seminars.json").write_text(text)

    # the static site GitHub Pages serves (or any web server: just serve this folder)
    site = HERE / "docs"
    site.mkdir(exist_ok=True)
    (site / ".nojekyll").write_text("")
    (site / "seminars.json").write_text(text)
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    page = (HERE / "page_template.html").read_text().replace("__SEMINARS_DATA__", blob)
    (site / "index.html").write_text(page)
    print(f"total events: {len(events)}; wrote docs/index.html", file=sys.stderr)

    if all(not s["ok"] for s in sources) and not events:
        sys.exit("every source failed and there is no earlier data to fall back on")


if __name__ == "__main__":
    main()
