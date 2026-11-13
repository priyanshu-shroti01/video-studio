"""Model registry: static facts about each local LLM (pipeline/intelligence/model_registry.json) plus live
local availability from the Ollama store. Benchmark numbers are written by `bench` (measured, never guessed)."""
from __future__ import annotations

import json
import urllib.error
from pathlib import Path

REGISTRY_FILE = Path(__file__).with_name("model_registry.json")


def load_registry() -> dict:
    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


def model_entry(model_id: str) -> dict | None:
    try:
        return next((m for m in load_registry()["models"] if m["id"] == model_id or model_id in m.get("aliases", [])), None)
    except (OSError, ValueError, KeyError):
        return None


def save_benchmark(model_id: str, results: dict, *, memory_required_mb: float | None = None) -> None:
    reg = load_registry()
    for m in reg["models"]:
        if m["id"] == model_id:
            m["benchmark"] = results
            if memory_required_mb:
                m["memory_required_mb"] = round(memory_required_mb)
                m["memory_measured"] = True
    REGISTRY_FILE.write_text(json.dumps(reg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def with_local_availability(host: str = "http://127.0.0.1:11434") -> dict:
    from .providers import _http
    reg = load_registry()
    try:
        names = {t["name"] for t in _http(f"{host}/api/tags", timeout=3).get("models", [])}
        live = True
    except (urllib.error.URLError, OSError, ValueError):
        names, live = set(), False
    store = Path.home() / ".ollama" / "models" / "manifests" / "registry.ollama.ai" / "library"
    for m in reg["models"]:
        name, _, tag = m["id"].partition(":")
        on_disk = (store / name / (tag or "latest")).exists()
        m["local_available"] = (m["id"] in names) if live else on_disk
        m["local_check"] = "ollama /api/tags" if live else "manifest file in ~/.ollama/models (server not running)"
    return reg
