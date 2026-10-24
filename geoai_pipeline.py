"""One backend for UI and API: parse -> gate -> geocode -> venues -> context -> weather -> score -> narrate."""
import re, time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import geoai_data as data
from geoai_config import ACT, FALLBACK_OSM
from geoai_data import Trace
from geoai_geo import haversine, bearing, dest, compass
from geoai_parse import parse_query, gate, resolve_window, h12, fmt_date
from geoai_score import limits, score_slot, windows
from geoai_narrate import narrate

POOL = ThreadPoolExecutor(8)   # shared: weather, venues and routes are fetched in parallel

def rush(t): return 1.6 if t.weekday() < 5 and (8 <= t.hour < 10 or 17 <= t.hour < 20) else 1.0
def lab(t): return f"{fmt_date(t)} {h12(t.hour)}"
def rg(a, b): return f"{a}" if a == b else f"{a} to {b}"
def kindword(k): return k.split("=")[1].replace("_", " ")
def pt(la, lo, **pr): return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lo, la]}, "properties": pr}

def enrich(pl, ctx):
    pl.update(ctx_ok=ctx is not None, near=[], green_idx=0.5, water_m=None, nearest={})
    if not ctx: return
    for s in ctx["sources"]:
        d = haversine(pl["lat"], pl["lon"], s["lat"], s["lon"])
        if d <= s["R"]: pl["near"].append(dict(s, dist=d, brg=bearing(s["lat"], s["lon"], pl["lat"], pl["lon"])))
    wd = [haversine(pl["lat"], pl["lon"], a, b) for a, b in ctx["water"]]
    pl["water_m"] = round(min(wd)) if wd else None
    gn = sum(1 for a, b in ctx["green"] if haversine(pl["lat"], pl["lon"], a, b) <= 800)
    pl["green_idx"] = min(1, gn/4)*.8 + (.2 if pl["water_m"] is not None and pl["water_m"] <= 800 else 0)
    for typ in ("highway", "industry"):
        nn = [n for n in pl["near"] if n["type"] == typ]
        if nn:
            m = min(nn, key=lambda n: n["dist"]); pl["nearest"][typ] = dict(name=m["name"], dist=round(m["dist"]))

def blocks(rows, flags):
    out, i = [], 0
    while i < len(rows):
        if flags[i]:
            j = i; rs = []
            while j < len(rows) and flags[j]:
                for x in flags[j]:
                    x = re.sub(r"\d+(\.\d+)?", "#", x)
                    if x not in [re.sub(r"\d+(\.\d+)?", "#", y) for y in rs]: rs.append(flags[j][flags[j].index(x)] if x in flags[j] else flags[j][0])
                j += 1
            out.append(dict(**{"from": lab(rows[i]["t"]), "to": h12((rows[j-1]["t"] + timedelta(hours=1)).hour), "reasons": rs[:2]})); i = j
        else: i += 1
    return out

def advice(act, profiles, seg_rows, prev_precip, start):
    carry, watch = [], []
    mf = max(r["feels"] for r in seg_rows); pop = max(r["pop"] for r in seg_rows)
    aq = [r["aqi"] for r in seg_rows if r["aqi"] is not None]; uv = max([r["uv"] for r in seg_rows if r["is_day"]] or [0])
    if mf >= 28: carry.append("plenty of water")
    if pop >= 20: carry.append("a rain jacket or umbrella")
    if aq and max(aq) >= 101: carry.append("an N95 mask")
    if "asthma" in profiles: carry.append("your reliever inhaler")
    if uv >= 6: carry.append("sunscreen, a hat and sunglasses")
    if not seg_rows[-1]["is_day"] and act in ("running", "cycling", "walk", "hiking", "football"):
        carry.append("a torch or lights and reflective clothing")
    if set(profiles) & {"senior", "child", "pregnancy", "cardiac"}:
        carry.append("snacks and a phone"); watch.append("take regular breaks in the shade and stop if you feel unwell")
    if prev_precip >= 2: watch.append("the ground may be wet or slippery after recent rain")
    if rush(start) > 1: watch.append("traffic is heavier at this hour, so leave early")
    watch.append(ACT[act]["tip"])
    return carry, watch

def build_text(L):
    f = [f"Activity: {L['act']}. Profile: {L['prof']}.", f"Requested time: {L['label']}."]
    t = []
    r = L["rec"]
    if r:
        c = r["conditions"]
        trav = f" Driving about {r['travel_min']} minutes." if r.get("travel_min") is not None else ""
        if L["outside"]: f.append("Nothing in the requested time is safe. This is the best slot in the next 48 hours instead.")
        f.append(f"BEST: {r['place']} ({kindword(r['kind'])}) from {r['start_label']} to {r['end_label']}. Score {r['score']} out of 100.{trav}")
        aqs = f", US AQI {rg(c['aqi_min'], c['aqi_max'])}" if c.get("aqi_max") is not None else ""
        f.append(f"Conditions: feels-like {rg(c['feels_min'], c['feels_max'])} °C, rain chance up to {c['rain_max']}%, wind up to {c['wind_max']} km/h from the {c['wind_dir']}{aqs}, UV up to {c['uv_max']}.")
        f.append("Exposure: " + r["exposure"]["text"] + ".")
        for a in L["alts"]:
            f.append(f"ALTERNATIVE: {a['place']} from {a['start_label']} to {a['end_label']}, score {a['score']}.")
        if L["backup"]: f.append(f"BACKUP TIME for {r['place']}: {L['backup']['start_label']} to {L['backup']['end_label']}, score {L['backup']['score']}.")
        for d in L["by_day"]: f.append(f"BY DAY: {d['date']} best is {d['place']} at {d['start_label']}, score {d['score']}.")
        t = [f"**Recommendation:** go to **{r['place']}** from {r['start_label']} to {r['end_label']} (score {r['score']} out of 100).{trav}",
             f"**Why:** feels-like {rg(c['feels_min'], c['feels_max'])} °C, rain chance up to {c['rain_max']}%, wind up to {c['wind_max']} km/h from the {c['wind_dir']}{aqs}. {r['exposure']['text'][0].upper()+r['exposure']['text'][1:]}."]
        if L["outside"]: t[0] = "Nothing in your requested time is safe. " + t[0]
        if L["alts"]: t[1] += " Alternatives: " + "; ".join(f"{a['place']} ({a['start_label']})" for a in L["alts"]) + "."
        if L["backup"]: t[1] += f" Backup time: {L['backup']['start_label']}."
        if L["by_day"] and len(L["by_day"]) > 1: t[1] += " Best per day: " + "; ".join(f"{d['date']} at {d['place']}, {d['start_label']}" for d in L["by_day"]) + "."
    else:
        f.append("NO SAFE SLOT in the requested time or the next 48 hours. Main reasons: " + "; ".join(L["reasons"]) + ".")
        t = [f"**Recommendation:** I would not go in this window. {('Main reasons: ' + '; '.join(L['reasons'])) if L['reasons'] else ''}.",
             "**Why:** every nearby place breaks at least one safety limit for this activity and profile."]
    for a in L["avoid"][:3]: f.append(f"AVOID: {a['scope']} {a['from']} to {a['to']}: {'; '.join(a['reasons'])}.")
    if L["carry"]: f.append("CARRY: " + "; ".join(x.rstrip(".") for x in L["carry"]) + ".")
    if L["watch"]: f.append("WATCH: " + "; ".join(x.rstrip(".") for x in L["watch"]) + ".")
    if L["assump"]: f.append("ASSUMPTIONS: " + " ".join(L["assump"]))
    t.append("**What to carry:** " + ("; ".join(x.rstrip(".") for x in L["carry"]) if L["carry"] else "nothing special beyond your usual kit") + ".")
    w = [x.rstrip(".") for x in L["watch"]] + [f"avoid {a['from']} to {a['to']} ({'; '.join(a['reasons'])})" for a in L["avoid"][:2]]
    t.append("**Watch out and avoid:** " + "; ".join(w) + ".")
    return "\n".join(f), "\n\n".join(t)

def run(query, lat=None, lon=None, use_slm=True):
    t0, tr, q = time.time(), Trace(), (query or "").strip()[:500]
    R = dict(status="ok", query=q, answer="", question=None, parsed=None, assumptions=[], recommendation=None, alternatives=[],
             backup_time=None, by_day=[], avoid_windows=[], carry=[], watch=[], evidence=[], map={"type": "FeatureCollection", "features": []},
             sources_used=[], warnings=[], narration=None, timing={})
    st, mark = {}, [time.time()]
    def lap(name):
        n_ = time.time(); st[name] = round(n_ - mark[0], 2); mark[0] = n_
    def done(status, answer, question=None):
        R.update(status=status, answer=answer, question=question, sources_used=tr.items, warnings=tr.warnings)
        R["timing"].update(total_s=round(time.time() - t0, 2), stages=st); return R
    if not q: return done("needs_info", "Ask a question about an outdoor activity.", "What would you like to do outdoors, and where?")
    p = parse_query(q); ql = p.pop("_ql"); lap("parse")
    R["parsed"] = dict(activity=p["activity"], location=p["location"], radius_km=p["radius_km"], profiles=p["profiles"], subject=p["subject"], reading=p["method"])
    R["assumptions"] = list(p["notes"])
    g = gate(dict(p, _ql=ql), lat is not None and lon is not None)
    if g: return done(*g)
    act = p["activity"]; A = ACT[act]; profiles = p["profiles"]
    if p["location"]:
        geo = data.geocode(p["location"], tr)
        if not geo: return done("needs_info", f"I couldn't find '{p['location']}' on OpenStreetMap.", "Could you add the city or a nearby landmark, for example 'Powai, Mumbai'?")
        olat, olon, where = geo["lat"], geo["lon"], p["location"]
    else: olat, olon, where = lat, lon, "your location"
    lap("geocode")
    fut_wx = POOL.submit(data.forecast, olat, olon, tr)       # weather loads while venues and map data load
    rad = p["radius_km"] or A["rad"]
    if not p["radius_km"]: R["assumptions"].append(f"No distance was given, so I searched within {rad} km.")
    area = dict(id="area", name=f"Around {where}", kind="area=centre", lat=olat, lon=olon, lit=True, access=None, dist=0, origin_only=True)
    commute = act == "cycling" and re.search(r"\b(work|office|commute|commuting)\b", ql)
    if commute:
        places = [area]; R["assumptions"].append("Your route isn't known, so I judged conditions around the area you gave, not along a specific road.")
    else:
        places = data.candidates(olat, olon, int(rad*1000), A["osm"], tr)
        if A["fac"] and places is not None and len(places) < 2:
            more = data.candidates(olat, olon, int(rad*1000), FALLBACK_OSM, tr) or []
            have = {x["id"] for x in places}
            places = (places + [x for x in more if x["id"] not in have])[:8]
            R["assumptions"].append(f"Few {A['label'].lower()} venues are tagged in OpenStreetMap here, so I included open grounds. Confirm availability before going.")
        if not places:
            tr.warn("Map data was unavailable, so I could only judge conditions around the search centre." if places is None
                    else f"No mapped venues matched within {rad} km, so I judged conditions around the search centre.")
            places = [area]
    def trv(pl):
        if pl.get("origin_only"): return dict(min=0, km=0, est=False, geometry=None)
        return data.route((olat, olon), (pl["lat"], pl["lon"]), tr, geom=True)
    futs = [POOL.submit(trv, pl) for pl in places]             # driving times load while map context loads
    ctx = data.context(places, tr)
    if ctx is None: tr.warn("Roads and industry data were unavailable, so pollution exposure was not assessed.")
    for pl in places: enrich(pl, ctx)
    wx = fut_wx.result()
    if not wx: return done("error", "I couldn't reach the weather service, so I can't give a grounded recommendation right now. Please try again shortly.")
    now = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=wx["utc_offset"])
    floor = now.replace(minute=0, second=0, microsecond=0)
    rows = [dict(r, t=datetime.fromisoformat(r["t"])) for r in wx["rows"] if r["temp"] is not None and r["feels"] is not None]
    allrows = rows; rows = [r for r in rows if r["t"] >= floor]
    sun = {d: [datetime.fromisoformat(a_), datetime.fromisoformat(b_)] for d, (a_, b_) in wx["sun"].items()}
    slots, label, tas = resolve_window(p["time"], now, dict(wx["sun"]), {r["t"] for r in rows})
    R["assumptions"] += tas
    if not slots: return done("needs_info", "That time is already past or beyond the 7-day forecast.", "Which day in the next 7 days, and roughly what time?")
    for pl, f in zip(places, futs):
        rt = f.result(); pl["travel"], pl["travel_km"], pl["travel_est"], pl["geom"] = rt["min"], rt["km"], rt["est"], rt.get("geometry")
    lap("fetch_live_data")
    lim = limits(act, profiles); dur = A["dur"]
    series = {pl["id"]: [score_slot(pl, r, pl["travel"]*rush(r["t"]), act, lim, sun) for r in rows] for pl in places}
    def rank(allowed):
        out = []
        for pl in places:
            w = windows(series[pl["id"]], rows, dur, allowed)
            if w: out.append((w[0][0], w[0][1], pl, w))
        return sorted(out, key=lambda x: -x[0])
    ranked, outside = rank(set(slots)), False
    if not ranked: ranked, outside = rank({r["t"] for r in rows[:48]}), True
    idx = {r["t"]: i for i, r in enumerate(rows)}
    lo, hi = idx[slots[0]], idx[slots[-1]] + 1
    reasons = {}
    for pl in places:
        for s in series[pl["id"]][lo:hi]:
            for x in s["avoid"]: reasons[x] = reasons.get(x, 0) + 1
    L = dict(act=A["label"], prof=", ".join(profiles) or "no health profile", label=label, rec=None, alts=[], backup=None, by_day=[],
             avoid=[], carry=[], watch=[], assump=R["assumptions"], outside=outside, reasons=sorted(reasons, key=lambda k: -reasons[k])[:3])
    feats = [pt(olat, olon, kind="origin", name=f"Search centre: {where}")]
    if ranked:
        sc, s0, pick, wins = ranked[0]
        seg_rows, ser = rows[s0:s0+dur], series[pick["id"]]
        seg = ser[s0:s0+dur]; end = seg_rows[-1]["t"] + timedelta(hours=1)
        aq = [r["aqi"] for r in seg_rows if r["aqi"] is not None]
        j = max(range(len(seg)), key=lambda i: seg[i]["expo"]); e, top = seg[j]["expo"], seg[j]["top"]
        if not pick["ctx_ok"]: etxt = "pollution exposure was not assessed because road and industry data were unavailable"
        elif e >= .35 and top: etxt = f"at {h12(seg_rows[j]['t'].hour)} the wind from the {compass(seg_rows[j]['wdir'])} blows from {top['name']} ({top['dist']:.0f} m away) toward this spot"
        else: etxt = "no major road or industrial area is upwind of this spot during the window"
        rec = dict(place=pick["name"], kind=pick["kind"], lat=pick["lat"], lon=pick["lon"], osm_id=pick["id"], start=seg_rows[0]["t"].isoformat(), end=end.isoformat(),
                   start_label=lab(seg_rows[0]["t"]), end_label=h12(end.hour), score=round(sc), access=pick.get("access"),
                   travel_min=None if pick.get("origin_only") else round(pick["travel"]*rush(seg_rows[0]["t"])), travel_km=round(pick["travel_km"], 1),
                   travel_estimated=pick["travel_est"], nearest=pick["nearest"], water_m=pick["water_m"], outside_requested_window=outside,
                   conditions=dict(feels_min=round(min(r["feels"] for r in seg_rows)), feels_max=round(max(r["feels"] for r in seg_rows)),
                                   rain_max=round(max(r["pop"] for r in seg_rows)), wind_max=round(max(r["wind"] for r in seg_rows)),
                                   wind_dir=compass(seg_rows[0]["wdir"]), aqi_min=round(min(aq)) if aq else None, aqi_max=round(max(aq)) if aq else None,
                                   uv_max=round(max(r["uv"] for r in seg_rows))), exposure=dict(level=round(e, 2), text=etxt))
        L["rec"] = rec; R["recommendation"] = rec
        for s2, st2, pl2, _ in ranked[1:3]:
            sr = rows[st2:st2+dur]; en = sr[-1]["t"] + timedelta(hours=1)
            a = dict(place=pl2["name"], kind=pl2["kind"], lat=pl2["lat"], lon=pl2["lon"], start_label=lab(sr[0]["t"]), end_label=h12(en.hour), score=round(s2),
                     travel_min=None if pl2.get("origin_only") else round(pl2["travel"]*rush(sr[0]["t"])))
            L["alts"].append(a)
        R["alternatives"] = L["alts"]
        for s2, st2 in wins:
            if abs(st2 - s0) >= dur:
                sr = rows[st2:st2+dur]; en = sr[-1]["t"] + timedelta(hours=1)
                L["backup"] = dict(start_label=lab(sr[0]["t"]), end_label=h12(en.hour), score=round(s2)); break
        R["backup_time"] = L["backup"]
        if not outside and len({s.date() for s in slots}) > 1:
            for d in sorted({s.date() for s in slots}):
                best = None
                for sc2, _, pl2, ws in ranked:
                    for s2, st2 in ws:
                        if rows[st2]["t"].date() == d:
                            if best is None or s2 > best[0]: best = (s2, st2, pl2)
                            break
                if best: L["by_day"].append(dict(date=fmt_date(d), place=best[2]["name"], start_label=h12(rows[best[1]]["t"].hour), score=round(best[0])))
        R["by_day"] = L["by_day"]
        pp = sum(r["precip"] for r in allrows if seg_rows[0]["t"] - timedelta(hours=6) <= r["t"] < seg_rows[0]["t"])
        L["carry"], L["watch"] = advice(act, profiles, seg_rows, pp, seg_rows[0]["t"])
        for n in {x for s in seg for x in s["watch"]}: L["watch"].insert(0, n)
        sl = slice(lo, hi)
        L["avoid"] = [dict(b, scope="At this venue,") for b in blocks(rows[sl], [s["avoid"] for s in ser[sl]])[:3]]
        allav = [[x for x in series[pl["id"]][i]["avoid"]] if all(series[q2["id"]][i]["avoid"] for q2 in places) else [] for i in range(lo, hi) for pl in places[:1]]
        area_b = blocks(rows[sl], allav)[:2]
        L["avoid"] = [b for b in L["avoid"] if not any(b["from"] == a["from"] and b["to"] == a["to"] for a in area_b)]
        L["avoid"] += [dict(b, scope="Everywhere nearby,") for b in area_b]
        R["avoid_windows"] = L["avoid"]; R["carry"], R["watch"] = L["carry"], L["watch"]
        R["evidence"] = [dict(time=lab(r["t"]), feels=round(r["feels"]), rain_pct=round(r["pop"]), wind_kmh=round(r["wind"]), wind_from=compass(r["wdir"]),
                              us_aqi=None if r["aqi"] is None else round(r["aqi"]), pm25=r["pm25"], uv=round(r["uv"]), exposure=round(s["expo"], 2))
                         for r, s in zip(seg_rows, seg)]
        for _, _, pl2, _ in ranked[:6]:
            feats.append(pt(pl2["lat"], pl2["lon"], kind="pick" if pl2 is pick else "alt", name=pl2["name"], score=round(next(x[0] for x in ranked if x[2] is pl2))))
        for pl2 in places:
            if pl2 not in [x[2] for x in ranked[:6]]: feats.append(pt(pl2["lat"], pl2["lon"], kind="other", name=pl2["name"]))
        hs = [n for n in pick["near"] if n["type"] == "highway"]
        for n in hs[::max(1, len(hs)//40)]: feats.append(pt(n["lat"], n["lon"], kind="highway", name=n["name"]))
        for n in [n for n in pick["near"] if n["type"] == "industry"][:15]: feats.append(pt(n["lat"], n["lon"], kind="industry", name=n["name"]))
        if ctx:
            for a, b in [w for w in ctx["water"] if haversine(pick["lat"], pick["lon"], *w) <= 1000][:15]: feats.append(pt(a, b, kind="water", name="Water body"))
            for a, b in [w for w in ctx["green"] if haversine(pick["lat"], pick["lon"], *w) <= 800][:15]: feats.append(pt(a, b, kind="green", name="Green cover"))
        wr = seg_rows[j]; la2, lo2 = dest(pick["lat"], pick["lon"], wr["wdir"], 700)
        feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[pick["lon"], pick["lat"]], [lo2, la2]]},
                      "properties": dict(kind="wind", name=f"Wind comes from the {compass(wr['wdir'])} at {h12(wr['t'].hour)}, {wr['wind']:.0f} km/h")})
        if not pick.get("origin_only"):
            rg = pick.get("geom")
            if rg: feats.append({"type": "Feature", "geometry": rg, "properties": dict(kind="route", name="Driving route to the pick")})
    else:
        feats += [pt(pl["lat"], pl["lon"], kind="other", name=pl["name"]) for pl in places]
    R["map"]["features"] = feats
    lap("score"); facts, template = build_text(L)
    text, method, bad = narrate(facts, template, use_slm)
    lap("narrate"); R["narration"] = dict(method=method, ungrounded_items_caught=bad)
    src = ", ".join(s["name"] for s in tr.items)
    R["evidence_text"] = facts
    return done("ok", f"{text}\n\n_Data used: {src}._")
