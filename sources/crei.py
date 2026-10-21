"""CREI (UPF) lectures and conferences, which the BSE feed does not carry.
Pages: https://crei.cat/crei-lectures-in-macroeconomics/ and https://crei.cat/conferences/ (current academic
year), plus each entry's /activities/<slug>/ detail page for time, affiliation and venue."""
import datetime as dt
import re

from collect import get, text_lines, split_affil, local_iso, field_of, MONTHS

LECTURES_URL = "https://crei.cat/crei-lectures-in-macroeconomics/"
CONFERENCES_URL = "https://crei.cat/conferences/"
SOURCE = "CREI events"

MONTH = dict(MONTHS, sept=9)
MON = r"\b(" + "|".join(sorted(MONTH, key=len, reverse=True)) + r")\b\.?"
RANGE = re.compile(MON + r"\s+(\d{1,2})(?:\s*[-–]\s*(?:" + MON + r"\s+)?(\d{1,2}))?,?\s+(\d{4})", re.I)
TIME_RANGE = re.compile(r"(\d{1,2})[:.](\d{2})\s*h?\s*[-–]\s*(\d{1,2})[:.](\d{2})")
TIME_ONE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
LINK_NOTE = re.compile(r"(?i)\s*[\[(]?\s*link to personal website\s*[\])]?.*$")


def _clean(fragment):
    return " ".join(text_lines(fragment))


def _days(text):
    """'November 18-20, 2026' / 'March 5, 2026' / 'June 30 - July 2, 2027' -> list of dates."""
    m = RANGE.search(text or "")
    if not m:
        return []
    mo1, d1, mo2, d2, y = m.groups()
    first = dt.date(int(y), MONTH[mo1.lower()], int(d1))
    last = dt.date(int(y), MONTH[(mo2 or mo1).lower()], int(d2 or d1))
    if last < first or (last - first).days > 14:
        return [first]
    return [first + dt.timedelta(k) for k in range((last - first).days + 1)]


def _field(*texts):
    t = " ".join(x for x in texts if x).lower()
    if re.search(r"macro|international|monetary|exchange rate|trade|growth", t):
        return "Macro & international"
    if re.search(r"spatial|urban|regional|geograph", t):
        return "Applied & policy"
    return field_of(*texts)


def _description(page):
    m = re.search(r'(?s)<div class="event-description">(.*?)</div>', page or "")
    return text_lines(m.group(1)) if m else []


def _lecture_detail(lines, speaker, days):
    """Pull speaker/affil, explicit lecture days, time and venue out of the detail page's paragraphs."""
    name, affil = split_affil(speaker)
    info = {"name": name, "affil": affil, "days": days, "time": None, "location": "", "campus": ""}
    for ln in lines:
        if name and ln.startswith(name):
            n2, a2 = split_affil(LINK_NOTE.sub("", ln))
            info["name"], info["affil"] = n2 or name, affil or a2  # the listing's short affiliation wins
            break
    for ln in lines:  # date line, e.g. "November, 18, 19 and 20, 2026" or "14, 15 & 16 November 2018"
        y = re.search(r"\b(20\d\d)\b", ln)
        mo = re.search(MON, ln, re.I)
        if y and mo:
            bare = re.sub(r"\d{1,2}[:.]\d{2}|\b20\d\d\b", " ", ln)
            try:
                listed = [dt.date(int(y.group(1)), MONTH[mo.group(1).lower()], int(d))
                          for d in re.findall(r"\b\d{1,2}\b", bare)]
            except ValueError:
                listed = []
            if listed and days and all(days[0] <= d <= days[-1] for d in listed):
                info["days"] = sorted(set(listed))
            break
    text = " ".join(lines)
    m = TIME_RANGE.search(text)
    if m:
        info["time"] = tuple(int(x) for x in m.groups())
    elif TIME_ONE.search(text):
        info["time"] = tuple(int(x) for x in TIME_ONE.search(text).groups()) + (None, None)
    for ln in lines:
        if re.search(r"(?i)universitat pompeu fabra|campus|\bsala\b|\broom\b", ln):
            if "ciutadella" in ln.lower():
                info["campus"] = "Ciutadella campus"
            loc = re.sub(r"(?i)^\s*universitat pompeu fabra\s*,?\s*", "", ln)
            loc = re.sub(r"(?i)^campus\s+(de\s+la\s+)?ciutadella\s*", "", loc).strip(" -–,")
            loc = re.sub(r"(?i)\(\s*how to get there.*?\)", "", loc).strip()
            info["location"] = re.sub(r"\b[A-ZÀ-Ý]{3,}(?:\s+[A-ZÀ-Ý]{3,})+\b", lambda w: w.group().title(), loc)
            break
    return info


def _event(**kw):
    ev = {"inst": "UPF", "host": "CREI", "internal": False, "canceled": False, "end": None, "all_day": True,
          "talks": [], "location": "", "campus": "", "notes": [], "mode": "", "source": SOURCE}
    ev.update(kw)
    return ev


def _articles(url):
    page = get(url)
    if page is None:
        raise RuntimeError(f"CREI listing not found: {url}")
    return re.findall(r'(?s)<article[^>]*crei-event.*?</article>', page)


def _lectures(start, end):
    out = []
    for art in _articles(LECTURES_URL):
        try:
            date_txt = _clean(re.search(r'(?s)crei-event-date[^>]*>(.*?)</h\d>', art).group(1))
            a = re.search(r'(?s)lecture-title[^>]*>\s*<a href="([^"]+)"[^>]*>(.*?)</a>', art)
            url, title = a.group(1), _clean(a.group(2))
            sp = re.search(r'(?s)crei-event-speaker[^>]*>(.*?)</h\d>', art)
            speaker = _clean(sp.group(1)) if sp else ""
            days = _days(date_txt)
            if not any(start <= d.isoformat() <= end for d in days):
                continue
            info = _lecture_detail(_description(get(url)), speaker, days)
            if re.fullmatch(r"(?i)tb[acd]\.?", title):
                title = ""
            talk = info["name"] and not re.fullmatch(r"(?i)tb[acd]\.?", info["name"])
            n = len(info["days"])
            for k, d in enumerate(info["days"], 1):
                if not start <= d.isoformat() <= end:
                    continue
                t = info["time"]
                out.append(_event(
                    series="CREI Lectures in Macroeconomics", kind="lecture", field="Macro & international",
                    canceled="cancel" in (date_txt + title).lower(),
                    start=local_iso(d.year, d.month, d.day, t[0], t[1]) if t else local_iso(d.year, d.month, d.day),
                    end=local_iso(d.year, d.month, d.day, t[2], t[3]) if t and t[2] is not None else None,
                    all_day=not t,
                    talks=[{"speaker": info["name"], "affil": info["affil"], "title": title,
                            "note": f"Lecture {k} of {n}" if n > 1 else ""}] if talk else [],
                    location=info["location"], campus=info["campus"], url=url))
        except RuntimeError:  # a detail page failed to fetch: let the collector fall back to the last good data
            raise
        except Exception:  # unparseable item
            continue
    return out


def _conferences(start, end):
    out = []
    for art in _articles(CONFERENCES_URL):
        try:
            date_txt = _clean(re.search(r'(?s)crei-event-date[^>]*>(.*?)</h\d>', art).group(1))
            a = re.search(r'(?s)crei-event-title[^>]*>\s*<a href="([^"]+)"[^>]*>(.*?)</a>', art)
            url, title = a.group(1), _clean(a.group(2))
            if re.match(r"(?i)bse summer forum", title):  # the collector excludes the Summer Forum on purpose
                continue
            days = [d for d in _days(date_txt) if start <= d.isoformat() <= end]
            if not days:
                continue
            lines = _description(get(url))
            notes = []
            for i, ln in enumerate(lines):  # "Organized by: A (X) and B (Y)." or "Organizers:" + one name per line
                if len(ln) < 250 and re.search(r"(?i)\borgani[sz](ed by|ers?)\b", ln):
                    names = [x for x in lines[i + 1:i + 5] if "(" in x] if ln.endswith(":") else []
                    notes = [ln + (" " + "; ".join(names) if names else "")]
                    break
            kind = "workshop" if re.search(r"(?i)workshop", title) else "conference"
            field = _field(title) if _field(title) != "Other" else _field(*lines)
            for d in days:
                out.append(_event(
                    series=title, kind=kind, field=field,
                    canceled="cancel" in (date_txt + title).lower(),
                    start=local_iso(d.year, d.month, d.day), notes=notes, url=url))
        except RuntimeError:
            raise
        except Exception:
            continue
    return out


def collect(start, end):
    out, seen = [], set()
    for ev in _lectures(start, end) + _conferences(start, end):
        key = (ev["url"], ev["start"][:10])
        if key not in seen:
            seen.add(key)
            out.append(ev)
    return out
