import React, {useState} from 'react';
import {Any, api} from '../api';
import {Alert, Button, Card, Dialog, Empty, ErrorBox, Field, State, Table, fmtAgo, fmtMb, toast, useApi, useLocal} from '../ui';
import type {Nav} from '../app';

const PLATFORMS = [['linkedin', 'LinkedIn'], ['youtube', 'YouTube'], ['instagram', 'Instagram'], ['facebook', 'Facebook'],
  ['x', 'X (Twitter)'], ['tiktok', 'TikTok'], ['website', 'My website']] as const;
const BUSY = ['RENDERING', 'PUBLISHING'];

/** Every production with the library actions: archive (moves files to output/_archive/, nothing is deleted),
 * restore from the archive (moves them back, never overwrites) and "I posted it on…" (records a post a person
 * made; nothing is uploaded). All need your name. */
export const Library: React.FC<{nav: Nav}> = ({nav}) => {
  const [tab, setTab] = useLocal('studio.library.tab', 'productions');
  const prods = useApi<Any[]>('/api/productions', 15000);
  const [archiving, setArchiving] = useState<Any>(null);
  const [posting, setPosting] = useState<Any>(null);
  const rows = (prods.data ?? []).filter((p) => !nav.brand || p.brand === nav.brand);
  const tabs = (
    <div className="seg">{[['productions', 'Productions'], ['archived', 'Archived']].map(([k, l]) => (
      <button type="button" key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>))}</div>
  );
  if (tab === 'archived') return <Archived nav={nav} tabs={tabs} onRestored={() => void prods.reload()} />;
  return (
    <div className="grid">
      <div className="span-12">{tabs}</div>
      <Card title="Productions" className="span-12" actions={<span className="muted sm">{rows.length} shown{nav.brand ? ` for ${nav.brand}` : ''}</span>}>
        <ErrorBox error={prods.error} />
        {rows.length === 0 ? <Empty>No productions{nav.brand ? ' for this brand' : ''}.</Empty> : (
          <Table cols={['Production', 'Brand', 'State', 'Updated', '']}>
            {rows.map((p) => (
              <tr key={p.id}>
                <td><button className="linkbtn" onClick={() => { nav.setPid(p.id); nav.go('publish', p.id); }}>{p.name}</button>
                  <div className="mono muted xs">{p.id}</div></td>
                <td className="sm">{p.brand}</td>
                <td><State s={p.state} /></td>
                <td className="muted sm">{fmtAgo(p.updated_at)}</td>
                <td className="nowrap">
                  <Button onClick={() => setPosting(p)} disabled={!['APPROVED', 'PUBLISHED'].includes(p.state)}
                    title={['APPROVED', 'PUBLISHED'].includes(p.state) ? 'Record a post you made yourself' : 'Only an approved video can be recorded as posted'}>I posted it on…</Button>{' '}
                  <Button variant="ghost" onClick={() => setArchiving(p)} disabled={BUSY.includes(p.state)}
                    title={BUSY.includes(p.state) ? 'Wait until it finishes' : 'Move to the archive'}>Archive…</Button>
                </td>
              </tr>
            ))}
          </Table>
        )}
        <p className="muted xs mt">Archived productions leave this list; their files move to <code>output/_archive/</code> and nothing is deleted.
          The <b>Archived</b> tab lists them and can move them back.</p>
      </Card>
      <ArchiveDialog p={archiving} onClose={() => setArchiving(null)} onDone={() => { setArchiving(null); void prods.reload(); }} />
      <PostedDialog p={posting} onClose={() => setPosting(null)} onDone={() => { setPosting(null); void prods.reload(); }} />
    </div>
  );
};

/** What is in output/_archive/: productions (with the render jobs archived with them) and loose jobs. Restore
 * moves the files back to where they were and shows them in the lists again; it refuses if that place is taken. */
const Archived: React.FC<{nav: Nav; tabs: React.ReactNode; onRestored: () => void}> = ({nav, tabs, onRestored}) => {
  const arch = useApi<Any>('/api/archive', 30000);
  const [restoring, setRestoring] = useState<Any>(null);
  const prods: Any[] = (arch.data?.productions ?? []).filter((p: Any) => !nav.brand || p.brand === nav.brand);
  const jobs: Any[] = nav.brand ? [] : (arch.data?.jobs ?? []);
  return (
    <div className="grid">
      <div className="span-12">{tabs}</div>
      <Card title="Archived" className="span-12"
        actions={<span className="muted sm">{prods.length + jobs.length} item(s){arch.data ? ` · ${fmtMb(arch.data.size_mb)} in output/_archive/` : ''}</span>}>
        <ErrorBox error={arch.error} />
        {prods.length + jobs.length === 0 ? <Empty>Nothing archived{nav.brand ? ' for this brand' : ''}.</Empty> : (
          <Table cols={['Archived item', 'Brand', 'State when archived', 'Archived', 'Size', '']}>
            {prods.map((p) => (
              <tr key={p.id}>
                <td>{p.name}<div className="mono muted xs">{p.id}{p.jobs?.length ? ` · ${p.jobs.length} render job(s)` : ''}</div></td>
                <td className="sm">{p.brand}</td>
                <td><State s={p.state} /></td>
                <td className="muted sm">{fmtAgo(p.archived_at)}</td>
                <td className="muted sm">{fmtMb(p.size_mb)}</td>
                <td className="nowrap"><Button onClick={() => setRestoring({...p, kind: 'production'})} disabled={!!p.blocked}
                  title={p.blocked ? `Cannot restore: ${p.blocked}` : `Move back to ${p.restore_to}`}>Restore…</Button></td>
              </tr>
            ))}
            {jobs.map((j) => (
              <tr key={j.id}>
                <td>{j.name}<div className="mono muted xs">render job {j.id}</div></td>
                <td className="muted sm">—</td>
                <td><State s={j.state} /></td>
                <td className="muted sm">{fmtAgo(j.archived_at)}</td>
                <td className="muted sm">{fmtMb(j.size_mb)}</td>
                <td className="nowrap"><Button onClick={() => setRestoring({...j, kind: 'job'})} disabled={!!j.blocked || !j.restore_to}
                  title={j.blocked ? `Cannot restore: ${j.blocked}` : j.restore_to ? `Move back to ${j.restore_to}` : 'No record of where it was'}>Restore…</Button></td>
              </tr>
            ))}
          </Table>
        )}
        <p className="muted xs mt">Restoring never overwrites: if the original folder exists again, move or rename it first.
          Deleting the archive for good is a manual step you do yourself (<code>output/_archive/</code>).</p>
      </Card>
      <RestoreDialog item={restoring} onClose={() => setRestoring(null)}
        onDone={() => { setRestoring(null); void arch.reload(); onRestored(); }} />
    </div>
  );
};

const RestoreDialog: React.FC<{item: Any; onClose: () => void; onDone: () => void}> = ({item, onClose, onDone}) => {
  const [actor, setActor] = useLocal('studio.reviewer', '');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  if (!item) return null;
  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const who = item.kind === 'production' ? {productionId: item.id} : {jobId: item.id};
      await api.post('/api/archive/restore', {...who, actor, note, confirm: true});
      toast('success', `${item.name} restored`);
      onDone();
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <Dialog open title={`Restore ${item.name}?`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={busy} disabled={!actor.trim()} onClick={submit}>Restore</Button></>}>
      <p className="sm">Its files move back from <code>output/_archive/</code> to <code>{item.restore_to}</code>
        {item.kind === 'production' && item.jobs?.length ? `, with its ${item.jobs.length} render job(s),` : ''} and it shows in the lists
        and the dashboard again, in the state it had ({String(item.state ?? '').replace(/_/g, ' ')}). Nothing is overwritten.</p>
      <Field label="Your name (required)"><input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="Full name" /></Field>
      <Field label="Why (optional)"><input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. needed again" /></Field>
      <ErrorBox error={err} />
    </Dialog>
  );
};

const ArchiveDialog: React.FC<{p: Any; onClose: () => void; onDone: () => void}> = ({p, onClose, onDone}) => {
  const [actor, setActor] = useLocal('studio.reviewer', '');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  if (!p) return null;
  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      await api.post(`/api/productions/${p.id}/archive`, {actor, note, confirm: true});
      toast('success', `${p.name} archived`);
      onDone();
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <Dialog open title={`Archive ${p.name}?`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={busy} disabled={!actor.trim()} onClick={submit}>Archive</Button></>}>
      <p className="sm">It disappears from every list. Its files and render jobs move to <code>output/_archive/</code>; nothing is deleted,
        and its approvals and history stay recorded.</p>
      <Field label="Your name (required)"><input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="Full name" /></Field>
      <Field label="Why (optional)"><input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. old test" /></Field>
      <ErrorBox error={err} />
    </Dialog>
  );
};

const PostedDialog: React.FC<{p: Any; onClose: () => void; onDone: () => void}> = ({p, onClose, onDone}) => {
  const [actor, setActor] = useLocal('studio.reviewer', '');
  const [platform, setPlatform] = useState('linkedin');
  const [other, setOther] = useState('');
  const [url, setUrl] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  if (!p) return null;
  const plat = platform === 'other' ? other.trim().toLowerCase() : platform;
  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api.post(`/api/productions/${p.id}/mark-published`, {platform: plat, url: url.trim(), actor, note, confirm: true});
      toast('success', `Recorded: posted on ${r.platform}`);
      onDone();
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <Dialog open title="I posted it on…" onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={busy} disabled={!actor.trim() || !plat || !url.trim().startsWith('https://')} onClick={submit}>Record the post</Button></>}>
      <Alert tone="info">This only records a post <b>you</b> made yourself. Nothing is uploaded. The video must still match what was approved.</Alert>
      <div className="form-grid mt">
        <Field label="Where">
          <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
            {PLATFORMS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            <option value="other">Somewhere else…</option>
          </select>
        </Field>
        {platform === 'other' && <Field label="Platform name" hint="lowercase, e.g. threads"><input value={other} onChange={(e) => setOther(e.target.value)} /></Field>}
        <Field label="Link to your post" wide><input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" /></Field>
        <Field label="Your name (required)"><input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="Full name" /></Field>
        <Field label="Note (optional)"><input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      <ErrorBox error={err} />
    </Dialog>
  );
};
