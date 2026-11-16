"""Hinglish copy bank (brief `language: "hinglish"`; pipeline/creative/language.py).

The same shape as the English banks (copybank.GENERIC_BANK, each pack's BANK): template id -> product family
("*" = any) -> variants {"id", "narration", "headline"?, "emphasis"?, "needs"?, "tags"?}. Lookup order is the same
too: the pack's Hinglish copy first, then the generic Hinglish layer. There is NO fallback to English: a template
without a Hinglish line is not used by a Hinglish concept (the director picks another candidate for that slot).

House style: Latin-script Hinglish as Indian short-form creators write it. Hindi grammar, everyday Hindi words, and
English for product and tech nouns ("product video", "website", "storyboard", "render", "plan", "domain"); short,
punchy sentences; casual second person ("aap", "dekho", "chuno"). No Urdu-heavy or textbook Hindi. The rules of the
English bank still hold: numbers only through placeholders bound to verified facts (written as digits; the voice
says them in Hindi), a template's narrative counts may be said in Hindi words ("teen ideas", "saat din"), no
clichés or superlatives, and every line keeps the cue words its template animates on: English cue words stay
English, and where Hindi says the cue ("Milo" for "Meet", "insaan" for "person") language.CUE_ALIASES maps it.

Not translated (no Hinglish line, so not used in Hinglish films): web-hosting `proof-plan-compare` (its English
lines need a {sites_word} value no product supplies, so it is unused in English too)"""
from __future__ import annotations

GENERIC: dict[str, dict[str, list[dict]]] = {
    # explainer ending: only the next part the brief names (brief.next_episode)
    "cta-next-episode": {"*": [
        {"id": "next", "narration": "Agle part mein, {next_label}: {next_title}."},
    ]},
    "hook-kinetic-spotlight": {"*": [
        {"id": "properly", "narration": "Aapko pata hai kya chahiye. Yeh raha {product_label}.", "tags": ["promise"]},
        {"id": "choosing", "narration": "{product_label} le rahe ho? Pehle dekho, kya milta hai.", "tags": ["question"]},
    ]},
    "turn-logo-sting": {"*": [
        {"id": "meet", "narration": "Milo {brand} se: {product_label}, simple aur saaf.", "headline": "{product_label}, simple aur saaf."},
    ]},
    "price-plan-card": {"*": [
        {"id": "plain", "narration": "{plan} ka price hai {price} {currency_word} {period_per}, aur card ke saare features included."},
        {"id": "short", "narration": "{plan}: {price} {currency_word} {period_per}. Card par jo bhi hai, sab included."},
    ]},
    "price-plans-lineup": {"*": [
        {"id": "fits", "narration": "{plan} hai {price} {currency_word} {period_per}. Aapko jo plan fit ho, wahi chuno."},
    ]},
    "price-compare-cycles": {"*": [
        {"id": "matrix", "narration": "{plan}: {price} {currency_word} {period_per}. Bade plans mein aur room hai."},
    ]},
    "price-counter-flat": {"*": [
        {"id": "renews", "narration": "{plan} hai {price} {currency_word} {period_per}, aur renewal par bhi wahi {price}.",
         "needs": ["renewal"]},
    ]},
    "cta-outro": {"*": [
        {"id": "ready", "narration": "Jab aap ready ho, {cta_spoken}, {domain} par."},
    ]},
    "cta-logo-lockup": {"*": [
        {"id": "brand", "narration": "{brand}. {cta_spoken}, aaj hi, {domain} par."},
        {"id": "ready", "narration": "Jab aap ready ho, {cta_spoken}, {domain} par."},
    ]},
}

# ---- software pack (family "app") ----------------------------------------------------------------------------------
SOFTWARE: dict[str, dict[str, list[dict]]] = {
    # ---- explainer style ("Myth, Steps, Proof"; pipeline/creative/explain.py) ----
    "hook-myth-verdict": {"app": [
        {"id": "agency", "narration": "Product video ke liye agency chahiye, ya mehenga subscription? Galat. Dono ki jarurat nahi.",
         "headline": "Product video ke liye agency chahiye, ya mehenga subscription?", "verdict": "Galat",
         "danger": ["agency", "mehenga subscription"], "tags": ["myth"]},
        {"id": "budget", "narration": "Product video ke liye bada budget chahiye? Galat.",
         "headline": "Product video ke liye bada budget chahiye?", "verdict": "Galat", "danger": ["bada budget"], "tags": ["myth"]},
    ]},
    "turn-term-reveal": {"app": [
        {"id": "meet", "narration": "Milo {brand} se: brief do, film lo, sab aapke Mac par.", "kicker": "Milo",
         "sub": "brief do, film lo", "pill": "sab aapke Mac par"},
        {"id": "short", "narration": "Milo {brand} se. Brief do, film lo.", "kicker": "Milo", "sub": "Brief do, film lo"},
    ]},
    "step-brief-footage": {"app": [
        {"id": "brief", "narration": "Step {step}: website chuno, chhota sa brief likho, aur teen ideas lo."},
        {"id": "short", "narration": "Step {step}: brief likho, aur teen ideas lo."},
    ]},
    "step-preview-footage": {"app": [
        {"id": "watch", "narration": "Step {step}: render se pehle preview mein har frame dekho, asli voice ke saath."},
        {"id": "short", "narration": "Step {step}: render se pehle har frame preview karo."},
    ]},
    "step-qa-gauge": {"app": [
        {"id": "checks", "narration": "Step {step}: yeh khud apna kaam check karta hai, {qa_spoken} blocking checks. Sab pass.",
         "verdict": "Sab pass"},
        {"id": "short", "narration": "Step {step}: {qa_spoken} blocking checks. Sab pass.", "verdict": "Sab pass"},
    ]},
    "point-zero-cost": {"app": [
        {"id": "cost", "narration": "Kharcha? Sirf {cost_spoken}. Na subscription, na API keys.", "pill": "Kharcha?"},
        {"id": "short", "narration": "Kharcha? Bas {cost_spoken}. Na subscription.", "pill": "Kharcha?"},
    ]},
    "cta-poll": {"app": [
        {"id": "first", "narration": "Aap pehle kya banaoge? Product demo, launch film, ya YouTube Short?",
         "question": "Aap pehle kya banaoge?", "options": ["Product demo", "launch film", "YouTube Short"]},
        {"id": "short", "narration": "Pehle kya banaoge? Demo, launch film, ya Short?",
         "question": "Pehle kya banaoge?", "options": ["Demo", "launch film", "Short"]},
    ]},
    "cta-comment-keyword": {"app": [
        {"id": "step", "narration": "Aap kaunsa step pehle try karoge? Comment karo, jaise PREVIEW.",
         "prompt": "Aap kaunsa step pehle try karoge?", "keyword": "PREVIEW"},
    ]},
    "hook-kinetic-spotlight": {"app": [
        {"id": "question", "narration": "Socho, aapka banaya software khud apni launch film bana de?",
         "headline": "khud apni launch film bana de?", "emphasis": ["film"], "tags": ["question"]},
    ]},
    "hook-chain-progress": {"app": [
        {"id": "chain", "narration": "Script. Storyboard. Voice. Animation. Render. Har launch film ek lambi chain hai.",
         "headline": "Har launch film ek lambi chain hai.", "emphasis": ["chain"], "tags": ["promise"]},
    ]},
    "hook-self-footage": {"app": [
        {"id": "watching", "narration": "Aap jo film dekh rahe ho, use isi software ne banaya hai.",
         "headline": "isi software ne banaya hai.", "emphasis": ["banaya"], "tags": ["twist"]},
    ]},
    "problem-production-chain": {"app": [
        {"id": "usual", "narration": "Launch film ka matlab: script, storyboard, voice-over, animation aur rendering. "
                                     "Har step ka alag tool, aur alag time.",
         "headline": "Har step ka alag tool, aur alag time.", "emphasis": ["time."]},
    ]},
    "turn-logo-sting": {"app": [
        {"id": "meet", "narration": "Milo {brand} se. Brief do, aur poori film lo.", "headline": "Brief do, aur poori film lo."},
    ]},
    "hook-zero-cost": {"app": [
        {"id": "promise", "narration": "Product videos ka kharcha: {cost_spoken}. Na subscription, na API keys.",
         "headline": "Product videos ka kharcha: {cost_spoken}.", "tags": ["promise"]},
    ]},
    "demo-app-footage": {"app": [
        {"id": "wizard", "narration": "Apni website chuno, product likho, audience batao. Studio teen ideas deta hai, "
                                      "aap chuno."},
        {"id": "brief", "narration": "Brief likho: product, audience, goal. Studio teen concepts deta hai. "
                                     "Aap ek chuno: designed scenes ke saath."},
        {"id": "short", "narration": "Apni website chuno, product likho, aur studio teen ideas deta hai, chunne ke liye."},
    ]},
    "demo-storyboard-footage": {"app": [
        {"id": "storyboard", "narration": "Concept chuno, aur storyboard taiyaar: har scene designed, har animation usi word par "
                                          "jo use bolta hai."},
    ]},
    "demo-pipeline": {"app": [
        {"id": "stages", "narration": "Phir pipeline: Concepts. Storyboard. Preview gate. Local voice. Render. "
                                      "Quality checks. Aur ship se pehle, ek insaan approve karta hai."},
    ]},
    "explain-architecture": {"app": [
        {"id": "principle", "narration": "Rule simple hai: AI propose kare, insaan decide karein, code exact rakhe: "
                                         "timing, layout, facts aur files.",
         "headline": "timing, layout, facts aur files.", "emphasis": ["files."]},
    ]},
    "demo-preview-gate": {"app": [
        # Hindi puts the verb last: "dekho" (watch) comes first here so the zooms follow the narration in order
        {"id": "watch", "narration": "Render se pehle dekho: har frame, asli awaaz, har scene preview mein. Phir approve karo."},
        {"id": "short", "narration": "Render se pehle dekho: har frame, asli awaaz, aur har scene preview mein."},
        {"id": "gate", "narration": "Storyboard mein har animation apne word par. Voice se pehle, har scene ka preview. "
                                    "Gate check karta hai, insaan approve karta hai."},
    ]},
    "demo-render-footage": {"app": [
        {"id": "stages", "narration": "Render ke stages dekho: pehle voice, phir timeline, frames, mix, aur checks."},
    ]},
    "demo-publishing-footage": {"app": [
        {"id": "publish", "narration": "Aakhir mein: insaan approve kare, phir Publishing, ek alag, confirmed step. "
                                       "Ek asli Short isi tarike se YouTube tak pahuncha."},
    ]},
    "proof-local-stack": {"app": [
        {"id": "local", "narration": "Python, Kokoro, Remotion aur FFmpeg. Sab kuch locally, ek hi Mac par."},
        {"id": "short", "narration": "Python, Kokoro, Remotion aur FFmpeg. Sab kuch ek Mac par."},
    ]},
    "proof-qa-counter": {"app": [
        {"id": "checks", "narration": "{qa_spoken} blocking checks pass: picture aur audio sync, har claim verified, "
                                      "captions checked."},
    ]},
    "reveal-self-footage": {"app": [
        {"id": "itself", "narration": "Aur yeh film? Ise {brand} ne khud banaya hai.",
         "headline": "{brand} ne khud banaya hai.", "emphasis": ["khud"]},
    ]},
    "cta-outro": {"app": [
        {"id": "code", "narration": "{cta_spoken}, GitHub par. Built to create. Used to create itself.",
         "headline": "Built to create. Used to create itself."},
    ]},
    "cta-logo-lockup": {"app": [
        {"id": "code", "narration": "{cta_spoken}, GitHub par. Dekho kaise bana."},
    ]},
}

# ---- web-hosting pack ----------------------------------------------------------------------------------------------
WEB_HOSTING: dict[str, dict[str, list[dict]]] = {
    # ---- explainer style ("Myth, Steps, Proof"; pipeline/creative/explain.py) ----
    "hook-myth-verdict": {
        "wordpress": [
            {"id": "weekend", "narration": "WordPress setup mein poora weekend lagta hai? Galat.",
             "headline": "WordPress setup mein poora weekend lagta hai?", "verdict": "Galat", "danger": ["poora weekend"],
             "tags": ["myth"]},
            {"id": "click", "narration": "WordPress setup mein poora weekend lagta hai? Galat. Bas ek click.",
             "headline": "WordPress setup mein poora weekend lagta hai?", "verdict": "Galat", "danger": ["poora weekend"],
             "tags": ["myth"]},
            {"id": "cost", "narration": "Fast WordPress hosting mehengi hi hoti hai? Galat.",
             "headline": "Fast WordPress hosting mehengi hi hoti hai?", "verdict": "Galat", "danger": ["mehengi"], "tags": ["myth"]},
        ],
        "shared": [
            {"id": "weekend", "narration": "Website ke liye developer aur poora weekend chahiye? Galat.",
             "headline": "Website ke liye developer aur poora weekend chahiye?", "verdict": "Galat",
             "danger": ["developer", "poora weekend"], "tags": ["myth"]},
            {"id": "cost", "narration": "Achhi hosting mehengi hi hoti hai? Galat.", "headline": "Achhi hosting mehengi hi hoti hai?",
             "verdict": "Galat", "danger": ["mehengi"], "tags": ["myth"]},
        ],
    },
    "turn-term-reveal": {
        "wordpress": [
            {"id": "meet", "narration": "Milo {brand} se: WordPress hosting, fast chalne ke liye tuned.", "kicker": "Milo",
             "sub": "WordPress hosting", "pill": "fast chalne ke liye tuned", "pill_icon": "zap"},
            {"id": "short", "narration": "Milo {brand} se. WordPress, fast aur tuned.", "kicker": "Milo",
             "sub": "WordPress", "pill": "fast aur tuned", "pill_icon": "zap"},
        ],
        "shared": [
            {"id": "meet", "narration": "Milo {brand} se: fast shared hosting, imaandaar price.", "kicker": "Milo",
             "sub": "fast shared hosting", "pill": "imaandaar price", "pill_icon": "check"},
        ],
    },
    "step-domain-search": {
        "wordpress": [
            {"id": "type", "narration": "Step {step}: apna domain type karo aur launch dabao. Aap live ho."},
            {"id": "short", "narration": "Step {step}: domain search karo aur launch dabao."},
        ],
        "shared": [
            {"id": "type", "narration": "Step {step}: apna domain type karo aur launch dabao. Aap live ho."},
            {"id": "short", "narration": "Step {step}: domain search karo aur launch dabao."},
        ],
    },
    "step-install-flow": {
        "wordpress": [
            {"id": "click", "narration": "Step {step}: ek click mein WordPress, plugins aur SSL install. Aap live ho."},
            {"id": "short", "narration": "Step {step}: ek click, aur WordPress install. Aap live ho."},
        ],
    },
    "step-device-site": {
        "*": [
            {"id": "phone", "narration": "Step {step}: aapki site phone par live, free SSL ke saath."},
            {"id": "short", "narration": "Step {step}: aapki site live, free SSL ke saath."},
        ],
    },
    "step-uptime-gauge": {
        "*": [
            {"id": "online", "narration": "Step {step}: {uptime} percent uptime target, aap online rehte ho.", "verdict": "online"},
        ],
    },
    "step-refund-countdown": {
        "*": [
            {"id": "try", "narration": "Step {step}: saat din try karo, warna paise wapas.", "needs": ["money_back"]},
        ],
    },
    "cta-poll": {
        "wordpress": [
            {"id": "build", "narration": "Aap pehle kya banaoge? Blog, online shop, ya portfolio?",
             "question": "Aap pehle kya banaoge?", "options": ["Blog", "online shop", "portfolio"]},
        ],
        "shared": [
            {"id": "live", "narration": "Pehle kya live hoga? Business site, blog, ya portfolio?",
             "question": "Pehle kya live hoga?", "options": ["Business site", "blog", "portfolio"]},
        ],
    },
    "cta-comment-keyword": {
        "*": [
            {"id": "stuck", "narration": "Kisi step par atke ho? Comment karo SETUP, aur batao kahan.",
             "prompt": "Kisi step par atke ho?", "keyword": "SETUP"},
        ],
    },
    "hook-kinetic-spotlight": {
        "wordpress": [
            {"id": "home", "narration": "Idea aapka hai. Ab WordPress site ko ghar chahiye.",
             "emphasis": ["ghar"], "tags": ["question"]},
            {"id": "decision", "narration": "Har WordPress site ka pehla faisla: woh kahan rahegi.",
             "emphasis": ["kahan"], "tags": ["promise"]},
            {"id": "closer", "narration": "Achhi WordPress hosting mehngi hoti hai? Zara dhyan se dekho.",
             "emphasis": ["dekho."], "tags": ["myth"]},
            {"id": "lean", "narration": "Aapki WordPress site ko ek ghar chahiye.", "emphasis": ["ghar"], "tags": ["question"]},
        ],
        "shared": [
            {"id": "home", "narration": "Idea aapka hai. Ab website ko ghar chahiye.", "emphasis": ["ghar"], "tags": ["question"]},
            {"id": "decision", "narration": "Har website ka pehla faisla: woh kahan rahegi.", "emphasis": ["kahan"],
             "tags": ["promise"]},
            {"id": "closer", "narration": "Achhi hosting mehngi hoti hai? Zara dhyan se dekho.", "emphasis": ["dekho."],
             "tags": ["myth"]},
            {"id": "lean", "narration": "Aapki nayi website ko ek ghar chahiye.", "emphasis": ["ghar"], "tags": ["question"]},
        ],
        "domains": [
            {"id": "find", "narration": "Aapke business ko ek naam chahiye, jo log dhoondh sakein.", "emphasis": ["naam"], "tags": ["question"]},
            {"id": "address", "narration": "Har brand online ek address se shuru hota hai.", "emphasis": ["address."],
             "tags": ["promise"]},
            {"id": "taken", "narration": "Har achha naam le liya gaya? Phir se dekho.", "emphasis": ["dekho."], "tags": ["myth"]},
        ],
    },
    "hook-progress-promise": {
        "wordpress": [
            {"id": "route", "narration": "Live WordPress site chahiye? Plan chuno, domain lo, aur install par click karo.",
             "headline": "Live WordPress site chahiye?", "emphasis": ["Live"]},
            {"id": "lean", "narration": "Live WordPress site: ek plan, ek domain, aur ek click.",
             "headline": "Live WordPress site", "emphasis": ["Live"]},
        ],
        "shared": [
            {"id": "route", "narration": "Live website chahiye? Plan chuno, domain lo, aur click karke live jao.",
             "headline": "Live website chahiye?", "emphasis": ["Live"]},
        ],
        "domains": [
            {"id": "name", "narration": "Online aane ki shuruaat ek naam se: search karo, register karo, email jodo.",
             "headline": "Online aane ki shuruaat", "emphasis": ["Online"]},
        ],
    },
    "hook-stalled-browser": {
        "wordpress": [
            {"id": "left", "narration": "WordPress site abhi bhi load ho rahi hai. Visitor chala gaya.",
             "headline": "Visitor chala gaya.", "emphasis": ["gaya."]},
        ],
        "shared": [
            {"id": "left", "narration": "Site abhi bhi load ho rahi hai. Visitor chala gaya.",
             "headline": "Visitor chala gaya.", "emphasis": ["gaya."]},
        ],
    },
    "hook-site-missing": {
        "wordpress": [
            {"id": "nothing", "narration": "Customer aapki shop search karta hai. Kuch nahi milta.", "headline": "Kuch nahi milta.",
             "emphasis": ["Kuch"], "tags": ["pain-point"]},
        ],
        "shared": [
            {"id": "nothing", "narration": "Customer aapki shop search karta hai. Kuch nahi milta.", "headline": "Kuch nahi milta.",
             "emphasis": ["Kuch"], "tags": ["pain-point"]},
        ],
        "domains": [
            {"id": "nothing", "narration": "Koi aapka business search karta hai. Kuch nahi milta.", "headline": "Kuch nahi milta.",
             "emphasis": ["Kuch"], "tags": ["pain-point"]},
        ],
    },
    "problem-diy-terminal": {
        "wordpress": [
            {"id": "weekend", "narration": "WordPress khud setup karna: config files, database errors, aur poora weekend gaya.",
             "headline": "poora weekend gaya.", "emphasis": ["weekend"]},
            {"id": "lean", "narration": "WordPress khud setup? Config files, database errors, weekend gaya.",
             "headline": "weekend gaya.", "emphasis": ["weekend"]},
        ],
        "shared": [
            {"id": "weekend", "narration": "Server khud setup karna: config files, permission errors, aur poora weekend gaya.",
             "headline": "poora weekend gaya.", "emphasis": ["weekend"]},
            {"id": "lean", "narration": "Server khud setup? Config files, permission errors, weekend gaya.",
             "headline": "weekend gaya.", "emphasis": ["weekend"]},
        ],
    },
    "problem-renewal-compare": {"*": [
        {"id": "increases", "narration": "Renewal par signup wala price aksar badh jaata hai. Backups ka paisa bhi alag.",
         "headline": "price aksar badh jaata hai.", "emphasis": ["badh"], "needs": ["typical_backups"]},
        {"id": "renewal-only", "narration": "Renewal par, signup wala price aksar badh jaata hai.",
         "headline": "price aksar badh jaata hai.", "emphasis": ["badh"]},
    ]},
    "turn-logo-sting": {
        "wordpress": [
            {"id": "meet", "narration": "Milo {brand} se. WordPress hosting, fast chalne ke liye.",
             "headline": "WordPress hosting, fast chalne ke liye.", "emphasis": ["fast"]},
            {"id": "lean", "narration": "Milo {brand} se: fast WordPress hosting.", "headline": "fast WordPress hosting.",
             "emphasis": ["fast"]},
        ],
        "shared": [
            {"id": "meet", "narration": "Milo {brand} se. Fast shared hosting, honest price par.",
             "headline": "Fast shared hosting, honest price par.", "emphasis": ["honest"]},
            {"id": "lean", "narration": "Milo {brand} se: fast shared hosting.", "headline": "fast shared hosting.",
             "emphasis": ["fast"]},
        ],
        "domains": [
            {"id": "meet", "narration": "Milo {brand} se. Domain aur hosting, ek hi jagah.",
             "headline": "Domain aur hosting, ek hi jagah.", "emphasis": ["jagah."]},
        ],
    },
    "demo-install-flow": {
        "wordpress": [
            {"id": "installs", "narration": "Ek click, aur WordPress install: theme, plugins, SSL aur LiteSpeed Cache. Aap live ho."},
            {"id": "lean", "narration": "Ek click: WordPress, theme, plugins, SSL, LiteSpeed Cache. Aur aap live."},
        ],
        "shared": [
            {"id": "want", "narration": "WordPress chahiye? Ek click: theme, plugins, SSL aur LiteSpeed Cache ke saath. "
                                        "Aap live ho."},
            {"id": "lean", "narration": "Ek click: WordPress, theme, plugins, SSL, LiteSpeed Cache. Aur aap live."},
        ],
    },
    "demo-domain-search": {
        "wordpress": [
            {"id": "type", "narration": "Domain type karo, launch dabao, aur live ho jao. Free SSL, daily backups."},
            {"id": "lean", "narration": "Apna domain type karo, launch dabao, aur live ho jao."},
        ],
        "shared": [
            {"id": "type", "narration": "Domain type karo, launch dabao, aur live ho jao. Free SSL, daily backups."},
            {"id": "lean", "narration": "Apna domain type karo, launch dabao, aur live ho jao."},
        ],
        "domains": [
            {"id": "type", "narration": "Jo naam chahiye, type karo. Available hai, toh claim karo aur email jodo."},
        ],
    },
    "demo-dashboard": {
        "domains": [
            {"id": "sits", "narration": "cPanel mein sab: domain, email, free SSL aur daily backups."},
        ],
        "*": [
            {"id": "sits", "narration": "Sab kuch cPanel mein: NVMe storage, daily backups aur Imunify360 security."},
            {"id": "lean", "narration": "cPanel mein sab: NVMe storage, daily backups, Imunify360 security."},
        ],
    },
    "demo-device-site": {
        "wordpress": [
            {"id": "live", "narration": "Aapki WordPress site live hai, aapke apne domain par. Free SSL. Daily backups."},
            {"id": "lean", "narration": "WordPress site live, apne domain par. Free SSL, daily backups."},
        ],
        "shared": [
            {"id": "live", "narration": "Aapki site live hai, aapke apne domain par. Free SSL. Daily backups."},
            {"id": "lean", "narration": "Site live, apne domain par. Free SSL, daily backups."},
        ],
        "domains": [
            {"id": "name", "narration": "Aapka naam live hai, aapke apne domain par, email aur free SSL ke saath."},
        ],
    },
    "demo-scroll-site": {
        "wordpress": [
            {"id": "runs", "narration": "Aapki nayi site LiteSpeed par chalti hai, free SSL, daily backups aur WooCommerce ready ke saath."},
            {"id": "lean", "narration": "Nayi site: LiteSpeed, free SSL, daily backups, WooCommerce ready."},
        ],
        "shared": [
            {"id": "runs", "narration": "Nayi site LiteSpeed aur NVMe storage par chalti hai, free SSL aur daily backups ke saath."},
            {"id": "lean", "narration": "Nayi site: LiteSpeed, NVMe, free SSL aur daily backups."},
        ],
    },
    "proof-server-stack": {"*": [
        {"id": "hood", "narration": "Andar se: LiteSpeed servers, NVMe storage, Imunify360 security aur automatic daily backups."},
        {"id": "lean", "narration": "Andar se: LiteSpeed, NVMe storage, Imunify360 aur automatic backups."},
    ]},
    "proof-checklist-counter": {"*": [
        {"id": "includes", "narration": "{plan} mein {storage} GB NVMe storage, free SSL, daily backups aur Imunify360 milta hai."},
        {"id": "lean", "narration": "{plan}: {storage} GB NVMe, free SSL, daily backups, Imunify360."},
    ]},
    "price-plan-card": {"*": [
        {"id": "renewal", "narration": "{plan}: {price} {currency_word} {period_per}, free SSL, daily backups, aur renewal par same price.",
         "needs": ["renewal", "not_domains"]},
        {"id": "plain", "narration": "{plan}: {price} {currency_word} {period_per}, free SSL aur daily backups ke saath.",
         "needs": ["not_domains"]},
        {"id": "lean", "narration": "{plan}: {price} {currency_word} {period_per}. Free SSL, daily backups.", "needs": ["not_domains"]},
        {"id": "domain", "narration": "{plan}: {price} {currency_word} {period_per}, free SSL aur pehle saal free domain ke saath.",
         "needs": ["free_domain"]},
    ]},
    "price-compare-cycles": {
        "wordpress": [
            {"id": "cycles", "narration": "{plan}: {monthly} {currency_word} monthly, {semi} mein chhe mahine, ya {annual} mein poora saal.",
             "needs": ["semi", "annual"]},
            {"id": "cycles-lean", "narration": "{plan}: {monthly} {currency_word} monthly, {semi} chhe mahine, {annual} saal bhar.",
             "needs": ["semi", "annual"]},
        ],
        "shared": [
            {"id": "matrix-short", "narration": "{plan}: {price} {currency_word} per month. Bade plans mein storage aur websites zyada."},
        ],
        "domains": [
            {"id": "matrix-short", "narration": "{plan}: {price} {currency_word} per year. Bade plans mein storage aur websites zyada."},
        ],
    },
    "price-plans-lineup": {"*": [
        {"id": "fits", "narration": "{plan}: {price} {currency_word} {period_per}. Aapko jo plan fit ho, wahi chuno.",
         "needs": ["not_domains"]},
        {"id": "fits-short", "narration": "{plan}: {price} {currency_word} {period_per}. Apna plan chuno, kabhi bhi upgrade karo.",
         "needs": ["not_domains"]},
        {"id": "domain", "narration": "{plan}: {price} {currency_word} per year. Apna plan chuno, free domain pehle saal.",
         "needs": ["free_domain"]},
    ]},
    "price-counter-flat": {"*": [
        {"id": "still", "narration": "{plan} ka ek saal {annual} {currency_word} ka. Renewal? Phir bhi {annual}.",
         "needs": ["annual", "renewal"]},
        {"id": "month", "narration": "{plan}: {monthly} {currency_word} per month, aur renewal par bhi wahi {monthly} {currency_word}.",
         "needs": ["no_annual", "renewal"]},
    ]},
    "cta-outro": {"*": [
        {"id": "guarantee", "narration": "{cta_spoken}, {domain} par. Saat din mein paise wapas.", "needs": ["money_back"]},
    ]},
    "cta-logo-lockup": {"*": [
        {"id": "brand", "narration": "{brand}. {cta_spoken}, aaj hi, {domain} par."},
        {"id": "build", "narration": "{brand} par banao. {cta_spoken}, {domain} par."},
    ]},
    "proof-feature-checklist": {
        "domains": [
            {"id": "includes", "narration": "{plan} mein domain email, free SSL, daily backups aur instant activation."},
        ],
        "*": [
            {"id": "comes", "narration": "{plan} ke saath free SSL, daily backups, free migration aur Imunify360 security."},
        ],
    },
}

PACKS = {"software": SOFTWARE, "web-hosting": WEB_HOSTING}


def banks(lang: str, pack_id: str) -> tuple[dict, ...]:
    """The banks to search for a language, highest priority first (pack, then generic). Unknown language: none."""
    if lang != "hinglish":
        return ()
    return tuple(b for b in (PACKS.get(pack_id), GENERIC) if b)
