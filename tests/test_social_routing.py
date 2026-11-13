"""Platform routing: decided from the real file; landscape never goes to Instagram; Shorts/Reels limits."""
from pipeline.social import routing


def _info(w, h, dur, size=20_000_000, fps=30.0):
    return {"width": w, "height": h, "aspect": w / h, "duration_s": dur, "fps": fps, "video_codec": "h264",
            "audio_codec": "aac", "audio_sample_rate": 48000, "size_bytes": size, "orientation": routing.orientation(w, h)}


def _platforms(plan):
    return {d["platform"]: d for d in plan["destinations"]}


def test_landscape_never_goes_to_instagram():
    for dur in (20, 60, 600):
        pl = routing.plan(_info(1920, 1080, dur), "landscape")
        d = _platforms(pl)
        assert set(d) == {"youtube"}
        assert d["youtube"]["kind"] == "video" and d["youtube"].get("chapters")
        rej = pl["rejected"][0]
        assert rej["platform"] == "instagram" and "9:16" in rej["reasons"][0]
        assert any("9:16" in s and "short" in s for s in pl["suggestions"])


def test_vertical_up_to_180s_is_short_and_reel():
    for dur in (3.5, 35, 180):
        d = _platforms(routing.plan(_info(1080, 1920, dur)))
        assert d["youtube"]["kind"] == "short" and d["instagram"]["kind"] == "reel"


def test_vertical_over_180s_is_long_form_youtube_and_reel_until_15_min():
    pl = routing.plan(_info(1080, 1920, 240))
    d = _platforms(pl)
    assert d["youtube"]["kind"] == "video" and "too long for Shorts" in d["youtube"]["reason"]
    assert "instagram" in d and any("180" in s for s in pl["suggestions"])
    pl = routing.plan(_info(1080, 1920, 901))
    assert "instagram" not in _platforms(pl) and "15 min" in pl["rejected"][0]["reasons"][0]


def test_instagram_limits_size_fps_min_duration_and_square():
    assert routing.instagram_problems(_info(1080, 1920, 2.0))[0].startswith("2.0 s is shorter")
    assert "300 MB" in routing.instagram_problems(_info(1080, 1920, 30, size=301 * 1024 * 1024))[0]
    assert "fps" in routing.instagram_problems(_info(1080, 1920, 30, fps=15))[0]
    sq = routing.plan(_info(1080, 1080, 30))
    assert _platforms(sq)["youtube"]["kind"] == "short" and "instagram" not in _platforms(sq)


def test_routing_reads_the_actual_file_not_the_format_name(tmp_path, make_video):
    v = make_video("final-short.mp4", 640, 360, 4.0)          # named "short" but actually landscape
    pl = routing.plan_file(v, "short")
    assert pl["video"]["orientation"] == "landscape-16:9" and "instagram" not in _platforms(pl)
    v = make_video("vert.mp4", 360, 640, 4.0)
    pl = routing.plan_file(v)
    assert pl["video"]["orientation"] == "vertical-9:16" and set(_platforms(pl)) == {"youtube", "instagram"}
