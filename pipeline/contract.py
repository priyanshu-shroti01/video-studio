"""Python mirror of src/engine/types.ts (the render contract). Keep CONTRACT_VERSION in sync."""
from __future__ import annotations

import re
from pathlib import Path

from .paths import ROOT

CONTRACT_VERSION = 2  # v2 is a superset of v1; the engine also accepts v1 props unchanged
FORMATS = {"short": (1080, 1920), "landscape": (1920, 1080)}
COMPOSITION_ID = "Storyboard"

BLOCK_TYPES = {
    "logo", "headline", "text", "pill", "price", "checklist", "bars", "compare-rows", "plans",
    "domain-input", "browser", "hook-tag", "flat-line", "cta",
    # v2
    "kinetic-text", "counter", "price-compare", "terminal", "dashboard", "device", "image", "progress",
    "scroll-demo", "chart", "feature-compare", "logo-sting", "outro",
    # v2b (optional, same contract version)
    "plan-card", "install-flow", "server-stack",
    # footage (additive, same contract version): real video clips; zooms[].at is resolved as an ordinary at time
    "footage",
    # composition (additive, same contract version): generated scene graphics (pipeline/creative/composer.py);
    # elements[].at / countEnd / pulseAt are ordinary time keys, resolved like every other nested time
    "composition",
}
# Keys (anywhere inside a block) whose values are times on the timeline -> resolved by storyboard.py
TIME_KEYS = {
    "at", "exitAt", "countEnd", "growEnd", "clickAt", "doneAt", "availableAt", "cursorStart", "urlAt",
    "loadUntil", "stallAt", "drawEnd", "emphasizeAt",
    # v2
    "typeEnd", "scrollEnd", "winnerAt", "highlightAt",
    # v2b
    "pulseAt",
}
ICONS = {"zap", "lock", "server", "cloud", "globe", "arrowUp", "arrowRight", "check",
         "shield", "rocket", "clock", "database", "mail", "users", "chart", "star",
         # v2b
         "app", "cpu", "memory", "disk", "refresh", "plug", "palette", "settings", "download", "gauge", "play"}
TONES = {"text", "muted", "brand", "danger", "success", "warning", "info"}
# composition elements (src/engine/types.ts COMPOSITION_*): kinds, shapes, motion presets, theme colour tokens, text roles
COMPOSITION_KINDS = {"text", "shape", "connector", "icon", "number", "logo", "media"}
COMPOSITION_SHAPES = {"rect", "roundrect", "circle", "ring", "arc", "line"}
COMPOSITION_MOTIONS = {"fade-up", "fade", "scale-in", "draw-on", "pop", "none"}
COMPOSITION_COLORS = {"brand", "brandText", "surface", "card", "raised", "border", "bg", "text", "muted", "success", "danger",
                      "warning", "info"}
COMPOSITION_ROLES = {"title", "label", "body", "value"}


def ts_contract_version() -> int | None:
    """Read CONTRACT_VERSION from the TypeScript side so drift is caught by `doctor` and tests."""
    f = Path(ROOT, "src/engine/types.ts")
    if not f.exists():
        return None
    m = re.search(r"CONTRACT_VERSION\s*=\s*(\d+)", f.read_text())
    return int(m.group(1)) if m else None
