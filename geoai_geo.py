import math
def haversine(la1, lo1, la2, lo2):
    p1, p2 = math.radians(la1), math.radians(la2)
    a = math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lo2-lo1)/2)**2
    return 2*6371000*math.asin(math.sqrt(a))

def bearing(la1, lo1, la2, lo2):
    """Initial bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2, dl = math.radians(la1), math.radians(la2), math.radians(lo2-lo1)
    y = math.sin(dl)*math.cos(p2)
    x = math.cos(p1)*math.sin(p2) - math.sin(p1)*math.cos(p2)*math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def angdiff(a, b):
    d = abs(a-b) % 360
    return min(d, 360-d)

def dest(lat, lon, brg, dist_m):
    d = dist_m/6371000; b = math.radians(brg); p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1)*math.cos(d) + math.cos(p1)*math.sin(d)*math.cos(b))
    l2 = l1 + math.atan2(math.sin(b)*math.sin(d)*math.cos(p1), math.cos(d)-math.sin(p1)*math.sin(p2))
    return math.degrees(p2), math.degrees(l2)

_C = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()
def compass(deg):
    return _C[int((deg % 360)/22.5 + .5) % 16]

def exposure(near, wind_kmh, wind_from_deg):
    """How exposed a place is to pollution sources at one hour.

    near: sources within their reach, each with gid, type, name, dist (m), brg (bearing source->place), w, R (reach m).
    Wind direction from Open-Meteo is the direction the wind blows FROM, so the plume travels toward
    wind_from+180. A place is downwind when the source->place bearing is within 60 deg of that heading.
    Calm air (<4 km/h) lets pollution linger: weak, direction-free exposure. Per source group (one road or
    one industrial area) only the strongest contribution counts, so a long road is not counted per vertex.
    Returns (exposure 0..1, strongest contributing source or None).
    """
    plume = (wind_from_deg + 180) % 360
    best = {}
    for s in near:
        prox = max(0.0, 1 - s["dist"]/s["R"])
        if prox <= 0: continue
        if wind_kmh < 4:
            f = s["w"]*prox*0.35
        else:
            d = angdiff(s["brg"], plume)
            if d > 60: continue
            f = s["w"]*prox*math.cos(math.radians(d*1.5))*min(1.0, 0.5 + wind_kmh/30)
        if f > best.get(s["gid"], (0, None))[0]:
            best[s["gid"]] = (f, s)
    if not best: return 0.0, None
    tot = sum(v[0] for v in best.values())
    top = max(best.values(), key=lambda v: v[0])[1]
    return 1 - math.exp(-1.2*tot), top
