"""Storyboard preview gate + human preview approval before rendering."""
import json
from pathlib import Path

import numpy as np
import pytest

from pipeline import preview_gate as G
from pipeline.errors import PipelineError


def test_invented_label_and_unverified_number_detection():
    assert G.LABEL_NUMBER.search("Browser: 39 rupees")
    assert not G.LABEL_NUMBER.search("WordPress hosting · billed monthly")
    nums = G.verified_numbers("shrotihost")
    assert "69" in nums and "699" in nums and "39" not in nums


def test_density_separates_empty_from_content():
    empty = np.full((480, 270), 12.0)
    busy = empty.copy()
    busy[100:300:6, 30:240] = 230                      # many text-like strokes
    assert G.density(empty) < G.EMPTY_DENSITY < G.density(busy)


@pytest.fixture
def ws_tmp():
    """Scratch dir INSIDE the workspace (paths outside it are rejected by design)."""
    import shutil
    import uuid
    from pipeline.paths import TMP_DIR
    d = TMP_DIR / f"test-productions-{uuid.uuid4().hex[:8]}"
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _prod_with_preview(tmp_path, monkeypatch):
    """A production whose preview + gate exist (gate computed from a stub so no render is needed)."""
    import pipeline.productions as P
    from pipeline import api
    monkeypatch.setattr(P, "PRODUCTIONS_DIR", tmp_path)
    brief = {"brand": "Shroti Host", "product": "WordPress Hosting", "format": "short"}
    p = api.create_production("shrotihost", brief)
    sb = json.loads(Path("tests/fixtures/gate-storyboard.json").read_text())
    proj = json.loads(Path("tests/fixtures/gate-project.json").read_text())
    proj["name"] = "gate-test"
    api.save_storyboard(p["id"], sb, project=proj)
    pd = Path(api.Productions().get(p["id"])["dir"])
    (pd / "preview").mkdir(exist_ok=True)
    return api, p["id"], pd


def _write_gate(api, pid, pd, status):
    p = api.Productions().get(pid)
    (pd / "preview/gate.json").write_text(json.dumps({"status": status, "storyboard_hash": api.storyboard_hash(p),
                                                       "checks": [{"id": "x", "status": status, "detail": "d"}]}))


def test_render_refused_without_human_preview_approval(registry, ws_tmp, monkeypatch):
    api, pid, pd = _prod_with_preview(ws_tmp, monkeypatch)
    with pytest.raises(PipelineError) as e:
        api.start_render(pid)
    assert "preview has not been approved" in e.value.message


def test_preview_approval_requires_passing_gate_and_matching_storyboard(registry, ws_tmp, monkeypatch):
    api, pid, pd = _prod_with_preview(ws_tmp, monkeypatch)
    _write_gate(api, pid, pd, "FAIL")
    with pytest.raises(PipelineError):
        api.approve_preview(pid, "Reviewer")              # failed gate cannot be approved
    _write_gate(api, pid, pd, "WARN")
    with pytest.raises(PipelineError):
        api.approve_preview(pid, "")                      # needs a named person
    api.approve_preview(pid, "Reviewer", "looked at the contact sheet")
    assert api._preview_approved(api._reg(), api.Productions().get(pid))
    sb = json.loads((pd / "storyboard.json").read_text())
    sb["scenes"][0]["narration"] = "New to WordPress? Your first site starts here."
    api.save_storyboard(pid, sb)                          # any storyboard change voids the preview approval
    assert not api._preview_approved(api._reg(), api.Productions().get(pid))


def test_v03_llm_demo_storyboard_fails_the_gate():
    """Regression: the gate must reject the storyboard that produced the unacceptable v0.3.0 demo."""
    pid = "P20261113-205715-f428a"
    d = next((p for p in (Path("output/productions") / pid, Path("output/_archive/productions") / pid)
              if (p / "preview/gate.json").exists()), Path("output/productions") / pid)   # it may have been archived
    if not (d / "preview/gate.json").exists():
        pytest.skip("v0.3.0 demo artifacts not present")
    rep = json.loads((d / "preview/gate.json").read_text())
    failed = {c["id"] for c in rep["checks"] if c["status"] == "FAIL"}
    assert {"preview.empty_scenes", "storyboard.invented_labels", "storyboard.numbers_verified"} <= failed


def test_gate_hash_is_the_saved_file_not_the_loaded_storyboard(registry, ws_tmp, monkeypatch):
    """Loading fills derived values (e.g. footage aspect/duration); the gate must still hash what approval checks."""
    api, pid, pd = _prod_with_preview(ws_tmp, monkeypatch)
    p = api.Productions().get(pid)
    h = G.saved_storyboard_hash(pd)
    assert h == api.storyboard_hash(p)
    sb = json.loads((pd / "storyboard.json").read_text())
    loaded = {**sb, "scenes": [{**s, "derived": True} for s in sb["scenes"]]}   # what a loader may add in memory
    assert G.sha256_json({"sb": loaded, "project": G.sha256_file(pd / "project.json")}) != h
    assert G.saved_storyboard_hash(pd) == h                                     # the file, not memory, decides
