import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {Any, api, fileUrl, waitTask} from '../api';
import {Alert, Badge, Button, Card, Dialog, Empty, ErrorBox, Field, WPS, estSeconds, isTyping, toast, useApi, words} from '../ui';
import type {Nav} from '../app';

const EDITABLE = ['DRAFT', 'STORYBOARD_READY', 'PREVIEW_READY', 'CHANGES_REQUESTED', 'FAILED'];
const RENDERABLE = ['STORYBOARD_READY', 'PREVIEW_READY', 'FAILED'];

type FieldKind = 'text' | 'number' | 'time' | 'bool' | 'tone' | 'icon' | string[];
const COMMON: [string, FieldKind][] = [['at', 'time'], ['exitAt', 'time']];
const FIELD_MAP: Record<string, [string, FieldKind][]> = {
  headline: [['words', 'text'], ['size', ['xl', 'l', 'm']], ['align', ['center', 'left']]],
  text: [['text', 'text'], ['size', ['l', 'm', 's']], ['tone', 'tone']],
  pill: [['text', 'text'], ['tone', 'tone'], ['icon', 'icon'], ['stamp', 'bool']],
  price: [['currency', 'text'], ['amount', 'number'], ['period', 'text'], ['label', 'text'], ['note', 'text'], ['countEnd', 'time']],
  logo: [['variant', ['onDark', 'onLight', 'mark']], ['width', 'number']],
  cta: [['text', 'text'], ['url', 'text'], ['urlAt', 'time'], ['clickAt', 'time'], ['sub', 'text']],
  'hook-tag': [['label', 'text'], ['text', 'text'], ['sub', 'text']],
  browser: [['url', 'text'], ['loadUntil', 'time'], ['stallAt', 'time']],
  'domain-input': [['title', 'text'], ['domain', 'text'], ['typeAt', 'time'], ['availableText', 'text']],
  bars: [['title', 'text']],
  'flat-line': [['title', 'text'], ['drawEnd', 'time']],
  checklist: [], 'compare-rows': [], plans: [['emphasizeAt', 'time']],
};
const BLOCK_DEFAULTS: Record<string, Any> = {
  headline: {size: 'l', words: 'Your headline here'},
  text: {text: 'Supporting line', size: 'm'},
  pill: {text: 'NEW', tone: 'brand'},
  price: {currency: '₹', amount: 49, period: '/mo', label: 'Starting at', note: 'excl. taxes'},
  checklist: {items: [{text: 'First benefit', icon: 'check', at: 0.4}, {text: 'Second benefit', icon: 'check', at: 1.0}]},
  bars: {title: 'Comparison', bars: [{label: 'Them', value: 3, tone: 'danger', at: 0.3}, {label: 'Us', value: 1, tone: 'brand', at: 0.8}]},
  'compare-rows': {rows: [{label: 'Intro', value: '₹49', at: 0.3}, {label: 'Renewal', value: '₹49', at: 0.9}]},
  plans: {plans: [{name: 'Starter', price: '₹49', period: '/mo'}, {name: 'Pro', price: '₹99', period: '/mo', badge: 'Popular'}]},
  'domain-input': {title: 'Find your domain', domain: 'yourname.in', typeAt: 0.2, availableText: 'is available!',
    button: {idle: 'Search', busy: 'Checking…', done: 'Available', clickAt: '@end-1.2', doneAt: '@end-0.8'}},
  browser: {url: 'your-website.in', loadUntil: '@end-0.5'},
  'hook-tag': {label: 'INTRO OFFER', text: 'Cheap!', sub: 'first term only'},
  'flat-line': {title: 'Your price', points: [{label: 'Year 1', value: '₹49'}, {label: 'Year 2', value: '₹49'}], drawEnd: '@end-0.5'},
  logo: {variant: 'onDark', width: 720},
  cta: {text: 'Get started', url: 'yourdomain.com', urlAt: '@end-1.0'},
};

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

function template(p: Any, domain: string): Any {
  const product = p.brief?.product ?? 'our product';
  const cta = p.brief?.cta ?? `Start today at ${domain}`;
  return {version: 1, title: p.name, structure: ['hook', 'problem', 'resolution', 'cta'], scenes: [
    {id: 'hook', purpose: 'hook', transition: 'fade', narration: `Looking for ${product}?`, blocks: [{type: 'headline', size: 'xl', words: `Looking for ${product}?`}]},
    {id: 'problem', purpose: 'problem', mood: 'danger', transition: 'fade', narration: 'Most options get expensive fast.', blocks: [{type: 'text', text: 'Most options get expensive fast.', size: 'l', tone: 'danger'}]},
    {id: 'resolution', purpose: 'resolution', mood: 'brand', brandBar: true, transition: 'fade', narration: `Here is a better way to get ${product}.`, blocks: [{type: 'headline', size: 'l', words: 'A better way'}]},
    {id: 'cta', purpose: 'cta', brandBar: true, transition: 'fade', narration: `${cta}.`.replace(/\.\.$/, '.'), blocks: [{type: 'logo', variant: 'onDark', width: 720}, {type: 'cta', text: 'Get started', url: domain, urlAt: '@end-1.0'}]},
  ]};
}

const sceneOfError = (e: string): number | null => {
  const m = /scenes\[(\d+)\]/.exec(e);
  return m ? Number(m[1]) : null;
};

export const StoryboardEditor: React.FC<{nav: Nav; pid: string}> = ({nav, pid}) => {
  const {data: p, error, reload} = useApi<Any>(`/api/productions/${pid}`);
  const {data: schema} = useApi<Any>('/api/storyboard/schema');
  const [sb, setSb] = useState<Any | null>(null);
  const [dirty, setDirty] = useState(false);
  const [sel, setSel] = useState(0);
  const [rev, setRev] = useState(0);              // bumps to re-seed JSON editors after structural changes
  const [errors, setErrors] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [apiErr, setApiErr] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [raw, setRaw] = useState(false);
  const [confirmRender, setConfirmRender] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => {
    if (p && !dirty) { setSb(p.storyboard ? clone(p.storyboard) : null); setRev((r) => r + 1); }
  }, [p]); // eslint-disable-line react-hooks/exhaustive-deps

  const editable = p ? EDITABLE.includes(p.state) : false;
  const scenes: Any[] = sb?.scenes ?? [];
  const scene = scenes[sel];
  const total = scenes.reduce((a, s) => a + estSeconds(s.narration ?? ''), 0);
  const target = p?.brief?.duration_seconds;
  const errScenes = useMemo(() => new Set(errors.map(sceneOfError).filter((x) => x !== null)), [errors]);

  const update = useCallback((fn: (d: Any) => void, structural = false) => {
    setSb((cur: Any) => { const d = clone(cur); fn(d); return d; });
    setDirty(true);
    if (structural) setRev((r) => r + 1);
  }, []);

  const save = useCallback(async () => {
    if (!sb || !editable) return;
    setBusy('save'); setApiErr(null);
    try {
      const r = await api.put(`/api/productions/${pid}/storyboard`, {storyboard: sb});
      setErrors([]); setWarnings(r.warnings ?? []); setDirty(false);
      toast('success', `Storyboard saved${r.warnings?.length ? ` with ${r.warnings.length} warning(s)` : ''}`);
      await reload();
    } catch (e: Any) {
      if (e.errors?.length) { setErrors(e.errors); const first = e.errors.map(sceneOfError).find((x: number | null) => x !== null); if (first != null) setSel(first); }
      setApiErr(e);
    } finally { setBusy(null); }
  }, [sb, editable, pid, reload]);

  const validate = async () => {
    if (!sb) return;
    setBusy('validate'); setApiErr(null);
    try {
      const r = await api.post(`/api/productions/${pid}/storyboard/validate`, {storyboard: sb});
      setErrors(r.errors); setWarnings(r.warnings);
      toast(r.errors.length ? 'danger' : 'success', r.errors.length ? `${r.errors.length} validation error(s)` : 'Storyboard is valid (static checks)');
    } catch (e) { setApiErr(e); } finally { setBusy(null); }
  };

  const runTask = async (kind: 'preview' | 'render') => {
    setBusy(kind); setApiErr(null);
    try {
      const {task} = await api.post(`/api/productions/${pid}/${kind}`);
      const t = await waitTask(task.id);
      if (t.status === 'failed') throw Object.assign(new Error(t.error?.message), t.error);
      await reload();
      if (kind === 'render') { toast('success', `Render job ${t.result.job_id} started`); nav.go('monitor', t.result.job_id); } else toast('success', 'Preview ready');
    } catch (e) { setApiErr(e); } finally { setBusy(null); }
  };

  const move = useCallback((from: number, to: number) => {
    if (to < 0 || to >= scenes.length) return;
    update((d) => { const [s] = d.scenes.splice(from, 1); d.scenes.splice(to, 0, s); }, true);
    setSel(to);
  }, [scenes.length, update]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { e.preventDefault(); void save(); return; }
      if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) { e.preventDefault(); move(sel, sel + (e.key === 'ArrowUp' ? -1 : 1)); return; }
      if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'j') setSel((s) => Math.min(scenes.length - 1, s + 1));
      if (e.key === 'k') setSel((s) => Math.max(0, s - 1));
    };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [save, move, sel, scenes.length]);

  useEffect(() => {
    if (!dirty) return;
    const f = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener('beforeunload', f);
    return () => window.removeEventListener('beforeunload', f);
  }, [dirty]);

  if (error) return <ErrorBox error={error} />;
  if (!p) return <div className="skeleton" />;

  const stills: Record<string, string> = {};
  for (const s of p.preview?.stills ?? []) stills[s.scene] = s.png;

  if (!sb) {
    return (
      <Card title="No storyboard yet">
        <p className="muted mb">Generate one from a concept, or start from a minimal hook → problem → resolution → CTA template and edit it here.</p>
        <div className="row">
          <Button variant="primary" disabled={!editable} onClick={() => { setSb(template(p, nav.brands.find((b) => b.id === p.brand)?.domain ?? 'yourdomain.com')); setDirty(true); setRev((r) => r + 1); }}>Start from template</Button>
          <Button onClick={() => nav.go('new', pid)}>Go to concepts</Button>
        </div>
        {!editable && <Alert tone="warning">The storyboard is locked while the production is {p.state}.</Alert>}
      </Card>
    );
  }

  const addScene = () => {
    let n = scenes.length + 1;
    while (scenes.some((s) => s.id === `scene-${n}`)) n++;
    const ns = {id: `scene-${n}`, purpose: 'point', transition: 'fade', narration: 'New scene narration.', blocks: [{type: 'text', text: 'New scene', size: 'l'}]};
    update((d) => { d.scenes.splice(sel + 1, 0, ns); }, true);
    setSel(sel + 1);
  };
  const dupScene = () => {
    const c = clone(scenes[sel]);
    let n = 2; while (scenes.some((s) => s.id === `${c.id}-${n}`)) n++;
    c.id = `${c.id}-${n}`.slice(0, 41);
    update((d) => { d.scenes.splice(sel + 1, 0, c); }, true);
    setSel(sel + 1);
  };
  const delScene = () => {
    if (scenes.length <= 1) return;
    if (!window.confirm(`Remove scene "${scene.id}"?`)) return;
    update((d) => { d.scenes.splice(sel, 1); }, true);
    setSel(Math.max(0, sel - 1));
  };

  return (
    <div className="editor">
      <div className="toolbar">
        <input className="title-in" value={sb.title ?? ''} placeholder="Storyboard title" disabled={!editable}
          onChange={(e) => update((d) => { d.title = e.target.value; })} aria-label="Storyboard title" />
        <span className={`dur ${target && Math.abs(total - target) > target * 0.2 ? 'warn-t' : ''}`} title={`~${WPS} words/s`}>
          ≈ {total.toFixed(1)} s{target ? ` / target ${target} s` : ''}</span>
        {dirty && <Badge tone="warning">unsaved</Badge>}
        <div className="spacer" />
        <Button variant="ghost" onClick={() => setShowHistory(true)}>History ({p.history.length})</Button>
        <Button variant="ghost" onClick={() => { setRaw(!raw); setRev((r) => r + 1); }}>{raw ? 'Scene editor' : 'Raw JSON'}</Button>
        <Button onClick={validate} busy={busy === 'validate'}>Validate</Button>
        <Button variant="primary" onClick={save} busy={busy === 'save'} disabled={!editable} kbd="⌘S">Save</Button>
        <Button onClick={() => runTask('preview')} busy={busy === 'preview'} disabled={dirty || !p.files['storyboard.json'] || !!busy}
          title={dirty ? 'Save first' : 'One still per scene from estimated timings'}>Low-cost preview</Button>
        <Button variant="success" onClick={() => setConfirmRender(true)} disabled={dirty || !RENDERABLE.includes(p.state) || !!busy}>Render…</Button>
      </div>
      {!editable && <Alert tone="warning">The storyboard is locked while the production is <b>{p.state}</b>. {p.state === 'AWAITING_APPROVAL' ? 'Request changes in the Publishing Center to edit it again.' : ''}</Alert>}
      <ErrorBox error={apiErr} title={errors.length ? `Validation failed — ${errors.length} problem(s)` : 'Request failed'} onDismiss={() => setApiErr(null)} />
      {errors.length > 0 && !apiErr && (
        <div className="alert alert-danger"><div className="alert-h"><strong>{errors.length} validation error(s)</strong></div>
          <ul className="errlist">{errors.map((e, i) => <li key={i}><button className="linkbtn" onClick={() => { const s = sceneOfError(e); if (s != null) setSel(s); }}><code>{e}</code></button></li>)}</ul></div>
      )}
      {warnings.length > 0 && <Alert tone="warning" title={`${warnings.length} warning(s)`}><ul className="errlist">{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></Alert>}

      {raw ? (
        <Card title="Storyboard JSON" actions={<span className="muted sm">Apply, then Save to validate on the server</span>}>
          <JsonArea key={`raw-${rev}`} value={sb} rows={30} disabled={!editable} onChange={(v) => { if (v && typeof v === 'object') { setSb(v); setDirty(true); } }} />
        </Card>
      ) : (
        <div className="ed-grid">
          <div className="scene-list" role="listbox" aria-label="Scenes">
            {scenes.map((s, i) => (
              <div key={`${s.id}-${i}`} role="option" aria-selected={i === sel} tabIndex={0}
                className={`scene-i ${i === sel ? 'sel' : ''} ${errScenes.has(i) ? 'has-err' : ''}`}
                onClick={() => setSel(i)} onKeyDown={(e) => { if (e.key === 'Enter') setSel(i); }}>
                <div className="scene-i-h"><span className="scene-n">{i + 1}</span><span className="scene-id">{s.id}</span><span className="muted sm">{estSeconds(s.narration ?? '').toFixed(1)}s</span></div>
                <div className="scene-i-m"><Badge tone={s.purpose === 'cta' ? 'brand' : s.purpose === 'problem' ? 'danger' : 'neutral'}>{s.purpose}</Badge>
                  <span className="muted sm">{(s.blocks ?? []).length} block{(s.blocks ?? []).length === 1 ? '' : 's'}{s.cues ? ` · ${Object.keys(s.cues).length} cues` : ''}{s.sfx?.length ? ` · ${s.sfx.length} sfx` : ''}</span></div>
                <div className="scene-i-t">{s.narration}</div>
              </div>
            ))}
            {editable && (
              <div className="scene-ops">
                <Button variant="ghost" onClick={addScene}>+ Scene</Button>
                <Button variant="ghost" onClick={dupScene} disabled={!scene}>Duplicate</Button>
                <Button variant="ghost" onClick={() => move(sel, sel - 1)} disabled={sel === 0} title="Alt+↑">↑</Button>
                <Button variant="ghost" onClick={() => move(sel, sel + 1)} disabled={sel >= scenes.length - 1} title="Alt+↓">↓</Button>
                <Button variant="ghost" className="danger-t" onClick={delScene} disabled={scenes.length <= 1}>Remove</Button>
              </div>
            )}
          </div>
          {scene ? (
            <SceneEditor key={`${sel}-${rev}`} scene={scene} index={sel} schema={schema} disabled={!editable} still={stills[scene.id]}
              stillBust={p.updated_at} errors={errors.filter((e) => sceneOfError(e) === sel)}
              onChange={(fn, structural) => update((d) => fn(d.scenes[sel]), structural)} />
          ) : <Empty>Select a scene.</Empty>}
        </div>
      )}

      {p.preview && (
        <Card title="Low-cost preview" className="mt" actions={<span className="muted sm">{p.preview.note} ≈ {p.preview.duration_estimate_s}s · built in {p.preview.seconds}s</span>}>
          <img className="contact" src={fileUrl(p.preview.contact_sheet, p.updated_at)} alt="Contact sheet of storyboard stills" />
        </Card>
      )}

      <Dialog open={confirmRender} title="Start full render?" onClose={() => setConfirmRender(false)}
        footer={<><Button variant="ghost" onClick={() => setConfirmRender(false)}>Cancel</Button>
          <Button variant="success" onClick={() => { setConfirmRender(false); void runTask('render'); }}>Start render</Button></>}>
        <p>This runs TTS, the chunked Remotion render, mixing and QA in a background process (it waits for the scheduler if another heavy job is running). The result stops at <b>AWAITING_APPROVAL</b>; nothing is published.</p>
        <p className="muted">Estimated length ≈ {total.toFixed(1)} s{target ? ` (target ${target} s)` : ''}.</p>
      </Dialog>
      <Dialog open={showHistory} title="Storyboard history" onClose={() => setShowHistory(false)}>
        {p.history.length === 0 ? <p className="muted">No previous versions yet — every save keeps the previous file.</p> : (
          <ul className="hist">{p.history.map((h: string) => (
            <li key={h}><span className="mono sm">{h.split('/').pop()}</span>
              <span className="row">
                <a href={fileUrl(h)} target="_blank" rel="noreferrer">View</a>
                {editable && <Button variant="ghost" onClick={async () => {
                  try { const r = await fetch(fileUrl(h), {credentials: 'same-origin'}); const v = await r.json(); setSb(v); setDirty(true); setRev((x) => x + 1); setShowHistory(false); toast('info', 'Loaded old version into the editor (not saved yet)'); } catch (e) { setApiErr(e); }
                }}>Load into editor</Button>}
              </span></li>))}</ul>
        )}
      </Dialog>
    </div>
  );
};

// ---- scene editor ------------------------------------------------------------------------------
const SceneEditor: React.FC<{scene: Any; index: number; schema: Any; disabled: boolean; still?: string; stillBust?: number; errors: string[];
  onChange: (fn: (s: Any) => void, structural?: boolean) => void}> = ({scene, index, schema, disabled, still, stillBust, errors, onChange}) => {
  const [newType, setNewType] = useState('text');
  const set = (k: string, v: Any) => onChange((s) => { if (v === '' || v === undefined || v === null) delete s[k]; else s[k] = v; });
  const purposes: string[] = schema?.purposes ?? ['hook', 'problem', 'turn', 'journey', 'resolution', 'cta'];
  const n = words(scene.narration ?? '');
  return (
    <div className="scene-ed">
      <Card title={<span>Scene {index + 1} <span className="mono muted">{scene.id}</span></span>}
        actions={<span className="muted sm">{n} words · ≈ {(n / WPS).toFixed(1)} s</span>}>
        {errors.length > 0 && <ul className="errlist err-inline">{errors.map((e, i) => <li key={i}><code>{e}</code></li>)}</ul>}
        <div className="scene-top">
          <div className="form-grid g3 grow">
            <Field label="Id"><input value={scene.id} disabled={disabled} onChange={(e) => set('id', e.target.value)} pattern="[a-z0-9][a-z0-9_-]{0,40}" /></Field>
            <Field label="Purpose"><select value={scene.purpose} disabled={disabled} onChange={(e) => set('purpose', e.target.value)}>{purposes.map((x) => <option key={x}>{x}</option>)}</select></Field>
            <Field label="Mood"><select value={scene.mood ?? ''} disabled={disabled} onChange={(e) => set('mood', e.target.value)}><option value="">default</option>{(schema?.moods ?? ['neutral', 'danger', 'brand']).map((x: string) => <option key={x}>{x}</option>)}</select></Field>
            <Field label="Transition"><select value={scene.transition ?? ''} disabled={disabled} onChange={(e) => set('transition', e.target.value)}><option value="">default</option>{(schema?.transitions ?? ['fade', 'slide-up', 'none']).map((x: string) => <option key={x}>{x}</option>)}</select></Field>
            <Field label="Layout"><select value={scene.layout ?? ''} disabled={disabled} onChange={(e) => set('layout', e.target.value)}><option value="">stack</option>{(schema?.layouts ?? ['stack', 'split']).map((x: string) => <option key={x}>{x}</option>)}</select></Field>
            {scene.layout === 'split' ? <Field label="Split at (blocks left)"><input type="number" min={1} value={scene.splitAt ?? ''} disabled={disabled} onChange={(e) => set('splitAt', e.target.value ? Number(e.target.value) : '')} /></Field>
              : <div className="field checks">
                <label className="check"><input type="checkbox" checked={!!scene.brandBar} disabled={disabled} onChange={(e) => set('brandBar', e.target.checked || '')} /> Brand bar</label>
                <label className="check"><input type="checkbox" checked={scene.autoSfx !== false} disabled={disabled} onChange={(e) => set('autoSfx', e.target.checked ? '' : false)} /> Auto SFX</label>
              </div>}
          </div>
          {still && <img className="still" src={fileUrl(still, stillBust)} alt={`Preview still for ${scene.id}`} />}
        </div>
        <Field label="Narration" wide hint="1–2 sentences. Times like @word:Grow must use words spoken in this scene.">
          <textarea rows={3} value={scene.narration} disabled={disabled} onChange={(e) => set('narration', e.target.value)} className="narration" />
        </Field>
      </Card>

      <Card title={`Blocks (${(scene.blocks ?? []).length})`} actions={!disabled && (
        <span className="row">
          <select value={newType} onChange={(e) => setNewType(e.target.value)} aria-label="Block type to add">{(schema?.blockTypes ?? Object.keys(BLOCK_DEFAULTS)).map((t: string) => <option key={t}>{t}</option>)}</select>
          <Button variant="ghost" onClick={() => onChange((s) => { s.blocks = [...(s.blocks ?? []), {type: newType, ...clone(BLOCK_DEFAULTS[newType] ?? {})}]; }, true)}>+ Add block</Button>
        </span>)}>
        {(scene.blocks ?? []).length > 3 && <Alert tone="warning">More than ~3 blocks per scene usually crowds the frame.</Alert>}
        {(scene.blocks ?? []).map((b: Any, bi: number) => (
          <BlockEditor key={bi} block={b} index={bi} count={scene.blocks.length} schema={schema} disabled={disabled}
            onChange={(nb) => onChange((s) => { s.blocks[bi] = nb; })}
            onMove={(d) => onChange((s) => { const [x] = s.blocks.splice(bi, 1); s.blocks.splice(bi + d, 0, x); }, true)}
            onRemove={() => onChange((s) => { s.blocks.splice(bi, 1); }, true)} />
        ))}
      </Card>

      <div className="grid2">
        <Card title="Cues" actions={<span className="muted sm">{'{"stop": {"word": "Stop"}}'}</span>}>
          <JsonArea value={scene.cues ?? {}} rows={5} disabled={disabled} onChange={(v) => onChange((s) => { if (v && Object.keys(v).length) s.cues = v; else delete s.cues; })} />
        </Card>
        <Card title="Sound effects" actions={<span className="muted sm">{'[{"at": "@stop", "sound": "pop/…"}]'}</span>}>
          <JsonArea value={scene.sfx ?? []} rows={5} disabled={disabled} onChange={(v) => onChange((s) => { if (Array.isArray(v) && v.length) s.sfx = v; else delete s.sfx; })} />
        </Card>
      </div>
    </div>
  );
};

const BlockEditor: React.FC<{block: Any; index: number; count: number; schema: Any; disabled: boolean; onChange: (b: Any) => void;
  onMove: (d: number) => void; onRemove: () => void}> = ({block, index, count, schema, disabled, onChange, onMove, onRemove}) => {
  const [json, setJson] = useState(false);
  const fields = [...(FIELD_MAP[block.type] ?? []), ...COMMON];
  const set = (k: string, v: Any) => { const nb = {...block}; if (v === '' || v === undefined) delete nb[k]; else nb[k] = v; onChange(nb); };
  const input = (k: string, kind: FieldKind) => {
    const v = block[k];
    if (Array.isArray(kind) || kind === 'tone' || kind === 'icon') {
      const opts = Array.isArray(kind) ? kind : kind === 'tone' ? (schema?.tones ?? []) : (schema?.icons ?? []);
      return <select value={v ?? ''} disabled={disabled} onChange={(e) => set(k, e.target.value)}><option value="">—</option>{opts.map((o: string) => <option key={o}>{o}</option>)}</select>;
    }
    if (kind === 'bool') return <input type="checkbox" checked={!!v} disabled={disabled} onChange={(e) => set(k, e.target.checked || '')} />;
    if (kind === 'number') return <input type="number" value={v ?? ''} disabled={disabled} onChange={(e) => set(k, e.target.value === '' ? '' : Number(e.target.value))} />;
    if (k === 'words' && typeof v !== 'string' && v !== undefined) return <span className="muted sm">word list — edit as JSON</span>;
    if (kind === 'time') {
      return <input value={v ?? ''} disabled={disabled} placeholder="1.2 · @word:x · @end-0.3" className="mono"
        onChange={(e) => { const t = e.target.value; set(k, /^-?\d+(\.\d+)?$/.test(t.trim()) ? Number(t) : t); }} />;
    }
    return <input value={v ?? ''} disabled={disabled} onChange={(e) => set(k, e.target.value)} />;
  };
  const extra = Object.keys(block).filter((k) => k !== 'type' && !fields.some(([f]) => f === k));
  return (
    <div className="block">
      <div className="block-h">
        <span className="block-n">{index + 1}</span>
        <select value={block.type} disabled={disabled} onChange={(e) => onChange({type: e.target.value, ...clone(BLOCK_DEFAULTS[e.target.value] ?? {})})} aria-label="Block type">
          {Array.from(new Set([block.type, ...(schema?.blockTypes ?? [])])).map((t) => <option key={t}>{t}</option>)}
        </select>
        <div className="spacer" />
        <Button variant="ghost" onClick={() => setJson(!json)}>{json ? 'Form' : 'JSON'}</Button>
        {!disabled && <>
          <Button variant="ghost" onClick={() => onMove(-1)} disabled={index === 0} aria-label="Move block up">↑</Button>
          <Button variant="ghost" onClick={() => onMove(1)} disabled={index >= count - 1} aria-label="Move block down">↓</Button>
          <Button variant="ghost" className="danger-t" onClick={onRemove} aria-label="Remove block">×</Button>
        </>}
      </div>
      {json ? <JsonArea value={block} rows={8} disabled={disabled} onChange={(v) => { if (v && typeof v === 'object' && !Array.isArray(v) && v.type) onChange(v); }} /> : (
        <div className="form-grid g3">
          {fields.map(([k, kind]) => <Field key={k} label={k}>{input(k, kind)}</Field>)}
          {extra.length > 0 && <div className="field field-wide"><span className="field-h">Also set (edit as JSON): {extra.map((k) => <code key={k} className="ml">{k}</code>)}</span></div>}
        </div>
      )}
    </div>
  );
};

/** JSON textarea: applies on valid parse, shows the parse error otherwise. */
const JsonArea: React.FC<{value: Any; onChange: (v: Any) => void; rows?: number; disabled?: boolean}> = ({value, onChange, rows = 6, disabled}) => {
  const [text, setText] = useState(() => JSON.stringify(value, null, 1));
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="json">
      <textarea className={`mono ${err ? 'bad' : ''}`} rows={rows} value={text} disabled={disabled} spellCheck={false}
        onChange={(e) => {
          setText(e.target.value);
          try { const v = JSON.parse(e.target.value); setErr(null); onChange(v); } catch (x) { setErr((x as Error).message); }
        }} />
      {err && <div className="json-err">{err}</div>}
    </div>
  );
};
