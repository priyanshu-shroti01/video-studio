#!/usr/bin/env node
/**
 * Security patch: make Remotion's local servers (render-time file server and `remotion studio`)
 * bind to the loopback interface instead of all interfaces (0.0.0.0 / ::).
 *
 * Why: upstream @remotion/renderer (checked 4.0.507 and 4.0.540) has no host option and always
 * binds every interface, exposing the bundle and public/ assets to the LAN while it runs.
 * Chromium reaches the server via http://localhost:<port>, which resolves to loopback, so
 * binding ::1 (or 127.0.0.1) keeps rendering working.
 *
 * Runs on `npm install` / `npm ci` (postinstall). Idempotent. Opt out for one process with
 * REMOTION_BIND_ALL=1 (e.g. to open Studio from another device on purpose).
 * Fails loudly if the upstream code no longer matches, instead of silently not protecting you.
 */
import {readFileSync, writeFileSync, existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const target = join(root, 'node_modules/@remotion/renderer/dist/port-config.js');
const MARK = '/* video-studio: loopback-only patch */';
const OLD_MARKS = ['/* shrotihost-videos: loopback-only patch */'];   // installs patched before the rename
const ORIGINAL = `const getHostToBind = (flattened, preferIpv4) => {
    if (preferIpv4 || !(0, exports.isIpV6Supported)(flattened)) {
        return '0.0.0.0';
    }
    return '::';
};`;
const PATCHED = `const getHostToBind = (flattened, preferIpv4) => {
    ${MARK}
    if (process.env.REMOTION_BIND_ALL !== '1') {
        if (!preferIpv4 && (0, exports.hasIPv6LoopbackAddress)(flattened)) {
            return '::1';
        }
        return '127.0.0.1';
    }
    if (preferIpv4 || !(0, exports.isIpV6Supported)(flattened)) {
        return '0.0.0.0';
    }
    return '::';
};`;

if (!existsSync(target)) {
  console.log('[patch-remotion-loopback] @remotion/renderer not installed; nothing to patch');
  process.exit(0);
}
const src = readFileSync(target, 'utf8');
if (src.includes(MARK) || OLD_MARKS.some((m) => src.includes(m))) {
  console.log('[patch-remotion-loopback] already applied');
  process.exit(0);
}
if (!src.includes(ORIGINAL)) {
  console.error('[patch-remotion-loopback] ERROR: upstream port-config.js changed; patch not applied. ' +
    'Review node_modules/@remotion/renderer/dist/port-config.js and update scripts/patch-remotion-loopback.mjs.');
  process.exit(1);
}
writeFileSync(target, src.replace(ORIGINAL, PATCHED));
console.log('[patch-remotion-loopback] applied: Remotion servers bind loopback only');
