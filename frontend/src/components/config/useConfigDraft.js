import { useEffect, useMemo, useRef, useState } from 'react';
import { validateConfig } from '#src/lib/api/config.js';
import { baseKeyOf, fromConfig, hasChanges, localErrors, toConfig } from './draft.js';

// Borrador de Configuración: estado editable, validación en vivo contra el backend y aviso de cambios sin guardar.
// `onVersionChange` se llama (durante el render) cada vez que llega una versión nueva de la config.
export default function useConfigDraft({ loaded, runtime, onDirty, onVersionChange = () => {} }) {
  const [draft, setDraft] = useState(() => fromConfig(loaded.config));
  const [errors, setErrors] = useState({});
  const [validating, setValidating] = useState(false);

  // Cada versión nueva cargada (inicio, guardado, recarga) reinicia el borrador. Se hace durante el render
  // (no en un efecto): así nunca se compara un borrador viejo (p. ej. el vacío previo a la carga) con la
  // config nueva, lo que marcaba "Cambios sin guardar" sin tocar nada.
  const [draftVersion, setDraftVersion] = useState(loaded.version);
  if (draftVersion !== loaded.version) {
    setDraftVersion(loaded.version);
    setDraft(fromConfig(loaded.config));
    onVersionChange();
  }

  const local = useMemo(() => localErrors(draft, runtime), [draft, runtime]);

  const payload = useMemo(() => toConfig(draft), [draft]);
  const payloadKey = JSON.stringify(payload);
  const baseKey = useMemo(() => baseKeyOf(loaded.config), [loaded.config]);
  const dirty = hasChanges(payloadKey, baseKey, local);
  const hasLocal = Object.keys(local).length > 0;

  const dirtyRef = useRef(dirty);
  useEffect(() => {
    dirtyRef.current = dirty;
    onDirty(dirty);
  }, [dirty]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const h = (e) => {
      if (dirtyRef.current) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', h);
    return () => window.removeEventListener('beforeunload', h);
  }, []);

  // Validación en vivo (con retardo) contra el mismo validador del backend.
  const seq = useRef(0);
  useEffect(() => {
    const n = ++seq.current;
    setValidating(true);
    const timer = setTimeout(async () => {
      try {
        const r = await validateConfig(JSON.parse(payloadKey));
        if (n === seq.current) {
          setErrors(r.errors);
          setValidating(false);
        }
      } catch (e) {
        if (n === seq.current) {
          setErrors({ '': e });
          setValidating(false);
        }
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [payloadKey]);

  const patch = (list, key, p) => setDraft((d) => ({ ...d, [list]: d[list].map((x) => (x.key === key ? { ...x, ...p } : x)) }));

  return { draft, setDraft, errors, validating, local, hasLocal, payload, payloadKey, dirty, patch };
}
