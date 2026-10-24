---
license: apache-2.0
base_model: Qwen/Qwen2.5-1.5B-Instruct
library_name: transformers
pipeline_tag: text-generation
language: [en]
tags: [geoai, outdoor-activities, small-language-model]
---

# GeoAI Outdoor Advisor: language model

**Base model:** [Qwen/Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct), 1.5B parameters, open weights, Apache-2.0 (confirm on the base model's card).
**Changes:** none. The weights are the unmodified base model, republished so the app loads them from this repository. (If you add a LoRA adapter later, describe the data and training here and keep the base model named above.)

## Intended use
Inside the GeoAI Outdoor Advisor app, the model does two jobs only:
1. Read a free-form outdoor-activity question into JSON (activity, place, radius, time, health profile).
2. Phrase advice from a facts block that the application builds from live weather, air-quality and OpenStreetMap data.

The model is never asked to supply weather, places or numbers from memory. The application checks that every number and place name in its text appears in the facts and falls back to a fixed template otherwise.

## Out of scope
General question answering, medical advice, or any use without live data. Recommendations are heuristic and not a substitute for professional advice.

## Load
```python
from transformers import AutoModelForCausalLM, AutoTokenizer
tok = AutoTokenizer.from_pretrained("Bhar1324/geoai-outdoor-advisor-qwen2.5-1.5b")
model = AutoModelForCausalLM.from_pretrained("Bhar1324/geoai-outdoor-advisor-qwen2.5-1.5b")
```
Base model: https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct. Owner: https://huggingface.co/Bhar1324. Source code and README: link your code repository here.
