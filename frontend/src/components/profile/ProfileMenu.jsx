import React, { useEffect, useId, useRef, useState } from 'react';
import { ui } from '#src/lib/errors.js';
import { PHOTO_ACCEPT, photoUrl, prepareAvatar, validatePhotoFile } from './photo.js';
import { showBadge } from '#src/lib/updates.js';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import ApiKeySection from './ApiKeySection.jsx';
import Avatar from './Avatar.jsx';
import Icon from '#src/components/ui/Icon.jsx';
import LanguageSelect from './LanguageSelect.jsx';
import { Alert, Button } from '#src/components/ui/index.js';
import { deletePhoto, putPhoto } from '#src/lib/api/profile.js';

// Perfil en la cabecera: botón circular con la foto (o la silueta) y un popover anclado debajo, por grupos con separador y rótulo:
// identidad (foto), actualización (solo móvil), Preferencias (idioma, tema), Integración (API key plegable y enlace a la documentación de la API) y Cuenta (salir). Con una actualización disponible, en móvil (<480 px, por CSS) el aviso sale de la cabecera: el avatar lleva un punto
// (con texto accesible) y el menú una entrada «Actualizar a vX.Y.Z» que abre el mismo diálogo (`onUpdate`). No modal: Esc cierra y devuelve el foco al botón; pulsar fuera o sacar el foco del popover (Tab) lo cierra.
// `open` inicial solo se usa para renderizar el popup en pruebas.
export default function ProfileMenu({
  profile,
  theme,
  effectiveTheme,
  onCycleTheme,
  onLogout,
  onPhoto,
  updates = null,
  onUpdate,
  open: initialOpen = false,
}) {
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
  const hasUpdate = showBadge(updates);

  useEffect(() => {
    if (open && !initialOpen) pop.current?.focus();
  }, [open, initialOpen]);
  useEffect(() => {
    if (!open) return undefined;
    const outside = (e) => {
      if (wrap.current && !wrap.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open]);

  const close = () => {
    setOpen(false);
    setError(null);
  };
  const onKeyDown = (e) => {
    if (e.key === 'Escape' && open) {
      e.stopPropagation();
      close();
      btn.current?.focus();
    }
  };
  // relatedTarget nulo = el foco se fue a nada (clic en zona no enfocable, selector de ficheros): lo gestiona pointerdown.
  const onBlur = (e) => {
    if (open && e.relatedTarget && !wrap.current.contains(e.relatedTarget)) close();
  };

  const pick = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = ''; // permite elegir de nuevo el mismo fichero
    if (!f) return;
    const bad = validatePhotoFile(f);
    if (bad) {
      setError(ui(bad));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      let blob;
      try {
        blob = await prepareAvatar(f);
      } catch {
        throw ui('profile.photo.failed');
      }
      const r = await putPhoto(blob);
      onPhoto(r.photo);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await deletePhoto();
      onPhoto(r.photo);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- delegación de teclado (Escape/Tab) de los controles hijos
    <div className="profile" ref={wrap} onKeyDown={onKeyDown} onBlur={onBlur}>
      <Button
        ref={btn}
        variant="ghost"
        iconOnly
        className="profile-btn"
        title={t('profile.open')}
        aria-label={t(hasUpdate ? 'profile.openUpdate' : 'profile.open')}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? popId : undefined}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <Avatar src={src} />
        {hasUpdate && <i className="upd-dot" role="img" aria-label={t('profile.updateDot')} />}
      </Button>
      {open && (
        <div id={popId} className="profile-pop" role="dialog" aria-label={t('profile.title')} tabIndex={-1} ref={pop}>
          <div className="profile-head">
            <Avatar src={src} size="lg" />
            <strong className="profile-name">{profile.name || 'Checkpoint'}</strong>
            <div className="profile-photo-actions">
              <Button onClick={() => file.current?.click()} disabled={busy}>
                {t('profile.photo.change')}
              </Button>
              {src && (
                <Button variant="ghost" onClick={remove} disabled={busy}>
                  {t('profile.photo.remove')}
                </Button>
              )}
            </div>
            <input ref={file} type="file" accept={PHOTO_ACCEPT} className="sr-only" tabIndex={-1} aria-hidden="true" onChange={pick} />
          </div>
          {error && (
            <Alert variant="error" role="alert">
              {errText(error)}
            </Alert>
          )}
          {hasUpdate && (
            <Button
              variant="ghost"
              className="profile-row profile-update"
              onClick={() => {
                close();
                onUpdate?.();
              }}
            >
              <Icon name="download" />
              <span className="profile-row-label">{t('profile.update', { version: updates.ultima })}</span>
            </Button>
          )}
          <div className="profile-group" role="group" aria-labelledby={`${popId}-prefs`}>
            <h3 id={`${popId}-prefs`} className="profile-group-title">
              {t('profile.group.prefs')}
            </h3>
            <LanguageSelect row />
            <Button variant="ghost" className="profile-row profile-pref" onClick={onCycleTheme}>
              <Icon name={effectiveTheme === 'dark' ? 'moon' : 'sun'} />
              <span className="profile-row-label">{t('profile.themeLabel')}</span>
              <span className="profile-row-value">{t(`app.theme.${theme}`)}</span>
            </Button>
          </div>
          <div className="profile-group" role="group" aria-labelledby={`${popId}-integ`}>
            <h3 id={`${popId}-integ`} className="profile-group-title">
              {t('profile.group.integration')}
            </h3>
            <ApiKeySection />
            {/* Documentación OpenAPI de la API de la API key: solo se abre con sesión; pestaña nueva para no perder la web. */}
            <a className="btn ghost profile-row" href="/api/docs" target="_blank" rel="noopener">
              <Icon name="book" />
              <span className="profile-row-label">{t('profile.apidocs')}</span>
            </a>
          </div>
          <div className="profile-group" role="group" aria-labelledby={`${popId}-acct`}>
            <h3 id={`${popId}-acct`} className="profile-group-title">
              {t('profile.group.account')}
            </h3>
            <Button variant="ghost" className="profile-row" onClick={onLogout}>
              <Icon name="logout" />
              <span className="profile-row-label">{t('app.logout')}</span>
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
