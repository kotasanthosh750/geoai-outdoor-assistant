"""Gradio Space entrypoint: one backend (geoai_pipeline) behind the Gradio UI and a JSON API."""
try:
    import spaces  # noqa: F401  (import first on Hugging Face Spaces)
except Exception:
    pass
import folium
import gradio as gr
import geoai_pipeline as pipeline
import geoai_slm as slm

slm.start()   # the language model loads in the background; the app answers with rules and templates until it is ready

# ---------------- map ----------------
STYLE = {"pick": ("#1f9d55", 11), "alt": ("#2f6fbf", 8), "other": ("#8a8f8c", 6), "highway": ("#555555", 3),
         "industry": ("#8a4fbf", 6), "water": ("#1aa3c4", 5), "green": ("#9ad19a", 4), "origin": ("#b3402f", 8)}
LEGEND = ("🟢 best pick · 🔵 alternative · ⚪ other venue · ⚫ major road · 🟣 industry · 🔷 water · "
          "🟠 dashed line: where the wind comes from · 🔴 search centre. Map © OpenStreetMap contributors.")

def render_map(g):
    feats = (g or {}).get("features", [])
    if not feats: return "<p style='padding:1rem'>The map appears after a recommendation.</p>"
    lo0, la0 = feats[0]["geometry"]["coordinates"][:2]
    m = folium.Map(location=[la0, lo0], zoom_start=13, tiles="OpenStreetMap")
    bounds = []
    for f in feats:
        p, k = f["properties"], f["properties"].get("kind", "other")
        tip = p.get("name", k) + (f" · score {p['score']}" if p.get("score") is not None else "")
        if f["geometry"]["type"] == "Point":
            lo, la = f["geometry"]["coordinates"]; c, r = STYLE.get(k, STYLE["other"])
            folium.CircleMarker([la, lo], radius=r, color="#ffffff", weight=1.5, fill=True, fill_color=c, fill_opacity=.95, tooltip=tip).add_to(m)
            if k in ("pick", "alt", "origin", "other"): bounds.append([la, lo])
        else:
            pts = [[c[1], c[0]] for c in f["geometry"]["coordinates"]]
            kw = dict(color="#c77d00", weight=5, dash_array="2 8") if k == "wind" else dict(color="#2f6fbf", weight=4, opacity=.7)
            folium.PolyLine(pts, tooltip=tip, **kw).add_to(m)
    if len(bounds) > 1: m.fit_bounds(bounds, max_zoom=15)
    return m._repr_html_()

# ---------------- text ----------------
def bullets(title, items):
    return f"\n\n**{title}**\n" + "\n".join(f"- {x}" for x in items) if items else ""

def render_text(r):
    md = r["answer"]
    if r["status"] != "ok" and r.get("question"): md = f"**{r['question']}**\n\n{md}"
    if r.get("alternatives"): md += bullets("Other options", [f"{a['place']}: {a['start_label']}–{a['end_label']} (score {a['score']})" for a in r["alternatives"]])
    if r.get("backup_time"): md += bullets("Backup time", [f"{r['backup_time']['start_label']}–{r['backup_time']['end_label']} (score {r['backup_time']['score']})"])
    if r.get("avoid_windows"): md += bullets("When to avoid", [f"{a['scope']} {a['from']} to {a['to']}: {'; '.join(a['reasons'])}" for a in r["avoid_windows"]])
    md += bullets("Assumptions I made", r.get("assumptions"))
    md += bullets("Data gaps", r.get("warnings"))
    md += bullets("Live data used", [f"[{s['name']}]({s['url']}): {s['purpose']}" + (" (cached)" if s["cached"] else "") for s in r.get("sources_used", [])])
    if r.get("narration"):
        how = "the small language model, checked against the data" if r["narration"]["method"] == "slm" else "a fixed template (the model draft failed the grounding check or the model was not ready)"
        md += f"\n\n<sub>Wording by {how}. Took {r['timing']['total_s']} s.</sub>"
    return md

def ui(query, use_slm):
    r = pipeline.run(query, None, None, bool(use_slm))
    return render_text(r), render_map(r["map"]), r

# ---------------- API functions (same backend) ----------------
def ask_json(query: str, use_slm: bool = True, lat: float | None = None, lon: float | None = None) -> dict:
    """Full JSON answer: status, answer, recommendation, alternatives, avoid_windows, evidence, GeoJSON map, sources_used."""
    return pipeline.run(query, lat, lon, bool(use_slm))

def health() -> dict:
    return {"status": "ok", "model": slm.MODEL_ID, "model_ready": slm.ready(), "model_error": slm.error()}

# ---------------- Gradio UI ----------------
with gr.Blocks(title="GeoAI Outdoor Advisor") as demo:
    gr.Markdown("# 🌳 GeoAI Outdoor Advisor\nAsk where and when to go. Answers use live weather, air quality and OpenStreetMap data fetched when you ask, with a small open language model (Qwen2.5-1.5B-Instruct) for wording.")
    with gr.Row():
        with gr.Column(scale=5):
            q = gr.Textbox(label="Your question", lines=3, placeholder="Where can I jog tomorrow morning near Indiranagar? I have mild asthma.")
            with gr.Row():
                go = gr.Button("Get recommendation", variant="primary")
                slm_on = gr.Checkbox(value=True, label="Polish wording with the language model (slower)")
            out = gr.Markdown()
            with gr.Accordion("Raw API response", open=False):
                raw = gr.JSON()
        with gr.Column(scale=6):
            map_html = gr.HTML(render_map(None))
            gr.Markdown(LEGEND)
    go.click(ui, [q, slm_on], [out, map_html, raw], api_name="ask")
    q.submit(ui, [q, slm_on], [out, map_html, raw], api_name=False)
    gr.api(ask_json, api_name="ask_json")
    gr.api(health, api_name="health")

if __name__ == "__main__":
    demo.queue(default_concurrency_limit=2).launch(server_name="0.0.0.0", server_port=7860)
