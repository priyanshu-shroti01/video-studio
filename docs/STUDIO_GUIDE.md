# Local Video Studio

A desktop-browser UI over the same service layer the CLI uses (`pipeline/api.py`, `pipeline/productions.py`,
`pipeline/publishing.py`). The CLI (`uv run video-pipeline …`) stays the primary automation interface; the Studio
cannot bypass validation, the scheduler, the preview review or the approval gate because it only calls those
functions.

## Launch

```bash
uv run python -m studio.build            # once, and after changing studio/web/src (esbuild -> studio/web/dist)
uv run video-pipeline studio --open      # or: uv run python -m studio.server  (--port 8765 default · --open · --new-token)
```

Open `http://127.0.0.1:8765/` in any browser on this Mac (`--open` does it for you); no token is needed. Opening the
address yourself signs that browser in with an HttpOnly, SameSite=Strict cookie; a page that another website opens
does not, and Host/Origin checks refuse other sites' requests. Scripts can still use the token (`/?token=…` or
`Authorization: Bearer`): it is
exchanged for an HttpOnly cookie and removed from the address bar. The token is stored in
`.pipeline/studio/session-token` (mode 0600) and **survives restarts**, so open tabs keep working after the Studio
is restarted. `--new-token` rotates it and signs out every open tab.
From Python: `from studio import serve; serve(8765, open_browser=False)`.

## Layout

- **Sidebar:** the seven sections, a global **Brand** selector ("All brands" or one brand; draft brands are
  marked) and the **Current production** picker, which lists only the selected brand's productions. The brand
  choice is a view preference stored in the browser. Every action still takes the brand from the production
  itself, and a new production defaults to the selected brand.
- **Connection banner:** if the server stops, a banner says "The Studio server is not running" with the command
  to start it again; the page keeps its last data and reconnects by itself. If the session is not valid, it says
  "Not signed in to this Studio" and points to the link printed in the terminal.
- **Look:** a brand-neutral dark theme with its own accent colour and the shared OFL fonts
  (`public/shared/fonts/`). Brand colours appear only as data (brand dots, previews), never as the Studio's chrome.

## Home and "Create a video" (everyday use)

The Studio opens on **Home** (`#/home`): a greeting, one **Create a video** button and a card per production with a
still (the rendered video's thumbnail, else the first preview still, else a contact sheet), the website, the shape,
when it last changed and its status in plain words: *Getting started*, *Pick an idea*, *Needs your review*,
*Making the video… 42%*, *Ready to post*, *Posted on LinkedIn*. A card opens the step that is next. With no
productions it shows a first-video prompt (or **Add your website first** when there is no website yet).

**Create a video** (`#/create`, `#/create/<production>`) walks the same workflow in six steps with a progress header:
1 Website → 2 What to promote (product, price, audience, what viewers should do, closing line; length "Let the story
decide" by default; vertical, wide or both) → 3 Pick an idea (the concepts task; three cards with hook, summary,
scene count, estimated length and claims to check) → 4 Review (build the preview, look at every scene, approve it
with your name; **Edit words and scenes** opens the Storyboard page with the frame-by-frame player) → 5 Make the
video (render progress in plain stage names; stop; try again) → 6 Approve & share (watch, check the open review items
with a note each, approve with your name; then download the videos, cover and captions, copy the title and
description, and record **I posted it on…**). Every step uses the same endpoints as the pages below, so the
rules are the same: a named person approves the preview and the video, nothing is approved or posted for you.
The power-user pages are under **Advanced** in the sidebar (the old Dashboard is **Overview**).

**Look:** one token system in `studio/web/src/styles.css` (spacing 4/8/12/16/24/32/48/64; type 28/22/16/14/13 with
fixed line heights; controls 32/40/48 high; radii 8/12/16), Host Grotesk and Geist Mono (OFL, vendored in
`public/shared/fonts/`), Lucide glyphs inlined in `studio/web/src/icons.tsx`, platform logos in
`public/shared/logos/platform-*.svg` (records in `public/shared/assets.json`). Nothing loads from the network.

## Sections (keys 1–9 follow the sidebar order, `?` for shortcuts)

| # | Section | What it does |
|---|---|---|
| 1 | Dashboard | brand filter chips with production counts; stats (needs you, productions, jobs, disk incl. archive, memory/swap); **Needs your attention** queue; **Brands** overview; **Pipeline** funnel and recent productions; jobs; system (scheduler queue, benchmark render defaults, Studio tasks) |
| 2 | New Production | brief form (brand, product, price, audience, format, duration, goal, tone, voice, CTA, request/notes, production name) → create → generate 3 concepts (comparison + fact-check) → select one. If the creative engine fails, the error is shown and **Write storyboard manually** still works |
| 3 | Storyboard | scene list (duration estimate at 2.33 words/s, the measured local-voice rate), forms for common block fields + JSON per block, cues/SFX JSON, add/duplicate/reorder/remove scenes, Validate, Save (⌘S, server-side validation with every error path), history, **Low-cost preview** (stills + contact sheet + quality gate), Render… |
| 4 | Asset Library | brand filter, category, search, licence/attribution/usage; image previews and audio players for files under `public/` and `output/` |
| 5 | Render Monitor | stage pipeline, progress, chunk table (fps, tabs, RSS, swap Δ, page-outs), memory, scheduler queue, live log tail, events, errors, request cancel |
| 6 | Preview & QA | before the render: the **preview review panel**; after it: final MP4 per format, voiceover, contact sheet, captions, audio report, QA checks grouped FAIL/WARN/PASS, branding/visual QA, claims and pronunciation, review flags with resolve (reviewer + note) |
| 7 | Publishing | "Nothing has been published" until a PUBLISHED record exists; video, thumbnail, metadata, transcript, credits, platform metadata, package hash, Approve / Request changes / Reject, Export (approved only), Publish (approved only, type the production id), the brand's publishing status |

**Library → Archived** lists what is in `output/_archive/` (state when archived, size) and **Restore…** moves a production (with its render jobs) or a loose job back, with your name; it refuses if the original folder exists again (never overwrites). CLI: `video-pipeline archive --list` / `archive --restore P --actor "Name"`.

### Dashboard

- **Needs your attention** lists the decisions only a person can make, most urgent first: review a preview before
  rendering, fix a storyboard that failed the preview gate, watch and decide on a video awaiting approval, revise
  after requested changes, look at a failed production, export or publish an approved one, and finish setting up a
  draft brand. Each item has a button that opens the right section.
- **Brands** shows, per brand: website, draft status, the number of verified facts, unverified claims, when the
  facts were last checked, and whether YouTube and Instagram credentials are present (presence only, never
  contents).
- **Pipeline** is a funnel (Draft → Storyboard → Preview review → Rendering → Final approval → Approved →
  Published); the two stages that wait for a person are highlighted. Recent productions show the state, the
  **preview gate** result (with "approved" once a person approved the preview) and the **QA** result.

### Preview & QA: the preview review panel

After a low-cost preview, and before any render, this section shows the storyboard contact sheet (one still per
scene, estimated timings, no voice) and every quality-gate check with its status. **Approve preview for rendering**
needs your name (an optional note says what you checked) and records a preview approval for that exact storyboard.
It is refused if the gate FAILed or if the storyboard changed after the preview; build a new preview first. The
approval allows the full render; it is not the final approval.

### Websites: suggested facts

**Add a website** also reads a few of the site's own pages (at most 6, one GET each, with a pause between
them) and lists **Suggested facts**: prices (amount, currency, period, billing, with the plan name from the card
title), numeric specs (storage, websites, bandwidth, RAM, CPU, users, projects…), guarantees and inclusions
(money-back, uptime, free SSL/domain, backups, 24/7 support, free trial) and the site URL. They are stored in
`knowledge/<brand>/candidates.json`, never in `facts.json`, and every one is NEEDS_REVIEW. Each shows the exact
text it was found in, with the number highlighted. **Add as fact** opens the same "I checked this on the website"
dialog (your name and the tick are required); the Studio reads the page again and adds the fact only if that exact
text is still there. **Reject** removes it, and it is not suggested again. Both are recorded in the audit log.
**Find facts on the website** runs the same search again for an existing brand. Prices that the page draws with
JavaScript, shows in images or hides behind a monthly/yearly toggle may be missing: add those by hand.
Routes: `GET /api/brands/<id>/candidates`, `POST …/candidates/extract` (task), `…/candidates/confirm
{candidateId, reviewer, confirm: true, note?}`, `…/candidates/reject {candidateId, reviewer, note?}`.

### Publishing: per-brand status

For the production's brand, YouTube and Instagram each show **configured** or **not configured** with the reason:
no `.pipeline/secrets/<brand>/<platform>.json`, or no expected account in `brand.json → publishing.accounts`.
Credentials are verified against the platform only when you publish. The Studio's publish dialog uploads to
YouTube or writes an export package; Instagram Reels are published from the CLI
(`video-pipeline publish --platform instagram …`, see [SOCIAL_PUBLISHING.md](SOCIAL_PUBLISHING.md)).

Long operations (concepts, storyboard generation, preview, render start, YouTube upload) run in background threads;
the UI polls `GET /api/tasks/<id>`. Renders are detached processes (`api.start_render`) and keep running if the Studio stops.

## Rules the Studio cannot break

* A full render needs a preview approval by a named person for the current storyboard (same rule as
  `production approve-preview`).
* Nothing publishes on a timer, on QA success or on approval. Only `POST /api/productions/<id>/publish` with
  `{"confirm": true, "actor": "…", "typedProductionId": "<id>"}` calls `pipeline.publishing.publish`, which re-checks
  the approval, the video hash and the brand's account. YouTube needs `.pipeline/secrets/<brand>/youtube.json`
  (chmod 600) and the brand's expected channel; uploads are private.
* Approval needs a reviewer name, a built package, completed QA (PASS/WARN) and every blocking flag resolved.
* Every time a production is loaded, `Productions.check_approval` re-hashes the package; any change invalidates the
  approval and returns the production to AWAITING_APPROVAL.

## Security

* Binds `127.0.0.1` only; a random session token (persisted, 0600) → `HttpOnly; SameSite=Strict` cookie (or
  `Authorization: Bearer`).
* `Host` must be `127.0.0.1:<port>` or `localhost:<port>` (DNS rebinding); a present `Origin`/`Sec-Fetch-Site` must be same-origin.
* POST/PUT must be `application/json` (≤ 4 MB); no CORS headers; OPTIONS/DELETE refused.
* Strict CSP (`default-src 'none'; script-src 'self' …; frame-ancestors 'none'`), `nosniff`, no framing, no referrer.
* Files only through `pipeline.api.safe_output_file` (`output/` and `public/`, plus audio files from `audio/kit` and
  `audio/music`; never `.pipeline` or `secrets`; dot-path segments refused); user files are served with
  `Content-Security-Policy: sandbox` and HTML/JS as text/plain.
* No shell commands; the token is never logged.

Tests: `uv run pytest tests/test_studio_server.py tests/test_studio_token.py tests/test_dashboard.py`.

## Endpoints

```
GET  /api/session | /api/dashboard[?brand=] | /api/brands | /api/storyboard/schema | /api/productions | /api/jobs | /api/tasks[/<id>]
GET  /api/productions/cards                          Home grid: id, name, brand, state, format, thumbnail, job progress, preview_approved, has_concepts, posted[]
POST /api/productions                                {brand, name?, brief{product, price, audience, format, duration_seconds, goal, tone, voice, cta, request}}
GET  /api/productions/<id>  ·  /api/productions/<id>/outputs
POST /api/productions/<id>/concepts | /select {conceptId} | /preview | /render          -> {task}
POST /api/productions/<id>/approve-preview {reviewer, note?}
PUT  /api/productions/<id>/storyboard {storyboard}   ·  POST …/storyboard/validate {storyboard}
POST /api/productions/<id>/package | /flags/<n>/resolve {reviewer, note} | /approve {reviewer, note?, packageHash?}
POST /api/productions/<id>/decision {decision: REJECTED|CHANGES_REQUESTED, reviewer, note}
POST /api/productions/<id>/export {confirm: true, actor, format?}
POST /api/productions/<id>/publish {confirm: true, actor, typedProductionId, platform: youtube|export, format?}
GET  /api/publish/status?brand= · /api/assets?brand= · /api/jobs/<job>/monitor   ·  POST /api/jobs/<job>/cancel
GET  /files/<output/… | public/… | audio/kit/… | audio/music/…>   (Range supported)   ·   /static/app.{js,css}
```

## Known limitations

* Audio under `audio/` (sound kit, music library) is listed in the Asset Library but not playable there: the UI plays
  only files under `output/` and `public/`.
* Single local user. Tasks are in memory (a restart forgets task status, not results).
* Instagram publishing, social metadata drafting and keyword research are CLI-only (`video-pipeline social …`).
