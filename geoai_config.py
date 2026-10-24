"""Per-activity rules and personal-profile modifiers.

All cut-offs are general rules (never per-question answers). Basis is documented in README.
feels = (cold limit, ideal upper bound, hot limit) in deg C (apparent temperature)
rain  = max rain probability %, wind = max wind km/h, aqi = max US AQI, uv = max UV index
day   = "hard" (avoid after dark unless lit), "soft" (dark is penalised), "none"
dur   = typical session length in hours, rad = default search radius km, ex = exertion 1..3
"""
ACT = {
 "running": dict(label="Running / jogging", ex=3, feels=(5,24,32), rain=40, wind=30, aqi=100, uv=9, day="soft", dur=1, rad=5,
   w=dict(temp=.20,rain=.10,wind=.05,aqi=.25,expo=.15,green=.10,light=.05,travel=.10),
   osm=[("leisure","park"),("leisure","track"),("landuse","recreation_ground")], fac=False,
   tip="Warm up, and carry your phone."),
 "cycling": dict(label="Cycling", ex=2, feels=(8,26,34), rain=30, wind=25, aqi=120, uv=9, day="soft", dur=1, rad=8,
   w=dict(temp=.15,rain=.15,wind=.20,aqi=.15,expo=.15,green=.05,light=.05,travel=.10),
   osm=[("leisure","park"),("leisure","track")], fac=False, tip="Wear a helmet and use lights."),
 "golf": dict(label="Golf", ex=2, feels=(10,28,36), rain=30, wind=28, aqi=150, uv=10, day="hard", dur=4, rad=25,
   w=dict(temp=.18,rain=.20,wind=.25,aqi=.08,expo=.04,green=.05,light=.05,travel=.15),
   osm=[("leisure","golf_course")], fac=True, tip="Call the club to confirm tee times and access."),
 "cricket": dict(label="Cricket", ex=2.5, feels=(8,27,33), rain=35, wind=35, aqi=100, uv=9, day="hard", dur=3, rad=8,
   w=dict(temp=.20,rain=.20,wind=.08,aqi=.17,expo=.10,green=.05,light=.05,travel=.15),
   osm=[("sport","cricket")], fac=True, tip="Check the pitch is bookable and the outfield is dry."),
 "football": dict(label="Football / five-a-side", ex=3, feels=(6,25,32), rain=40, wind=40, aqi=100, uv=9, day="soft", dur=2, rad=8,
   w=dict(temp=.20,rain=.12,wind=.04,aqi=.25,expo=.10,green=.04,light=.05,travel=.20),
   osm=[("sport","soccer"),("sport","football")], fac=True, tip="Confirm the ground or turf booking."),
 "tennis": dict(label="Tennis", ex=2, feels=(8,27,34), rain=20, wind=20, aqi=120, uv=9, day="hard", dur=2, rad=8,
   w=dict(temp=.15,rain=.20,wind=.25,aqi=.10,expo=.05,green=.02,light=.03,travel=.20),
   osm=[("sport","tennis")], fac=True, tip="Confirm the court booking."),
 "hiking": dict(label="Hiking / nature walk", ex=2.5, feels=(5,25,32), rain=30, wind=40, aqi=120, uv=9, day="hard", dur=3, rad=30,
   w=dict(temp=.20,rain=.18,wind=.05,aqi=.12,expo=.05,green=.15,light=.10,travel=.15),
   osm=[("natural","peak"),("tourism","viewpoint"),("leisure","nature_reserve"),("leisure","park")], fac=False,
   tip="Start early, carry an offline map and tell someone your route."),
 "walk": dict(label="Walk in a park", ex=1.5, feels=(5,26,33), rain=40, wind=40, aqi=100, uv=9, day="soft", dur=1, rad=4,
   w=dict(temp=.20,rain=.10,wind=.03,aqi=.27,expo=.15,green=.15,light=.05,travel=.05),
   osm=[("leisure","park"),("leisure","garden"),("leisure","nature_reserve")], fac=False, tip="Take breaks and walk at an easy pace."),
 "picnic": dict(label="Picnic / park outing", ex=1, feels=(10,28,34), rain=20, wind=30, aqi=150, uv=9, day="hard", dur=2, rad=8,
   w=dict(temp=.20,rain=.25,wind=.08,aqi=.10,expo=.07,green=.15,light=.05,travel=.10),
   osm=[("leisure","park"),("leisure","garden")], fac=False, tip="Pick a shaded spot and carry a ground sheet."),
 "event": dict(label="Outdoor event / gathering", ex=1, feels=(10,29,35), rain=15, wind=35, aqi=200, uv=10, day="none", dur=4, rad=10,
   w=dict(temp=.20,rain=.35,wind=.10,aqi=.08,expo=.05,green=.05,light=.02,travel=.15),
   osm=[("amenity","events_venue"),("leisure","park"),("leisure","garden")], fac=False,
   tip="Keep a covered or indoor backup, and book early."),
 "photography": dict(label="Outdoor photography", ex=1, feels=(5,30,38), rain=40, wind=45, aqi=200, uv=11, day="hard", dur=1, rad=10, golden=True,
   w=dict(temp=.08,rain=.20,wind=.05,aqi=.07,expo=.03,green=.10,light=.35,travel=.12),
   osm=[("tourism","viewpoint"),("leisure","park"),("natural","beach"),("natural","peak")], fac=False,
   tip="Arrive early to scout your spot."),
}
FALLBACK_OSM = [("leisure","park"),("landuse","recreation_ground"),("leisure","pitch")]

# Profiles tighten the limits: aqi multiplier on max AQI, heat = degrees C removed from heat limits,
# expo = exposure-weight multiplier, travel = multiplier on max acceptable travel time.
PROFILE = {
 "asthma":    dict(aqi=.70, heat=0, expo=1.6, travel=1.0),
 "senior":    dict(aqi=.80, heat=4, expo=1.3, travel=.75),
 "child":     dict(aqi=.80, heat=4, expo=1.3, travel=.75),
 "pregnancy": dict(aqi=.80, heat=4, expo=1.3, travel=.75),
 "cardiac":   dict(aqi=.80, heat=4, expo=1.3, travel=.75),
}
