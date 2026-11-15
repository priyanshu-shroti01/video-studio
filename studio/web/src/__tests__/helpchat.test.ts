import {describe, expect, it} from 'vitest';
import {HelpMsg, MAX_HISTORY, MAX_MESSAGE, MAX_QUESTION, chatFull, cleanQuestion, helpDetail, historyFor, pageContext, setHelpDetail, sourceLabel} from '../helpchat-logic';

describe('help chat: page context', () => {
  it('names the page, the wizard step and the selected video status', () => {
    expect(pageContext('Create a video', 'step 3 of 6 (Pick an idea)', 'STORYBOARD_READY'))
      .toBe("Create a video, step 3 of 6 (Pick an idea); the selected video's status: Storyboard ready");
    expect(pageContext('Home')).toBe('Home');
    expect(pageContext('x'.repeat(300)).length).toBe(120);
  });
  it('keeps the step a page sets until the page clears it', () => {
    setHelpDetail('step 2 of 6 (What to promote)');
    expect(helpDetail()).toBe('step 2 of 6 (What to promote)');
    setHelpDetail('');
    expect(helpDetail()).toBe('');
  });
});

describe('help chat: conversation caps', () => {
  const qa = (n: number): HelpMsg[] => Array.from({length: n}, (_, i): HelpMsg[] => [
    {role: 'user', content: `q${i}`}, {role: 'assistant', content: `a${i}`, status: 'ok'}]).flat();

  it('sends answered questions only, never a paused or failed reply', () => {
    const msgs: HelpMsg[] = [{role: 'user', content: 'q1'}, {role: 'assistant', content: 'paused', status: 'paused'},
      {role: 'user', content: 'q1'}, {role: 'assistant', content: 'a1', status: 'ok'},
      {role: 'user', content: 'q2'}, {role: 'assistant', content: 'oops', status: 'error'}];
    expect(historyFor(msgs)).toEqual([{role: 'user', content: 'q1'}, {role: 'assistant', content: 'a1'}]);
  });
  it('stays within the server limits and says when the chat is full', () => {
    expect(historyFor(qa(10)).length).toBe(MAX_HISTORY);
    expect(chatFull(qa(MAX_HISTORY / 2 - 1))).toBe(false);
    expect(chatFull(qa(MAX_HISTORY / 2))).toBe(true);
    const long: HelpMsg[] = [{role: 'user', content: 'x'.repeat(5000)}, {role: 'assistant', content: 'y'.repeat(5000), status: 'ok'}];
    expect(historyFor(long).every((m) => m.content.length <= MAX_MESSAGE)).toBe(true);
    expect(cleanQuestion(`  ${'z'.repeat(900)}  `).length).toBe(MAX_QUESTION);
  });
  it('shows a source as "guide: section"', () => {
    expect(sourceLabel('Studio guide › Preview & QA: the preview review panel')).toBe('Studio guide: Preview & QA: the preview review panel');
  });
});
