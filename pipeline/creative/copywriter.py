"""The LLM's role: copy assistant, not designer.

It may (a) pick a hook from the hook template's options and (b) rewrite narration / on-screen-phrase slots
inside fixed word budgets in the copy-bank style. It never sees or writes blocks, labels, prices or times.
Every output is validated per slot:

  schema · word budget · banned phrases · Latin script · numbers (only exact bound fact values) · no currency
  symbols / percentages / URLs except the brand domain · on-screen phrase must be spoken verbatim · claim
  check (pipeline.intelligence.claims) · beat alignment: every beat the bank line anchors on a spoken word must
  still find its word, and the scene must still pass the sync rules

Any failure -> the copy-bank line for that slot. The report records, per slot, the source ("llm" | "bank")
and the reasons."""
from __future__ import annotations

import json
import re

from ..intelligence.claims import NEEDS_REVIEW, normalize_numbers
from ..intelligence.providers import LLMError, MockProvider, Provider
from ..timing import norm
from .copybank import banned_hits, word_count

SYSTEM = (
    "You are a senior copywriter for 30-second product videos. The visuals, labels, prices and timing are FIXED by a "
    "designer; you only write the voice-over lines (and a short on-screen phrase where asked). House style: confident, "
    "concrete, second person, short sentences, name the real thing shown on screen instead of adjectives. "
    "Never use clichés (seamless, game-changer, unlock, effortless, no tech skills needed), superlatives (best, fastest, "
    "cheapest), guarantees, or any number that is not in the ALLOWED NUMBERS list. Never write currency or percent symbols; "
    "write the amount and the currency word. Keep every CUE WORD: an animation is triggered when the narrator says it. "
    "Return JSON only.")


def system_prompt(voice: str = "", style: str = "") -> str:
    return SYSTEM + (f"\nBRAND VOICE: {voice}" if voice else "") + (f"\nINDUSTRY STYLE: {style}" if style else "")

RE_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
RE_URL = re.compile(r"\b(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}\b", re.I)


# ---- hooks (concept stage) -----------------------------------------------------------------------------
def choose_hooks(provider: Provider | None, brief: dict, concepts: list[dict], log: list, voice: str = "") -> dict[str, dict]:
    """-> {concept_id: {"choice": variant id, "source": "llm"|"bank", "reason"}}"""
    out = {c["id"]: {"choice": c["hook_variant"], "source": "bank", "reason": "deterministic default"} for c in concepts}
    if provider is None:
        return out
    ok, why = provider.available()
    if not ok:
        log.append({"event": "llm_unavailable", "task": "hooks", "reason": why})
        for v in out.values():
            v["reason"] = f"LLM unavailable: {why}"
        return out
    schema = {"type": "object", "additionalProperties": False, "required": [c["id"] for c in concepts],
              "properties": {c["id"]: {"type": "string", "enum": [h["id"] for h in c["hook_options"]]} for c in concepts}}
    lines = []
    for c in concepts:
        lines.append(f"Concept {c['id']} ({c['name']}: {c['logline']}). Hook options:")
        lines += [f"  - {h['id']}: \"{h['text']}\"" for h in c["hook_options"]]
    msg = (f"Product: {brief['product']} by {brief['brand']}. Audience: {brief.get('audience') or 'general'}. Tone: {brief.get('tone')}.\n"
           + "\n".join(lines) + "\nFor each concept pick the hook option that will stop a scroller in this audience. "
           "Give different concepts different kinds of hooks. JSON: {concept_id: option_id}.")
    try:
        r = provider.generate_json(system=system_prompt(voice), messages=[{"role": "user", "content": msg}], schema=schema, task="creative_hooks",
                                   context={"brief": brief, "concepts": concepts}, temperature=0.4, seed=5, max_tokens=200)
    except LLMError as e:
        log.append({"event": "llm_error", "task": "hooks", "error": e.message})
        return out
    log.append({"event": "hooks_generated", "stats": r.stats.as_dict(), "schema_errors": r.schema_errors[:4], "raw": r.data})
    for c in concepts:
        v = r.data.get(c["id"]) if isinstance(r.data, dict) else None
        if v in {h["id"] for h in c["hook_options"]}:
            out[c["id"]] = {"choice": v, "source": "llm", "reason": "chosen by the model from the template's hook options"}
        else:
            out[c["id"]]["reason"] = f"model returned {v!r}, not one of the options"
    return out


# ---- slot validation -----------------------------------------------------------------------------------
def numbers_in(text: str) -> set[float]:
    return {float(x.replace(",", "")) for x in RE_NUM.findall(normalize_numbers(text))}


def validate_line(slot: dict, narration: str, headline: str | None, *, fb, brief, domain: str, banned: list[str] | None = None) -> list[str]:
    """Problems with an LLM line for one scene slot (empty = accept)."""
    p = []
    if not isinstance(narration, str) or not narration.strip():
        return ["narration missing"]
    n = word_count(narration)
    lo, hi = slot["words"]
    if not lo <= n <= hi:
        p.append(f"narration has {n} words; budget {lo}–{hi}")
    if re.search(r"[^\x00-\x7F’‘“”—–…]", narration):
        p.append("non-Latin or symbol characters (write amounts as digits plus the currency word)")
    if re.search(r"[₹%$€£#@*]", narration):
        p.append("currency/percent/markup symbol in narration")
    for b in banned_hits(narration + " " + (headline or ""), banned):
        p.append(f"banned phrase {b!r}")
    allowed = {float(x) for x in slot["allowed_numbers"]}
    bad = sorted(x for x in numbers_in(narration) if x not in allowed and x >= 2)
    if bad:
        p.append(f"numbers {[int(x) if x.is_integer() else x for x in bad]} are not bound facts for this scene (allowed {sorted(int(a) for a in allowed)})")
    for m in RE_URL.finditer(narration):
        if m.group(0).lower().rstrip(".") != domain.lower():
            p.append(f"URL {m.group(0)!r} is not the brand site")
    # beat alignment (every beat the bank line anchors on a spoken word still finds one of its cue words) is checked
    # on the rebuilt scene by api._scene_ok, which accepts any of a beat's cue words, not only the bank's
    if slot.get("headline"):
        lo_h, hi_h = slot["headline"]
        if not headline:
            p.append("on-screen phrase missing")
        else:
            hn = word_count(headline)
            if not lo_h <= hn <= hi_h:
                p.append(f"on-screen phrase has {hn} words; budget {lo_h}–{hi_h}")
            if norm(headline) not in norm(narration) or not _is_phrase(headline, narration):
                p.append(f"on-screen phrase {headline!r} is not spoken verbatim in the narration (no new labels)")
    if not p:
        from .claims_v2 import verify_line
        for c in verify_line(narration + (" " + headline if headline else ""), fb, brief):
            if c["status"] == NEEDS_REVIEW:
                p.append(f"claim {c['text']!r}: {c.get('reason', 'not verified')}")
    return p


def _is_phrase(h: str, narr: str) -> bool:
    hw = [norm(w) for w in h.split() if norm(w)]
    nw = [norm(w) for w in narr.split() if norm(w)]
    return any(nw[i:i + len(hw)] == hw for i in range(len(nw) - len(hw) + 1))


def copy_schema(slots: list[dict]) -> dict:
    props = {}
    for s in slots:
        p = {"narration": {"type": "string", "minLength": 8, "maxLength": s["words"][1] * 9}}
        req = ["narration"]
        if s.get("headline"):
            p["headline"] = {"type": "string", "minLength": 2, "maxLength": 48}
            req.append("headline")
        props[s["scene"]] = {"type": "object", "additionalProperties": False, "required": req, "properties": p}
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def copy_prompt(brief: dict, concept: dict, slots: list[dict], examples: list[str]) -> str:
    lines = [f"PRODUCT: {brief['product']} by {brief['brand']} · AUDIENCE: {brief.get('audience') or 'general'} · TONE: {brief.get('tone')}",
             f"CONCEPT: {concept['name']} — {concept['logline']}", "",
             "HOUSE STYLE EXAMPLES (copy bank):"] + [f"  \"{e}\"" for e in examples[:6]] + ["", "SCENES (write a NEW line for each scene in your own words: same meaning, same cue words; do not copy the current line):"]
    for s in slots:
        lines.append(f"- {s['scene']} [{s['role']}] on screen: {s['describe']}")
        lines.append(f"    current line: \"{s['bank']['narration']}\"")
        lines.append(f"    words: {s['words'][0]}–{s['words'][1]} · REQUIRED WORDS: {', '.join(s['required_words']) or 'none'} · "
                     f"ALLOWED NUMBERS: {', '.join(str(int(x)) for x in s['allowed_numbers']) or 'none'}")
        if s.get("headline"):
            lines.append(f"    headline: {s['headline'][0]}–{s['headline'][1]} words, copied word for word from YOUR narration "
                         f"(current: \"{s['bank'].get('headline')}\")")
    lines.append("\nReturn JSON: {scene_id: {\"narration\": ..., \"headline\"?: ...}} for every scene.")
    return "\n".join(lines)


def rewrite(provider: Provider | None, brief: dict, concept: dict, slots: list[dict], examples: list[str], log: list,
            seed: int = 21, voice: str = "", style: str = "") -> dict[str, dict]:
    """-> {scene_id: {"narration", "headline"?} } raw model proposals (unvalidated); {} when no model."""
    if provider is None:
        return {}
    ok, why = provider.available()
    if not ok:
        log.append({"event": "llm_unavailable", "task": "copy", "reason": why})
        return {}
    try:
        r = provider.generate_json(system=system_prompt(voice, style), messages=[{"role": "user", "content": copy_prompt(brief, concept, slots, examples)}],
                                   schema=copy_schema(slots), task="creative_copy",
                                   context={"brief": brief, "concept": concept, "slots": slots}, temperature=0.6, seed=seed,
                                   max_tokens=900)
    except LLMError as e:
        log.append({"event": "llm_error", "task": "copy", "error": e.message})
        return {}
    log.append({"event": "copy_generated", "stats": r.stats.as_dict(), "schema_errors": r.schema_errors[:6]})
    data = r.data if isinstance(r.data, dict) else {}
    out = {}
    for s in slots:
        d = data.get(s["scene"])
        if isinstance(d, dict):
            extra = sorted(set(d) - {"narration", "headline"})
            out[s["scene"]] = {"narration": d.get("narration"), "headline": d.get("headline"), "extra_keys": extra}
    return out


# ---- mock ----------------------------------------------------------------------------------------------
def mock_responder(task: str, context: dict, messages: list[dict]) -> dict:
    """Deterministic stand-in for the model: picks the last hook option, and proposes the *alternative* bank line
    for each slot (so the LLM path is exercised and validated end to end without a model)."""
    if task == "creative_hooks":
        return {c["id"]: c["hook_options"][-1]["id"] for c in context["concepts"]}
    if task == "creative_copy":
        out = {}
        for s in context["slots"]:
            alt = s.get("alternatives") or [s["bank"]]
            pick = alt[0]
            d = {"narration": pick["narration"]}
            if s.get("headline"):
                d["headline"] = pick.get("headline") or ""
            out[s["scene"]] = d
        return out
    raise ValueError(f"no mock answer for {task!r}")


def mock_provider(**kw) -> MockProvider:
    return MockProvider(responder=mock_responder, model="mock-creative-1", **kw)


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False)
