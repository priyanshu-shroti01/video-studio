"""Frame-accurate Studio player: props identical to the preview/render timeline path, with estimated timing."""
import json
import shutil
import uuid
from pathlib import Path

import pytest

from pipeline import preview_player as PP
from pipeline.config import load_project
from pipeline.errors import NotFound, PipelineError
from pipeline.timeline import build_timeline, estimated_timing


@pytest.fixture
def ws_tmp():
    """Scratch dir INSIDE the workspace (paths outside it are rejected by design)."""
    from pipeline.paths import TMP_DIR
    d = TMP_DIR / f"test-productions-{uuid.uuid4().hex[:8]}"
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _prod(tmp_path, monkeypatch):
    """A production with the gate fixture storyboard saved through the API (no render, no TTS)."""
    import pipeline.productions as P
    from pipeline import api
    monkeypatch.setattr(P, "PRODUCTIONS_DIR", tmp_path)
    p = api.create_production("shrotihost", {"brand": "Shroti Host", "product": "WordPress Hosting", "format": "short"})
    sb = json.loads(Path("tests/fixtures/gate-storyboard.json").read_text())
    proj = json.loads(Path("tests/fixtures/gate-project.json").read_text())
    proj["name"] = "player-test"
    api.save_storyboard(p["id"], sb, project=proj)
    return api, p["id"], Path(api.Productions().get(p["id"])["dir"])


def test_player_props_match_the_preview_timeline_exactly(registry, ws_tmp, monkeypatch):
    api, pid, pd = _prod(ws_tmp, monkeypatch)
    out = PP.player_props(pid, "short")
    # same code path as pipeline/preview.py storyboard_stills (and the gate)
    cfg, _ = load_project(str(pd.relative_to(Path.cwd()) / "project.json"))
    expected = build_timeline({**cfg, "formats": ["short"]}, estimated_timing(cfg["storyboard"])).props["short"]
    assert out["props"] == expected
    assert out["propsHash"] and out["storyboardHash"]
    assert out["timing"] == "estimated" and "estimated" in out["timingNote"].lower()
    assert (out["fps"], out["durationInFrames"]) == (expected["fps"], expected["durationInFrames"])
    assert (out["width"], out["height"]) == (1080, 1920)
    assert out["productionId"] == pid and out["format"] == "short" and out["inProject"]
    json.dumps(out)                                        # the endpoint must be able to serialise it


def test_scene_frames_cover_the_timeline_in_order(registry, ws_tmp, monkeypatch):
    api, pid, _ = _prod(ws_tmp, monkeypatch)
    out = PP.player_props(pid)
    sc = out["scenes"]
    assert [s["id"] for s in sc] == [s["id"] for s in out["props"]["scenes"]]
    assert sc[0]["startFrame"] == 0 and sc[-1]["endFrame"] == out["durationInFrames"] - 1
    for a, b in zip(sc, sc[1:]):
        assert a["startFrame"] <= a["endFrame"] < b["startFrame"] <= b["endFrame"]


def test_assets_are_served_from_the_studio_file_route(registry, ws_tmp, monkeypatch):
    api, pid, _ = _prod(ws_tmp, monkeypatch)
    out = PP.player_props(pid)
    assert out["staticBase"] == "/files/public"
    paths = {a["path"] for a in out["assets"]}
    theme = out["props"]["theme"]
    assert {theme["logo"]["onDark"], theme["logo"]["mark"]} <= paths
    assert any(p.endswith(".woff2") for p in paths)        # theme fonts are listed too
    for a in out["assets"]:
        assert a["url"] == PP.public_url(a["path"]) and a["url"].startswith("/files/public/")
        assert a["exists"], a["path"]
        from pipeline.api import safe_output_file           # the existing /files/ route accepts every URL
        safe_output_file("public/" + a["path"])
    assert out["missingAssets"] == []


def test_public_url_encodes_like_static_file():
    assert PP.public_url("brands/x/logo mark.svg") == "/files/public/brands/x/logo%20mark.svg"
    assert PP.public_url("a/b#c(1).png") == "/files/public/a/b%23c(1).png"


def test_other_format_and_errors(registry, ws_tmp, monkeypatch):
    api, pid, pd = _prod(ws_tmp, monkeypatch)
    land = PP.player_props(pid, "landscape")              # previewable even if the project renders short only
    assert (land["width"], land["height"]) == (1920, 1080) and not land["inProject"]
    assert land["props"]["format"] == "landscape"
    with pytest.raises(PipelineError):
        PP.player_props(pid, "square")
    (pd / "storyboard.json").unlink()
    with pytest.raises(NotFound):
        PP.player_props(pid)
