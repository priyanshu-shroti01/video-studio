# Publishing approval

**The system never publishes on its own.** The preview, QA success and approval each stop and wait for a
person. Uploading needs a separate, explicit command with `--confirm` (or the Studio's typed-confirmation
dialog), and is checked again right before any bytes leave the machine.

## Production states

```
DRAFT → STORYBOARD_READY → PREVIEW_READY → RENDERING → QA_COMPLETE → AWAITING_APPROVAL → APPROVED → PUBLISHING → PUBLISHED
                 ↑                                                        │
                 └──────────── CHANGES_REQUESTED ◄────────────────────────┤        side states: REJECTED, FAILED, CANCELLED
```

Transitions are validated in `pipeline/productions.py` (an illegal jump raises `INVALID_STATE_TRANSITION`).
Before RENDERING, a named person must approve the storyboard preview (`production approve-preview`; see
[QA_GUIDE.md](QA_GUIDE.md#human-preview-approval)). That approval is bound to the storyboard hash and only allows
the render; it is not the final approval described below.
Every human decision is written to the `audit_log` table with actor, time and detail.

## The approval package

When the render job completes QA, the production moves to `AWAITING_APPROVAL` and
`output/productions/<id>/approval/` gets:

- `APPROVAL_PACKAGE.md`: title, QA summary, review flags, and the sha256 of every file
- `approval-manifest.json`: machine-readable version; its **package hash** is the sha256 over all file hashes

Files covered: final video(s), thumbnail, title, description, hashtags, **social metadata
(`publishing/metadata.json`: YouTube snippet/status/chapters, Instagram caption/cover/hashtags)**, captions (SRT),
QA report (JSON + MD), audio report, asset/credit manifest, and, when present, the branding report, visual-QA report, claims report,
pronunciation checklist and alignment report.

## Review flags

| Severity | Raised for | Blocks approval |
|---|---|---|
| blocking | QA FAIL; unknown asset licence; test-only music; unverified commercial claim (`claims-report.json`); branding FAIL; a render started without a preview review (`human:preview-not-reviewed`, audited override only); **mandatory human checks: pronunciation, final watch-through** | yes, until a named reviewer resolves it with a note |
| advisory | QA WARN items | no (shown for information) |

The two human checks are always raised, because automated QA cannot judge pronunciation or overall
quality. `reports/pronunciation-checklist.md` lists every brand/technical term with its spoken form and
timestamp.

`video-pipeline social draft` (or the MCP `draft_metadata` tool) adds an advisory `metadata:review` flag
(read `publishing/metadata.json` before approving: it is published exactly as approved) and, if the metadata
fails validation, a blocking `metadata:invalid` flag. Draft metadata **before** approving: drafting is refused
once a production is `APPROVED` ("approval would be invalidated: request changes first"). To redraft an approved,
not yet published production, a person withdraws the approval explicitly:
`uv run video-pipeline social draft --id <P…> --reopen-review --actor "Name"` (audited).

## Approve / reject

```bash
uv run video-pipeline production show --id <P…>                       # state + flags
uv run video-pipeline review resolve --id <P…> --flag 12 --reviewer "Name" --note "listened, fine"
uv run video-pipeline approve --id <P…> --reviewer "Name" [--package-hash <hash you reviewed>]
uv run video-pipeline request-changes --id <P…> --reviewer "Name" --note "price card too dense"
uv run video-pipeline reject --id <P…> --reviewer "Name" --note "off-brand"
```

Approval is refused if: the state isn't `AWAITING_APPROVAL`; there's no reviewer name; the render job isn't
COMPLETED with QA PASS/WARN; any blocking flag is open; the package changed since it was built; or
`--package-hash` doesn't match the current package.

**Invalidation:** the approval stores the package hash. Whenever a production is loaded (Studio, `publish`,
`export`), the hash is recomputed. If any approved file changed (video, title, description, hashtags,
thumbnail, captions, reports), the approval is marked invalidated, the production returns to
`AWAITING_APPROVAL`, and the event is audited. Tested by `test_any_change_after_approval_invalidates_it`.

## Export and publish

```bash
uv run video-pipeline export --id <P…>                                 # local upload-ready package + zip + SHA256SUMS
uv run video-pipeline publish --id <P…> --platform youtube   --format short --actor "Name" --confirm
uv run video-pipeline publish --id <P…> --platform instagram --format short --actor "Name" --confirm
```

`publishing.gate()` requires all of: state `APPROVED` (or `PUBLISHED` to another platform with the same,
still-valid approval), a still-valid approval, job QA PASS/WARN, and that the exact video file hashes to its
value in the approved package. `publish()` additionally requires a destination account **of the production's
brand**: `brands/<brand>/brand.json → publishing.accounts` names the expected YouTube `channel_id` / Instagram
`ig_user_id`, credentials come from `.pipeline/secrets/<brand>/`, and the platform's own "who am I" answer must
match before any byte is sent. It refuses duplicate uploads of the same video to the same platform, metadata that
failed validation, a past `publishAt`, and (Instagram) anything that is not 9:16 within the Reels limits. The video
hash is checked again immediately before the bytes leave the machine.

- **export** writes `output/productions/<id>/export/<fmt>-<hash>/` (video, thumbnail, title, description,
  hashtags, captions, credits, `platform-metadata.json` with YouTube/Instagram fields, `SHA256SUMS.json`)
  plus a zip. Nothing leaves the machine; the production stays `APPROVED`.
- **youtube** uses the official YouTube Data API v3 (resumable upload), only when
  `.pipeline/secrets/<brand>/youtube.json` (mode 600) holds `client_id`, `refresh_token` (and `client_secret` if the
  client has one). Snippet and status come from the approved `metadata.json` (tags, category, languages,
  optional `publishAt`, optional thumbnail). Uploads are `private` by default and declare
  `containsSyntheticMedia: true` (the narration is synthetic). A failure returns the production to `APPROVED`
  with the error recorded.
- **instagram** uses the official Instagram Platform API (Facebook Login for Business), Reels with resumable upload
  of the local file, only when `.pipeline/secrets/<brand>/instagram.json` (mode 600) is set up; it checks the
  account's publishing limit first. Landscape video is never sent to Instagram.
- The legacy global `.pipeline/secrets/youtube.json` is not used (it is not tied to a brand); move it into the
  brand's directory (SOCIAL_SETUP.md).
- The MCP publish tools (`publish_youtube`, `publish_instagram_reel`) call the same `publish(confirm=True)`; an AI
  assistant using the MCP server may call them only when the user explicitly asked to publish that production to that
  platform.

**The automated tests use fake transports; they never call a live platform API.**

The Studio's Publishing Center calls the same functions and additionally requires typing the production id.
