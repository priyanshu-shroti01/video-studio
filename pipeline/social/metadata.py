"""Per-platform publishing metadata: YouTube (Shorts / long-form) and Instagram Reels.

Two writers produce the same "copy" (title, hook, summary, Instagram hook/body, first comment, extra tags):
  llm       the LOCAL model only (Ollama on 127.0.0.1, JSON-schema constrained, under the cross-process
            scheduler so it never overlaps a render). Nothing leaves the machine.
  template  deterministic, written from the brand profile and verified facts. Always available; used
            whenever the LLM is unavailable, busy, or its output fails validation.
Structured parts are never written by the LLM: links, CTA, prices (from facts), chapters (from the real
voice timings), hashtags (from the brand profile), category, languages and disclosures.

Everything published must be in the approval package (productions.package_files): drafting is only
allowed BEFORE approval. Output: publishing/metadata.json (versioned; source + validation) plus the
existing title.txt / description.md / hashtags.txt kept consistent with it. Previous versions are kept in
publishing/history/<timestamp>/."""
from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from ..errors import PipelineError
from ..paths import atomic_write_json, atomic_write_text, rel
from . import routing
from .brandcfg import BANNED_HASHTAGS, BrandSocial, load, load_brand_facts

SCHEMA_ID = "social-metadata/1"
DRAFT_STATES = {"QA_COMPLETE", "AWAITING_APPROVAL"}
LOCKED_STATES = {"APPROVED", "PUBLISHING", "PUBLISHED"}
CURRENCY = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
YT_TITLE_MAX, YT_DESC_MAX_BYTES, YT_TAGS_MAX = 100, 5000, 500
IG_CAPTION_MAX, IG_VISIBLE = 2200, 125
CLICHES = [r"game[- ]?changer", r"revolutioni[sz]e", r"unleash", r"elevate your", r"next level", r"look no further",
           r"in today'?s (?:digital|fast-paced) world", r"skyrocket", r"supercharge", r"don'?t miss (?:out|this)",
           r"act now", r"best[- ]in[- ]class", r"cutting[- ]edge", r"seamless(?:ly)?", r"synergy", r"must[- ]have",
           r"mind[- ]blowing", r"you won'?t believe", r"secret (?:trick|hack)", r"hack your", r"world[- ]class",
           r"one[- ]stop[- ]shop", r"take (?:it|your \w+) to the next level", r"crush(?:ing)? it", r"limited[- ]time"]
LINK_IN_BIO = re.compile(r"link in (?:our |the )?bio", re.I)
HASHTAG = re.compile(r"^#[A-Za-z][A-Za-z0-9_]{1,49}$")
PURPOSE_LABEL = {"hook": "Intro", "intro": "Intro", "problem": "The problem", "turn": "The solution", "point": "Key points",
                 "example": "Example", "journey": "How it works", "resolution": "The result", "conclusion": "Summary",
                 "cta": "Get started"}


class MetadataLocked(PipelineError):
    code, exit_code = "METADATA_LOCKED", 6


# ---- context ---------------------------------------------------------------------------------------------
def context(prod, pid: str) -> dict:
    p = prod.get(pid)
    if not p["job_id"]:
        raise PipelineError(f"production {pid} has no render job yet: render it first (metadata belongs to the rendered package)")
    job = prod.reg.get(p["job_id"])
    out = Path(job["output_dir"])
    cfg = load(p["brand"])
    fb = load_brand_facts(cfg)
    brief = p.get("brief") or {}
    sb = _json(out / "metadata/storyboard.json") or {}
    timing = _json(out / "metadata/timing.json") or {}
    pcfg = _json(out / "metadata/production-config.json") or {}
    formats = {}
    for v in sorted((out / "video").glob("final-*.mp4")):
        fmt = v.stem.removeprefix("final-")
        try:
            pl = routing.plan_file(v, fmt)
        except routing.ProbeError as e:
            pl = {"format": fmt, "video": None, "error": e.message, "destinations": [], "rejected": [], "suggestions": []}
        formats[fmt] = {"path": v, "plan": pl}
    product = brief.get("product") or sb.get("title") or cfg.name
    return {"production": p, "job": job, "out": out, "brand": cfg, "facts": fb, "brief": brief, "storyboard": sb,
            "timing": timing, "project": pcfg, "formats": formats, "product": product,
            "product_cfg": cfg.product_for(product)}


def _json(f: Path):
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return None


# ---- verified building blocks ------------------------------------------------------------------------------
def _verifier(ctx):
    from ..intelligence.claims import Verifier
    if "_verifier" not in ctx:                  # building one indexes every fact (~0.15 s): once per context
        ctx["_verifier"] = Verifier(ctx["facts"], {})   # facts only: nothing is trusted because a brief said it
    return ctx["_verifier"]


def unverified(ctx, text: str, scope: str = "metadata") -> list[dict]:
    """Claims in `text` that are not backed by the fact base (prices, numbers, plans, URLs, risky terms)."""
    if not text or not text.strip():
        return []
    v = _verifier(ctx)
    # line by line: the verifier binds a price to the plan named in the same text, so a multi-plan list must
    # be checked one line at a time (each line is one claim, e.g. "- WP Starter: ₹69/month")
    return [c.as_dict() for line in text.splitlines() if line.strip()
            for c in v.verify_text(line, scope, ctx["product"]) if c.status == "NEEDS_REVIEW"]


def _ok(ctx, text: str) -> bool:
    return not unverified(ctx, text)


def _money(v: dict) -> str:
    sym = CURRENCY.get(v.get("currency", ""), v.get("currency", "") + " ")
    amt = v["amount"]
    amt = f"{amt:,.0f}" if float(amt).is_integer() else f"{amt:,.2f}"
    return f"{sym}{amt}"


def price_facts(ctx) -> list[dict]:
    """Monthly plan prices for the production's product, cheapest first (facts with category 'price')."""
    fp = ctx["product_cfg"].get("factProduct")
    out, seen = [], set()
    for f in ctx["facts"].prices():
        v = f.get("value") or {}
        if not f.get("plan") or v.get("period") != "month" or v.get("billing", "monthly") != "monthly":
            continue
        if fp and f.get("product") != fp:
            continue
        if f["plan"] in seen:
            continue
        seen.add(f["plan"])
        out.append(f)
    return sorted(out, key=lambda f: f["value"]["amount"])


def price_lines(ctx, limit: int = 4) -> tuple[list[str], list[str], str | None]:
    """(plan lines, fact ids, 'from' price text) — each line re-verified against the facts."""
    lines, ids = [], []
    pf = price_facts(ctx)
    for f in pf[:limit]:
        line = f"{f['plan']}: {_money(f['value'])}/month"
        if _ok(ctx, line):
            lines.append(line)
            ids.append(f["id"])
    frm = f"{_money(pf[0]['value'])}/month" if pf and _ok(ctx, f"{pf[0]['plan']} from {_money(pf[0]['value'])}/month") else None
    return lines, ids, frm


def taxes_note(ctx) -> str | None:
    if any((f.get("value") or {}).get("taxes") == "excluded" for f in ctx["facts"].prices()):
        return "Prices exclude taxes."
    return None


def highlights(ctx, limit: int = 3) -> list[tuple[str, str]]:
    """(sentence, fact id) for the product's highlight facts; each sentence must verify cleanly."""
    fb, pc = ctx["facts"], ctx["product_cfg"]
    ids = list(pc.get("highlightFactIds") or [])
    if not ids:
        fp = pc.get("factProduct")
        ids = [f["id"] for f in fb.facts if f["category"] in ("feature", "policy") and f.get("product") in (fp, "all")]
    out = []
    for fid in ids:
        f = fb.by_id(fid)
        if not f:
            continue
        s = f["claim"].strip().rstrip(".") + "."
        s = s[0].upper() + s[1:]
        if _ok(ctx, s):
            out.append((s, fid))
        if len(out) >= limit:
            break
    return out


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+", text or "") if s.strip()]


def hook_line(ctx, max_len: int = 120) -> str:
    """The video's own opening line (already voiced), if it verifies; otherwise a neutral product line."""
    scenes = ctx["storyboard"].get("scenes", [])
    cand = ""
    for s in _sentences(" ".join(sc.get("narration", "") for sc in scenes[:2])):
        nxt = (cand + " " + s).strip()
        if len(nxt) > max_len or not _ok(ctx, s):
            break
        cand = nxt
        if len(cand) > 50:
            break
    return cand or f"{ctx['product']} by {ctx['brand'].name}."


def chapters(ctx, fmt: str) -> tuple[list[dict] | None, str]:
    """YouTube chapters from the real scene timings (landscape only). First at 0:00, >= 3 chapters,
    each >= 10 s; otherwise None with the reason."""
    info = (ctx["formats"].get(fmt) or {}).get("plan", {}).get("video") or {}
    if not str(info.get("orientation", "")).startswith("landscape"):
        return None, "chapters are only added to landscape (long-form) videos"
    scenes = ctx["storyboard"].get("scenes", [])
    spans = ctx["timing"].get("scene_spans") or []
    dur = float(info.get("duration_s") or ctx["timing"].get("duration") or 0)
    if not scenes or len(spans) != len(scenes):
        return None, "scene timings are missing or do not match the storyboard"
    groups: list[dict] = []
    for i, (sc, sp) in enumerate(zip(scenes, spans)):
        start = 0.0 if i == 0 else max(0.0, float(sp[0]) - 0.25)
        label = _chapter_label(ctx, sc)
        if groups and groups[-1]["label"] == label:
            continue
        groups.append({"start": start, "label": label})
    # greedy: a chapter absorbs the following sections until it is >= 10 s long
    merged: list[dict] = []
    cur = None
    for g in groups:
        if cur is None:
            cur = dict(g)
        elif g["start"] - cur["start"] < 10:
            continue                                   # still too short: this section joins the current chapter
        else:
            cur["end"] = g["start"]
            merged.append(cur)
            cur = dict(g)
    if cur is not None:
        cur["end"] = dur
        if cur["end"] - cur["start"] < 10 and merged:
            merged[-1]["end"] = dur                    # a short tail joins the previous chapter
        else:
            merged.append(cur)
    if len(merged) < 3 or any(c["end"] - c["start"] < 10 for c in merged):
        return None, f"{len(merged)} chapter(s) of >= 10 s possible in {dur:.0f} s; YouTube needs >= 3, so chapters are skipped"
    merged[0]["start"] = 0.0
    return [{"start_s": round(c["start"], 2), "time": _ts(c["start"]), "title": c["label"]} for c in merged], "ok"


def _chapter_label(ctx, sc: dict) -> str:
    purpose = sc.get("purpose", "")
    if purpose == "turn":
        return f"Meet {ctx['brand'].name}"
    return PURPOSE_LABEL.get(purpose) or (sc.get("id") or "Part").replace("-", " ").capitalize()


def _ts(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def credits_section(ctx) -> list[str]:
    """Licence credits the render wrote into description.md (kept verbatim, de-duplicated)."""
    f = ctx["out"] / "publishing/description.md"
    hist = sorted((ctx["out"] / "publishing/history").glob("*/description.md")) if (ctx["out"] / "publishing/history").exists() else []
    src = hist[0] if hist else f                 # the render's original, not a previous draft
    try:
        lines = src.read_text().splitlines()
    except OSError:
        return []
    out, on = [], False
    for ln in lines:
        if re.match(r"^(Sound effects|Music|Credits):\s*$", ln.strip()):
            on = True
            out.append(ln.strip())
            continue
        if on:
            if not ln.strip().startswith("- "):
                on = False
                continue
            if ln.strip() not in out:
                out.append(ln.strip())
    return out


def tags_length(tags: list[str]) -> int:
    """YouTube's count: commas between tags count, and a tag with a space counts its implied quotes."""
    return sum(len(t) + (2 if " " in t else 0) for t in tags) + max(0, len(tags) - 1)


def fit_tags(tags: list[str], limit: int = YT_TAGS_MAX) -> list[str]:
    out, seen = [], set()
    for t in tags:
        t = re.sub(r"[<>,#]", "", t).strip()
        if not t or t.lower() in seen or len(t) > 100:
            continue
        if tags_length(out + [t]) > limit:
            break
        out.append(t)
        seen.add(t.lower())
    return out


def pick_hashtags(ctx, platform: str, n_min: int, n_max: int) -> list[str]:
    pc, bc = ctx["product_cfg"], ctx["brand"]
    prod_tags = list((pc.get("hashtags") or {}).get(platform, []))
    brand_tags = list(bc.hashtags.get(platform, []))
    order = prod_tags[:1] + brand_tags[:1] + prod_tags[1:] + brand_tags[1:]
    out = []
    for h in order:
        h = h if h.startswith("#") else "#" + h
        if HASHTAG.match(h) and h.lower() not in BANNED_HASHTAGS and h.lower() not in {x.lower() for x in out} and _ok(ctx, h.lstrip("#")):
            out.append(h)
        if len(out) >= n_max:
            break
    if len(out) < n_min:
        base = "#" + re.sub(r"\W", "", bc.name)
        if base.lower() not in {x.lower() for x in out} and HASHTAG.match(base):
            out.append(base)
    return out[:n_max]


# ---- copy writers --------------------------------------------------------------------------------------------
def primary_keyword(ctx, keyword: str | None = None) -> str:
    return (keyword or ctx["product_cfg"].get("primaryKeyword") or ctx["product"]).strip()


def template_copy(ctx, keyword: str | None = None) -> dict:
    kw = primary_keyword(ctx, keyword)
    _, _, frm = price_lines(ctx)
    name = ctx["brand"].name
    title = f"{kw} from {frm}" if frm else kw
    if len(f"{title} | {name}") <= YT_TITLE_MAX and name.lower() not in title.lower():
        title = f"{title} | {name}"
    hook = hook_line(ctx)
    hl = highlights(ctx)
    summary = " ".join(s for s, _ in hl[:2]) or f"{ctx['product']} by {name}."
    return {"title": title[:YT_TITLE_MAX], "hook": hook, "summary": summary[:300], "ig_hook": hook[:IG_VISIBLE],
            "ig_body": "\n\n".join(s for s, _ in hl) or summary, "first_comment": "", "tags": []}


LLM_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "hook", "summary", "ig_hook", "ig_body", "first_comment", "tags"],
    "properties": {
        "title": {"type": "string", "minLength": 10, "maxLength": 95},
        "hook": {"type": "string", "minLength": 10, "maxLength": 120},
        "summary": {"type": "string", "minLength": 20, "maxLength": 300},
        "ig_hook": {"type": "string", "minLength": 10, "maxLength": 120},
        "ig_body": {"type": "string", "minLength": 20, "maxLength": 500},
        "first_comment": {"type": "string", "maxLength": 300},
        "tags": {"type": "array", "maxItems": 10, "items": {"type": "string", "minLength": 2, "maxLength": 30}},
    },
}


def _llm_prompt(ctx, keyword: str) -> tuple[str, str]:
    b, brief = ctx["brand"], ctx["brief"]
    lines, _, frm = price_lines(ctx)
    narr = " ".join(s.get("narration", "") for s in ctx["storyboard"].get("scenes", []))
    system = (f"You write social media publishing copy for {b.name}. Output JSON only, matching the schema.\n"
              f"BRAND VOICE: {b.voice}\n"
              "FACT DISCIPLINE: every price, plan, number, spec, feature, guarantee or comparison must appear in the FACT SHEET. "
              "Never invent discounts, speed numbers, uptime, customer counts, reviews, awards or competitor claims. "
              "If unsure, leave the claim out.\n"
              "FORMAT: no hashtags, no links, no emojis, no ALL-CAPS words, no exclamation marks. Hashtags, links, prices "
              "and the call to action are added by the system.\n"
              "AVOID CLICHES: game changer, unleash, elevate, next level, seamless, cutting-edge, look no further, "
              "don't miss out, act now, supercharge, skyrocket.")
    user = (f"PRODUCT: {ctx['product']}\nAUDIENCE: {brief.get('audience', '')}\nGOAL: {brief.get('goal', '')}\n"
            f"TONE: {brief.get('tone', '')}\nPRIMARY KEYWORD: {keyword}\n"
            f"VERIFIED PRICES: {'; '.join(lines) or 'none (do not mention prices)'}\n"
            f"FACT SHEET:\n{ctx['facts'].for_prompt(ctx['product'], limit=40)}\n\n"
            f"VIDEO NARRATION (already approved for the video):\n{narr}\n\n"
            "Write:\n"
            f"- title: YouTube title, under 90 characters, containing '{keyword}' within the first 60 characters, specific "
            "and readable (sentence case or title case)\n"
            "- hook: one sentence that opens the YouTube description and makes the viewer's problem concrete\n"
            "- summary: 1-2 sentences on what the product does for this audience, using fact-sheet items only\n"
            "- ig_hook: the first line of an Instagram Reels caption (under 120 characters), a hook that works without the video\n"
            "- ig_body: 2-3 very short paragraphs separated by blank lines, using fact-sheet items only\n"
            "- first_comment: an optional helpful first comment (may be empty)\n"
            "- tags: up to 10 YouTube search tags (lowercase phrases people actually search)")
    return system, user


def render_busy(reg) -> bool:
    try:
        with reg.conn() as c:
            return c.execute("SELECT 1 FROM sched_queue WHERE state='granted' AND kind='render'").fetchone() is not None
    except Exception:  # noqa: BLE001
        return False


def llm_copy(ctx, provider, keyword: str, log: list, reg=None, attempts: int = 2) -> tuple[dict | None, list[str]]:
    """Ask the LOCAL model for copy; validate every attempt. Returns (copy, remaining problems) of the last
    schema-valid attempt, or (None, []) if the model is unavailable/busy/failed."""
    from ..intelligence.providers import LLMError
    from ..jobs import Registry
    from ..scheduler import HeavyWork
    reg = reg or Registry()
    if render_busy(reg):
        log.append({"event": "llm_skipped", "reason": "a render is running; the LLM never runs alongside a render"})
        return None, []
    ok, why = provider.available()
    if not ok:
        log.append({"event": "llm_unavailable", "reason": why})
        return None, []
    best: tuple[dict | None, list[str]] = (None, [])
    system, user = _llm_prompt(ctx, keyword)
    msgs = [{"role": "user", "content": user}]
    try:
        with HeavyWork(reg, "llm", ref=f"social:{ctx['production']['id']}", timeout=900):
            for attempt in range(attempts):
                try:
                    r = provider.generate_json(system=system, messages=msgs, schema=LLM_SCHEMA, task="social_metadata",
                                               context={"brief": ctx["brief"]}, temperature=0.5, seed=7 + attempt,
                                               max_tokens=700)
                except LLMError as e:
                    log.append({"event": "llm_error", "attempt": attempt, "error": e.message})
                    return best
                copy = {**r.data, "tags": list(r.data.get("tags") or [])}
                probs = copy_problems(ctx, copy, keyword)
                log.append({"event": "llm_generated", "attempt": attempt, "stats": r.stats.as_dict(),
                            "schema_errors": r.schema_errors[:5], "problems": probs[:8]})
                if not r.schema_errors:
                    best = (copy, probs)
                    if not probs:
                        return best
                msgs = msgs + [{"role": "assistant", "content": r.raw},
                               {"role": "user", "content": "Problems: " + "; ".join([*r.schema_errors[:4], *probs[:8]]) +
                                ". Remove every number, duration or claim that is not in the FACT SHEET. Return corrected JSON."}]
    except PipelineError as e:
        log.append({"event": "llm_error", "error": e.message})
    finally:
        try:
            provider.unload()
        except Exception:  # noqa: BLE001
            pass
    return best


COPY_FIELDS = ("title", "hook", "summary", "ig_hook", "ig_body", "first_comment")


def merge_with_template(ctx, copy: dict, probs: list[str], keyword: str | None) -> tuple[dict, list[str]]:
    """Keep the LLM fields that verified; replace each failing field with the template's (tags: drop bad ones)."""
    bad = {p.split(":", 1)[0] for p in probs}
    tpl = template_copy(ctx, keyword)
    out, replaced = dict(copy), []
    for f in COPY_FIELDS:
        if f in bad:
            out[f] = tpl[f]
            replaced.append(f)
    if "tags" in bad:
        out["tags"] = [t for t in copy.get("tags") or [] if not unverified(ctx, t, "tags") and not style_problems(t, ctx)]
        replaced.append("tags (filtered)")
    return out, replaced


def copy_problems(ctx, copy: dict, keyword: str) -> list[str]:
    probs = []
    for k in ("title", "hook", "summary", "ig_hook", "ig_body", "first_comment"):
        t = copy.get(k) or ""
        for c in unverified(ctx, t, k):
            probs.append(f"{k}: unverified claim {c['text']!r} ({c.get('reason', 'not in the fact sheet')[:80]})")
        probs += [f"{k}: {p}" for p in style_problems(t, ctx)]
        if re.search(r"https?://|www\.|#\w", t):
            probs.append(f"{k}: no links or hashtags (the system adds them)")
    for t in copy.get("tags") or []:
        for c in unverified(ctx, t, "tags"):
            probs.append(f"tags: unverified claim {c['text']!r}")
    if keyword.lower() not in (copy.get("title") or "").lower()[:60]:
        probs.append(f"title: put the primary keyword '{keyword}' in the first 60 characters")
    return probs


# ---- assembly ------------------------------------------------------------------------------------------------
def _allowed_caps(ctx) -> set[str]:
    words = set()
    for f in ctx["facts"].facts:
        words |= set(re.findall(r"\b[A-Z0-9]{2,}\b", f.get("excerpt", "") + " " + f.get("claim", "")))
    words |= set(re.findall(r"\b[A-Z0-9]{2,}\b", ctx["brand"].name))
    return words


def style_problems(text: str, ctx=None) -> list[str]:
    probs = []
    for rx in CLICHES:
        m = re.search(rf"\b{rx}\b", text, re.I)
        if m:
            probs.append(f"cliche {m.group(0)!r}")
    for phrase in (ctx["brand"].banned if ctx else []):
        if re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", text, re.I):
            probs.append(f"brand-banned phrase {phrase!r}")
    allowed = _allowed_caps(ctx) if ctx else set()
    caps = [w for w in re.findall(r"\b[A-Z]{4,}\b", text) if w not in allowed]
    if caps:
        probs.append(f"ALL-CAPS words {caps[:3]}")
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) > 20 and sum(ch.isupper() for ch in letters) / len(letters) > 0.4:
        probs.append("too much upper case")
    if text.count("!") > 1:
        probs.append("more than one exclamation mark")
    return probs


def youtube_entry(ctx, fmt: str, copy: dict, keyword: str, publish_at: str | None, set_thumbnail: bool) -> dict:
    b = ctx["brand"]
    pl = ctx["formats"][fmt]["plan"]
    yt = next((d for d in pl["destinations"] if d["platform"] == "youtube"), {"kind": "short" if fmt == "short" else "video"})
    lines, ids, _ = price_lines(ctx)
    chaps, chap_note = chapters(ctx, fmt)
    tags3 = pick_hashtags(ctx, "youtube", 3, 3)
    cta = b.cta.get("youtube") or b.link
    hook = copy["hook"].strip()
    if b.domain and b.domain not in hook:
        room = 150 - len(cta) - 1
        if len(hook) > room:
            hook = hook[:max(0, room - 1)].rsplit(" ", 1)[0] + "…"
        first = f"{hook}\n{cta}"
    else:
        first = hook
    desc = [first, "", copy["summary"].strip()]
    if lines:
        desc += ["", "Plans:", *[f"- {ln}" for ln in lines]]
        if taxes_note(ctx):
            desc.append(taxes_note(ctx))
    if chaps:
        desc += ["", "Chapters:", *[f"{c['time']} {c['title']}" for c in chaps]]
    if b.ai_disclosure:
        desc += ["", "The voiceover in this video is AI-generated (synthetic voice)."]
    cr = credits_section(ctx)
    if cr:
        desc += ["", *cr]
    desc += ["", " ".join(tags3)]
    pc = ctx["product_cfg"]
    tags = fit_tags([keyword, *(pc.get("tags") or []), ctx["product"], b.name, *(copy.get("tags") or [])])
    status = {"privacyStatus": "private" if publish_at else b.privacy_default, "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": True}
    if publish_at:
        status["publishAt"] = publish_at
    return {"kind": yt.get("kind"), "snippet": {"title": copy["title"].strip(), "description": "\n".join(desc).strip() + "\n",
                                                "tags": tags, "categoryId": b.category_id, "defaultLanguage": b.language,
                                                "defaultAudioLanguage": b.language},
            "status": status, "hashtags": tags3, "chapters": chaps, "chapters_note": chap_note,
            "set_thumbnail": bool(set_thumbnail), "fact_ids": ids, "credits_lines": len(cr)}


def instagram_entry(ctx, fmt: str, copy: dict) -> dict | None:
    pl = ctx["formats"][fmt]["plan"]
    if not any(d["platform"] == "instagram" for d in pl["destinations"]):
        return None
    b = ctx["brand"]
    _, _, frm = price_lines(ctx)
    tags = pick_hashtags(ctx, "instagram", 3, 5)
    parts = [copy["ig_hook"].strip(), copy["ig_body"].strip()]
    if frm:
        parts.append(f"{ctx['product']} from {frm}." + (f" {taxes_note(ctx)}" if taxes_note(ctx) else ""))
    parts.append(b.cta.get("instagram") or "Link in bio")
    if b.ai_disclosure:
        parts.append("Voiceover: AI-generated.")
    caption = "\n\n".join(p for p in parts if p) + "\n\n" + " ".join(tags)
    thumb_t = (ctx["project"].get("publishing") or {}).get("thumbnailAt")
    spans = ctx["timing"].get("scene_spans") or []
    if thumb_t is None and spans:
        thumb_t = float(spans[-1][0]) + 1.2              # the render's default thumbnail moment
    dur = (pl.get("video") or {}).get("duration_s") or 0
    thumb_ms = int(min(float(thumb_t or 0), max(0.0, dur - 0.2)) * 1000) if thumb_t is not None else 0
    return {"kind": "reel", "caption": caption, "first_comment": (copy.get("first_comment") or "").strip() or None,
            "share_to_feed": True, "thumb_offset_ms": thumb_ms, "cover_url": None, "is_ai_generated": b.ai_disclosure,
            "hashtags": tags,
            "cover_note": "cover_url needs a public image URL, so the cover is a frame of the video (thumb_offset); "
                          "publishing/thumbnail.png is taken from the same moment"}


# ---- validation ----------------------------------------------------------------------------------------------
def validate_youtube(ctx, e: dict, keyword: str) -> dict:
    err, warn = [], []
    sn = e["snippet"]
    t, d = sn["title"], sn["description"]
    if not 1 <= len(t) <= YT_TITLE_MAX:
        err.append(f"title is {len(t)} characters (1-{YT_TITLE_MAX})")
    if re.search(r"[<>]", t + d):
        err.append("title/description may not contain < or >")
    if keyword and keyword.lower() not in t.lower()[:60]:
        warn.append(f"primary keyword '{keyword}' is not in the first 60 characters of the title")
    if len(d.encode()) > YT_DESC_MAX_BYTES:
        err.append(f"description is {len(d.encode())} bytes (max {YT_DESC_MAX_BYTES})")
    dom = ctx["brand"].domain
    if dom and (d.find(dom) < 0 or d.find(dom) > 150):
        err.append(f"the {dom} link must be in the first 150 characters of the description")
    tl = tags_length(sn["tags"])
    if tl > YT_TAGS_MAX:
        err.append(f"tags total {tl} characters (max {YT_TAGS_MAX})")
    err += _hashtag_errors(e["hashtags"], 3, 3, "youtube")
    marketing = d.split("\n\nSound effects:")[0].split("\n\nMusic:")[0]
    # chapter timestamps come from the voice timings, not from copy: not claims
    marketing = re.sub(r"(?m)^(?:Chapters:|\d{1,2}:\d{2}(?::\d{2})? .*)$", "", marketing)
    in_desc = re.findall(r"(?<![\w#])#[A-Za-z]\w*", marketing)
    if [h for h in in_desc if h.lower() in BANNED_HASHTAGS]:
        err.append("youtube: generic hashtags in the description")
    err += _claim_errors(ctx, {"title": t, "description": marketing, "tags": ", ".join(sn["tags"])})
    err += [f"title: {p}" for p in style_problems(t, ctx)] + [f"description: {p}" for p in style_problems(marketing, ctx)]
    c = e.get("chapters")
    if c:
        if c[0]["start_s"] != 0 or len(c) < 3:
            err.append("chapters must start at 0:00 and have at least 3 entries")
        ends = [x["start_s"] for x in c[1:]] + [None]
        for x, nxt in zip(c, ends):
            if nxt is not None and nxt - x["start_s"] < 10:
                err.append(f"chapter {x['time']} is shorter than 10 s")
    st = e["status"]
    if st.get("publishAt"):
        if st.get("privacyStatus") != "private":
            err.append("publishAt requires privacyStatus 'private'")
        try:
            when = datetime.fromisoformat(st["publishAt"].replace("Z", "+00:00"))
            if when.tzinfo is None:
                err.append("publishAt needs a timezone (e.g. 2026-12-01T10:00:00+05:30)")
            elif when <= datetime.now(timezone.utc):
                err.append("publishAt is in the past")
        except ValueError:
            err.append("publishAt is not ISO 8601")
    if st.get("privacyStatus") not in ("private", "unlisted", "public"):
        err.append(f"privacyStatus {st.get('privacyStatus')!r} is invalid")
    if st.get("selfDeclaredMadeForKids") is not False or st.get("containsSyntheticMedia") is not True:
        err.append("status must declare selfDeclaredMadeForKids=false and containsSyntheticMedia=true (synthetic voice)")
    return {"status": "FAIL" if err else "PASS", "errors": err, "warnings": warn}


def validate_instagram(ctx, e: dict) -> dict:
    err, warn = [], []
    cap = e["caption"]
    if len(cap) > IG_CAPTION_MAX:
        err.append(f"caption is {len(cap)} characters (max {IG_CAPTION_MAX})")
    first = cap.split("\n", 1)[0]
    if len(first) > IG_VISIBLE:
        warn.append(f"first line is {len(first)} characters; only ~{IG_VISIBLE} show before 'more'")
    if not LINK_IN_BIO.search(cap):
        err.append("caption needs a 'link in bio' call to action (links in captions are not clickable)")
    if re.search(r"https?://", cap):
        warn.append("caption contains a URL; it will not be clickable on Instagram")
    err += _hashtag_errors(e["hashtags"], 3, 5, "instagram")
    in_cap = re.findall(r"(?<![\w#])#[A-Za-z]\w*", cap)
    if len(in_cap) > 5:
        err.append("caption has more than 5 hashtags")
    err += [f"instagram: generic hashtag {h} is not allowed" for h in in_cap if h.lower() in BANNED_HASHTAGS]
    body = re.sub(r"(?<!\w)#\w+", "", cap)
    err += _claim_errors(ctx, {"caption": body, "first_comment": e.get("first_comment") or ""})
    err += [f"caption: {p}" for p in style_problems(body, ctx)]
    if any(len(p) > 400 for p in cap.split("\n\n")):
        warn.append("a caption paragraph is longer than 400 characters; keep paragraphs short")
    return {"status": "FAIL" if err else "PASS", "errors": err, "warnings": warn}


def _hashtag_errors(tags: list[str], lo: int, hi: int, platform: str) -> list[str]:
    err = []
    if not lo <= len(tags) <= hi:
        err.append(f"{platform}: {len(tags)} hashtags (want {lo}-{hi})" if lo != hi else f"{platform}: {len(tags)} hashtags (want {lo})")
    for h in tags:
        if not HASHTAG.match(h):
            err.append(f"{platform}: invalid hashtag {h!r}")
        if h.lower() in BANNED_HASHTAGS:
            err.append(f"{platform}: generic hashtag {h} is not allowed")
    if len({h.lower() for h in tags}) != len(tags):
        err.append(f"{platform}: duplicate hashtags")
    return err


def _claim_errors(ctx, fields: dict) -> list[str]:
    return [f"{k}: unverified claim {c['text']!r} — {c.get('reason', 'not in the fact base')}"
            for k, t in fields.items() for c in unverified(ctx, t, k)]


# ---- drafting ------------------------------------------------------------------------------------------------
def assemble(ctx, copy: dict, keyword: str, publish_at: str | None = None, set_thumbnail: bool = False) -> dict:
    formats, val = {}, {}
    for fmt, f in ctx["formats"].items():
        if not f["plan"].get("video"):
            formats[fmt] = {"video": rel(f["path"]), "error": f["plan"].get("error")}
            val[fmt] = {"status": "FAIL", "errors": [f["plan"].get("error") or "video could not be probed"]}
            continue
        yt = youtube_entry(ctx, fmt, copy, keyword, publish_at, set_thumbnail)
        ig = instagram_entry(ctx, fmt, copy)
        rv = {"youtube": validate_youtube(ctx, yt, keyword)}
        if ig:
            rv["instagram"] = validate_instagram(ctx, ig)
        rv["status"] = "FAIL" if any(v["status"] == "FAIL" for v in rv.values() if isinstance(v, dict)) else "PASS"
        formats[fmt] = {"video": rel(f["path"]), "routing": f["plan"], "youtube": yt, "instagram": ig,
                        "instagram_refused": next((r["reasons"] for r in f["plan"]["rejected"] if r["platform"] == "instagram"), None)}
        val[fmt] = rv
    status = "FAIL" if not formats or any(v["status"] == "FAIL" for v in val.values()) else "PASS"
    return {"formats": formats, "validation": {"status": status, "formats": val}}


def check_draft_allowed(prod, pid: str) -> dict:
    p = prod.get(pid)
    if p["state"] in LOCKED_STATES:
        raise MetadataLocked(f"production is {p['state']}: approval would be invalidated: request changes first. "
                             "Metadata is part of the approved package, so it can only be drafted before approval. "
                             "A person can withdraw the approval with `video-pipeline social draft --id "
                             f"{pid} --reopen-review --actor NAME`.")
    if p["state"] not in DRAFT_STATES:
        raise MetadataLocked(f"production is {p['state']}: metadata is drafted after the render's QA "
                             f"(states {sorted(DRAFT_STATES)}), before approval")
    return p


def reopen_review(prod, pid: str, actor: str, note: str = "") -> None:
    """Human action: withdraw a valid approval so metadata can be redrafted (APPROVED -> AWAITING_APPROVAL)."""
    if not actor.strip():
        raise MetadataLocked("withdrawing an approval needs the person's name (--actor)")
    p = prod.get(pid)
    if p["state"] != "APPROVED":
        raise MetadataLocked(f"production is {p['state']}; only an APPROVED (not yet published) production can be reopened")
    with prod.reg.conn() as c:
        c.execute("UPDATE approvals SET invalidated_at=?, invalidated_reason=? WHERE production_id=? AND decision='APPROVED' "
                  "AND invalidated_at IS NULL", (time.time(), f"withdrawn by {actor} to redraft social metadata", pid))
    prod.transition(pid, "AWAITING_APPROVAL", actor=actor, note=note or "approval withdrawn to redraft social metadata")


def draft(prod, pid: str, *, provider: str | object = "ollama", keyword: str | None = None,
          publish_at: str | None = None, set_thumbnail: bool = False, reg=None, copy: dict | None = None) -> dict:
    """Write publishing/metadata.json (+ title/description/hashtags) for every rendered format.

    `copy` (fields COPY_FIELDS + tags) is human-written copy: it gets exactly the same claim, style and platform
    validation as LLM copy and is refused (never silently replaced) if any check fails. source = "human"."""
    check_draft_allowed(prod, pid)
    ctx = context(prod, pid)
    if not ctx["formats"]:
        raise PipelineError("the render job has no final videos")
    kw = primary_keyword(ctx, keyword)
    log: list = []
    human = copy is not None
    source = "template"
    if human:
        copy = {"first_comment": "", "tags": [], **copy}
        missing = [k for k in COPY_FIELDS if k not in copy]
        if missing:
            raise PipelineError(f"human copy is missing {missing}")
        probs = copy_problems(ctx, copy, kw)
        if probs:
            raise PipelineError("human copy failed the checks", detail="\n".join(probs))
        source, provider = "human", None
        log.append({"event": "human_copy"})
    if provider not in ("template", None) and not human:
        prov = provider
        if isinstance(provider, str):
            from ..intelligence.providers import get_provider
            prov = get_provider(provider, **({"autostart": False} if provider == "ollama" else {}))
        copy, probs = llm_copy(ctx, prov, kw, log, reg=reg or prod.reg)
        if copy and probs:
            copy, replaced = merge_with_template(ctx, copy, probs, keyword)
            log.append({"event": "llm_partial", "template_fields": replaced})
            source = "llm+template" if len(replaced) < len(COPY_FIELDS) else "template"
            copy = copy if source != "template" else None
        elif copy:
            source = "llm"
    llm_info = {"requested": "human" if human else provider if isinstance(provider, str) else getattr(provider, "name", "custom"),
                "log": log}
    built = assemble(ctx, copy, kw, publish_at, set_thumbnail) if copy else None
    if built and built["validation"]["status"] == "FAIL" and human:
        raise PipelineError("human copy failed platform validation", detail="\n".join(
            e for v in built["validation"]["formats"].values() for p in ("youtube", "instagram")
            for e in (v.get(p) or {}).get("errors", [])))
    if built and built["validation"]["status"] == "FAIL":
        log.append({"event": "llm_rejected", "reason": "assembled metadata failed validation; using the template",
                    "errors": [e for v in built["validation"]["formats"].values()
                               for p in ("youtube", "instagram") for e in (v.get(p) or {}).get("errors", [])][:8]})
        built, source = None, "template"
    if not built:
        built = assemble(ctx, template_copy(ctx, keyword), kw, publish_at, set_thumbnail)
    pub = ctx["out"] / "publishing"
    prev = _json(pub / "metadata.json") or {}
    doc = {"schema": SCHEMA_ID, "version": int(prev.get("version", 0)) + 1,
           "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "production_id": pid,
           "job_id": ctx["job"]["id"], "brand": ctx["brand"].brand_id, "product": ctx["product"],
           "primary_keyword": kw, "source": source, "llm": llm_info,
           "facts": {"file": rel(ctx["facts"].path) if ctx["facts"].path else None, "fetched_at": ctx["facts"].fetched_at},
           **built}
    _snapshot(pub)
    atomic_write_json(pub / "metadata.json", doc)
    primary = "short" if "short" in built["formats"] and built["formats"]["short"].get("youtube") else \
        next((f for f, v in built["formats"].items() if v.get("youtube")), None)
    if primary:
        yt = built["formats"][primary]["youtube"]
        atomic_write_text(pub / "title.txt", yt["snippet"]["title"] + "\n")
        atomic_write_text(pub / "description.md", yt["snippet"]["description"])
        atomic_write_text(pub / "hashtags.txt", " ".join(yt["hashtags"]) + "\n")
    p = prod.get(pid)
    if built["validation"]["status"] == "FAIL":
        prod.flag(pid, "metadata:invalid", "publishing/metadata.json failed validation: fix it before approving", "blocking", "social")
    prod.flag(pid, "metadata:review", "Read publishing/metadata.json (YouTube title/description/tags, Instagram caption) "
              "before approving: it is published exactly as approved", "advisory", "social")
    if p["state"] == "AWAITING_APPROVAL":
        prod.build_package(pid)                   # the reviewer must see (and approve) the new metadata
    prod.reg.audit("system", "social.metadata.draft", pid, {"version": doc["version"], "source": source,
                                                              "validation": built["validation"]["status"]})
    return {"path": rel(pub / "metadata.json"), "version": doc["version"], "source": source,
            "validation": built["validation"], "formats": {f: {"youtube_title": (v.get("youtube") or {}).get("snippet", {}).get("title"),
                                                               "instagram": bool(v.get("instagram")),
                                                               "instagram_refused": v.get("instagram_refused")}
                                                           for f, v in built["formats"].items()},
            "llm": llm_info}


def _snapshot(pub: Path) -> None:
    files = [f for f in ("metadata.json", "title.txt", "description.md", "hashtags.txt") if (pub / f).exists()]
    if not files:
        return
    d = pub / "history" / time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    n = 1
    while d.exists():
        d = d.with_name(d.name.split("-")[0] + f"-{n}")
        n += 1
    d.mkdir(parents=True)
    for f in files:
        shutil.copy2(pub / f, d / f)


def load_metadata(job_out: Path) -> dict | None:
    return _json(Path(job_out) / "publishing/metadata.json")
