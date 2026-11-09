import React, { useEffect, useId, useRef, useState } from 'react';
import { api } from '../api.js';
import { ui } from '../errors.js';
import { PHOTO_ACCEPT, photoUrl, prepareAvatar, validatePhotoFile } from '../photo.js';
import { errText, useI18n } from '../useI18n.js';
import ApiKeySection from './ApiKeySection.jsx';
import Avatar from './Avatar.jsx';
import Icon from './Icon.jsx';
import LanguageSelect from './LanguageSelect.jsx';
import { Alert, Button } from './ui/index.js';

// Perfil en la cabecera: botón circular con la foto (o la silueta) y un popover anclado debajo con foto, idioma, tema,
// salir y la versión. No modal: Esc cierra y devuelve el foco al botón; pulsar fuera o sacar el foco del popover (Tab) lo cierra.
// `open` inicial solo se usa para renderizar el popup en pruebas.
export default function ProfileMenu({ profile, version, theme, effectiveTheme, onCycleTheme, onLogout, onPhoto, open: initialOpen = false }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(initialOpen);
  const [error, setError] = useState(null); // error de la foto (se traduce al pintar)
  const [busy, setBusy] = useState(false);
  const wrap = useRef(null);
  const btn = useRef(null);
  const pop = useRef(null);
  const file = useRef(null);
  const popId = useId();
  const src = photoUrl(profile.photo);

  useEffect(() => { if (open && !initialOpen) pop.current?.focus(); }, [open, initialOpen]);
  useEffect(() => {
    if (!open) return undefined;
    const outside = (e) => { if (wrap.current && !wrap.current.contains(e.target)) setOpen(false); };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open]);

  const close = () => { setOpen(false); setError(null); };
  const onKeyDown = (e) => { if (e.key === 'Escape' && open) { e.stopPropagation(); close(); btn.current?.focus(); } };
  // relatedTarget nulo = el foco se fue a nada (clic en zona no enfocable, selector de ficheros): lo gestiona pointerdown.
  const onBlur = (e) => { if (open && e.relatedTarget && !wrap.current.contains(e.relatedTarget)) close(); };

  const pick = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = ''; // permite elegir de nuevo el mismo fichero
    if (!f) return;
    const bad = validatePhotoFile(f);
    if (bad) { setError(ui(bad)); return; }
    setBusy(true); setError(null);
    try {
      let blob;
      try { blob = await prepareAvatar(f); } catch { throw ui('profile.photo.failed'); }
      const r = await api('/api/profile/photo', { method: 'PUT', body: blob });
      onPhoto(r.photo);
    } catch (err) { setError(err); } finally { setBusy(false); }
  };
  const remove = async () => {
    setBusy(true); setError(null);
    try { const r = await api('/api/profile/photo', { method: 'DELETE' }); onPhoto(r.photo); }
    catch (err) { setError(err); } finally { setBusy(false); }
  };

  return (
    <div className="profile" ref={wrap} onKeyDown={onKeyDown} onBlur={onBlur}>
      <Button ref={btn} variant="ghost" iconOnly className="profile-btn" title={t('profile.open')} aria-label={t('profile.open')}
        aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? popId : undefined} onClick={() => (open ? close() : setOpen(true))}>
        <Avatar src={src} />
      </Button>
      {open && (
        <div id={popId} className="profile-pop" role="dialog" aria-label={t('profile.title')} tabIndex={-1} ref={pop}>
          <div className="profile-head">
            <Avatar src={src} size="lg" />
            <strong className="profile-name">{profile.name || 'Checkpoint'}</strong>
            <div className="profile-photo-actions">
              <Button onClick={() => file.current?.click()} disabled={busy}>{t('profile.photo.change')}</Button>
              {src && <Button variant="ghost" onClick={remove} disabled={busy}>{t('profile.photo.remove')}</Button>}
            </div>
            <input ref={file} type="file" accept={PHOTO_ACCEPT} className="sr-only" tabIndex={-1} aria-hidden="true" onChange={pick} />
          </div>
          {error && <Alert variant="error" role="alert">{errText(error)}</Alert>}
          <LanguageSelect />
          <ApiKeySection />
          <Button variant="ghost" className="profile-row" onClick={onCycleTheme}>
            <Icon name={effectiveTheme === 'dark' ? 'moon' : 'sun'} />{t('profile.theme', { theme: t(`app.theme.${theme}`) })}
          </Button>
          <Button variant="ghost" className="profile-row" onClick={onLogout}>
            <Icon name="logout" />{t('app.logout')}
          </Button>
          {version && <small className="profile-version muted">{t('profile.version', { version })}</small>}
        </div>
      )}
    </div>
  );
}
