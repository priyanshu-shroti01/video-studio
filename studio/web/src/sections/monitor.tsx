import React, {useEffect, useRef, useState} from 'react';
import {Any, api} from '../api';
import {Alert, Button, Card, Empty, ErrorBox, KV, Progress, Stat, State, Table, fmtAgo, fmtMb, fmtTime, toast, useApi} from '../ui';
import type {Nav} from '../app';

const TERMINAL = ['COMPLETED', 'FAILED', 'CANCELLED'];
const STAGES = ['PREPARING', 'GENERATING_AUDIO', 'BUILDING_TIMELINE', 'RENDERING', 'POST_PROCESSING', 'QA'];

export const RenderMonitor: React.FC<{nav: Nav; jobArg?: string}> = ({nav, jobArg}) => {
  const jobs = useApi<Any[]>('/api/jobs', 5000);
  const list = jobs.data ?? [];
  const fallback = list.find((j) => !TERMINAL.includes(j.state))?.id ?? list[0]?.id;
  const jobId = jobArg ?? fallback;
  const [live, setLive] = useState(true);
  const mon = useApi<Any>(jobId ? `/api/jobs/${jobId}/monitor` : null, live ? 2000 : false);
  const j = mon.data;
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [j?.log?.length]);
  useEffect(() => { if (j && TERMINAL.includes(j.state)) setLive(false); else setLive(true); }, [j?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!jobId) return <Empty>No render jobs yet. Start one from the Storyboard Editor (Render…).</Empty>;
  const stages: Record<string, Any> = Object.fromEntries((j?.stages ?? []).map((s: Any) => [s.stage, s]));
  const rr = j?.render_report;
  const cancel = async () => {
    if (!window.confirm(`Request cancellation of job ${jobId}?`)) return;
    try { const r = await api.post(`/api/jobs/${jobId}/cancel`); toast('info', `Cancel requested (${r.state})`); void mon.reload(); } catch (e) { toast('danger', String((e as Error).message)); }
  };
  return (
    <div className="grid">
      <Card className="span-12" title={<span className="row"><select value={jobId} onChange={(e) => nav.go('monitor', e.target.value)} aria-label="Job">
        {list.map((x) => <option key={x.id} value={x.id}>{x.name} · {x.id} · {x.state}</option>)}</select>
        {j && <State s={j.state} />}{j?.qa_status && <State s={j.qa_status} />}</span>}
        actions={<>
          <label className="check"><input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> live</label>
          {j && !TERMINAL.includes(j.state) && <Button variant="danger" onClick={cancel}>Request cancel</Button>}
        </>}>
        <ErrorBox error={mon.error} />
        {j && (
          <>
            <div className="mon-head">
              <div className="grow">
                <div className="row between"><b>{j.stage ?? 'QUEUED'}</b><span className="muted">{Math.round((j.progress ?? 0) * 100)}%</span></div>
                <Progress value={j.progress ?? 0} tone={j.state === 'FAILED' ? 'danger' : j.state === 'COMPLETED' ? 'success' : 'brand'} />
                <div className="muted sm mt-s">{j.message}</div>
              </div>
              <KV rows={[['Created', fmtTime(j.created_at)], ['Updated', fmtAgo(j.updated_at)], ['Attempts', j.attempts], ['Heartbeat', fmtAgo(j.heartbeat)], ['PID', j.pid ?? '—']]} />
            </div>
            <div className="pipeline">
              {STAGES.map((s) => {
                const r = stages[s];
                const st = r?.status ?? (j.stage === s && !TERMINAL.includes(j.state) ? 'running' : 'pending');
                return <div key={s} className={`pstage ps-${String(st).toLowerCase()}`}><div className="pstage-n">{s.replace(/_/g, ' ')}</div><div className="pstage-s">{String(st).toLowerCase()}{r?.seconds ? ` · ${r.seconds.toFixed(1)}s` : ''}</div></div>;
              })}
            </div>
            {j.error && <Alert tone="danger" title={`Error: ${j.error.code ?? ''}`}><div>{j.error.message}</div>{j.error.detail && <pre className="pre">{j.error.detail}</pre>}</Alert>}
          </>
        )}
      </Card>

      {j && <>
        <div className="stats span-12">
          {(rr?.formats ?? []).map((f: Any) => <Stat key={f.format} label={`${f.format} render`} value={`${f.fps_rendered ?? '—'} fps`} sub={`${f.frames} frames · ${f.encoder} · ×${f.realtime_factor ?? '—'} realtime · peak ${fmtMb(f.peak_rss_mb)}`} />)}
          <Stat label="Memory available" value={fmtMb(j.memory?.available_mb)} tone={j.memory?.available_mb < 2000 ? 'warning' : undefined} />
          <Stat label="Swap used" value={fmtMb(j.memory?.swap_used_mb)} />
          <Stat label="Chunks on disk" value={(j.chunks_on_disk ?? []).length} />
        </div>

        <Card title="Chunks" className="span-12">
          {!rr ? <Empty>No render report yet (written when RENDERING finishes). Chunks on disk: {(j.chunks_on_disk ?? []).join(', ') || 'none'}</Empty> : (
            <Table cols={['Format', 'Frames', 'Seconds', 'Encoder', 'Tabs', 'Peak RSS', 'Swap Δ', 'Page-outs Δ', 'Reused', 'Attempts']}>
              {rr.formats.flatMap((f: Any) => (f.chunks ?? []).map((c: Any, i: number) => (
                <tr key={`${f.format}-${i}`}>
                  <td>{f.format}</td><td className="mono nowrap">{c.frames?.[0]}–{c.frames?.[1]}</td><td>{c.seconds}</td><td>{c.encoder}</td><td>{c.concurrency}</td>
                  <td>{fmtMb(c.peak_rss_mb)}</td><td className={c.swap_delta_mb > 64 ? 'warn-t' : ''}>{c.swap_delta_mb} MB</td><td>{c.pageouts_delta}</td>
                  <td>{c.reused ? 'yes' : 'no'}</td><td>{c.attempts}</td>
                </tr>)))}
            </Table>
          )}
        </Card>
        <Card title="Scheduler queue" className="span-12">
          {(j.scheduler ?? []).length === 0 ? <Empty>Idle.</Empty> : (
            <Table cols={['State', 'Kind', 'Prio', 'PID', 'Ref']}>
              {j.scheduler.map((q: Any) => <tr key={q.id}><td><State s={q.state} /></td><td>{q.kind}</td><td>{q.priority}</td><td className="mono">{q.pid}</td><td className="mono xs">{q.job_ref}</td></tr>)}
            </Table>
          )}
        </Card>

        <Card title="Log tail" className="span-7" actions={<span className="muted sm">logs/pipeline.jsonl · last 40</span>}>
          <div className="log" ref={logRef}>
            {(j.log ?? []).length === 0 ? <div className="muted">No log lines yet.</div> : j.log.map((l: Any, i: number) => (
              <div key={i} className={`log-l lv-${l.level ?? 'info'}`}><span className="log-t">{l.ts ? new Date(l.ts * 1000).toLocaleTimeString() : ''}</span><span className="log-s">{l.stage ?? ''}</span><span>{l.message ?? l.msg ?? JSON.stringify(l)}</span></div>
            ))}
          </div>
        </Card>
        <Card title="Events" className="span-5">
          <div className="log">
            {(j.events ?? []).map((e: Any, i: number) => <div key={i} className={`log-l lv-${e.level}`}><span className="log-t">{new Date(e.ts * 1000).toLocaleTimeString()}</span><span className="log-s">{e.stage ?? ''}</span><span>{e.message}</span></div>)}
          </div>
        </Card>
      </>}
    </div>
  );
};
