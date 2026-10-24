"""Small language model wrapper (<= 3B parameters, open weights, runs inside this app)."""
try:
    import spaces                      # present on Hugging Face Spaces; must be imported before torch
    _gpu = spaces.GPU(duration=30)
except Exception:
    _gpu = lambda f: f
import os, json, re, threading
MODEL_ID = os.environ.get("MODEL_ID", "Qwen/Qwen2.5-1.5B-Instruct")
_s = dict(tok=None, model=None, ready=False, error=None)
_lock = threading.Lock()

def _load():
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(MODEL_ID)
        gpu = torch.cuda.is_available()
        m = AutoModelForCausalLM.from_pretrained(MODEL_ID, torch_dtype=torch.float16 if gpu else torch.float32)
        if gpu: m = m.to("cuda")
        m.eval(); _s.update(tok=tok, model=m, ready=True)
    except Exception as e:                      # the app keeps working with rules + templates
        _s["error"] = f"{type(e).__name__}: {e}"

def start():
    threading.Thread(target=_load, daemon=True).start()

def ready(): return _s["ready"]
def error(): return _s["error"]

@_gpu
def generate(system, user, max_new=200, max_time=30):
    if not _s["ready"]: return None
    import torch
    tok, m = _s["tok"], _s["model"]
    with _lock:
        text = tok.apply_chat_template([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                       tokenize=False, add_generation_prompt=True)
        ids = tok(text, return_tensors="pt").to(m.device)
        with torch.no_grad():
            out = m.generate(**ids, max_new_tokens=max_new, do_sample=False, max_time=max_time,
                             pad_token_id=tok.eos_token_id)
        return tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()

def json_from(text):
    if not text: return None
    m = re.search(r"\{.*\}", text, re.S)
    try: return json.loads(m.group(0)) if m else None
    except Exception: return None
