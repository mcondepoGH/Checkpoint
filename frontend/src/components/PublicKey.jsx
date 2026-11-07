import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';

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

function osSteps(os, k) {
  if (os === 'Linux') {
    return [
      ['Activar el servidor SSH, Debian / Ubuntu y derivadas (el servicio se llama ssh)', 'sudo apt install openssh-server && sudo systemctl enable --now ssh'],
      ['Activar el servidor SSH, Arch Linux y derivadas (el servicio se llama sshd)', 'sudo pacman -S --needed openssh && sudo systemctl enable --now sshd'],
      ['Activar el servidor SSH, Fedora y Steam Deck (el servicio se llama sshd). En Steam Deck, en modo escritorio, fija antes una contraseña con passwd si no tiene', 'sudo systemctl enable --now sshd'],
      ['Firewall (solo si está activo): ufw, o firewalld', 'sudo ufw allow 22/tcp\n# firewalld:\nsudo firewall-cmd --permanent --add-service=ssh && sudo firewall-cmd --reload'],
      ['Añadir la clave a authorized_keys', `mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo "${k}" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys`],
    ];
  }
  return [
    ['Activar el servidor OpenSSH (PowerShell como administrador; o Configuración > Aplicaciones > Características opcionales > Servidor OpenSSH)', 'Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0\nStart-Service sshd; Set-Service sshd -StartupType Automatic'],
    ['Usuario normal: añadir la clave a su authorized_keys (PowerShell)', `New-Item -ItemType Directory -Force "$env:USERPROFILE\\.ssh" | Out-Null\nAdd-Content -Path "$env:USERPROFILE\\.ssh\\authorized_keys" -Value '${k}'`],
    ['Usuario administrador: la clave va en otro fichero (PowerShell como administrador)', `Add-Content -Path "C:\\ProgramData\\ssh\\administrators_authorized_keys" -Value '${k}'\nicacls "C:\\ProgramData\\ssh\\administrators_authorized_keys" /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"`],
  ];
}

function KeyHelp({ pubKey, children }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState('Linux');
  const k = pubKey || PH;
  return (
    <div className="keyhelp">
      <div className="keyhelp-head">
        <div className="keyhelp-intro">{children}</div>
        <button type="button" className="btn chip" aria-label="Info: pasos para dar de alta la clave" title="Info" aria-expanded={open} aria-controls="keyhelp-panel" onClick={() => setOpen(!open)}>?</button>
      </div>
      {open && (
        <div id="keyhelp-panel" className="keyhelp-panel">
          <h4>1. Para qué sirve</h4>
          <p className="muted">savesync genera su propia clave SSH. savesync (el servidor) la usa para entrar por SSH, sin contraseña, a cada dispositivo (PC, Steam Deck) y copiar sus partidas. Hay que dar de alta la parte <strong>pública</strong> en cada dispositivo.</p>

          <h4>2. En esta web: copia la clave</h4>
          <p className="muted">Pulsa <strong>Copiar</strong> bajo la caja de la clave pública. Es la clave de savesync (no hay que generar ninguna en tu PC).</p>

          <h4>3. En el dispositivo remoto: pégala en authorized_keys</h4>
          <p className="muted">Haz esto en cada dispositivo al que savesync se conecta. Elige su sistema:</p>
          <div role="tablist" aria-label="Sistema del dispositivo remoto" className="row">
            {['Linux', 'Windows'].map((o) => (
              <button key={o} type="button" role="tab" aria-selected={tab === o} className={'btn tab' + (tab === o ? ' active' : '')} onClick={() => setTab(o)}>{o}</button>
            ))}
          </div>
          <div role="tabpanel">
            {!pubKey && <p className="muted">Aún no hay clave visible: sustituye <code>{PH}</code> por la clave copiada.</p>}
            {osSteps(tab, k).map(([label, cmd]) => (
              <div key={label}><p className="muted">{label}</p><CodeBlock text={cmd} /></div>
            ))}
            <p className="muted">La línea resultante en <code>authorized_keys</code> es una sola línea:</p>
            <CodeBlock text="ssh-ed25519 AAAAC3Nza...XXXX savesync" />
            {tab === 'Windows' && <p className="muted">Deja el shell por defecto (cmd.exe) y usa un usuario local.</p>}
          </div>

          <h4>4. Comprueba la conexión</h4>
          <p className="muted">En esta web, en la tarjeta del dispositivo, pulsa <strong>Probar conexión</strong>. Debe responder <code>conexión OK</code>. La primera vez guarda la huella del dispositivo.</p>

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
    api('/api/ssh/public-key').then((r) => setKey(r.public_key)).catch((e) => setErr(e.message));
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
