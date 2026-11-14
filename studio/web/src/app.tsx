import React, {useCallback, useEffect, useState} from 'react';
import {Any} from './api';
import {Badge, Button, Dialog, State, Toasts, isTyping, useApi, useLocal} from './ui';
import {Dashboard} from './sections/dashboard';
import {NewProduction} from './sections/newprod';
import {StoryboardEditor} from './sections/storyboard';
import {AssetLibrary} from './sections/assets';
import {RenderMonitor} from './sections/monitor';
import {PreviewQA} from './sections/qa';
import {PublishingCenter} from './sections/publish';
import {Brands} from './sections/brands';
import {Library} from './sections/library';
import {Setup} from './sections/setup';
import {Home, homeTitle} from './sections/home';
import {Icon} from './icons';
import {CreateWizard} from './sections/wizard';

export type Route = {section: string; arg?: string};
/** Sidebar order: the everyday pages first, then the power-user tools ("advanced"). Keys 1–9 follow this order. */
const SECTIONS: {key: string; label: string; icon: string; needsProd?: boolean; advanced?: boolean}[] = [
  {key: 'home', label: 'Home', icon: 'house'},
  {key: 'create', label: 'Create a video', icon: 'plus'},
  {key: 'library', label: 'Library', icon: 'list-video'},
  {key: 'brands', label: 'Websites & facts', icon: 'globe'},
  {key: 'dashboard', label: 'Overview', icon: 'layout-dashboard', advanced: true},
  {key: 'storyboard', label: 'Storyboard', icon: 'clapperboard', needsProd: true, advanced: true},
  {key: 'qa', label: 'Preview & QA', icon: 'circle-check', needsProd: true, advanced: true},
  {key: 'publish', label: 'Publishing', icon: 'send', needsProd: true, advanced: true},
  {key: 'monitor', label: 'Render Monitor', icon: 'activity', advanced: true},
  {key: 'new', label: 'Brief form', icon: 'file-pen-line', advanced: true},
  {key: 'assets', label: 'Asset Library', icon: 'images', advanced: true},
  {key: 'setup', label: 'Setup', icon: 'settings', advanced: true},
];

function parseHash(): Route {
  const h = window.location.hash.replace(/^#\/?/, '');
  const [section, arg] = h.split('/');
  return {section: SECTIONS.some((s) => s.key === section) ? section : 'home', arg: arg ? decodeURIComponent(arg) : undefined};
}

export const go = (section: string, arg?: string) => {
  window.location.hash = `/${section}${arg ? `/${encodeURIComponent(arg)}` : ''}`;
};

/** brand '' = all brands. The brand filter is a view preference (localStorage); every action still takes the brand from the production. */
export type Nav = {go: typeof go; pid: string; setPid: (p: string) => void; brand: string; setBrand: (b: string) => void; brands: Any[]};

export const App: React.FC = () => {
  const [route, setRoute] = useState<Route>(parseHash);
  const [pid, setPidRaw] = useLocal('studio.production', '');
  const [brand, setBrand] = useLocal('studio.brand', '');
  const brandsApi = useApi<Any[]>('/api/brands', 60000);
  const [help, setHelp] = useState(false);
  const prods = useApi<Any[]>('/api/productions', 15000);
  const session = useApi<Any>('/api/session', 4000);   // heartbeat: drives the connection banner

  useEffect(() => {
    const f = () => setRoute(parseHash());
    window.addEventListener('hashchange', f);
    return () => window.removeEventListener('hashchange', f);
  }, []);

  // a production id in the route wins (deep links)
  useEffect(() => {
    if (route.arg && /^P\d{8}-\d{6}-[0-9a-f]{5}$/.test(route.arg) && route.arg !== pid) setPidRaw(route.arg);
  }, [route.arg, pid, setPidRaw]);

  const setPid = useCallback((p: string) => { setPidRaw(p); void prods.reload(); }, [setPidRaw, prods]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return;
      const n = Number(e.key);
      if (n >= 1 && n <= Math.min(9, SECTIONS.length)) { e.preventDefault(); go(SECTIONS[n - 1].key); }
      if (e.key === '?') setHelp((h) => !h);
    };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, []);

  const current = prods.data?.find((p) => p.id === pid);
  const brands = brandsApi.data ?? [];
  const nav: Nav = {go, pid, setPid, brand, setBrand, brands};
  const visibleProds = (prods.data ?? []).filter((p) => !brand || p.brand === brand);
  const sec = SECTIONS.find((s) => s.key === route.section)!;

  let body: React.ReactNode;
  if (sec.needsProd && !pid) {
    body = <ProductionPicker prods={visibleProds} onPick={(p) => setPid(p)} />;
  } else {
    switch (route.section) {
      case 'new': body = <NewProduction nav={nav} pid={route.arg ?? ''} />; break;
      case 'storyboard': body = <StoryboardEditor key={pid} nav={nav} pid={pid} />; break;
      case 'assets': body = <AssetLibrary nav={nav} />; break;
      case 'monitor': body = <RenderMonitor nav={nav} jobArg={route.arg} />; break;
      case 'qa': body = <PreviewQA key={pid} nav={nav} pid={pid} />; break;
      case 'publish': body = <PublishingCenter key={pid} nav={nav} pid={pid} />; break;
      case 'library': body = <Library nav={nav} />; break;
      case 'brands': body = <Brands nav={nav} arg={route.arg} />; break;
      case 'setup': body = <Setup />; break;
      case 'dashboard': body = <Dashboard nav={nav} />; break;
      case 'create': body = <CreateWizard key={route.arg ?? 'new'} nav={nav} pid={route.arg && /^P\d{8}-\d{6}-[0-9a-f]{5}$/.test(route.arg) ? route.arg : undefined} />; break;
      default: body = <Home nav={nav} />;
    }
  }

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <svg className="brand-mark" width={28} height={28} viewBox="0 0 28 28" aria-hidden fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
            <rect x="0.8" y="0.8" width="26.4" height="26.4" rx="7" strokeOpacity={0.25} />
            <path d="M7 10.5V7h3.5M17.5 7H21v3.5M7 17.5V21h3.5M17.5 21H21v-3.5" strokeOpacity={0.55} /><path d="M12 10.6l5.2 3.4L12 17.4z" fill="currentColor" stroke="none" />
          </svg>
          <div><div className="brand-t">Video Studio</div><div className="brand-s">local · v{session.data?.version ?? '…'}</div></div>
        </div>
        <nav className="nav" aria-label="Sections">
          {SECTIONS.map((s, i) => (
            <React.Fragment key={s.key}>
              {s.advanced && !SECTIONS[i - 1]?.advanced && <div className="nav-sep">Advanced</div>}
              <a href={`#/${s.key}`} className={`nav-i ${s.key === 'create' ? 'nav-cta' : ''} ${route.section === s.key ? 'active' : ''}`} aria-current={route.section === s.key ? 'page' : undefined}>
                <span className="nav-ic"><Icon name={s.icon} size={s.key === 'create' ? 16 : 18} /></span><span>{s.label}</span>{i < 9 && <kbd>{i + 1}</kbd>}
              </a>
            </React.Fragment>
          ))}
        </nav>
        <div className="side-prod">
          <label className="field-l" htmlFor="brandsel">Brand</label>
          <select id="brandsel" value={brand} onChange={(e) => setBrand(e.target.value)}>
            <option value="">All brands</option>
            {brands.map((b) => <option key={b.id} value={b.id}>{b.name}{b.status === 'draft' ? ' (draft)' : ''}</option>)}
          </select>
          <label className="field-l" htmlFor="prodsel">Current production</label>
          <select id="prodsel" value={pid} onChange={(e) => setPid(e.target.value)}>
            <option value="">— none —</option>
            {visibleProds.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.id.slice(-5)}</option>)}
          </select>
          {current && <div className="side-prod-s"><State s={current.state} /></div>}
        </div>
        <div className="side-foot">
          <div className="lock">Nothing publishes without your explicit, typed confirmation.</div>
          <button className="linkbtn" onClick={() => setHelp(true)}>Keyboard shortcuts <kbd>?</kbd></button>
        </div>
      </aside>
      <main className="main">
        <header className="top">
          <div>
            <h1>{sec.key === 'home' ? homeTitle() : sec.label}</h1>
            {(sec.needsProd || (sec.key === 'create' && route.arg)) && current && <div className="crumb">{current.name} <span className="mono muted">{current.id}</span></div>}
          </div>
          <div className="top-r">
            {current && sec.key !== 'home' && <Badge tone="neutral">{current.brand}</Badge>}
            {sec.key !== 'create' && <Button variant="primary" onClick={() => go('create')}><Icon name="plus" size={16} />Create a video</Button>}
          </div>
        </header>
        <ConnectionBanner error={session.error} />
        <div className="content">{body}</div>
      </main>
      <Dialog open={help} title="Keyboard shortcuts" onClose={() => setHelp(false)}>
        <table className="tbl"><tbody>
          {SECTIONS.slice(0, 9).map((s, i) => <tr key={s.key}><td><kbd>{i + 1}</kbd></td><td>{s.label}</td></tr>)}
          <tr><td><kbd>⌘/Ctrl</kbd>+<kbd>S</kbd></td><td>Save storyboard (validates)</td></tr>
          <tr><td><kbd>J</kbd> / <kbd>K</kbd></td><td>Next / previous scene</td></tr>
          <tr><td><kbd>Alt</kbd>+<kbd>↑</kbd>/<kbd>↓</kbd></td><td>Move scene up / down</td></tr>
          <tr><td><kbd>Esc</kbd></td><td>Close dialog</td></tr>
        </tbody></table>
      </Dialog>
      <Toasts />
    </div>
  );
};

const ProductionPicker: React.FC<{prods: Any[]; onPick: (p: string) => void}> = ({prods, onPick}) => (
  <div className="card"><div className="card-b">
    <h3 className="mb">Choose a production</h3>
    {prods.length === 0 ? (
      <p className="muted">No videos yet. <a href="#/create">Create a video</a> to get started.</p>
    ) : (
      <div className="pick-list">
        {prods.map((p) => (
          <button key={p.id} className="pick" onClick={() => onPick(p.id)}>
            <span className="pick-n">{p.name}</span><span className="mono muted sm">{p.id}</span><State s={p.state} />
          </button>
        ))}
      </div>
    )}
  </div></div>
);

/** Shown when the Studio server stopped or this tab's session is not valid. Pages keep their last data and
 * reconnect by themselves when the server is back (the session cookie survives Studio restarts). */
const ConnectionBanner: React.FC<{error: unknown}> = ({error}) => {
  if (!error) return null;
  const status = (error as Any)?.status;
  return (
    <div className="conn-banner" role="status">
      {status === 401 || status === 403 ? (
        <><strong>Not signed in to this Studio.</strong> <a href="/">Reload the Studio</a> (or open{' '}
          <code>{window.location.origin}/</code> in this browser).</>
      ) : (
        <><strong>The Studio server is not running.</strong> Start it again with <code>uv run video-pipeline studio</code>;
          this page reconnects by itself.</>
      )}
    </div>
  );
};
