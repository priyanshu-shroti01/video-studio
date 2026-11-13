"""Dashboard service: multi-brand overview, brand filter and the human-attention queue."""
from pipeline import api


def test_dashboard_lists_every_brand_without_secret_contents():
    d = api.dashboard()
    ids = {b["id"] for b in d["brands"]}
    assert "shrotihost" in ids and "_defaults" not in ids
    assert "acme-demo" not in ids                                     # hidden test brand: not on the dashboard
    assert "acme-demo" in {b["id"] for b in api.brand_overview(include_hidden=True)}
    for b in d["brands"]:
        assert set(b["accounts"]) == {"youtube", "instagram"} and all(isinstance(v, bool) for v in b["accounts"].values())


def test_brand_filter_scopes_productions_jobs_and_attention():
    d = api.dashboard("acme-demo")
    assert d["brand"] == "acme-demo"
    assert all(p["brand"] == "acme-demo" for p in d["productions"]["recent"])
    assert all(a["brand"] == "acme-demo" for a in d["attention"])
    assert all(j["brand"] == "acme-demo" for j in d["jobs"]["recent"])


def test_attention_is_sorted_most_urgent_first():
    pr = [a["priority"] for a in api.dashboard()["attention"]]
    assert pr == sorted(pr)


def test_hidden_test_brand_is_usable_by_exact_id_only():
    from pipeline.brands import resolve_brand, visible_brands
    import pytest
    assert "acme-demo" not in visible_brands()
    assert resolve_brand("acme-demo") == "acme-demo"                  # tests and explicit use still work
    with pytest.raises(Exception):
        resolve_brand("ACME Demo")                                    # but a brief can't land on it by name
