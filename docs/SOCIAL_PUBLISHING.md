# Social publishing (YouTube + Instagram Reels)

The social layer turns an approved production into platform uploads. It is multi-brand: every rule that
is specific to a brand lives in `brands/<id>/brand.json` and `knowledge/<id>/facts.json`, and every brand
has its own credentials and its own expected accounts. Nothing is ever published automatically. Setup is in
[SOCIAL_SETUP.md](SOCIAL_SETUP.md); the approval rules are in [PUBLISHING_APPROVAL.md](PUBLISHING_APPROVAL.md).

```
 render + QA ──► social plan (ffprobe routing) ──► social draft (local LLM / template) ──► approval package
                                                       publishing/metadata.json            (hash covers it)
                                                                                                │ human approves
                                                                                                ▼
   publish --platform youtube|instagram --actor NAME --confirm   (or MCP publish_* tool, on the user's request)
        └─► publishing.gate(): APPROVED · approval still valid · QA ok · video hash = approved hash
        └─► brand-bound account check: brand.json publishing.accounts == platform "who am I"
        └─► adapter upload (YouTube Data API v3 / Instagram resumable Reels) ─► publications + audit log
```

| Module | Role |
|---|---|
| `pipeline/social/routing.py` | ffprobe the real file → destinations with reasons |
| `pipeline/social/metadata.py` | YouTube + Instagram metadata: template + local LLM, validation, `metadata.json` writer |
| `pipeline/social/keywords.py` | opt-in search-demand research (network), seed phrases only, 24 h cache |
| `pipeline/social/instagram.py` | Instagram Reels adapter (resumable upload), token refresh helper |
| `pipeline/social/brandcfg.py` | per-brand social config, expected accounts, per-brand secrets |
| `pipeline/social/service.py` | functions shared by the CLI and the MCP server |
| `pipeline/social/cli.py` | `video-pipeline social plan|draft|keywords|status|list|accounts|token-refresh` |
| `pipeline/social/mcp_server.py` | stdio MCP server `video-pipeline-mcp` |
| `pipeline/publishing.py` | `gate()`, export, YouTube adapter, `publish()` for both platforms |
| `scripts/youtube_oauth.py` | one-time loopback OAuth helper (per brand) |

## Routing

Routing is decided from the actual video file (width/height after rotation, duration, size, fps, codecs),
never from the format name.

| Video | YouTube | Instagram |
|---|---|---|
| 9:16, ≤ 180 s | **Short** | **Reel** |
| 9:16, 180 s – 15 min | regular video (too long for Shorts; a suggestion to cut a ≤ 180 s version) | **Reel** (within the API's 3 s – 15 min, ≤ 300 MB) |
| 9:16, > 15 min or > 300 MB | regular video | refused, with the reason |
| 16:9 | regular video **with chapters** (≥ 3 chapters of ≥ 10 s, else skipped) | **never**; the plan suggests rendering the 9:16 `short` format |
| square / other | Short if ≤ 180 s, else regular | refused (only 9:16 is routed to Reels) |

`uv run video-pipeline social plan --id <P>` prints the plan; the MCP tool `plan_platforms` returns it as JSON.
`publish --platform instagram` probes the file again and refuses anything that is not eligible.

## Metadata (`publishing/metadata.json`)

`social draft` writes one versioned document per production (`schema: social-metadata/1`, `version`,
`source: llm | llm+template | template`, the LLM log, the fact-base timestamp, per-format entries and the
validation result) and keeps `title.txt`, `description.md` and `hashtags.txt` identical to the primary
format's YouTube entry. Earlier versions (and the render's original files) are kept in
`publishing/history/<timestamp>/`. Drafting adds an advisory review flag ("read metadata.json before
approving") and, if validation fails, a blocking one.

**Who writes what.** The local LLM (or the deterministic template) writes only free text: title, hook,
summary, Instagram hook/body, optional first comment, extra tags. The system adds everything structured:
the link and CTA (brand profile), plan/price lines (facts only, re-verified line by line), chapters (real
voice timings), hashtags (brand profile), category, languages, disclosures. Each LLM field that fails
validation is replaced by the template's field; if nothing usable remains, the whole draft is the template.

**YouTube** (per format): title ≤ 100 chars with the primary keyword in the first 60; description with the
hook and the brand link in the first 150 characters, a verified plan list, chapters (landscape), an
AI-voice disclosure line, licence credits carried over from the render, and 3 hashtags; tags ≤ 500 characters
counted YouTube's way (commas, plus quotes around tags with spaces); `categoryId` from the brand (28 =
Science & Technology); `defaultLanguage`/`defaultAudioLanguage`; `selfDeclaredMadeForKids: false`;
`containsSyntheticMedia: true`; privacy from the brand (`private` by default); optional `publishAt`
(forces `private`); optional `set_thumbnail`.

**Instagram Reels**: caption ≤ 2,200 characters; the first line is the hook (only ~125 characters show
before "more"); short paragraphs; a verified price line; the brand's "link in bio" CTA (caption links are
not clickable); an AI-voice note; 3–5 specific hashtags (never `#fyp`, `#viral`, `#explore`, …);
`share_to_feed: true`; cover = a video frame (`thumb_offset`, the thumbnail's moment) because `cover_url`
needs a public image URL; `is_ai_generated` from the brand profile; optional first comment.

**Validation** (blocking when it fails): lengths and byte limits, `<`/`>` in YouTube text, link position,
tag budget, hashtag count/format/banned list (also inside the caption/description), unverified claims (every
price, number, plan, URL and risky term must be backed by `knowledge/<brand>/facts.json`; nothing is trusted
because a brief said it), clichés, brand-banned phrases (`publishing.social.bannedPhrases` +
`creative.banned`), ALL-CAPS words, exclamation spam, chapter rules, `publishAt` in the future with a timezone.
Known gap: like the storyboard claim checker, it does not catch number-free claims such as "no extra cost";
the reviewer must read the metadata.

## Approval rule

Metadata is part of the approval package (`productions.package_files` includes `publishing/metadata.json`
alongside title, description, hashtags and thumbnail). So it must be drafted **before approval**:
`social draft` works only in `QA_COMPLETE` / `AWAITING_APPROVAL` and rebuilds the package so the reviewer
approves what will be published. After approval it refuses with *"approval would be invalidated: request
changes first"*. A person can deliberately withdraw an approval to redraft:
`video-pipeline social draft --id <P> --reopen-review --actor "Name"` (audited; not available via MCP).
Any edit to an approved metadata file invalidates the approval automatically.

## Publishing

```bash
uv run video-pipeline publish --id <P> --platform youtube   --format short --actor "Name" --confirm
uv run video-pipeline publish --id <P> --platform instagram --format short --actor "Name" --confirm
```

`publish()` requires `gate()` plus: a valid metadata document (if present; Instagram requires one), the
brand's expected account in `brand.json`, per-brand credentials, and that the platform says the credentials
belong to that account (`channels.list?mine=true` / `GET /<ig_user_id>?fields=id,username`). It refuses a
duplicate upload of the same video to the same platform, re-hashes the file right before the bytes leave,
records every attempt in `publications` and the audit log, and returns what was sent. A production stays
publishable to the other platform after its first upload (`PUBLISHED` + still-valid approval).

## MCP server

Run it as `uv run video-pipeline-mcp` (stdio; logs on stderr; stdout is the protocol). To use it from an MCP client,
register it in the client's MCP configuration, run from the repository root:

```json
{"mcpServers": {"video-pipeline-social": {"command": "uv", "args": ["run", "video-pipeline-mcp"]}}}
```

Every
tool takes or derives the brand from the production; a `brand_id` that does not match is refused.

| Tool | Annotations | What it does |
|---|---|---|
| `list_publishable` | readOnly, not destructive, closed world | productions with a rendered package, **grouped by brand**, with account status |
| `plan_platforms` | readOnly, closed world | routing plan from ffprobe |
| `publication_status` | readOnly, closed world | approvals, publications, open review flags |
| `draft_metadata` | not readOnly, not destructive, closed world | local LLM / template draft; refused after approval |
| `keyword_research` | readOnly, **openWorld** | seed-only research; returns the exact outgoing URLs |
| `publish_youtube` | **destructive, openWorld** | `publishing.publish(confirm=True)` through `gate()`; needs `actor`, `production_id`, `format` |
| `publish_instagram_reel` | **destructive, openWorld** | same, Instagram Reels |

Approvals, review-flag resolution, approval withdrawal, credentials and token refresh are deliberately not
tools. An AI assistant may call a publish tool only when the user explicitly asked to publish that production to that
platform, and publish tools must never be put on a permissions allowlist.

## Limits and quotas (checked 2026-11-13)

| Item | Value | Source |
|---|---|---|
| YouTube Shorts | square or vertical, up to 3 minutes | support.google.com/youtube/answer/15424877 |
| YouTube title / description / tags | 100 chars / 5,000 bytes / 500 chars (commas and implied quotes count); no `<` `>` | developers.google.com/youtube/v3/docs/videos |
| `publishAt` | only with `privacyStatus: private` on a never-published video; ISO 8601 | same |
| YouTube quota | default 10,000 units/day **plus** separate buckets of 100 `videos.insert` and 100 `search.list` calls/day; `videos.insert` = 1 unit in the "Video Uploads" bucket; `search.list` = 1 unit in "Search Queries"; `channels.list`/`videos.list` = 1; `thumbnails.set` ≈ 50; `videos.update` = 50. Reset at midnight Pacific | developers.google.com/youtube/v3/determine_quota_cost, …/guides/quota_and_compliance_audits |
| Older figures | the commonly quoted "1,600 units per upload" and "search = 100 units" are the **previous** model; the current pages say otherwise | as above |
| Unaudited API projects | the current `videos.insert` page says uploads from unverified projects are **not** restricted to private viewing; more quota needs the (form-based) audit. We still upload `private` by default | developers.google.com/youtube/v3/docs/videos/insert |
| Custom thumbnails | `thumbnails.set` works for videos and Shorts after processing succeeds; the channel must be verified; ≤ 50 MB (Studio: 2 MB on mobile) | developers.google.com/youtube/v3/docs/thumbnails/set, support.google.com/youtube/answer/72431 |
| Instagram Reels file | MP4/MOV, H.264/HEVC, AAC ≤ 48 kHz, 23–60 fps, ≤ 1920 columns, 3 s – 15 min, ≤ 300 MB, 9:16 recommended | developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media |
| Instagram caption | ≤ 2,200 chars, ≤ 30 hashtags, ≤ 20 @-tags (we use 3–5 hashtags) | same |
| Instagram publishing limit | `content_publishing_limit` reports `quota_total` (reference page: "currently 50" per 24 h; overview page: 100). Checked before every upload | …/reference/ig-user/content_publishing_limit, developers.facebook.com/documentation/instagram-platform/content-publishing |
| Resumable upload | Facebook Login for Business only (`graph.facebook.com` + `rupload.facebook.com`); Instagram Login (`graph.instagram.com`) needs a public `video_url`, which this pipeline does not have | …/content-publishing/resumable-uploads |
| Container | expires if not published within 24 h; Meta suggests polling `status_code` once a minute for up to 5 min | content-publishing |
| Graph API version | v27.0 in the current docs (configurable `api_version`) | same |
| Tokens | Facebook long-lived user token ≈ 60 days (extend by re-exchange); Page token from it does not expire; Instagram Login token 60 days, refreshable after 24 h. Google: refresh tokens of "Testing" consent screens expire after 7 days | developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived, …/instagram-platform/reference/refresh_access_token, developers.google.com/identity/protocols/oauth2 |

## Privacy: what leaves the machine

| Action | Sent | To |
|---|---|---|
| `social plan`, `draft`, `status`, `list`, `accounts` | nothing (drafting uses Ollama on 127.0.0.1 only) | — |
| `social keywords --network` / `keyword_research` | only generic seed phrases from `brand.json` (+ extra seeds that are plain lowercase words); every URL is returned; API keys redacted in results and cache | suggestqueries.google.com (undocumented YouTube autocomplete endpoint), optionally googleapis.com |
| `publish --platform youtube` | the approved video, metadata from `metadata.json`, optionally the thumbnail; OAuth token exchange | oauth2.googleapis.com, www.googleapis.com |
| `publish --platform instagram` | the approved video and caption/cover settings | graph.facebook.com, rupload.facebook.com |
| `social token-refresh` | the token being extended (+ app id/secret for Facebook Login) | graph.facebook.com / graph.instagram.com |

Briefs, narration, storyboards and voice audio are never sent to any external AI service. Secrets live in
`.pipeline/secrets/<brand>/` (files 0600, directory 0700), are never printed, logged or returned by MCP tools, and
are kept out of URLs (the `Authorization` header) except in the two token-refresh calls, which Meta defines as GET
query parameters.

**Not exercised against the real services.** All tests use fake transports; no upload, OAuth flow or
platform API call has been made from this repository.
