import React, {useEffect, useState} from 'react';
import {Any, api, fileUrl, runTask} from '../api';
import {Alert, Badge, Button, ErrorBox, Field, Progress, Spinner, estSeconds, toast, useApi, useLocal} from '../ui';
import type {Nav} from '../app';
import {PLATFORM_NAMES, platformName, plainStatus} from './home';
import {Icon, PlatformLogo} from '../icons';

/** "Create a video": the whole workflow one step at a time, in plain words. Every step calls the same endpoints
 * as the power-user pages (and so the same rules): a named person approves the preview and the final video,
 * nothing is approved or posted automatically. */
const STEPS = ['Website', 'What to promote', 'Pick an idea', 'Review', 'Make the video', 'Approve & share'];

const GOALS: [string, string][] = [['conversions', 'Buy or sign up'], ['awareness', 'Get to know us'], ['education', 'Understand how it works'],
  ['launch', 'Hear about something new'], ['engagement', 'Comment, share, follow'], ['retention', 'Come back and use it more']];
const LENGTHS: [string, string, number][] = [['flex', 'Let the story decide', 45], ['30', 'About 30 seconds', 30], ['60', 'About 1 minute', 60], ['90', 'About 1½ minutes', 90]];
const FORMATS: [string, string, string][] = [['short', 'Vertical 9:16', 'Reels, Shorts, TikTok'], ['landscape', 'Wide 16:9', 'YouTube, your website'], ['both', 'Both', 'each composed for its frame']];
const EDITABLE = ['DRAFT', 'STORYBOARD_READY', 'PREVIEW_READY', 'CHANGES_REQUESTED', 'FAILED'];
const JOB_STAGES: [string, string][] = [['PREPARING', 'Getting ready'], ['GENERATING_AUDIO', 'Recording the voice'], ['BUILDING_TIMELINE', 'Timing every scene'],
  ['RENDERING', 'Drawing the video'], ['POST_PROCESSING', 'Adding music and finishing'], ['QA', 'Checking quality']];
const fmtLen = (s?: number | null) => (s == null ? '—' : s < 60 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, '0')} s`);

function stepFor(p: Any): number {
  switch (p.state) {
    case 'DRAFT': return 2;
    case 'STORYBOARD_READY': case 'CHANGES_REQUESTED': return 3;
    case 'PREVIEW_READY': return p.preview_approved ? 4 : 3;
    case 'RENDERING': case 'FAILED': return 4;
    default: return 5;
  }
}

const StepHeader: React.FC<{current: number; reached: number; onPick?: (i: number) => void}> = ({current, reached, onPick}) => (
  <ol className="wsteps" aria-label="Steps">
    {STEPS.map((s, i) => {
      const st = i === current ? 'cur' : i <= reached ? 'done' : 'todo';
      const can = onPick && i <= reached && i !== current;
      return (
        <li key={s} className={`wstep ${st}`} aria-current={i === current ? 'step' : undefined}>
          <button type="button" disabled={!can} onClick={() => can && onPick!(i)}>
            <span className="wstep-n">{i < reached && i !== current ? <Icon name="check" size={13} /> : i + 1}</span><span className="wstep-l">{s}</span>
          </button>
        </li>
      );
    })}
  </ol>
);

const Panel: React.FC<{title: React.ReactNode; sub?: React.ReactNode; children?: React.ReactNode; foot?: React.ReactNode}> = ({title, sub, children, foot}) => (
  <section className="wpanel">
    <header className="wpanel-h"><h2>{title}</h2>{sub && <p className="muted">{sub}</p>}</header>
    {children}
    {foot && <footer className="wpanel-f">{foot}</footer>}
  </section>
);

export const CreateWizard: React.FC<{nav: Nav; pid?: string}> = ({nav, pid}) =>
  pid ? <ProductionSteps key={pid} nav={nav} pid={pid} /> : <NewVideo nav={nav} />;

// ---- steps 1 and 2: a new production ------------------------------------------------------------------
const NewVideo: React.FC<{nav: Nav}> = ({nav}) => {
  const [step, setStep] = useState(0);
  const [brand, setBrand] = useState(nav.brand || (nav.brands.length === 1 ? nav.brands[0].id : ''));
  return (
    <div className="wiz">
      <StepHeader current={step} reached={brand ? 1 : 0} onPick={(i) => setStep(i)} />
      {step === 0 ? <PickWebsite nav={nav} brand={brand} onPick={(b) => { setBrand(b); setStep(1); }} />
        : <Promote nav={nav} brand={brand} onBack={() => setStep(0)} />}
    </div>
  );
};

const PickWebsite: React.FC<{nav: Nav; brand: string; onPick: (b: string) => void}> = ({nav, brand, onPick}) => (
  <Panel title="Which website is this video for?" sub="Prices, plans and claims in the video come only from this website's checked facts.">
    <div className="wchoices">
      {nav.brands.map((b) => (
        <button key={b.id} type="button" className={`wchoice ${brand === b.id ? 'on' : ''}`} onClick={() => onPick(b.id)}>
          <span className="wchoice-dot" style={b.brand ? {background: b.brand} : undefined} />
          <span className="wchoice-t">{b.name}</span>
          <span className="muted sm">{b.domain ?? 'no website address yet'}</span>
          {b.status === 'draft' && <Badge tone="warning">setup not finished</Badge>}
        </button>
      ))}
      <button type="button" className="wchoice wchoice-add" onClick={() => nav.go('brands')}>
        <span className="wchoice-plus"><Icon name="plus" size={18} /></span><span className="wchoice-t">Add a website</span>
        <span className="muted sm">We read your site and draft its facts for you to check</span>
      </button>
    </div>
  </Panel>
);

const Promote: React.FC<{nav: Nav; brand: string; onBack: () => void}> = ({nav, brand, onBack}) => {
  const b = nav.brands.find((x) => x.id === brand);
  const [f, setF] = useState<Record<string, string>>({goal: 'conversions', length: 'flex', format: 'short'});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({...f, [k]: e.target.value});
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const len = LENGTHS.find((l) => l[0] === f.length) ?? LENGTHS[0];
      const brief: Record<string, unknown> = {product: f.product, format: f.format === 'landscape' ? 'landscape' : 'short', duration_seconds: len[2],
        ...(len[0] === 'flex' ? {duration_flexible: true} : {}), ...(f.format === 'both' ? {formats: ['short', 'landscape']} : {})};
      for (const k of ['price', 'audience', 'goal', 'cta', 'tone', 'request']) if (f[k]?.trim()) brief[k] = f[k].trim();
      const p = await api.post('/api/productions', {brand, name: f.name?.trim() || undefined, brief});
      try { await api.post(`/api/productions/${p.id}/concepts`); } catch { /* step 3 offers the button again */ }
      nav.setPid(p.id);
      nav.go('create', p.id);
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  if (!b) return <Panel title="Pick a website first"><Button onClick={onBack}><Icon name="arrow-left" size={16} />Choose a website</Button></Panel>;
  return (
    <form onSubmit={submit}>
      <Panel title="What do you want to promote?" sub={<>For <b>{b.name}</b>. Only the first field is required; the rest makes the ideas sharper.</>}
        foot={<><Button type="button" variant="ghost" onClick={onBack}><Icon name="arrow-left" size={16} />Back</Button><span className="spacer" />
          <Button variant="primary" className="btn-lg" type="submit" busy={busy} disabled={!f.product?.trim()}>Get 3 ideas<Icon name="arrow-right" size={16} /></Button></>}>
        <div className="form-grid">
          <Field label="Product or offer" wide hint="The thing the video is about, in your words.">
            <input required autoFocus maxLength={120} value={f.product ?? ''} onChange={set('product')} placeholder="e.g. Fast WordPress hosting" /></Field>
          <Field label="Price (optional)" hint="Exactly as on your website. A price that is not in your checked facts is flagged for you to check.">
            <input maxLength={60} value={f.price ?? ''} onChange={set('price')} placeholder="e.g. ₹49/month" /></Field>
          <Field label="Who is it for?"><input maxLength={160} value={f.audience ?? ''} onChange={set('audience')} placeholder="e.g. small-business owners" /></Field>
          <Field label="After watching, viewers should…">
            <select value={f.goal} onChange={set('goal')}>{GOALS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field label="Closing line (call to action)"><input maxLength={60} value={f.cta ?? ''} onChange={set('cta')} placeholder={`e.g. Start at ${b.domain ?? 'yourwebsite.com'}`} /></Field>
          <Field label="Length" wide>
            <div className="seg seg-wrap">{LENGTHS.map(([k, l]) => <button type="button" key={k} className={f.length === k ? 'on' : ''} onClick={() => setF({...f, length: k})}>{l}</button>)}</div></Field>
          <Field label="Shape" wide>
            <div className="wformats">{FORMATS.map(([k, l, s]) => (
              <button type="button" key={k} className={`wformat ${f.format === k ? 'on' : ''}`} onClick={() => setF({...f, format: k})}>
                <span className={`wformat-ic ${k}`} aria-hidden /><span><b>{l}</b><span className="muted xs">{s}</span></span>
              </button>))}</div></Field>
        </div>
        <details className="wmore">
          <summary>More options</summary>
          <div className="form-grid mt">
            <Field label="Tone of voice"><input maxLength={120} value={f.tone ?? ''} onChange={set('tone')} placeholder="e.g. confident, warm, no hype" /></Field>
            <Field label="Video name" hint="Shown on your Home page; defaults to the product"><input maxLength={100} value={f.name ?? ''} onChange={set('name')} /></Field>
            <Field label="Anything the video must show or say?" wide>
              <textarea rows={3} maxLength={2000} value={f.request ?? ''} onChange={set('request')} placeholder="e.g. compare our price with the big hosts; show the one-click install" /></Field>
          </div>
        </details>
        <ErrorBox error={err} title="The video could not be started" />
      </Panel>
    </form>
  );
};

// ---- steps 3–6: an existing production ---------------------------------------------------------------------
const ProductionSteps: React.FC<{nav: Nav; pid: string}> = ({nav, pid}) => {
  const [fast, setFast] = useState(true);
  const prod = useApi<Any>(`/api/productions/${pid}`, fast ? 2500 : 10000);
  const p = prod.data;
  const [view, setView] = useState<number | null>(null);
  const running = (p?.tasks ?? []).some((t: Any) => t.status === 'running') || ['RENDERING', 'QA_COMPLETE', 'PUBLISHING'].includes(p?.state);
  useEffect(() => { setFast(running); }, [running]);
  const auto = p ? stepFor(p) : 2;
  useEffect(() => { setView(null); }, [auto]);           // a new state moves you to its step
  if (prod.error && !p) return <ErrorBox error={prod.error} title="This video could not be loaded" actions={{retry: () => void prod.reload()}} />;
  if (!p) return <div className="wiz"><StepHeader current={2} reached={2} /><div className="skeleton" /></div>;
  const step = view ?? auto;
  const reload = () => void prod.reload();
  const s = plainStatus({...p, posted: (p.publications ?? []).filter((x: Any) => x.status === 'PUBLISHED').map((x: Any) => x.platform)});
  return (
    <div className="wiz">
      <StepHeader current={step} reached={auto} onPick={(i) => setView(i === auto ? null : i)} />
      <div className="wstatus"><Badge tone={s.tone}>{s.label}</Badge><span className="muted sm">{p.name}</span>
        <span className="spacer" /><button className="linkbtn sm" onClick={() => nav.go('home')}>All videos</button></div>
      {step <= 1 ? <BriefSummary nav={nav} p={p} />
        : step === 2 ? <PickIdea nav={nav} p={p} reload={reload} />
          : step === 3 ? <Review nav={nav} p={p} reload={reload} onNext={() => setView(null)} />
            : step === 4 ? <Make nav={nav} p={p} reload={reload} onNext={() => setView(null)} />
              : <ApproveShare nav={nav} p={p} reload={reload} />}
    </div>
  );
};

const BriefSummary: React.FC<{nav: Nav; p: Any}> = ({nav, p}) => {
  const b = nav.brands.find((x) => x.id === p.brand);
  const br = p.brief ?? {};
  const rows: [string, React.ReactNode][] = [['Website', b?.name ?? p.brand], ['Product', br.product], ['Price', br.price], ['Who it is for', br.audience],
    ['Viewers should', GOALS.find((g) => g[0] === br.goal)?.[1] ?? br.goal], ['Closing line', br.cta],
    ['Length', br.duration_flexible ? 'Let the story decide' : br.duration_seconds ? `About ${br.duration_seconds} seconds` : null],
    ['Shape', (br.formats ?? [br.format]).map((x: string) => (x === 'landscape' ? 'Wide 16:9' : 'Vertical 9:16')).join(' + ')]];
  return (
    <Panel title="What this video promotes" sub="To change these, start a new video: the ideas and storyboard were written for this brief."
      foot={<Button variant="primary" onClick={() => nav.go('create')}>Start a new video</Button>}>
      <dl className="kv wkv">{rows.filter(([, v]) => v).map(([k, v]) => <React.Fragment key={k}><dt>{k}</dt><dd>{v}</dd></React.Fragment>)}</dl>
    </Panel>
  );
};

const latestTask = (p: Any, kinds: string[]) => (p.tasks ?? []).find((t: Any) => kinds.includes(t.kind));
const taskError = (t: Any) => (t?.status === 'failed' ? Object.assign(new Error(t.error?.message ?? 'failed'), t.error) : null);

// ---- step 3: pick an idea ----------------------------------------------------------------------------------
const PickIdea: React.FC<{nav: Nav; p: Any; reload: () => void}> = ({nav, p, reload}) => {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [last, setLast] = useState<{kind: 'concepts' | 'storyboard'; id?: string}>({kind: 'concepts'});
  const res = p.concepts;
  const concepts: Any[] = res?.concepts ?? [];
  const t = latestTask(p, ['concepts', 'storyboard']);
  const thinking = t?.status === 'running' ? t.kind : busy === 'concepts' ? 'concepts' : busy ? 'storyboard' : null;
  const failed = !busy && !err ? taskError(t) : null;
  const editable = EDITABLE.includes(p.state);
  const needs: Any[] = res?.brief_claims?.needs_review ?? [];
  const ideas = async () => {
    setBusy('concepts'); setErr(null); setLast({kind: 'concepts'});
    try { await runTask(`/api/productions/${p.id}/concepts`); toast('success', 'Three ideas are ready'); } catch (x) { setErr(x); } finally { setBusy(null); reload(); }
  };
  const pick = async (c: Any) => {
    if (p.storyboard && !window.confirm('Use this idea instead? It replaces the current storyboard, including any edits.')) return;
    setBusy(c.id); setErr(null); setLast({kind: 'storyboard', id: c.id});
    try { await runTask(`/api/productions/${p.id}/select`, {conceptId: c.id}); toast('success', 'Storyboard ready: build a preview next'); } catch (x) { setErr(x); } finally { setBusy(null); reload(); }
  };
  return (
    <Panel title="Pick an idea" sub="Three different ways to tell the story. Every price and claim is checked against your website's facts."
      foot={<><Button variant="ghost" onClick={() => nav.go('storyboard')}>Write my own storyboard instead</Button><span className="spacer" />
        {concepts.length > 0 && editable && <Button busy={busy === 'concepts'} disabled={!!thinking} onClick={ideas}>Get 3 new ideas</Button>}</>}>
      {thinking && (
        <div className="wwait"><Spinner /><div><b>{thinking === 'concepts' ? 'Writing three ideas…' : 'Building the storyboard from your idea…'}</b>
          <div className="muted sm">{thinking === 'concepts' ? 'Usually about a minute. It waits its turn if a video is being made.' : 'Scenes, words and visuals: usually under a minute.'}</div></div></div>
      )}
      <ErrorBox error={err ?? failed} title={(err ? last.kind : t?.kind) === 'storyboard' ? 'The storyboard could not be built' : 'The ideas could not be written'}
        actions={{retry: () => { const id = err ? last.id : p.concept_id; void ((err ? last.kind : t?.kind) === 'storyboard' && id ? pick({id}) : ideas()); }}} />
      {needs.length > 0 && (
        <Alert tone="warning" title="Some things in your brief are not in your website's checked facts">
          <ul className="wlist">{needs.map((c, i) => <li key={i}><b>{c.text}</b>{c.reason ? <span className="muted"> · {c.reason}</span> : null}</li>)}</ul>
          They will be flagged for you to check before the video can be approved.
        </Alert>
      )}
      {concepts.length === 0 && !thinking ? (
        <div className="wempty"><p>No ideas yet.</p><Button variant="primary" className="btn-lg" busy={busy === 'concepts'} disabled={!editable} onClick={ideas}>Get 3 ideas</Button></div>
      ) : (
        <div className="widea-grid">
          {concepts.map((c) => {
            const chosen = p.concept_id === c.id;
            const pc = c.pacing ?? {};
            const review = c.claims?.needs_review ?? 0;
            return (
              <article key={c.id} className={`widea ${chosen ? 'on' : ''}`}>
                <div className="widea-h"><h3>{c.name ?? c.title ?? c.id}</h3>
                  {chosen ? <Badge tone="success">Chosen</Badge> : res?.recommended === c.id ? <Badge tone="brand">Our pick</Badge> : null}</div>
                {c.hook && <blockquote className="widea-hook">“{c.hook}”</blockquote>}
                {c.logline && <p className="widea-log">{c.logline}</p>}
                <div className="widea-meta">
                  {pc.scene_count != null && <span>{pc.scene_count} scenes</span>}
                  {pc.est_seconds != null && <span>about {fmtLen(pc.est_seconds)}</span>}
                  {review > 0 && <span className="warn-t">{review} claim{review > 1 ? 's' : ''} to check</span>}
                </div>
                <Button variant={chosen ? 'secondary' : 'primary'} className="w100" busy={busy === c.id} disabled={!!thinking || !editable}
                  onClick={() => void pick(c)}>{chosen && p.storyboard ? 'Rebuild from this idea' : 'Use this idea'}</Button>
              </article>
            );
          })}
        </div>
      )}
      {!editable && <p className="muted sm">The idea can't be changed now: the video is already {plainStatus(p).label.toLowerCase()}.</p>}
    </Panel>
  );
};

// ---- step 4: review the preview -------------------------------------------------------------------------------
const GATE_WORDS: Record<string, [string, 'success' | 'warning' | 'danger']> = {
  PASS: ['Automatic checks passed', 'success'], WARN: ['Automatic checks passed, with notes', 'warning'], FAIL: ['Needs fixing before the video can be made', 'danger']};

const Review: React.FC<{nav: Nav; p: Any; reload: () => void; onNext: () => void}> = ({nav, p, reload, onNext}) => {
  const [reviewer, setReviewer] = useLocal('studio.reviewer', '');
  const [note, setNote] = useState('');
  const [looked, setLooked] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [last, setLast] = useState<'preview' | 'approve'>('preview');
  const sb = p.storyboard;
  const scenes: Any[] = sb?.scenes ?? [];
  const est = estSeconds(scenes.map((s) => s.narration ?? '').join(' '));
  const g = p.gate;
  const sheet = p.files?.['preview/contact-sheet.jpg'];
  const t = latestTask(p, ['preview']);
  const building = busy === 'preview' || t?.status === 'running';
  const stale = g && !g.current;
  const preview = async () => {
    setBusy('preview'); setErr(null); setLast('preview');
    try { await runTask(`/api/productions/${p.id}/preview`); toast('success', 'Preview ready: look at every scene'); } catch (x) { setErr(x); } finally { setBusy(null); reload(); }
  };
  const approve = async () => {
    setBusy('approve'); setErr(null); setLast('approve');
    try { await api.post(`/api/productions/${p.id}/approve-preview`, {reviewer: reviewer.trim(), note}); toast('success', 'Preview approved: the video can be made now'); }
    catch (x) { setErr(x); } finally { setBusy(null); reload(); }
  };
  if (!sb) return <Panel title="No storyboard yet" sub="Pick an idea first, or write the storyboard yourself."><Button onClick={() => nav.go('storyboard')}>Open the storyboard editor</Button></Panel>;
  const gw = g ? GATE_WORDS[g.status] ?? [g.status, 'warning'] : null;
  const issues: Any[] = (g?.checks ?? []).filter((c: Any) => c.status !== 'PASS');
  return (
    <Panel title="Review the storyboard" sub={<>{sb.title ? <b>{sb.title}</b> : null} {scenes.length} scenes · about {fmtLen(est)} of narration.
      Look at one still per scene before the real video is made.</>}
      foot={<><Button variant="ghost" onClick={() => nav.go('storyboard')}>Edit words and scenes · watch frame by frame</Button><span className="spacer" />
        <Button variant={!g || stale ? 'primary' : 'secondary'} busy={building} disabled={!!busy || !EDITABLE.includes(p.state)} onClick={preview}>{g ? 'Build the preview again' : 'Build preview'}</Button></>}>
      {p.state === 'CHANGES_REQUESTED' && <Alert tone="warning" title="Changes were requested">Edit the storyboard, then build a new preview and approve it again.</Alert>}
      {building && <div className="wwait"><Spinner /><div><b>Building the preview…</b><div className="muted sm">One still per scene, no voice yet. Usually under a minute.</div></div></div>}
      {stale && !building && <Alert tone="warning">The storyboard changed after this preview. Build the preview again before approving.</Alert>}
      <ErrorBox error={err ?? (!busy ? taskError(t) : null)} title="That didn't work" onDismiss={err ? () => setErr(null) : undefined}
        actions={{'rebuild-preview': () => void preview(), retry: () => void (last === 'approve' ? approve() : preview())}} />
      {!g && !building && <div className="wempty"><p>No preview yet. It takes about a minute and shows every scene as a still.</p></div>}
      {g && (
        <div className="wreview">
          <div className="wreview-img">{sheet ? <img src={fileUrl(sheet, p.updated_at)} alt="One still per scene" /> : <div className="wempty">No preview image.</div>}</div>
          <div className="wreview-side">
            {gw && <div className={`wgate wgate-${gw[1]}`}><b>{gw[0]}</b>
              {issues.length > 0 && <ul className="wlist">{issues.slice(0, 6).map((c) => <li key={c.id}>{c.detail || c.id}</li>)}</ul>}</div>}
            {p.preview_approved ? (
              <Alert tone="success" title="You approved this preview">
                <div className="mb">The video can be made now. Any storyboard change needs a new review.</div>
                {p.state === 'PREVIEW_READY' && <Button variant="primary" onClick={onNext}>Next: make the video<Icon name="arrow-right" size={16} /></Button>}</Alert>
            ) : (
              <div className="wapprove">
                <h3>Approve the preview</h3>
                <p className="muted sm">Approving lets the Studio make the full video. It is not the final approval and posts nothing.</p>
                <label className="check wcheck"><input type="checkbox" checked={looked} onChange={(e) => setLooked(e.target.checked)} />
                  I looked at every scene: the words, numbers and prices are right</label>
                <Field label="Your name"><input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Full name" autoComplete="name" /></Field>
                <Field label="Note (optional)"><input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What you checked" /></Field>
                <Button variant="primary" className="w100" busy={busy === 'approve'} disabled={!!busy || !looked || !reviewer.trim() || stale || g.status === 'FAIL'}
                  onClick={approve}>Approve preview</Button>
                {g.status === 'FAIL' && <p className="muted xs">Fix the storyboard and build the preview again first.</p>}
              </div>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
};

// ---- step 5: make the video ------------------------------------------------------------------------------------
const Make: React.FC<{nav: Nav; p: Any; reload: () => void; onNext: () => void}> = ({nav, p, reload, onNext}) => {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const j = p.job;
  const rendering = p.state === 'RENDERING' || p.state === 'QA_COMPLETE';
  const canStart = ['PREVIEW_READY', 'STORYBOARD_READY', 'FAILED'].includes(p.state) && p.preview_approved;
  const done: Record<string, string> = Object.fromEntries((j?.stages ?? []).map((s: Any) => [s.stage, String(s.status).toLowerCase()]));
  const start = async () => {
    setBusy(true); setErr(null);
    try { await runTask(`/api/productions/${p.id}/render`); toast('success', 'The video is being made'); } catch (x) { setErr(x); } finally { setBusy(false); reload(); }
  };
  const stop = async () => {
    if (!j || !window.confirm('Stop making this video? You can start again later.')) return;
    try { await api.post(`/api/jobs/${j.id}/cancel`); toast('info', 'Stopping…'); reload(); } catch (x) { setErr(x); }
  };
  const finished = stepFor(p) >= 5;
  const showJob = j && (rendering || p.state === 'FAILED' || finished);
  return (
    <Panel title="Make the video" sub="The Studio records the voice, draws every frame, adds music and checks the result. This takes a few minutes; you can leave this page."
      foot={<>{j && <Button variant="ghost" onClick={() => nav.go('monitor', j.id)}>Technical details</Button>}<span className="spacer" />
        {rendering && j && <Button variant="danger" onClick={stop}>Stop</Button>}
        {canStart && <Button variant="primary" className="btn-lg" busy={busy} onClick={start}>{p.state === 'FAILED' ? 'Try again' : 'Make the video'}</Button>}
        {stepFor(p) >= 5 && <Button variant="primary" onClick={onNext}>Next: watch and approve<Icon name="arrow-right" size={16} /></Button>}</>}>
      <ErrorBox error={err} title="The video could not be started" onDismiss={() => setErr(null)} actions={{retry: () => void start()}} />
      {!showJob && canStart && <div className="wempty"><p>Preview approved. Ready when you are.</p><p className="muted sm">Close other heavy apps if your Mac feels slow: making a video needs a lot of memory.</p></div>}
      {!showJob && !canStart && !rendering && p.state !== 'FAILED' && stepFor(p) < 4 && <Alert tone="info">Approve the preview first (step 4).</Alert>}
      {showJob && (
        <div className="wmake">
          <div className="row between"><b>{p.state === 'FAILED' ? 'It stopped' : finished ? 'Finished' : p.state === 'QA_COMPLETE' ? 'Checking quality…' : (JOB_STAGES.find((s) => s[0] === j.stage)?.[1] ?? 'Waiting for its turn') + '…'}</b>
            <span className="muted">{Math.round((finished ? 1 : j.progress ?? 0) * 100)}%</span></div>
          <Progress value={finished ? 1 : j.progress ?? 0} tone={p.state === 'FAILED' ? 'danger' : finished ? 'success' : 'brand'} />
          <ol className="wstages">
            {JOB_STAGES.map(([k, l]) => {
              const st = done[k] ?? (j.stage === k && rendering ? 'running' : 'pending');
              return <li key={k} className={`wst ${st}`}><span className="wst-ic" aria-hidden>{st === 'done' ? <Icon name="check" size={12} /> : st === 'failed' ? '!' : ''}</span>{l}</li>;
            })}
          </ol>
          {p.state === 'FAILED' && (
            <Alert tone="danger" title="Something went wrong while making the video">
              <div>{j.error?.message ?? j.message ?? 'The render did not finish.'}</div>
              <div className="muted sm mt-s">Try again; if it fails twice, open Technical details or Setup.</div>
            </Alert>
          )}
        </div>
      )}
    </Panel>
  );
};

// ---- step 6: approve and share -------------------------------------------------------------------------------------
const ApproveShare: React.FC<{nav: Nav; p: Any; reload: () => void}> = ({nav, p, reload}) => {
  const outs = useApi<Any>(`/api/productions/${p.id}/outputs`);
  const [reviewer, setReviewer] = useLocal('studio.reviewer', '');
  const [note, setNote] = useState('');
  const [watched, setWatched] = useState(false);
  const [fmt, setFmt] = useState(0);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const reloadOuts = outs.reload;
  useEffect(() => { void reloadOuts(); }, [p.state, reloadOuts]);
  const o = outs.data;
  const act = async (name: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(name); setErr(null);
    try { await fn(); toast('success', ok); } catch (x) { setErr(x); } finally { setBusy(null); reload(); void outs.reload(); }
  };
  const manifest = p.approval_manifest;
  const open: Any[] = (p.flags ?? []).filter((f: Any) => f.status === 'open');
  const blocking = open.filter((f) => f.severity === 'blocking');
  const advisory = open.filter((f) => f.severity !== 'blocking');
  const approved = ['APPROVED', 'PUBLISHING', 'PUBLISHED'].includes(p.state) && p.approval_valid;
  const videos: Any[] = o?.videos ?? [];
  const bust = o?.job?.updated_at;

  const shown = videos[Math.min(fmt, Math.max(0, videos.length - 1))];
  const VideoBox = (
    <div className="wvideos">
      {videos.length > 1 && <div className="wvideo-tabs" role="tablist" aria-label="Shape">{videos.map((v, i) => (
        <button key={v.path} role="tab" aria-selected={v === shown} className={`tab ${v === shown ? 'on' : ''}`} onClick={() => setFmt(i)}>
          {v.format === 'landscape' ? 'Wide 16:9' : 'Vertical 9:16'}</button>))}</div>}
      {!o ? <div className="skeleton" /> : !shown ? <div className="wempty">No finished video yet.</div> : (
        <video key={shown.path} className={`player ${shown.format === 'short' ? 'portrait sm' : ''}`} controls preload="metadata" src={fileUrl(shown.play ?? shown.path, bust)} />
      )}
    </div>
  );

  if (p.state === 'REJECTED' || p.state === 'CANCELLED') {
    return (
      <Panel title={p.state === 'REJECTED' ? 'This video was not approved' : 'This video was cancelled'} sub="You can start a new one from the same idea any time."
        foot={<><Button variant="ghost" onClick={() => nav.go('publish')}>See the decision history</Button><span className="spacer" /><Button variant="primary" onClick={() => nav.go('create')}>Create a new video</Button></>}>
        {VideoBox}
      </Panel>
    );
  }

  if (!approved) {
    const needPackage = !manifest && ['QA_COMPLETE', 'AWAITING_APPROVAL'].includes(p.state);
    return (
      <Panel title="Watch it, then approve" sub="Watch the whole video with sound on. Approving does not post anything: you share it yourself in the next step."
        foot={<><Button variant="ghost" onClick={() => nav.go('qa')}>Quality report</Button><span className="spacer" /></>}>
        <ErrorBox error={err} onDismiss={() => setErr(null)} />
        <div className="wshare">
          {VideoBox}
          <div className="wshare-side">
            {o?.voiceover && <div className="mb"><div className="field-l">The voice on its own (listen to how names are said)</div><audio controls preload="none" src={fileUrl(o.voiceover, bust)} className="w100" /></div>}
            {needPackage && <Alert tone="info" title="Almost there">
              <div className="mb">The files to approve need to be gathered first.</div>
              <Button variant="primary" busy={busy === 'pkg'} onClick={() => act('pkg', () => api.post(`/api/productions/${p.id}/package`), 'Ready for your approval')}>Prepare for approval</Button></Alert>}
            {(blocking.length > 0 || p.state === 'AWAITING_APPROVAL') && (
              <Field label="Your name"><input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Full name" autoComplete="name" /></Field>
            )}
            {blocking.length > 0 && (
              <div className="wchecks">
                <h3>Check these yourself ({blocking.length})</h3>
                <p className="muted xs">Each needs your name and a short note on what you checked.</p>
                {blocking.map((f) => (
                  <div key={f.id} className="wcheck-i">
                    <div>{f.message}</div>
                    <div className="flag-r mt-s">
                      <input placeholder="What you checked" value={notes[f.id] ?? ''} onChange={(e) => setNotes({...notes, [f.id]: e.target.value})} aria-label="What you checked" />
                      <Button busy={busy === `f${f.id}`} disabled={!reviewer.trim() || !(notes[f.id] ?? '').trim() || !!busy}
                        onClick={() => act(`f${f.id}`, () => api.post(`/api/productions/${p.id}/flags/${f.id}/resolve`, {reviewer: reviewer.trim(), note: notes[f.id]}), 'Marked as checked')}>Checked</Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {advisory.length > 0 && <details className="mt"><summary>{advisory.length} other note{advisory.length > 1 ? 's' : ''} (optional)</summary>
              <ul className="wlist">{advisory.map((f) => <li key={f.id}>{f.message}</li>)}</ul></details>}
            {p.state === 'AWAITING_APPROVAL' && (
              <div className="wapprove mt">
                <label className="check wcheck"><input type="checkbox" checked={watched} onChange={(e) => setWatched(e.target.checked)} />
                  I watched the whole video and listened to the voice</label>
                <Field label="Note" hint="Optional to approve; required to ask for changes"><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
                <Button variant="success" className="w100 btn-lg" busy={busy === 'approve'} disabled={!!busy || !watched || !reviewer.trim() || blocking.length > 0 || !manifest}
                  title={blocking.length ? 'Check the items above first' : ''}
                  onClick={() => act('approve', () => api.post(`/api/productions/${p.id}/approve`, {reviewer: reviewer.trim(), note, packageHash: manifest?.package_hash}), 'Approved. Nothing has been posted.')}>Approve the video</Button>
                <Button variant="ghost" className="w100" busy={busy === 'changes'} disabled={!!busy || !reviewer.trim() || !note.trim()}
                  onClick={() => act('changes', () => api.post(`/api/productions/${p.id}/decision`, {decision: 'CHANGES_REQUESTED', reviewer: reviewer.trim(), note}), 'Changes requested')}>Ask for changes</Button>
                {blocking.length > 0 && <p className="muted xs">Check the items above before approving.</p>}
              </div>
            )}
          </div>
        </div>
      </Panel>
    );
  }

  const pub = o?.publishing ?? {};
  const posted: Any[] = (p.publications ?? []).filter((x: Any) => x.status === 'PUBLISHED');
  const copy = (s: string) => { void navigator.clipboard?.writeText(s).then(() => toast('success', 'Copied'), () => toast('warning', 'Copy failed: select the text instead')); };
  return (
    <Panel title="Your video is ready" sub="Download it and post it wherever you like. Then tell the Studio where it went, so your Home page shows it."
      foot={<><Button variant="ghost" onClick={() => nav.go('publish')}>Upload to YouTube or export a package</Button><span className="spacer" />
        <Button onClick={() => nav.go('home')}>Back to Home</Button></>}>
      <div className="wshare">
        {VideoBox}
        <div className="wshare-side">
          <h3>Download</h3>
          <div className="wdl">
            {videos.map((v, i) => <a key={v.path} className={`btn ${i === 0 ? 'btn-primary' : ''}`} href={fileUrl(v.path)} download><Icon name="download" size={16} />{v.format === 'landscape' ? 'Wide video (16:9)' : 'Vertical video (9:16)'} <span className="muted-on">{v.mb} MB</span></a>)}
            {pub.thumbnail && <a className="btn" href={fileUrl(pub.thumbnail)} download><Icon name="download" size={16} />Cover image</a>}
            {o?.captions_path && <a className="btn" href={fileUrl(o.captions_path)} download><Icon name="download" size={16} />Captions (.srt)</a>}
          </div>
          {(pub.title || pub.description) && (
            <div className="wcopy mt">
              {pub.title && <div className="wcopy-i"><div className="field-l">Title</div><div className="wcopy-t">{pub.title}</div><Button variant="ghost" onClick={() => copy(pub.title)}>Copy</Button></div>}
              {pub.description && <div className="wcopy-i"><div className="field-l">Description</div><div className="wcopy-t pre-wrap">{pub.description}{(pub.hashtags ?? []).length ? `\n\n${pub.hashtags.join(' ')}` : ''}</div>
                <Button variant="ghost" onClick={() => copy(`${pub.description}${(pub.hashtags ?? []).length ? `\n\n${pub.hashtags.join(' ')}` : ''}`)}>Copy</Button></div>}
            </div>
          )}
          <PostedForm p={p} posted={posted} reviewer={reviewer} setReviewer={setReviewer} onDone={reload} />
        </div>
      </div>
    </Panel>
  );
};

const PostedForm: React.FC<{p: Any; posted: Any[]; reviewer: string; setReviewer: (v: string) => void; onDone: () => void}> = ({p, posted, reviewer, setReviewer, onDone}) => {
  const [platform, setPlatform] = useState('linkedin');
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api.post(`/api/productions/${p.id}/mark-published`, {platform, url: url.trim(), actor: reviewer.trim(), confirm: true});
      toast('success', `Recorded: posted on ${platformName(r.platform ?? platform)}`); setUrl(''); onDone();
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <div className="wposted mt">
      <h3>I posted it on…</h3>
      {posted.length > 0 && <ul className="wlist wlist-plain">{posted.map((x) => <li key={x.id} className="wposted-i"><PlatformLogo platform={x.platform} size={16} /><b>{platformName(x.platform)}</b>{' '}
        {x.remote_id?.startsWith('https://') ? <a href={x.remote_id} target="_blank" rel="noreferrer">open post ↗</a> : <span className="muted">{x.remote_id}</span>}</li>)}</ul>}
      <p className="muted xs">Records a post you made yourself. Nothing is uploaded.</p>
      <div className="form-grid">
        <Field label="Where" wide><div className="wplat" role="group" aria-label="Where you posted it">
          {Object.entries(PLATFORM_NAMES).filter(([k]) => k !== 'export').map(([k, l]) => (
            <button type="button" key={k} className={platform === k ? 'on' : ''} aria-pressed={platform === k} onClick={() => setPlatform(k)}>
              <PlatformLogo platform={k} size={18} />{k === 'website' ? <><Icon name="globe" size={18} />Your website</> : l}</button>))}</div></Field>
        <Field label="Your name"><input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Full name" /></Field>
        <Field label="Link to your post" wide><input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" /></Field>
      </div>
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
      <Button className="mt-s" busy={busy} disabled={!reviewer.trim() || !url.trim().startsWith('https://')} onClick={submit}>Record the post</Button>
    </div>
  );
};
