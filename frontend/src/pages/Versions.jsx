import React, { useEffect, useState } from 'react';
import { api } from '../api.js';
import { labelOf } from '../names.js';
import EmptyState from '../components/EmptyState.jsx';
import { errText, useI18n } from '../useI18n.js';

export default function Versions({ config, onGoSettings }) {
  const { t } = useI18n();
  const games = Object.keys(config.games);
  const [game, setGame] = useState(games[0] || '');
  const [list, setList] = useState([]);
  const [msg, setMsg] = useState(null); // {error?, body}: `body` es un error o respuesta con {code, params} (se traduce al pintar)
  const [limit, setLimit] = useState(null);

  const load = (g) => g ? api(`/api/versions/${encodeURIComponent(g)}`).then(setList).catch((e) => setMsg({ error: true, body: e })) : setList([]);
  const loadLimit = (g) => (g ? api(`/api/versions/${encodeURIComponent(g)}/limit`).then(setLimit).catch(() => setLimit(null)) : setLimit(null));
  useEffect(() => { load(game); loadLimit(game); }, [game, config]); // eslint-disable-line react-hooks/exhaustive-deps

  const restore = async (version, source, sourceName) => {
    if (!window.confirm(t('versions.confirm', { version, source: sourceName }))) return;
    try {
      const r = await api(`/api/versions/${encodeURIComponent(game)}/restore`, { method: 'POST', body: { version, source } });
      setMsg({ body: r }); load(game); loadLimit(game);
    } catch (e) { setMsg({ error: true, body: e }); }
  };

  return (
    <section className={list.length === 0 ? 'fill' : undefined}>
      <div className="row between versions-head">
        <h2>{t('versions.title')}</h2>
        <select aria-label={t('versions.gameAria')} value={game} onChange={(e) => { setGame(e.target.value); setMsg(null); }}>
          {games.map((g) => <option key={g} value={g}>{labelOf(config.games, g)}</option>)}
        </select>
      </div>
      {limit && game && (
        <p className="muted versions-limit">
          {limit.max === 0 ? t('versions.limit.unlimited', { count: limit.count }) : t('versions.limit.max', { count: limit.count, max: limit.max })}{limit.override ? t('versions.limit.override') : t('versions.limit.global')}
        </p>
      )}
      {msg && <div className={`alert ${msg.error ? 'error' : 'ok'}`}>{errText(msg.body)}</div>}
      {list.length === 0 && (games.length === 0 ? (
        <EmptyState variant="page" icon="🎮" title={t('sync.noGames.title')}
          text={t('versions.noGames.text')}
          action={onGoSettings && <button type="button" className="btn primary" onClick={onGoSettings}>{t('common.goSettings')}</button>} />
      ) : (
        <EmptyState variant="page" icon="🗂️" title={t('versions.none.title')}
          text={t('versions.none.text')} />
      ))}
      <div className="grid">
        {list.map((v) => (
          <div className="card" key={v.version}>
            <h3>{v.version}</h3>
            {v.sources.map((s) => (
              <div className="row between version-src" key={s.source}>
                <span className="version-info"><b>{s.name || s.source}</b> · {t('files', { count: s.files })} · {s.mtime}</span>
                <button className="btn" onClick={() => restore(v.version, s.source, s.name || s.source)}>{t('versions.restore')}</button>
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
