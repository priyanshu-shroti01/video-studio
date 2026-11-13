"""Creative intelligence: product brief -> 3 distinct concepts -> validated, fact-checked storyboard, using a
LOCAL model only (Ollama on 127.0.0.1) with a deterministic template planner as fallback.

    from pipeline.intelligence import generate_concepts, build_storyboard
    res = generate_concepts(brief_dict, request_sentence, provider="ollama", out_dir="output/x")
    sb, project, reports = build_storyboard(res["brief"], res["concepts"][0], provider="ollama", out_dir="output/x")

See docs/CREATIVE_ENGINE.md and docs/LOCAL_AI.md."""
from .api import build_storyboard, generate_concepts
from .brief import parse_brief
from .claims import verify_storyboard
from .facts import load_facts
from .providers import LLMError, LLMUnavailable, MockProvider, OllamaProvider, get_provider

__all__ = ["generate_concepts", "build_storyboard", "parse_brief", "verify_storyboard", "load_facts", "get_provider",
           "MockProvider", "OllamaProvider", "LLMError", "LLMUnavailable"]
