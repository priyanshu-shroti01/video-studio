/**
 * Pure geometry of the v2b blocks (plan-card, install-flow, server-stack), in design units relative to the
 * block box. The renderer (blocks-v2b.tsx) draws from these numbers and the QA manifest reports them, exactly
 * like geometry.ts. Each block picks a wide (landscape, two-column) or tall (Shorts / narrow column) layout from
 * the design width it is given, so it reads as a hero in both formats.
 */
import {formatNumber, Rect, T, TextSpec} from './geometry';
import {estimateTextWidth, fitFontSize, WEIGHT} from './motion/typography';
import {BlockV2} from './types';

type B<K extends BlockV2['type']> = Extract<BlockV2, {type: K}>;

/** Natural (maximum) design widths: wide layouts; a narrower column switches the block to its tall layout. */
export const V2B_NATURAL_W = {'plan-card': 1400, 'install-flow': 1560, 'server-stack': 1440} as const;
export const V2B_WIDE_MIN = {'plan-card': 1100, 'install-flow': 1250, 'server-stack': 1200} as const;

// ------------------------------------------------------------------------------------------------ plan-card
export const planPriceText = (b: B<'plan-card'>, v: number) => {
  const decimals = Number.isInteger(b.price) && Number.isInteger(b.countFrom ?? 0) ? 0 : 2;
  return formatNumber(v, decimals, 'indian');
};
/** Baseline offset from a line box's centre, and cap height, as fractions of the font size. */
export const BASELINE = 0.36;
export const CAP = 0.72;
export const CTA_ARROW = 64;
export const PLAN = {pad: 58, nameFs: 54, nameH: 64, badgeFs: 26, badgeH: 50, priceFs: 196, periodFs: 52, billingFs: 31, rowH: 72, check: 46, icon: 40, featFs: 38, ctaH: 108, ctaFs: 40} as const;

export const geomPlanCard = (b: B<'plan-card'>, w: number) => {
  const P = PLAN;
  const wide = w >= V2B_WIDE_MIN['plan-card'];
  const pad = P.pad;
  const texts: TextSpec[] = [];
  const leftW = wide ? Math.round(w * 0.43) : w;
  const innerL = leftW - 2 * pad;
  const cur = b.currency ?? '₹';
  const period = b.period ?? '/mo';
  // ---- header: name with the badge pill on its right, or above it (eyebrow) when they don't fit side by side
  let y = pad;
  const badgeText = b.badge ? b.badge.toUpperCase() : '';
  const badgeLs = 1.5;
  const badgeTextW = b.badge ? estimateTextWidth(badgeText, P.badgeFs, {weight: WEIGHT.heavy, letterSpacing: badgeLs}) : 0;
  const badgeW = b.badge ? Math.min(innerL, badgeTextW + 44) : 0;
  const nameNeed = estimateTextWidth(b.name, P.nameFs, {weight: WEIGHT.heavy, letterSpacing: -1});
  const eyebrow = !!b.badge && nameNeed + 20 + badgeW > innerL;
  let badge: Rect | undefined;
  if (b.badge && eyebrow) {
    badge = {x: pad, y, w: badgeW, h: P.badgeH};
    y += P.badgeH + 16;
  }
  const nameW = innerL - (b.badge && !eyebrow ? badgeW + 20 : 0);
  const nameFs = fitFontSize(b.name, P.nameFs, nameW, {weight: WEIGHT.heavy, minFs: 34, letterSpacing: -1});
  texts.push(T(b.name, pad, y, nameW, P.nameH, nameFs, WEIGHT.heavy, 'left', 'title', {ls: -1}));
  if (b.badge && !eyebrow) badge = {x: pad + innerL - badgeW, y: y + (P.nameH - P.badgeH) / 2, w: badgeW, h: P.badgeH};
  if (badge) texts.push(T(badgeText, badge.x + 22, badge.y, badge.w - 44, badge.h, fitFontSize(badgeText, P.badgeFs, badge.w - 44, {weight: WEIGHT.heavy, minFs: 18, letterSpacing: badgeLs}), WEIGHT.heavy, 'center', 'label', {ls: badgeLs}));
  y += P.nameH + 22;
  // ---- price: small raised currency + big amount + period (amount fitted to the widest count value)
  const widest = [planPriceText(b, b.price), planPriceText(b, b.countFrom ?? 0)].sort((p, q) => q.length - p.length)[0];
  const ratio = 0.46;
  const measure = (fs: number) => ({
    cur: estimateTextWidth(cur, fs * ratio, {weight: WEIGHT.bold}),
    amt: estimateTextWidth(widest, fs, {weight: WEIGHT.heavy, letterSpacing: -0.04 * fs}),
    per: estimateTextWidth(period, P.periodFs * (fs / P.priceFs), {weight: WEIGHT.bold}),
  });
  let priceFs: number = P.priceFs;
  const total = (m: ReturnType<typeof measure>, fs: number) => m.cur + fs * 0.03 + m.amt + fs * 0.06 + m.per;
  const m0 = measure(priceFs);
  if (total(m0, priceFs) > innerL) priceFs = Math.max(90, Math.floor((priceFs * innerL) / total(m0, priceFs)));
  const m = measure(priceFs);
  const periodFs = Math.round(P.periodFs * (priceFs / P.priceFs));
  const priceH = Math.round(priceFs * 1.02);
  const curFs = Math.round(priceFs * ratio);
  const amtX = pad + m.cur + priceFs * 0.03;
  const amt = estimateTextWidth(planPriceText(b, b.price), priceFs, {weight: WEIGHT.heavy, letterSpacing: -0.04 * priceFs});
  // baseline of a single-line run ≈ line-box centre + BASELINE·fs (Plus Jakarta Sans metrics)
  const baseline = y + priceH / 2 + BASELINE * priceFs;
  const perH = Math.round(periodFs * 1.3);
  const curH = Math.round(curFs * 1.3);
  const capTop = baseline - CAP * priceFs;
  const price = {y, h: priceH, fs: priceFs, curFs, amtX, curX: pad, perX: amtX + amt + priceFs * 0.06, periodFs, baseline, perY: baseline - perH / 2 - BASELINE * periodFs, perH, curY: capTop - curH / 2 + (CAP - BASELINE) * curFs, curH};
  texts.push(T(`${cur}${planPriceText(b, b.price)}`, pad, y, innerL, priceH, priceFs, WEIGHT.heavy, 'left', 'price', {est: m.cur + priceFs * 0.03 + amt}));
  texts.push(T(period, price.perX, price.perY, Math.max(10, pad + innerL - price.perX), perH, periodFs, WEIGHT.bold, 'left', 'label'));
  y += priceH + 6;
  if (b.billing) {
    texts.push(T(b.billing, pad, y, innerL, 44, fitFontSize(b.billing, P.billingFs, innerL, {weight: WEIGHT.semibold, minFs: 22}), WEIGHT.semibold, 'left', 'body'));
    y += 44;
  }
  // ---- CTA (left column bottom in wide, card bottom in tall)
  const ctaW = innerL;
  let cta: Rect | undefined;
  // ---- features
  const n = b.features.length;
  const hasIcon = b.features.some((f) => f.icon);
  const fx0 = wide ? leftW + pad : pad;
  const fInner = wide ? w - leftW - 2 * pad : innerL;
  const textX = fx0 + P.check + 22 + (hasIcon ? P.icon + 18 : 0);
  const featW = fx0 + fInner - textX;
  const featFs = Math.min(P.featFs, ...b.features.map((f) => fitFontSize(f.text, P.featFs, featW, {weight: WEIGHT.bold, minFs: 24})));
  let rowsY: number;
  let divider: {x: number; y: number; w: number; h: number};
  let h: number;
  if (wide) {
    y += 40;
    cta = b.ctaLabel ? {x: pad, y, w: ctaW, h: P.ctaH} : undefined;
    const leftH = y + (cta ? P.ctaH : 0) + pad;
    const rightH = 2 * pad + n * P.rowH;
    h = Math.max(leftH, rightH);
    rowsY = (h - n * P.rowH) / 2;
    if (cta && leftH < h) cta = {...cta, y: cta.y + (h - leftH)};
    divider = {x: leftW, y: pad, w: 2, h: h - 2 * pad};
  } else {
    y += 30;
    divider = {x: pad, y, w: innerL, h: 2};
    y += 30;
    rowsY = y;
    y += n * P.rowH + (b.ctaLabel ? 30 : 0);
    cta = b.ctaLabel ? {x: pad, y, w: ctaW, h: P.ctaH} : undefined;
    y += cta ? P.ctaH : 0;
    h = y + pad;
  }
  const rows = b.features.map((f, i) => {
    const ry = rowsY + i * P.rowH;
    texts.push(T(f.text, textX, ry, featW, P.rowH, featFs, WEIGHT.bold, 'left', 'body'));
    return {y: ry, check: {x: fx0, y: ry + (P.rowH - P.check) / 2, s: P.check}, icon: f.icon ? {x: fx0 + P.check + 22, y: ry + (P.rowH - P.icon) / 2, s: P.icon} : undefined};
  });
  // label centred in the button minus the arrow zone on the right (CTA_ARROW)
  if (cta && b.ctaLabel) texts.push(T(b.ctaLabel, cta.x + 30, cta.y, cta.w - 60 - CTA_ARROW, cta.h, fitFontSize(b.ctaLabel, P.ctaFs, cta.w - 60 - CTA_ARROW, {weight: WEIGHT.heavy, minFs: 24}), WEIGHT.heavy, 'center', 'label'));
  return {wide, pad, leftW, innerL, h: Math.round(h), badge, price, rows, featFs, cta, divider, texts};
};

// ------------------------------------------------------------------------------------------------ install-flow
export const INSTALL = {chromeH: 72, pad: 48, tile: 108, nameFs: 50, pctFs: 40, barH: 14, rowH: 84, status: 48, labelFs: 38, doneH: 104, doneFs: 40, urlFs: 28, prevChrome: 60} as const;

export const geomInstallFlow = (b: B<'install-flow'>, w: number) => {
  const I = INSTALL;
  const wide = w >= V2B_WIDE_MIN['install-flow'];
  const hasPrev = !!b.siteUrl;
  const winW = wide && hasPrev ? Math.round(w * 0.58) : w;
  const pad = I.pad;
  const inner = winW - 2 * pad;
  const texts: TextSpec[] = [];
  if (b.title) texts.push(T(b.title, 150, 0, winW - 300, I.chromeH, fitFontSize(b.title, 26, winW - 300, {weight: WEIGHT.bold, minFs: 18}), WEIGHT.bold, 'center', 'label'));
  let y = I.chromeH + pad - 8;
  const tile = {x: pad, y, s: I.tile};
  const pctW = estimateTextWidth('100%', I.pctFs, {weight: WEIGHT.heavy});
  const nameX = pad + I.tile + 28;
  const nameW = winW - pad - pctW - 24 - nameX;
  texts.push(T(b.app, nameX, y, nameW, I.tile, fitFontSize(b.app, I.nameFs, nameW, {weight: WEIGHT.heavy, minFs: 28, letterSpacing: -1}), WEIGHT.heavy, 'left', 'title', {ls: -1}));
  texts.push(T('100%', winW - pad - pctW, y, pctW, I.tile, I.pctFs, WEIGHT.heavy, 'right', 'label'));
  y += I.tile + 30;
  const bar = {x: pad, y, w: inner, h: I.barH};
  y += I.barH + 26;
  const labelX = pad + I.status + 24;
  const labelW = winW - pad - labelX;
  const labelFs = Math.min(I.labelFs, ...b.steps.map((s) => fitFontSize(s.label, I.labelFs, labelW, {weight: WEIGHT.bold, minFs: 24})));
  const rows = b.steps.map((s, i) => {
    const ry = y + i * I.rowH;
    texts.push(T(s.label, labelX, ry, labelW, I.rowH, labelFs, WEIGHT.bold, 'left', 'label'));
    return {y: ry, icon: {x: pad, y: ry + (I.rowH - I.status) / 2, s: I.status}};
  });
  y += b.steps.length * I.rowH + 18;
  const done = {x: pad, y, w: inner, h: I.doneH};
  const doneX = pad + 28 + 56 + 22;
  texts.push(T(b.doneText, doneX, y, pad + inner - 24 - doneX, I.doneH, fitFontSize(b.doneText, I.doneFs, pad + inner - 24 - doneX, {weight: WEIGHT.heavy, minFs: 24}), WEIGHT.heavy, 'left', 'title'));
  y += I.doneH + pad;
  const win = {x: 0, y: 0, w: winW, h: y};
  let preview: Rect | undefined;
  let h = win.h;
  if (hasPrev) {
    if (wide) {
      const pw = w - winW - 56;
      const ph = Math.round(pw * 0.72);
      preview = {x: winW + 56, y: Math.max(0, Math.round((win.h - ph) / 2 + 40)), w: pw, h: ph};
      h = Math.max(win.h, preview.y + ph);
    } else {
      const pw = Math.round(w * 0.66);
      const ph = Math.round(pw * 0.66);
      preview = {x: w - pw - 36, y: win.h - 36, w: pw, h: ph};
      h = preview.y + ph;
    }
    const urlX = preview.x + 120;
    const urlW = preview.w - 120 - 28;
    texts.push(T(b.siteUrl!, urlX, preview.y + 10, urlW, I.prevChrome - 20, fitFontSize(b.siteUrl!, I.urlFs, urlW - 40, {mono: true, minFs: 20}), WEIGHT.regular, 'left', 'url', {mono: true}));
  }
  return {wide, winW, pad, inner, tile, nameX, bar, rows, labelFs, done, win, preview, h: Math.round(h), texts};
};

// ------------------------------------------------------------------------------------------------ server-stack
export const STACK = {unitH: 124, unitGap: 16, rackPad: 22, tile: 76, labelFs: 42, titleFs: 40, titleH: 60, globe: 168, statusH: 66, statusFs: 30} as const;

export const geomServerStack = (b: B<'server-stack'>, w: number) => {
  const S = STACK;
  const wide = w >= V2B_WIDE_MIN['server-stack'];
  const nodes = b.nodes.slice(0, 4);
  const n = Math.max(1, nodes.length);
  const texts: TextSpec[] = [];
  let y = 0;
  if (b.title) {
    texts.push(T(b.title, 0, 0, wide ? Math.round(w * 0.58) : w, S.titleH, fitFontSize(b.title, S.titleFs, wide ? w * 0.58 : w, {weight: WEIGHT.bold, minFs: 26}), WEIGHT.bold, wide ? 'left' : 'center', 'title'));
    y += S.titleH + 22;
  }
  const rackW = wide ? Math.round(w * 0.58) : w;
  const rackH = 2 * S.rackPad + n * S.unitH + (n - 1) * S.unitGap;
  const rack = {x: 0, y, w: rackW, h: rackH};
  const labelX = S.rackPad + 54 + S.tile + 26;
  const baysW = 210;
  const labelW = rackW - S.rackPad - baysW - 30 - labelX;
  const labelFs = Math.min(S.labelFs, ...nodes.map((x) => fitFontSize(x.label, S.labelFs, labelW, {weight: WEIGHT.heavy, minFs: 26})));
  const units = nodes.map((nd, i) => {
    const uy = y + S.rackPad + i * (S.unitH + S.unitGap);
    texts.push(T(nd.label, labelX, uy, labelW, S.unitH, labelFs, WEIGHT.heavy, 'left', 'label'));
    return {x: S.rackPad, y: uy, w: rackW - 2 * S.rackPad, h: S.unitH, tile: {x: S.rackPad + 54, y: uy + (S.unitH - S.tile) / 2, s: S.tile}, bays: {x: rackW - S.rackPad - baysW - 18, y: uy + 26, w: baysW, h: S.unitH - 52}};
  });
  const G = S.globe;
  let globe: {cx: number; cy: number; r: number};
  let links: {x0: number; y0: number; cx: number; cy: number; x1: number; y1: number}[];
  let status: Rect | undefined;
  let h: number;
  const statusText = b.status?.text ?? '';
  const statusW = b.status ? Math.min(wide ? w - rackW - 40 : w, estimateTextWidth(statusText, S.statusFs, {weight: WEIGHT.bold}) + 100) : 0;
  if (wide) {
    const colX = rackW + (w - rackW) / 2;
    globe = {cx: colX + 30, cy: rack.y + rack.h / 2, r: G / 2};
    links = units.map((u) => {
      const x0 = rackW;
      const y0 = u.y + u.h / 2;
      const x1 = globe.cx - globe.r - 6;
      const y1 = globe.cy + (y0 - (rack.y + rack.h / 2)) * 0.18;
      return {x0, y0, cx: (x0 + x1) / 2 + 40, cy: y0, x1, y1};
    });
    // below the globe and below every link's start, so no data line runs under the pill
    const lowest = Math.max(...links.map((l) => l.y0));
    status = b.status ? {x: globe.cx - statusW / 2, y: Math.max(globe.cy + globe.r + 34, lowest + 40), w: statusW, h: S.statusH} : undefined;
    if (status && status.x + status.w > w) status = {...status, x: w - status.w};
    h = Math.max(rack.y + rack.h, status ? status.y + status.h : 0);
  } else {
    const linkH = 150;
    globe = {cx: w / 2, cy: rack.y + rack.h + linkH + G / 2, r: G / 2};
    links = units.map((_, i) => {
      const x0 = rackW * ((i + 1) / (n + 1));
      const y0 = rack.y + rack.h;
      const x1 = globe.cx + (x0 - w / 2) * 0.16;
      const y1 = globe.cy - globe.r - 6;
      return {x0, y0, cx: x0, cy: (y0 + y1) / 2 + 30, x1, y1};
    });
    status = b.status ? {x: (w - statusW) / 2, y: globe.cy + globe.r + 30, w: statusW, h: S.statusH} : undefined;
    h = status ? status.y + status.h : globe.cy + globe.r;
  }
  // every link ends exactly on the website node's rim
  links = links.map((l) => {
    const dx = l.x1 - globe.cx;
    const dy = l.y1 - globe.cy;
    const d = Math.max(1e-6, Math.hypot(dx, dy));
    return {...l, x1: globe.cx + (dx / d) * (globe.r + 4), y1: globe.cy + (dy / d) * (globe.r + 4)};
  });
  if (status && b.status) texts.push(T(statusText, status.x + 64, status.y, status.w - 88, status.h, fitFontSize(statusText, S.statusFs, status.w - 88, {weight: WEIGHT.bold, minFs: 20}), WEIGHT.bold, 'left', 'label'));
  return {wide, rack, units, labelFs, globe, links, status, h: Math.round(h + 4), texts};
};

/** Point + tangent-free position on a quadratic Bézier (pulses travel along the links). */
export const quadAt = (l: {x0: number; y0: number; cx: number; cy: number; x1: number; y1: number}, p: number) => {
  const q = 1 - p;
  return {x: q * q * l.x0 + 2 * q * p * l.cx + p * p * l.x1, y: q * q * l.y0 + 2 * q * p * l.cy + p * p * l.y1};
};
