import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import procs


@pytest.fixture(autouse=True)
def _private_video_out(tmp_path, monkeypatch):
    """No test may touch the real video-out/ (an archive test once emptied it via the server's refresh)."""
    from pipeline import video_out as VO
    d = tmp_path / "video-out"
    monkeypatch.setenv("VIDEO_PIPELINE_VIDEO_OUT", str(d))          # subprocesses (CLI tests) inherit this
    monkeypatch.setattr(VO, "OUT", d)
    monkeypatch.setattr(VO, "INDEX", d / ".index.json")


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """A private SQLite registry per test (never touches .pipeline/registry.db)."""
    monkeypatch.setenv("VIDEO_PIPELINE_DB", str(tmp_path / "registry.db"))
    from pipeline.jobs import Registry
    return Registry()


@pytest.fixture
def no_sleep(monkeypatch):
    calls = []
    monkeypatch.setattr(procs, "_backoff_sleep", lambda s: calls.append(s))
    return calls


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture
def make_video(tmp_path):
    """make_video(name, w, h, seconds, audio=True, color=None) -> Path (H.264/AAC MP4)."""
    def _make(name="v.mp4", w=1080, h=1920, seconds=2.0, audio=True, color=None, fps=30):
        out = tmp_path / name
        src = f"color=c={color}:s={w}x{h}:r={fps}:d={seconds}" if color else f"testsrc2=s={w}x{h}:r={fps}:d={seconds}"
        args = ["-f", "lavfi", "-i", src]
        if audio:
            args += ["-f", "lavfi", "-i", f"sine=f=440:d={seconds}:r=48000"]
        args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast"]
        if audio:
            args += ["-c:a", "aac", "-af", "volume=0.3", "-shortest"]
        ff(*args, str(out))
        return out
    return _make


@pytest.fixture
def make_tone(tmp_path):
    def _make(name="t.wav", seconds=2.0, freq=440, volume=0.3, codec="pcm_s16le", layout="stereo"):
        out = tmp_path / name
        ff("-f", "lavfi", "-i", f"sine=f={freq}:d={seconds}:r=48000", "-af",
           f"volume={volume},aformat=channel_layouts={layout}", "-c:a", codec, str(out))
        return out
    return _make


def pytest_collection_modifyitems(config, items):
    if not shutil.which("ffmpeg"):
        skip = pytest.mark.skip(reason="ffmpeg not on PATH")
        for it in items:
            it.add_marker(skip)
