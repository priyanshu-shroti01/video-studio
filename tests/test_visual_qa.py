"""Visual QA: layout-manifest checks, OCR price/URL matching, template-label detection."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline.qa import FAIL, PASS
from pipeline.visual_qa import checks as V
from pipeline.visual_qa.ocr import TextBox, best_match, ocr, price_match

ROOT = Path(__file__).resolve().parent.parent


def _box(t):
    return [TextBox(t, 1.0, 10, 10, 300, 60)]


@pytest.mark.parametrize("expected,read,ok", [
    ("₹79", "279", True), ("₹79", "₴79", True), ("₹49/mo", "·49 (mо", True), ("₹49", "R49", True),
    ("₹49", "₴99", False), ("₹49", "299", False), ("₹49", "₴249", False), ("₹49", "2249", False)])
def test_price_matching_is_strict_on_digits_but_tolerates_rupee_misreads(expected, read, ok):
    assert price_match(expected, _box(read), (0, 0, 400, 100))[0] is ok


def test_url_match_exact_and_multiline():
    boxes = [TextBox("Launch your site", 1, 10, 10, 300, 40), TextBox("today", 1, 10, 60, 120, 40)]
    assert best_match("Launch your site today", boxes, (0, 0, 400, 120))[0] == 1.0
    assert best_match("shrotihost.in", _box("shrotihost.in"))[0] == 1.0
    assert best_match("shrotihost.in", _box("shrotihost.com"))[0] < 1.0


def _manifest(**over):
    m = {"width": 1080, "height": 1920, "safeArea": {"x": 70, "y": 130, "w": 940, "h": 1060},
         "captionBand": {"x": 108, "y": 1193, "w": 864, "h": 209},
         "scenes": [{"id": "s1", "start": 0, "end": 3, "blocks": [
             {"type": "text", "bbox": {"x": 100, "y": 300, "w": 800, "h": 200}, "visible": {"from": 0.1, "to": 3},
              "texts": [{"text": "Hello", "overflow": False, "estWidth": 100, "maxWidth": 800}], "logos": []}]}],
         "watermark": None, "brandBar": None}
    m.update(over)
    return m


def _status(cs, cid):
    return next(c.status for c in cs if c.id == cid)


def test_static_checks_pass_on_clean_layout():
    assert all(c.status == PASS for c in V.static_checks(_manifest()))


def test_static_checks_catch_overflow_caption_band_and_distorted_logo():
    m = _manifest()
    b = m["scenes"][0]["blocks"][0]
    b["texts"][0].update(overflow=True, estWidth=900)
    b["bbox"]["y"] = 1150                                     # into the caption band
    b["logos"] = [{"variant": "onDark", "aspect": 4.2, "expectedAspect": 5.0, "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}]
    cs = V.static_checks(m)
    for cid in ("layout.text_overflow", "layout.caption_band", "brand.logo_aspect"):
        assert _status(cs, cid) == FAIL, cid


def test_duplicate_branding_detected():
    m = _manifest(watermark={"policy": "brand", "bbox": {"x": 40, "y": 130, "w": 80, "h": 40},
                             "visibleRanges": [[0, 3]]})
    m["scenes"][0]["blocks"][0]["logos"] = [{"variant": "onDark", "aspect": 5, "expectedAspect": 5,
                                             "bbox": {"x": 300, "y": 300, "w": 500, "h": 100}}]
    assert _status(V.static_checks(m), "brand.no_duplicate_branding") == FAIL


@pytest.mark.skipif(not (shutil.which("swiftc") and shutil.which("qlmanage")), reason="needs macOS Vision + Quick Look")
def test_ocr_reads_real_text_and_template_labels(tmp_path):
    svg = tmp_path / "t.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="400"><rect width="1080" height="400" '
                   'fill="#0a0a0f"/><text x="60" y="160" fill="#fff" font-family="Helvetica" font-size="60">'
                   'shrotihost.in</text><text x="60" y="290" fill="#fff" font-family="Helvetica" font-size="60">'
                   'Made with TEMPLATE</text></svg>')
    subprocess.run(["qlmanage", "-t", "-s", "1080", "-o", str(tmp_path), str(svg)], capture_output=True, check=True)
    img = tmp_path / "t.svg.png"
    items = ocr([img])[str(img)]["items"]
    assert best_match("shrotihost.in", items)[0] == 1.0
    assert any(V.FORBIDDEN_LABELS.search(b.text) for b in items)


def test_layout_manifest_cli_matches_props():
    props = ROOT / "src/engine/fixtures/sample-v2-short.json"
    m = V.layout_manifest(props)
    p = json.loads(props.read_text())
    assert m["contractVersion"] == 2 and m["width"] == 1080 and len(m["scenes"]) == len(p["scenes"])


def test_ocr_engine_errors_fail_qa_instead_of_reading_as_empty_frames():
    ok = {"a.png": {"items": [], "error": None}, "b.png": {"items": [], "error": None}}
    bad = {"a.png": {"items": [], "error": "e5rtError(... 13)"}, "b.png": {"items": [], "error": None}}
    assert V.ocr_engine_check(ok).status == PASS
    c = V.ocr_engine_check(bad)
    assert c.status == FAIL and c.critical and "1/2" in c.detail


def test_ocr_retries_failed_frames_once(monkeypatch, tmp_path):
    import pipeline.visual_qa.ocr as O
    calls = []

    class R:
        def __init__(self, out): self.returncode, self.stdout, self.stderr = 0, out, ""

    def fake_run(cmd, **kw):
        calls.append(cmd[1:])
        err = len(calls) == 1
        return R("\n".join(json.dumps({"file": f, "width": 1, "height": 1, **({"error": "e5rt"} if err else {"items": []})})
                           for f in cmd[1:]))
    monkeypatch.setattr(O, "ocr_bin", lambda: Path("/bin/true"))
    monkeypatch.setattr(O.subprocess, "run", fake_run)
    monkeypatch.setattr(O.time, "sleep", lambda s: None)
    out = O.ocr([tmp_path / "a.png"])
    assert len(calls) == 2 and out[str(tmp_path / "a.png")]["error"] is None
