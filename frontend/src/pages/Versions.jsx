import React, { useEffect, useState } from 'react';
import { labelOf } from '#src/lib/names.js';
import EmptyState from '#src/components/ui/EmptyState.jsx';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { Alert, Button, Select } from '#src/components/ui/index.js';
import { getVersionsLimit, listVersions, restoreVersion } from '#src/lib/api/versions.js';

export default function Versions({ config, onGoSettings }) {
  const { t } = useI18n();
  const games = Object.keys(config.games);
  const [game, setGame] = useState(games[0] || '');
  const [list, setList] = useState([]);
  const [msg, setMsg] = useState(null); // {error?, body}: `body` es un error o respuesta con {code, params} (se traduce al pintar)
  const [limit, setLimit] = useState(null);

  const load = (g) =>
    g
      ? listVersions(g)
          .then(setList)
          .catch((e) => setMsg({ error: true, body: e }))
      : setList([]);
  const loadLimit = (g) =>
    g
      ? getVersionsLimit(g)
          .then(setLimit)
          .catch(() => setLimit(null))
      : setLimit(null);
  useEffect(() => {
    load(game);
    loadLimit(game);
  }, [game, config]); // eslint-disable-line react-hooks/exhaustive-deps

  const restore = async (version, source, sourceName) => {
    if (!window.confirm(t('versions.confirm', { version, source: sourceName }))) return;
    try {
      const r = await restoreVersion(game, version, source);
      setMsg({ body: r });
      load(game);
      loadLimit(game);
    } catch (e) {
      setMsg({ error: true, body: e });
    }
  };

  return (
    <section className={list.length === 0 ? 'fill' : undefined}>
      <div className="row between versions-head">
        <h2>{t('versions.title')}</h2>
        <Select
          aria-label={t('versions.gameAria')}
          value={game}
          onChange={(e) => {
            setGame(e.target.value);
            setMsg(null);
          }}
          options={games.map((g) => ({
            value: g,
            label: labelOf(config.games, g) + (config.games[g].enabled === false ? ` ${t('versions.disabledSuffix')}` : ''),
          }))}
        />
      </div>
      {limit && game && (
        <p className="muted versions-limit">
          {limit.max === 0
            ? t('versions.limit.unlimited', { count: limit.count })
            : t('versions.limit.max', { count: limit.count, max: limit.max })}
          {limit.override ? t('versions.limit.override') : t('versions.limit.global')}
        </p>
      )}
      {game && config.games[game]?.enabled === false && (
        <Alert variant="info" compact>
          {t('versions.disabledNote')}
        </Alert>
      )}
      {msg && <Alert variant={msg.error ? 'error' : 'ok'}>{errText(msg.body)}</Alert>}
      {list.length === 0 &&
        (games.length === 0 ? (
          <EmptyState
            variant="page"
            icon="🎮"
            title={t('sync.noGames.title')}
            text={t('versions.noGames.text')}
            action={
              onGoSettings && (
                <Button variant="primary" onClick={onGoSettings}>
                  {t('common.goSettings')}
                </Button>
              )
            }
          />
        ) : (
          <EmptyState variant="page" icon="🗂️" title={t('versions.none.title')} text={t('versions.none.text')} />
        ))}
      <div className="grid">
        {list.map((v) => (
          <div className="card" key={v.version}>
            <h3>{v.version}</h3>
            {v.sources.map((s) => (
              <div className="row between version-src" key={s.source}>
                <span className="version-info">
                  <b>{s.name || s.source}</b> · {t('files', { count: s.files })} · {s.mtime}
                </span>
                <Button onClick={() => restore(v.version, s.source, s.name || s.source)}>{t('versions.restore')}</Button>
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
