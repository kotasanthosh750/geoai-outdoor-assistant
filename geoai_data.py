"""Live data wrappers. Everything is fetched at query time and cached with TTLs."""
import os, time, hashlib, threading, requests
import geoai_cache as cache
from geoai_geo import haversine

CONTACT = os.environ.get("CONTACT_EMAIL", "324106715036@andhrauniversity.edu.in")
S = requests.Session()
S.headers.update({"User-Agent": f"GeoAI-Outdoor-Assistant/1.0 (hackathon project; {CONTACT})"})

SRC = {
 "nominatim": ("OpenStreetMap Nominatim", "https://nominatim.openstreetmap.org"),
 "overpass": ("OpenStreetMap Overpass API", "https://overpass-api.de"),
 "openmeteo": ("Open-Meteo forecast API", "https://open-meteo.com"),
 "openmeteo_aq": ("Open-Meteo air-quality API (CAMS model)", "https://open-meteo.com/en/docs/air-quality-api"),
 "osrm": ("OSRM public demo server", "https://router.project-osrm.org"),
}
MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]

class Trace:
    def __init__(self): self.items, self.warnings = [], []
    def add(self, key, purpose, cached):
        n, u = SRC[key]
        if not any(i["name"] == n and i["purpose"] == purpose for i in self.items):
            self.items.append(dict(name=n, url=u, purpose=purpose, cached=cached))
    def warn(self, m):
        if m not in self.warnings: self.warnings.append(m)

def _get(url, params, timeout=15, tries=2):
    last = None
    for _ in range(tries):
        try:
            r = S.get(url, params=params, timeout=timeout); r.raise_for_status(); return r.json()
        except Exception as e:
            last = e; time.sleep(0.5)
    raise last

_nom_lock, _last_nom = threading.Lock(), [0.0]
def geocode(q, trace):
    key = "geo:" + q.lower().strip()
    hit = cache.get(key)
    if hit is not None:
        trace.add("nominatim", "Resolve place name to coordinates", True); return hit or None
    with _nom_lock:                                   # Nominatim policy: max 1 request/second
        wait = 1.1 - (time.time() - _last_nom[0])
        if wait > 0: time.sleep(wait)
        try:
            d = _get("https://nominatim.openstreetmap.org/search", {"q": q, "format": "jsonv2", "limit": 1}, tries=1)
        except Exception:
            trace.warn("Geocoding service unavailable"); return None
        finally:
            _last_nom[0] = time.time()
    res = {"lat": float(d[0]["lat"]), "lon": float(d[0]["lon"]), "name": d[0]["display_name"]} if d else {}
    cache.put(key, res, 30*86400 if res else 86400)
    trace.add("nominatim", "Resolve place name to coordinates", False)
    return res or None

def overpass(q, trace, ttl, purpose):
    key = "op:" + hashlib.sha1(q.encode()).hexdigest()
    hit = cache.get(key)
    if hit:
        trace.add("overpass", purpose, True); return hit
    last = None
    for url in MIRRORS:
        try:
            r = S.post(url, data={"data": q}, timeout=(5, 28)); r.raise_for_status(); d = r.json()
            cache.put(key, d, ttl); trace.add("overpass", purpose, False); return d
        except Exception as e:
            last = e
    trace.warn(f"OpenStreetMap map data unavailable ({type(last).__name__})")
    return None

def _label(tags, pairs):
    for k, v in pairs:
        if tags.get(k) == v: return f"{k}={v}"
    return pairs[0][0] + "=" + pairs[0][1]

def candidates(lat, lon, radius_m, pairs, trace, n=8):
    body = "".join(f'nwr["{k}"="{v}"](around:{radius_m},{lat},{lon});' for k, v in pairs)
    d = overpass(f"[out:json][timeout:25];({body});out center 250;", trace, 7*86400,
                 "Candidate venues, parks and grounds near the search area")
    if d is None: return None
    seen, out = set(), []
    for e in d.get("elements", []):
        t = e.get("tags", {})
        la = e.get("lat") or e.get("center", {}).get("lat"); lo = e.get("lon") or e.get("center", {}).get("lon")
        if la is None or lo is None: continue
        name = t.get("name") or t.get("name:en")
        key = (name or "", round(la, 3), round(lo, 3))
        if key in seen: continue
        seen.add(key)
        out.append(dict(id=f'{e["type"]}/{e["id"]}', name=name, kind=_label(t, pairs), lat=la, lon=lo,
                        lit=t.get("lit") == "yes", access=t.get("access"), dist=haversine(lat, lon, la, lo)))
    named = [p for p in out if p["name"]]
    pool = named if len(named) >= 3 else out
    for p in pool:
        if not p["name"]: p["name"] = f'Unnamed {p["kind"].split("=")[1].replace("_"," ")} (OSM {p["id"]})'
    pool.sort(key=lambda p: p["dist"])
    if len(pool) > n:                                   # spread picks across the radius
        step = len(pool)/n; pool = [pool[int(i*step)] for i in range(n)]
    return pool

def _areas(places, r):
    """One bounding box when candidates are close together (fast); otherwise one circle per place."""
    la, lo = [p["lat"] for p in places], [p["lon"] for p in places]
    if max(la) - min(la) < 0.12 and max(lo) - min(lo) < 0.12:
        pad = 0.035
        return [f"({min(la)-pad:.4f},{min(lo)-pad:.4f},{max(la)+pad:.4f},{max(lo)+pad:.4f})"]
    return [f"(around:{r},{p['lat']},{p['lon']})" for p in places]

def context(places, trace):
    """Roads, industry, water and green cover around the candidates (one Overpass call)."""
    h = [f'way["highway"~"^(motorway|trunk|primary)$"]{a};' for a in _areas(places, 2500)]
    i = [f'nwr["{k}"="{v}"]{a};' for a in _areas(places, 3000) for k, v in (("landuse", "industrial"), ("man_made", "works"), ("power", "plant"))]
    w = [x for a in _areas(places, 1000) for x in (f'nwr["natural"="water"]{a};', f'way["waterway"~"^(river|canal)$"]{a};')]
    g = [x for a in _areas(places, 800) for x in (f'nwr["leisure"~"^(park|garden|nature_reserve)$"]{a};', f'nwr["landuse"="forest"]{a};', f'nwr["natural"="wood"]{a};')]
    q = (f"[out:json][timeout:30];({''.join(h)})->.h;({''.join(i)})->.i;({''.join(w)})->.w;({''.join(g)})->.g;"
         ".h out geom qt 600;.i out center qt 200;.w out center qt 200;.g out center qt 400;")
    d = overpass(q, trace, 7*86400, "Roads, industrial areas, water bodies and green cover around candidates")
    if d is None: return None
    src, water, green, seen = [], [], [], set()
    for e in d.get("elements", []):
        k = (e["type"], e["id"])
        if k in seen: continue
        seen.add(k); t = e.get("tags", {})
        c = (e.get("lat") or e.get("center", {}).get("lat"), e.get("lon") or e.get("center", {}).get("lon"))
        if t.get("highway") and e.get("geometry"):
            major = t["highway"] in ("motorway", "trunk")
            nm = t.get("name") or t.get("ref") or t["highway"]
            lp = None
            for pt in e["geometry"]:                    # keep a vertex roughly every 200 m
                if lp is None or haversine(lp[0], lp[1], pt["lat"], pt["lon"]) >= 200:
                    src.append(dict(gid=k, type="highway", name=nm, lat=pt["lat"], lon=pt["lon"],
                                    w=1.0 if major else .5, R=1500 if major else 800, cls=t["highway"]))
                    lp = (pt["lat"], pt["lon"])
        elif c[0] is None: continue
        elif t.get("landuse") == "industrial" or t.get("man_made") == "works" or t.get("power") == "plant":
            src.append(dict(gid=k, type="industry", name=t.get("name") or "industrial area", lat=c[0], lon=c[1], w=1.3, R=3000))
        elif t.get("natural") == "water" or t.get("waterway"): water.append((c[0], c[1]))
        else: green.append((c[0], c[1]))
    return dict(sources=src[:3000], water=water, green=green)

HOURLY = ("temperature_2m,apparent_temperature,relative_humidity_2m,precipitation_probability,precipitation,"
          "weather_code,wind_speed_10m,wind_direction_10m,uv_index,is_day")
def forecast(lat, lon, trace):
    key = f"wx:{lat:.2f}:{lon:.2f}"
    hit = cache.get(key)
    if hit:
        trace.add("openmeteo", "Hourly weather, wind direction, UV, sunrise and sunset", True)
        if hit["aq_ok"]: trace.add("openmeteo_aq", "Hourly US AQI and PM2.5 forecast", True)
        else: trace.warn("Air-quality forecast unavailable; AQI was not considered")
        return hit
    try:
        f = _get("https://api.open-meteo.com/v1/forecast", {"latitude": lat, "longitude": lon, "hourly": HOURLY,
                 "daily": "sunrise,sunset", "timezone": "auto", "forecast_days": 7, "wind_speed_unit": "kmh"})
    except Exception:
        trace.warn("Weather service unavailable"); return None
    aq = {}
    try:
        a = _get("https://air-quality-api.open-meteo.com/v1/air-quality", {"latitude": lat, "longitude": lon,
                 "hourly": "us_aqi,pm2_5", "timezone": "auto", "forecast_days": 5})
        aq = dict(zip(a["hourly"]["time"], zip(a["hourly"]["us_aqi"], a["hourly"]["pm2_5"])))
    except Exception:
        trace.warn("Air-quality forecast unavailable; AQI was not considered")
    H, rows = f["hourly"], []
    for i, ts in enumerate(H["time"]):
        a_ = aq.get(ts, (None, None))
        rows.append(dict(t=ts, temp=H["temperature_2m"][i], feels=H["apparent_temperature"][i], pop=H["precipitation_probability"][i] or 0,
                         precip=H["precipitation"][i] or 0, code=H["weather_code"][i], wind=H["wind_speed_10m"][i] or 0,
                         wdir=H["wind_direction_10m"][i] or 0, uv=H["uv_index"][i] or 0, is_day=bool(H["is_day"][i]),
                         aqi=a_[0], pm25=a_[1]))
    out = dict(rows=rows, sun=dict(zip(f["daily"]["time"], zip(f["daily"]["sunrise"], f["daily"]["sunset"]))),
               utc_offset=f.get("utc_offset_seconds", 0), aq_ok=bool(aq))
    cache.put(key, out, 1800)
    trace.add("openmeteo", "Hourly weather, wind direction, UV, sunrise and sunset", False)
    if aq: trace.add("openmeteo_aq", "Hourly US AQI and PM2.5 forecast", False)
    return out

def route(a, b, trace, geom=False):
    key = f"osrm:{a[0]:.4f},{a[1]:.4f}:{b[0]:.4f},{b[1]:.4f}:{int(geom)}"
    hit = cache.get(key)
    if hit:
        trace.add("osrm", "Driving time and route from the search centre to each venue", True); return hit
    try:
        d = _get(f"https://router.project-osrm.org/route/v1/driving/{a[1]},{a[0]};{b[1]},{b[0]}",
                 {"overview": "simplified" if geom else "false", "geometries": "geojson"}, timeout=10, tries=1)
        rt = d["routes"][0]
        res = dict(min=rt["duration"]/60, km=rt["distance"]/1000, est=False, geometry=rt.get("geometry"))
    except Exception:
        km = haversine(a[0], a[1], b[0], b[1])/1000*1.35
        trace.warn("Routing service unavailable for some places; those travel times are straight-line estimates")
        return dict(min=km/25*60, km=km, est=True, geometry=None)
    cache.put(key, res, 7*86400)
    trace.add("osrm", "Driving time and route from the search centre to each venue", False)
    return res
