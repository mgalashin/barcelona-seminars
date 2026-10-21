"""UB department and group pages: the Xavier Raurich UB Macro Workshop (sites.google.com/view/ubmacro),
the Financial and Actuarial Mathematics Seminar (web.ub.edu/.../departament-matematica-economica) and the
Workshop on Pensions and Insurance (Faculty of Economics and Business agenda on web.ub.edu)."""
import datetime as dt
import html
import re

from collect import get, text_lines, split_affil, local_iso, MONTHS

SOURCE = "UB department and group pages"
FEE = "Faculty of Economics and Business"

MACRO_URL = "https://sites.google.com/view/ubmacro"
MAT_URL = "https://web.ub.edu/en/web/departament-matematica-economica/seminari-de-matem%C3%A0tica"
MAT_URL_CA = "https://web.ub.edu/ca/web/departament-matematica-economica/seminari-de-matem%C3%A0tica"
AGENDA = ("https://web.ub.edu/en/web/facultat-economia-empresa/inici?p_p_id=com_liferay_asset_publisher_web_portlet_"
          "AssetPublisherPortlet_INSTANCE_gbyz&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view&_com_liferay_asset_"
          "publisher_web_portlet_AssetPublisherPortlet_INSTANCE_gbyz_cur={page}")
# this year's edition; later editions get a new slug and are found by scanning the agenda
PENSIONS_KNOWN = "https://web.ub.edu/en/web/facultat-economia-empresa/w/workshop-on-pensions-and-insurance-2"


def _event(**kw):
    ev = {"inst": "UB", "internal": False, "canceled": False, "end": None, "all_day": False, "talks": [],
          "location": "", "campus": "Diagonal campus", "notes": [], "mode": "", "source": SOURCE}
    ev.update(kw)
    return ev


# ---------------------------------------------------------------- (a) UB Macro Workshop (Google Site)

def _site_lines(raw):
    """Google Sites splits words across inline tags ('202<span>6'): drop those without a space."""
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", raw)
    s = re.sub(r"(?i)</?(?:span|a|b|strong|em|i|u|font|sup|sub|small)\b[^>]*>", "", s)
    s = re.sub(r"(?i)<(?:p|div|li|h\d|tr|section)\b[^>]*>", "\n", s)
    return text_lines(s)


def collect_macro():
    lines = _site_lines(get(MACRO_URL) or "")
    head = None  # 'November 12-13, 2026 - Barcelona, Spain' under the workshop title; the only place with a year
    for i, ln in enumerate(lines[:-1]):
        if re.search(r"(?i)UB Macro Workshop", ln):
            head = re.match(r"([A-Za-z]+)\s+(\d{1,2})\s*[-–]\s*(?:([A-Za-z]+)\s+)?(\d{1,2})\s*,\s*(20\d\d)\b", lines[i + 1])
            if head:
                break
    if not head or head.group(1).lower() not in MONTHS:
        return []
    year = int(head.group(5))
    location = ""
    if "Venue" in lines:
        for ln in lines[lines.index("Venue") + 1:lines.index("Venue") + 4]:
            if re.match(r"(?i)(sala|aula)\b", ln):
                location = ln.split(",")[0].strip()
                break
    days, day, used = {}, None, set()  # (y, mo, d) -> {"slots": [...], "talks": [...]}
    for i, ln in enumerate(lines):
        if ln == "Venue":
            break
        m = re.match(r"^([A-Za-z]+)\s+(\d{1,2})$", ln)
        if m and m.group(1).lower() in MONTHS:
            day = days.setdefault((year, MONTHS[m.group(1).lower()], int(m.group(2))), {"slots": [], "talks": []})
            continue
        if day is None or i in used:
            continue
        m = re.match(r"^(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})$", ln)
        if m:
            day["slots"].append(tuple(int(x) for x in m.groups()))
            continue
        name, affil = split_affil(ln)
        if affil and len(name.split()) <= 6:  # 'Name (Affiliation)', then the paper title on the next line
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            is_title = nxt != "Venue" and not re.match(r"^(\d{1,2}:\d{2}|[A-Za-z]+\s+\d{1,2}$)", nxt) \
                and not split_affil(nxt)[1]
            if is_title:
                used.add(i + 1)
            day["talks"].append({"speaker": name, "affil": affil, "title": nxt if is_title else "", "note": ""})
    if not days:  # programme not out yet: one all-day row per day of the announced range
        mo1, d1, d2 = MONTHS[head.group(1).lower()], int(head.group(2)), int(head.group(4))
        mo2 = MONTHS.get((head.group(3) or head.group(1)).lower(), mo1)
        try:
            d0, d9 = dt.date(year, mo1, d1), dt.date(year, mo2, d2)
        except ValueError:
            return []
        days = {(x.year, x.month, x.day): {"slots": [], "talks": []}
                for x in (d0 + dt.timedelta(k) for k in range(min((d9 - d0).days + 1, 7)))}
    out = []
    for (y, mo, d), info in sorted(days.items()):
        slots = info["slots"]
        try:
            out.append(_event(
                host="UB macroeconomics group", series="Xavier Raurich UB Macro Workshop", kind="workshop",
                field="Macro & international",
                start=local_iso(y, mo, d, *min(s[:2] for s in slots)) if slots else local_iso(y, mo, d),
                end=local_iso(y, mo, d, *max(s[2:] for s in slots)) if slots else None, all_day=not slots,
                talks=info["talks"], location=location, url=MACRO_URL))
        except ValueError:  # impossible date such as 'November 31'
            continue
    return out


# ---------------------------------------------------------------- (b) Financial and Actuarial Mathematics Seminar

MAT_ITEM = re.compile(r'<div id="(?P<id>[\w-]+)" class="collapse-container.*?data-lfr-editable-id="collapse-title"[^>]*>'
                      r'(?P<head>.*?)</button>(?P<body>.*?)(?=<div id="[\w-]+" class="collapse-container|<style|$)', re.S)
MAT_HEAD = re.compile(r"^\((\d{1,2})/(\d{1,2})/(\d{4})\s*,\s*([^,()]*?)\s*(?:,\s*(\d{1,2})[:.](\d{2})\s*h?)?\s*\)\s*(.+)$")


def _split_speaker_title(s):
    """'Name. Title' -> (name, title), skipping initials and 'Dr.' when looking for the first '. '."""
    for m in re.finditer(r"\.\s+", s):
        last = s[:m.start()].split()[-1] if s[:m.start()].split() else ""
        if len(last) > 1 and last.lower() not in ("dr", "dra", "prof", "sr", "sra", "jr"):
            return s[:m.start()].strip(), s[m.end():].strip().rstrip(".")
    return s.strip(), ""


def collect_mat():
    url = MAT_URL
    raw = get(url)
    if raw is None:
        url, raw = MAT_URL_CA, get(MAT_URL_CA) or ""
    out = []
    for it in MAT_ITEM.finditer(raw):
        try:
            head = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", it.group("head")))).strip()
            m = MAT_HEAD.match(head)
            if not m:
                continue
            d, mo, y, room, hh, mm, rest = m.groups()
            iso = local_iso(int(y), int(mo), int(d), int(hh), int(mm)) if hh else local_iso(int(y), int(mo), int(d))
            speaker, title = _split_speaker_title(rest)
            body = re.search(r'class="collapse-body"[^>]*>(.*)', it.group("body"), re.S)
            lines = text_lines(body.group(1)) if body else []
            surname = speaker.split()[-1].lower() if speaker else "\0"
            affil, note = [], ""
            for ln in lines[:8]:
                if re.match(r"(?i)(e-?mail|abstract)\b", ln) or ln.rstrip(".").lower() == title.lower():
                    break
                if surname in ln.lower():  # the name line, possibly 'Name and Coauthor'
                    others = [p for p in re.split(r"\s*,\s*|\s+and\s+|\s*&\s*", ln) if p and surname not in p.lower()]
                    note = f"(with {' and '.join(others)})" if others and " and " in ln else note
                    continue
                affil.append(ln.strip().rstrip(",.;"))
            room = "" if re.search(r"(?i)\b(tba|tbc|tbd)\b", room) else room.strip()
            out.append(_event(
                host="UB Department of Mathematical Economics, Finance and Actuarial Science",
                series="Financial and Actuarial Mathematics Seminar", kind="seminar", field="Finance",
                canceled=bool(re.search(r"(?i)\b(cancel+ed|cancel·lat|anul·lat|suspès|suspended|postponed|ajornat|aplaçat)\b", head)),
                start=iso, all_day="T" not in iso,
                talks=[{"speaker": speaker, "affil": ", ".join(affil[:3]), "title": title, "note": note}],
                location=f"{room}, {FEE}" if room else FEE, url=f"{url}#{it.group('id')}"))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------- (c) Workshop on Pensions and Insurance

def collect_pensions():
    urls = [PENSIONS_KNOWN]
    for page in (1, 2, 3):  # agenda is sorted by event date, newest first; upcoming items also sit in a sidebar
        for href, title in re.findall(r'<h3 class="title">\s*<a href="([^"]+)">([^<]*)</a>', get(AGENDA.format(page=page)) or ""):
            if re.search(r"(?i)pensions?\b.*insurance", html.unescape(title)) and href not in urls:
                urls.append(href)
    out = []
    for url in urls:
        raw = get(url)
        if not raw:
            continue
        try:
            m = re.search(r"cal\.addEvent\(.*'(\d{1,2})/(\d{1,2})/(\d{4})\s*',\s*'(\d{1,2})/(\d{1,2})/(\d{4})\s*'\s*\)", raw)
            if m:
                mo1, d1, y1, mo2, d2, y2 = map(int, m.groups())
            else:  # visible 'dd/mm/yy - dd/mm/yy'
                t = re.search(r'calendario\.svg.*?class="text-icon">(.*?)</span>', raw, re.S)
                ds = re.findall(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", t.group(1) if t else "")
                if not ds:
                    continue
                (d1, mo1, y1), (d2, mo2, y2) = [tuple(map(int, x)) for x in (ds[0], ds[-1])]
                y1, y2 = [y + 2000 if y < 100 else y for y in (y1, y2)]
            d0, d9 = dt.date(y1, mo1, d1), dt.date(y2, mo2, d2)
            detail = dict((k.strip(" :").lower(), " ".join(text_lines(v))) for k, v in re.findall(
                r'<span class="detail-title">(.*?)</span>\s*<span class="detail-text">(.*?)</span>', raw, re.S))
            location = detail.get("location", "") or detail.get("lloc", "")
            org = detail.get("organizing", "") or detail.get("organitza", "")
            day = d0
            while day <= d9 and (day - d0).days < 10:
                out.append(_event(
                    host="UB Actuarial and Financial Modelling group", series="Workshop on Pensions and Insurance",
                    kind="workshop", field="Finance", start=local_iso(day.year, day.month, day.day), all_day=True,
                    location=location, campus="Diagonal campus" if re.search(r"(?i)economia i empresa|diagonal", location) else "",
                    notes=[f"Organized by: {org}"] if org else [], url=url))
                day += dt.timedelta(days=1)
        except Exception:
            continue
    return out


# ----------------------------------------------------------------

def collect(start, end):
    out, seen = [], set()
    for ev in collect_macro() + collect_mat() + collect_pensions():
        key = (ev["series"], ev["start"], ev["talks"][0]["speaker"] if ev["talks"] else "")
        if start <= ev["start"][:10] <= end and key not in seen:
            seen.add(key)
            out.append(ev)
    return out
