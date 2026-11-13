#!/usr/bin/env node
/**
 * Deterministic layout manifest for QA:  node scripts/engine-layout.mjs <props.json> > layout.json
 *
 * Bundles src/engine/manifest.ts (the SAME pure layout/planning code the Storyboard renderer uses) with
 * esbuild in memory, resolves asset aspects from public/ (SVG viewBox, PNG/JPEG headers — exactly like
 * the renderer's calculateMetadata), and prints the manifest as JSON. No browser, no network.
 * Exit codes: 0 ok, 2 usage / bad props, 1 internal error.
 */
import {build} from 'esbuild';
import {readFileSync, existsSync} from 'node:fs';
import {dirname, join, resolve, sep} from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PUBLIC = join(ROOT, 'public');

const fail = (msg, code = 2) => {
  process.stderr.write(`engine-layout: ${msg}\n`);
  process.exit(code);
};

const arg = process.argv[2];
if (!arg || arg === '-h' || arg === '--help') fail('usage: node scripts/engine-layout.mjs <props.json> > layout.json');

let props;
try {
  props = JSON.parse(readFileSync(resolve(arg), 'utf8'));
} catch (e) {
  fail(`cannot read props ${arg}: ${e instanceof Error ? e.message : String(e)}`);
}

const out = await build({
  entryPoints: [join(ROOT, 'src/engine/manifest.ts')],
  bundle: true,
  write: false,
  format: 'esm',
  platform: 'node',
  target: 'node20',
  logLevel: 'silent',
  // the manifest graph must stay free of React/Remotion; fail loudly if that ever regresses
  external: ['remotion', 'react', 'react-dom'],
});
const code = out.outputFiles[0].text;
if (/from\s+["'](remotion|react)["']/.test(code)) fail('manifest bundle imports remotion/react — keep src/engine/manifest.ts pure', 1);
const M = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);

/** public/ reader confined to public/ (paths in props are relative to public/). */
const readPublic = (p) => {
  const f = resolve(PUBLIC, p);
  if (!f.startsWith(PUBLIC + sep) || !existsSync(f)) return undefined;
  return new Uint8Array(readFileSync(f));
};

try {
  const full = M.withAssetAspects(props, readPublic, M.collectAssetPaths, M.intrinsicAspect);
  process.stdout.write(JSON.stringify(M.buildManifest(full), null, 1) + '\n');
} catch (e) {
  fail(e instanceof Error ? e.message : String(e), 1);
}
