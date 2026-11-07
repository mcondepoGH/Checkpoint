import React, { useEffect, useState } from 'react';
import { api } from '../api.js';
import EmptyState from '../components/EmptyState.jsx';

export default function Versions({ config, onGoSettings }) {
  const games = Object.keys(config.games);
  const [game, setGame] = useState(games[0] || '');
  const [list, setList] = useState([]);
  const [msg, setMsg] = useState(null);

  const load = (g) => g ? api(`/api/versions/${encodeURIComponent(g)}`).then(setList).catch((e) => setMsg({ error: true, text: e.message })) : setList([]);
  useEffect(() => { load(game); }, [game]);

  const restore = async (version, source) => {
    if (!window.confirm(`¿Restaurar ${version}/${source} en el hub? La copia actual del hub se guarda como versión.`)) return;
    try {
      const r = await api(`/api/versions/${encodeURIComponent(game)}/restore`, { method: 'POST', body: { version, source } });
      setMsg({ text: r.message }); load(game);
    } catch (e) { setMsg({ error: true, text: e.message }); }
  };

  return (
    <section className={list.length === 0 ? 'fill' : undefined}>
      <div className="row between">
        <h2>Versiones</h2>
        <select value={game} onChange={(e) => { setGame(e.target.value); setMsg(null); }}>
          {games.map((g) => <option key={g}>{g}</option>)}
        </select>
      </div>
      {msg && <div className={`alert ${msg.error ? 'error' : 'ok'}`}>{msg.text}</div>}
      {list.length === 0 && (games.length === 0 ? (
        <EmptyState variant="page" icon="🎮" title="Sin juegos configurados"
          text="Cuando añadas un juego y se sincronice, aquí aparecerán sus versiones guardadas."
          action={onGoSettings && <button type="button" className="btn primary" onClick={onGoSettings}>Ir a Configuración</button>} />
      ) : (
        <EmptyState variant="page" icon="🗂️" title="Sin versiones guardadas"
          text="Aún no hay versiones de este juego. Se guardan automáticamente al sobrescribir una copia durante la sincronización." />
      ))}
      <div className="grid">
        {list.map((v) => (
          <div className="card" key={v.version}>
            <h3>{v.version}</h3>
            {v.sources.map((s) => (
              <div className="row between" key={s.source}>
                <span><b>{s.source}</b> · {s.files} ficheros · {s.mtime}</span>
                <button className="btn" onClick={() => restore(v.version, s.source)}>Restaurar</button>
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
