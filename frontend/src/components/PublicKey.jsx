import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { errText } from '../useI18n.js';

const PH = 'PEGA_AQUÍ_LA_CLAVE';

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
  const [ok, setOk] = useState(false);
  const copy = async () => {
    const r = await copyText(text);
    setOk(r);
    if (r) setTimeout(() => setOk(false), 2000);
  };
  return (
    <div className="codeblock">
      <pre><code>{text}</code></pre>
      <button type="button" className="btn" onClick={copy}>{ok ? 'Copiado' : 'Copiar'}</button>
    </div>
  );
}

const LINUX_KEY = (k) => `mkdir -p ~/.ssh && chmod 700 ~/.ssh\necho "${k}" >> ~/.ssh/authorized_keys\nchmod 600 ~/.ssh/authorized_keys`;

// Cada paso: [título corto, una línea de explicación, comando]
function osSteps(os, distro, k) {
  if (os === 'Windows') {
    return [
      ['Activar el servidor OpenSSH', 'En PowerShell abierto como administrador.', 'Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0\nStart-Service sshd; Set-Service sshd -StartupType Automatic'],
      ['Pegar la clave (usuario normal)', 'En PowerShell, con el usuario con el que se conectará Checkpoint.', `New-Item -ItemType Directory -Force "$env:USERPROFILE\\.ssh" | Out-Null\nAdd-Content -Path "$env:USERPROFILE\\.ssh\\authorized_keys" -Value '${k}'`],
      ['Pegar la clave (usuario administrador)', 'Si ese usuario es administrador, la clave va en otro fichero. PowerShell como administrador.', `Add-Content -Path "C:\\ProgramData\\ssh\\administrators_authorized_keys" -Value '${k}'\nicacls "C:\\ProgramData\\ssh\\administrators_authorized_keys" /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"`],
    ];
  }
  if (distro === 'Arch Linux') {
    return [
      ['Instalar y activar el servidor SSH', 'En una terminal. El servicio se llama sshd.', 'sudo pacman -S --needed openssh\nsudo systemctl enable --now sshd'],
      ['Abrir el puerto 22 (solo si hay firewall)', 'Arch no trae firewall activo por defecto. Usa el que tengas.', '# ufw\nsudo ufw allow 22/tcp\n# firewalld\nsudo firewall-cmd --permanent --add-service=ssh && sudo firewall-cmd --reload'],
      ['Pegar la clave en authorized_keys', 'Como el usuario con el que se conectará Checkpoint (sin sudo).', LINUX_KEY(k)],
    ];
  }
  return [
    ['Instalar y activar el servidor SSH', 'En una terminal. El servicio se llama ssh.', 'sudo apt update && sudo apt install -y openssh-server\nsudo systemctl enable --now ssh'],
    ['Abrir el puerto 22 (solo si ufw está activo)', 'Comprueba antes con sudo ufw status.', 'sudo ufw allow 22/tcp'],
    ['Pegar la clave en authorized_keys', 'Como el usuario con el que se conectará Checkpoint (sin sudo).', LINUX_KEY(k)],
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
        <button key={o} ref={(el) => { refs.current[o] = el; }} type="button" role="tab" id={`${idBase}-tab-${o}`} aria-selected={value === o} aria-controls={`${idBase}-panel`} tabIndex={value === o ? 0 : -1} className={'btn tab' + (value === o ? ' active' : '')} onClick={() => onChange(o)}>{o}</button>
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
  const [open, setOpen] = useState(false);
  const [sys, setSys] = useState('Linux');
  const [distro, setDistro] = useState(DISTROS[0]);
  const k = pubKey || PH;
  const steps = osSteps(sys, distro, k);
  return (
    <div className="keyhelp">
      <div className="keyhelp-head">
        <div className="keyhelp-intro">{children}</div>
        <button type="button" className="btn chip" aria-label="Info: pasos para dar de alta la clave" title="Info" aria-expanded={open} aria-controls="keyhelp-panel" onClick={() => setOpen(!open)}>?</button>
      </div>
      {open && (
        <div id="keyhelp-panel" className="keyhelp-panel">
          <p className="muted keyhelp-lead">Checkpoint usa su propia clave SSH para entrar, sin contraseña, a cada dispositivo y copiar sus partidas. Hay que dar de alta la parte <strong>pública</strong> en cada dispositivo.</p>
          <ol className="keysteps">
            <Step n={1} title="Copia la clave" hint="En esta web.">
              <p className="muted">Pulsa <strong>Copiar</strong> bajo la caja de la clave pública. Es la clave de Checkpoint: no hay que generar ninguna en tu PC.</p>
            </Step>
            <Step n={2} title="Pégala en el dispositivo remoto" hint="En cada dispositivo al que se conecta Checkpoint. Elige su sistema.">
              <Tabs label="Sistema del dispositivo remoto" idBase="ks-sys" items={SYSTEMS} value={sys} onChange={setSys} />
              {sys === 'Linux' && <Tabs label="Distribución Linux" idBase="ks-distro" items={DISTROS} value={distro} onChange={setDistro} small />}
              <div role="tabpanel" id={sys === 'Linux' ? 'ks-distro-panel' : 'ks-sys-panel'} aria-labelledby={sys === 'Linux' ? `ks-distro-tab-${distro}` : 'ks-sys-tab-Windows'} className="keypanel">
                {!pubKey && <p className="muted">Aún no hay clave visible: sustituye <code>{PH}</code> por la clave copiada.</p>}
                <ol className="keysubsteps">
                  {steps.map(([title, hint, cmd], i) => (
                    <li key={title} className="keysub">
                      <h5><span className="keysub-n" aria-hidden="true">{String.fromCharCode(97 + i)}</span>{title}</h5>
                      <p className="muted">{hint}</p>
                      <CodeBlock text={cmd} />
                    </li>
                  ))}
                </ol>
                <p className="muted">En <code>authorized_keys</code> la clave ocupa una sola línea, con este aspecto:</p>
                <CodeBlock text="ssh-ed25519 AAAAC3Nza...XXXX checkpoint" />
                {sys === 'Windows' && <p className="muted">Deja el shell por defecto (cmd.exe) y usa un usuario local.</p>}
              </div>
            </Step>
            <Step n={3} title="Comprueba la conexión" hint="En esta web.">
              <p className="muted">En la tarjeta del dispositivo, pulsa <strong>Probar conexión</strong>. Debe responder <code>conexión OK</code>. La primera vez guarda la huella del dispositivo.</p>
            </Step>
          </ol>
          <div className="alert warn">Pega solo la clave pública (una línea que empieza por <code>ssh-ed25519</code>). NUNCA una clave privada.</div>
        </div>
      )}
    </div>
  );
}

export default function PublicKey() {
  const [key, setKey] = useState('');
  const [err, setErr] = useState('');
  const [copied, setCopied] = useState(false);
  const area = useRef(null);

  useEffect(() => {
    api('/api/ssh/public-key').then((r) => setKey(r.public_key)).catch((e) => setErr(errText(e)));
  }, []);

  const copy = async () => {
    const ok = await copyText(key, area.current);
    setCopied(ok);
    if (ok) setTimeout(() => setCopied(false), 2000);
  };

  return (
    <details className="card pubkey">
      <summary>Clave pública SSH</summary>
      <KeyHelp pubKey={key}>
        <p className="muted">Cópiala y añádela a <code>authorized_keys</code> de cada dispositivo. Pulsa <strong>?</strong> para ver los pasos.</p>
      </KeyHelp>
      {err && <div className="alert error">{err}</div>}
      {key && (
        <>
          <label htmlFor="pubkey-text" className="sr-only">Clave pública SSH</label>
          <textarea id="pubkey-text" ref={area} readOnly rows={3} value={key} onFocus={(e) => e.target.select()} />
          <div className="row">
            <button type="button" className="btn" onClick={copy}>{copied ? 'Copiada' : 'Copiar'}</button>
          </div>
        </>
      )}
    </details>
  );
}
