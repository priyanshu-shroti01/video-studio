"""Pre-flight checks before render / QA (pipeline/preflight.py). The system readers are monkeypatched: no real
memory pressure, disk or OCR needed."""
import json
import sys

import pytest

from pipeline import preflight as PF
from pipeline.errors import PreflightError


@pytest.fixture
def healthy(monkeypatch, tmp_path):
    """A healthy Mac: plenty of disk + memory, ffmpeg present, a working OCR tool."""
    monkeypatch.setenv("VIDEO_PREFLIGHT", "1")
    monkeypatch.setattr(PF, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(PF, "_mem_ocr_cache", {})
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(PF, "read_disk_free_gb", lambda p: 50.0)
    monkeypatch.setattr(PF, "read_memory", lambda: {"available_mb": 6000.0, "swap_used_mb": 100.0,
                                                    "swap_total_mb": 1024.0})
    monkeypatch.setattr(PF, "which", lambda n: f"/usr/bin/{n}")
    tool = tmp_path / "ocr-abc"
    tool.write_text("")
    monkeypatch.setattr(PF, "ocr_tool", lambda: tool)
    calls = []

    def ocr(exe, img):
        calls.append(img)
        assert img.read_bytes().startswith(b"\x89PNG")
        return True, "", ["OCR"]
    monkeypatch.setattr(PF, "run_ocr", ocr)
    return calls


def test_healthy_machine_passes(healthy):
    rep = PF.preflight("render")
    assert rep.ok and not rep.soft and rep.facts["ocr"] == "ok" and rep.facts["swap_pct"] < 10


def test_skippable_with_env(monkeypatch, healthy):
    monkeypatch.setenv("VIDEO_PREFLIGHT", "0")
    monkeypatch.setattr(PF, "read_disk_free_gb", lambda p: 0.1)
    rep = PF.preflight("render")
    assert rep.skipped and not healthy


def test_disk_low_is_hard(monkeypatch, healthy):
    monkeypatch.setattr(PF, "read_disk_free_gb", lambda p: 1.2)
    with pytest.raises(PreflightError) as ei:
        PF.preflight("render")
    d = ei.value.to_dict()
    assert d["code"] == "PREFLIGHT" and d["action"] == "free-disk"
    assert "1.2 GB" in d["hint"] and "disk" in ei.value.message


def test_disk_tight_is_a_warning(monkeypatch, healthy):
    monkeypatch.setattr(PF, "read_disk_free_gb", lambda p: 3.5)
    logged = []
    rep = PF.preflight("QA", log=lambda m, lvl: logged.append((lvl, m)))
    assert rep.ok and logged and logged[0][0] == "warn" and "3.5 GB" in logged[0][1]


def test_swap_full_and_low_memory_is_hard(monkeypatch, healthy):
    monkeypatch.setattr(PF, "read_memory", lambda: {"available_mb": 700.0, "swap_used_mb": 1900.0,
                                                    "swap_total_mb": 2048.0})
    with pytest.raises(PreflightError) as ei:
        PF.preflight("render")
    assert ei.value.action == "close-apps" and "restart" in ei.value.hint


@pytest.mark.parametrize("mem", [
    {"available_mb": 700.0, "swap_used_mb": 100.0, "swap_total_mb": 1024.0},     # low memory, swap fine
    {"available_mb": 4000.0, "swap_used_mb": 1000.0, "swap_total_mb": 1024.0},   # swap full, memory fine
])
def test_one_memory_signal_alone_is_only_a_warning(monkeypatch, healthy, mem):
    monkeypatch.setattr(PF, "read_memory", lambda: mem)
    rep = PF.preflight("render", log=lambda *a: None)
    assert rep.ok and [p.check for p in rep.soft] == ["memory"]


def test_ocr_failure_is_hard_and_not_cached(monkeypatch, healthy):
    monkeypatch.setattr(PF, "run_ocr", lambda exe, img: (False, "Vision: request failed", []))
    with pytest.raises(PreflightError) as ei:
        PF.preflight("QA")
    assert ei.value.action == "retry" and "text recognition" in ei.value.hint
    assert not (PF.CACHE_DIR / PF.OCR_FILE).exists()


def test_ocr_success_is_cached_for_ten_minutes(monkeypatch, healthy):
    PF.preflight("QA")
    PF.preflight("QA")
    assert len(healthy) == 1
    PF._mem_ocr_cache.clear()                         # a new process reads the on-disk cache
    rep = PF.preflight("QA")
    assert len(healthy) == 1 and rep.facts["ocr"] == "ok (cached)"
    f = PF.CACHE_DIR / PF.OCR_FILE
    d = json.loads(f.read_text())
    f.write_text(json.dumps({**d, "at": d["at"] - PF.OCR_CACHE_S - 1}))
    PF._mem_ocr_cache.clear()
    PF.preflight("QA")
    assert len(healthy) == 2


def test_ocr_skipped_when_not_needed_or_not_macos(monkeypatch, healthy):
    PF.preflight("render", need_ocr=False)
    monkeypatch.setattr(sys, "platform", "linux")
    PF.preflight("render")
    assert not healthy


def test_ocr_tool_not_built_yet(monkeypatch, healthy):
    monkeypatch.setattr(PF, "ocr_tool", lambda: None)
    rep = PF.preflight("render", log=lambda *a: None)
    assert rep.ok and rep.soft[0].check == "ocr"
    monkeypatch.setattr(PF, "which", lambda n: None if n == "swiftc" else f"/usr/bin/{n}")
    with pytest.raises(PreflightError) as ei:
        PF.preflight("render")
    assert "xcode-select" in ei.value.hint


def test_missing_ffmpeg_is_hard(monkeypatch, healthy):
    monkeypatch.setattr(PF, "which", lambda n: None if n == "ffprobe" else f"/usr/bin/{n}")
    with pytest.raises(PreflightError) as ei:
        PF.preflight("render")
    assert "brew install ffmpeg" in ei.value.hint


def test_several_hard_problems_are_all_named(monkeypatch, healthy):
    monkeypatch.setattr(PF, "read_disk_free_gb", lambda p: 0.5)
    monkeypatch.setattr(PF, "which", lambda n: None if n == "ffmpeg" else f"/usr/bin/{n}")
    with pytest.raises(PreflightError) as ei:
        PF.preflight("render")
    assert "disk" in ei.value.message and "ffmpeg" in ei.value.message
    assert ei.value.action == "free-disk" and "brew install ffmpeg" in ei.value.hint


def test_probe_png_is_a_valid_png():
    b = PF.probe_png()
    assert b.startswith(b"\x89PNG\r\n\x1a\n") and b.endswith(b"IEND\xaeB`\x82")


def test_real_readers_are_fast_and_safe(monkeypatch, tmp_path):
    """The real system readers on this machine (whatever it is): no exception, no slow call."""
    monkeypatch.setenv("VIDEO_PREFLIGHT", "1")
    rep = PF.check("render", out_dir=tmp_path, need_ocr=False)
    assert rep.seconds < 2.0 and "disk_free_gb" in rep.facts
