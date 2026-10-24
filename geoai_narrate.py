"""Narration by the SLM from a facts block only, followed by a code-level grounding check."""
import re
import geoai_slm as slm

SYSTEM = ("You are an outdoor-activity advisor. Write the answer using ONLY the FACTS provided. "
 "Never add a number, time, place name or claim that is not in the FACTS. Use exactly four short paragraphs "
 "starting with these labels: Recommendation, Why, What to carry, Watch out and avoid. About 130 words in total. "
 "If the FACTS say no safe slot exists, say clearly not to go and why.")
NUM = re.compile(r"\d+(?:\.\d+)?")
OKCAPS = {"i", "you", "your", "if", "it", "the", "this", "that", "there", "avoid", "carry", "check", "wear", "bring", "keep", "take", "stay", "go", "plan", "start"}

def check(text, facts):
    allowed, vocab = set(NUM.findall(facts)), set(re.findall(r"[a-z'’]+", facts.lower()))
    bad = [n for n in NUM.findall(text) if n not in allowed]
    clean = re.sub(r"[*#_`]", "", text)
    for sent in re.split(r"(?<=[.!?:])\s+|\n+", clean):
        toks = re.findall(r"[A-Za-z][A-Za-z'’]+", sent)[1:]
        bad += [t for t in toks if t[0].isupper() and t.lower() not in vocab and t.lower() not in OKCAPS]
    return bad

def _trim(t):
    t = t.strip()
    if t and t[-1] not in ".!?)": 
        i = max(t.rfind(". "), t.rfind(".\n"))
        t = t[:i+1] if i > 40 else t
    return t

def narrate(facts, template, use_slm=True):
    """Returns (text, method, violations_seen)."""
    seen = []
    if use_slm and slm.ready():
        user = f"FACTS:\n{facts}\n\nWrite the answer now."
        for _ in range(1):
            txt = slm.generate(SYSTEM, user, max_new=180, max_time=25)
            txt = _trim(txt) if txt else None
            if not txt or len(txt) < 80: continue
            bad = check(txt, facts)
            if not bad: return txt, "slm", seen
            seen += bad[:5]
            user += f"\nYour previous draft used items not in the FACTS ({', '.join(bad[:5])}). Remove them."
    return template, "template", seen
