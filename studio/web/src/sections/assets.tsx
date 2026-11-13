import React, {useMemo, useState} from 'react';
import {Any, fileUrl, servable} from '../api';
import {Badge, Card, Empty, ErrorBox, Field, Table, fmtBytes, useApi} from '../ui';
import type {Nav} from '../app';

const IMG = new Set(['svg', 'png', 'jpg', 'jpeg', 'webp', 'gif']);
const AUDIO = new Set(['wav', 'mp3', 'ogg', 'flac', 'm4a', 'aac']);
const PAGE = 120;

const category = (path: string) => {
  const p = path.split('/');
  if (p[0] === 'audio' && p[1] === 'kit') return `sfx/${p[2] ?? ''}`;
  if (p[0] === 'audio' && p[1] === 'music') return 'music';
  if (p[0] === 'public' && p[1] === 'brands') return `brand/${p[3] ?? ''}`;
  return `${p[0]}/${p[1] ?? ''}`;
};
const licTone = (l: string) => (!l || l === 'UNKNOWN' ? 'danger' : /test|not for publication/i.test(l) ? 'warning' : 'success') as 'danger' | 'warning' | 'success';

const Preview: React.FC<{path: string; type: string}> = ({path, type}) => {
  const ext = (type || path.split('.').pop() || '').toLowerCase();
  if (!servable(path)) return <span className="muted sm" title="audio/ is not served by safe_output_file (output/ and public/ only)">not served</span>;
  if (IMG.has(ext)) return <img className="asset-thumb" src={fileUrl(path)} alt="" loading="lazy" />;
  if (AUDIO.has(ext)) return <audio controls preload="none" src={fileUrl(path)} className="asset-audio" />;
  if (ext === 'woff2' || ext === 'ttf') return <span className="font-sample">Aa</span>;
  return <span className="muted sm">{ext}</span>;
};

export const AssetLibrary: React.FC<{nav: Nav}> = ({nav}) => {
  const [picked, setBrand] = useState('');
  const brand = picked || nav.brand || nav.brands[0]?.id || '';
  const {data, error, loading} = useApi<Any>(brand ? `/api/assets?brand=${encodeURIComponent(brand)}` : null);
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('');
  const [limit, setLimit] = useState(PAGE);
  // files Studio can preview (public/, output/) first
  const rows: Any[] = useMemo(() => [...(data?.assets ?? [])].sort((a, b) => Number(servable(b.path)) - Number(servable(a.path))), [data]);
  const cats = useMemo(() => Array.from(new Set(rows.map((r) => category(r.path)))).sort(), [rows]);
  const filtered = useMemo(() => {
    const ql = q.toLowerCase();
    return rows.filter((r) => (!cat || category(r.path) === cat) &&
      (!ql || [r.path, r.license, r.attribution, r.source].some((x) => (x ?? '').toLowerCase().includes(ql))));
  }, [rows, q, cat]);
  const music: Any[] = data?.music ?? [];
  const unknown = rows.filter((r) => !r.license || r.license === 'UNKNOWN').length;

  return (
    <div className="grid">
      <Card className="span-12" title="Registered assets" actions={<span className="muted sm">{loading ? 'loading…' : `${filtered.length} of ${rows.length}`}{unknown ? ` · ${unknown} with unknown licence` : ''}</span>}>
        <div className="filters">
          <Field label="Brand"><select value={brand} onChange={(e) => { setBrand(e.target.value); setLimit(PAGE); }}>
            {nav.brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></Field>
          <Field label="Category"><select value={cat} onChange={(e) => { setCat(e.target.value); setLimit(PAGE); }}><option value="">All</option>{cats.map((c) => <option key={c}>{c}</option>)}</select></Field>
          <Field label="Search"><input type="search" value={q} placeholder="path, licence, attribution…" onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} /></Field>
        </div>
        <ErrorBox error={error} />
        {filtered.length === 0 ? <Empty>No assets match. Register assets with <code>uv run video-pipeline assets scan</code>.</Empty> : (
          <>
            <Table cols={['Preview', 'Asset', 'Category', 'Licence', 'Attribution / source', 'Size', 'Used by']}>
              {filtered.slice(0, limit).map((r) => {
                const refs: string[] = (() => { try { return JSON.parse(r.refs_json || '[]'); } catch { return []; } })();
                return (
                  <tr key={r.sha256}>
                    <td className="w-prev"><Preview path={r.path} type={r.type} /></td>
                    <td><div className="mono sm break">{r.path}</div><div className="muted xs mono">{r.sha256.slice(0, 12)}</div></td>
                    <td><Badge>{category(r.path)}</Badge></td>
                    <td><Badge tone={licTone(r.license)}>{r.license || 'UNKNOWN'}</Badge></td>
                    <td className="sm"><div>{r.attribution || <span className="muted">—</span>}</div>
                      {r.source && /^https?:\/\//.test(r.source) ? <a className="xs" href={r.source} target="_blank" rel="noopener noreferrer">{r.source}</a> : <span className="muted xs">{r.source}</span>}</td>
                    <td className="muted sm nowrap">{fmtBytes(r.bytes)}</td>
                    <td className="sm">{refs.length ? <span title={refs.join('\n')}>{refs.length} job{refs.length > 1 ? 's' : ''}</span> : <span className="muted">—</span>}</td>
                  </tr>
                );
              })}
            </Table>
            {filtered.length > limit && <div className="center mt"><button className="btn btn-ghost" onClick={() => setLimit(limit + PAGE)}>Show more ({filtered.length - limit} left)</button></div>}
          </>
        )}
        <p className="muted xs mt">Audio under <code>audio/</code> (sound kit, music) is listed but not playable here: the Studio serves files only from <code>output/</code> and <code>public/</code>.</p>
      </Card>

      <Card className="span-12" title={`Music library (${music.length})`}>
        {music.length === 0 ? <Empty>No tracks. Run <code>scripts/fetch_music.py</code> or add licensed music.</Empty> : (
          <Table cols={['Track', 'Moods', 'Licence', 'Publishable', 'Attribution', 'Duration']}>
            {music.map((t) => (
              <tr key={t.id ?? t.file}>
                <td><div>{t.title}</div><div className="mono xs muted">audio/music/{t.file}</div></td>
                <td>{(t.moods ?? []).map((m: string) => <Badge key={m}>{m}</Badge>)}</td>
                <td><Badge tone={licTone(t.license)}>{t.license}</Badge></td>
                <td>{t.publishable && t.brandSafe !== false ? <Badge tone="success">yes</Badge> : <Badge tone="danger">no</Badge>}</td>
                <td className="sm">{t.attribution}{t.landing_url && <div><a className="xs" href={t.landing_url} target="_blank" rel="noopener noreferrer">{t.landing_url}</a></div>}</td>
                <td className="muted sm">{t.duration_s ? `${Math.round(t.duration_s)} s` : '—'}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
};
