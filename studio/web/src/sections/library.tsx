import React, {useState} from 'react';
import {Any, api} from '../api';
import {Alert, Button, Card, Dialog, Empty, ErrorBox, Field, State, Table, fmtAgo, toast, useApi, useLocal} from '../ui';
import type {Nav} from '../app';

const PLATFORMS = [['linkedin', 'LinkedIn'], ['youtube', 'YouTube'], ['instagram', 'Instagram'], ['facebook', 'Facebook'],
  ['x', 'X (Twitter)'], ['tiktok', 'TikTok'], ['website', 'My website']] as const;
const BUSY = ['RENDERING', 'PUBLISHING'];

/** Every production with the library actions: archive (moves files to output/_archive/, nothing is deleted) and
 * "I posted it on…" (records a post a person made; nothing is uploaded). Both need your name. */
export const Library: React.FC<{nav: Nav}> = ({nav}) => {
  const prods = useApi<Any[]>('/api/productions', 15000);
  const [archiving, setArchiving] = useState<Any>(null);
  const [posting, setPosting] = useState<Any>(null);
  const rows = (prods.data ?? []).filter((p) => !nav.brand || p.brand === nav.brand);
  return (
    <div className="grid">
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
          Restoring from the Studio is not available yet: ask whoever maintains the studio to move them back.</p>
      </Card>
      <ArchiveDialog p={archiving} onClose={() => setArchiving(null)} onDone={() => { setArchiving(null); void prods.reload(); }} />
      <PostedDialog p={posting} onClose={() => setPosting(null)} onDone={() => { setPosting(null); void prods.reload(); }} />
    </div>
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
