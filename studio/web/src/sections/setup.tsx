import React, {useCallback, useEffect, useState} from 'react';
import {Any, runTask} from '../api';
import {Alert, Badge, Button, Card, ErrorBox, Spinner, fmtTime} from '../ui';

const ICON: Record<string, string> = {ok: '✓', missing: '✕', optional: '!'};

/** The `video-pipeline doctor` checks in plain language, each with what to do when it is not OK. */
export const Setup: React.FC = () => {
  const [res, setRes] = useState<Any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const check = useCallback(async () => {
    setBusy(true); setErr(null);
    try { setRes(await runTask('/api/setup/check', {}, undefined, 800)); } catch (x) { setErr(x); } finally { setBusy(false); }
  }, []);
  useEffect(() => { void check(); }, [check]);
  const items: Any[] = res?.checks ?? [];
  const missing = items.filter((c) => c.status === 'missing');
  const optional = items.filter((c) => c.status === 'optional');
  const h = res?.host;
  return (
    <div className="grid">
      <Card title="Setup checklist" className="span-12"
        actions={<Button busy={busy} onClick={check}>Check again</Button>}>
        {busy && !res && <Spinner label=" Checking this Mac…" />}
        <ErrorBox error={err} title="The check could not run" actions={{retry: () => void check()}} />
        {res && (
          <>
            {res.ok
              ? <Alert tone="success" title="Everything needed is installed">You can make, preview and render videos on this Mac.</Alert>
              : <Alert tone="danger" title={`${missing.length} thing(s) to fix before rendering`}>Follow the steps below, then press <b>Check again</b>.</Alert>}
            <div className="muted sm mb">{h ? `${h.model ?? ''} · ${h.perf_cores ?? '?'}P+${h.eff_cores ?? '?'}E cores · ${h.mem_gb ?? '?'} GB memory · ` : ''}checked {fmtTime(Date.parse(res.checked_at) / 1000)}
              {optional.length > 0 && <> · <Badge tone="warning">{optional.length} optional</Badge></>}</div>
            <ul className="setup-list">
              {[...missing, ...optional, ...items.filter((c) => c.status === 'ok')].map((c) => (
                <li key={c.check} className={`setup-i ${c.status}`}>
                  <span className="ic" aria-label={c.status}>{ICON[c.status]}</span>
                  <div>
                    <div>{c.label}</div>
                    {c.fix && <div className="setup-fix">{c.fix}</div>}
                    <div className="muted xs">{c.detail}</div>
                  </div>
                  <Badge tone={c.status === 'ok' ? 'success' : c.status === 'missing' ? 'danger' : 'warning'}>
                    {c.status === 'ok' ? 'OK' : c.status === 'missing' ? 'needed' : 'optional'}</Badge>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
    </div>
  );
};
