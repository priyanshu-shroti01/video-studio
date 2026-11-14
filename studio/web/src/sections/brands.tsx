import React, {useEffect, useState} from 'react';
import {Any, api, fileUrl, runTask, waitTask} from '../api';
import {Alert, Badge, Button, Card, Dialog, Empty, ErrorBox, Field, Spinner, State, Table, fmtAgo, toast, useApi, useLocal} from '../ui';
import type {Nav} from '../app';

const iso = (s?: string | null) => (s ? Date.parse(s) / 1000 : null);
const suggestId = (site: string) => {
  try {
    const host = new URL(site.includes('://') ? site : `https://${site}`).hostname.replace(/^www\./, '');
    return host.split('.')[0].toLowerCase().replace(/[^a-z0-9_-]/g, '').slice(0, 41);
  } catch { return ''; }
};
const showValue = (v: Any) => (v == null ? '—' : typeof v === 'object' ? Object.entries(v).map(([k, x]) => `${k}: ${x}`).join(' · ') : String(v));

/** Websites (brands): add a website, then review and check its facts. Replaces `brand init` and the facts command. */
export const Brands: React.FC<{nav: Nav; arg?: string}> = ({nav, arg}) => {
  const list = useApi<Any[]>('/api/brands', 30000);
  const [adding, setAdding] = useState(false);
  const sel = arg || nav.brand || '';
  const pick = (id: string) => { nav.setBrand(id); nav.go('brands', id); };
  return (
    <div className="grid">
      <Card title="Websites" className="span-12"
        actions={<Button variant="primary" onClick={() => setAdding(true)} disabled={adding}>+ Add a website</Button>}>
        <ErrorBox error={list.error} />
        {(list.data ?? []).length === 0 ? <Empty>No websites yet. Add one to start.</Empty> : (
          <Table cols={['Website', 'Status', '']}>
            {(list.data ?? []).map((b) => (
              <tr key={b.id} className={`row-link ${sel === b.id ? 'sel' : ''}`} onClick={() => pick(b.id)}>
                <td><span className="brand-row"><span className="dot" style={b.brand ? {background: b.brand} : undefined} />{b.name}</span>
                  <div className="muted sm">{b.domain ?? 'no website set'} · <span className="mono">{b.id}</span></div></td>
                <td>{b.status === 'draft' ? <Badge tone="warning">draft: review it</Badge> : <Badge tone="success">ready</Badge>}</td>
                <td className="nowrap"><Button variant={sel === b.id ? 'primary' : 'secondary'} onClick={(e) => { e.stopPropagation(); pick(b.id); }}>Facts</Button></td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      {adding && <AddWebsite onClose={() => setAdding(false)} onDone={(id) => { void list.reload(); setAdding(false); pick(id); }} />}
      {sel ? <BrandFacts key={sel} brand={sel} /> : <div className="span-12"><Empty>Choose a website to see its facts.</Empty></div>}
    </div>
  );
};

// ---- add a website --------------------------------------------------------------------------------
const AddWebsite: React.FC<{onClose: () => void; onDone: (id: string) => void}> = ({onClose, onDone}) => {
  const inds = useApi<Any[]>('/api/industries');
  const [site, setSite] = useState('');
  const [industry, setIndustry] = useState('');
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [err, setErr] = useState<unknown>(null);
  const [res, setRes] = useState<Any>(null);
  useEffect(() => { if (!industry && inds.data?.length) setIndustry(inds.data[0].id); }, [inds.data, industry]);
  const submit = async () => {
    setBusy(true); setErr(null); setRes(null); setElapsed(0);
    const t0 = Date.now();
    try {
      const r = await api.post('/api/brands', {site, industry, id: id.trim(), name: name.trim()});
      const t = await waitTask(r.task.id, () => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
      if (t.status === 'failed') throw Object.assign(new Error(t.error?.message), t.error);
      setRes(t.result);
      toast('success', `Drafted ${t.result.name}`);
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  const draft = res?.draft;
  return (
    <Card title="Add a website" className="span-12" actions={<Button variant="ghost" onClick={onClose}>Close</Button>}>
      {!res && (
        <>
          <p className="sm muted mb">The Studio reads your website's home page once and drafts the brand: name, logo, colours and the
            pages where prices and features are. Nothing is published, and no fact is invented: facts are checked against the site.</p>
          <div className="form-grid">
            <Field label="Website address" hint="https:// is added if you leave it out">
              <input value={site} onChange={(e) => setSite(e.target.value)} placeholder="https://example.com" autoFocus />
            </Field>
            <Field label="What does the site sell?" hint="Chooses the video templates for this kind of business">
              <select value={industry} onChange={(e) => setIndustry(e.target.value)}>
                {(inds.data ?? []).map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
              </select>
            </Field>
            <Field label="Name (optional)" hint="Taken from the site if empty">
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="My Site" />
            </Field>
            <Field label="Short id (optional)" hint="Lowercase letters, digits, - or _. Used for folder names.">
              <input value={id} onChange={(e) => setId(e.target.value)} placeholder={suggestId(site) || 'mysite'} />
            </Field>
          </div>
          <ErrorBox error={err} title="Could not add the website" actions={{retry: () => void submit()}} />
          <div className="row mt">
            <Button variant="primary" busy={busy} disabled={!site.trim() || !industry} onClick={submit}>Read the website and draft the brand</Button>
            {busy && <Spinner label={` Reading the website… ${elapsed}s`} />}
          </div>
        </>
      )}
      {res && draft && (
        <div className="grid2">
          <div>
            <h4 className="h4">Drafted brand: {draft.name} <Badge tone="warning">draft</Badge></h4>
            {draft.logo && <img className="logo-prev" src={fileUrl(draft.logo, Date.now())} alt={`${draft.name} logo`} />}
            <div className="swatches mt">
              {['brand', 'brandText', 'bg', 'card', 'text', 'muted'].filter((k) => typeof draft.colors?.[k] === 'string').map((k) => [k, draft.colors[k]] as const).map(([k, v]) => (
                <span key={k} className="swatch" title={k}><i style={{background: String(v)}} />{k}</span>))}
            </div>
            {draft.colour_source && <div className="muted sm mt-s">Brand colour from {draft.colour_source}</div>}
            {(res.validation_errors ?? []).length > 0 && <Alert tone="warning" title="Needs fixing">{res.validation_errors.join(' · ')}</Alert>}
          </div>
          <div>
            <h4 className="h4">Check these</h4>
            <ul className="sm">{(res.review ?? []).map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
            <h4 className="h4 mt">Pages where facts can come from</h4>
            <ul className="sm">{Object.entries(res.fact_pages ?? {}).map(([k, u]) => <li key={k}><a href={String(u)} target="_blank" rel="noopener noreferrer">{String(u)}</a></li>)}</ul>
            <p className="sm muted">Facts start empty: prices and features are added only with the exact text from these pages, then checked here.</p>
            <Button variant="primary" onClick={() => onDone(res.brand)}>Open its facts</Button>
          </div>
        </div>
      )}
    </Card>
  );
};

// ---- facts review ---------------------------------------------------------------------------------------
const STATUS_TONE: Record<string, 'success' | 'warning' | 'danger' | 'neutral'> = {verified: 'success', stale: 'danger', unchecked: 'warning', NEEDS_REVIEW: 'warning'};
const STATUS_TEXT: Record<string, string> = {
  verified: 'verified', stale: 'not found on the page any more', unchecked: 'page could not be read', NEEDS_REVIEW: 'needs review',
};

const BrandFacts: React.FC<{brand: string}> = ({brand}) => {
  const detail = useApi<Any>(`/api/brands/${encodeURIComponent(brand)}`);
  const facts = useApi<Any>(`/api/brands/${encodeURIComponent(brand)}/facts`);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [report, setReport] = useState<Any>(null);
  const [checking, setChecking] = useState<Any>(null);
  const [filter, setFilter] = useState<'all' | 'attention'>('all');
  const d = detail.data, f = facts.data;
  const recheck = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await runTask(`/api/brands/${encodeURIComponent(brand)}/facts/refresh`, {}, undefined, 1500);
      setReport(r);
      toast(r.status === 'OK' ? 'success' : 'warning', r.status === 'OK' ? `All ${r.verified} facts still on the website` : `${r.stale.length} fact(s) not found any more`);
      void facts.reload();
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  if (detail.error || facts.error) return <div className="span-12"><ErrorBox error={detail.error || facts.error} /></div>;
  if (!d || !f) return <div className="span-12 skeleton" />;
  const rows: Any[] = f.facts ?? [];
  const attention = rows.filter((x) => x.status !== 'verified');
  const shown = filter === 'attention' ? attention : rows;
  const last = report ?? f.last_refresh;
  return (
    <>
      <Card className="span-12" title={<span>{d.name} facts {d.status === 'draft' && <Badge tone="warning">draft</Badge>}</span>}
        actions={<Button variant="primary" busy={busy} disabled={!rows.length} onClick={recheck}
          title={rows.length ? 'Reads each source page again and looks for the exact text' : 'No facts to check yet'}>Re-check against the website</Button>}>
        <p className="sm muted">Every price, plan and feature in a video must be one of these facts, with the exact text it was found in.
          Re-checking never changes the facts: you decide. A fact that needs review is used only after someone confirms it on the website.</p>
        <div className="row wrap mt-s">
          <Badge tone="success">{rows.filter((x) => x.status === 'verified').length} verified</Badge>
          {attention.length > 0 && <Badge tone="warning">{attention.length} need attention</Badge>}
          {(f.not_found ?? []).length > 0 && <Badge tone="danger">{f.not_found.length} claim(s) not on the website</Badge>}
          <span className="muted sm">facts collected {f.fetched_at ? fmtAgo(iso(f.fetched_at)) : 'never'}{last ? ` · last re-check ${fmtAgo(iso(last.checked_at))}` : ''}</span>
        </div>
        {busy && <Alert tone="info"><Spinner label=" Reading the website pages…" /></Alert>}
        <ErrorBox error={err} title="The re-check failed" actions={{retry: () => void recheck()}} />
        {last && Object.keys(last.fetch_errors ?? {}).length > 0 && (
          <Alert tone="warning" title="Some pages could not be read">
            <ul className="sm">{Object.entries(last.fetch_errors).map(([u, e]) => <li key={u}>{u}: {String(e)}</li>)}</ul>
          </Alert>
        )}
        {rows.length === 0 && (
          <Alert tone="info" title="No facts yet">
            Facts are added with their exact source text from these pages; then you check them here.
            <ul className="sm">{Object.entries(f.pages ?? {}).map(([k, u]) => <li key={k}><a href={String(u)} target="_blank" rel="noopener noreferrer">{String(u)}</a></li>)}</ul>
          </Alert>
        )}
      </Card>

      {(f.not_found ?? []).length > 0 && (
        <Card className="span-12" title="Claims that are not on the website">
          <p className="sm muted">These were asked for (for example in a brief) but were not found on the site. They cannot be shown in a video.
            Change the brief, or put the claim on the website first and then add it as a fact.</p>
          <Table cols={['Claim', 'What was found', 'Status']}>
            {f.not_found.map((n: Any, i: number) => (
              <tr key={i}><td>{n.claim}<div className="muted sm">{n.origin}</div></td><td className="sm">{n.finding}</td><td><State s={n.status} /></td></tr>
            ))}
          </Table>
        </Card>
      )}

      {rows.length > 0 && (
        <Card className="span-12" title={`Facts (${rows.length})`}
          actions={<div className="row">
            <button className={`chip ${filter === 'all' ? 'on' : ''}`} onClick={() => setFilter('all')}>All</button>
            <button className={`chip ${filter === 'attention' ? 'on' : ''}`} onClick={() => setFilter('attention')}>Needs attention <span className="n">{attention.length}</span></button>
          </div>}>
          {shown.length === 0 ? <Empty>Nothing needs attention.</Empty> : (
            <Table cols={['Claim', 'Value', 'Source', 'Status', '']}>
              {shown.map((x) => {
                const lastCheck = (x.human_checks ?? []).slice(-1)[0];
                return (
                  <tr key={x.id}>
                    <td><div>{x.claim}</div><div className="mono muted xs">{x.id}</div></td>
                    <td className="sm">{showValue(x.value)}</td>
                    <td>{x.source_url?.startsWith('https://')
                      ? <a className="sm" href={x.source_url} target="_blank" rel="noopener noreferrer">{x.source_url.replace(/^https:\/\//, '')}</a>
                      : <span className="sm mono">{x.source_url}</span>}
                      <div className="excerpt mt-s">“{x.excerpt}”</div></td>
                    <td><Badge tone={STATUS_TONE[x.status] ?? 'neutral'}>{STATUS_TEXT[x.status] ?? x.status}</Badge>
                      {lastCheck && <div className="muted xs mt-s">checked by {lastCheck.reviewer} {fmtAgo(iso(lastCheck.checked_at))}</div>}</td>
                    <td className="nowrap"><Button variant={x.status === 'verified' ? 'ghost' : 'secondary'} onClick={() => setChecking(x)}>I checked this…</Button></td>
                  </tr>
                );
              })}
            </Table>
          )}
        </Card>
      )}
      <ConfirmFact brand={brand} fact={checking} onClose={() => setChecking(null)} onDone={() => { setChecking(null); void facts.reload(); }} />
    </>
  );
};

/** The ONLY way a fact becomes verified by a person: open the source, tick, give your name. */
const ConfirmFact: React.FC<{brand: string; fact: Any; onClose: () => void; onDone: () => void}> = ({brand, fact, onClose, onDone}) => {
  const [reviewer, setReviewer] = useLocal('studio.reviewer', '');
  const [note, setNote] = useState('');
  const [seen, setSeen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { setSeen(false); setNote(''); setErr(null); }, [fact?.id]);
  if (!fact) return null;
  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api.post(`/api/brands/${encodeURIComponent(brand)}/facts/confirm`, {factId: fact.id, reviewer, note, confirm: true});
      toast('success', r.status === 'verified' ? 'Recorded: you checked this fact' : `Recorded (${r.status})`);
      onDone();
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <Dialog open title="I checked this on the website" onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={busy} disabled={!seen || !reviewer.trim()} onClick={submit}>Record my check</Button></>}>
      <p><b>{fact.claim}</b></p>
      <p className="sm">Open <a href={fact.source_url} target="_blank" rel="noopener noreferrer">{fact.source_url}</a> and look for this text:</p>
      <div className="excerpt mb">“{fact.excerpt}”</div>
      {fact.status === 'stale' && <Alert tone="warning">The last re-check did not find this text on the page. If the website changed, the fact must be
        corrected before it is used: recording a check does not change the fact.</Alert>}
      <label className="row mb"><input type="checkbox" checked={seen} onChange={(e) => setSeen(e.target.checked)} />
        <span>I opened the page and this is what the website says.</span></label>
      <Field label="Your name (required)"><input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Full name" /></Field>
      <Field label="Note (optional)"><input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Where on the page, anything odd" /></Field>
      <ErrorBox error={err} />
    </Dialog>
  );
};
