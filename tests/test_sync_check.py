from pipeline.sync_check import STATIC_FAIL, evaluate


def words(spec):
    """spec: [(text, start)] -> words of 0.3 s each"""
    return [{"text": t, "start": s, "end": s + 0.3} for t, s in spec]


def scene(blocks, start=0.0, end=10.0, sid="s"):
    return {"id": sid, "start": start, "end": end, "blocks": blocks}


def test_voice_over_frozen_screen_fails():
    # v0.3 regression: one entrance, then the voice lists features over a frozen screen
    w = words([("One-click", 1.0), ("install.", 1.6), ("SSL.", 2.4), ("Cache.", 3.4), ("Done.", 4.4), ("Launch.", 5.4)])
    r = evaluate([scene([{"type": "browser", "at": 0.9, "loadUntil": 1.2}])], w, 6.0)
    assert r["status"] == "FAIL" and r["longest_static_s"] > STATIC_FAIL


def test_beats_on_spoken_words_pass():
    w = words([("One-click", 1.0), ("install.", 1.6), ("SSL.", 2.4), ("Cache.", 3.4), ("Done.", 4.4)])
    items = [{"text": x, "at": t} for x, t in (("One-click install", 1.0), ("Free SSL", 2.4), ("LiteSpeed Cache", 3.4))]
    r = evaluate([scene([{"type": "checklist", "at": 0.9, "items": items, "badge": {"text": "Live", "at": 4.4}}], end=5.0)], w, 5.0)
    assert r["status"] == "PASS", r


def test_price_shown_before_it_is_spoken_fails():
    w = words([("Plans", 0.2), ("start", 0.6), ("at", 1.0), ("69", 2.5), ("rupees", 2.9)])
    rows = [{"label": "WP Starter", "value": "₹69/month", "at": 0.1}]
    r = evaluate([scene([{"type": "compare-rows", "rows": rows, "at": 0.1}], end=3.5)], w, 3.5)
    assert r["status"] == "FAIL" and r["early_numbers"][0]["number"] == "69"


def test_count_up_landing_on_the_spoken_number_passes():
    w = words([("starting", 0.5), ("at", 1.0), ("69", 1.5), ("rupees", 1.9)])
    r = evaluate([scene([{"type": "price", "amount": 69, "at": 0.4, "countEnd": 1.7}], end=2.5)], w, 2.5)
    assert not r["early_numbers"]


def test_plan_catalog_is_context_not_an_early_claim():
    w = words([("Pick", 0.3), ("Business", 0.8), ("at", 1.2), ("119", 1.6)])
    plans = [{"name": "Starter", "price": "₹69"}, {"name": "Business", "price": "₹119"}]
    r = evaluate([scene([{"type": "plans", "plans": plans, "at": 0.1, "emphasizeAt": 0.8}], end=2.2)], w, 2.2)
    assert not r["early_numbers"]
