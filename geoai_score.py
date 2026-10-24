"""Scoring of place x hour. Hard limits mark a slot as 'avoid'; soft components rank what is left."""
import math
from geoai_config import ACT, PROFILE
from geoai_geo import exposure, compass

def limits(act, profiles):
    a = ACT[act]; lo, ideal, hi = a["feels"]
    aq, heat, ex, tr = a["aqi"], 0, 1.0, 1.0
    for p in profiles:
        m = PROFILE[p]; aq = min(aq, a["aqi"]*m["aqi"]); heat = max(heat, m["heat"]); ex = max(ex, m["expo"]); tr = min(tr, m["travel"])
    return dict(feels_lo=lo, feels_ideal=ideal-heat, feels_hi=hi-heat, rain=a["rain"], wind=a["wind"], aqi=round(aq),
                uv=a["uv"] - (2 if profiles else 0), expo_mult=ex, max_travel=60*tr)

def _hi(v, ideal, limit):
    return 1.0 if v <= ideal else max(0.0, 1 - (v-ideal)/max(1e-6, limit-ideal))

def score_slot(pl, r, travel_min, act, lim, sun):
    A, avoid, watch = ACT[act], [], []
    f, aqi, dark = r["feels"], r["aqi"], not r["is_day"]
    if r["code"] in (95, 96, 99): avoid.append("thunderstorm forecast")
    if r["pop"] > lim["rain"]: avoid.append(f"rain chance {r['pop']:.0f}% is above the {lim['rain']}% limit")
    if r["precip"] >= 1.0: avoid.append(f"{r['precip']:.1f} mm of rain expected")
    if f > lim["feels_hi"]: avoid.append(f"feels-like {f:.0f}°C is above the {lim['feels_hi']:.0f}°C limit")
    if f < lim["feels_lo"] - 5: avoid.append(f"feels-like {f:.0f}°C is too cold")
    if r["wind"] > lim["wind"]: avoid.append(f"wind {r['wind']:.0f} km/h is above the {lim['wind']} km/h limit")
    if aqi is not None and aqi > lim["aqi"]: avoid.append(f"US AQI {aqi:.0f} is above the {lim['aqi']} limit")
    if A["day"] == "hard" and dark and not pl.get("lit"): avoid.append("after dark")
    temp = _hi(f, lim["feels_ideal"], lim["feels_hi"])
    if f < lim["feels_lo"] + 6: temp = min(temp, max(0.0, (f - lim["feels_lo"] + 5)/11))
    uvc = _hi(r["uv"], 5, lim["uv"] + 3) if r["is_day"] else 1.0
    c = dict(temp=.8*temp + .2*uvc, rain=1 - .8*min(1, r["pop"]/lim["rain"]), wind=_hi(r["wind"], lim["wind"]*.4, lim["wind"]),
             aqi=1.0 if aqi is None else _hi(aqi, min(50, lim["aqi"]*.5), lim["aqi"]),
             green=pl["green_idx"], travel=1 - min(1, travel_min/lim["max_travel"]))
    e, top = exposure(pl["near"], r["wind"], r["wdir"]) if pl["ctx_ok"] else (0.0, None)
    c["expo"] = 1 - e
    if A["day"] == "none": c["light"] = 1.0
    elif A.get("golden"):
        if dark: c["light"] = 0.0
        else:
            mid = r["t"].replace(minute=30); ev = sun.get(r["t"].date().isoformat(), [])
            m = min([abs((mid - s).total_seconds())/60 for s in ev] or [999])
            c["light"] = 1.0 if m <= 60 else .6 if m <= 120 else .4
    else: c["light"] = 1.0 if not dark else (.8 if pl.get("lit") else 0.0)
    w = dict(A["w"]); w["light"] *= 4 if A["day"] == "soft" else 1; w["expo"] *= lim["expo_mult"]*(1 + .25*(A["ex"]-1))
    if not pl["ctx_ok"]: w["expo"] = w["green"] = 0
    if pl.get("origin_only"): w["travel"] = 0
    if aqi is None: w["aqi"] = 0
    score = 100*sum(w[k]*c[k] for k in w)/sum(w.values())
    if e >= .35 and top:
        watch.append(f"wind from the {compass(r['wdir'])} carries emissions from {top['name']} ({top['dist']:.0f} m away) toward this spot")
    if dark and A["day"] == "soft" and not pl.get("lit"): watch.append("it will be dark here and the venue is not tagged as lit")
    if r["pop"] >= 25: watch.append(f"{r['pop']:.0f}% chance of rain")
    if r["is_day"] and r["uv"] >= 7: watch.append(f"UV index {r['uv']:.0f}")
    return dict(score=0.0 if avoid else round(score, 1), raw=round(score, 1), avoid=avoid, watch=watch, expo=e, top=top)

def windows(series, rows, dur, allowed):
    """Best consecutive windows of `dur` hours with no hard-avoid hour, starting inside `allowed`."""
    out = []
    for s in range(len(series) - dur + 1):
        if rows[s]["t"] not in allowed: continue
        seg = series[s:s+dur]
        if any(x["avoid"] for x in seg): continue
        out.append((sum(x["score"] for x in seg)/dur, s))
    return sorted(out, reverse=True)
