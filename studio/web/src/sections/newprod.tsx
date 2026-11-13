import React, {useState} from 'react';
import {Any, api, waitTask} from '../api';
import {Alert, Badge, Button, Card, Empty, ErrorBox, Field, Pre, Spinner, State, toast, useApi} from '../ui';
import type {Nav} from '../app';

const GOALS = ['conversions', 'awareness', 'education', 'engagement', 'retention', 'launch'];

export const NewProduction: React.FC<{nav: Nav; pid: string}> = ({nav, pid}) =>
  pid ? <Concepts nav={nav} pid={pid} /> : <BriefForm nav={nav} />;

const BriefForm: React.FC<{nav: Nav}> = ({nav}) => {
  const [f, setF] = useState<Record<string, string>>({brand: nav.brand, format: 'short', duration_seconds: '35', goal: 'conversions'});
  const brandId = f.brand || nav.brands[0]?.id || '';
  const domain = nav.brands.find((b) => b.id === brandId)?.domain ?? 'yourdomain.com';
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({...f, [k]: e.target.value});
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const {brand: _b, name, duration_seconds, duration_flexible, also_other, ...rest} = f;
      const other = rest.format === 'landscape' ? 'short' : 'landscape';
      const brief: Record<string, unknown> = {...rest, ...(duration_flexible ? {duration_flexible: true} : {}),
        ...(also_other ? {formats: [rest.format, other]} : {})};
      const brand = brandId;
      const p = await api.post('/api/productions', {brand, name: name || undefined,
        brief: {...brief, duration_seconds: Number(duration_seconds)}});
      toast('success', `Production ${p.id} created`);
      nav.setPid(p.id);
      nav.go('new', p.id);
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <div className="grid">
      <Card title="Product brief" className="span-8">
        <form onSubmit={submit} className="form">
          <div className="form-grid">
            <Field label="Brand">
              <select value={brandId} onChange={set('brand')}>{nav.brands.map((b) => <option key={b.id} value={b.id}>{b.name} ({b.id}){b.status === 'draft' ? ' · draft' : ''}</option>)}</select>
            </Field>
            <Field label="Product *"><input required maxLength={120} value={f.product ?? ''} onChange={set('product')} placeholder="NVMe web hosting" /></Field>
            <Field label="Price" hint="Exactly as on the site, e.g. ₹49/mo (excl. taxes). Unverified prices become review flags.">
              <input maxLength={60} value={f.price ?? ''} onChange={set('price')} placeholder="₹49/mo" /></Field>
            <Field label="Audience"><input maxLength={160} value={f.audience ?? ''} onChange={set('audience')} placeholder="Indian small-business owners" /></Field>
            <Field label="Format">
              <div className="seg">{['short', 'landscape'].map((x) => <button type="button" key={x} className={f.format === x ? 'on' : ''} onClick={() => setF({...f, format: x})}>{x === 'short' ? 'Short 9:16' : 'Landscape 16:9'}</button>)}</div>
            </Field>
            <Field label="Duration (seconds)" hint="Shorts: 25–45 s"><input type="number" min={10} max={180} value={f.duration_seconds} onChange={set('duration_seconds')} /></Field>
            <Field label="Length" hint="A target for Shorts; or let the story decide (stays under 3 minutes)">
              <label className="check"><input type="checkbox" checked={f.duration_flexible === 'yes'} onChange={(e) => setF({...f, duration_flexible: e.target.checked ? 'yes' : ''})} /> Let the story set the length</label></Field>
            <Field label="Also render" hint="An extra, separately composed format">
              <label className="check"><input type="checkbox" checked={f.also_other === 'yes'} onChange={(e) => setF({...f, also_other: e.target.checked ? 'yes' : ''})} /> {f.format === 'landscape' ? 'Short 9:16' : 'Landscape 16:9'}</label></Field>
            <Field label="Goal"><select value={f.goal} onChange={set('goal')}>{GOALS.map((g) => <option key={g}>{g}</option>)}</select></Field>
            <Field label="Tone"><input maxLength={120} value={f.tone ?? ''} onChange={set('tone')} placeholder="confident, warm, no hype" /></Field>
            <Field label="Voice" hint="Local voice id (e.g. am_michael, bm_george) or leave blank for the preset default"><input maxLength={60} value={f.voice ?? ''} onChange={set('voice')} /></Field>
            <Field label="Call to action"><input maxLength={60} value={f.cta ?? ''} onChange={set('cta')} placeholder={`Start at ${domain}`} /></Field>
            <Field label="Request / notes" wide hint="Free text: what must the video show? (problem, demo, pricing comparison…)">
              <textarea rows={3} maxLength={2000} value={f.request ?? ''} onChange={set('request')} /></Field>
            <Field label="Production name" hint="Optional; defaults to the product"><input maxLength={100} value={f.name ?? ''} onChange={set('name')} /></Field>
          </div>
          <ErrorBox error={err} title="Could not create the production" />
          <div className="form-actions"><Button variant="primary" type="submit" busy={busy}>Create production</Button></div>
        </form>
      </Card>
      <Card title="What happens next" className="span-4">
        <ol className="steps">
          <li><b>Concepts.</b> The local creative engine proposes 3 distinct concepts with a fact-check of every claim.</li>
          <li><b>Storyboard.</b> Pick a concept (or write the storyboard by hand) and edit scenes, narration and blocks.</li>
          <li><b>Preview.</b> One still per scene — cheap, no voice, no full render.</li>
          <li><b>Render + QA.</b> Full render in the background; automated QA and review flags.</li>
          <li><b>Approve.</b> A named reviewer approves the exact package (sha256-bound).</li>
          <li><b>Export / publish.</b> Only on explicit, typed confirmation. Never automatic.</li>
        </ol>
      </Card>
    </div>
  );
};

const ROWS: [string, (c: Any) => React.ReactNode][] = [
  ['Pattern', (c) => c.pattern_name ?? c.pattern],
  ['Hook', (c) => c.hook && <q>{c.hook}</q>],
  ['Hook style', (c) => c.hook_style],
  ['Pacing', (c) => c.pacing ? `${c.pacing.words_per_second ?? '?'} w/s · ${c.pacing.scene_count ?? '?'} scenes` : c.words_per_second],
  ['Visual approach', (c) => (c.visual_approach?.hero_blocks ?? c.hero_blocks ?? []).join(', ') || c.visual_approach?.summary],
  ['Animation', (c) => c.animation_style],
  ['Music mood', (c) => c.music_mood],
  ['CTA', (c) => c.cta_treatment ? `${c.cta_treatment.style}: ${c.cta_treatment.text}` : c.cta],
  ['Covers', (c) => [(c.requirements_covered ?? []).join(', '), (c.requirements_missing ?? []).length ? ` (missing: ${c.requirements_missing.join(', ')})` : ''].join('')],
  ['Claims', (c) => c.claims ? <span>{c.claims.verified} verified · <span className={c.claims.needs_review ? 'warn-t' : ''}>{c.claims.needs_review} need review</span></span> : null],
  ['Source', (c) => c.source],
];

const Concepts: React.FC<{nav: Nav; pid: string}> = ({nav, pid}) => {
  const {data: p, error, reload} = useApi<Any>(`/api/productions/${pid}`);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [raw, setRaw] = useState(false);
  if (error) return <ErrorBox error={error} />;
  if (!p) return <div className="skeleton" />;
  const res = p.concepts;
  const concepts: Any[] = res?.concepts ?? [];
  const needs: Any[] = res?.brief_claims?.needs_review ?? [];
  const run = async (kind: 'concepts' | 'select', body: Any = {}) => {
    setBusy(kind === 'select' ? body.conceptId : kind); setErr(null);
    try {
      const {task} = await api.post(`/api/productions/${pid}/${kind}`, body);
      const t = await waitTask(task.id);
      if (t.status === 'failed') throw Object.assign(new Error(t.error?.message), t.error);
      if (kind === 'select') { toast('success', 'Storyboard generated'); nav.go('storyboard'); } else { toast('success', 'Concepts ready'); await reload(); }
    } catch (x) { setErr(x); } finally { setBusy(null); }
  };
  const locked = !['DRAFT', 'STORYBOARD_READY', 'PREVIEW_READY', 'CHANGES_REQUESTED', 'FAILED'].includes(p.state);
  return (
    <div className="grid">
      <Card className="span-12" title={<span>{p.name} <State s={p.state} /></span>}
        actions={<>
          <Button variant="secondary" onClick={() => nav.go('storyboard')}>Write storyboard manually</Button>
          <Button variant="primary" busy={busy === 'concepts'} disabled={!!busy || locked} onClick={() => run('concepts')}>{concepts.length ? 'Regenerate concepts' : 'Generate 3 concepts'}</Button>
        </>}>
        <div className="brief-line">
          {Object.entries(p.brief ?? {}).filter(([k]) => !['brand_id'].includes(k)).map(([k, v]) => <span key={k} className="chip"><b>{k.replace('_seconds', '')}</b> {String(v)}</span>)}
        </div>
        {busy === 'concepts' && <Alert tone="info"><Spinner label=" Generating concepts with the local model — this waits for the scheduler if a render is running." /></Alert>}
        <ErrorBox error={err} title="The creative engine failed" />
        {err ? <Alert tone="warning" title="You can still continue">The creative engine is optional. Use <b>Write storyboard manually</b> to start from a template in the Storyboard Editor.</Alert> : null}
      </Card>

      {concepts.length === 0 ? (
        <div className="span-12"><Empty>No concepts yet. Generate them, or write the storyboard manually.</Empty></div>
      ) : (
        <>
          <div className="concepts span-12">
            {concepts.map((c) => (
              <div key={c.id} className={`concept ${p.concept_id === c.id ? 'selected' : ''}`}>
                <div className="concept-h"><Badge tone="brand">{c.id}</Badge><h3>{c.name ?? c.title}</h3></div>
                {c.logline && <p className="muted">{c.logline}</p>}
                <dl className="kv kv-tight">{ROWS.map(([k, f]) => <React.Fragment key={k}><dt>{k}</dt><dd>{f(c) ?? '—'}</dd></React.Fragment>)}</dl>
                {Array.isArray(c.beats) && <ol className="beats">{c.beats.map((b: Any, i: number) => <li key={i}><i>{b.purpose}</i> — {b.idea}</li>)}</ol>}
                <Button variant={p.concept_id === c.id ? 'success' : 'primary'} className="w100" busy={busy === c.id} disabled={!!busy || locked}
                  onClick={() => run('select', {conceptId: c.id})}>{p.concept_id === c.id ? 'Selected — rebuild storyboard' : 'Select this concept'}</Button>
              </div>
            ))}
          </div>
          <Card title="Fact-check" className="span-6">
            {needs.length === 0 ? <div className="ok-t">No brief claims flagged NEEDS_REVIEW.</div> : (
              <ul className="flaglist">{needs.map((c, i) => <li key={i}><Badge tone="warning">NEEDS_REVIEW</Badge> <b>{c.text}</b> <span className="muted">— {c.reason ?? 'not in approved facts'}</span></li>)}</ul>
            )}
            {res?.distinctness && <p className="muted sm mt">Distinctness: min score {res.distinctness.min_score}, all distinct: {String(res.distinctness.all_distinct)}</p>}
            {res?.provider && <p className="muted sm">Provider: {res.provider.provider ?? JSON.stringify(res.provider)}</p>}
          </Card>
          <Card title="Comparison report" className="span-6" actions={<Button variant="ghost" onClick={() => setRaw(!raw)}>{raw ? 'Hide' : 'Show'} markdown</Button>}>
            {raw ? <Pre max={420}>{p.comparison_md ?? 'No comparison report file.'}</Pre> : <p className="muted">The side-by-side table above mirrors <code>concepts/comparison.md</code>.</p>}
          </Card>
        </>
      )}
    </div>
  );
};
