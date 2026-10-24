"""Question understanding: SLM proposes a JSON reading, deterministic rules validate and fill gaps,
then the code gate decides whether to answer, ask, or decline. Nothing here is guessed silently."""
import re
from datetime import datetime, timedelta, time as dtime
import geoai_slm as slm
from geoai_config import ACT

PAT = [("photography", r"\b(photo\w*|golden hour)\b"),
 ("running", r"\b(runs?|running|jog\w*|marathon|5k|10k)\b"),
 ("cycling", r"\b(cycl\w*|bike|biking|bicycle\w*)\b"),
 ("golf", r"\bgolf\w*\b"), ("cricket", r"\bcricket\b"),
 ("football", r"\b(football|five-a-side|5-a-side|futsal|soccer)\b"), ("tennis", r"\btennis\b"),
 ("hiking", r"\b(hik\w*|trek\w*|trail\w*|nature walk)\b"),
 ("picnic", r"\b(picnic\w*|park outing)\b"),
 ("event", r"\b(wedding|fair|party|birthday|gathering|reception|barbecue|bbq|concert|festival|outdoor event)\b"),
 ("walk", r"\b(walk\w*|stroll\w*)\b")]
OTHER = r"\b(swim\w*|ski\w*|surf\w*|skydiv\w*|fishing|camping|kayak\w*|climbing|scuba|paraglid\w*|badminton|volleyball|basketball|rafting|boating|sailing|horse ?riding)\b"
OUTDOORISH = r"\b(outdoor\w*|outside|go out|weather|park)\b"
PROFILE_PAT = {
 "asthma": r"\b(asthma\w*|wheez\w*|copd|breathing (problem|issue|difficult\w*)|respiratory)\b",
 "senior": r"\b(senior\w*|elderly|old age|retired|grand(?:parents?|mother|father|ma|pa)|parents?|my (?:mom|dad|mother|father))\b",
 "child": r"\b(kids?|child\w*|toddler|infant|baby|son|daughter)\b",
 "pregnancy": r"\b(pregnan\w*|expecting)\b",
 "cardiac": r"\b(heart (?:condition|disease|patient|problem)|cardiac|hypertension|blood pressure)\b"}
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = "january february march april may june july august september october november december".split()
BAD = set(DAYS + MONTHS + ["today", "tomorrow", "tonight", "morning", "evening", "afternoon", "weekend", "week", "night", "the"])
NUMW = {"two": 2, "three": 3, "few": 3, "2": 2, "3": 3, "4": 4, "5": 5}
PART = {"early_morning": (5, 8), "morning": (5, 10), "midday": (11, 14), "lunch": (12, 14), "afternoon": (12, 17),
        "evening": (16, 20), "after_work": (17, 21), "night": (19, 23)}

def h12(h): return f"{(h % 12) or 12} {'AM' if h < 12 else 'PM'}"
def fmt_date(d): return d.strftime("%a %d %b")

# ---------- rule extraction ----------
def rule_activity(ql):
    best = None
    for k, p in PAT + [("other", OTHER)]:
        m = re.search(p, ql)
        if m and (best is None or m.start() < best[0]): best = (m.start(), k, m.group(0))
    return (best[1], best[2]) if best else (None, None)

def rule_profiles(ql):
    found, notes = [], []
    for k, p in PROFILE_PAT.items():
        if re.search(p, ql): found.append(k)
    if re.search(r"\bparents?\b", ql): notes.append("I took 'parents' to mean seniors (60+).")
    for m in re.finditer(r"(\d{1,2})\s*[- ]?\s*(?:year|yr)s?[- ]?old|\baged?\s+(\d{1,2})\b|\bi(?:'m| am)\s+(\d{2})\b", ql):
        n = int(next(g for g in m.groups() if g))
        if n >= 60 and "senior" not in found: found.append("senior")
        if n <= 12 and "child" not in found: found.append("child")
    return found, notes

def rule_radius(ql):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(km|kms|kilomet\w+|miles?|mi)\b", ql)
    if not m: return None
    v = float(m.group(1)) * (1.609 if m.group(2).startswith("mi") else 1)
    return round(min(v, 50), 1)

CAP = r"([A-Z][\w'’\-]*(?:[ ,]+[A-Z][\w'’\-]*)*)"
TRIG = (r"(?i:\bnear|\baround|\bin|\bat|\bclose to|\bnearby|\bfrom|"
        r"\bwithin\s+\d+(?:\.\d+)?\s*(?:km|kms|kilometers?|kilometres?|miles?|mi)\s+(?:of|from))\s+(?:(?i:the)\s+)?")
def rule_location(q):
    found = []
    for m in re.finditer(TRIG + CAP, q):
        loc = m.group(1).strip(" ,")
        if loc.split()[0].lower() in BAD or loc.lower() in found: continue
        found.append(loc)
    if found: return ", ".join(found[:2])
    m = re.search(r"(?i)\b(?:near|around|in|close to)\s+([a-z][a-z' \-]{2,40}?)(?=\s+(?:today|tomorrow|tonight|this|next|on|at|for|after|before|between|with|please)\b|[?.,!]|$)", q)
    if m:
        loc = m.group(1).strip()
        if loc.split()[0] not in BAD and not re.match(r"(next|past|morning|evening|afternoon|weekend|coming)", loc): return loc
    return None

def rule_time(ql):
    t = dict(days=[], part=None, hour=None)
    for k, p in [("tonight", r"\btonight\b"), ("today", r"\btoday\b"), ("day_after", r"\bday after tomorrow\b"),
                 ("tomorrow", r"\btomorrow\b"), ("weekend", r"\bweekend\b")]:
        if re.search(p, ql) and not (k == "tomorrow" and "day_after" in t["days"]): t["days"].append(k)
    for i, d in enumerate(DAYS):
        if re.search(rf"\b{d}\b", ql): t["days"].append(f"wd{i}")
    m = re.search(r"\bnext\s+(two|three|few|\d)\s+days?\b", ql)
    if m: t["days"].append(f"n{NUMW[m.group(1)]}")
    if re.search(r"\bnext 48 hours\b", ql): t["days"].append("n2")
    for k, p in [("early_morning", r"\bearly morning|\bdawn\b"), ("morning", r"\bmorning\b"), ("afternoon", r"\bafternoon\b"),
                 ("after_work", r"\bafter (?:work|office)\b"), ("evening", r"\bevening\b"), ("night", r"\bnight\b|\btonight\b"),
                 ("lunch", r"\blunch\b"), ("midday", r"\bnoon\b|\bmidday\b")]:
        if re.search(p, ql): t["part"] = k; break
    if re.search(r"\bsunset|sundown|golden hour", ql): t["part"] = "sunset"
    elif re.search(r"\bsunrise\b", ql): t["part"] = "sunrise"
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)", ql)
    if m:
        h = int(m.group(1)) % 12 + (12 if m.group(3).startswith("p") else 0); t["hour"] = h
    else:
        m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", ql)
        if m: t["hour"] = int(m.group(1))
    return t

# ---------- SLM reading ----------
SLM_SYS = ("You convert an outdoor-activity question into JSON. Output ONLY one JSON object with keys: "
 '"activity" (one of running, cycling, golf, cricket, football, tennis, hiking, walk, picnic, event, photography, other, none), '
 '"location" (place name copied exactly from the question, or null), "radius_km" (number or null), '
 '"day" (day words copied from the question, or null), "part_of_day" (morning, afternoon, evening, night or null), '
 '"health" (list from asthma, senior, child, pregnancy; empty if none). Never invent a place. '
 'Example: "Good time for a jog in Indiranagar tomorrow morning? I am pregnant." -> '
 '{"activity":"running","location":"Indiranagar","radius_km":null,"day":"tomorrow","part_of_day":"morning","health":["pregnancy"]}')

def slm_read(q):
    if not slm.ready(): return None
    return slm.json_from(slm.generate(SLM_SYS, q, max_new=90, max_time=25))

def parse_query(q):
    ql = q.lower()
    act, other_name = rule_activity(ql)
    loc = rule_location(q)
    s = (slm_read(q) or {}) if (act is None or loc is None) else {}     # model only helps when rules found nothing
    if act is None and s.get("activity") in ACT: act = s["activity"]
    elif act is None and s.get("activity") == "other": act, other_name = "other", "that activity"
    profiles, notes = rule_profiles(ql)
    for p in (s.get("health") or []):
        if p in ("asthma", "senior", "child", "pregnancy") and p not in profiles and re.search(PROFILE_PAT[p], ql): profiles.append(p)
    sl = s.get("location")
    if not loc and isinstance(sl, str) and 2 <= len(sl) <= 60 and re.sub(r"\W+", " ", sl.lower()).strip() in re.sub(r"\W+", " ", ql):
        loc = sl.strip()                       # accept the SLM's place only if it literally appears in the question
    t = rule_time(ql)
    if not t["days"] and t["part"] is None and t["hour"] is None and (s.get("day") or s.get("part_of_day")):
        t = rule_time(f'{s.get("day") or ""} {s.get("part_of_day") or ""}'.lower())
    subject = "other" if re.search(r"\b(my|our) (parents?|mom|mother|dad|father|grand\w+|kids?|son|daughter|children|child|wife|husband|friends?|team|class)\b", ql) or "kids" in ql else "self"
    return dict(activity=act, other_name=other_name, location=loc, radius_km=rule_radius(ql), time=t, profiles=profiles,
                subject=subject, notes=notes, method="slm+rules" if s else "rules", _ql=ql)

def gate(p, has_coords):
    """Returns None to proceed, or (status, message, question)."""
    sup = ", ".join(a["label"].lower() for a in ACT.values())
    if p["activity"] == "other":
        return ("out_of_scope", f"I can't advise on {p['other_name']} yet. I cover: {sup}.", None)
    if p["activity"] is None:
        if re.search(OUTDOORISH, p["_ql"]):
            return ("needs_info", "Which outdoor activity do you have in mind?", "Which activity: running, cycling, golf, cricket, football, tennis, hiking, a walk, a picnic, an event or photography?")
        return ("out_of_scope", f"I only advise on outdoor activities using live weather and map data. I cover: {sup}.", None)
    if not p["location"] and not has_coords:
        return ("needs_info", "I need an area to search before I can recommend a place.",
                "Which neighbourhood or city should I look around, and how far are you willing to travel?")
    return None

# ---------- time window ----------
def resolve_window(t, now, sun, avail):
    A, today = [], now.date()
    days, part, hr = list(t["days"]), t["part"], t["hour"]
    if "tonight" in days: part = part or "night"
    dates = []
    def add(d):
        if d not in dates: dates.append(d)
    for tok in days:
        if tok in ("today", "tonight"): add(today)
        elif tok == "tomorrow": add(today + timedelta(1))
        elif tok == "day_after": add(today + timedelta(2))
        elif tok == "weekend":
            wd = today.weekday()
            ds = [today, today + timedelta(1)] if wd == 5 else [today] if wd == 6 else [today + timedelta((5 - wd) % 7), today + timedelta((5 - wd) % 7 + 1)]
            for d in ds: add(d)
            A.append("I took 'weekend' as " + " and ".join(fmt_date(d) for d in ds) + ".")
        elif tok[0] == "n" and tok[1:].isdigit():
            for k in range(int(tok[1:])): add(today + timedelta(k))
            A.append(f"I took 'next {tok[1:]} days' as {fmt_date(today)} onward.")
        elif tok.startswith("wd"): add(today + timedelta((int(tok[2:]) - today.weekday()) % 7))
    def rng(d):
        if hr is not None: return hr, min(hr + 1, 23)
        if part in PART: return PART[part]
        if part in ("sunset", "sunrise") and sun.get(d.isoformat()):
            ts = datetime.fromisoformat(sun[d.isoformat()][1 if part == "sunset" else 0])
            return (ts.hour - 1, ts.hour) if part == "sunset" else (ts.hour, ts.hour + 1)
        return 5, 22
    floor = now.replace(minute=0, second=0, microsecond=0)
    if not dates:
        if part is None and hr is None:
            slots = [floor + timedelta(hours=i) for i in range(24)]
            A.append("No time was given, so I looked at the next 24 hours.")
            return [s for s in slots if s in avail], "the next 24 hours", A
        d = today if now.hour <= rng(today)[1] else today + timedelta(1)
        add(d); A.append(f"No day was given, so I used {'today' if d == today else 'tomorrow'}.")
    dates.sort(); slots, labels = [], []
    for d in dates:
        a, b = rng(d)
        for h in range(a, b + 1):
            dt = datetime.combine(d, dtime(h))
            if dt >= floor and dt in avail: slots.append(dt)
        labels.append(f"{fmt_date(d)} {h12(a)}–{h12(b)}" if hr is None or True else "")
    if part in PART: A.append(f"I took '{part.replace('_', ' ')}' as {h12(PART[part][0])}–{h12(PART[part][1])}.")
    if part is None and hr is None: A.append("No time of day was given, so I considered 5 AM–10 PM.")
    if not slots: A.append("That time is already past or beyond the 7-day forecast.")
    return slots, "; ".join(labels), A
