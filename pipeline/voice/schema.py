"""Voice configuration schema (project/preset `voice` section) and the semantic checks the JSON-schema
subset cannot express (provider/voice pairing, the online opt-in gate, installed models)."""
from __future__ import annotations

KOKORO_VOICE = r"^[abh][fm]_[a-z]+$"
PIPER_VOICE = r"^[a-z]{2,3}_[A-Z]{2}-[a-z0-9_]+-(x_low|low|medium|high)$"
EDGE_VOICE = r"^[A-Za-z]{2,3}-[A-Za-z]{2,4}-[A-Za-z]+Neural$"

VOICE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "$comment": {"type": "string"},
        "provider": {"type": "string", "enum": ["kokoro", "piper", "edge", "mock"]},
        "voice": {"type": "string", "pattern": f"{KOKORO_VOICE}|{PIPER_VOICE}|{EDGE_VOICE}|^mock$"},
        "rate": {"type": "string", "pattern": r"^[+-]\d{1,2}%$"},
        "pitch": {"type": "string", "pattern": r"^[+-]\d{1,3}Hz$"},
        "lang": {"type": "string", "enum": ["en-us", "en-gb"]},
        # Edge TTS sends narration text to Microsoft. It is refused unless this is literally true.
        "allowOnline": {"type": "boolean"},
        # per-project pronunciation overrides: {"display text": "spoken respelling"}
        "pronunciation": {"type": "object", "additionalProperties": {"type": "string", "minLength": 1,
                                                                     "maxLength": 200}},
        "maxPause": {"type": "number", "minimum": 0, "maximum": 3},
        "pad": {"type": "number", "minimum": 0, "maximum": 2},
        "sceneGap": {"type": "number", "minimum": 0, "maximum": 3},
        "timeout": {"type": "number", "minimum": 5, "maximum": 600},
        "attempts": {"type": "integer", "minimum": 1, "maximum": 8},
    },
}


def check_voice_config(v: dict, *, check_models: bool = True) -> tuple[list[str], list[str]]:
    """-> (errors, warnings) for a merged voice section. Call after VOICE_SCHEMA validation."""
    import re

    from . import registry
    errors, warnings = [], []
    prov, voice = v.get("provider"), v.get("voice", "")
    if prov == "edge":
        if v.get("allowOnline") is not True:
            errors.append("$.voice.provider: 'edge' is Microsoft's ONLINE TTS service and would send the narration "
                          "text off this machine; set \"allowOnline\": true in the project's voice section to opt "
                          "in, or use a local provider ('kokoro' or 'piper')")
        else:
            warnings.append("$.voice: Edge TTS (online) is enabled by allowOnline: narration text is sent to Microsoft")
        if voice and not re.search(EDGE_VOICE, voice):
            errors.append(f"$.voice.voice: {voice!r} is not an Edge voice name (e.g. en-IN-PrabhatNeural)")
    elif prov in ("kokoro", "piper"):
        known = registry.voices(prov)
        if voice not in known:
            errors.append(f"$.voice.voice: {voice!r} is not an installed {prov} voice; choose one of {sorted(known)}")
        else:
            meta = known[voice]
            if not meta.get("commercial", False):
                errors.append(f"$.voice.voice: {voice!r} is not licensed for commercial use ({meta.get('licence')})")
            if check_models:
                missing = registry.problems(registry.voice_files(prov, voice)
                                            + (["kokoro-model", "kokoro-vocab"] if prov == "kokoro" else []),
                                            verify=False)
                if missing:
                    warnings.append(f"$.voice: {prov} model files are not installed ({'; '.join(missing)}); run: "
                                    + registry.FETCH_HINT.format(group=prov))
        if v.get("allowOnline"):
            warnings.append("$.voice.allowOnline has no effect: the selected provider runs locally")
        if v.get("pitch", "+0Hz") not in ("+0Hz", "-0Hz"):
            warnings.append(f"$.voice.pitch {v['pitch']} is ignored by the local '{prov}' provider")
        if v.get("lang") and prov == "piper":
            warnings.append("$.voice.lang is ignored by piper (each Piper voice has a fixed phonemizer language)")
    elif prov == "mock" and voice != "mock":
        errors.append("$.voice.voice: the mock provider only has voice 'mock'")
    return errors, warnings
