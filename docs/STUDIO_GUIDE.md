# Local Video Studio

A desktop-browser UI over the same service layer the CLI uses (`pipeline/api.py`, `pipeline/productions.py`,
`pipeline/publishing.py`). The CLI (`uv run video-pipeline …`) stays the primary automation interface; the Studio
cannot bypass validation, the scheduler, the preview review or the approval gate because it only calls those
functions.

## Launch

```bash
videostudio                              # after install.sh: starts the Studio and opens your browser (stop / status / update / doctor)
uv run python -m studio.build            # developers: after changing studio/web/src (esbuild -> studio/web/dist)
uv run video-pipeline studio --open      # or: uv run python -m studio.server  (--port 8765 default · --open · --new-token)
```

Use Chrome or Safari. VS Code's built-in browser has no AAC decoder and may block audio: the Studio's players use a
copy with Opus audio (`output/_play/`), but that browser can still stay silent.

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
- **Help button:** a round **?** button at the bottom right of every page opens the [help chat](#help-chat).
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
| 1 | Home | your videos as cards (still, brand, shape, last change, plain status, next step); click a card to continue |
| 2 | Create a video | the six-step wizard: website → what to promote → pick an idea → review (preview, quality gate, approve with your name) → make the video (progress, stop, retry) → approve & share (downloads, title/description, "I posted it on…") |
| 3 | Library | Productions and Archived lists; "I posted it on…", Archive…, Restore… (each with your name) |
| 4 | Websites & facts | add a website; verified facts with their source text; suggested facts to confirm or reject; re-check against the site |
| 5 | Overview *(Advanced)* | brand filter chips, stats (needs you, productions, jobs, disk, memory/swap), the **Needs your attention** queue, brands, pipeline funnel, jobs, scheduler |
| 6 | Storyboard *(Advanced)* | scene list, block forms + JSON, cues/SFX, Validate, Save (⌘S), history, **Low-cost preview** stills + quality gate, **Watch every frame** (the real engine in the browser: play, scrub, ±1 frame / ±1 s, loop a scene, both formats; **Use the real voice** records the narration locally for sound and exact timing; voice only, music and effects come with the render), Render… |
| 7 | Preview & QA *(Advanced)* | before the render: the preview review panel; after it: final video per format (with sound), voiceover, contact sheet, captions, audio report, QA checks, claims and pronunciation, review flags |
| 8 | Publishing *(Advanced)* | video, thumbnail, metadata, transcript, package hash, Approve / Request changes / Reject, Export, Publish (type the production id), the brand's publishing status |
| 9 | Render Monitor *(Advanced)* | stages, progress, chunk table, memory, scheduler queue, log tail, cancel |
| – | Brief form, Asset Library, Setup *(Advanced)* | the full brief form (incl. Quality and "Generate new components"); assets with licences; a plain checklist of what's installed |

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

## Help chat

The round **?** button at the bottom right of every page opens a small chat panel for how-to questions ("How do I
add my website?", "Why did my render fail?", "What does Preview & QA mean?"). It is answered by the same local AI
model the Studio already uses, so it costs nothing and nothing leaves the Mac.

- **Grounded in the guides.** The sections of this guide, [TROUBLESHOOTING.md](TROUBLESHOOTING.md),
  [INSTALL.md](INSTALL.md) and the README that best match the question (simple keyword match) go into the prompt,
  together with the page you are on (for example "Create a video, step 3 of 6 (Pick an idea)"). The answer names
  the sections it came from, and says so when the guides don't cover a question.
- **It only explains.** It has no buttons and calls no workflow action: it cannot approve, reject, render, archive
  or publish anything. It never states prices, plans or product facts; those come only from a brand's verified facts
  (a sentence with a price in an answer is replaced by a pointer to **Websites & facts**).
- **Scheduled like all AI work.** It runs under the scheduler (never alongside a render or the voice) and starts the
  local runtime only if needed, stopping it again if it started it; the model is unloaded after each answer. While a
  video renders it answers "The helper is paused while a video renders. Try again in a few minutes." instead of
  waiting. If the model isn't installed, or memory is too low, it says so in plain words (Setup shows how to add the
  model).
- **Limits.** A question is at most 500 characters; a chat holds 6 questions and answers (the server refuses more,
  and the panel offers **New chat**). One question is answered at a time. The conversation lives only in that tab;
  whether the panel is open is remembered for the browser session only (closed by default).
- **Keyboard.** The button and panel are reachable with Tab; Enter sends, Shift+Enter adds a line, Esc closes the
  panel and returns focus to the button. Answers are announced to screen readers. At narrow widths the panel spans
  the window. The pages keep enough space at the bottom that the closed button never covers their last buttons.

Route: `POST /api/help/ask {question, history?: [{role: user|assistant, content}], page?}` → `{status: ok | paused |
unavailable | error, message, sources[]}`; same cookie, Host, Origin and JSON checks as every other POST.

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

Tests: `uv run pytest tests/test_studio_server.py tests/test_studio_token.py tests/test_dashboard.py tests/test_help_chat.py`
(the help chat's model is always a stand-in there) and `npm test` (`studio/web/src/__tests__/`).

## Endpoints

```
GET  /api/session | /api/dashboard[?brand=] | /api/brands | /api/storyboard/schema | /api/productions | /api/jobs | /api/tasks[/<id>]
GET  /api/productions/cards                          Home grid: id, name, brand, state, format, thumbnail, job progress, preview_approved, has_concepts, posted[]
POST /api/productions                                {brand, name?, brief{product, price, audience, format, duration_seconds, goal, tone, voice, pace, language, cta, request}}
GET  /api/productions/<id>  ·  /api/productions/<id>/outputs
POST /api/productions/<id>/concepts | /select {conceptId} | /preview | /render          -> {task}
POST /api/productions/<id>/approve-preview {reviewer, note?}
PUT  /api/productions/<id>/storyboard {storyboard}   ·  POST …/storyboard/validate {storyboard}
POST /api/productions/<id>/package | /flags/<n>/resolve {reviewer, note} | /approve {reviewer, note?, packageHash?}
POST /api/productions/<id>/decision {decision: REJECTED|CHANGES_REQUESTED, reviewer, note}
POST /api/productions/<id>/export {confirm: true, actor, format?}
POST /api/productions/<id>/publish {confirm: true, actor, typedProductionId, platform: youtube|export, format?}
GET  /api/publish/status?brand= · /api/assets?brand= · /api/jobs/<job>/monitor   ·  POST /api/jobs/<job>/cancel
POST /api/help/ask {question, history?, page?}       help chat: {status: ok|paused|unavailable|error, message, sources[]}
GET  /files/<output/… | public/… | audio/kit/… | audio/music/…>   (Range supported)   ·   /static/app.{js,css}
```

`brief.language` is `english` (default) or `hinglish`. Hinglish means Latin-script Hinglish captions, spoken by the
Kokoro Hindi voice `hm_omega` unless `voice` names another one ([LOCAL_TTS](LOCAL_TTS.md#hinglish)). A Microsoft
Hindi voice (`"voice": "hi-IN-MadhurNeural"` or `"hi-IN-SwaraNeural"`) sounds more natural but is online, so it also
needs `"allow_online_voice": true` in the brief. The brief
form has no language picker yet, so set it through the API or the brief file. A Hinglish brief also writes the copy:
the concepts and the storyboard come out in Hinglish (copy bank and local LLM, see
[CREATIVE_SYSTEM](CREATIVE_SYSTEM.md#language-english-or-hinglish-brieflanguage)), and the storyboard editor's length
estimate uses the slower Hinglish rate (2.0 words/s instead of 2.33).

## Known limitations

* Audio under `audio/` (sound kit, music library) is listed in the Asset Library but not playable there: the UI plays
  only files under `output/` and `public/`.
* Single local user. Tasks are in memory (a restart forgets task status, not results).
* Instagram publishing, social metadata drafting and keyword research are CLI-only (`video-pipeline social …`).
