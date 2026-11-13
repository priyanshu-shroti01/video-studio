"""End-to-end: real Remotion + FFmpeg render through every stage, with the offline mock TTS so the
suite never depends on Microsoft's live service. ~1-2 minutes."""
import json
import shutil
import threading
import time
from pathlib import Path

import pytest

from pipeline.config import config_hash, load_project
from pipeline.errors import Cancelled
from pipeline.paths import OUTPUT_DIR, ROOT
from pipeline.runner import JobRunner

pytestmark = pytest.mark.e2e

STORY = {"scenes": [
    {"id": "hook", "purpose": "hook", "narration": "Stop overpaying for hosting.",
     "blocks": [{"type": "headline", "size": "xl", "words": "Stop overpaying for hosting.", "tones": {"hosting.": "brand"}}]},
    {"id": "cta", "purpose": "cta", "narration": "Launch today at shrotihost.in.",
     "blocks": [{"type": "logo", "variant": "onDark", "width": 700},
                {"type": "cta", "text": "Launch today", "url": "shrotihost.in", "urlAt": "@word:shrotihost"}]}]}


@pytest.fixture
def project(tmp_path):
    name = f"e2etest-{int(time.time() * 1000)}"
    sb = ROOT / "projects" / f"{name}.storyboard.json"
    pj = ROOT / "projects" / f"{name}.json"
    sb.write_text(json.dumps(STORY))
    pj.write_text(json.dumps({"name": name, "brand": "shrotihost", "preset": "shorts", "formats": ["short"],
                              "storyboard": f"projects/{sb.name}",
                              "voice": {"provider": "mock", "voice": "mock"},
                              "audio": {"music": "audio/music/test-bed.wav"},
                              "render": {"chunkFrames": 60, "concurrency": 2}}))
    yield pj
    sb.unlink(missing_ok=True)
    pj.unlink(missing_ok=True)


def _job(registry, pj, force=False):
    cfg, _ = load_project(pj.relative_to(ROOT))
    return registry.create(cfg["name"], config_hash(cfg), cfg, None, OUTPUT_DIR, force=force)


def test_full_pipeline_cancel_and_resume(registry, project):
    job = _job(registry, project)
    jid = job["id"]
    try:
        runner = JobRunner(registry, jid, echo=lambda m: None)
        err = {}

        def go():
            try:
                runner.run()
            except Exception as e:  # noqa: BLE001
                err["e"] = e
        t = threading.Thread(target=go)
        t.start()
        # cancel as soon as the first chunk is on disk (mid-render)
        chunks = Path(job["output_dir"]) / "work" / "chunks"
        deadline = time.time() + 240
        while time.time() < deadline and not list(chunks.glob("short-000000-*.mp4")):
            time.sleep(0.5)
        registry.request_cancel(jid)
        t.join(240)
        assert isinstance(err.get("e"), Cancelled), err
        assert registry.get(jid)["state"] == "CANCELLED"

        # resume: TTS + timeline come from cache, rendered chunks are reused
        res = JobRunner(registry, jid, echo=lambda m: None).run()
        assert res["state"] == "COMPLETED" and res["qa_status"] in ("PASS", "WARN")
        rr = json.loads((Path(job["output_dir"]) / "reports/render-report.json").read_text())
        assert rr["formats"][0]["chunks"][0]["reused"] is True
        out = Path(job["output_dir"])
        for f in ("video/final-short.mp4", "audio/voiceover.wav", "audio/mixed-audio.wav", "captions/captions.srt",
                  "captions/captions-short.ass", "reports/qa-report.json", "reports/QA_REPORT.md",
                  "previews/short/contact-sheet.jpg", "publishing/thumbnail.png", "assets/manifest.json",
                  "metadata/storyboard.json", "metadata/job-manifest.json"):
            assert (out / f).exists(), f
        qa = json.loads((out / "reports/qa-report.json").read_text())
        assert not [c for r in qa["formats"] for c in r["checks"] if c["status"] == "FAIL" and c["critical"]]

        # completed outputs are never overwritten
        with pytest.raises(Exception):
            JobRunner(registry, jid, echo=lambda m: None).run()
        # an identical second job is refused unless forced
        with pytest.raises(Exception):
            _job(registry, project)
    finally:
        shutil.rmtree(Path(job["output_dir"]), ignore_errors=True)
