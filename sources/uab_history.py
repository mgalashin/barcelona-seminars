"""UAB Economic History Unit (UHE) research seminars, from the year accordions on
https://www.uab.cat/en/economics-economic-history/uhe/research/seminars
(no feed and no per-event pages; each talk is a date|time room line, a speaker line and a title line)."""
import re

from collect import get, text_lines, local_iso

URL = "https://www.uab.cat/en/economics-economic-history/uhe/research/seminars"
SOURCE = "UAB Economic History seminars"

BLOCK = re.compile(r'(?s)<h[23][^>]*class="acordio-titol"[^>]*>.*?<span>\s*[^<]*?\d{4}[^<]*?\s*</span>.*?</h[23]>'
                   r'\s*<div id="acordio-contingut-\d+" class="acordio-contingut[^"]*"[^>]*>(.*?)</div>')
# "1-10-2026 | 14:00 Seminar room B3-112C", "2025-11-5 | 2:30 pm Seminar room B3-112C"
DATE_LINE = re.compile(r"(?i)^(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})\s*\|?\s*"
                       r"(?:(\d{1,2})[:.](\d{2})\s*([ap]\.?m\.?)?)?\s*(.*)$")
WITH = re.compile(r"(?i)\s*\(((?:with|amb|con)\s[^)]*)\)|,?\s+\b((?:with|amb|con)\s.+)$")


def _clock(hh, mm, ampm):
    hh, mm = int(hh), int(mm)
    if ampm and ampm[0].lower() == "p" and hh < 12:
        hh += 12
    elif ampm and ampm[0].lower() == "a" and hh == 12:
        hh = 0
    return hh, mm


def _speaker(line):
    """'Anna Solé (with X and Y) , UAB.' -> ('Anna Solé', 'UAB', '(with X and Y)')."""
    note = ""
    m = WITH.search(line)
    if m:
        note = f"({(m.group(1) or m.group(2)).strip(' .')})"
        line = line[:m.start()] + line[m.end():]
    name, _, affil = line.partition(",")
    return name.strip(), affil.strip().rstrip(".").strip(), note


def _record(head, rest):
    """head: DATE_LINE match; rest: following lines up to the next date line -> (start, room, talk, lines)."""
    a, b, c, hh, mm, ampm, room = head.groups()
    y, mo, d = (int(a), int(b), int(c)) if len(a) == 4 else (int(c), int(b), int(a))
    start = local_iso(y, mo, d, *_clock(hh, mm, ampm)) if hh else local_iso(y, mo, d)
    if not rest:
        return None
    name, affil, note = _speaker(rest[0])
    title = rest[1].strip().strip('"“”«»').strip() if len(rest) > 1 else ""
    if title.endswith(".") and not title.endswith(".."):
        title = title[:-1].strip()
    if not name:
        return None
    return start, room.strip(), {"speaker": name, "affil": affil, "title": title, "note": note}, rest


def collect(start, end):
    raw = get(URL)
    if raw is None:
        raise RuntimeError(f"{URL} returned 404")
    blocks = BLOCK.findall(raw) or [raw]
    events = {}
    for body in blocks:
        lines = text_lines(body)
        heads = [i for i, ln in enumerate(lines) if DATE_LINE.match(ln)]
        for k, i in enumerate(heads):
            rest = lines[i + 1:heads[k + 1] if k + 1 < len(heads) else len(lines)]
            try:
                rec = _record(DATE_LINE.match(lines[i]), rest)
            except (ValueError, IndexError):
                continue
            if not rec or not (start <= rec[0][:10] <= end):
                continue
            iso, room, talk, rest = rec
            # status markers: the room line, lines after the title, or an all-caps word in the speaker/title line
            # ("CANCEL·LAT"), but not ordinary title words: a history talk may well be about debt "cancellation"
            blob = " ".join([room] + rest[2:] + re.findall(r"\b[A-ZÀ-Ý][A-ZÀ-Ý·]+\b", " ".join(rest[:2])))
            ev = events.get(iso)
            if ev is None:
                ev = events[iso] = {
                    "inst": "UAB", "host": "UAB Economic History Unit", "series": "UAB Economic History Seminar",
                    "kind": "seminar", "field": "Economic history", "internal": False, "canceled": False,
                    "start": iso, "end": None, "all_day": "T" not in iso, "talks": [],
                    "location": room, "campus": "Bellaterra campus", "notes": [], "mode": "",
                    "url": URL, "source": SOURCE,
                }
            if re.search(r"(?i)cancel|anul·?l|suspès|suspendid", blob):
                ev["canceled"] = True
            if re.search(r"(?i)postponed|ajornat|aplazad", blob) and "Postponed" not in ev["notes"]:
                ev["notes"].append("Postponed")
            if all(t["speaker"] != talk["speaker"] for t in ev["talks"]):
                ev["talks"].append(talk)
    return sorted(events.values(), key=lambda e: e["start"])
