import React, {useCallback, useEffect, useRef, useState} from 'react';
import {ApiError, api} from './api';
import {Button, Spinner} from './ui';
import {Icon} from './icons';
import {HelpMsg, HelpStatus, MAX_QUESTION, chatFull, cleanQuestion, helpDetail, historyFor, pageContext, sourceLabel} from './helpchat-logic';

/** The help chat: a round button at the bottom right of every page that opens a small panel. It answers how-to
 * questions with the local AI model, from the Studio guides (POST /api/help/ask, pipeline/help_chat.py). It only
 * explains: it has no buttons that change anything. Closed by default; the open/closed state lasts for this
 * browser session only. The conversation lives in this tab's memory. */
const SUGGESTIONS = ['How do I add my website?', 'Why did my render fail?', 'What does Preview & QA mean?'];
const OPEN_KEY = 'studio.help.open';

const readOpen = () => { try { return sessionStorage.getItem(OPEN_KEY) === '1'; } catch { return false; } };
const writeOpen = (v: boolean) => { try { sessionStorage.setItem(OPEN_KEY, v ? '1' : '0'); } catch { /* private mode */ } };

function plainError(e: unknown): string {
  const err = e as ApiError;
  if (err?.status === 0) return 'The Studio server is not reachable. Start it again, then ask once more.';
  if (err?.status === 401 || err?.status === 403) return 'This browser is not signed in to the Studio. Reload the page, then ask again.';
  if (err?.status === 400 && err.message) return err.message.charAt(0).toUpperCase() + err.message.slice(1) + '.';
  return 'The helper couldn’t answer that just now. Try again in a moment.';
}

export const HelpChat: React.FC<{page: string; state?: string | null}> = ({page, state}) => {
  const [open, setOpenRaw] = useState(readOpen);
  const [msgs, setMsgs] = useState<HelpMsg[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const fab = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const returnFocus = useRef(false);

  const setOpen = useCallback((v: boolean) => { setOpenRaw(v); writeOpen(v); if (!v) returnFocus.current = true; }, []);

  // focus: the question box when the panel opens, the round button again when it closes
  useEffect(() => {
    if (open) input.current?.focus();
    else if (returnFocus.current) { returnFocus.current = false; fab.current?.focus(); }
  }, [open]);

  // Esc closes the panel (a modal dialog on top gets the Esc first)
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape' && !document.querySelector('.dlg-back')) setOpen(false); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [open, setOpen]);

  useEffect(() => { log.current?.scrollTo({top: log.current.scrollHeight}); }, [msgs, busy, open]);

  const full = chatFull(msgs);
  const ask = async (raw: string) => {
    const q = cleanQuestion(raw);
    if (!q || busy || full) return;
    const history = historyFor(msgs);
    setMsgs((m) => [...m, {role: 'user', content: q}]);
    setText('');
    setBusy(true);
    try {
      const r = await api.post<{status: HelpStatus; message: string; sources?: string[]}>('/api/help/ask',
        {question: q, history, page: pageContext(page, helpDetail(), state)});
      setMsgs((m) => [...m, {role: 'assistant', content: r.message, status: r.status, sources: r.sources ?? []}]);
    } catch (e) {
      setMsgs((m) => [...m, {role: 'assistant', content: plainError(e), status: 'error'}]);
    } finally {
      setBusy(false);
      input.current?.focus();
    }
  };
  const reset = () => { setMsgs([]); setText(''); input.current?.focus(); };

  return (
    <>
      {open && (
        <section className="help-panel" id="help-panel" role="dialog" aria-modal="false" aria-labelledby="help-title">
          <header className="help-h">
            <div>
              <h2 id="help-title">Help</h2>
              <p className="help-sub">Answers from the Studio guides. Nothing leaves this Mac.</p>
            </div>
            <div className="help-h-r">
              {msgs.length > 0 && <Button variant="ghost" className="btn-sm" onClick={reset}>New chat</Button>}
              <button type="button" className="btn-x" onClick={() => setOpen(false)} aria-label="Close help">×</button>
            </div>
          </header>
          <div className="help-log" ref={log} role="log" aria-live="polite" aria-busy={busy} tabIndex={-1}>
            {msgs.length === 0 && (
              <div className="help-intro">
                <p>Ask how to do something in the Studio. The helper explains; it can&rsquo;t click, approve or post anything for you.</p>
                <div className="help-sugg" role="group" aria-label="Example questions">
                  {SUGGESTIONS.map((s) => <button type="button" key={s} onClick={() => void ask(s)}>{s}</button>)}
                </div>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`help-msg help-${m.role}${m.status && m.status !== 'ok' ? ' help-note' : ''}`}>
                <span className="sr-only">{m.role === 'user' ? 'You said: ' : 'Helper: '}</span>
                {m.content}
                {m.status === 'ok' && m.sources && m.sources.length > 0 && (
                  <div className="help-src">From {m.sources.slice(0, 2).map(sourceLabel).join(' · ')}</div>
                )}
              </div>
            ))}
            {busy && <div className="help-msg help-assistant help-wait"><Spinner label="Looking in the guides…" /></div>}
          </div>
          <form className="help-f" onSubmit={(e) => { e.preventDefault(); void ask(text); }}>
            {full ? (
              <p className="help-full">This chat is full. <button type="button" className="linkbtn" onClick={reset}>Start a new chat</button></p>
            ) : (
              <>
                <label htmlFor="help-q" className="sr-only">Your question</label>
                <textarea id="help-q" ref={input} rows={2} maxLength={MAX_QUESTION} value={text} placeholder="Ask how to do something…"
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void ask(text); } }} />
                <div className="help-fr">
                  <span className="help-hint" aria-live="polite">{text.length > MAX_QUESTION - 100 ? `${MAX_QUESTION - text.length} characters left` : 'Enter sends · Shift+Enter adds a line'}</span>
                  <Button variant="primary" className="btn-sm" type="submit" disabled={!text.trim()} busy={busy}>Ask</Button>
                </div>
              </>
            )}
          </form>
        </section>
      )}
      <button ref={fab} type="button" className="help-fab" onClick={() => setOpen(!open)} aria-expanded={open}
        aria-controls={open ? 'help-panel' : undefined} aria-label={open ? 'Close help' : 'Help: ask how to do something'}>
        <Icon name={open ? 'x' : 'circle-help'} size={22} />
      </button>
    </>
  );
};
