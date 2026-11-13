"""Onboard a new brand (website) as a draft: `video-pipeline brand init --id <id> --site https://… [--name …]`.

Reads the site's home page (one GET, plus the logo file) and drafts everything a brand needs:

  brands/<id>/brand.json          profile (name, website, industry, CTA URL, publishing defaults)   status: draft
  brands/<id>/theme.json          design tokens: brand colour from <meta theme-color> or the most-used CSS colour,
                                  neutral dark palette, the studio's shared OFL fonts
  brands/<id>/assets.json         licence records; the downloaded logo is NEEDS_REVIEW until the owner confirms
  brands/<id>/pronunciation.json  name + domain respelling skeleton (confirm by ear)
  public/brands/<id>/...          logo (SVG only: raster logos are listed for manual conversion) + fonts
  knowledge/<id>/facts.json       empty verified-facts file with the candidate pricing/product pages found on the site

Nothing is invented: prices and features are never scraped into facts here. They are added by the
claim-verification step (`python -m pipeline.intelligence facts --brand <id> --refresh`) from these pages.
Refuses to touch an existing brand (no overwrites)."""
from __future__ import annotations

import collections
import html.parser
import json
import re
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

from .errors import ConfigError
from .paths import ROOT, atomic_write_json, safe_name

UA = "Mozilla/5.0 (Macintosh) video-studio-brand-init"
HEX6 = re.compile(r"#([0-9a-fA-F]{6})\b")
PAGE_HINT = re.compile(r"pric|plan|hosting|product|feature|offer|shop|store|course|service|package", re.I)
SHARED_FONTS = "shared/fonts"                    # OFL Plus Jakarta Sans + Geist Mono, copied (never linked) per brand


def _get(url: str, timeout: float = 30.0) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 - https URL given by the owner
        return r.read(5_000_000), r.headers.get("Content-Type", "")


class _Scan(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False
        self.links: list[str] = []
        self.logos: list[str] = []
        self.icons: list[str] = []
        self.css: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        if tag == "meta":
            k = a.get("name") or a.get("property")
            if k:
                self.meta[k.lower()] = a.get("content", "")
        elif tag == "title":
            self._in_title = True
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "img":
            blob = " ".join([a.get("src", ""), a.get("alt", ""), a.get("class", ""), a.get("id", "")]).lower()
            if "logo" in blob and a.get("src"):
                self.logos.append(a["src"])
        elif tag == "link":
            rel = a.get("rel", "").lower()
            if "icon" in rel and a.get("href"):
                self.icons.append(a["href"])
            if "stylesheet" in rel and a.get("href"):
                self.css.append(a["href"])
        if a.get("style"):
            self.css.append("inline:" + a["style"])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, d):
        if self._in_title:
            self.title += d


def _palette(brand: str) -> dict:
    """A dark palette around the brand colour (same token set the engine uses for every brand)."""
    def mix(c, t, f):
        a = [int(c[i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(t[i:i + 2], 16) for i in (1, 3, 5)]
        return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))
    return {"bg": "#0b0b10", "surface": "#131318", "card": "#17171f", "raised": "#191921",
            "border": "rgba(255,255,255,0.14)", "borderStrong": "rgba(255,255,255,0.22)", "text": "#f5f5f7",
            "text2": "#a1a1ab", "muted": "#87878f", "brand": brand, "brandHover": mix(brand, "#ffffff", 0.2),
            "brandActive": mix(brand, "#000000", 0.15), "brandText": mix(brand, "#ffffff", 0.3),
            "success": "#22c55e", "danger": "#f0576b", "warning": "#f5a524", "info": "#3fa7ff",
            "light": {"card": "#ffffff", "surface": "#f7f5fa", "border": "#e6e1ec", "text": "#15111c",
                      "text2": "#4b4655", "muted": "#726c7d", "success": "#15803d"}}


def _brand_colour(scan: _Scan, page: str, base: str) -> tuple[str, str]:
    tc = scan.meta.get("theme-color", "")
    if HEX6.fullmatch(tc.strip()):
        return tc.strip().lower(), "meta theme-color"
    css = page
    for href in scan.css[:4]:
        if href.startswith("inline:"):
            css += href
            continue
        try:
            css += _get(urllib.parse.urljoin(base, href), 20)[0].decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - best effort
            pass
    counts = collections.Counter(m.lower() for m in HEX6.findall(css))
    for hexv, _ in counts.most_common(40):          # most-used saturated, mid-light colour
        r, g, b = (int(hexv[i:i + 2], 16) for i in (0, 2, 4))
        mx, mn = max(r, g, b), min(r, g, b)
        if mx - mn > 60 and 60 < (mx + mn) / 2 < 210:
            return "#" + hexv, "most-used saturated CSS colour"
    return "#6d5efc", "fallback (no brand colour found): set colors.brand by hand"


def _spoken_domain(domain: str, name: str) -> str:
    stem, _, tld = domain.partition(".")
    words = name if stem.replace("-", "").lower() == name.replace(" ", "").lower() else stem
    return f"{words} dot {' dot '.join(tld.split('.'))}" if tld else words


def init_brand(brand_id: str, site: str, name: str | None = None, industry: str = "general", fetch=_get) -> dict:
    safe_name(brand_id)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", brand_id):
        raise ConfigError("brand id must be lowercase letters, digits, - or _ (e.g. 'mysite')")
    for d in (ROOT / "brands" / brand_id, ROOT / "public/brands" / brand_id, ROOT / "knowledge" / brand_id):
        if d.exists():
            raise ConfigError(f"{d.relative_to(ROOT)} already exists: brand init never overwrites an existing brand")
    u = urllib.parse.urlparse(site if "://" in site else "https://" + site)
    if u.scheme != "https" or not u.netloc:
        raise ConfigError("--site must be an https:// URL")
    base = f"https://{u.netloc}/"
    domain = u.netloc.removeprefix("www.")
    body, _ = fetch(base)
    page = body.decode("utf-8", "replace")
    scan = _Scan()
    scan.feed(page)
    name = name or scan.meta.get("og:site_name") or re.split(r"\s[|\-–—:]\s", scan.title.strip())[0] or brand_id
    colour, colour_src = _brand_colour(scan, page, base)
    review: list[str] = []

    pub = ROOT / "public/brands" / brand_id
    (pub / "logos").mkdir(parents=True)
    shutil.copytree(ROOT / "public" / SHARED_FONTS, pub / "fonts", ignore=shutil.ignore_patterns("*.md"))
    logo_rel, logo_note = None, ""
    for src in scan.logos + scan.icons:
        url = urllib.parse.urljoin(base, src)
        if not urllib.parse.urlparse(url).path.lower().endswith(".svg"):
            continue
        try:
            data, _ = fetch(url)
        except Exception:  # noqa: BLE001
            continue
        if b"<svg" in data[:2000].lower() and b"<script" not in data.lower():
            (pub / "logos/logo.svg").write_bytes(data)
            logo_rel, logo_note = f"brands/{brand_id}/logos/logo.svg", url
            break
    if not logo_rel:
        # placeholder wordmark so the brand validates; the owner must replace it
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 200"><text x="0" y="140" font-family="sans-serif" '
               f'font-size="120" font-weight="700" fill="#ffffff">{html.escape(name)[:14]}</text></svg>')
        (pub / "logos/logo.svg").write_text(svg)
        logo_rel = f"brands/{brand_id}/logos/logo.svg"
        raster = [urllib.parse.urljoin(base, s) for s in scan.logos + scan.icons][:5]
        review.append(f"No SVG logo found; a text placeholder was created. Add SVG logos (on-dark, on-light, mark) "
                      f"to public/brands/{brand_id}/logos/. Candidates seen on the site: {raster or 'none'}")
    from .brands import svg_aspect
    aspect = round(svg_aspect(pub / "logos/logo.svg") or 4.0, 3)

    shrot_theme = json.loads((ROOT / "brands/_defaults/theme-defaults.json").read_text())
    theme = {"$comment": f"DRAFT generated by `brand init` from {base}; review colours, logos and fonts.",
             "name": name, "colors": _palette(colour),
             "fonts": {fam: {"family": f["family"], "files": [{**x, "src": f"brands/{brand_id}/fonts/{Path(x['src']).name}"}
                                                           for x in f["files"]]}
                       for fam, f in shrot_theme["fonts"].items()},
             "logo": {"onDark": logo_rel, "onLight": logo_rel, "mark": logo_rel, "aspect": aspect},
             "background": {"style": "dots-glow", "glowA": colour, "glowB": "#3fa7ff"},
             "caption": {"highlight": _palette(colour)["brandText"], "box": "rgba(0,0,0,0.55)", "text": "#f5f5f7",
                         "dim": "rgba(255,255,255,0.45)"},
             "radius": {"card": 32, "pill": 999}, "source": {"site": base, "brandColour": colour_src},
             "sfx": shrot_theme.get("sfx", {})}
    profile = {"$comment": "DRAFT generated by `brand init`. Review every field, then set status to 'ready'.",
               "id": brand_id, "name": name, "website": base.rstrip("/"), "status": "draft",
               "assetRoots": [f"public/brands/{brand_id}/"],
               "watermark": {"policy": "platform", "variant": "mark", "opacity": 0.85, "widthFrac": 0.07, "marginFrac": 0.04},
               "intro": {"enabled": False}, "outro": {"enabled": True, "url": domain},
               "creative": {"industry": industry, "tone": "clear, confident, specific", "cta": f"Visit {domain}", "bannedWords": []},
               "publishing": {"hashtags": ["#" + re.sub(r"\W", "", name)], "descriptionFooter": base.rstrip("/"),
                              "platforms": ["youtube", "instagram"], "privacyDefault": "private", "accounts": {}},
               "knowledge": f"knowledge/{brand_id}/facts.json"}
    assets = {"assets": [{"path": logo_rel, "source": logo_note or "placeholder generated by brand init",
                          "license": "NEEDS_REVIEW (brand owner's logo: confirm you may use it)", "attribution": ""}] +
              [{"path": f"brands/{brand_id}/fonts/{p.name}", "source": "copy of OFL font", "license": "OFL-1.1",
                "attribution": ""} for p in sorted((pub / "fonts").iterdir())]}
    pron = {"$comment": "Brand pronunciations (display -> spoken). Generated guesses: confirm by ear.",
            "entries": [{"display": domain, "spoken": _spoken_domain(domain, name)}]}
    pages, seen = {"home": base}, set()
    for href in scan.links:
        url = urllib.parse.urljoin(base, href).split("#")[0]
        p = urllib.parse.urlparse(url)
        if p.netloc.removeprefix("www.") == domain and PAGE_HINT.search(p.path) and url not in seen and len(pages) < 8:
            seen.add(url)
            pages[p.path.strip("/").replace("/", "-") or "home"] = url
    facts = {"$comment": f"Verified facts for {name}. Empty until claims are verified against these pages: "
                         f"`uv run python -m pipeline.intelligence facts --brand {brand_id} --refresh`. Never add claims "
                         "that are not on the site.",
             "brand": brand_id, "brand_name": name, "site": base, "fetched_at": "", "pages": pages, "facts": [],
             "not_found": []}

    bd = ROOT / "brands" / brand_id
    bd.mkdir(parents=True)
    atomic_write_json(bd / "brand.json", profile)
    atomic_write_json(bd / "theme.json", theme)
    atomic_write_json(bd / "assets.json", assets)
    atomic_write_json(bd / "pronunciation.json", pron)
    (ROOT / "knowledge" / brand_id).mkdir(parents=True)
    atomic_write_json(ROOT / "knowledge" / brand_id / "facts.json", facts)

    from .brands import validate_brand
    errs = validate_brand(brand_id, theme)
    review += [f"brand colour {colour} ({colour_src})", "logo licence is NEEDS_REVIEW in assets.json",
               "only one logo variant: add on-light and mark variants", f"pronunciation guess: {pron['entries'][0]}",
               f"{len(pages)} candidate fact pages found; facts are empty until verified"]
    return {"brand": brand_id, "name": name, "site": base, "files": [f"brands/{brand_id}/", f"public/brands/{brand_id}/",
                                                                      f"knowledge/{brand_id}/facts.json"],
            "validation_errors": errs, "review": review, "fact_pages": pages}
