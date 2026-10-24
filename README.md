# geoai-outdoor-assistant
GeoAI assistant that recommends the best nearby place and time for outdoor activities. A small open SLM (Qwen2.5-1.5B) parses questions and writes advice; code fetches live OSM, Open-Meteo and OSRM data, scores place × hour using wind exposure from roads/industry, and verifies every number. Gradio UI + JSON API.
