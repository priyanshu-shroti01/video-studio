// Pure helpers for the help chat (studio/web/src/helpchat.tsx). No DOM, so vitest can test them in node.
// The caps mirror pipeline/help_chat.py; the server enforces them too.

export const MAX_QUESTION = 500;
export const MAX_MESSAGE = 2000;
export const MAX_HISTORY = 12;          // earlier messages the server accepts (6 questions and answers)

export type HelpStatus = 'ok' | 'paused' | 'unavailable' | 'error';
export type HelpMsg = {role: 'user' | 'assistant'; content: string; status?: HelpStatus; sources?: string[]};

// What the current page adds to its name (the wizard's step); set by the page, read when a question is sent.
let detail = '';
export const setHelpDetail = (d: string) => { detail = d; };
export const helpDetail = () => detail;

/** "user is on" for the model: "Create a video, step 3 of 6 (Pick an idea); the selected video's status: Draft". */
export function pageContext(label: string, extra = '', state?: string | null): string {
  let s = extra ? `${label}, ${extra}` : label;
  if (state) {
    const t = state.replace(/_/g, ' ').toLowerCase();
    s += `; the selected video's status: ${t.charAt(0).toUpperCase()}${t.slice(1)}`;
  }
  return s.slice(0, 120);
}

/** The earlier conversation the server gets: answered questions only (a paused or failed reply and its question
 * are left out, so asking again doesn't repeat them), newest last, within the server's caps. */
export function historyFor(msgs: HelpMsg[]): {role: 'user' | 'assistant'; content: string}[] {
  const out: {role: 'user' | 'assistant'; content: string}[] = [];
  for (let i = 0; i < msgs.length - 1; i++) {
    const q = msgs[i];
    const a = msgs[i + 1];
    if (q.role === 'user' && a.role === 'assistant' && a.status === 'ok') {
      out.push({role: 'user', content: q.content.slice(0, MAX_MESSAGE)}, {role: 'assistant', content: a.content.slice(0, MAX_MESSAGE)});
      i++;
    }
  }
  return out.slice(-MAX_HISTORY);
}

/** The chat is full once it holds as many answered questions as the server accepts as history. */
export const chatFull = (msgs: HelpMsg[]) => historyFor(msgs).length >= MAX_HISTORY;

/** "Studio guide › Preview & QA: the preview review panel" -> "Studio guide: Preview & QA: the preview review panel". */
export const sourceLabel = (path: string) => path.replace(' › ', ': ');

/** The question as sent: trimmed and within the cap (the textarea has maxLength too). */
export const cleanQuestion = (s: string) => s.trim().slice(0, MAX_QUESTION);
