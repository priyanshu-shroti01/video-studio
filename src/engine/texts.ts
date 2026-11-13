/**
 * Text runs + logo rects of every block, in design units relative to the block box (for the QA manifest).
 * v2 blocks come straight from geometry.ts (the renderer draws from the same numbers); v1 blocks are
 * derived from the constants of their (unchanged) renderers in blocks.tsx. Pure.
 */
import {
  AspectEnv,
  containRect,
  geomChart,
  geomCounter,
  geomDashboard,
  geomDevice,
  geomFeatureCompare,
  geomImage,
  geomKinetic,
  geomLogoSting,
  geomOutro,
  geomPriceCompare,
  geomProgress,
  geomScrollDemo,
  geomTerminal,
  LogoSpec,
  T,
  TextSpec,
  pillMetrics,
} from './geometry';
import {geomComposition} from './geometry-composition';
import {geomFootage} from './geometry-footage';
import {geomInstallFlow, geomPlanCard, geomServerStack} from './geometry-v2b';
import {CTA_FS, HEADLINE_FS, splitText, TEXT_FS, wrapWords} from './layout';
import {estimateTextWidth, WEIGHT} from './motion/typography';
import {Block} from './types';

export type BlockContent = {texts: TextSpec[]; logos: LogoSpec[]};

const BAR_MAX = 260;

export const blockContent = (b: Block, w: number, h: number, env: AspectEnv): BlockContent => {
  const texts: TextSpec[] = [];
  const logos: LogoSpec[] = [];
  const est = (s: string, fs: number, weight: number = WEIGHT.heavy, ls = 0, mono = false) => estimateTextWidth(s, fs, {weight, letterSpacing: ls, mono});
  switch (b.type) {
    case 'logo': {
      const box = {x: 0, y: 0, w, h};
      const expected = env.asset(env.logoPaths?.[b.variant] ?? '') ?? env.logo[b.variant];
      logos.push({...containRect(box, expected), variant: b.variant, expected});
      break;
    }
    case 'headline': {
      const fs = HEADLINE_FS[b.size];
      const lh = fs * 1.08;
      const ls = -0.025 * fs;
      wrapWords(b.words.map((x) => x.text), fs, w).forEach((line, li) => {
        const lw = line.reduce((s, i) => s + est(b.words[i].text, fs, WEIGHT.heavy, ls) + 0.26 * fs, 0);
        texts.push(T(line.map((i) => b.words[i].text).join(' '), 0, li * lh, w, lh, fs, WEIGHT.heavy, b.align ?? 'center', 'title', {est: lw}));
      });
      break;
    }
    case 'text': {
      const fs = TEXT_FS[b.size];
      const words = splitText(b.text);
      wrapWords(words, fs, w, 0.56).forEach((l, li) => texts.push(T(l.map((i) => words[i]).join(' '), 0, li * fs * 1.25, w, fs * 1.25, fs, WEIGHT.bold, 'center', 'body')));
      break;
    }
    case 'pill': {
      const {fs, padX, iconW, h, ls} = pillMetrics(b);
      texts.push(T(b.text, padX + iconW, 0, w - 2 * padX - iconW, h, fs, WEIGHT.heavy, 'center', 'label', ls ? {ls} : {}));
      break;
    }
    case 'price': {
      const labelH = b.label ? 62 : 0;
      if (b.label) texts.push(T(b.label, 0, 0, w, 62, 46, WEIGHT.bold, 'center', 'label'));
      const main = `${b.currency}${b.amount}`;
      const total = est(main, 280, WEIGHT.heavy, -10) + (b.period ? 12 + est(b.period, 84) : 0);
      texts.push(T(main + (b.period ?? ''), 0, labelH, w, 300, 280, WEIGHT.heavy, 'center', 'price', {est: total}));
      if (b.note) texts.push(T(b.note, 0, labelH + 300, w, 44, 30, WEIGHT.semibold, 'center', 'body'));
      break;
    }
    case 'checklist':
      b.items.forEach((it, i) => {
        const x = 34 + 64 + 28 + (it.icon ? 54 + 28 : 0);
        texts.push(T(it.text, x, i * 130, w - x - 34, 108, 52, WEIGHT.heavy, 'left', 'body'));
      });
      break;
    case 'bars': {
      texts.push(T(b.title, 50, 36, w - 100, 48, 38, WEIGHT.bold, 'left', 'title'));
      const n = b.bars.length;
      const slot = (w - 100) / n;
      const maxV = Math.max(...b.bars.map((x) => x.value), 1e-9);
      b.bars.forEach((bar, i) => texts.push(T(bar.label, 50 + slot * i, h - 92 + 18, slot, 46, 36, WEIGHT.heavy, 'center', 'label')));
      if (b.badge) {
        const barH = (b.bars[b.badge.bar].value / maxV) * BAR_MAX;
        const cx = 50 + slot * b.badge.bar + slot / 2;
        const tw = est(b.badge.text, 64);
        const pillH = 88;
        texts.push(T(b.badge.text, cx + 29 - Math.max(tw, slot) / 2, h - 92 - barH - 18 - pillH, Math.max(tw, slot), pillH, 64, WEIGHT.heavy, 'center', 'label'));
      }
      break;
    }
    case 'compare-rows':
      b.rows.forEach((r, i) => {
        const y = 50 + 20 + i * 112;
        const vw = est(r.value, 56);
        texts.push(T(r.label, 132, y, w - 40 - 132 - vw - 26, 110, 48, WEIGHT.bold, 'left', 'label'));
        texts.push(T(r.value, 132, y, w - 40 - 132, 110, 56, WEIGHT.heavy, 'right', 'price'));
      });
      if (b.badge) texts.push(T(b.badge.text, 0, 10, w + 20 - 28, 76, 40, WEIGHT.heavy, 'right', 'label'));
      break;
    case 'plans': {
      const n = b.plans.length;
      const cardW = (w - 24 * (n - 1)) / n;
      b.plans.forEach((p, i) => {
        const x = i * (cardW + 24);
        const inner = cardW - 40;
        const pfs = Math.min(92, cardW / Math.max(3, p.price.length) / 0.62);
        let y = 36 + 34;
        texts.push(T(p.name, x + 20, y, inner, 58, 46, WEIGHT.heavy, 'center', 'title'));
        y += 58 + 14;
        texts.push(T(p.price, x + 20, y, inner, pfs * 1.26, pfs, WEIGHT.heavy, 'center', 'price', {ls: -3}));
        y += pfs * 1.26;
        if (p.period) texts.push(T(p.period, x + 20, y, inner, 36, 30, WEIGHT.bold, 'center', 'label'));
        y += 36 + 38;
        if (p.detail) texts.push(T(p.detail, x + 20, y, inner, 40, 28, WEIGHT.bold, 'center', 'body'));
        texts.push(T(b.select?.index === i ? 'Selected ✓' : 'Choose', x + 20, 36 + 450 - 26 - 70, inner, 70, 30, WEIGHT.heavy, 'center', 'label'));
        if (p.badge) texts.push(T(p.badge, x, 10, cardW, 52, 26, WEIGHT.heavy, 'center', 'label'));
      });
      break;
    }
    case 'domain-input':
      texts.push(T(b.title, 44, 40, w - 88, 50, 50, WEIGHT.heavy, 'left', 'title'));
      texts.push(T(b.domain, 142, 116, w - 44 - 28 - 142, 112, 56, WEIGHT.regular, 'left', 'url', {mono: true, ls: -1}));
      texts.push(T(`${b.domain} ${b.availableText}`, 44 + 44 + 14, 242, w - 88 - 58, 64, 36, WEIGHT.heavy, 'left', 'body'));
      texts.push(T(b.button.done, 44, 324, w - 88, 116, 50, WEIGHT.heavy, 'center', 'label'));
      break;
    case 'browser':
      texts.push(T(b.url, 168, 26, w - 30 - 168, 52, 30, WEIGHT.regular, 'left', 'url', {mono: true}));
      texts.push(T('Loading… 0.0s', 114, 390, w - 114 - 40, 52, 38, WEIGHT.regular, 'left', 'label', {mono: true}));
      if (b.tag) texts.push(T(b.tag.text, 0, 18, w + 30 - 31, 76, 44, WEIGHT.heavy, 'right', 'label'));
      break;
    case 'hook-tag':
      texts.push(T(b.label, 60, 126, w - 120, 38, 30, WEIGHT.heavy, 'center', 'label', {ls: 4}));
      texts.push(T(b.text, 60, 164, w - 120, 92, 84, WEIGHT.heavy, 'center', 'title', {ls: -2}));
      if (b.sub) texts.push(T(b.sub, 60, 256, w - 120, 36, 28, WEIGHT.semibold, 'center', 'body'));
      break;
    case 'flat-line': {
      texts.push(T(b.title, 50, 40, w - 100, 46, 36, WEIGHT.bold, 'left', 'title'));
      const n = b.points.length;
      const span = w - 180;
      b.points.forEach((pt, i) => {
        const pos = n === 1 ? 0 : i / (n - 1);
        const x = 90 + pos * span - 90;
        texts.push(T(pt.value, x, 120, 180, 56, 44, WEIGHT.heavy, 'center', 'price'));
        texts.push(T(pt.label, x, 242, 180, 36, 28, WEIGHT.bold, 'center', 'label'));
      });
      break;
    }
    case 'cta': {
      const words = splitText(b.text);
      const lines = wrapWords(words, CTA_FS, w);
      const lh = CTA_FS * 1.1;
      lines.forEach((l, li) => {
        const lw = l.reduce((s, i) => s + est(words[i], CTA_FS, WEIGHT.heavy, -3) + 28, 0);
        texts.push(T(l.map((i) => words[i]).join(' '), 0, li * lh, w, lh, CTA_FS, WEIGHT.heavy, 'center', 'title', {est: lw}));
      });
      const textH = lines.length * lh;
      texts.push(T(b.url, 56, textH + 30, w - 112 - 90, 150, 76, WEIGHT.heavy, 'center', 'url', {ls: -1}));
      if (b.sub) texts.push(T(b.sub, 0, textH + 30 + 150 + 24, w, 46, 36, WEIGHT.bold, 'center', 'body'));
      break;
    }
    case 'kinetic-text':
      return {texts: geomKinetic(b, w).texts, logos};
    case 'counter':
      return {texts: geomCounter(b, w).texts, logos};
    case 'price-compare':
      return {texts: geomPriceCompare(b, w, env.polish).texts, logos};
    case 'terminal':
      return {texts: geomTerminal(b, w).texts, logos};
    case 'dashboard': {
      const g = geomDashboard(b, w, env);
      return {texts: g.texts, logos: g.logos};
    }
    case 'device': {
      const g = geomDevice(b, w, env);
      return {texts: g.texts, logos: g.logos};
    }
    case 'image': {
      const g = geomImage(b, w, env);
      return {texts: g.texts, logos: g.logos};
    }
    case 'progress':
      return {texts: geomProgress(b, w).texts, logos};
    case 'scroll-demo':
      return {texts: geomScrollDemo(b, w).texts, logos};
    case 'chart':
      return {texts: geomChart(b, w, env.polish).texts, logos};
    case 'feature-compare':
      return {texts: geomFeatureCompare(b, w, env.polish).texts, logos};
    case 'logo-sting': {
      const g = geomLogoSting(b, w, env);
      return {texts: g.texts, logos: g.logos};
    }
    case 'outro': {
      const g = geomOutro(b, w, env);
      return {texts: g.texts, logos: g.logos};
    }
    case 'plan-card':
      return {texts: geomPlanCard(b, w).texts, logos};
    case 'install-flow':
      return {texts: geomInstallFlow(b, w).texts, logos};
    case 'server-stack':
      return {texts: geomServerStack(b, w).texts, logos};
    case 'footage':
      return {texts: geomFootage(b, w, env).texts, logos};
    case 'composition': {
      const g = geomComposition(b, w, env);
      return {texts: g.texts, logos: g.logos};
    }
  }
  return {texts, logos};
};
