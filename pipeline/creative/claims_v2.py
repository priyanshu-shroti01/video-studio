"""Fact check of a creative storyboard with pipeline.intelligence.claims, extended to every block type (the
intelligence package only extracts v1 block texts)."""
from __future__ import annotations

from ..intelligence.claims import Verifier, block_texts as v1_texts, summarize
from ..intelligence.facts import FactBase


def block_texts(b: dict) -> list[tuple[str, str]]:
    ty, out = b.get("type"), []

    def add(path, *parts):
        s = " ".join(str(p) for p in parts if p not in (None, "", True, False))
        if s.strip():
            out.append((path, s))

    if ty == "kinetic-text":
        w = b.get("words")
        add("words", w if isinstance(w, str) else " ".join(x.get("text", "") for x in w or []))
    elif ty == "counter":
        add("counter", f"{b.get('prefix', '')}{b.get('to')}{b.get('suffix', '')}", b.get("label"))
    elif ty == "price-compare":
        add("title", b.get("title"))
        for i, r in enumerate(b.get("rows", [])):
            for j, v in enumerate(r.get("values", [])):
                col = (b.get("columns") or [""] * (j + 1))[j] if j < len(b.get("columns", [])) else ""
                add(f"rows[{i}].values[{j}]", r.get("label"),
                    f"{col} plan" if col and not col.lower().startswith(("monthly", "yearly", "6 ")) else col, v)
        add("winnerLabel", b.get("winnerLabel"))
    elif ty == "feature-compare":
        add("title", b.get("title"))
        for j, c in enumerate(b.get("columns", [])):
            add(f"columns[{j}]", c)
        for i, r in enumerate(b.get("rows", [])):
            for j, v in enumerate(r.get("values", [])):
                add(f"rows[{i}].values[{j}]", r.get("label"), "—", v if isinstance(v, str) else "")
    elif ty == "terminal":
        add("title", b.get("title"))
        for i, ln in enumerate(b.get("lines", [])):
            add(f"lines[{i}]", ln.get("text"))
    elif ty == "dashboard":
        add("title", b.get("title"))
        add("nav", " · ".join(b.get("nav", [])))
        for i, s in enumerate(b.get("stats", [])):
            add(f"stats[{i}]", f"{s.get('label')}: {s.get('value')}", s.get("delta"))
    elif ty == "device":
        sc = b.get("screen") or {}
        add("screen", sc.get("title"), sc.get("subtitle"), " · ".join(sc.get("rows", [])), sc.get("button"))
    elif ty == "progress":
        add("title", b.get("title"))
        for i, s in enumerate(b.get("steps", [])):
            add(f"steps[{i}]", s.get("label"))
    elif ty == "scroll-demo":
        add("url", b.get("url"))
        for i, s in enumerate(b.get("sections", [])):
            add(f"sections[{i}]", s.get("title"), (s.get("text") or "").replace("|", ","))
    elif ty == "chart":
        add("title", b.get("title"))
    elif ty == "logo-sting":
        add("tagline", b.get("tagline"))
    elif ty == "outro":
        add("url", b.get("url")); add("cta", b.get("cta")); add("tagline", b.get("tagline"))
    elif ty == "plan-card":
        add("price", f"{b.get('name')} plan {b.get('currency', '')}{b.get('price')}{b.get('period', '')}", b.get("billing"))
        add("badge", f"{b.get('name')} plan", b.get("badge")) if b.get("badge") else None
        for i, f in enumerate(b.get("features", [])):
            add(f"features[{i}]", f.get("text"))
        add("ctaLabel", b.get("ctaLabel"))
    elif ty == "install-flow":
        add("app", b.get("app")); add("title", b.get("title"))
        for i, s in enumerate(b.get("steps", [])):
            add(f"steps[{i}]", s.get("label"))
        add("doneText", b.get("doneText")); add("siteUrl", b.get("siteUrl"))
    elif ty == "server-stack":
        add("title", b.get("title"))
        for i, n in enumerate(b.get("nodes", [])):
            add(f"nodes[{i}]", n.get("label"))
        if b.get("status"):
            add("status", b["status"].get("text"))
    else:
        out = v1_texts(b)
    return out


def verify(sb: dict, fb: FactBase, brief: dict, publishing: dict | None = None) -> dict:
    v = Verifier(fb, brief)
    claims = []
    for i, sc in enumerate(sb.get("scenes", [])):
        p = f"scenes[{i}]({sc.get('id')})"
        ctx = sc.get("narration", "")
        claims += v.verify_text(ctx, f"{p}.narration", ctx)
        for j, b in enumerate(sc.get("blocks", [])):
            for path, text in block_texts(b):
                claims += v.verify_text(text, f"{p}.blocks[{j}]:{b.get('type')}.{path}", ctx)
    if sb.get("title"):
        claims += v.verify_text(sb["title"], "storyboard.title")
    for k in ("title", "description"):
        if publishing and publishing.get(k):
            claims += v.verify_text(publishing[k], f"publishing.{k}")
    out = summarize(claims, fb, brief)
    out["verified"] = [c for c in out["claims"] if c["status"] == "VERIFIED"]
    return out


def verify_line(text: str, fb: FactBase, brief: dict, context: str = "") -> list[dict]:
    v = Verifier(fb, brief)
    return [c.as_dict() for c in v.verify_text(text, "line", context or text)]
