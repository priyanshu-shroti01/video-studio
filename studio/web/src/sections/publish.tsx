import React, {useState} from 'react';
import {Any, api, fileUrl, waitTask} from '../api';
import {Alert, Badge, Button, Card, Dialog, Empty, ErrorBox, Field, KV, Pre, State, Table, fmtTime, toast, useApi, useLocal} from '../ui';
import type {Nav} from '../app';

export const PublishingCenter: React.FC<{nav: Nav; pid: string}> = ({nav, pid}) => {
  const prod = useApi<Any>(`/api/productions/${pid}`, 8000);
  const outs = useApi<Any>(`/api/productions/${pid}/outputs`);
  const [reviewer, setReviewer] = useLocal('studio.reviewer', '');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [dlg, setDlg] = useState<null | 'publish' | 'export'>(null);
  const p = prod.data, o = outs.data;
  if (prod.error) return <ErrorBox error={prod.error} />;
  if (!p || !o) return <div className="skeleton" />;

  const reload = async () => { await prod.reload(); await outs.reload(); };
  const act = async (name: string, fn: () => Promise<Any>, ok: string) => {
    setBusy(name); setErr(null);
    try { await fn(); toast('success', ok); await reload(); } catch (e) { setErr(e); } finally { setBusy(null); }
  };
  const manifest = p.approval_manifest;
  const openBlocking = (p.flags ?? []).filter((f: Any) => f.status === 'open' && f.severity === 'blocking');
  const approved = p.state === 'APPROVED' && p.approval_valid;
  const published = (p.publications ?? []).filter((x: Any) => x.status === 'PUBLISHED');
  const exportsDone = (p.publications ?? []).filter((x: Any) => x.status === 'EXPORTED');
  const pub = o.publishing ?? {};
  const meta = p.exports?.[p.exports.length - 1]?.platform_metadata;
  const credits: Any[] = o.credits?.assets ?? [];

  return (
    <div className="grid">
      <div className="span-12">
        {published.length === 0 ? (
          <div className="banner banner-safe"><span className="banner-dot" />Nothing has been published.
            <span className="muted"> Approval and export never upload anything; publishing needs a separate, typed confirmation.</span></div>
        ) : (
          <div className="banner banner-pub">Published: {published.map((x: Any) => `${x.platform} ${x.remote_id ?? ''} (${fmtTime(x.created_at)})`).join(' · ')}</div>
        )}
      </div>
      {!o.job && <div className="span-12"><Empty>No render yet. The Publishing Center fills in after the render job and QA finish.</Empty></div>}

      {o.job && <>
        <Card title="Final video & thumbnail" className="span-5">
          {o.videos.length ? o.videos.map((v: Any) => <video key={v.path} className={`player ${v.format === 'short' ? 'portrait sm' : ''}`} controls preload="metadata" src={fileUrl(v.path, o.job.updated_at)} />) : <Empty>No video.</Empty>}
          {pub.thumbnail && <div className="mt"><div className="field-l">Thumbnail</div><img className="thumb" src={fileUrl(pub.thumbnail, o.job.updated_at)} alt="Thumbnail" /></div>}
        </Card>
        <Card title="Metadata" className="span-7">
          <KV rows={[['Title', <b>{pub.title || '—'}</b>], ['Hashtags', (pub.hashtags ?? []).map((h: string) => <Badge key={h}>{h}</Badge>)]]} />
          <div className="field-l mt">Description</div><Pre max={200}>{pub.description || '—'}</Pre>
          <div className="field-l mt">Transcript</div><Pre max={160}>{o.transcript || '—'}</Pre>
        </Card>

        <Card title="Approval" className="span-7" actions={<State s={p.state} />}>
          <KV rows={[
            ['Package hash', manifest ? <code title={manifest.package_hash}>{manifest.package_hash.slice(0, 16)}…</code> : <span className="muted">not built</span>],
            ['Package built', manifest?.built_at ?? '—'],
            ['QA', <State s={o.job.qa_status} />],
            ['Blocking flags open', openBlocking.length ? <span className="warn-t">{openBlocking.length} — resolve them in <a href="#/qa">Preview &amp; QA</a></span> : <span className="ok-t">0</span>],
            ['Current approval', p.approval ? <span className={p.approval.valid ? 'ok-t' : 'warn-t'}>{p.approval.valid ? 'valid' : 'INVALID'} · by {p.approval.reviewer} · {fmtTime(p.approval.created_at)}</span> : <span className="muted">none</span>],
          ]} />
          {p.approval_error && <p className="muted sm">{p.approval_error}</p>}
          {manifest && <details className="mt"><summary>Approved files ({Object.keys(manifest.files).length})</summary>
            <Table cols={['File', 'sha256']}>{Object.entries(manifest.files).map(([k, v]: [string, Any]) => <tr key={k}><td className="mono sm">{k}</td><td className="mono xs">{v.sha256.slice(0, 24)}…</td></tr>)}</Table></details>}

          <div className="decide mt">
            <div className="form-grid">
              <Field label="Reviewer *"><input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Your name" /></Field>
              <Field label="Note" hint="Required to reject or request changes"><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
            </div>
            <ErrorBox error={err} onDismiss={() => setErr(null)} />
            <div className="row wrap">
              {['QA_COMPLETE', 'AWAITING_APPROVAL'].includes(p.state) && <Button busy={busy === 'pkg'} onClick={() => act('pkg', () => api.post(`/api/productions/${pid}/package`), 'Approval package rebuilt')}>{manifest ? 'Rebuild package' : 'Build package'}</Button>}
              <Button variant="success" busy={busy === 'approve'} disabled={p.state !== 'AWAITING_APPROVAL' || !reviewer.trim() || openBlocking.length > 0 || !manifest}
                title={openBlocking.length ? 'Resolve blocking flags first' : ''}
                onClick={() => act('approve', () => api.post(`/api/productions/${pid}/approve`, {reviewer, note, packageHash: manifest?.package_hash}), 'Approved — nothing has been published')}>Approve package</Button>
              <Button busy={busy === 'changes'} disabled={p.state !== 'AWAITING_APPROVAL' || !reviewer.trim() || !note.trim()}
                onClick={() => act('changes', () => api.post(`/api/productions/${pid}/decision`, {decision: 'CHANGES_REQUESTED', reviewer, note}), 'Changes requested')}>Request changes</Button>
              <Button variant="danger" busy={busy === 'reject'} disabled={p.state !== 'AWAITING_APPROVAL' || !reviewer.trim() || !note.trim()}
                onClick={() => { if (window.confirm('Reject this production? This is final.')) void act('reject', () => api.post(`/api/productions/${pid}/decision`, {decision: 'REJECTED', reviewer, note}), 'Rejected'); }}>Reject</Button>
            </div>
            {p.state === 'CHANGES_REQUESTED' && <Alert tone="warning">Changes requested. Edit the <a href="#/storyboard">storyboard</a> and render again.</Alert>}
          </div>
          {(p.approvals ?? []).length > 0 && <details className="mt"><summary>Decision history ({p.approvals.length})</summary>
            <Table cols={['When', 'Decision', 'Reviewer', 'Note', 'Package']}>{p.approvals.map((a: Any) => <tr key={a.id}><td className="sm">{fmtTime(a.created_at)}</td><td><State s={a.decision} />{a.invalidated_at && <Badge tone="danger">invalidated</Badge>}</td><td>{a.reviewer}</td><td className="sm">{a.note}{a.invalidated_reason && <div className="muted xs">{a.invalidated_reason}</div>}</td><td className="mono xs">{(a.package_hash || '').slice(0, 12)}</td></tr>)}</Table></details>}
        </Card>

        <Card title="Export & publish" className="span-5">
          <p className="muted sm">Both need an <b>APPROVED</b> production whose approval still matches every file. The publish gate re-hashes the video right before anything leaves the machine.</p>
          <div className="row wrap mt">
            <Button variant="primary" disabled={!approved} onClick={() => setDlg('export')}>Export package…</Button>
            <Button variant="danger" disabled={!approved} onClick={() => setDlg('publish')}>Publish…</Button>
          </div>
          {!approved && <p className="muted xs mt-s">Disabled until the production is approved{p.state === 'APPROVED' && !p.approval_valid ? ' (the approval was invalidated by a content change)' : ''}.</p>}
          {(['youtube', 'instagram'] as const).map((k) => o[k] && (
            <div key={k} className="mt"><b>{k === 'youtube' ? 'YouTube' : 'Instagram'}:</b> {o[k].configured ? <Badge tone="success">configured</Badge> : <Badge tone="warning">not configured</Badge>} <span className="muted sm">{o[k].reason}</span></div>))}
          {exportsDone.length > 0 && <div className="mt"><div className="field-l">Local exports (not published)</div>
            <ul className="hist">{p.exports.map((x: Any) => <li key={x.dir}><span className="mono xs">{x.dir}</span>{x.zip && <a href={fileUrl(x.zip)} download>zip</a>}</li>)}</ul></div>}
          {(p.publications ?? []).length > 0 && <Table cols={['Platform', 'Status', 'Remote id', 'When']} className="mt">{p.publications.map((x: Any) => <tr key={x.id}><td>{x.platform}</td><td><State s={x.status} /></td><td className="mono xs">{x.remote_id ?? '—'}</td><td className="sm">{fmtTime(x.created_at)}</td></tr>)}</Table>}
        </Card>

        <Card title={meta ? 'Platform metadata (exported)' : 'Platform metadata (preview)'} className="span-6" actions={!meta && <span className="muted xs">computed like the export; the exported file is authoritative</span>}>
          <Pre max={300}>{JSON.stringify(meta ?? o.platform_preview, null, 1)}</Pre>
        </Card>
        <Card title={`Credits (${credits.length} assets)`} className="span-6" actions={<span className="muted xs">assets/manifest.json</span>}>
          {credits.length === 0 ? <Empty>No asset manifest.</Empty> : (
            <div className="scroll-box"><Table cols={['Asset', 'Licence', 'Attribution']}>{credits.map((a: Any, i: number) => <tr key={i}><td className="mono xs break w-path">{a.path}</td><td className="wrap-badge"><Badge tone={!a.license || a.license === 'UNKNOWN' ? 'danger' : 'neutral'}>{a.license}</Badge></td><td className="xs">{a.attribution || '—'}</td></tr>)}</Table></div>
          )}
        </Card>
      </>}

      {dlg === 'export' && <ExportDialog open pid={pid} reviewer={reviewer} formats={o.videos?.map((v: Any) => v.format) ?? []} onClose={() => setDlg(null)} onDone={reload} />}
      {dlg === 'publish' && <PublishDialog open pid={pid} reviewer={reviewer} youtube={o.youtube} formats={o.videos?.map((v: Any) => v.format) ?? []} onClose={() => setDlg(null)} onDone={reload} nav={nav} />}
    </div>
  );
};

const ExportDialog: React.FC<{open: boolean; pid: string; reviewer: string; formats: string[]; onClose: () => void; onDone: () => void}> = ({open, pid, reviewer, formats, onClose, onDone}) => {
  const [actor, setActor] = useState(reviewer);
  const [fmt, setFmt] = useState(formats[0] ?? 'short');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const go = async () => {
    setBusy(true); setErr(null);
    try { const r = await api.post(`/api/productions/${pid}/export`, {confirm: true, actor, format: fmt}); toast('success', `Exported to ${r.dir} — nothing was uploaded`); onClose(); onDone(); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} title="Export ready-to-upload package" onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} disabled={!actor.trim()} onClick={go}>Export</Button></>}>
      <p>Copies the approved video, thumbnail, metadata, captions and credits into <code>export/</code> with checksums and a zip. <b>No network access; nothing is published.</b></p>
      <div className="form-grid">
        <Field label="Actor *"><input value={actor} onChange={(e) => setActor(e.target.value)} /></Field>
        <Field label="Format"><select value={fmt} onChange={(e) => setFmt(e.target.value)}>{(formats.length ? formats : ['short']).map((f) => <option key={f}>{f}</option>)}</select></Field>
      </div>
      <ErrorBox error={err} />
    </Dialog>
  );
};

const PublishDialog: React.FC<{open: boolean; pid: string; reviewer: string; youtube: Any; formats: string[]; onClose: () => void; onDone: () => void; nav: Nav}> =
  ({open, pid, reviewer, youtube, formats, onClose, onDone}) => {
    const [actor, setActor] = useState(reviewer);
    const [typed, setTyped] = useState('');
    const [platform, setPlatform] = useState(youtube?.configured ? 'youtube' : 'export');
    const [fmt, setFmt] = useState(formats[0] ?? 'short');
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState<unknown>(null);
    const ok = typed.trim() === pid && actor.trim().length > 0;
    const go = async () => {
      setBusy(true); setErr(null);
      try {
        const r = await api.post(`/api/productions/${pid}/publish`, {confirm: true, actor, typedProductionId: typed.trim(), platform, format: fmt});
        if (r.task) {
          const t = await waitTask(r.task.id, undefined, 2000);
          if (t.status === 'failed') throw Object.assign(new Error(t.error?.message), t.error);
          toast('success', `Published to ${platform}: ${t.result.remote_id}`);
        } else toast('success', `Exported (platform "export" never uploads): ${r.result.dir}`);
        setTyped(''); onClose(); onDone();
      } catch (e) { setErr(e); } finally { setBusy(false); }
    };
    return (
      <Dialog open={open} title="Publish — explicit confirmation" onClose={onClose} tone="danger"
        footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="danger" busy={busy} disabled={!ok} onClick={go}>{platform === 'youtube' ? 'Upload to YouTube' : 'Export'}</Button></>}>
        <Alert tone="warning" title="This sends the approved video to an external platform.">YouTube uploads use the official Data API and are created <b>private</b>, marked as containing synthetic media. Nothing else in the Studio ever publishes.</Alert>
        <div className="form-grid">
          <Field label="Platform"><select value={platform} onChange={(e) => setPlatform(e.target.value)}>
            <option value="youtube" disabled={!youtube?.configured}>YouTube{youtube?.configured ? '' : ' (not configured)'}</option><option value="export">Export package only (no upload)</option></select></Field>
          <Field label="Format"><select value={fmt} onChange={(e) => setFmt(e.target.value)}>{(formats.length ? formats : ['short']).map((f) => <option key={f}>{f}</option>)}</select></Field>
          <Field label="Actor *"><input value={actor} onChange={(e) => setActor(e.target.value)} /></Field>
          <Field label={`Type the production id to confirm: ${pid}`} wide><input value={typed} onChange={(e) => setTyped(e.target.value)} className="mono" placeholder={pid} autoComplete="off" spellCheck={false} /></Field>
        </div>
        {!youtube?.configured && <p className="muted sm">YouTube is not set up for this brand: {youtube?.reason}. Instagram Reels and other platforms: <code>video-pipeline social</code> (docs/SOCIAL_PUBLISHING.md).</p>}
        <ErrorBox error={err} />
      </Dialog>
    );
  };
