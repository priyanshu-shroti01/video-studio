# Watermark policy

Set in `brands/<id>/brand.json` → `watermark`, overridable per project with `"branding": {"watermark": {…}}`.

| policy | Behaviour |
|---|---|
| `none` | no overlay |
| `brand` | the brand's logo variant (`variant`: `mark` \| `onDark` \| `onLight`) at `position` (`top-left`, `top-right`, `bottom-left`, `bottom-right`, `top-center`) |
| `custom` | a specific `asset`, which must live inside the brand's own asset root (or the shared, licensed roots) |
| `platform` | the brand mark in the platform-safe corner: Shorts top-left below the status bar (y ≥ 120 px), landscape top-right |

Fields: `opacity` 0.05–1 (Shroti Host: 0.85), `widthFrac`, `marginFrac`. Shroti Host default: `platform`, `mark`.

## Guarantees (implemented and tested)

- **Never distorted:** logos are drawn at the SVG viewBox aspect with `object-fit: contain` (`brand.logo_aspect`).
- **No duplicate branding:** the watermark fades out (0.3 s, no flicker under 0.6 s) while a logo, CTA, outro, logo-sting, brand bar, or an image/device showing the logo is visible (`brand.no_duplicate_branding`, engine tests).
- **Safe margins:** never inside the caption band (`brand.watermark_safe`); content below a top watermark is pushed down.
- **No accidental labels:** OCR fails QA on template/preview/"made with"/watermark text (`ocr.no_template_labels`).
- **Third-party marks only by reference:** besides the brand's own assets (brand isolation) and CC0/OFL/owned files, a
  third-party product icon (e.g. WordPress on the `install-flow` tile) is used only from `public/shared/assets.json`,
  with a licence and a trademark note, unmodified and only to refer to that product.

## Provenance and disclosure

- The pipeline only overlays assets the brand owns. It never removes or alters third-party marks, embedded provenance or Content Credentials.
- Export metadata declares `containsSyntheticMedia: true` for YouTube, because the narration is synthetic (local TTS). Keep that disclosure when uploading.
- Sound and music attribution (CC0, given voluntarily) is written into `publishing/description.md`.
