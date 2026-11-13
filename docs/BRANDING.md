# Branding

Brands are data. The studio serves several websites, each a brand, and the engine and pipeline contain no brand
constants. There is no default brand: every production belongs to exactly one brand, taken from the production
or resolved from the brief.

## Brands

```bash
uv run video-pipeline brand list            # brands with status, verified facts and publishing accounts (--all: include hidden)
uv run video-pipeline brand init --id mysite --site https://mysite.com --industry web-hosting [--name "My Site"]
uv run python -m pipeline.intelligence facts --brand mysite --refresh   # verify facts against the site
```

- **`brand init`** (`pipeline/brand_init.py`) drafts a brand from the site's home page (one GET plus the logo
  file): profile (`status: draft`), theme (brand colour from `<meta theme-color>` or the most-used CSS colour, a
  neutral dark palette, the shared OFL fonts), licence records (the downloaded logo is `NEEDS_REVIEW` until the
  owner confirms it may be used; raster logos are listed for manual SVG conversion), a pronunciation skeleton, and
  an empty fact base listing the candidate pricing/product pages. It never scrapes prices or features into facts,
  and it refuses to touch an existing brand.
- **Facts** enter `knowledge/<id>/facts.json` only through verification against the site. Until then, prices and
  features can't be shown.
- **Resolving a brief.** `pipeline.brands.resolve_brand` matches the brief's `brand` field against each brand's
  id, display name ("Shroti Host") or domain ("shrotihost.in"). No match or several matches is an error, so a
  brief never lands on the wrong brand silently; pass `--brand <id>` to `production create` when it is ambiguous.
- **Hidden brands.** A brand with `"hidden": true` in `brand.json` (the fictional test brand `acme-demo`) is usable
  by its exact id but never appears in lists, the Studio or name/domain resolution.

## Layout per brand

| Path | Contents |
|---|---|
| `brands/<id>/theme.json` | design tokens the engine draws with: colours, fonts, logo variants + aspect, background, caption style, radius, **sound conventions** (`sfx`) |
| `brands/<id>/brand.json` | profile: name, website, `status`, `assetRoots`, watermark policy, intro/outro, knowledge-file path, `creative`, `publishing` (below) |
| `brands/<id>/assets.json` | licence records for the brand's own files |
| `brands/<id>/pronunciation.json` | display → spoken entries for the brand name, domain and product names (e.g. `shrotihost.in` → "Shro-tee Host dot in"); captions keep the display text |
| `public/brands/<id>/` | the brand's files (logos, fonts, product UI). Shroti Host: `logos/{logo-on-dark,logo-on-light,icon}.svg`, OFL fonts |
| `knowledge/<id>/facts.json` | verified facts with source URLs and verbatim excerpts |
| `projects/<id>/` | hand-authored projects; briefs in `projects/<id>/briefs/` |

Brand pronunciations are applied to every project of that brand; a project's own `voice.pronunciation` entries win.
Confirm them by ear: the `human:pronunciation` review flag asks for that on every video, and
`reports/pronunciation-checklist.md` lists each term with its timestamp.

### `brand.json` sections

| Section | Read by | Holds |
|---|---|---|
| `creative` | the hybrid engine (`pipeline/creative`) | `industry` (selects the industry pack, e.g. `web-hosting`), house `voice`, default `cta`, fact-bound `tagline` per product family, `banned` words, `placeholderDomain`. Without `creative.industry` the hybrid engine refuses the brand with a clear error. See [CREATIVE_SYSTEM.md](CREATIVE_SYSTEM.md) |
| `publishing` | export, social metadata, publishing | `hashtags`, `descriptionFooter`, `platforms`, `privacyDefault`; `accounts` (the **only** YouTube `channel_id` / Instagram `ig_user_id` this brand may publish to); `social` (voice, link, language, region, category, AI disclosure, CTA, hashtag sets, products / keyword seeds). See [SOCIAL_SETUP.md](SOCIAL_SETUP.md) |

A brand drafted by `brand init` gets a starter `creative` block with `industry` set from `--industry`; review its
tone, CTA and banned words before generating concepts.

Shroti Host tokens: background `#0a0a0f`, brand purple `#a810c7` (hover `#c817ea`, text `#cf6cf2`), success
`#22c55e`, Plus Jakarta Sans + Geist Mono, logo viewBox 150×30 (aspect 5.0), mark 39×23.

## Shared, licensed assets (`public/shared/`)

Files every brand may use, each with a record in `public/shared/assets.json`:

| Path | What | Licence |
|---|---|---|
| `public/shared/fonts/` | Plus Jakarta Sans, Geist Mono (Studio UI, default fonts for new brands) | OFL-1.1 |
| `public/shared/logos/wordpress.svg` | WordPress icon, used on the `install-flow` app tile | CC0-1.0 (Simple Icons); WordPress® is a trademark of the WordPress Foundation, used only to refer to WordPress |
| `public/shared/studio/icon.svg` | the Studio's own icon | self-made |

Third-party product icons are looked up by product name (`pipeline/shared_assets.py`). A scene shows the real icon
only when a file with a licence record exists; otherwise the engine draws a neutral initial. Licences are listed in
[LICENSING.md](LICENSING.md).

## Isolation

A production for brand A may use only `public/brands/A/**` plus the shared, licensed roots `public/shared/`,
`audio/kit/` and `audio/music/`. Validation (`pipeline/brands.py`, run by `validate`/`create`) rejects theme
assets, watermark assets and storyboard `asset`/`src`/`image` paths outside those roots. Facts, pronunciation,
credentials (`.pipeline/secrets/<id>/`) and expected publishing accounts are per brand as well. The Studio's asset
library filters by brand. Tested with the hidden test brand `acme-demo` (`tests/test_brands.py`).

## Brand validation

**Static** (every `validate`): colour tokens are `#RRGGBB`; fonts and logos exist inside the brand's roots;
`theme.logo.aspect` equals the SVG viewBox aspect within 5% (a mismatch would distort the logo); watermark
policy, opacity and asset are valid.

**Rendered** (QA stage, `reports/branding-report.json`):
- `brand.logo_aspect`: every logo drawn at its file's intrinsic aspect (from the layout manifest)
- `brand.logo_present`: each expected logo is present, contains brand-colour pixels, and isn't clipped
- `brand.no_duplicate_branding`: the watermark is hidden whenever a logo, CTA, outro, logo-sting or brand bar is on screen
- `brand.watermark_render` / `brand.watermark_safe`: the watermark shows where expected, disappears when suppressed, and stays clear of captions
- `ocr.no_template_labels`: no "template", "preview", "watermark", "lorem", "made with" … text anywhere
- `brand.palette` (warning): saturated pixels sit near the theme palette

A branding FAIL becomes a blocking review flag on the production.

## Adding a brand

Prefer `video-pipeline brand init` (above), then review every drafted file: set `status` to `ready`, confirm the
logo licence in `assets.json`, check `pronunciation.json` by ear, fill in `creative`, verify facts, and add the
expected accounts under `publishing.accounts` before connecting social accounts. To build one by hand, copy
`brands/acme-demo/` → `brands/<new>/` (remove `"hidden": true`), put files under `public/brands/<new>/`, record their
licences in `assets.json`, and run `uv run video-pipeline validate` on a project with `"brand": "<new>"`.
