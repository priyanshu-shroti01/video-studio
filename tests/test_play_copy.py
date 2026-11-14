"""In-app play copies: same H.264 picture, Opus audio (VS Code's browser has no AAC decoder)."""
import json
import subprocess

from pipeline.play_copy import play_copy


def _streams(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name", "-of", "json", str(p)],
                         capture_output=True, text=True, check=True).stdout
    return {s["codec_type"]: s["codec_name"] for s in json.loads(out)["streams"]}


def test_play_copy_keeps_the_picture_and_makes_the_audio_opus(make_video, tmp_path):
    src = make_video("final-short.mp4", 320, 568, 1.0)
    assert _streams(src) == {"video": "h264", "audio": "aac"}
    c = play_copy(src, play_dir=tmp_path / "_play")
    assert c and c.parent == tmp_path / "_play" and _streams(c) == {"video": "h264", "audio": "opus"}
    v = lambda p: subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-map", "0:v", "-c", "copy", "-f", "md5", "-"],  # noqa: E731
                                 capture_output=True, text=True, check=True).stdout
    assert v(src) == v(c)                                  # the picture is copied byte for byte
    mtime = c.stat().st_mtime_ns
    assert play_copy(src, play_dir=tmp_path / "_play") == c and c.stat().st_mtime_ns == mtime   # cached


def test_play_copy_without_audio_and_missing_files(make_video, tmp_path):
    silent = make_video("silent.mp4", 320, 568, 1.0, audio=False)
    c = play_copy(silent, play_dir=tmp_path / "_play")
    assert c and _streams(c) == {"video": "h264"}
    assert play_copy(tmp_path / "nope.mp4", play_dir=tmp_path / "_play") is None
