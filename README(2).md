---
title: GeoAI Outdoor Advisor
emoji: 🌳
colorFrom: green
colorTo: blue
sdk: gradio
app_file: app.py
pinned: false
license: apache-2.0
---

# GeoAI Outdoor Advisor

Ask a free-form question such as "where can I run tomorrow evening near Koregaon Park?". The assistant picks the best nearby **place and time**, says what to carry, what to watch for and when to avoid going, and shows it on a map. Every number comes from live data fetched for that question.

- **Space page:** `https://huggingface.co/spaces/Bhar1324/geoai-outdoor-assistant`
- **Live app (UI with text and map):** `https://bhar1324-geoai-outdoor-assistant.hf.space/`
- **API endpoint:** `POST https://bhar1324-geoai-outdoor-assistant.hf.space/gradio_api/call/ask_json` (see API below)
- **Model on Hugging Face:** `https://huggingface.co/Bhar1324/geoai-outdoor-advisor-qwen2.5-1.5b` (see `MODEL_CARD.md`)

## How it works

The small language model does language work only. Code does the data fetching, geometry, scoring and checking.

1. **Understand** (SLM + rules): the SLM reads the question into JSON (activity, place, radius, time, health profile). Deterministic rules validate it and fill gaps. A place name from the SLM is accepted only if it literally appears in the question.
2. **Gate** (code): out-of-scope questions are declined, and a missing place or activity gets a clarifying question. Vague times ("evening", "this weekend") are resolved with the assumption stated in the answer.
3. **Fetch live data**: geocode the place, find candidate venues, fetch roads, industry, water and green cover around each, fetch hourly weather and air quality, and get driving times.
4. **Geospatial exposure** (code): for each place and hour, the bearing from each major road or industrial area to the place is compared with that hour's wind direction. A place counts as downwind when the source lies within 60° of the wind's origin, weighted by distance and wind speed. This is why a ground near an expressway can be poor at 8 AM and fine by evening.
5. **Score place × hour** (code): hard limits mark a slot "avoid"; the remaining slots are ranked by weighted soft scores (temperature and UV, rain, wind, air quality, exposure, green cover, daylight, travel time). Activity rules are in `app/config.py`; profiles (asthma, senior, child, pregnancy, cardiac) tighten the limits.
6. **Write the answer** (SLM): the model phrases the advice from a facts block only. A **grounding check** then rejects any number or capitalised name that is not in the facts; one retry, then a fixed template is used. The response says which one produced the text.

## Files
All code sits in the repository root (no sub-folders): `app.py` (UI and API), `geoai_pipeline.py`, `geoai_parse.py`, `geoai_data.py`, `geoai_geo.py`, `geoai_score.py`, `geoai_config.py`, `geoai_narrate.py`, `geoai_slm.py`, `geoai_cache.py`, `requirements.txt`. Upload all of them.

## Activities
Running/jogging, cycling (leisure or commute), golf, cricket, football/five-a-side, tennis, hiking/nature walk, park walk, picnic/park outing, outdoor events, photography.

## API

Gradio exposes the backend over HTTP. The JSON endpoint is `ask_json`; the UI button uses `ask`; `health` reports model status.

```python
from gradio_client import Client
c = Client("Bhar1324/geoai-outdoor-assistant")
r = c.predict("Is Saturday or Sunday better for a hike near Lonavala?", True, None, None, api_name="/ask_json")
```
Arguments: `query`, `use_slm` (false skips model wording: faster, template text), `lat`, `lon` (optional; used only when the question names no place).

Plain HTTP (two steps, standard Gradio API):
```bash
curl -s -X POST https://bhar1324-geoai-outdoor-assistant.hf.space/gradio_api/call/ask_json \
  -H "Content-Type: application/json" -d '{"data": ["Where can I jog tomorrow evening near Powai?", true, null, null]}'
# -> {"event_id": "..."}   then:
curl -N https://bhar1324-geoai-outdoor-assistant.hf.space/gradio_api/call/ask_json/<event_id>
```

Response fields: `status` (`ok`, `needs_info`, `out_of_scope`, `error`), `answer` (text), `question` (clarifying question when `needs_info`), `parsed`, `assumptions`, `recommendation` (place, window, score, travel, conditions, exposure), `alternatives`, `backup_time`, `by_day`, `avoid_windows`, `carry`, `watch`, `evidence` (hourly values behind the pick), `map` (GeoJSON FeatureCollection), `sources_used`, `warnings` (data gaps), `narration`, `timing`.

## Data sources (all free, fetched live and cached)
| Source | Used for | Cache |
|---|---|---|
| OpenStreetMap Nominatim | place name to coordinates (1 req/s, identifying User-Agent) | 30 days |
| OpenStreetMap Overpass API (+ kumi.systems mirror) | venues, roads, industrial areas, water, green cover | 7 days |
| Open-Meteo forecast API | hourly temperature, feels-like, rain, wind speed and direction, UV, sunrise/sunset | 30 min |
| Open-Meteo air-quality API (CAMS model) | hourly US AQI and PM2.5 | 30 min |
| OSRM public demo server | driving time and route | 7 days |
| OpenStreetMap tiles (Leaflet) | map background | browser |

Not used: CPCB, OpenAQ, WAQI, IMD, elevation APIs. Map data © OpenStreetMap contributors (ODbL).

## Run it
```bash
pip install -r requirements.txt
# optional: export CONTACT_EMAIL=your@email   (sent in the User-Agent as OSM policies require; defaults to the project owner)
python app.py                             # open http://localhost:7860
```
On Hugging Face: create a **Gradio** Space, upload all files to the repo root, and optionally set `CONTACT_EMAIL` as a Space variable. The language model loads in the background; `health` shows `model_ready`, and until then answers use rules and a fixed template. To use your own model repo, set a `MODEL_ID` Space variable. On **ZeroGPU** hardware the model call runs under `@spaces.GPU`; on plain CPU hardware a 1.5B model takes roughly a minute per model-worded answer, so use `use_slm=false` there if you need speed.

## Basis of the thresholds
Limits in `app/config.py` are heuristics, not medical advice: air quality uses US AQI categories (≤50 good, 51–100 moderate, 101–150 unhealthy for sensitive groups) with profile multipliers; heat limits use apparent temperature with comfort and caution bands in the range of common heat-index guidance; rain, wind and daylight limits reflect what each sport tolerates. Profiles reduce the AQI limit (asthma ×0.7, others ×0.8), lower heat limits by 4 °C and shorten acceptable travel. They have not been clinically validated.

## Known limitations
- Weather and air quality are taken at the search centre, not per venue. Air quality is a regional model value; place-level differences come only from the wind-and-sources exposure estimate.
- Road and industry exposure is a geometric heuristic from OpenStreetMap, which is patchy in some Indian areas. Industrial areas are represented by their centre point.
- Travel times come from OSRM without live traffic; a weekday rush-hour factor (×1.6 for 8–10 AM and 5–8 PM) is applied and labelled as an assumption.
- Venue availability, bookings and opening hours are not known. Private or members-only access is flagged only when OpenStreetMap tags it.
- The 7-day horizon follows the forecast APIs (air quality: 5 days; later hours are scored without AQI and flagged).

## AI assistance disclosure
Parts of this code were written with help from an AI coding assistant (Claude by Anthropic) during development. No hosted large model is used in the running assistant; the only model at query time is the open-weights SLM described above.
