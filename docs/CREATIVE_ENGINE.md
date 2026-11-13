# LLM-only creative engine (`pipeline/intelligence`, opt-in)

> **This is not the default engine.** Productions use the hybrid engine (`pipeline/creative`) unless the brief sets
> `"engine": "llm"`. The hybrid engine, where templates own composition and labels and the LLM only drafts copy in
> validated slots, is documented in [CREATIVE_SYSTEM.md](CREATIVE_SYSTEM.md). This page documents the v0.3.0
> LLM-only engine, which is kept for comparison and experiments. The fact base (`facts.py`) and the claim checker
> (`claims.py`) described here are shared by both engines.

Turns a short product brief into **3 genuinely different video concepts**, then a **validated, fact-checked
storyboard** for the chosen one, in the standard storyboard format (`projects/<brand>/*.storyboard.json`). Inference is local only
(see LOCAL_AI.md). When no model is available, or the model keeps failing, a deterministic template planner
produces the output instead, and every report says which path produced it.

```
brief.json + request sentence
   │  brief.py        schema, normalisation, requirements ("problem", "demonstration", "pricing-comparison", "cta")
   ▼
facts.py  knowledge/<brand>/facts.json (verbatim excerpts from the public site, re-checkable with --refresh)
   │
   ▼  concepts.py     3 concepts: LLM (pattern enum restricted to unused patterns) → claim check → distinctness check
   │                  → regenerate on near-duplicate / invented claim → template concept as last resort
   ▼  storyboard_gen.py  SCENE BY SCENE: the pattern's beats fix the structure; each scene is generated against its
   │                  own schema (allowed block types; required blocks as required properties block_1..N; word budget
   │                  from the duration-fitted template shape) → compile (sanitise + brand conventions)
   │                  → scene check: validate_storyboard · block fields · word budget · on-screen text length · Latin
   │                    script · no repeated narration · CTA says the CTA + site · claims (invented → error)
   │                  → repair loop (errors fed back, 2 rounds) → autofix anchors → template scene for that beat
   │                  → publishing metadata call (fact-checked, template fallback) → whole-storyboard check
   ▼  claims.py       every claim in narration, block fields, title, publishing → fact id | NEEDS_REVIEW | ILLUSTRATIVE
   ▼  preview.py      creative-plan.json (music mood, captions, SFX notes, CTA, publishing) + storyboard-preview.md
   ▼  review.json     approval package: status BLOCKED while any claim needs owner review
```

## Use

```bash
python -m pipeline.intelligence demo --out output/eval-llm/demo            # built-in demo brief, end to end
python -m pipeline.intelligence concepts  --brief brief.json --request "…" --out DIR [--provider ollama|mock|none]
python -m pipeline.intelligence storyboard --brief brief.json --concepts DIR/concepts.json --pick 2 --out DIR
python -m pipeline.intelligence verify --storyboard projects/<brand>/x.storyboard.json --brand <brand>   # fact-check any storyboard
python -m pipeline.intelligence facts --brand <brand> [--refresh] [--claim "₹39"]                       # re-check facts on the live site
```
Exit code 3 means output was produced but is **BLOCKED** for review. In a production, select this engine with
`"engine": "llm"` in the brief. From Python:

```python
from pipeline.intelligence import generate_concepts, build_storyboard
res = generate_concepts(brief_dict, request_text, provider="ollama", out_dir="output/x")   # -> dict
sb, project, reports = build_storyboard(res["brief"], res["concepts"][0], provider="ollama", out_dir="output/x")
reports["review"]["blocking"], reports["path"]      # True/False, "llm" | "llm+repair" | "llm+template(k/n scenes)" | "template" | "template (llm fallback)"
```
`provider` takes "ollama", "mock" (deterministic, for tests), None (planner only) or a `Provider` instance.

Files written to `out_dir`: `concepts.json`, `concepts.md` (comparison), `<name>.storyboard.json`, `<name>.json`
(project config, valid for `video-pipeline validate`), `claims.json`, `review.json`, `creative-plan.json`,
`storyboard-preview.md`, `generation-log.json`.

## Brief schema
`brand`, `product` (required), `price`, `audience`, `format` (short|landscape), `duration_seconds` (10–180),
`goal`, `cta`, `tone`, `voice` (an Edge voice id), `request` (free text), `requirements`, `platform`, `url`, `notes`.
Missing fields are filled from the request sentence ("35-second", "YouTube Short", "premium"). A conflict is a
warning, never a silent override.

## Narrative patterns (`patterns.py`)
| id | beats → storyboard purposes |
|---|---|
| hook-problem-solution-demo-cta | hook→hook · problem→problem · solution→turn · demonstration→journey · pricing→resolution · cta→cta |
| myth-reality-explanation | myth→hook · reality→problem · explanation→point · proof→resolution · cta |
| before-after | before→hook · before-cost→problem · switch→turn · after→journey · after-price→resolution · cta |
| feature-benefit-proof | hook · feature→point · benefit→example · proof→resolution · cta |
| problem-discovery-transformation | problem→hook · struggle→problem · discovery→turn · transformation→journey · result→resolution · cta |
| tutorial-demo-result | promise→hook · step-1/2→journey · step-3→example · result→resolution · cta |

Each beat suggests block types and lists which brief requirements it satisfies. `rank_patterns` orders them
by goal fit and requirement coverage.

## Distinctness
For each pair of concepts: same pattern? hook similarity (max of content-word and character-trigram Jaccard),
hero-block Jaccard, and whether animation, CTA, music and pacing differ. Score = 0.25·pattern differs +
0.25·(1−block J) + 0.25·(1−hook sim) + 0.25·(share of other axes that differ). A pair is a **near-duplicate**
if the pattern is the same, hook sim > 0.55, block J > 0.8 or score < 0.45. The candidate is then rejected
and regenerated with the reasons, and after 3 attempts a template concept for an unused pattern replaces it.

## Fact discipline (`claims.py`)
Extracted claim kinds: price (₹49/mo, "forty-nine rupees a month", price/plans blocks), percent, quantity
(GB, cores, websites, days…), multiplier (3×, triple, 10x), any other number, plan names, domains/emails,
risky terms (fastest, best, guaranteed, unlimited, customers, award, discount, uptime…) and fact keywords.
- **Prices** must match amount, period, product (WordPress vs shared, taken from the scope, then the scene, then
  the brief) and plan. "From ₹X" must be the product's starting price.
- **Risky terms** must be covered by a fact keyword, otherwise NEEDS_REVIEW. "99.9% uptime guarantee" is flagged
  because the site says *target*.
- **Brief-supplied** claims that aren't on the site get `origin: brief` and NEEDS_REVIEW (the owner must confirm),
  and the approval package is **BLOCKED**. Model-invented claims (`origin: generated`) are fed back to the model
  as errors, and the storyboard is rejected if they persist.
- Placeholder UI domains (yourbrand.in) are ILLUSTRATIVE (non-blocking).
- The model never sees the `bars` block, since relative bar heights imply numbers nobody sourced.

## Storyboard conventions applied by the compiler
At most 3 blocks per scene. `danger` mood on problem scenes, `brand` on turn and CTA scenes. The brand bar
appears after the logo reveal (not on logo or CTA scenes). The CTA URL is forced to the brand site. Prices
in narration are spelled out for TTS ("39 rupees a month"). Auto-SFX come from the theme's sound family.
`structure` comes from the pattern. Duration is estimated at 2.33 words/s (calibrated to the local voice, which
measured 2.37) + 0.2 s per scene + 0.5 s pad, with a tolerance of 0.85–1.12× the target.

Why scene by scene: measured on qwen3-4B (LOCAL_AI.md), one-shot storyboards came back with 4 short scenes,
missing beats and anchors outside the scene. Scene-level generation with grammar-enforced required blocks made
3/3 storyboards valid and within the duration.

## Known limitations
- Template copy is written for hosting products, with WordPress-specific lines. Other products get generic
  hosting copy, and templates can't stretch much past ~36 s (longer targets trigger a duration warning).
- The claim checker is lexical: it catches numbers, plans, URLs and a list of risky words, but not number-free
  comparisons or positioning ("costs less than a coffee", "no tech skills needed"). A human still reads
  `storyboard-preview.md`.
- With a 4B model, copy quality is uneven: generic hooks, terse scenes, odd labels (e.g. a pill "Browser: 39
  rupees"), and scenes that are mostly empty backdrop. This is why the hybrid engine became the default (see
  [the same-brief comparison](reports/CREATIVE_COMPARISON.md)). Expect 0–2 template scenes per storyboard. The `scene_sources` field in generation-log.json says which.
- The engine itself outputs a music mood only (`audio.music: null` in its project file). In a production, the
  mood is mapped to a licensed track from the music library (`"mood:<mood>"`).
