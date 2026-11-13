"""MCP server: tool registration + annotations, refusals, stdout hygiene. Keyword research: only generic
seed phrases leave the machine, queries are visible, cache works, offline works."""
import asyncio
import json
import urllib.error
from urllib.parse import parse_qs, urlparse

import pytest

from _social_fixtures import approve, make_production, sw  # noqa: F401
from pipeline.social import keywords as K
from pipeline.social import service

EXPECTED = {
    "list_publishable": dict(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    "plan_platforms": dict(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    "publication_status": dict(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    "draft_metadata": dict(readOnlyHint=False, destructiveHint=False, openWorldHint=False),
    "keyword_research": dict(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
    "publish_youtube": dict(readOnlyHint=False, destructiveHint=True, openWorldHint=True),
    "publish_instagram_reel": dict(readOnlyHint=False, destructiveHint=True, openWorldHint=True),
}


def _call(srv, name, args):
    r = asyncio.run(srv.call_tool(name, args))
    return json.loads(r.content[0].text)


def test_tools_registered_with_annotations():
    from pipeline.social.mcp_server import build_server
    tools = {t.name: t for t in asyncio.run(build_server().list_tools())}
    assert set(tools) == set(EXPECTED)
    for name, want in EXPECTED.items():
        got = tools[name].annotations.model_dump(by_alias=True, exclude_none=True)
        assert {k: got[k] for k in want} == want, name
    for name in ("publish_youtube", "publish_instagram_reel"):
        props = tools[name].input_schema["properties"]
        assert {"production_id", "actor", "format"} <= set(props) and "actor" in tools[name].input_schema["required"]
        assert "confirm" not in props                                   # confirmation is the user's explicit request
    assert "brand_id" in tools["list_publishable"].input_schema["properties"]


def test_mcp_draft_refused_after_approval_and_publish_refused_without_setup(sw, capsys):
    from pipeline.social.mcp_server import build_server
    srv = build_server()
    pid, out = make_production(sw)
    assert _call(srv, "draft_metadata", {"production_id": pid, "provider": "template"})["ok"]
    approve(sw, pid)
    r = _call(srv, "draft_metadata", {"production_id": pid, "provider": "template"})
    assert not r["ok"] and "approval would be invalidated: request changes first" in r["error"]["message"]
    r = _call(srv, "publish_youtube", {"production_id": pid, "format": "short", "actor": "Test Person"})
    assert not r["ok"] and r["error"]["code"] == "PUBLISH_NOT_CONFIGURED"     # no credentials for this brand
    r = _call(srv, "publish_instagram_reel", {"production_id": pid, "actor": "Test Person", "brand_id": "acme-demo"})
    assert not r["ok"] and r["error"]["code"] == "PUBLISH_ACCOUNT_MISMATCH"
    listed = _call(srv, "list_publishable", {})
    groups = {g["brand"]: g for g in listed["brands"]}
    assert pid in {p["id"] for p in groups["shrotihost"]["productions"]}
    assert groups["shrotihost"]["accounts"]["youtube"]["expected_account"]
    plan = _call(srv, "plan_platforms", {"production_id": pid})
    assert {d["platform"] for d in plan["plans"]["short"]["destinations"]} == {"youtube", "instagram"}
    assert capsys.readouterr().out == ""                                   # stdout is the MCP protocol


def test_keyword_research_sends_only_generic_seeds(sw):
    sent = []

    def http(url):
        sent.append(url)
        q = parse_qs(urlparse(url).query)["q"][0]
        return 200, f'window.google.ac.h(["{q}",[["{q} plans",0],["{q} for students",0]],{{}}])'.encode()
    pid, _ = make_production(sw)
    res = service.keyword_research(production_id=pid, prod=sw.prod, http=http,
                                   extra_seeds=["wordpress for students", "Priya's brief: ₹39 plan", "me@example.com"])
    brand_seeds = K.seeds_for("shrotihost", "WordPress Hosting")
    qs = [parse_qs(urlparse(u).query) for u in sent]
    assert [q["q"][0] for q in qs] == brand_seeds + ["wordpress for students"]
    assert all(q["client"] == ["youtube"] and q["hl"] == ["en"] and q["gl"] == ["in"] for q in qs)
    assert [q["url"] for q in res["queries"]] == sent                     # exactly what left the machine
    blob = " ".join(sent).lower()
    for private in ("new to wordpress", "shouldn", "website beginners", "conversions", "39", "example.com", "priya"):
        assert private not in blob
    assert len(res["rejected_seeds"]) == 2 and res["ranked"] and not res["offline"]
    assert any("not a ranking guarantee" in n for n in res["notes"]) and any("Instagram" in n for n in res["notes"])
    again = service.keyword_research(production_id=pid, prod=sw.prod, http=http)
    assert again["cached"] == len(brand_seeds) and len(sent) == len(brand_seeds) + 1     # 24 h cache


def test_keyword_research_offline_and_api_key_redacted(sw):
    def offline(url):
        raise urllib.error.URLError("no network")
    res = K.research("shrotihost", product="WordPress Hosting", http=offline)
    assert res["offline"] and all(v == [] for v in res["suggestions"].values()) and res["ranked"] == []
    calls = []

    def api(url):
        calls.append(url)
        if "suggestqueries" in url:
            raise urllib.error.URLError("blocked")
        if "/search" in url:
            return 200, json.dumps({"items": [{"id": {"videoId": "v1"}}]}).encode()
        return 200, json.dumps({"items": [{"snippet": {"title": "T", "channelTitle": "C", "tags": ["x"]},
                                           "statistics": {"viewCount": "10"}}]}).encode()
    res = K.research("shrotihost", product="WordPress Hosting", http=api, use_api=True, api_key="AIza-SECRET",
                     max_api_seeds=1)
    assert "AIza-SECRET" not in json.dumps(res) and any("key=REDACTED" in q["url"] for q in res["queries"])
    assert res["quota_units"]["search_queries_bucket"] == 1 and list(res["api"].values())[0][0]["views"] == 10
    assert all("AIza-SECRET" not in f.read_text() for f in (sw.ws / "cache/keywords").glob("*.json"))


def test_generic_seed_filter():
    assert K.generic_seed("WordPress Hosting India") == "wordpress hosting india"
    for bad in ("hosting at ₹39", "https://x.in", "a", "my client mr sharma wants seven words now", "me@x.com"):
        assert K.generic_seed(bad) is None


@pytest.mark.parametrize("brand", ["shrotihost"])
def test_brand_profile_drives_seeds(brand):
    seeds = K.seeds_for(brand)
    assert seeds and all(K.generic_seed(s) == s for s in seeds)
