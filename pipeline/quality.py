"""Quality presets: frame rate x render scale x bitrate (docs/ARCHITECTURE.md "Quality presets").

  standard  1080 wide, 30 fps   (the default; identical to every render before presets existed)
  smooth    1080 wide, 60 fps   (~2x render time)
  ultra     2x size,   60 fps   (2160x3840 Short / 3840x2160 landscape, ~4-6x render time)

The layout never changes: compositions, props and the QA layout manifest stay in design units (1080-wide).
`ultra` asks Remotion for `--scale=2`, so Chromium rasterises every vector (text, SVG, CSS) at twice the
pixel density instead of upscaling a 1080p frame. Time-based values (seconds) are fps-independent; only the
props' `fps`/`durationInFrames` and a few frame-quantised constants change with the frame rate."""
from __future__ import annotations

from dataclasses import dataclass

from .contract import FORMATS
from .errors import ConfigError

DEFAULT_QUALITY = "standard"
BASE_FPS = 30                        # the rate every frame-count constant was tuned for


@dataclass(frozen=True)
class QualityPreset:
    name: str
    fps: int
    scale: int
    bitrate: str                     # VideoToolbox ABR target (it undershoots; x264 fallback uses it too)
    label: str
    cost: str                        # render time vs standard, for the UI

    def size(self, fmt: str) -> tuple[int, int]:
        """Output pixel size of a format at this preset."""
        w, h = FORMATS[fmt]
        return w * self.scale, h * self.scale


QUALITY_PRESETS: dict[str, QualityPreset] = {
    "standard": QualityPreset("standard", 30, 1, "40M", "Standard (1080p · 30 fps)", "1x"),
    "smooth": QualityPreset("smooth", 60, 1, "24M", "Smooth (1080p · 60 fps)", "~2x"),
    "ultra": QualityPreset("ultra", 60, 2, "60M", "Ultra (4K · 60 fps)", "~4-6x"),
}
QUALITIES = list(QUALITY_PRESETS)


def preset(name: str | None) -> QualityPreset:
    if name is None:
        return QUALITY_PRESETS[DEFAULT_QUALITY]
    try:
        return QUALITY_PRESETS[name]
    except KeyError:
        raise ConfigError(f"unknown quality {name!r}; use one of {QUALITIES}") from None


def of_config(cfg: dict) -> QualityPreset:
    """The preset of a resolved project config (`render.quality`, default standard)."""
    return preset((cfg.get("render") or {}).get("quality"))


def of_brief(brief: dict | None) -> QualityPreset:
    return preset((brief or {}).get("quality"))


def apply_to_project(project: dict, brief: dict | None) -> dict:
    """Productions inherit the brief's quality as `render.quality` (only when the brief names one, so a project
    without it stays byte-identical to before)."""
    q = (brief or {}).get("quality")
    if q:
        preset(q)                    # validate
        project.setdefault("render", {})["quality"] = q
    return project
