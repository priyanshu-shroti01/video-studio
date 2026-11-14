import React from 'react';
import {Any, fileUrl} from '../api';
import {Badge, Button, ErrorBox, Tone, fmtAgo, useApi} from '../ui';
import type {Nav} from '../app';
import {Icon} from '../icons';

export const PLATFORM_NAMES: Record<string, string> = {linkedin: 'LinkedIn', youtube: 'YouTube', instagram: 'Instagram',
  facebook: 'Facebook', x: 'X', tiktok: 'TikTok', website: 'your website', export: 'a download'};
export const platformName = (p: string) => PLATFORM_NAMES[p] ?? p.charAt(0).toUpperCase() + p.slice(1);
const list = (xs: string[]) => (xs.length <= 1 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);

/** A production's status in plain words, the tone of its pill, and what clicking it does next. */
export function plainStatus(p: Any): {label: string; tone: Tone; next: string} {
  switch (p.state) {
    case 'DRAFT': return p.has_concepts ? {label: 'Pick an idea', tone: 'brand', next: 'Choose one of three ideas'}
      : {label: 'Getting started', tone: 'neutral', next: 'Get three ideas'};
    case 'STORYBOARD_READY': return {label: 'Storyboard ready', tone: 'brand', next: 'Build a preview'};
    case 'PREVIEW_READY': return p.preview_approved ? {label: 'Ready to make', tone: 'brand', next: 'Make the video'}
      : {label: 'Needs your review', tone: 'warning', next: 'Look at the preview'};
    case 'RENDERING': return {label: `Making the video… ${Math.round((p.job_progress ?? 0) * 100)}%`, tone: 'info', next: 'See progress'};
    case 'QA_COMPLETE': return {label: 'Checking quality…', tone: 'info', next: 'See progress'};
    case 'AWAITING_APPROVAL': return {label: 'Needs your review', tone: 'warning', next: 'Watch and approve'};
    case 'APPROVED': return {label: 'Ready to post', tone: 'success', next: 'Download and share'};
    case 'PUBLISHING': return {label: 'Posting…', tone: 'info', next: 'See status'};
    case 'PUBLISHED': return {label: (p.posted ?? []).length ? `Posted on ${list((p.posted as string[]).map(platformName))}` : 'Posted',
      tone: 'success', next: 'Download and share'};
    case 'CHANGES_REQUESTED': return {label: 'Changes requested', tone: 'warning', next: 'Edit the storyboard'};
    case 'FAILED': return {label: 'Something went wrong', tone: 'danger', next: 'See what happened'};
    case 'REJECTED': return {label: 'Not approved', tone: 'neutral', next: 'Open'};
    case 'CANCELLED': return {label: 'Cancelled', tone: 'neutral', next: 'Open'};
    default: return {label: String(p.state ?? '—').replace(/_/g, ' ').toLowerCase(), tone: 'neutral', next: 'Open'};
  }
}

export const homeTitle = () => 'Your videos';

const NEEDS_YOU = (p: Any) => p.state === 'AWAITING_APPROVAL' || (p.state === 'PREVIEW_READY' && !p.preview_approved)
  || (p.state === 'DRAFT' && p.has_concepts) || p.state === 'CHANGES_REQUESTED';

export const Home: React.FC<{nav: Nav}> = ({nav}) => {
  const cards = useApi<Any[]>('/api/productions/cards', 6000);
  const brandsById: Record<string, Any> = Object.fromEntries(nav.brands.map((b) => [b.id, b]));
  const all = cards.data ?? [];
  const rows = all.filter((p) => !nav.brand || p.brand === nav.brand);
  const waiting = rows.filter(NEEDS_YOU).length;
  const making = rows.filter((p) => p.state === 'RENDERING' || p.state === 'QA_COMPLETE').length;
  const create = () => nav.go('create');
  const open = (p: Any) => { nav.setPid(p.id); nav.go('create', p.id); };

  return (
    <div className="home">
      <p className="home-sum">
        {rows.length === 0 ? 'Turn what you sell into a short video, made on this Mac.'
          : waiting ? `${waiting} video${waiting > 1 ? 's are' : ' is'} waiting for you.`
            : making ? `${making} video${making > 1 ? 's are' : ' is'} being made right now.` : 'Nothing is waiting for you.'}
      </p>

      {nav.brand && all.length !== rows.length && (
        <div className="home-filter muted sm">Showing {brandsById[nav.brand]?.name ?? nav.brand} only ·{' '}
          <button className="linkbtn" onClick={() => nav.setBrand('')}>Show all websites</button></div>
      )}
      {cards.error && !cards.data ? <ErrorBox error={cards.error} title="Your videos could not be loaded" actions={{retry: () => void cards.reload()}} /> : null}

      {!cards.data && !cards.error ? (
        <div className="pgrid">{[0, 1, 2].map((i) => <div key={i} className="pcard pcard-skel"><div className="pcard-img skeleton" /><div className="pcard-b"><div className="skel-line" /><div className="skel-line short" /></div></div>)}</div>
      ) : rows.length === 0 && cards.data ? (
        <FirstVideo nav={nav} onCreate={create} />
      ) : (
        <div className="pgrid">
          {rows.map((p) => {
            const s = plainStatus(p);
            const b = brandsById[p.brand];
            return (
              <button key={p.id} className="pcard" onClick={() => open(p)} title={s.next}>
                <div className={`pcard-img ${p.format === 'landscape' ? '' : 'portrait'}`}>
                  {p.thumbnail ? (
                    <>
                      <img className="pcard-fg" src={fileUrl(p.thumbnail, p.updated_at)} alt="" loading="lazy" />
                    </>
                  ) : <div className="pcard-ph"><Icon name="play" size={28} /></div>}
                  {p.state === 'RENDERING' && <span className="pcard-prog" style={{transform: `scaleX(${Math.max(0, Math.min(1, p.job_progress ?? 0))})`}} />}
                </div>
                <div className="pcard-b">
                  <div className="pcard-t">{p.name}</div>
                  <div className="pcard-m">
                    <span className="brand-chip"><span className="dot" style={b?.brand ? {background: b.brand} : undefined} />{b?.name ?? p.brand}</span>
                    <span className="muted">· {p.format === 'landscape' ? 'Wide' : 'Vertical'}</span>
                    <span className="muted pcard-ago">{fmtAgo(p.updated_at)}</span>
                  </div>
                  <div className="pcard-s"><Badge tone={s.tone}>{s.label}</Badge><span className="pcard-next">{s.next}<Icon name="arrow-right" size={14} /></span></div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

const FirstVideo: React.FC<{nav: Nav; onCreate: () => void}> = ({nav, onCreate}) => (
  <div className="first">
    <div className="first-ic"><Icon name="clapperboard" size={26} /></div>
    <h2>Make your first video</h2>
    <p className="muted">Tell the Studio what you want to promote. It writes three ideas, builds a storyboard from your website's
      checked facts, and makes the video with a local voice. You review it before anything is shared.</p>
    {nav.brands.length === 0 ? (
      <Button variant="primary" className="btn-lg" onClick={() => nav.go('brands')}>Add your website first</Button>
    ) : (
      <Button variant="primary" className="btn-lg" onClick={onCreate}><Icon name="plus" size={18} />Create a video</Button>
    )}
    <ol className="first-steps">
      <li><b>Pick your website</b><span>so prices and claims come from your own facts</span></li>
      <li><b>Say what to promote</b><span>product, price, who it's for</span></li>
      <li><b>Choose an idea, review, approve</b><span>nothing is posted without you</span></li>
    </ol>
  </div>
);
