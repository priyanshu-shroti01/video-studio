import React from 'react';
import {Any} from '../api';
import {Badge, Button, Card, Empty, ErrorBox, Progress, Stat, State, Table, fmtAgo, fmtMb, useApi} from '../ui';
import type {Nav} from '../app';

/** The production pipeline in order; the highlighted stages wait for a person. */
const FUNNEL: {state: string; label: string; human?: boolean}[] = [
  {state: 'DRAFT', label: 'Draft'},
  {state: 'STORYBOARD_READY', label: 'Storyboard'},
  {state: 'PREVIEW_READY', label: 'Preview review', human: true},
  {state: 'RENDERING', label: 'Rendering'},
  {state: 'AWAITING_APPROVAL', label: 'Final approval', human: true},
  {state: 'APPROVED', label: 'Approved'},
  {state: 'PUBLISHED', label: 'Published'},
];
const OTHER = ['QA_COMPLETE', 'PUBLISHING', 'CHANGES_REQUESTED', 'REJECTED', 'FAILED', 'CANCELLED'];
const ACTION_LABEL: Record<string, string> = {
  'review-preview': 'Review preview', 'fix-storyboard': 'Fix storyboard', approve: 'Review & decide', revise: 'Revise',
  failed: 'Open monitor', ready: 'Open publishing', 'brand-setup': 'Open brand',
};
const iso = (s?: string | null) => (s ? Date.parse(s) / 1000 : null);

export const Dashboard: React.FC<{nav: Nav}> = ({nav}) => {
  const q = nav.brand ? `?brand=${encodeURIComponent(nav.brand)}` : '';
  const {data: d, error} = useApi<Any>(`/api/dashboard${q}`, 5000);
  // keep showing the last good data through a hiccup or a Studio restart; the shell shows the connection banner
  if (error && !d) return <ErrorBox error={error} title="Dashboard unavailable" />;
  if (!d) return <div className="skeleton" />;
  const brands: Any[] = d.brands ?? [];
  const byId: Record<string, Any> = Object.fromEntries(brands.map((b) => [b.id, b]));
  const byState: Record<string, number> = d.productions.by_state ?? {};
  const totalProds = Object.values(byState).reduce((a: number, b) => a + (b as number), 0);
  const attention: Any[] = d.attention ?? [];
  const recentJobs: Any[] = d.jobs.recent ?? [];
  const rd = d.render_defaults ?? {};
  const swapHigh = d.memory.swap_used_mb > 4000;
  const shown = nav.brand ? brands.filter((b) => b.id === nav.brand) : brands;
  const open = (it: Any) => {
    if (it.production) nav.setPid(it.production);
    if (it.kind === 'brand-setup') nav.setBrand(it.brand);
    nav.go(it.action, it.action === 'monitor' ? undefined : it.production ?? undefined);
  };
  const BrandTag: React.FC<{id?: string}> = ({id}) => {
    const b = id ? byId[id] : null;
    return <span className="brand-row"><span className="dot" style={b?.colour ? {background: b.colour} : undefined} />{b?.name ?? id ?? '—'}</span>;
  };

  return (
    <div className="grid">
      <div className="dash-bar span-12" role="group" aria-label="Filter by brand">
        <span className="lbl">Brand</span>
        <button className={`chip ${!nav.brand ? 'on' : ''}`} onClick={() => nav.setBrand('')}>All brands <span className="n">{brands.reduce((a, b) => a + (b.productions ?? 0), 0)}</span></button>
        {brands.map((b) => (
          <button key={b.id} className={`chip ${nav.brand === b.id ? 'on' : ''}`} onClick={() => nav.setBrand(b.id)} title={b.website ?? b.id}>
            <span className="dot" style={b.colour ? {background: b.colour} : undefined} />{b.name}
            {b.status === 'draft' && <Badge tone="warning">draft</Badge>}<span className="n">{b.productions ?? 0}</span>
          </button>
        ))}
      </div>

      <div className="stats span-12">
        <Stat label="Needs you" value={attention.filter((a) => a.priority <= 2).length} tone={attention.some((a) => a.priority <= 2) ? 'warning' : 'success'}
          sub={`${byState.PREVIEW_READY ?? 0} preview · ${byState.AWAITING_APPROVAL ?? 0} final approval`} />
        <Stat label="Productions" value={totalProds} sub={nav.brand ? byId[nav.brand]?.name : `${brands.length} brands`} />
        <Stat label="Active jobs" value={d.jobs.active.length} tone={d.jobs.active.length ? 'info' : undefined} sub={`${d.jobs.total} total`} />
        <Stat label="Completed" value={d.jobs.completed} tone="success" sub={d.jobs.failed ? `${d.jobs.failed} failed` : 'no failures'} />
        <Stat label="Free disk" value={`${d.storage.free_gb} GB`} tone={d.storage.free_gb < 10 ? 'warning' : undefined}
          sub={`output ${fmtMb(d.storage.output_mb)} · archive ${fmtMb(d.storage.archive_mb)} · models ${fmtMb(d.storage.models_mb)}`} />
        <Stat label="Memory available" value={fmtMb(d.memory.available_mb)} tone={d.memory.available_mb < 2000 ? 'warning' : undefined}
          sub={<span className={swapHigh ? 'warn-t' : ''}>swap used {fmtMb(d.memory.swap_used_mb)}</span>} />
      </div>

      <Card title="Needs your attention" className="span-7" actions={<span className="muted sm">decisions only a person can make</span>}>
        {attention.length === 0 ? (
          <div className="attn-ok"><span className="ic">✓</span>Nothing is waiting for you{nav.brand ? ` for ${byId[nav.brand]?.name}` : ''}.</div>
        ) : (
          <div className="attn">
            {attention.map((it, i) => (
              <div key={`${it.kind}-${it.production ?? it.brand}-${i}`} className={`attn-i p${it.priority}`}>
                <span className="bar" />
                <div>
                  <div className="attn-t">{it.title}</div>
                  <div className="attn-s"><BrandTag id={it.brand} />{it.production && <span>{it.name} <span className="mono muted">{it.production.slice(-5)}</span></span>}
                    {it.detail && <span className="muted">· {it.detail}</span>}</div>
                </div>
                <Button variant={it.priority === 1 ? 'primary' : 'secondary'} onClick={() => open(it)}>{ACTION_LABEL[it.kind] ?? 'Open'}</Button>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Brands" className="span-5" actions={<span className="muted sm"><code>video-pipeline brand init</code> adds a site</span>}>
        {shown.length === 0 ? <Empty>No brands.</Empty> : (
          <Table cols={['Brand', 'Verified facts', 'Publishing accounts']}>
            {shown.map((b) => (
              <tr key={b.id} title={(b.review ?? []).join(' · ')}>
                <td className="nowrap"><BrandTag id={b.id} /><div className="muted sm">{b.website ? b.website.replace(/^https:\/\//, '') : 'no website set'}{b.status === 'draft' ? ' · draft' : ''}</div></td>
                <td>{b.facts}{b.unverified_claims ? <Badge tone="warning">{b.unverified_claims} unverified</Badge> : null}
                  <div className="muted sm">{b.facts_checked ? `checked ${fmtAgo(iso(b.facts_checked))}` : 'never checked'}</div></td>
                <td className="nowrap">{(['youtube', 'instagram'] as const).map((k) => (
                  <Badge key={k} tone={b.accounts?.[k] ? 'success' : 'neutral'} title={b.accounts?.[k] ? 'connected' : 'not connected'}>{b.accounts?.[k] ? '✓' : '—'} {k === 'youtube' ? 'YouTube' : 'Instagram'}</Badge>))}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card title="Pipeline" className="span-12" actions={<span className="muted sm">highlighted stages wait for a person</span>}>
        {totalProds === 0 ? <Empty>No productions yet. Press <kbd>2</kbd> to start one from a brief.</Empty> : (
          <>
            <div className="funnel">
              {FUNNEL.map((f) => {
                const n = byState[f.state] ?? 0;
                return <div key={f.state} className={`funnel-c ${n === 0 ? 'zero' : ''} ${f.human && n ? 'hot' : ''}`}><div className="k">{f.label}</div><div className="v">{n}</div></div>;
              })}
            </div>
            {OTHER.some((s) => byState[s]) && (
              <div className="state-grid mt">{OTHER.filter((s) => byState[s]).map((s) => <div key={s} className="state-cell"><State s={s} /><span className="state-n">{byState[s]}</span></div>)}</div>
            )}
          </>
        )}
        {(d.productions.recent ?? []).length > 0 && (
          <Table cols={['Production', 'Brand', 'State', 'Preview gate', 'QA', 'Updated']} className="mt">
            {d.productions.recent.map((p: Any) => (
              <tr key={p.id} className="row-link" onClick={() => { nav.setPid(p.id); nav.go(p.state === 'DRAFT' ? 'new' : p.state === 'PREVIEW_READY' ? 'qa' : 'storyboard', p.state === 'DRAFT' ? p.id : undefined); }}>
                <td><div>{p.name}</div><div className="mono muted sm">{p.id}</div></td>
                <td><BrandTag id={p.brand} /></td>
                <td><State s={p.state} /></td>
                <td>{p.gate ? <><State s={p.gate} />{p.preview_approved ? <Badge tone="success">approved</Badge> : null}</> : <span className="muted">—</span>}</td>
                <td>{p.qa_status ? <State s={p.qa_status} /> : <span className="muted">—</span>}</td>
                <td className="muted">{fmtAgo(p.updated_at)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card title="Jobs" className="span-7" actions={<a href="#/monitor">Open monitor →</a>}>
        {recentJobs.length === 0 ? <Empty>No render jobs{nav.brand ? ' for this brand' : ''} yet.</Empty> : (
          <Table cols={['Job', 'State', 'Progress', 'QA', 'Updated']}>
            {recentJobs.map((j) => (
              <tr key={j.id} className="row-link" onClick={() => nav.go('monitor', j.id)}>
                <td><div className="nowrap">{j.brand ? <BrandTag id={j.brand} /> : <span className="muted">no production</span>}</div><div className="mono muted sm">{j.id}</div></td>
                <td><State s={j.state} />{j.state !== 'COMPLETED' && j.stage ? <div className="muted sm">{j.stage}</div> : null}</td>
                <td className="w-progress"><Progress value={j.progress ?? 0} tone={j.state === 'FAILED' ? 'danger' : j.state === 'COMPLETED' ? 'success' : 'brand'} /></td>
                <td>{j.qa_status ? <State s={j.qa_status} /> : '—'}</td><td className="muted">{fmtAgo(j.updated_at)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card title="System" className="span-5" actions={<span className="muted sm">one heavy workload at a time</span>}>
        <h4 className="h4">Scheduler queue</h4>
        {(d.scheduler ?? []).length === 0 ? <div className="muted sm">Idle: no render, voice or LLM work queued.</div> : (
          <Table cols={['State', 'Kind', 'Priority', 'PID', 'Ref']}>
            {d.scheduler.map((s: Any) => <tr key={s.id}><td><State s={s.state} /></td><td>{s.kind}</td><td>{s.priority}</td><td className="mono">{s.pid}</td><td className="mono sm">{s.job_ref}</td></tr>)}
          </Table>
        )}
        <h4 className="h4 mt">Render defaults</h4>
        {Object.keys(rd).length === 0 ? <div className="muted sm">No benchmark yet: <code>uv run video-pipeline benchmark</code>.</div> : (
          <Table cols={['Format', 'Encoder', 'Tabs', 'Worst fps', 'Peak RSS']}>
            {Object.entries(rd).map(([f, r]: [string, Any]) => (
              <tr key={f}><td>{f}</td><td>{r.encoder}</td><td>{r.concurrency}</td><td>{r.worst_fps}</td><td>{fmtMb(r.peak_rss_mb)}</td></tr>
            ))}
          </Table>
        )}
        {(d.tasks ?? []).length > 0 && (
          <>
            <h4 className="h4 mt">Studio tasks</h4>
            <Table cols={['Task', 'Production', 'Status', 'Started']}>
              {d.tasks.map((t: Any) => <tr key={t.id}><td>{t.kind}</td><td className="mono sm">{t.production}</td><td><State s={t.status} /></td><td className="muted">{fmtAgo(t.started_at)}</td></tr>)}
            </Table>
          </>
        )}
      </Card>
    </div>
  );
};
