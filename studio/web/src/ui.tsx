import React, {useCallback, useEffect, useRef, useState} from 'react';
import {ApiError, Any, api} from './api';

// ---- formatting ------------------------------------------------------------------------------
export const fmtTime = (t?: number | null) => (t ? new Date(t * 1000).toLocaleString(undefined, {
  month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—');
export const fmtAgo = (t?: number | null) => {
  if (!t) return '—';
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
};
export const fmtMb = (mb?: number | null) => (mb == null ? '—' : mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : `${Math.round(mb)} MB`);
export const fmtBytes = (b?: number | null) => (b == null ? '—' : b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : b > 1e3 ? `${(b / 1e3).toFixed(0)} kB` : `${b} B`);
export const words = (s: string) => (s.trim() ? s.trim().split(/\s+/).length : 0);
export const WPS = 2.33;   // measured on the local voice (pipeline/creative/anchors.py)
export const estSeconds = (narration: string) => words(narration) / WPS;

// ---- state tones -----------------------------------------------------------------------------
export type Tone = 'neutral' | 'brand' | 'success' | 'warning' | 'danger' | 'info';
export function stateTone(s?: string | null): Tone {
  switch (s) {
    case 'COMPLETED': case 'APPROVED': case 'PUBLISHED': case 'PASS': case 'done': case 'resolved': case 'VERIFIED': case 'EXPORTED':
      return 'success';
    case 'FAILED': case 'REJECTED': case 'FAIL': case 'failed': case 'CANCELLED': case 'blocking':
      return 'danger';
    case 'WARN': case 'AWAITING_APPROVAL': case 'CHANGES_REQUESTED': case 'NEEDS_REVIEW': case 'advisory': case 'RETRYING': case 'open':
      return 'warning';
    case 'RENDERING': case 'PUBLISHING': case 'running': case 'QA': case 'PREPARING': case 'GENERATING_AUDIO': case 'BUILDING_TIMELINE':
    case 'POST_PROCESSING': case 'QA_COMPLETE': case 'granted':
      return 'info';
    case 'STORYBOARD_READY': case 'PREVIEW_READY':
      return 'brand';
    default:
      return 'neutral';
  }
}

export const Badge: React.FC<{tone?: Tone; children: React.ReactNode; title?: string}> = ({tone = 'neutral', children, title}) => (
  <span className={`badge badge-${tone}`} title={title}>{children}</span>
);
export const State: React.FC<{s?: string | null}> = ({s}) => <Badge tone={stateTone(s)}>{s ? s.replace(/_/g, ' ') : '—'}</Badge>;

// ---- layout ------------------------------------------------------------------------------------
export const Card: React.FC<{title?: React.ReactNode; actions?: React.ReactNode; children?: React.ReactNode; className?: string; pad?: boolean}> =
  ({title, actions, children, className = '', pad = true}) => (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-h">
          <h3>{title}</h3>
          <div className="card-actions">{actions}</div>
        </header>
      )}
      <div className={pad ? 'card-b' : ''}>{children}</div>
    </section>
  );

export const Stat: React.FC<{label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: Tone}> = ({label, value, sub, tone}) => (
  <div className={`stat ${tone ? `stat-${tone}` : ''}`}>
    <div className="stat-l">{label}</div>
    <div className="stat-v">{value}</div>
    {sub && <div className="stat-s">{sub}</div>}
  </div>
);

export const Empty: React.FC<{children: React.ReactNode}> = ({children}) => <div className="empty">{children}</div>;

export const KV: React.FC<{rows: [string, React.ReactNode][]}> = ({rows}) => (
  <dl className="kv">{rows.map(([k, v]) => <React.Fragment key={k}><dt>{k}</dt><dd>{v ?? '—'}</dd></React.Fragment>)}</dl>
);

export const Progress: React.FC<{value: number; tone?: Tone}> = ({value, tone = 'brand'}) => (
  <div className="progress"><div className={`progress-bar pb-${tone}`} style={{width: `${Math.max(0, Math.min(1, value)) * 100}%`}} /></div>
);

export const Spinner: React.FC<{label?: string}> = ({label}) => <span className="spinner-wrap"><span className="spinner" />{label}</span>;

// ---- errors --------------------------------------------------------------------------------------
export const ErrorBox: React.FC<{error: unknown; title?: string; onDismiss?: () => void}> = ({error, title, onDismiss}) => {
  if (!error) return null;
  const e = error as ApiError & {detail?: string};
  const lines: string[] = e.errors?.length ? e.errors : e.detail ? String(e.detail).split('\n').filter(Boolean) : [];
  return (
    <div className="alert alert-danger" role="alert">
      <div className="alert-h">
        <strong>{title ?? 'Error'}{e.code ? <code className="ml">{e.code}</code> : null}</strong>
        {onDismiss && <button className="btn-x" onClick={onDismiss} aria-label="Dismiss">×</button>}
      </div>
      <div>{e.message ?? String(error)}</div>
      {lines.length > 0 && <ul className="errlist">{lines.slice(0, 80).map((l, i) => <li key={i}><code>{l}</code></li>)}</ul>}
    </div>
  );
};

export const Alert: React.FC<{tone?: Tone; title?: React.ReactNode; children?: React.ReactNode}> = ({tone = 'info', title, children}) => (
  <div className={`alert alert-${tone}`}>{title && <div className="alert-h"><strong>{title}</strong></div>}{children}</div>
);

// ---- inputs ----------------------------------------------------------------------------------------
export const Field: React.FC<{label: string; hint?: React.ReactNode; children: React.ReactNode; wide?: boolean}> = ({label, hint, children, wide}) => (
  <label className={`field ${wide ? 'field-wide' : ''}`}>
    <span className="field-l">{label}</span>
    {children}
    {hint && <span className="field-h">{hint}</span>}
  </label>
);

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'success'; busy?: boolean; kbd?: string};
export const Button: React.FC<BtnProps> = ({variant = 'secondary', busy, kbd, children, className = '', disabled, ...rest}) => (
  <button className={`btn btn-${variant} ${className}`} disabled={disabled || busy} {...rest}>
    {busy && <span className="spinner sm" />}
    {children}
    {kbd && <kbd>{kbd}</kbd>}
  </button>
);

// ---- dialog ----------------------------------------------------------------------------------------
export const Dialog: React.FC<{open: boolean; title: string; onClose: () => void; children: React.ReactNode; footer?: React.ReactNode; tone?: Tone}> =
  ({open, title, onClose, children, footer, tone}) => {
    const ref = useRef<HTMLDivElement>(null);
    const closeRef = useRef(onClose);
    closeRef.current = onClose;
    useEffect(() => {
      if (!open) return;
      const k = (e: KeyboardEvent) => { if (e.key === 'Escape') closeRef.current(); };
      window.addEventListener('keydown', k);
      const first = ref.current?.querySelector<HTMLElement>('.dlg-b input, .dlg-b textarea, .dlg-b select, .dlg-f button');
      first?.focus();
      return () => window.removeEventListener('keydown', k);
    }, [open]);
    if (!open) return null;
    return (
      <div className="dlg-back" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
        <div className={`dlg ${tone ? `dlg-${tone}` : ''}`} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
          <header className="dlg-h"><h3>{title}</h3><button className="btn-x" onClick={onClose} aria-label="Close">×</button></header>
          <div className="dlg-b">{children}</div>
          {footer && <footer className="dlg-f">{footer}</footer>}
        </div>
      </div>
    );
  };

// ---- toasts ------------------------------------------------------------------------------------------
type ToastT = {id: number; tone: Tone; text: string};
let pushToast: (tone: Tone, text: string) => void = () => {};
export const toast = (tone: Tone, text: string) => pushToast(tone, text);
export const Toasts: React.FC = () => {
  const [items, setItems] = useState<ToastT[]>([]);
  useEffect(() => {
    let n = 0;
    pushToast = (tone, text) => {
      const id = ++n;
      setItems((xs) => [...xs, {id, tone, text}]);
      setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), tone === 'danger' ? 9000 : 4500);
    };
  }, []);
  return <div className="toasts" aria-live="polite">{items.map((t) => <div key={t.id} className={`toast toast-${t.tone}`}>{t.text}</div>)}</div>;
};

// ---- data hooks ------------------------------------------------------------------------------------
export function useApi<T = Any>(path: string | null, pollMs?: number | false) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const seq = useRef(0);
  const load = useCallback(async () => {
    if (!path) return;
    const my = ++seq.current;
    setLoading(true);
    try {
      const d = await api.get<T>(path);
      if (my === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (my === seq.current) setError(e);
    } finally {
      if (my === seq.current) setLoading(false);
    }
  }, [path]);
  useEffect(() => { setData(null); setError(null); void load(); }, [load]);
  useEffect(() => {
    if (!pollMs || !path) return;
    const t = setInterval(() => { if (!document.hidden) void load(); }, pollMs);
    return () => clearInterval(t);
  }, [pollMs, path, load]);
  return {data, error, loading, reload: load, setData};
}

export function useLocal(key: string, initial: string): [string, (v: string) => void] {
  const [v, setV] = useState<string>(() => {
    try { return localStorage.getItem(key) ?? initial; } catch { return initial; }
  });
  const set = useCallback((x: string) => { setV(x); try { localStorage.setItem(key, x); } catch { /* private mode */ } }, [key]);
  return [v, set];
}

export const isTyping = (e: KeyboardEvent) => {
  const t = e.target as HTMLElement | null;
  return !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
};

/** Markdown-ish text block (rendered as preformatted, never as HTML). */
export const Pre: React.FC<{children: React.ReactNode; max?: number; className?: string}> = ({children, max = 360, className = ''}) => (
  <pre className={`pre ${className}`} style={{maxHeight: max}}>{children}</pre>
);

export const Table: React.FC<{cols: string[]; children: React.ReactNode; className?: string}> = ({cols, children, className = ''}) => (
  <div className="tbl-wrap"><table className={`tbl ${className}`}><thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead><tbody>{children}</tbody></table></div>
);
