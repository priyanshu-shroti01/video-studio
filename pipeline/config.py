"""Project configuration = preset defaults <- project file overrides, plus the brand theme and the
storyboard, fully resolved and validated. Its hash identifies a production (duplicate detection) and
seeds every stage's cache key."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from .contract import FORMATS
from .errors import ConfigError
from .paths import ROOT, safe_name, safe_path, sha256_json
from .schema import validate
from .storyboard import validate_storyboard
from .voice.schema import VOICE_SCHEMA  # owned by the voice subsystem

PRESETS_DIR = ROOT / "presets"
BRANDS_DIR = ROOT / "brands"

PROJECT_SCHEMA = {
    "type": "object",
    "required": ["name", "brand", "preset", "storyboard"],
    "additionalProperties": False,
    "properties": {
        "$comment": {"type": "string"},
        "name": {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"},
        "brand": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9_-]{0,40}$"},
        "preset": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9_-]{0,40}$"},
        "formats": {"type": "array", "minItems": 1, "items": {"type": "string", "enum": list(FORMATS)}},
        "storyboard": {"type": ["string", "object"]},
        "voice": {"type": "object"},
        "audio": {"type": "object"},
        "captions": {"type": "object"},
        "render": {"type": "object"},
        "qa": {"type": "object"},
        "publishing": {"type": "object"},
        "structure": {"type": "array", "items": {"type": "string"}},
        "captionsByFormat": {"type": "object"},
        "motion": {"type": "string", "enum": ["calm", "standard", "energetic", "cinematic"]},
        "branding": {"type": "object"},
        "review": {"type": "object"},
    },
}
AUDIO_SCHEMA = {
    "type": "object",
    "properties": {
        "music": {"type": ["string", "null"]},
        "musicDb": {"type": "number", "minimum": -60, "maximum": 0},
        "voiceDb": {"type": "number", "minimum": -20, "maximum": 12},
        "sfxDb": {"type": "number", "minimum": -40, "maximum": 6},
        "lufs": {"type": ["number", "null"], "minimum": -36, "maximum": -6},
        "truePeak": {"type": "number", "minimum": -9, "maximum": 0},
        "lra": {"type": "number", "minimum": 1, "maximum": 30},
        "voiceRefLufs": {"type": ["number", "null"], "minimum": -40, "maximum": -6},
        "musicMood": {"type": "string", "enum": ["cinematic", "corporate", "technology", "energetic", "minimal",
                                                  "educational", "calm", "promotional"]},
        "musicRequest": {"type": "string"},
        "autoSfx": {"type": "boolean"},
        "tail": {"type": "number", "minimum": 0, "maximum": 5},
        "kit": {"type": "string"},
        "duck": {"type": "object", "properties": {
            "threshold": {"type": "number", "minimum": 0.001, "maximum": 1},
            "ratio": {"type": "number", "minimum": 1, "maximum": 20},
            "attackMs": {"type": "number", "minimum": 0.01, "maximum": 2000},
            "releaseMs": {"type": "number", "minimum": 0.01, "maximum": 9000}}},
    },
}
CAPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "enabled": {"type": "boolean"}, "style": {"type": "string", "enum": ["word", "phrase"]},
        "maxWords": {"type": "integer", "minimum": 1, "maximum": 12},
        "maxChars": {"type": "integer", "minimum": 8, "maximum": 80},
        "fontSize": {"type": "integer", "minimum": 24, "maximum": 140},
        "bottomFrac": {"type": "number", "minimum": 0.02, "maximum": 0.6},
        "maxWidthFrac": {"type": "number", "minimum": 0.3, "maximum": 1},
        "maxCps": {"type": "number", "minimum": 5, "maximum": 60},
        "hold": {"type": "number", "minimum": 0, "maximum": 3},
    },
}
RENDER_SCHEMA = {
    "type": "object",
    "properties": {
        "encoder": {"type": "string", "enum": ["auto", "videotoolbox", "x264"]},
        "bitrate": {"type": "string", "pattern": r"^\d{1,3}M$"},
        "crf": {"type": "integer", "minimum": 0, "maximum": 51},
        "imageFormat": {"type": "string", "enum": ["png", "jpeg"]},
        "chunkFrames": {"type": "integer", "minimum": 30, "maximum": 100000},
        "concurrency": {"type": ["integer", "string"]},
        "timeoutPerChunk": {"type": "number", "minimum": 30},
        "stallTimeout": {"type": "number", "minimum": 10},
        "retries": {"type": "integer", "minimum": 0, "maximum": 5},
        "minFreeGb": {"type": "number", "minimum": 0},
    },
}


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_json(path: Path, what: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"{what} not found: {path}") from e
    except json.JSONDecodeError as e:
        raise ConfigError(f"{what} is not valid JSON: {path}: line {e.lineno} col {e.colno}: {e.msg}") from e


def load_preset(name: str) -> dict:
    return load_json(safe_path(PRESETS_DIR / f"{safe_name(name)}.json"), f"preset '{name}'")


def load_theme(brand: str) -> dict:
    theme = load_json(safe_path(BRANDS_DIR / safe_name(brand) / "theme.json"), f"brand theme '{brand}'")
    return theme


def theme_asset_paths(theme: dict) -> list[str]:
    paths = [theme["logo"][k] for k in ("onDark", "onLight", "mark")]
    for fam in theme["fonts"].values():
        paths += [f["src"] for f in fam["files"]]
    return paths


def load_project(path: str | Path) -> tuple[dict, list[str]]:
    """-> (resolved config, warnings). Raises ConfigError with every problem listed."""
    p = safe_path(path, must_exist=True)
    raw = load_json(p, "project config")
    errs = validate(raw, PROJECT_SCHEMA, "$")
    if errs:
        raise ConfigError("project config is invalid", detail="\n".join(errs))
    preset = load_preset(raw["preset"])
    cfg = deep_merge(preset, {k: v for k, v in raw.items() if k != "$comment"})
    if isinstance(cfg["storyboard"], str):
        sp = safe_path(cfg["storyboard"], must_exist=True)
        cfg["storyboard_path"] = str(sp.relative_to(ROOT))
        cfg["storyboard"] = load_json(sp, "storyboard")
    cfg["theme"] = load_theme(raw["brand"])
    errs = []
    for key, schema in (("voice", VOICE_SCHEMA), ("audio", AUDIO_SCHEMA), ("captions", CAPTION_SCHEMA),
                        ("render", RENDER_SCHEMA)):
        errs += validate(cfg.get(key, {}), schema, f"$.{key}")
    from .voice.schema import check_voice_config
    ve, vw = check_voice_config(cfg.get("voice", {}))
    errs += [f"$.voice: {e}" for e in ve]
    sb_errs, warnings = validate_storyboard(cfg["storyboard"], structure=cfg.get("structure"))
    warnings += [f"voice: {w}" for w in vw]
    errs += sb_errs
    from .brands import asset_allowed, load_profile, referenced_assets, validate_brand
    cfg["brandProfile"] = load_profile(raw["brand"])
    # brand pronunciations (brands/<id>/pronunciation.json) sit under the project's own overrides
    from .brands import load_pronunciation
    bp = load_pronunciation(raw["brand"])
    if bp:
        cfg.setdefault("voice", {})["pronunciation"] = {**bp, **(cfg.get("voice", {}).get("pronunciation") or {})}
    errs += [f"brand: {e}" for e in validate_brand(raw["brand"], cfg["theme"])]
    for a in referenced_assets(cfg["storyboard"]):
        if not asset_allowed(raw["brand"], a, cfg["brandProfile"]):
            errs.append(f"$storyboard: asset {a} belongs to another brand or an unapproved location")
    if not sb_errs:
        # footage: the file must be a decodable video inside public/; fill aspect + duration from ffprobe (in memory)
        from .footage import prepare_footage
        errs += prepare_footage(cfg["storyboard"])
    music = cfg.get("audio", {}).get("music")
    if music:
        from .music import is_publishable, resolve
        try:
            path, rec = resolve(music, cfg.get("publishing", {}).get("durationHint", 35.0))
            safe_path(path, must_exist=True)
            cfg["audio"]["music"] = path
            if music.startswith("mood:"):
                cfg["audio"]["musicRequest"] = music
            if not rec or not is_publishable(rec):
                warnings.append(f"music {path} is not cleared for publication (licence: "
                                f"{rec.get('license') if rec else 'no record'}); approval will be blocked")
        except Exception as e:  # noqa: BLE001
            errs.append(f"$.audio.music: {e}")
    if errs:
        raise ConfigError("project config is invalid", detail="\n".join(errs))
    return cfg, warnings


def config_hash(cfg: dict) -> str:
    """Hash of everything that affects the output (not the file path it came from)."""
    return sha256_json({k: v for k, v in cfg.items() if k not in ("storyboard_path", "publishing")})
