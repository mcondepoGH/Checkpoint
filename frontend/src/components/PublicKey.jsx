import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { errText, useI18n } from '../useI18n.js';
import { Alert, Button } from './ui/index.js';

function copyText(text, area) {
  return (async () => {
    try { await navigator.clipboard.writeText(text); return true; } catch { /* HTTP en LAN: sin API de portapapeles */ }
    const ta = area || document.createElement('textarea');
    if (!area) { ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta); }
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch { ok = false; }
    if (!area) document.body.removeChild(ta);
    return ok;
  })();
}

function CodeBlock({ text }) {
  const { t } = useI18n();
  const [ok, setOk] = useState(false);
  const copy = async () => {
    const r = await copyText(text);
    setOk(r);
    if (r) setTimeout(() => setOk(false), 2000);
  };
  return (
    <div className="codeblock">
      <pre><code>{text}</code></pre>
      <Button onClick={copy}>{ok ? t('common.copied') : t('common.copy')}</Button>
    </div>
  );
}

const LINUX_KEY = (k) => `mkdir -p ~/.ssh && chmod 700 ~/.ssh\necho "${k}" >> ~/.ssh/authorized_keys\nchmod 600 ~/.ssh/authorized_keys`;

// Cada paso: [id del paso (claves `keyhelp.step.<id>.title|hint`), comando]. Los comandos no se traducen.
function osSteps(os, distro, k) {
  if (os === 'Windows') {
    return [
      ['winServer', 'Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0\nStart-Service sshd; Set-Service sshd -StartupType Automatic'],
      ['winUser', `New-Item -ItemType Directory -Force "$env:USERPROFILE\\.ssh" | Out-Null\nAdd-Content -Path "$env:USERPROFILE\\.ssh\\authorized_keys" -Value '${k}'`],
      ['winAdmin', `Add-Content -Path "C:\\ProgramData\\ssh\\administrators_authorized_keys" -Value '${k}'\nicacls "C:\\ProgramData\\ssh\\administrators_authorized_keys" /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"`],
    ];
  }
  if (distro === 'Arch Linux') {
    return [
      ['archInstall', 'sudo pacman -S --needed openssh\nsudo systemctl enable --now sshd'],
      ['archFirewall', '# ufw\nsudo ufw allow 22/tcp\n# firewalld\nsudo firewall-cmd --permanent --add-service=ssh && sudo firewall-cmd --reload'],
      ['linuxKey', LINUX_KEY(k)],
    ];
  }
  return [
    ['debInstall', 'sudo apt update && sudo apt install -y openssh-server\nsudo systemctl enable --now ssh'],
    ['debFirewall', 'sudo ufw allow 22/tcp'],
    ['linuxKey', LINUX_KEY(k)],
  ];
}

// Pestañas accesibles: flechas, Inicio y Fin; tabindex itinerante.
function Tabs({ label, idBase, items, value, onChange, small }) {
  const refs = useRef({});
  const onKey = (e) => {
    const i = items.indexOf(value);
    let n = -1;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') n = (i + 1) % items.length;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') n = (i - 1 + items.length) % items.length;
    else if (e.key === 'Home') n = 0;
    else if (e.key === 'End') n = items.length - 1;
    if (n < 0) return;
    e.preventDefault();
    onChange(items[n]);
    refs.current[items[n]]?.focus();
  };
  return (
    <div role="tablist" aria-label={label} className={'keytabs' + (small ? ' sub' : '')} onKeyDown={onKey}>
      {items.map((o) => (
        <Button key={o} ref={(el) => { refs.current[o] = el; }} role="tab" id={`${idBase}-tab-${o}`} aria-selected={value === o} aria-controls={`${idBase}-panel`} tabIndex={value === o ? 0 : -1} className={'tab' + (value === o ? ' active' : '')} onClick={() => onChange(o)}>{o}</Button>
      ))}
    </div>
  );
}

function Step({ n, title, hint, children }) {
  return (
    <li className="keystep">
      <span className="keystep-n" aria-hidden="true">{n}</span>
      <div className="keystep-body">
        <h4>{title}</h4>
        {hint && <p className="muted">{hint}</p>}
        {children}
      </div>
    </li>
  );
}

const SYSTEMS = ['Windows', 'Linux'];
const DISTROS = ['Debian / Ubuntu', 'Arch Linux'];

function KeyHelp({ pubKey, children }) {
  const { t, rich } = useI18n();
  const PH = t('keyhelp.placeholder'); // marcador dentro de los comandos, hasta que haya clave
  const [open, setOpen] = useState(false);
  const [sys, setSys] = useState('Linux');
  const [distro, setDistro] = useState(DISTROS[0]);
  const k = pubKey || PH;
  const steps = osSteps(sys, distro, k);
  return (
    <div className="keyhelp">
      <div className="keyhelp-head">
        <div className="keyhelp-intro">{children}</div>
        <Button className="chip" aria-label={t('keyhelp.infoAria')} title={t('keyhelp.infoTitle')} aria-expanded={open} aria-controls="keyhelp-panel" onClick={() => setOpen(!open)}>?</Button>
      </div>
      {open && (
        <div id="keyhelp-panel" className="keyhelp-panel">
          <p className="muted keyhelp-lead">{rich('keyhelp.lead')}</p>
          <ol className="keysteps">
            <Step n={1} title={t('keyhelp.s1.title')} hint={t('keyhelp.s1.hint')}>
              <p className="muted">{rich('keyhelp.s1.text', { copy: t('common.copy') })}</p>
            </Step>
            <Step n={2} title={t('keyhelp.s2.title')} hint={t('keyhelp.s2.hint')}>
              <Tabs label={t('keyhelp.tabs.system')} idBase="ks-sys" items={SYSTEMS} value={sys} onChange={setSys} />
              {sys === 'Linux' && <Tabs label={t('keyhelp.tabs.distro')} idBase="ks-distro" items={DISTROS} value={distro} onChange={setDistro} small />}
              <div role="tabpanel" id={sys === 'Linux' ? 'ks-distro-panel' : 'ks-sys-panel'} aria-labelledby={sys === 'Linux' ? `ks-distro-tab-${distro}` : 'ks-sys-tab-Windows'} className="keypanel">
                {!pubKey && <p className="muted">{rich('keyhelp.noKey', { placeholder: PH })}</p>}
                <ol className="keysubsteps">
                  {steps.map(([id, cmd], i) => (
                    <li key={id} className="keysub">
                      <h5><span className="keysub-n" aria-hidden="true">{String.fromCharCode(97 + i)}</span>{t(`keyhelp.step.${id}.title`)}</h5>
                      <p className="muted">{t(`keyhelp.step.${id}.hint`)}</p>
                      <CodeBlock text={cmd} />
                    </li>
                  ))}
                </ol>
                <p className="muted">{rich('keyhelp.oneLine')}</p>
                <CodeBlock text="ssh-ed25519 AAAAC3Nza...XXXX checkpoint" />
                {sys === 'Windows' && <p className="muted">{t('keyhelp.windowsNote')}</p>}
              </div>
            </Step>
            <Step n={3} title={t('keyhelp.s3.title')} hint={t('keyhelp.s1.hint')}>
              <p className="muted">{rich('keyhelp.s3.text', { test: t('device.test'), ok: t('err.transport.connection_ok') })}</p>
            </Step>
          </ol>
          <Alert variant="warn">{rich('keyhelp.warn')}</Alert>
        </div>
      )}
    </div>
  );
}

export default function PublicKey() {
  const { t, rich } = useI18n();
  const [key, setKey] = useState('');
  const [err, setErr] = useState(null); // error de la API (se traduce al pintar)
  const [copied, setCopied] = useState(false);
  const area = useRef(null);

  useEffect(() => {
    api('/api/ssh/public-key').then((r) => setKey(r.public_key)).catch((e) => setErr(e));
  }, []);

  const copy = async () => {
    const ok = await copyText(key, area.current);
    setCopied(ok);
    if (ok) setTimeout(() => setCopied(false), 2000);
  };

  return (
    <details className="card pubkey">
      <summary>{t('keyhelp.summary')}</summary>
      <KeyHelp pubKey={key}>
        <p className="muted">{rich('keyhelp.intro')}</p>
      </KeyHelp>
      {err && <Alert variant="error">{errText(err)}</Alert>}
      {key && (
        <>
          <label htmlFor="pubkey-text" className="sr-only">{t('keyhelp.summary')}</label>
          <textarea id="pubkey-text" ref={area} readOnly rows={3} value={key} onFocus={(e) => e.target.select()} />
          <div className="row">
            <Button onClick={copy}>{copied ? t('keyhelp.copied') : t('common.copy')}</Button>
          </div>
        </>
      )}
    </details>
  );
}
