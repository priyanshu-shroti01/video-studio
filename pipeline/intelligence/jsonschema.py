"""Schema check for LLM outputs: pipeline.schema.validate plus anyOf / const / maxItems (the extra keywords
used in the Ollama `format` schemas)."""
from __future__ import annotations

from ..schema import validate as _base


def check(value, schema: dict, path: str = "$") -> list[str]:
    if "anyOf" in schema:
        best = None
        for sub in schema["anyOf"]:
            e = check(value, sub, path)
            if not e:
                return []
            best = e if best is None or len(e) < len(best) else best
        return best or [f"{path}: matches no alternative"]
    errs: list[str] = []
    if "const" in schema and value != schema["const"]:
        return [f"{path}: expected {schema['const']!r}"]
    shallow = {k: v for k, v in schema.items() if k not in ("properties", "items", "anyOf", "const", "maxItems", "additionalProperties")}
    errs += _base(value, shallow, path)
    if errs:
        return errs
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, v in enumerate(value):
                errs += check(v, schema["items"], f"{path}[{i}]")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for k, v in value.items():
            if k in props:
                errs += check(v, props[k], f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: unknown field '{k}'")
    return errs
