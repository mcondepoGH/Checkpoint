// Pasos de la ayuda de la clave pública SSH (funciones puras, sin React).
// Cada paso: { id (claves `keyhelp.step.<id>.title|hint`), cmds: [{ text, label? }] }.
// Un comando = una card con su propio «Copiar». `label` es una clave i18n opcional (alternativas: se ELIGE una).
// Las cadenas con && donde el segundo depende del primero son un solo comando. Los comandos no se traducen.
const cmd = (text, label) => (label ? { text, label } : { text });

const linuxKey = (k) => ({
  id: 'linuxKey',
  cmds: [cmd('mkdir -p ~/.ssh && chmod 700 ~/.ssh'), cmd(`echo "${k}" >> ~/.ssh/authorized_keys`), cmd('chmod 600 ~/.ssh/authorized_keys')],
});

export function osSteps(os, distro, k) {
  if (os === 'Windows') {
    return [
      { id: 'winServer', cmds: [cmd('Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0'), cmd('Start-Service sshd'), cmd('Set-Service sshd -StartupType Automatic')] },
      { id: 'winUser', cmds: [cmd('New-Item -ItemType Directory -Force "$env:USERPROFILE\\.ssh" | Out-Null'), cmd(`Add-Content -Path "$env:USERPROFILE\\.ssh\\authorized_keys" -Value '${k}'`)] },
      { id: 'winAdmin', cmds: [cmd(`Add-Content -Path "C:\\ProgramData\\ssh\\administrators_authorized_keys" -Value '${k}'`), cmd('icacls "C:\\ProgramData\\ssh\\administrators_authorized_keys" /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"')] },
    ];
  }
  if (distro === 'Arch Linux') {
    return [
      { id: 'archInstall', cmds: [cmd('sudo pacman -S --needed openssh'), cmd('sudo systemctl enable --now sshd')] },
      { id: 'archFirewall', alt: true, cmds: [cmd('sudo ufw allow 22/tcp', 'keyhelp.alt.ufw'), cmd('sudo firewall-cmd --permanent --add-service=ssh && sudo firewall-cmd --reload', 'keyhelp.alt.firewalld')] },
      linuxKey(k),
    ];
  }
  return [
    { id: 'debInstall', cmds: [cmd('sudo apt update && sudo apt install -y openssh-server'), cmd('sudo systemctl enable --now ssh')] },
    { id: 'debFirewall', cmds: [cmd('sudo ufw allow 22/tcp')] },
    linuxKey(k),
  ];
}
