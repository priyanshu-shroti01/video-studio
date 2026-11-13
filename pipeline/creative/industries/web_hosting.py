"""Industry pack: web hosting (shared hosting, WordPress hosting, domains).

Everything here is industry vocabulary, not a brand: the brand name, domain, tagline, CTA and voice come from
brands/<id>/brand.json and every number / plan / feature label from knowledge/<id>/facts.json. The pack expects
the hosting fact-id convention below (FACT_IDS / FEATURES); a feature or template whose fact is missing from a
brand's fact base is simply not used."""
from __future__ import annotations

from ..anchors import Anchors
from ..product import plans_for
from ..templates import T, checklist, fmt_off, ic, kinetic, num, pill, plan_word
from . import Pack

# ---- product families -----------------------------------------------------------------------------------
FACT_IDS = {
    "renewal": "policy.same_renewal", "typical_renewal": "comparison.typical_renewal", "typical_backups": "comparison.typical_backups",
    "money_back": "policy.money_back", "uptime_target": "policy.uptime_target", "free_domain": "offer.free_domain_annual",
    "upgrade": "policy.upgrade", "taxes": "policy.taxes", "activation": "policy.instant_activation",
    "billing_cycles": "policy.billing_cycles", "live": "platform.live_in_minutes", "setup_steps": "wp.setup_demo",
    "installer": "wp.softaculous", "one_click": "wp.one_click", "cpanel": "platform.cpanel", "litespeed": "platform.litespeed",
    "nvme": "platform.nvme", "security": "platform.security", "cloudflare": "platform.cloudflare", "email": "platform.email",
    "ssl": "platform.free_ssl", "migration": "policy.free_migration", "woo": "wp.starter.features",
}
# copy that names one of these terms is only used when the brand's fact base backs it (role must be allowed)
TERM_ROLES = {"Imunify360": "security", "LiteSpeed Cache": "one_click", "LiteSpeed": "litespeed", "cPanel": "cpanel", "NVMe": "nvme",
              "SSL": "ssl", "backup": "nvme", "migration": "migration", "WooCommerce": "woo", "email on your domain": "email",
              "seven-day": "money_back", "money-back": "money_back", "renew": "renewal", "free domain": "free_domain",
              "instant activation": "activation", "upgrade": "upgrade", "theme": "setup_steps", "plugins": "setup_steps"}
GATED = tuple(FACT_IDS)


def _domain_plans(fb):
    offer = fb.by_id(FACT_IDS["free_domain"])
    names = set((offer or {}).get("value", {}).get("plans", []))
    plans = [p for p in plans_for(fb, "shared") + plans_for(fb, "wordpress") if p.name in names and p.annual]
    return sorted(plans, key=lambda p: p.annual)


FAMILIES = [
    {"id": "wordpress", "match": r"wordpress|\bwp\b|woocommerce", "product": "wordpress", "label": "WordPress hosting", "icon": "rocket"},
    {"id": "domains", "match": r"^(?!.*hosting).*\bdomains?\b", "product": None, "label": "Domains", "icon": "globe", "period": "year",
     "plans": _domain_plans},
    {"id": "shared", "match": None, "product": "shared", "label": "Web hosting", "icon": "rocket"},
]
HOSTING = ("wordpress", "shared")

# fact-bound feature labels: key -> (label, icon, fact id, families or None = all, allow-role or None)
FEATURES = {
    "ssl": ("Free SSL", "lock", "platform.free_ssl", None, None),
    "backups": ("Daily backups", "cloud", "platform.nvme", None, None),
    "nvme": ("NVMe SSD storage", "disk", "platform.nvme", None, None),
    "litespeed": ("LiteSpeed Web Server", "zap", "platform.litespeed", None, None),
    "lscache": ("LiteSpeed Cache", "zap", "wp.one_click", HOSTING, None),
    "security": ("Imunify360 security", "shield", "platform.security", None, None),
    "cloudlinux": ("CloudLinux isolation", "server", "platform.cloudlinux", None, None),
    "migration": ("Free migration", "arrowRight", "policy.free_migration", None, None),
    "email": ("Email on your domain", "mail", "platform.email", None, None),
    "woo": ("WooCommerce ready", "star", "wp.starter.features", ("wordpress",), None),
    "cpanel": ("cPanel + Softaculous", "settings", "platform.cpanel", None, None),
    "cloudflare": ("Cloudflare protected", "shield", "platform.cloudflare", None, None),
    "activation": ("Instant activation", "rocket", "policy.instant_activation", None, "activation"),
    "renewal": ("Same price on renewal", "refresh", "policy.same_renewal", None, "renewal"),
    "money_back": ("7-day money-back guarantee", "shield", "policy.money_back", None, "money_back"),
    "free_domain": ("Free domain, first year", "globe", "offer.free_domain_annual", None, "free_domain"),
}
FEATURE_CUES = {"ssl": ["SSL"], "backups": ["backups", "backed", "daily", "automatic"], "nvme": ["NVMe", "SSDs", "storage"],
                "litespeed": ["LiteSpeed"], "lscache": ["Cache", "LiteSpeed"], "security": ["Imunify360", "security", "protected"],
                "cloudlinux": ["CloudLinux", "isolated"], "migration": ["migration"], "email": ["email"],
                "woo": ["WooCommerce"], "cpanel": ["cPanel", "Softaculous", "panel"], "cloudflare": ["Cloudflare"],
                "activation": ["instant", "instantly", "activation"], "renewal": ["renewal", "renews", "renew"],
                "money_back": ["seven", "money", "guarantee"], "free_domain": ["domain", "free"]}


def has(*roles):
    return lambda pf: all(pf.allow.get(r, False) for r in roles)


# ---- pack hooks for the generic templates ------------------------------------------------------------
def plan_features(ctx):
    pf, p = ctx.pf, ctx.pf.featured
    out = []
    if p.storage_gb:
        out.append((f"{p.storage_gb} GB NVMe storage", "disk", f"fact:{p.facts['storage']}", ["NVMe", "storage", "GB"]))
    for k in (["ssl", "free_domain"] if pf.family == "domains" else ["ssl", "backups"]):
        f = ctx.feature(k)
        if f:
            out.append((f[0], f[1], f"fact:{FEATURES[k][2]}", ["domain"] if k == "free_domain" else FEATURE_CUES[k]))
    if pf.family != "domains" and p.websites:
        out.append((f"{p.websites} {'WordPress ' if pf.family == 'wordpress' else ''}website{'s' if p.websites > 1 else ''}",
                    "globe", f"fact:{p.facts['websites']}", ["website", "websites", "migration"]))
    return out


def plan_detail(ctx, plan):
    return (f"{plan.storage_gb} GB NVMe", f"fact:{plan.facts['storage']}") if plan.storage_gb else None


def compare_rows(ctx, trio, A):
    rows = []
    offer = ctx.fb.by_id(FACT_IDS["free_domain"])
    if ctx.pf.family == "domains" and offer and all(x.name in offer["value"].get("plans", []) for x in trio):
        rows.append({"label": ctx.L("Free domain", f"fact:{offer['id']}"), "values": [ctx.L("First year", f"fact:{offer['id']}")] * len(trio),
                     "at": A.at(["domain", "free"], -0.1, name="row:domain", priority=True)})
    if all(x.storage_gb for x in trio):
        rows.append({"label": ctx.L("NVMe storage", "fact:platform.nvme"),
                     "values": [ctx.L(f"{x.storage_gb} GB", f"fact:{x.facts['storage']}") for x in trio],
                     "at": A.at(["storage", "room"], -0.1, name="row:storage")})
    if all(x.websites for x in trio):
        rows.append({"label": ctx.L("Websites", "template"),
                     "values": [ctx.L(str(x.websites), f"fact:{x.facts['websites']}") for x in trio],
                     "at": A.at(["websites", "sites", "grow"], -0.1, name="row:websites")})
    return rows


def checklist_keys(family):
    return ["email", "ssl", "backups", "activation"] if family == "domains" else ["ssl", "backups", "migration", "security"]


def _site(ctx, prefix: str = "") -> str:
    d = ctx.pf.placeholder_domain
    return d if not prefix else f"{prefix}.{d.rsplit('.', 1)[-1]}"


# ---- hosting templates --------------------------------------------------------------------------------
def b_hook_progress(ctx, A, copy):
    fam = ctx.pf.family
    steps = {"wordpress": [("Pick a plan", ["plan"]), ("Claim a domain", ["domain"]), ("Install WordPress", ["click", "install", "WordPress"])],
             "shared": [("Pick a plan", ["plan"]), ("Claim a domain", ["domain"]), ("Go live", ["click", "live"])],
             "domains": [("Search a name", ["search", "name"]), ("Register it", ["register"]), ("Add email", ["email"])]}[fam]
    k = kinetic(ctx, A, copy, "l")
    prog = {"type": "progress", "title": ctx.L("Your launch", "template"),
            "steps": [{"label": ctx.L(lbl, "pack:template"), "at": A.at(c, -0.1, name=f"step:{lbl}")} for lbl, c in steps]}
    prog["at"] = prog["steps"][0]["at"]
    return [k, prog]


def b_stalled_browser(ctx, A, copy):
    stall = A.at(["loading", "slow", "waiting"], 0.0, name="stall")
    b = {"type": "browser", "url": ctx.L(_site(ctx, "your-website"), "template:illustrative"), "at": A.first_word(0.0, "browser"),
         "stallAt": stall, "loadUntil": stall, "tag": {"text": ctx.L("Still loading…", "template"), "at": A.after(0.35, "tag")}}
    return [b, kinetic(ctx, A, copy, "l")]


def b_site_missing(ctx, A, copy):
    at = A.at(["searches", "looks", "types", "search"], -0.05, name="device")
    dev = {"type": "device", "frame": "phone", "at": at,
           "screen": {"title": ctx.L(_site(ctx), "template:illustrative"), "subtitle": ctx.L("This site can't be reached", "template"),
                      "button": ctx.L("Try again", "template")}}
    return [dev, kinetic(ctx, A, copy, "l")]


def b_diy_terminal(ctx, A, copy):
    wp = ctx.pf.family == "wordpress"
    first = A.first_word(0.0, "terminal")
    lines = [{"text": ctx.L("unzip wordpress.zip" if wp else "sudo nano /etc/hosts", "template"), "kind": "cmd",
              "at": A.at(["WordPress", "server", "hard", "way"], 0.0, name="line:start")},
             {"text": ctx.L("nano wp-config.php" if wp else "nano config.php", "template"), "kind": "cmd",
              "at": A.at(["config", "files"], -0.1, name="line:config")},
             {"text": ctx.L("Error establishing a database connection" if wp else "Permission denied", "template"),
              "kind": "err", "at": A.at(["database", "errors", "permission", "cryptic"], 0.0, name="line:error")},
             {"text": ctx.L("site still offline", "template"), "kind": "dim", "at": A.at(["weekend", "website", "still"], 0.0, name="line:offline")}]
    return [{"type": "terminal", "title": ctx.L("Terminal", "template"), "prompt": "$", "lines": lines, "at": first},
            kinetic(ctx, A, copy, "m")]


def b_renewal_compare(ctx, A, copy):
    fid = lambda r: ctx.pf.fact_ids[r]  # noqa: E731
    rows = [{"label": ctx.L("Renewal price", "template"),
             "values": [ctx.L("Often increases", f"fact:{fid('typical_renewal')}"), ctx.L("Same price", f"fact:{fid('renewal')}")],
             "at": A.at(["renewal", "renew", "price"], -0.1, name="row:renewal")}]
    if ctx.pf.allow.get("typical_backups"):
        rows.append({"label": ctx.L("Daily backups", f"fact:{fid('nvme')}"),
                     "values": [ctx.L("Often a paid add-on", f"fact:{fid('typical_backups')}"), ctx.L("Included", f"fact:{fid('nvme')}")],
                     "at": A.at(["backups", "extra"], -0.1, name="row:backups")})
    hl = A.at(["extra", "too", "increases"], 0.3, name="highlight")
    fc = {"type": "feature-compare", "title": ctx.L("At renewal", "template"),
          "columns": [ctx.L("Typical host", f"fact:{fid('typical_renewal')}"), ctx.L(ctx.pf.brand, "brand:name")], "rows": rows,
          "highlight": 1, "highlightAt": hl, "at": rows[0]["at"]}
    return [kinetic(ctx, A, copy, "m"), fc]


def b_install_flow(ctx, A, copy):
    f = ctx.fb.by_id(FACT_IDS["setup_steps"])
    labels = f["value"]["steps"]
    cue_for = [["WordPress", "installs", "install"], ["theme"], ["plugins"], ["SSL"], ["LiteSpeed", "Cache"]]
    inst = ctx.fb.by_id(FACT_IDS["installer"])
    p = pill(ctx, "Softaculous 1-Click Installs" if inst else "One-click install", f"fact:{FACT_IDS['installer' if inst else 'one_click']}",
             A.first_word(0.0, "pill"), "download")
    flow_at = A.at(["click", "Click", "One"], -0.1, name="window", free=True)
    steps = [{"label": ctx.L(lbl, f"fact:{f['id']}"), "at": A.at(cue_for[i] if i < len(cue_for) else [], 0.0, name=f"step:{i}")}
             for i, lbl in enumerate(labels)]
    flow = {"type": "install-flow", "app": ctx.L("WordPress", f"fact:{FACT_IDS['one_click']}"),
            "title": ctx.L("One-click install", f"fact:{FACT_IDS['one_click']}"), "steps": steps,
            "doneAt": A.at(["live", "ready", "done"], 0.0, name="done"), "doneText": ctx.L("Your site is live", "template"),
            "siteUrl": ctx.L(_site(ctx), "template:illustrative"), "at": flow_at}
    from ...shared_assets import app_icon
    icon = app_icon(flow["app"])
    if icon:                                    # the real, licensed product icon instead of the initial
        flow["appIcon"] = icon
    return [flow, p]


def b_domain_search(ctx, A, copy):
    dom = ctx.pf.family == "domains"
    type_at = A.at(["Type", "Search", "type", "search"], 0.1, name="type")
    btn = ({"idle": "Register", "busy": "Registering…", "done": "It's yours"} if dom else
           {"idle": "Launch site", "busy": "Launching…", "done": "Your site is live"})
    btn = {k: ctx.L(v, "template") for k, v in btn.items()}
    click = A.at(["launch", "claim", "register"], 0.0, gap=1.0, name="click")
    done = A.at(["live", "minutes", "yours", "available"], 0.1, gap=0.8, name="done")
    di = {"type": "domain-input", "title": ctx.L("Find your domain", "template"), "domain": ctx.L(_site(ctx), "template:illustrative"),
          "typeAt": type_at, "at": fmt_off(type_at, -0.25), "availableText": ctx.L("is available", "template"),
          "button": {**btn, "clickAt": click, "doneAt": done}}
    cl = checklist(ctx, A, ["email", "ssl"] if dom else ["ssl", "email", "backups"])
    return [di] + ([cl] if cl else [])


def b_dashboard(ctx, A, copy):
    p = ctx.pf.featured
    at = A.at(["cPanel", "panel", "Everything"], -0.1, name="dashboard")
    nav = {"wordpress": ["Home", "WordPress", "Backups", "SSL", "Email"], "shared": ["Home", "Files", "Backups", "SSL", "Email"],
           "domains": ["Home", "Domains", "DNS", "Email", "SSL"]}[ctx.pf.family]
    stats = [{"label": ctx.L("Plan", "template"), "value": ctx.L(p.name, f"fact:{p.facts.get('monthly') or p.facts.get('annual')}")}]
    if p.storage_gb:
        stats.append({"label": ctx.L("NVMe storage", f"fact:{FACT_IDS['nvme']}"), "value": ctx.L(f"{p.storage_gb} GB", f"fact:{p.facts['storage']}")})
    stats.append({"label": ctx.L("Backups", f"fact:{FACT_IDS['nvme']}"), "value": ctx.L("Daily", f"fact:{FACT_IDS['nvme']}"), "tone": "success"})
    db = {"type": "dashboard", "title": ctx.L("cPanel", f"fact:{FACT_IDS['cpanel']}"), "nav": [ctx.L(n, "template") for n in nav],
          "active": 1, "stats": stats, "at": at}
    keys = ["cpanel", "email", "ssl", "backups"] if ctx.pf.family == "domains" else ["cpanel", "nvme", "backups", "security"]
    cl = checklist(ctx, A, keys, name="dash")
    return [db] + ([cl] if cl else [])


def b_device_site(ctx, A, copy):
    at = A.at(["live", "phone", "site", "name", "domain"], -0.1, name="device")
    rows = ["Home", "Shop", "Contact"] if ctx.pf.family != "domains" else ["Home", "About", "Contact"]
    dev = {"type": "device", "frame": "phone", "at": at,
           "screen": {"title": ctx.L(_site(ctx), "template:illustrative"), "subtitle": ctx.L("Your site is live", "template"),
                      "rows": [ctx.L(r, "template") for r in rows], "button": ctx.L("Visit site", "template")}}
    keys = ["email", "ssl"] if ctx.pf.family == "domains" else ["ssl", "backups"]
    lead = []
    if A.has("live") and ctx.fb.by_id(FACT_IDS["live"]):
        lead.append({"text": ctx.L("Live in minutes", f"fact:{FACT_IDS['live']}"), "icon": ic("clock"), "at": A.at(["live"], -0.1, name="item:live")})
    if A.has("domain") or not lead:
        lead.append({"text": ctx.L("Your own domain", "template"), "icon": ic("globe"), "at": A.at(["domain", "own"], -0.1, name="item:domain")})
    cl = checklist(ctx, A, keys)
    if cl:
        cl["items"] = (lead + cl["items"])[:4]
        cl["at"] = cl["items"][0]["at"]
    return [dev] + ([cl] if cl else [])


def b_scroll_site(ctx, A, copy):
    wp = ctx.pf.family == "wordpress"
    feats = [f[1] for f in ctx.features(["ssl", "backups", "lscache" if wp else "nvme"])]
    sections = [{"title": ctx.L("Your new WordPress site" if wp else "Your new website", "template"), "kind": "hero"},
                {"title": ctx.L("Included", "template"), "text": ctx.L(" | ".join(feats), "facts"), "kind": "features"}]
    woo = ctx.feature("woo")
    if woo:
        sections.append({"title": woo[0], "kind": "plain"})
    sections.append({"title": ctx.L("Open for business", "template"), "kind": "cta"})
    sd = {"type": "scroll-demo", "url": ctx.L(_site(ctx), "template:illustrative"), "sections": sections, "at": A.first_word(0.0, "scroll"),
          "scrollEnd": A.last_word(0.2, "scrollEnd")}
    cl = checklist(ctx, A, ["litespeed", "ssl", "backups", "woo"] if wp else ["litespeed", "nvme", "ssl", "backups"])
    return [sd] + ([cl] if cl else [])


def b_server_stack(ctx, A, copy):
    nodes = [{"label": label, "icon": icon, "at": A.at(FEATURE_CUES[k], -0.1, name=f"node:{k}")}
             for k, label, icon in ctx.features(["litespeed", "nvme", "security", "backups"])]
    ss = {"type": "server-stack", "title": ctx.L("Under the hood", "template"), "nodes": nodes[:4], "at": A.word_expr(0)}
    ss["pulseAt"] = A.after(0.35, "pulse")
    if ctx.pf.allow.get("uptime_target"):
        ss["status"] = {"text": ctx.L("99.9% uptime target", f"fact:{FACT_IDS['uptime_target']}"), "at": A.after(0.5, "status"), "tone": "success"}
    out = [ss]
    cf = ctx.feature("cloudflare")
    if cf:
        out.append(pill(ctx, cf[0], f"fact:{FACT_IDS['cloudflare']}", A.at(["protected", "Cloudflare"], 0.0, name="pill"), cf[1]))
    return out


def b_checklist_counter(ctx, A, copy):
    p = ctx.pf.featured
    c_at = A.at([num(p.storage_gb)], -0.05, name="counter")
    counter = {"type": "counter", "to": p.storage_gb, "from": 0, "suffix": " GB", "at": c_at, "countEnd": fmt_off(c_at, 0.75),
               "label": ctx.L(f"NVMe storage · {p.name}", f"fact:{p.facts['storage']}"), "tone": "brand", "size": "l"}
    cl = checklist(ctx, A, ["ssl", "backups", "migration", "security"])
    return [counter] + ([cl] if cl else [])


def b_plan_compare(ctx, A, copy):
    p, s = ctx.pf.featured, ctx.pf.second
    head_at = A.at([plan_word(s.name)], -0.1, name="compare")
    rows = []
    if s.storage_gb:
        rows.append({"label": ctx.L("NVMe storage", f"fact:{FACT_IDS['nvme']}"),
                     "values": [ctx.L(f"{p.storage_gb} GB", f"fact:{p.facts['storage']}"), ctx.L(f"{s.storage_gb} GB", f"fact:{s.facts['storage']}")],
                     "at": A.at([num(s.storage_gb), "GB", "room"], -0.1, name="row:storage")})
    if s.websites:
        rows.append({"label": ctx.L("Websites", "template"),
                     "values": [ctx.L(str(p.websites), f"fact:{p.facts['websites']}"), ctx.L(str(s.websites), f"fact:{s.facts['websites']}")],
                     "at": A.at([num(s.websites), "websites", "sites"], -0.1, name="row:websites")})
    if s.ram:
        rows.append({"label": ctx.L("RAM", "template"), "values": [ctx.L(p.ram, f"fact:{p.facts['cpu_ram']}"), ctx.L(s.ram, f"fact:{s.facts['cpu_ram']}")],
                     "at": A.at(["upgrade", "server", "time"], 0.0, name="row:ram")})
    fc = {"type": "feature-compare", "columns": [ctx.L(p.name, f"fact:{p.facts['monthly']}"), ctx.L(s.name, f"fact:{s.facts['monthly']}")],
          "rows": rows, "highlight": 1, "highlightAt": A.after(0.3, "highlight"), "at": head_at}
    out = [fc]
    if ctx.pf.allow.get("upgrade"):
        out.append(pill(ctx, "Upgrade any time", f"fact:{FACT_IDS['upgrade']}", A.at(["upgrade", "Move"], 0.0, name="pill"), "arrowUp"))
    return out


IND = ("web-hosting",)
_always = lambda pf: True  # noqa: E731
TEMPLATES = [
    T("hook-progress-promise", "Promise in three moves", "hook", IND, None, "progress", "kinetic-text", ("spotlight", "glow"), "drift",
      "energetic", "fade", None, (10, 15), (2, 5), {"steps": "plan / domain / install (or search / register / email)"}, (), (), _always,
      b_hook_progress, "A three-step progress rail lights each step on the word that names it."),
    T("hook-stalled-browser", "The stalled site", "problem", IND, HOSTING, "browser", "kinetic-text", ("deep",), "drift", "calm",
      "fade", "danger", (9, 13), (2, 8), {"stall": ["loading", "slow"], "tag": "after stall"}, (), (), _always, b_stalled_browser,
      "A browser that never finishes loading, with the viewer's consequence in kinetic type (problem visual, not a demo)."),
    T("hook-site-missing", "Nothing comes up", "hook", IND, None, "device", "kinetic-text", ("deep", "spotlight"), "drift", "cinematic",
      "fade", "danger", (7, 12), (2, 6), {"device": ["searches", "looks"], "kinetic-text": "the consequence, word by word"}, (), (),
      _always, b_site_missing, "A phone shows 'This site can't be reached' when someone looks the business up."),
    T("problem-diy-terminal", "Setup the hard way", "problem", IND, HOSTING, "terminal", "kinetic-text", ("grid",), "pan-left", "standard",
      "slide-up", "danger", (11, 15), (2, 4), {"lines": ["config", "database/errors", "weekend/website"]}, (), (), _always, b_diy_terminal,
      "A terminal fills with config commands and a real-world error, one line per spoken pain point."),
    T("problem-renewal-compare", "Renewal reality", "problem", IND, None, "feature-compare", "kinetic-text", ("split",), "none", "standard",
      "mask-wipe", "danger", (10, 17), (2, 8), {"rows": ["renewal", "backups"], "highlight": "after the contrast"}, (), (),
      has("typical_renewal", "renewal"), b_renewal_compare,
      "Typical host vs the brand: renewal and backups rows from the fact base's own comparison facts (only if they exist)."),
    T("demo-install-flow", "One-click WordPress install", "demo", IND, HOSTING, "install-flow", "pill", ("light",), "push-in", "standard",
      "slide-up", None, (12, 19), None, {"steps": ["click/WordPress", "theme", "plugins", "SSL", "LiteSpeed/Cache"], "done": ["live"]},
      (), (), has("setup_steps", "one_click"), b_install_flow,
      "The installer runs the fact base's own setup sequence, each step ticking on its spoken word, ending live."),
    T("demo-domain-search", "Domain search", "demo", IND, None, "domain-input", "checklist", ("grid",), "pan-right", "standard",
      "slide-up", None, (12, 18), None, {"type": ["type", "search"], "click": ["launch", "claim"], "done": ["live", "minutes"],
                                         "checklist": "one item per spoken feature"}, (), (), _always, b_domain_search,
      "A domain is typed key by key, found available and launched; included features check in as they are named."),
    T("demo-dashboard", "Control panel", "demo", IND, None, "dashboard", "checklist", ("deep", "grid"), "drift", "standard", "fade", None,
      (11, 17), None, {"dashboard": ["cPanel", "panel"], "checklist": ["cPanel", "NVMe/storage", "backups", "security"]}, (), (),
      has("cpanel"), b_dashboard, "cPanel dashboard with the featured plan's verified stats; the spoken list checks in beside it."),
    T("demo-device-site", "Live on a phone", "demo", IND, None, "device", "checklist", ("light", "glow"), "push-in", "standard",
      "slide-up", None, (10, 17), None, {"device": ["live"], "checklist": ["live/domain", "SSL", "backups/email"]}, (), (), _always,
      b_device_site, "The finished site on a phone frame; included features check in on their words."),
    T("demo-scroll-site", "Site walkthrough", "demo", IND, HOSTING, "scroll-demo", "checklist", ("light",), "none", "standard", "slide-up",
      None, (11, 19), None, {"scroll": "whole narration", "checklist": ["LiteSpeed", "SSL", "backups", "WooCommerce"]}, (), (),
      _always, b_scroll_site, "A new site scrolls top to bottom while the stack under it checks in feature by feature."),
    T("proof-server-stack", "Under the hood", "proof", IND, None, "server-stack", "pill", ("grid", "deep"), "pan-left", "standard", "fade",
      None, (9, 16), None, {"nodes": ["LiteSpeed", "NVMe", "Imunify360", "backups"], "status": "after the last node"}, (), (),
      has("litespeed", "nvme"), b_server_stack, "A server rack lights node by node (web server, storage, security, backups) with the uptime target."),
    T("proof-checklist-counter", "What's included", "proof", IND, HOSTING, "counter", "checklist", ("deep", "glow", "spotlight"), "push-in",
      "energetic", "fade", None, (12, 17), None, {"counter": "the storage number", "checklist": ["SSL", "backups", "migration", "Imunify360"]},
      ("storage",), (), lambda pf: bool(pf.featured.storage_gb), b_checklist_counter,
      "Storage counts up on its spoken number, then the plan's included features check in one by one."),
    T("proof-plan-compare", "Room to grow", "proof", IND, HOSTING, "feature-compare", "pill", ("split",), "none", "standard", "fade", None,
      (10, 16), None, {"columns": "the second plan's name", "rows": ["storage number", "websites number"]},
      ("plan2", "storage2", "websites2"), (), lambda pf: pf.second is not None, b_plan_compare,
      "Featured plan vs the next tier: storage, websites, RAM from the plan facts."),
]

# ---- blueprints ---------------------------------------------------------------------------------------
BLUEPRINTS = [
    {"id": "setup-solved", "name": "Setup, Solved", "pattern": "hook-problem-solution-demo-cta",
     "pattern_name": "Hook → Problem → Reveal → Demo → Price → CTA",
     "logline": "Open on the idea, show the painful do-it-yourself setup, reveal the brand, then demo the product and land the verified price.",
     "slots": [("hook", ["hook-kinetic-spotlight", "hook-progress-promise"]),
               ("problem", ["problem-diy-terminal", "hook-stalled-browser", "problem-renewal-compare"]),
               ("turn", ["turn-logo-sting"]),
               ("demo", ["demo-install-flow", "demo-domain-search", "demo-device-site"]),
               ("pricing", ["price-plan-card", "price-plans-lineup"]),
               ("cta", ["cta-outro", "cta-logo-lockup"])],
     "hook_tags": ["question", "promise"], "music": "technology", "cta_style": "url-click",
     "pacing": {"label": "steady build", "detail": "slow cinematic open, quick problem, longest beat on the demo"}},
    {"id": "three-moves", "name": "Live in Three Moves", "pattern": "tutorial-demo-result",
     "pattern_name": "Promise → Step → Step → Step → Price → CTA",
     "logline": "A tutorial that never leaves the product: claim a domain, set it up, check the control panel, then compare prices.",
     "slots": [("hook", ["hook-progress-promise", "hook-kinetic-spotlight"]),
               ("demo", ["demo-domain-search", "demo-device-site"]),
               ("demo", ["demo-install-flow", "demo-device-site", "demo-domain-search"]),
               ("proof", ["demo-dashboard", "proof-checklist-counter", "proof-server-stack", "proof-feature-checklist"]),
               ("pricing", ["price-compare-cycles", "price-plans-lineup", "price-plan-card"]),
               ("cta", ["cta-logo-lockup", "cta-outro"])],
     "hook_tags": ["promise"], "music": "educational", "cta_style": "button-press",
     "pacing": {"label": "brisk walkthrough", "detail": "no problem beat; four product screens back to back, energetic entrances"}},
    {"id": "under-the-hood", "name": "Under the Hood", "pattern": "before-after",
     "pattern_name": "Before → Cost → Reveal → Infrastructure → After → Plans → CTA",
     "logline": "Start on the broken experience and the renewal surprise, reveal the brand, open the server rack, show the finished site, then pick a plan.",
     "slots": [("hook", ["hook-stalled-browser", "hook-site-missing", "hook-kinetic-spotlight"]),
               ("problem", ["problem-renewal-compare", "problem-diy-terminal"]),
               ("turn", ["turn-logo-sting"]),
               ("proof", ["proof-server-stack", "proof-checklist-counter", "proof-feature-checklist"]),
               ("demo", ["demo-scroll-site", "demo-dashboard", "demo-device-site"]),
               ("pricing", ["price-plans-lineup", "price-plan-card", "price-compare-cycles"]),
               ("cta", ["cta-outro", "cta-logo-lockup"])],
     "hook_tags": ["pain-point"], "music": "cinematic", "cta_style": "logo-lockup",
     "pacing": {"label": "cinematic, seven beats", "detail": "dark open, light demo, short scenes with crossfading backdrops"}},
    {"id": "price-that-stays", "name": "The Price That Stays", "pattern": "myth-reality-explanation",
     "pattern_name": "Myth → Reality → Reveal → Proof → Price → CTA",
     "logline": "Challenge the 'good hosting costs a lot' belief, show what renewal usually does, then show the price holding.",
     "slots": [("hook", ["hook-kinetic-spotlight", "hook-site-missing", "hook-progress-promise"]),
               ("problem", ["problem-renewal-compare", "hook-stalled-browser"]),
               ("turn", ["turn-logo-sting"]), ("demo", ["demo-device-site", "demo-domain-search", "demo-dashboard"]),
               ("pricing", ["price-counter-flat", "price-plan-card"]), ("cta", ["cta-logo-lockup", "cta-outro"])],
     "hook_tags": ["myth"], "music": "corporate", "cta_style": "callback-question",
     "pacing": {"label": "argument", "detail": "measured myth/reality open, proof-heavy close"}},
    {"id": "whats-inside", "name": "What's Inside", "pattern": "feature-benefit-proof",
     "pattern_name": "Hook → Reveal → Features → Panel → Price → CTA",
     "logline": "Lead with the brand, then unpack the plan: features, the control panel and the price card.",
     "slots": [("hook", ["hook-kinetic-spotlight", "hook-progress-promise"]), ("turn", ["turn-logo-sting"]),
               ("proof", ["proof-checklist-counter", "proof-feature-checklist", "proof-server-stack"]),
               ("demo", ["demo-dashboard", "demo-device-site"]),
               ("pricing", ["price-plan-card", "price-plans-lineup", "price-compare-cycles"]), ("cta", ["cta-outro", "cta-logo-lockup"])],
     "hook_tags": ["promise"], "music": "energetic", "cta_style": "offer-stamp",
     "pacing": {"label": "feature sprint", "detail": "short reveal, then dense feature proof"}},
]

STYLE = ("Name the real thing on screen (the control panel, the web server, the security scanner) instead of adjectives; "
         "say a price as the amount plus the currency word.")
BANNED = ["no tech skills", "tech skills not needed", "blazing fast", "lightning fast"]

# ---- copy (industry layer; takes precedence over the generic bank) -------------------------------------
# Length: estimates use the measured local-voice rate (anchors.WPS), so a 6-scene video fits 30–35 s with roughly
# 62–70 words in total (about 11 a scene; ~9–10 a scene for 7 scenes). Each template keeps short variants so the
# director can always fit the window; the domain is spoken as several words, so CTA lines stay lean.
BANK: dict[str, dict[str, list[dict]]] = {
    "hook-kinetic-spotlight": {
        "wordpress": [
            {"id": "home", "narration": "You have the idea. Now your WordPress site needs a home.",
             "headline": "your WordPress site needs a home", "emphasis": ["home"], "tags": ["question"]},
            {"id": "decision", "narration": "Every WordPress site starts with one decision: where it lives.",
             "headline": "where it lives", "emphasis": ["lives"], "tags": ["promise"]},
            {"id": "closer", "narration": "Think good WordPress hosting has to cost a lot? Look closer.",
             "headline": "Look closer", "emphasis": ["closer"], "tags": ["myth"]},
        ],
        "shared": [
            {"id": "home", "narration": "You have the idea. Now your website needs a home.",
             "headline": "your website needs a home", "emphasis": ["home"], "tags": ["question"]},
            {"id": "decision", "narration": "Every website starts with one decision: where it lives.",
             "headline": "where it lives", "emphasis": ["lives"], "tags": ["promise"]},
            {"id": "closer", "narration": "Think good hosting has to cost a lot? Look closer.",
             "headline": "Look closer", "emphasis": ["closer"], "tags": ["myth"]},
        ],
        "domains": [
            {"id": "find", "narration": "Your business needs a name people can find.",
             "headline": "a name people can find", "emphasis": ["find"], "tags": ["question"]},
            {"id": "address", "narration": "Every brand online starts with one thing: its address.",
             "headline": "its address", "emphasis": ["address"], "tags": ["promise"]},
            {"id": "taken", "narration": "Think every good name is already taken? Look again.",
             "headline": "Look again", "emphasis": ["again"], "tags": ["myth"]},
        ],
    },
    "hook-progress-promise": {
        "wordpress": [
            {"id": "route", "narration": "A live WordPress site takes a plan, a domain and one click.",
             "headline": "A live WordPress site", "emphasis": ["live"]},
            {"id": "nothing", "narration": "From nothing to a live WordPress site: pick a plan, claim a domain, click install.",
             "headline": "a live WordPress site", "emphasis": ["live"]},
            {"id": "steps", "narration": "Pick a plan, claim a domain, click install. A live WordPress site.",
             "headline": "A live WordPress site", "emphasis": ["live"]},
            {"id": "lean", "narration": "A live WordPress site: a plan, a domain, one click.",
             "headline": "A live WordPress site", "emphasis": ["live"]},
        ],
        "shared": [
            {"id": "route", "narration": "A live website takes a plan, a domain and one click.",
             "headline": "A live website", "emphasis": ["live"]},
            {"id": "nothing", "narration": "From nothing to a live website: pick a plan, claim a domain, and click live.",
             "headline": "a live website", "emphasis": ["live"]},
        ],
        "domains": [
            {"id": "name", "narration": "Getting online starts with a name: search it, register it, add email.",
             "headline": "Getting online", "emphasis": ["online"]},
            {"id": "search", "narration": "Search the name you want, register it, then put email on it.",
             "headline": "Search the name", "emphasis": ["name"]},
        ],
    },
    "hook-stalled-browser": {
        "wordpress": [
            {"id": "left", "narration": "Your WordPress site is still loading. Your visitor left.",
             "headline": "Your visitor left", "emphasis": ["left."]},
            {"id": "slow", "narration": "A slow WordPress site loses visitors before the page even appears.",
             "headline": "loses visitors before the page even appears.", "emphasis": ["visitors"]},
            {"id": "gone", "narration": "Your page is still loading. Your visitor already left.",
             "headline": "Your visitor already left", "emphasis": ["left."]},
        ],
        "shared": [
            {"id": "left", "narration": "Your site is still loading. Your visitor has already left.",
             "headline": "Your visitor has already left", "emphasis": ["left."]},
            {"id": "slow", "narration": "A slow website loses visitors before the page even appears.",
             "headline": "loses visitors before the page even appears.", "emphasis": ["visitors"]},
            {"id": "gone", "narration": "Your page is still loading. Your visitor already left.",
             "headline": "Your visitor already left", "emphasis": ["left."]},
        ],
    },
    "hook-site-missing": {
        "wordpress": [
            {"id": "nothing", "narration": "A customer searches for your shop. Nothing comes up.", "headline": "Nothing comes up.",
             "emphasis": ["Nothing"], "tags": ["pain-point"]},
            {"id": "reached", "narration": "Someone looks you up. They get an error page.", "headline": "an error page.",
             "emphasis": ["error"], "tags": ["pain-point"]},
        ],
        "shared": [
            {"id": "nothing", "narration": "A customer searches for your shop. Nothing comes up.", "headline": "Nothing comes up.",
             "emphasis": ["Nothing"], "tags": ["pain-point"]},
            {"id": "reached", "narration": "Someone looks you up. They get an error page.", "headline": "an error page.",
             "emphasis": ["error"], "tags": ["pain-point"]},
        ],
        "domains": [
            {"id": "nothing", "narration": "Someone searches for your business. Nothing comes up.", "headline": "Nothing comes up.",
             "emphasis": ["Nothing"], "tags": ["pain-point"]},
            {"id": "reached", "narration": "A customer looks you up and finds someone else's name.", "headline": "someone else's name.",
             "emphasis": ["else's"], "tags": ["pain-point"]},
        ],
    },
    "problem-diy-terminal": {
        "wordpress": [
            {"id": "weekend", "narration": "Setting up WordPress by hand: config files, database errors, a lost weekend.",
             "headline": "a lost weekend", "emphasis": ["weekend."]},
            {"id": "hard", "narration": "The hard way? Config files, database errors, and still no website.",
             "headline": "still no website", "emphasis": ["website."]},
        ],
        "shared": [
            {"id": "weekend", "narration": "Setting up a server by hand: config files, cryptic errors, a lost weekend.",
             "headline": "a lost weekend", "emphasis": ["weekend."]},
            {"id": "hard", "narration": "The hard way? Config files, permission errors, and still no website.",
             "headline": "still no website", "emphasis": ["website."]},
        ],
    },
    "problem-renewal-compare": {
        "*": [
            {"id": "increases", "narration": "At renewal, the price you signed up for often increases. Backups cost extra too.",
             "headline": "the price you signed up for often increases.", "emphasis": ["increases."], "needs": ["typical_backups"]},
            {"id": "raise", "narration": "Most hosts raise the price at renewal. Backups cost extra too.",
             "headline": "raise the price", "emphasis": ["price"], "needs": ["typical_backups"]},
            {"id": "renewal-only", "narration": "Then renewal arrives, and the price you signed up for often increases.",
             "headline": "the price you signed up for often increases.", "emphasis": ["increases."]},
            {"id": "raise-short", "narration": "Most hosts raise renewal prices and charge extra for backups.",
             "headline": "raise renewal prices", "emphasis": ["prices"], "needs": ["typical_backups"]},
            {"id": "comes", "narration": "Renewal comes, and the price often increases. Backups cost extra too.",
             "headline": "the price often increases.", "emphasis": ["increases."], "needs": ["typical_backups"]},
        ],
    },
    "turn-logo-sting": {
        "wordpress": [
            {"id": "meet", "narration": "Meet {brand}. WordPress hosting, tuned to run fast.", "headline": "WordPress hosting, tuned to run fast.", "emphasis": ["fast."]},
            {"id": "this", "narration": "This is {brand}: managed WordPress hosting, tuned to run fast.", "headline": "managed WordPress hosting, tuned to run fast.", "emphasis": ["fast."]},
        ],
        "shared": [
            {"id": "meet", "narration": "Meet {brand}. Fast shared hosting, priced honestly.", "headline": "Fast shared hosting, priced honestly.", "emphasis": ["honestly."]},
            {"id": "this", "narration": "This is {brand}: fast shared hosting, priced honestly.", "headline": "fast shared hosting, priced honestly.", "emphasis": ["honestly."]},
        ],
        "domains": [
            {"id": "meet", "narration": "Meet {brand}. Your domain and hosting, under one roof.", "headline": "Your domain and hosting, under one roof.", "emphasis": ["roof."]},
            {"id": "this", "narration": "This is {brand}: domains, LiteSpeed hosting, and email on your domain.", "headline": "domains, LiteSpeed hosting, and email on your domain.", "emphasis": ["email"]},
        ],
    },
    "demo-install-flow": {
        "wordpress": [
            {"id": "installs", "narration": "One click installs WordPress, a theme, plugins, SSL and LiteSpeed Cache. You're live."},
            {"id": "once", "narration": "Click once. WordPress installs, then your theme, plugins, SSL and LiteSpeed Cache. You're live."},
            {"id": "short", "narration": "One click sets up WordPress, a theme, plugins, SSL and LiteSpeed Cache. Then you're live."},
        ],
        "shared": [
            {"id": "want", "narration": "Want WordPress? One click installs it, with a theme, plugins, SSL and LiteSpeed Cache. You're live."},
            {"id": "once", "narration": "Click once. WordPress installs, then your theme, plugins, SSL and LiteSpeed Cache. You're live."},
        ],
    },
    "demo-domain-search": {
        "wordpress": [
            {"id": "type", "narration": "Type your domain, hit launch, and you're live with free SSL and daily backups."},
            {"id": "search", "narration": "Search your name, launch in minutes, and get free SSL, email and daily backups."},
        ],
        "shared": [
            {"id": "type", "narration": "Type your domain, hit launch, and you're live with free SSL and daily backups."},
            {"id": "search", "narration": "Search your name, launch in minutes, and get free SSL, email and daily backups."},
        ],
        "domains": [
            {"id": "type", "narration": "Type the name you want. If it's available, claim it and add email."},
            {"id": "search", "narration": "Search your name, claim it while it's available, then add email and free SSL."},
        ],
    },
    "demo-dashboard": {
        "domains": [
            {"id": "sits", "narration": "One cPanel holds it all: your domain, email, free SSL and daily backups."},
            {"id": "panel", "narration": "Everything sits in cPanel: email on your domain, free SSL and daily backups."},
            {"id": "short", "narration": "Everything sits in cPanel: your email, free SSL and daily backups."},
        ],
        "*": [
            {"id": "sits", "narration": "Everything sits in cPanel: NVMe storage, daily backups and Imunify360 security."},
            {"id": "panel", "narration": "One panel runs it all. cPanel shows your NVMe storage, daily backups and Imunify360."},
            {"id": "shows", "narration": "Your cPanel shows it all: NVMe storage, daily backups and Imunify360."},
        ],
    },
    "demo-device-site": {
        "wordpress": [
            {"id": "live", "narration": "Your WordPress site is live, on your own domain. Free SSL. Daily backups."},
            {"id": "phone", "narration": "Open your phone: your site is live. Free SSL, daily backups."},
            {"id": "short", "narration": "Your WordPress site is live. Your own domain, free SSL, daily backups."},
        ],
        "shared": [
            {"id": "live", "narration": "Your site is live, on your own domain. Free SSL. Daily backups."},
            {"id": "phone", "narration": "Open your phone: your site is live. Free SSL, daily backups."},
            {"id": "short", "narration": "Your site is live. Your own domain, free SSL, daily backups."},
        ],
        "domains": [
            {"id": "name", "narration": "Your name is live on your own domain, with email and free SSL."},
            {"id": "short", "narration": "Your name is live on your own domain. Email and free SSL included."},
            {"id": "phone", "narration": "Open your phone: your site is live. Email and free SSL included."},
        ],
    },
    "demo-scroll-site": {
        "wordpress": [
            {"id": "runs", "narration": "Your new site runs on LiteSpeed, with free SSL, daily backups, and WooCommerce ready when you are."},
            {"id": "scroll", "narration": "Scroll your new WordPress site: LiteSpeed under it, free SSL, daily backups, WooCommerce ready."},
            {"id": "short", "narration": "Your new site runs on LiteSpeed. Free SSL, daily backups, WooCommerce ready."},
            {"id": "lean", "narration": "Here is your new site, with SSL, backups and WooCommerce ready."},
        ],
        "shared": [
            {"id": "runs", "narration": "Your new site runs on LiteSpeed and NVMe storage, with free SSL and daily backups."},
            {"id": "scroll", "narration": "Scroll your new site: LiteSpeed and NVMe underneath, free SSL and daily backups on top."},
            {"id": "short", "narration": "Your new site runs on LiteSpeed and NVMe. Free SSL. Daily backups."},
            {"id": "lean", "narration": "Here is your new site, with free SSL and daily backups."},
        ],
    },
    "proof-server-stack": {
        "*": [
            # end on "automatic daily backups": the backups node lands on "automatic" and the status/pill beats that
            # follow it stay inside the scene
            {"id": "underneath", "narration": "Underneath: LiteSpeed servers and NVMe SSDs, Imunify360 security and automatic daily backups."},
            {"id": "hood", "narration": "Under the hood: LiteSpeed servers, NVMe storage, Imunify360 security, and automatic daily backups."},
            {"id": "short", "narration": "Under the hood: LiteSpeed, NVMe storage, Imunify360 security and automatic daily backups."},
            {"id": "runs", "narration": "It runs on LiteSpeed and NVMe, with Imunify360 and automatic daily backups."},
            {"id": "lean", "narration": "Under the hood: LiteSpeed, NVMe, Imunify360 and automatic backups."},
        ],
    },
    "proof-checklist-counter": {
        "*": [
            {"id": "includes", "narration": "{plan} includes {storage} GB of NVMe storage, free SSL, daily backups and Imunify360."},
            {"id": "every", "narration": "Every {plan} plan has {storage} GB of NVMe storage, free SSL and daily backups."},
        ],
    },
    "proof-plan-compare": {
        "*": [
            {"id": "room", "narration": "Need more room? {plan2} gives you {storage2} GB and {websites2} {sites_word}. Upgrade any time."},
            {"id": "outgrow", "narration": "Outgrow {plan}? {plan2} brings {storage2} GB of storage and {websites2} {sites_word}. Upgrade any time."},
        ],
    },
    "price-plan-card": {
        "*": [
            {"id": "renewal", "narration": "{plan} is {price} {currency_word} {period_word}, with free SSL, daily backups and the same price on renewal.",
             "needs": ["renewal", "not_domains"]},
            {"id": "renews", "narration": "{plan} is {price} {currency_word} {period_word}, and it renews at the same price.",
             "needs": ["renewal", "not_domains"]},
            {"id": "starts", "narration": "It all starts at {price} {currency_word} {period_word} on {plan}, and renews at the same price.",
             "needs": ["renewal", "lowest", "not_domains"]},
            {"id": "plain", "narration": "{plan}: {price} {currency_word} {period_word}, with free SSL and daily backups.",
             "needs": ["not_domains"]},
            {"id": "with", "narration": "{plan} is {price} {currency_word} {period_word}, with free SSL and daily backups.",
             "needs": ["not_domains"]},
            {"id": "domain", "narration": "{plan} is {price} {currency_word} a year, with free SSL and a free domain for the first year.",
             "needs": ["free_domain"]},
            {"id": "domain-pay", "narration": "Pay {price} {currency_word} a year for {plan}, with a free domain for the first year.",
             "needs": ["free_domain"]},
            {"id": "domain-short", "narration": "{plan}: {price} {currency_word} a year, plus a free domain for the first year.",
             "needs": ["free_domain"]},
        ],
    },
    "price-compare-cycles": {
        "wordpress": [
            {"id": "cycles", "narration": "{plan} is {monthly} {currency_word} a month, {semi} for six months, or {annual} for the whole year.",
             "needs": ["semi", "annual"]},
            {"id": "cycles-short", "narration": "{plan}: {monthly} {currency_word} a month, {semi} for six months, or {annual} a year.",
             "needs": ["semi", "annual"]},
            {"id": "cycles-lean", "narration": "{plan}: {monthly} {currency_word} monthly, {semi} for six months, {annual} yearly.",
             "needs": ["semi", "annual"]},
        ],
        "shared": [
            {"id": "matrix", "narration": "{plan} is {price} {currency_word} a month. Bigger plans add storage, more websites, and room to grow.",
             "needs": ["renewal"]},
            {"id": "matrix-plain", "narration": "Start on {plan} at {price} {currency_word} a month. Bigger plans add storage and websites when you need them."},
            {"id": "matrix-short", "narration": "{plan} is {price} {currency_word} a month. Bigger plans add storage and websites."},
        ],
        "domains": [
            {"id": "matrix", "narration": "{plan} is {price} {currency_word} a year with a free domain for the first year. Bigger plans add storage.",
             "needs": ["free_domain"]},
            {"id": "matrix-short", "narration": "{plan} is {price} {currency_word} a year. Bigger plans add storage and websites."},
        ],
    },
    "price-plans-lineup": {
        "*": [
            {"id": "popular", "narration": "Plans start at {price} {currency_word} {period_word} with {plan}; the most popular plan is one step up.",
             "needs": ["lowest", "plan2_popular", "not_domains"]},
            {"id": "fits", "narration": "{plan} is {price} {currency_word} {period_word}. Pick the plan that fits, and upgrade any time.",
             "needs": ["not_domains"]},
            {"id": "fits-short", "narration": "{plan} is {price} {currency_word} {period_word}. Pick your plan, upgrade any time.",
             "needs": ["not_domains"]},
            {"id": "popular-short", "narration": "Plans start at {price} {currency_word} {period_word} with {plan}. The most popular is one step up.",
             "needs": ["lowest", "plan2_popular", "not_domains"]},
            {"id": "start", "narration": "Plans start at {price} {currency_word} {period_word} with {plan}. Upgrade any time.",
             "needs": ["lowest", "not_domains"]},
            {"id": "domain", "narration": "Pick your plan. {plan} is {price} {currency_word} a year, with a free domain for the first year.",
             "needs": ["free_domain"]},
            {"id": "domain-short", "narration": "{plan} is {price} {currency_word} a year, with a free domain for the first year.",
             "needs": ["free_domain"]},
            {"id": "domain-lean", "narration": "{plan} is {price} {currency_word} a year. Free domain for the first year.",
             "needs": ["free_domain"]},
        ],
    },
    "price-counter-flat": {
        "*": [
            {"id": "still", "narration": "Pay {annual} {currency_word} for a year of {plan}. Renewal? Still {annual}.",
             "needs": ["annual", "renewal"]},
            {"id": "year-short", "narration": "One year of {plan} costs {annual} {currency_word}. Renewal? Still {annual}.",
             "needs": ["annual", "renewal"]},
            {"id": "year", "narration": "A year of {plan} costs {annual} {currency_word}. Next year, it renews at {annual} again.",
             "needs": ["annual", "renewal"]},
            {"id": "month", "narration": "{plan} is {monthly} {currency_word} a month, and it renews at {monthly} {currency_word}, month after month.",
             "needs": ["no_annual", "renewal"]},
        ],
    },
    "cta-outro": {
        "*": [
            # the trust pill lands on "Seven" (its number is never drawn before it is spoken); a short tail keeps the
            # last stretch of speech under the sync limit
            {"id": "guarantee", "narration": "{cta_spoken} at {domain}. Seven days, or your money back.", "needs": ["money_back"]},
            {"id": "click", "narration": "Your site is one click away. {cta_spoken} at {domain}.", "needs": ["not_domains"]},
            {"id": "live", "narration": "Ready to go live? {cta_spoken} at {domain}.", "needs": ["not_domains"]},
            {"id": "name", "narration": "Your name is waiting. {cta_spoken} at {domain}.", "needs": ["domains"]},
        ],
    },
    "cta-logo-lockup": {
        "*": [
            {"id": "brand", "narration": "{brand}. {cta_spoken} today at {domain}."},
            {"id": "ready", "narration": "Ready when you are. {cta_spoken} at {domain}."},
            {"id": "build", "narration": "Build it on {brand}. {cta_spoken} at {domain}."},
        ],
    },
    "proof-feature-checklist": {
        "domains": [
            {"id": "includes", "narration": "{plan} includes email on your domain, free SSL, daily backups, and instant activation."},
        ],
        "*": [
            {"id": "comes", "narration": "{plan} comes with free SSL, daily backups, free migration, and Imunify360 security."},
            {"id": "activation", "narration": "{plan} comes with free SSL, daily backups, free migration, and instant activation."},
        ],
    },
}

PACK = Pack(id="web-hosting", name="Web hosting (shared, WordPress, domains)", families=FAMILIES, fact_ids=FACT_IDS,
            gated_roles=GATED, features=FEATURES, feature_cues=FEATURE_CUES, templates=TEMPLATES, bank=BANK,
            blueprints=BLUEPRINTS, plan_features=plan_features, plan_detail=plan_detail, compare_rows=compare_rows,
            checklist_keys=checklist_keys, cta_sub_keys=["renewal", "ssl", "backups"], banned=BANNED, style=STYLE,
            term_roles=TERM_ROLES)
