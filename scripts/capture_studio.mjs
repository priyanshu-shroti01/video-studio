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
 * waitFor: selector (up to 120 s); scroll: pixels (smooth); hold/wait: ms; record: true/false starts/stops recording. The screencast only emits frames on change;
 * frame durations come from their timestamps, so pauses are kept exactly. Output: H.264 30 fps, yuv420p, BT.709.
 */
import {spawn, spawnSync} from 'node:child_process';
import {mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join} from 'node:path';

const plan = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const vp = {width: 1440, height: 900, scale: 2, ...(plan.viewport || {})};
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
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method === 'Page.screencastFrame') {
    const {data, metadata, sessionId} = m.params;
    if (recording) {
      const f = join(tmp, `f${String(frames.length).padStart(6, '0')}.jpg`);
      writeFileSync(f, Buffer.from(data, 'base64'));
      frames.push({f, t: metadata.timestamp, wall: Date.now() / 1000});
    }
    ws.send(JSON.stringify({id: ++id, method: 'Page.screencastFrameAck', params: {sessionId}}));
  }
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({id: i, method, params})); });
const evaluate = async (expr) => (await send('Runtime.evaluate', {expression: expr, awaitPromise: true, returnByValue: true})).result?.result?.value;
const centre = async (js) => evaluate(`(() => { const el = ${js}; if (!el) return null; el.scrollIntoView({block: 'center', inline: 'center'});
  const r = el.getBoundingClientRect(); return {x: r.x + r.width / 2, y: r.y + r.height / 2}; })()`);
const clickAt = async (p) => {
  for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) {
    await send('Input.dispatchMouseEvent', {type, x: p.x, y: p.y, button: 'left', clickCount: 1});
    await sleep(type === 'mouseMoved' ? 120 : 40);
  }
};
const q = (sel) => `document.querySelector(${JSON.stringify(sel)})`;

await send('Page.enable');
await send('Runtime.enable');
// The screencast captures at layout size, so render the page at width*scale with CSS zoom = scale: same layout as a
// width x height screen, scale-times the pixels (sharp when the film zooms in). Input coordinates are viewport pixels.
await send('Emulation.setDeviceMetricsOverride', {width: vp.width * vp.scale, height: vp.height * vp.scale, deviceScaleFactor: 1, mobile: false});
await send('Page.addScriptToEvaluateOnNewDocument', {source: `document.addEventListener('DOMContentLoaded', () => { document.documentElement.style.zoom = '${vp.scale}'; });`});
await send('Page.navigate', {url: plan.url});
await sleep(2500);                                      // token → cookie → app shell
const base = new URL(plan.url).origin + '/';
await evaluate(`document.documentElement.style.zoom = '${vp.scale}'`);
await send('Page.startScreencast', {format: 'jpeg', quality: 92, maxWidth: vp.width * vp.scale, maxHeight: vp.height * vp.scale, everyNthFrame: 1});
for (const s of plan.steps) {
  if (s.record === true) recording = true;
  if (s.record === false) recording = false;
  if (s.nav !== undefined) { await send('Page.navigate', {url: base + s.nav}); await sleep(1800); }
  if (s.wait || s.hold) await sleep(s.wait || s.hold);
  if (s.waitFor) {
    for (let i = 0; i < 600 && !(await evaluate(`!!${q(s.waitFor)}`)); i++) await sleep(200);
  }
  if (s.click) { const p = await centre(q(s.click)); if (!p) throw new Error(`no element ${s.click}`); await clickAt(p); }
  if (s.clickText) {
    const p = await centre(`[...document.querySelectorAll('button, a')].find((b) => b.textContent.trim().startsWith(${JSON.stringify(s.clickText)}))`);
    if (!p) throw new Error(`no button "${s.clickText}"`);
    await clickAt(p);
  }
  if (s.select) {
    await evaluate(`(() => { const el = ${q(s.select[0])}; const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
      set.call(el, ${JSON.stringify(s.select[1])}); el.dispatchEvent(new Event('change', {bubbles: true})); })()`);
    await sleep(300);
  }
  if (s.check) {
    const p = await centre(q(s.check)); if (p) await clickAt(p);
  }
  if (s.checkIndex !== undefined) {         // the n-th checkbox on the page (labels share selectors)
    const p = await centre(`document.querySelectorAll('input[type=checkbox]')[${s.checkIndex}]`); if (p) await clickAt(p);
  }
  if (s.selectIndex) {                      // [n, value]: the n-th <select> on the page
    await evaluate(`(() => { const el = document.querySelectorAll('select')[${s.selectIndex[0]}];
      const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
      set.call(el, ${JSON.stringify(s.selectIndex[1])}); el.dispatchEvent(new Event('change', {bubbles: true})); })()`);
    await sleep(300);
  }
  if (s.setValue) {                         // [selector, value]: replace an input's value (e.g. a number field)
    const p = await centre(q(s.setValue[0])); if (p) await clickAt(p);
    await evaluate(`(() => { const el = ${q(s.setValue[0])}; const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      set.call(el, ${JSON.stringify(String(s.setValue[1]))}); el.dispatchEvent(new Event('input', {bubbles: true})); })()`);
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
      await evaluate(`(() => { const all = [...document.querySelectorAll('*')].filter((el) => el.scrollHeight > el.clientHeight + 4 &&
        /(auto|scroll)/.test(getComputedStyle(el).overflowY)); const page = document.scrollingElement;
        if (page.scrollHeight > page.clientHeight + 4) all.push(page);
        const el = all.sort((a, b) => b.clientHeight - a.clientHeight)[0] || page;
        el.scrollBy(0, ${s.scroll / n}); })()`);
      await sleep(22);
    }
  }
}
await sleep(400);
const endT = Date.now() / 1000;                // keep the time after the last on-screen change (the screencast only sends changes)
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
const r = spawnSync('ffmpeg', ['-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', join(tmp, 'list.txt'), '-vf',
  'fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2:flags=lanczos,format=yuv420p', '-c:v', 'libx264', '-preset', 'slow', '-crf', '16',
  '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-movflags', '+faststart', plan.out], {stdio: 'inherit'});
rmSync(tmp, {recursive: true, force: true});
if (r.status !== 0) throw new Error('ffmpeg failed');
console.log(JSON.stringify({out: plan.out, frames: frames.length, seconds: +(frames.at(-1).t - frames[0].t).toFixed(2)}));
