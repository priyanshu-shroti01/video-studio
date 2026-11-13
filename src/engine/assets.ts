import {RenderProps} from './types';

/**
 * Intrinsic aspect ratio (width / height) of an image file from its bytes: SVG viewBox (or width/height),
 * PNG IHDR, JPEG SOFn, GIF, WebP (VP8/VP8L/VP8X). Pure; shared by the renderer (calculateMetadata,
 * fetch) and scripts/engine-layout.mjs (fs), so both see the same numbers. undefined = unknown.
 */
export const intrinsicAspect = (bytes: Uint8Array, path = ''): number | undefined => {
  const u16be = (o: number) => (bytes[o] << 8) | bytes[o + 1];
  const u16le = (o: number) => bytes[o] | (bytes[o + 1] << 8);
  const u24le = (o: number) => bytes[o] | (bytes[o + 1] << 8) | (bytes[o + 2] << 16);
  const u32be = (o: number) => ((bytes[o] << 24) >>> 0) + (bytes[o + 1] << 16) + (bytes[o + 2] << 8) + bytes[o + 3];
  const ok = (w: number, h: number) => (w > 0 && h > 0 && Number.isFinite(w / h) ? w / h : undefined);
  // PNG
  if (bytes.length > 24 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) return ok(u32be(16), u32be(20));
  // GIF
  if (bytes.length > 10 && bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46) return ok(u16le(6), u16le(8));
  // JPEG
  if (bytes.length > 4 && bytes[0] === 0xff && bytes[1] === 0xd8) {
    let o = 2;
    while (o + 9 < bytes.length) {
      if (bytes[o] !== 0xff) {
        o++;
        continue;
      }
      const m = bytes[o + 1];
      if (m >= 0xc0 && m <= 0xcf && m !== 0xc4 && m !== 0xc8 && m !== 0xcc) return ok(u16be(o + 7), u16be(o + 5));
      if (m === 0xd8 || m === 0x01 || (m >= 0xd0 && m <= 0xd7)) {
        o += 2;
        continue;
      }
      o += 2 + u16be(o + 2);
    }
    return undefined;
  }
  // WebP
  if (bytes.length > 30 && String.fromCharCode(...bytes.slice(0, 4)) === 'RIFF' && String.fromCharCode(...bytes.slice(8, 12)) === 'WEBP') {
    const chunk = String.fromCharCode(...bytes.slice(12, 16));
    if (chunk === 'VP8X') return ok(1 + u24le(24), 1 + u24le(27));
    if (chunk === 'VP8 ') return ok(u16le(26) & 0x3fff, u16le(28) & 0x3fff);
    if (chunk === 'VP8L') {
      const b = (i: number) => bytes[21 + i];
      return ok(1 + (((b(1) & 0x3f) << 8) | b(0)), 1 + (((b(3) & 0x0f) << 10) | (b(2) << 2) | ((b(1) & 0xc0) >> 6)));
    }
    return undefined;
  }
  // MP4 / MOV / WebM (footage): the video track's display size
  const v = videoInfo(bytes);
  if (v) return v.aspect;
  // SVG (text)
  const head = new TextDecoder().decode(bytes.slice(0, Math.min(bytes.length, 4096)));
  if (/<svg[\s>]/i.test(head) || path.toLowerCase().endsWith('.svg')) return svgAspect(head);
  return undefined;
};

/** Aspect of an SVG from the root element's viewBox (preferred) or numeric width/height. */
export const svgAspect = (svgText: string): number | undefined => {
  const m = /<svg\b[^>]*>/i.exec(svgText);
  if (!m) return undefined;
  const tag = m[0];
  const vb = /\bviewBox\s*=\s*["']\s*([-\d.eE+]+)[\s,]+([-\d.eE+]+)[\s,]+([-\d.eE+]+)[\s,]+([-\d.eE+]+)\s*["']/.exec(tag);
  if (vb) {
    const w = parseFloat(vb[3]);
    const h = parseFloat(vb[4]);
    if (w > 0 && h > 0) return w / h;
  }
  const w = /\bwidth\s*=\s*["']\s*([\d.]+)(px)?\s*["']/.exec(tag);
  const h = /\bheight\s*=\s*["']\s*([\d.]+)(px)?\s*["']/.exec(tag);
  if (w && h && parseFloat(h[1]) > 0) return parseFloat(w[1]) / parseFloat(h[1]);
  return undefined;
};

/** Every public/ asset whose aspect the v2 layout needs: the three logos, image/device assets, custom watermark, and
 *  footage clips whose block has no `aspect` (the pipeline always fills it, so production props never read videos). */
export const collectAssetPaths = (props: Pick<RenderProps, 'theme' | 'scenes' | 'watermark'>): string[] => {
  const out = new Set<string>([props.theme.logo.onDark, props.theme.logo.onLight, props.theme.logo.mark]);
  for (const s of props.scenes)
    for (const b of s.blocks) {
      if ((b.type === 'image' || b.type === 'device') && b.asset) out.add(b.asset);
      if (b.type === 'footage' && b.asset && !(typeof b.aspect === 'number' && b.aspect > 0)) out.add(b.asset);
      if (b.type === 'composition') for (const e of b.elements ?? []) if (e.kind === 'media' && e.asset) out.add(e.asset);
    }
  if (props.watermark?.policy === 'custom' && props.watermark.asset) out.add(props.watermark.asset);
  return [...out].sort();
};

/** Footage clips whose block has no `duration` (the renderer reads it from the file header to hold the last frame). */
export const collectFootageNeedingDuration = (props: Pick<RenderProps, 'scenes'>): string[] => {
  const out = new Set<string>();
  for (const s of props.scenes)
    for (const b of s.blocks) if (b.type === 'footage' && b.asset && !(typeof b.duration === 'number' && b.duration > 0)) out.add(b.asset);
  return [...out].sort();
};

export type VideoInfo = {width: number; height: number; aspect: number; duration?: number};

/**
 * Display size (and duration, when stored) of the video track of an MP4 / MOV (ISO-BMFF: moov › trak › tkhd + mdhd,
 * rotation from the tkhd matrix) or WebM / Matroska (EBML: Info › Duration × TimecodeScale, Tracks › Video ›
 * Display/PixelWidth/Height). Needs the header boxes (MP4 `moov` anywhere in the given bytes). Pure; undefined = not a
 * video or unreadable.
 */
export const videoInfo = (bytes: Uint8Array): VideoInfo | undefined => {
  if (bytes.length > 12 && String.fromCharCode(...bytes.slice(4, 8)) === 'ftyp') return mp4Info(bytes);
  if (bytes.length > 4 && bytes[0] === 0x1a && bytes[1] === 0x45 && bytes[2] === 0xdf && bytes[3] === 0xa3) return webmInfo(bytes);
  return undefined;
};

const mp4Info = (bytes: Uint8Array): VideoInfo | undefined => {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const type = (o: number) => String.fromCharCode(bytes[o], bytes[o + 1], bytes[o + 2], bytes[o + 3]);
  const u64 = (o: number) => dv.getUint32(o) * 2 ** 32 + dv.getUint32(o + 4);
  /** child boxes [type, bodyStart, end] of the range [a, b) */
  const boxes = (a: number, b: number): [string, number, number][] => {
    const out: [string, number, number][] = [];
    let o = a;
    while (o + 8 <= b) {
      let size = dv.getUint32(o);
      let head = 8;
      if (size === 1) {
        if (o + 16 > b) break;
        size = u64(o + 8);
        head = 16;
      } else if (size === 0) size = b - o;
      if (size < head) break;
      out.push([type(o + 4), o + head, Math.min(b, o + size)]);
      o += size;
    }
    return out;
  };
  const moov = boxes(0, bytes.length).find((x) => x[0] === 'moov');
  if (!moov) return undefined;
  for (const [t, a, b] of boxes(moov[1], moov[2])) {
    if (t !== 'trak') continue;
    const kids = boxes(a, b);
    const mdia = kids.find((x) => x[0] === 'mdia');
    const tkhd = kids.find((x) => x[0] === 'tkhd');
    if (!mdia || !tkhd) continue;
    const mk = boxes(mdia[1], mdia[2]);
    const hdlr = mk.find((x) => x[0] === 'hdlr');
    if (!hdlr || hdlr[1] + 12 > hdlr[2] || type(hdlr[1] + 8) !== 'vide') continue;
    const v1 = bytes[tkhd[1]] === 1;
    const m = tkhd[1] + (v1 ? 52 : 40);
    if (m + 44 > tkhd[2]) continue;
    const ma = dv.getInt32(m) / 65536;
    const mb = dv.getInt32(m + 4) / 65536;
    let w = dv.getUint32(m + 36) / 65536;
    let h = dv.getUint32(m + 40) / 65536;
    if (Math.abs(ma) < 1e-6 && Math.abs(Math.abs(mb) - 1) < 1e-6) [w, h] = [h, w]; // rotated ±90°
    if (!(w > 0 && h > 0)) continue;
    let duration: number | undefined;
    const mdhd = mk.find((x) => x[0] === 'mdhd');
    if (mdhd) {
      const o = mdhd[1];
      const [ts, d] = bytes[o] === 1 ? [dv.getUint32(o + 20), u64(o + 24)] : [dv.getUint32(o + 12), dv.getUint32(o + 16)];
      if (ts > 0 && d > 0 && d < 2 ** 52) duration = d / ts;
    }
    return {width: w, height: h, aspect: w / h, duration};
  }
  return undefined;
};

const webmInfo = (bytes: Uint8Array): VideoInfo | undefined => {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  /** EBML variable-length integer at o: [value, length]; `id` keeps the marker bit, sizes drop it (all-ones = unknown). */
  const vint = (o: number, id: boolean): [number, number] | undefined => {
    const first = bytes[o];
    if (first === undefined || first === 0) return undefined;
    let len = 1;
    while (!(first & (0x80 >> (len - 1)))) len++;
    if (len > 8 || o + len > bytes.length) return undefined;
    let v = id ? first : first & (0xff >> len);
    let ones = v === (0xff >> len);
    for (let i = 1; i < len; i++) {
      v = v * 256 + bytes[o + i];
      ones = ones && bytes[o + i] === 0xff;
    }
    return [!id && ones ? -1 : v, len];
  };
  const uint = (o: number, n: number) => {
    let v = 0;
    for (let i = 0; i < n; i++) v = v * 256 + bytes[o + i];
    return v;
  };
  const CONTAINERS = new Set([0x18538067, 0x1549a966, 0x1654ae6b, 0xae, 0xe0]);
  let scale = 1e6;
  let dur: number | undefined;
  let pw = 0, ph = 0, dw = 0, dh = 0;
  let trackType = 0;
  let videoSeen = false;
  const walk = (a: number, b: number, depth: number) => {
    let o = a;
    while (o < b && depth < 8) {
      const id = vint(o, true);
      if (!id) return;
      const sz = vint(o + id[1], false);
      if (!sz) return;
      const body = o + id[1] + sz[1];
      const end = sz[0] < 0 ? b : Math.min(b, body + sz[0]);
      const n = end - body;
      switch (id[0]) {
        case 0x2ad7b1:
          scale = uint(body, n);
          break;
        case 0x4489:
          dur = n === 4 ? dv.getFloat32(body) : n === 8 ? dv.getFloat64(body) : undefined;
          break;
        case 0x83:
          trackType = uint(body, n);
          break;
        case 0xb0:
          pw = uint(body, n);
          break;
        case 0xba:
          ph = uint(body, n);
          break;
        case 0x54b0:
          dw = uint(body, n);
          break;
        case 0x54ba:
          dh = uint(body, n);
          break;
        case 0x1f43b675: // Cluster: frame data, nothing more to read
          return;
        default:
          if (CONTAINERS.has(id[0])) {
            if (id[0] === 0xae) trackType = 0;
            walk(body, end, depth + 1);
            if (id[0] === 0xe0 && trackType !== 2) videoSeen = true;
          }
      }
      if (videoSeen && dur !== undefined) break;
      o = end;
    }
  };
  walk(0, bytes.length, 0);
  const w = dw || pw;
  const h = dh || ph;
  if (!(w > 0 && h > 0)) return undefined;
  const duration = dur !== undefined && dur > 0 ? (dur * scale) / 1e9 : undefined;
  return {width: w, height: h, aspect: w / h, duration};
};
