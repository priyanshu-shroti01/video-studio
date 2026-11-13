# Social setup: connecting each brand's YouTube channel and Instagram account

Do this once **per brand**. Every brand (`brands/<id>/`) has its own channel, its own Instagram account, its
own credentials in `.pipeline/secrets/<id>/` and its own expected account ids in
`brands/<id>/brand.json → publishing.accounts`. Publishing refuses unless the platform confirms that the
credentials belong to the expected account, so a video of one brand cannot be posted to another brand's
account by mistake. Examples below use `shrotihost`; repeat with your other brand ids.

Nothing here is done by the pipeline or by an AI assistant: you create the projects, sign in and store the secrets.

## 0. Secrets directory

```bash
mkdir -p -m 700 .pipeline/secrets/shrotihost
chmod 700 .pipeline/secrets
```
Files inside must be `chmod 600`; the adapters refuse anything readable by others. `.pipeline/` is
git-ignored. An old single `.pipeline/secrets/youtube.json` (v0.3.0) is **not** used any more. If you have
one, move it into the brand it belongs to:
`mv .pipeline/secrets/youtube.json .pipeline/secrets/shrotihost/ && chmod 600 .pipeline/secrets/shrotihost/youtube.json`.

## 1. YouTube (Google Cloud, YouTube Data API v3)

One Google Cloud project can serve all brands; each brand gets its own refresh token for its own channel.

1. https://console.cloud.google.com/ → create a project (e.g. "video-studio").
2. **APIs & Services → Library → YouTube Data API v3 → Enable.**
3. **Google Auth Platform / OAuth consent screen:** User type *External*; app name; your support email;
   add yourself as a test user. Scopes: `.../auth/youtube.upload` and `.../auth/youtube.readonly`.
   While the app is in **Testing**, Google expires refresh tokens after **7 days**. For lasting tokens set
   the publishing status to **In production** (Google may require verification for sensitive scopes; until
   then you can keep re-running step 5).
4. **Clients → Create client → Application type: Desktop app.** Download the JSON (`client_secret_….json`).
   Keep it outside the repo or delete it after step 5.
5. Get the refresh token with the local loopback helper (opens your browser, listens on
   `http://127.0.0.1:<random port>`, PKCE, never prints tokens):
   ```bash
   uv run python scripts/youtube_oauth.py --brand shrotihost --client-secrets ~/Downloads/client_secret_XXXX.json
   # optional: --api-key   (hidden prompt for a Data API key used only by keyword research)
   # optional: --privacy unlisted   (default upload privacy; "private" is the default)
   ```
   Sign in with the Google account that owns **this brand's** channel and choose that channel if asked. The
   script writes `.pipeline/secrets/shrotihost/youtube.json` (0600) and prints the authorised channel id.
6. Put that id in `brands/shrotihost/brand.json`:
   ```json
   "publishing": { "accounts": { "youtube": { "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx", "channel_title": "Shroti Host" } } }
   ```
   (Channel ids are not secret. YouTube Studio → Settings → Channel → Advanced also shows it.)
7. Check (offline): `uv run video-pipeline social accounts --brand shrotihost`.

Notes
- Uploads default to `private` (`privacyStatus` in `youtube.json` may be `private` or `unlisted`; `public` is
  used only if you write it there yourself). Scheduled uploads (`social draft --publish-at …`) are always private
  until the scheduled time.
- Quota (2026-11-13 docs): 100 uploads/day in their own bucket, plus 10,000 units/day for other calls. More needs
  Google's "YouTube API Services – Audit and Quota Extension" form.
- Custom thumbnails (`social draft --set-thumbnail`) need a verified channel (phone verification).
- Optional keyword research via the Data API: create an **API key** (Credentials → API key, restrict it to
  "YouTube Data API v3") and store it as `"api_key"` in the brand's `youtube.json` (or use `--api-key` above).

## 2. Instagram (Meta, Instagram Platform API, Reels)

Local video files can only be uploaded with **resumable upload**, which Meta offers to apps using
**Facebook Login for Business** (`graph.facebook.com` + `rupload.facebook.com`). The "Instagram Login" variant
(`graph.instagram.com`) needs the video on a public URL and is refused by this pipeline.

1. Make the brand's Instagram account a **professional account** (Business or Creator) and link it to a
   **Facebook Page** of that brand (Instagram → Settings → Account type and tools / Accounts Center).
2. https://developers.facebook.com/apps → **Create app** (type *Business*). Add the products
   **Facebook Login for Business** and **Instagram** (Instagram API with Facebook Login).
3. Permissions to request (Meta docs, 2026-11-13): `instagram_basic`, `instagram_content_publish`,
   `pages_read_engagement` (and `ads_management` or `ads_read` if your Page role comes through Business
   Manager). Your own accounts work in development mode with you as an app admin/tester; App Review is needed
   only for other people's accounts.
   (If you ever use Instagram Login instead, the names are `instagram_business_basic` and
   `instagram_business_content_publish`, but that login type cannot upload local files.)
4. Get a token with Graph API Explorer (https://developers.facebook.com/tools/explorer): select your app,
   *User Token*, tick the permissions, generate, approve for the brand's Page and Instagram account.
5. Exchange it for a **long-lived** token (about 60 days):
   `GET https://graph.facebook.com/v27.0/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=SHORT_TOKEN`
   (run it yourself, e.g. in Graph API Explorer or `curl`; don't paste the token anywhere else). A Page token
   fetched with a long-lived user token (`GET /me/accounts`) has no expiry date and also works.
6. Find the Instagram user id: `GET /me/accounts?fields=name,instagram_business_account` → the
   `instagram_business_account.id` of the brand's Page (looks like `17841…`).
7. Write `.pipeline/secrets/shrotihost/instagram.json` and `chmod 600` it:
   ```json
   {"ig_user_id": "17841…", "access_token": "EAAG…", "api_host": "graph.facebook.com", "api_version": "v27.0",
    "token_expires_at": "2027-01-12T00:00:00Z", "app_id": "…", "app_secret": "…"}
   ```
   `app_id`/`app_secret` are needed only for `social token-refresh`.
8. Put the same id in `brands/shrotihost/brand.json → publishing.accounts.instagram.ig_user_id` (and
   `username` for readability).
9. Before the token expires: `uv run video-pipeline social token-refresh --brand shrotihost` (re-exchanges a
   Facebook Login user token for a new ~60-day one; only the new expiry is printed). If it already expired,
   repeat steps 4–7.

Publishing rate limit: checked before every upload via `content_publishing_limit` (`quota_total` per 24 h; the
reference page says 50).

## 3. Use

```bash
uv run video-pipeline social plan  --id <P>                 # where can each rendered video go, and why
uv run video-pipeline social draft --id <P>                 # before approval; local LLM, template fallback
uv run video-pipeline social keywords --id <P> --network    # optional; shows the exact outgoing queries
uv run video-pipeline approve --id <P> --reviewer "Name"    # approve the package incl. metadata.json
uv run video-pipeline publish --id <P> --platform youtube   --format short --actor "Name" --confirm
uv run video-pipeline publish --id <P> --platform instagram --format short --actor "Name" --confirm
```

The same is available to AI assistants through the MCP server `video-pipeline-mcp` (see docs/SOCIAL_PUBLISHING.md → MCP server).
Approve the server when your MCP client asks; never add the publish tools to an allowlist.

## 4. Adding another brand

1. Create `brands/<id>/{brand.json,theme.json,assets.json}` and `knowledge/<id>/facts.json` (see BRANDING.md).
2. In `brand.json → publishing` add `privacyDefault`, `accounts` and a `social` block: `voice`, `link`,
   `language`, `region`, `categoryId`, `aiDisclosure`, `cta.youtube`, `cta.instagram` (a "link in bio" line),
   `hashtags.youtube|instagram`, optional `bannedPhrases`, and `products[]` with `id`, `match`, `factProduct`,
   `primaryKeyword`, `keywordSeeds` (generic search phrases: the only text keyword research sends),
   `tags`, `highlightFactIds` and `hashtags`. `brands/shrotihost/brand.json` is a complete example.
3. Do sections 0–2 with that brand id.
