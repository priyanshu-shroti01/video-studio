#!/usr/bin/env node
/**
 * Record real footage of the running Studio: drives the actual web UI in headless Chromium with scripted input
 * and records the real screen (Chrome DevTools Protocol screencast) into an MP4. Nothing is mocked: every frame
 * is the live application. Used for product footage (the `footage` block).
 *
 *   node scripts/capture_studio.mjs <plan.json>
 *
 * plan.json:
 *   {"url": "http://127.0.0.1:8765/?token=…",      // Studio login URL (the token is never logged)
 *    "out": "public/brands/<id>/footage/x.mp4",
 *    "viewport": {"width": 1440, "height": 900, "scale": 2},   // layout size; frames are width*scale x height*scale
 *    "steps": [{"nav": "#/new"}, {"wait": 800}, {"type": ["input[maxlength='120']", "Video Studio", 18]},
 *              {"select": ["select", "videostudio"]}, {"click": "button[type=submit]"}, {"clickText": "Select this concept"},
 *              {"waitFor": ".concept"}, {"scroll": 400}, {"hold": 1500}]}
 *
 * type: [selector, text, chars per second]; select: [selector, value]; click: selector; clickText: visible button text;
 * checkIndex: n-th checkbox; selectIndex: [n, value]; setValue: [selector, value];
 * waitFor: selector (up to 120 s); scroll: pixels (smooth); hold/wait: ms; record: true/false starts/stops recording (time off camera is
 * cut from the clip and from region times). The screencast only emits frames on change;
 * frame durations come from their timestamps, so pauses are kept exactly. Output: H.264 30 fps, yuv420p, BT.709.
 *
 * Recording for video (text must stay readable when the film shows the clip on a phone):
 *   viewport.uiScale (default 1): CSS zoom of the UI itself relative to the layout viewport. The page lays out in
 *     width/uiScale x height/uiScale CSS px and every glyph is uiScale x larger in the recording (frames stay
 *     width*scale x height*scale). A desktop UI recorded at uiScale 1 shows 13-14 px body text, i.e. ~1 % of the frame
 *     height: unreadable once the film shrinks the clip into a 9:16 column.
 *   crop: {x, y, w, h} in layout px of the viewport (before scale): only that part of the screen is encoded.
 *   {"region": ["name", "css selector"]} / {"regionText": ["name", "visible text"]}: records the element's bounding
 *     rect, normalised 0..1 to the encoded frame (after crop), with the clip time t (s since recording started) into
 *     the sidecar <out>.regions.json ([{name, t, x, y, w, h}]): the footage beats' `region` come from it.
 *     regionText takes an optional third item, a selector of the ancestor to report (e.g. ".card" for the whole card).
 *   {"scrollTo": "css selector"} / {"scrollToText": "visible text" | [text, ancestor]}: smooth-scrolls it to the middle of the view.
 *   {"play": "css selector"}: starts that <video> (muted).
 *   {"hover": "css selector"} / {"hoverText": "visible text" | [text, ancestor]}: glides the mouse onto the element (hover
 *     styles show) without clicking or scrolling: for read-only tours of cards and buttons.
 *
 * Presets (median OCR line height of a settled frame: "9:16" = clip height scaled to 1175 px and centre-cropped to
 * 940 px, the footage viewport of a Short before any zoom; "16:9" = clip scaled to 1000 px wide):
 *   video-legible   {"viewport": {"width": 1440, "height": 800, "scale": 2.4, "uiScale": 1.4},
 *                    "crop": {"x": 308, "y": 0, "w": 1132, "h": 800}}   (scripts/capture-plans/videostudio/*.json)
 *                   1029x571 CSS px of UI (the Studio's < 1180 px layout: 220 px sidebar, cropped away), 2716x1920 frames.
 *                   One clip serves both formats: 25-28.6 px (9:16) / 16-18 px (16:9), against 18 / 10 px for the
 *                   v1 desktop recordings (1440x900 at uiScale 1). Zoom beats of 1.3-4x come on top.
 *   phone-legible   {"viewport": {"width": 1600, "height": 1000, "scale": 2, "uiScale": 1.6}, "crop": tight, h <= ~780}
 *                   (scripts/capture-plans/videostudio/studio-*-v3.json): what decides text size in a 9:16 "fill" is the
 *                   CSS height of the crop (crop.h / uiScale), not uiScale alone, so crop to the part of the page the
 *                   clip is about (<= ~490 CSS px tall: ~31-45 px in 9:16 before zoom beats). Widen the layout (e.g.
 *                   2000 px) for wide tables, raise it (e.g. 1560 px) when a click recentres a tall element (the
 *                   storyboard player under its sticky toolbar). Clicks scroll their target to the middle of the view:
 *                   record a region again after a click.
 *   mobile-legible  {"width": 900, "height": 1300, "scale": 2, "uiScale": 1.75}  portrait-only footage (9:16 films);
 *                   514x743 CSS px: the UI's narrow layout, ~2.1x larger text than v1 in a Short.
 *   desktop-legible {"width": 1280, "height": 800, "scale": 2, "uiScale": 1.5}   16:9-only films (853x533 CSS px).
 * Keep the CSS height (height / uiScale) at or below ~600 px: text height in a Short scales with 1 / CSS height.
 */
import {spawn, spawnSync} from 'node:child_process';
import {mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join} from 'node:path';

const plan = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const vp = {width: 1440, height: 900, scale: 2, uiScale: 1, ...(plan.viewport || {})};
const zoom = vp.scale * vp.uiScale;                     // CSS zoom of the page (pixels x UI size)
const crop = plan.crop ? {x: 0, y: 0, w: vp.width, h: vp.height, ...plan.crop} : null;   // layout px
const regions = [];
const chrome = 'node_modules/.remotion/chrome-headless-shell/mac-arm64/chrome-headless-shell-mac-arm64/chrome-headless-shell';
const port = 9300 + Math.floor(Math.random() * 400);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const proc = spawn(chrome, ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox', '--single-process',
  '--no-zygote', '--use-mock-keychain', '--password-store=basic', '--no-first-run', '--hide-scrollbars', '--font-render-hinting=none',
  `--remote-debugging-port=${port}`, 'about:blank'], {stdio: 'ignore'});
let targets;
for (let i = 0; i < 60 && !targets; i++) { await sleep(250); try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); } catch { /* starting */ } }
const ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r));
let id = 0;
const pending = new Map();
const frames = [];
const tmp = mkdtempSync(join(tmpdir(), 'capture-'));
let recording = false;
let t0 = null;                                          // wall time of the first recorded frame (clip time 0)
let paused = 0;                                         // seconds spent with recording off (cut from the clip)
let pauseAt = null;
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method === 'Page.screencastFrame') {
    const {data, metadata, sessionId} = m.params;
    if (recording) {
      const f = join(tmp, `f${String(frames.length).padStart(6, '0')}.jpg`);
      writeFileSync(f, Buffer.from(data, 'base64'));
      if (!frames.length) t0 = Date.now() / 1000;
      frames.push({f, t: metadata.timestamp - paused, wall: Date.now() / 1000 - paused});
    }
    ws.send(JSON.stringify({id: ++id, method: 'Page.screencastFrameAck', params: {sessionId}}));
  }
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({id: i, method, params})); });
// Page code is a fixed function; plan values (selectors, texts, numbers) only ever travel as call arguments
// (Runtime.callFunctionOn), never spliced into source.
const call = async (fn, ...args) => {
  const g = await send('Runtime.evaluate', {expression: 'globalThis'});
  const r = await send('Runtime.callFunctionOn', {functionDeclaration: fn.toString(), objectId: g.result?.result?.objectId,
    arguments: args.map((value) => ({value})), awaitPromise: true, returnByValue: true});
  return r.result?.result?.value;
};
// Runs in the page. loc: {sel} | {text, up} (the smallest visible element whose text starts with `text`, or its
// closest `up` ancestor, e.g. its card) | {button} (a button or link by its text) | {all, i} (the i-th match).
function act(loc, action, arg) {
  let el = null;
  if (loc.sel !== undefined) el = document.querySelector(loc.sel);
  else if (loc.button !== undefined) el = [...document.querySelectorAll('button, a')].find((b) => b.textContent.trim().startsWith(loc.button));
  else if (loc.all !== undefined) el = document.querySelectorAll(loc.all)[loc.i];
  else if (loc.text !== undefined) {
    el = [...document.querySelectorAll('body *')].filter((e) => e.getClientRects().length && e.textContent.trim().startsWith(loc.text)
      && (!loc.up || e.closest(loc.up))).sort((a, b) => a.textContent.length - b.textContent.length)[0] || null;
    if (el && loc.up) el = el.closest(loc.up);
  }
  if (!el) return action === 'exists' ? false : null;
  const mid = () => { const r = el.getBoundingClientRect(); return {x: r.x + r.width / 2, y: r.y + r.height / 2}; };
  const setValue = (proto, value, event) => {
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value); el.dispatchEvent(new Event(event, {bubbles: true})); return true;
  };
  switch (action) {
    case 'exists': return true;
    case 'point': return mid();
    case 'centre': el.scrollIntoView({block: 'center', inline: 'center'}); return mid();
    case 'rect': { const r = el.getBoundingClientRect(); return {x: r.x / arg, y: r.y / arg, w: r.width / arg, h: r.height / arg}; }
    case 'scroll': el.scrollIntoView({behavior: 'smooth', block: 'center'}); return true;
    case 'play': el.muted = true; return el.play().then(() => true, () => false);
    case 'select': return setValue(HTMLSelectElement.prototype, arg, 'change');
    case 'input': return setValue(HTMLInputElement.prototype, arg, 'input');
    default: return null;
  }
}
const at = (loc, action, arg = null) => call(act, loc, action, arg);
const centre = (loc) => at(loc, 'centre');
let hoverAt = null;                                     // last pointer position of a hover step
const clickAt = async (p) => {
  for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) {
    await send('Input.dispatchMouseEvent', {type, x: p.x, y: p.y, button: 'left', clickCount: 1});
    await sleep(type === 'mouseMoved' ? 120 : 40);
  }
};
const q = (sel) => ({sel});
const byText = (text, up) => ({text, up});

await send('Page.enable');
await send('Runtime.enable');
// The screencast captures at layout size, so render the page at width*scale with CSS zoom = scale: same layout as a
// width x height screen, scale-times the pixels (sharp when the film zooms in). Input coordinates are viewport pixels.
await send('Emulation.setDeviceMetricsOverride', {width: vp.width * vp.scale, height: vp.height * vp.scale, deviceScaleFactor: 1, mobile: false});
// fixed source: the zoom itself is stored per origin by the call below, so later navigations open zoomed from the first paint
await send('Page.addScriptToEvaluateOnNewDocument', {source: "document.addEventListener('DOMContentLoaded', () => { "
  + "const z = sessionStorage.getItem('capture-studio-zoom'); if (z) document.documentElement.style.zoom = z; });"});
await send('Page.navigate', {url: plan.url});
await sleep(2500);                                      // token → cookie → app shell
const base = new URL(plan.url).origin + '/';
await call((z) => { sessionStorage.setItem('capture-studio-zoom', z); document.documentElement.style.zoom = z; }, String(zoom));
// an element's rect in layout px of the viewport (getBoundingClientRect is in viewport px of the width*scale metrics)
const rectOf = (loc) => at(loc, 'rect', vp.scale);   // an element's rect in layout px of the viewport
const record = async (name, loc) => {
  const r = await rectOf(loc); if (!r) throw new Error(`no region element for ${name}`);
  const c = crop || {x: 0, y: 0, w: vp.width, h: vp.height};
  const n = (v) => +Math.min(1, Math.max(0, v)).toFixed(4);
  const x0 = n((r.x - c.x) / c.w), y0 = n((r.y - c.y) / c.h), x1 = n((r.x + r.w - c.x) / c.w), y1 = n((r.y + r.h - c.y) / c.h);
  const t = t0 === null ? 0 : +((Date.now() / 1000) - t0 - paused).toFixed(2);
  regions.push({name, t, x: x0, y: y0, w: +(x1 - x0).toFixed(4), h: +(y1 - y0).toFixed(4)});
};
await send('Page.startScreencast', {format: 'jpeg', quality: 92, maxWidth: vp.width * vp.scale, maxHeight: vp.height * vp.scale, everyNthFrame: 1});
for (const s of plan.steps) {
  if (s.record === true && !recording) {   // restart the screencast so a static page still yields its first frame now
    if (pauseAt !== null) { paused += Date.now() / 1000 - pauseAt; pauseAt = null; }
    recording = true;
    await send('Page.stopScreencast');
    await send('Page.startScreencast', {format: 'jpeg', quality: 92, maxWidth: vp.width * vp.scale, maxHeight: vp.height * vp.scale, everyNthFrame: 1});
    for (let i = 0; i < 10 && !frames.length; i++) {   // no frame yet: repaint one invisible pixel to get one
      await call(() => { const d = document.createElement('div'); d.style.cssText = 'position:fixed;left:0;top:0;width:1px;height:1px;background:rgba(0,0,0,0.004);pointer-events:none';
        document.body.appendChild(d); setTimeout(() => d.remove(), 60); });
      await sleep(150);
    }
  }
  if (s.record === false && recording) {   // the last frame holds until now; the time off camera is cut, not kept
    recording = false;
    pauseAt = Date.now() / 1000;
    if (frames.length) { const last = frames.at(-1); frames.push({f: last.f, t: last.t + (pauseAt - paused - last.wall), wall: pauseAt - paused}); }
  }
  if (s.nav !== undefined) { await send('Page.navigate', {url: base + s.nav}); await sleep(1800); }
  if (s.wait || s.hold) await sleep(s.wait || s.hold);
  if (s.waitFor) {
    for (let i = 0; i < 600 && !(await at(q(s.waitFor), 'exists')); i++) await sleep(200);
  }
  if (s.click) { const p = await centre(q(s.click)); if (!p) throw new Error(`no element ${s.click}`); await clickAt(p); }
  if (s.clickText) {
    const p = await centre({button: s.clickText});
    if (!p) throw new Error(`no button "${s.clickText}"`);
    await clickAt(p);
  }
  if (s.region) await record(s.region[0], q(s.region[1]));
  if (s.regionText) await record(s.regionText[0], byText(s.regionText[1], s.regionText[2]));
  if (s.scrollTo || s.scrollToText) {       // smooth-scroll an element to the middle of the view (selector / visible text)
    const el = s.scrollTo ? q(s.scrollTo) : byText(...[s.scrollToText].flat());   // text or [text, ancestor selector]
    if (!(await at(el, 'scroll'))) {
      throw new Error(`no element ${s.scrollTo || s.scrollToText}`);
    }
    await sleep(900);
  }
  if (s.hover || s.hoverText) {              // move the mouse onto an element (hover styles), without clicking or scrolling
    const el = s.hover ? q(s.hover) : byText(...[s.hoverText].flat());
    const p = await at(el, 'point');
    if (!p) throw new Error(`no element ${s.hover || s.hoverText}`);
    for (let i = 1; i <= 12; i++) {           // a short glide from the last position, so the pointer path looks human
      const k = i / 12, from = hoverAt || p;
      await send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: from.x + (p.x - from.x) * k, y: from.y + (p.y - from.y) * k});
      await sleep(25);
    }
    hoverAt = p;
  }
  if (s.play) {                              // start a <video>/<audio> (muted: no autoplay prompt)
    await at(q(s.play), 'play');
  }
  if (s.select) {
    await at(q(s.select[0]), 'select', String(s.select[1]));
    await sleep(300);
  }
  if (s.check) {
    const p = await centre(q(s.check)); if (p) await clickAt(p);
  }
  if (s.checkIndex !== undefined) {         // the n-th checkbox on the page (labels share selectors)
    const p = await centre({all: 'input[type=checkbox]', i: Number(s.checkIndex)}); if (p) await clickAt(p);
  }
  if (s.selectIndex) {                      // [n, value]: the n-th <select> on the page
    await at({all: 'select', i: Number(s.selectIndex[0])}, 'select', String(s.selectIndex[1]));
    await sleep(300);
  }
  if (s.setValue) {                         // [selector, value]: replace an input's value (e.g. a number field)
    const p = await centre(q(s.setValue[0])); if (p) await clickAt(p);
    await at(q(s.setValue[0]), 'input', String(s.setValue[1]));
    await sleep(250);
  }
  if (s.type) {
    const [sel, text, cps = 16] = s.type;
    const p = await centre(q(sel)); if (!p) throw new Error(`no input ${sel}`);
    await clickAt(p);
    for (const ch of text) { await send('Input.insertText', {text: ch}); await sleep(1000 / cps); }
  }
  if (s.scroll) {                             // smooth scroll of whatever actually scrolls (main pane or the page)
    const n = 30;
    for (let i = 0; i < n; i++) {
      // the page itself counts too (its overflow is 'visible'): otherwise a small scrolling panel would win
      await call((dy) => { const all = [...document.querySelectorAll('*')].filter((el) => el.scrollHeight > el.clientHeight + 4 &&
        /(auto|scroll)/.test(getComputedStyle(el).overflowY)); const page = document.scrollingElement;
        if (page.scrollHeight > page.clientHeight + 4) all.push(page);
        const el = all.sort((a, b) => b.clientHeight - a.clientHeight)[0] || page;
        el.scrollBy(0, dy); }, s.scroll / n);
      await sleep(22);
    }
  }
}
await sleep(400);
const endT = Date.now() / 1000 - paused;       // keep the time after the last on-screen change (the screencast only sends changes)
await send('Page.stopScreencast');
ws.close();
proc.kill();
if (!frames.length) throw new Error('no frames recorded');
const offset = frames[0].t - (frames[0].wall ?? frames[0].t);
frames.push({f: frames[frames.length - 1].f, t: endT + offset});
// concat list: each frame lasts until the next one (exact pauses); the last holds 1 s
const lines = frames.map((fr, i) => `file '${fr.f}'\nduration ${Math.max(0.001, ((frames[i + 1]?.t ?? fr.t + 1) - fr.t)).toFixed(4)}`);
lines.push(`file '${frames[frames.length - 1].f}'`);
writeFileSync(join(tmp, 'list.txt'), lines.join('\n'));
mkdirSync(dirname(plan.out), {recursive: true});
const cropF = crop ? `crop=${Math.round(crop.w * vp.scale)}:${Math.round(crop.h * vp.scale)}:${Math.round(crop.x * vp.scale)}:${Math.round(crop.y * vp.scale)},` : '';
const r = spawnSync('ffmpeg', ['-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', join(tmp, 'list.txt'), '-vf',
  `fps=30,${cropF}scale=trunc(iw/2)*2:trunc(ih/2)*2:flags=lanczos,format=yuv420p`, '-c:v', 'libx264', '-preset', 'slow', '-crf', '16',
  '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-movflags', '+faststart', plan.out], {stdio: 'inherit'});
rmSync(tmp, {recursive: true, force: true});
if (r.status !== 0) throw new Error('ffmpeg failed');
if (regions.length) writeFileSync(plan.out.replace(/\.[a-z0-9]+$/i, '') + '.regions.json', JSON.stringify(regions, null, 1) + '\n');
console.log(JSON.stringify({out: plan.out, frames: frames.length, seconds: +(frames.at(-1).t - frames[0].t).toFixed(2)}));
