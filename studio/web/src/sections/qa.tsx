import React, {useState} from 'react';
import {Any, api, fileUrl} from '../api';
import {Alert, Badge, Button, Card, Empty, ErrorBox, KV, Pre, State, Table, toast, useApi, useLocal} from '../ui';
import type {Nav} from '../app';

export const PreviewQA: React.FC<{nav: Nav; pid: string}> = ({nav, pid}) => {
  const prod = useApi<Any>(`/api/productions/${pid}`, 8000);
  const outs = useApi<Any>(`/api/productions/${pid}/outputs`);
  const [fmt, setFmt] = useState(0);
  const p = prod.data, o = outs.data;
  if (prod.error) return <ErrorBox error={prod.error} />;
  if (!p || !o) return <div className="skeleton" />;
  if (!o.job) {
    return p.gate ? <PreviewGate pid={pid} p={p} onChange={() => void prod.reload()} /> : (
      <Empty>No preview or render yet for this production ({p.state}). Build a preview from the <a href="#/storyboard">Storyboard Editor</a>:
        it renders one still per scene and runs the quality gate before any full render.</Empty>);
  }
  const qa = o.reports['qa-report'];
  const checks: Any[] = (qa?.formats ?? []).flatMap((f: Any) => (f.checks ?? []).map((c: Any) => ({...c, format: f.format})));
  const by = (s: string) => checks.filter((c) => c.status === s);
  const flags: Any[] = p.flags ?? [];
  const openBlocking = flags.filter((f) => f.status === 'open' && f.severity === 'blocking');
  const video = o.videos[fmt] ?? o.videos[0];
  const bust = o.job.updated_at;
  return (
    <div className="grid">
      <div className="qa-sum span-12">
        <div className="qa-col qa-pass"><div className="qa-n">{by('PASS').length}</div><div className="qa-l">Automated PASS</div></div>
        <div className="qa-col qa-warn"><div className="qa-n">{by('WARN').length}</div><div className="qa-l">Automated WARNING</div></div>
        <div className="qa-col qa-human"><div className="qa-n">{openBlocking.length}</div><div className="qa-l">Human review required</div></div>
        <div className="qa-col qa-fail"><div className="qa-n">{by('FAIL').length}</div><div className="qa-l">FAIL</div></div>
      </div>
      <Alert tone="info">QA PASS is necessary, not sufficient: watch the video end to end and listen to the voiceover (brand-name pronunciation cannot be checked automatically).</Alert>

      <Card title="Final video" className="span-7" actions={<>{o.videos.map((v: Any, i: number) => <button key={v.path} className={`tab ${i === fmt ? 'on' : ''}`} onClick={() => setFmt(i)}>{v.format}</button>)}<State s={o.job.qa_status} /></>}>
        {video ? (
          <>
            <video key={video.path} className={`player ${video.format === 'short' ? 'portrait' : ''}`} controls preload="metadata" src={fileUrl(video.path, bust)} />
            <div className="muted sm mt-s">{video.path} · {video.mb} MB</div>
          </>
        ) : <Empty>No final MP4 in this job.</Empty>}
        {o.voiceover && <div className="mt"><div className="field-l">Voiceover (listen for pronunciation)</div><audio controls preload="none" src={fileUrl(o.voiceover, bust)} className="w100" /></div>}
      </Card>

      <Card title="Review flags" className="span-5" actions={<span className="muted sm">{openBlocking.length} blocking open</span>}>
        <Flags pid={pid} flags={flags} onChange={() => void prod.reload()} />
      </Card>

      <Card title="Contact sheet" className="span-12">
        {o.contact_sheets.length === 0 ? <Empty>No contact sheet.</Empty> : o.contact_sheets.map((c: string) => <img key={c} className="contact" src={fileUrl(c, bust)} alt="Contact sheet" />)}
      </Card>

      <Card title="QA checks" className="span-7" actions={<a href={fileUrl(`${o.job.output_dir}/reports/QA_REPORT.md`)} target="_blank" rel="noreferrer">QA_REPORT.md</a>}>
        {checks.length === 0 ? <Empty>No QA report.</Empty> : (['FAIL', 'WARN', 'PASS'] as const).map((s) => by(s).length > 0 && (
          <details key={s} open={s !== 'PASS'} className="qa-group">
            <summary><State s={s} /> {by(s).length} check{by(s).length > 1 ? 's' : ''}</summary>
            <Table cols={['Check', 'Format', 'Category', 'Detail']}>
              {by(s).map((c, i) => <tr key={i}><td className="mono sm">{c.id}{c.critical ? <Badge tone="neutral">critical</Badge> : null}</td><td>{c.format}</td><td className="muted">{c.category}</td><td className="sm">{c.detail}</td></tr>)}
            </Table>
          </details>
        ))}
      </Card>

      <Card title="Audio" className="span-5"><AudioReport r={o.reports['audio-report']} /></Card>

      <Card title="Branding QA" className="span-6"><GenericReport r={o.reports['branding-report']} name="reports/branding-report.json" /></Card>
      <Card title="Visual QA" className="span-6"><GenericReport r={o.reports['visual-qa']} name="reports/visual-qa.json" /></Card>

      <Card title="Captions (SRT)" className="span-6" actions={o.captions_path && <a href={fileUrl(o.captions_path)} target="_blank" rel="noreferrer">Open file</a>}>
        {o.captions_srt ? <Pre max={300}>{o.captions_srt}</Pre> : <Empty>No captions.</Empty>}
      </Card>
      <Card title="Claims & pronunciation" className="span-6">
        {o.reports['claims-report'] ? (
          <ul className="flaglist">{(o.reports['claims-report'].claims ?? []).map((c: Any, i: number) => <li key={i}><State s={c.status} /> {c.text} {c.reason && <span className="muted">— {c.reason}</span>}</li>)}</ul>
        ) : <p className="muted sm">No claims report (manual storyboard or creative engine not used): every price and claim needs a human check against the brand's website.</p>}
        {o.pronunciation_md && <Pre max={220}>{o.pronunciation_md}</Pre>}
      </Card>
      <div className="span-12 row end"><Button variant="primary" onClick={() => nav.go('publish')}>Continue to Publishing Center →</Button></div>
    </div>
  );
};

export const Flags: React.FC<{pid: string; flags: Any[]; onChange: () => void}> = ({pid, flags, onChange}) => {
  const [reviewer, setReviewer] = useLocal('studio.reviewer', '');
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [err, setErr] = useState<unknown>(null);
  if (flags.length === 0) return <Empty>No review flags (they are created when the render job finishes).</Empty>;
  const resolve = async (id: number) => {
    setBusy(id); setErr(null);
    try { await api.post(`/api/productions/${pid}/flags/${id}/resolve`, {reviewer, note: notes[id] ?? ''}); toast('success', `Flag #${id} resolved`); onChange(); } catch (e) { setErr(e); } finally { setBusy(null); }
  };
  const sorted = [...flags].sort((a, b) => (a.status === b.status ? 0 : a.status === 'open' ? -1 : 1) || (a.severity === b.severity ? 0 : a.severity === 'blocking' ? -1 : 1));
  return (
    <div>
      <label className="field"><span className="field-l">Reviewer name (required to resolve)</span><input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Your name" /></label>
      <ErrorBox error={err} />
      <ul className="flags">
        {sorted.map((f) => (
          <li key={f.id} className={`flag fl-${f.status} fl-${f.severity}`}>
            <div className="flag-h"><Badge tone={f.severity === 'blocking' ? 'danger' : 'warning'}>{f.severity}</Badge><code>{f.kind}</code><span className="muted xs">#{f.id} · {f.source}</span>
              {f.status === 'resolved' && <Badge tone="success">resolved</Badge>}</div>
            <div className="flag-m">{f.message}</div>
            {f.status === 'resolved' ? <div className="muted xs">by {f.resolved_by}: {f.resolution_note}</div> : (
              <div className="flag-r">
                <input placeholder="Resolution note (required)" value={notes[f.id] ?? ''} onChange={(e) => setNotes({...notes, [f.id]: e.target.value})} aria-label={`Note for flag ${f.id}`} />
                <Button variant="secondary" busy={busy === f.id} disabled={!reviewer.trim() || !(notes[f.id] ?? '').trim()} onClick={() => resolve(f.id)}>Resolve</Button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
};

const AudioReport: React.FC<{r: Any}> = ({r}) => {
  if (!r || !r.mix) return <Empty>No audio report.</Empty>;
  const s = r.settings ?? {};
  const lufsOk = s.lufs == null || Math.abs(r.mix.integrated_lufs - s.lufs) <= 1;
  const tpOk = s.true_peak == null || r.mix.true_peak_dbtp <= s.true_peak + 0.2;
  return (
    <KV rows={[
      ['Integrated loudness', <span className={lufsOk ? 'ok-t' : 'warn-t'}>{r.mix.integrated_lufs} LUFS {s.lufs != null && <span className="muted">(target {s.lufs})</span>}</span>],
      ['True peak', <span className={tpOk ? 'ok-t' : 'warn-t'}>{r.mix.true_peak_dbtp} dBTP {s.true_peak != null && <span className="muted">(max {s.true_peak})</span>}</span>],
      ['Loudness range', `${r.mix.lra_lu} LU`],
      ['Clipped samples', r.mix.clipped_samples],
      ['Music ducking under voice', r.ducking ? `${r.ducking.under_voice_db} dB over ${r.ducking.windows} windows` : '—'],
      ['Ducking settings', `threshold ${s.duck_threshold} · ratio ${s.duck_ratio} · ${s.duck_attack_ms}/${s.duck_release_ms} ms`],
      ['Duration', `${r.mix.duration_s} s`],
      ['Sound effects', `${(r.sfx_events ?? []).length} events`],
    ]} />
  );
};

const GenericReport: React.FC<{r: Any; name: string}> = ({r, name}) => {
  if (!r) return <p className="muted sm">Not generated for this job (<code>{name}</code> does not exist yet).</p>;
  const checks: Any[] = r.checks ?? [];
  return (
    <div>
      {r.status && <div className="mb"><State s={r.status} /></div>}
      {checks.length ? (
        <Table cols={['Check', 'Status', 'Detail']}>
          {checks.map((c, i) => <tr key={i}><td className="mono sm">{c.id}</td><td><State s={c.status} /></td><td className="sm">{c.detail}</td></tr>)}
        </Table>
      ) : <Pre max={260}>{JSON.stringify(r, null, 1)}</Pre>}
    </div>
  );
};

/** Human review of the storyboard preview (required before the full render). Same rule as the CLI's approve-preview:
 * a named reviewer, a gate that is not FAIL, and approval bound to the exact storyboard. */
const PreviewGate: React.FC<{pid: string; p: Any; onChange: () => void}> = ({pid, p, onChange}) => {
  const [reviewer, setReviewer] = useLocal('studio.reviewer', '');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const g = p.gate;
  const sheet = p.files?.['preview/contact-sheet.jpg'];
  const blocked = g.status === 'FAIL' || !g.current;
  const approve = async () => {
    setBusy(true); setErr(null);
    try {
      await api.post(`/api/productions/${pid}/approve-preview`, {reviewer, note});
      toast('success', 'Preview approved: the full render is now allowed');
      onChange();
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <div className="grid">
      <Card title="Storyboard preview" className="span-8" actions={<span className="muted sm">one still per scene · estimated timing, no voice</span>}>
        {sheet ? <img className="contact-lg" src={fileUrl(sheet, p.updated_at)} alt="Storyboard preview contact sheet" /> : <Empty>No contact sheet.</Empty>}
      </Card>
      <Card title={<>Quality gate <State s={g.status} /></>} className="span-4">
        {!g.current && <Alert tone="warning">The storyboard changed after this preview. Build a new preview before approving.</Alert>}
        <div className="gate-list">
          {(g.checks ?? []).map((c: Any) => (
            <div key={c.id} className="gate-row"><State s={c.status} /><div><div className="mono sm">{c.id}</div><div className="muted sm">{c.detail}</div></div></div>
          ))}
        </div>
        {p.preview_approved ? (
          <Alert tone="success" title="Preview approved">The full render is allowed for this exact storyboard. Any storyboard change needs a new review.</Alert>
        ) : (
          <>
            <p className="sm muted">Look at every scene: does each one show something meaningful, do the visuals change with what is said,
              is every price and label real? Approving allows the expensive full render. It is not final approval.</p>
            <label className="field"><span className="field-l">Your name (reviewer)</span>
              <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Full name" /></label>
            <label className="field"><span className="field-l">Note (optional)</span>
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What you checked" /></label>
            {err ? <ErrorBox error={err} onDismiss={() => setErr(null)} /> : null}
            <Button variant="primary" busy={busy} disabled={blocked || !reviewer.trim()} onClick={approve}>Approve preview for rendering</Button>
            {g.status === 'FAIL' && <div className="muted sm mt-s">The gate failed: fix the storyboard and build a new preview first.</div>}
          </>
        )}
      </Card>
    </div>
  );
};
