// Ayuda de la clave pública: un comando por card, alternativas con etiqueta, sin comentarios dentro de los comandos.
import test from 'node:test';
import assert from 'node:assert/strict';
import { en, es, flat } from '../../helpers/locales.mjs';
import { osSteps } from '#src/components/keyhelp/keyhelpSteps.js';

const K = 'ssh-ed25519 AAAATESTKEY checkpoint';
const load = (l) => Object.fromEntries(flat({ es, en }[l]));
const ES = load('es');
const EN = load('en');
const texts = (st) => st.map((s) => s.cmds.map((c) => c.text));
const CASES = [['Windows', 'x'], ['Linux', 'Debian / Ubuntu'], ['Linux', 'Arch Linux']];

test('nº de pasos y de cards por sistema/distro', () => {
  assert.deepEqual(osSteps('Windows', 'x', K).map((s) => [s.id, s.cmds.length]), [['winServer', 3], ['winUser', 2], ['winAdmin', 2]]);
  assert.deepEqual(osSteps('Linux', 'Debian / Ubuntu', K).map((s) => [s.id, s.cmds.length]), [['debInstall', 2], ['debFirewall', 1], ['linuxKey', 3]]);
  assert.deepEqual(osSteps('Linux', 'Arch Linux', K).map((s) => [s.id, s.cmds.length]), [['archInstall', 2], ['archFirewall', 2], ['linuxKey', 3]]);
});

test('cada comando es una sola línea y no contiene comentarios `# `', () => {
  for (const [os, d] of CASES) for (const s of osSteps(os, d, K)) for (const c of s.cmds) {
    assert.ok(!c.text.includes('\n'), `${s.id}: salto de línea`);
    assert.ok(!/(^|\s)# /.test(c.text), `${s.id}: comentario en «${c.text}»`);
    assert.ok(!/;\s*(Set|Start)-/.test(c.text), `${s.id}: sentencias PowerShell unidas`);
  }
});

test('Arch: ufw y firewalld son alternativas con etiqueta traducida; el resto sin etiqueta', () => {
  const st = osSteps('Linux', 'Arch Linux', K);
  const fw = st.find((s) => s.id === 'archFirewall');
  assert.equal(fw.alt, true);
  assert.deepEqual(fw.cmds.map((c) => c.label), ['keyhelp.alt.ufw', 'keyhelp.alt.firewalld']);
  assert.equal(fw.cmds[0].text, 'sudo ufw allow 22/tcp');
  assert.equal(fw.cmds[1].text, 'sudo firewall-cmd --permanent --add-service=ssh && sudo firewall-cmd --reload');
  for (const s of st.filter((x) => x.id !== 'archFirewall')) for (const c of s.cmds) assert.equal(c.label, undefined);
  for (const L of [ES, EN]) for (const c of fw.cmds) assert.ok(typeof L[c.label] === 'string' && L[c.label].length > 0, c.label);
});

test('las && dependientes siguen siendo un solo comando', () => {
  assert.ok(texts(osSteps('Linux', 'Debian / Ubuntu', K))[0].includes('sudo apt update && sudo apt install -y openssh-server'));
  assert.equal(texts(osSteps('Linux', 'Arch Linux', K))[2][0], 'mkdir -p ~/.ssh && chmod 700 ~/.ssh');
});

test('Linux: clave interpolada en su propio echo y chmod 600 aparte', () => {
  for (const d of ['Debian / Ubuntu', 'Arch Linux']) {
    const key = osSteps('Linux', d, K).find((s) => s.id === 'linuxKey');
    assert.deepEqual(key.cmds.map((c) => c.text), ['mkdir -p ~/.ssh && chmod 700 ~/.ssh', `echo "${K}" >> ~/.ssh/authorized_keys`, 'chmod 600 ~/.ssh/authorized_keys']);
  }
});

test('Windows: PowerShell separado, clave en Add-Content, icacls aparte', () => {
  const t = texts(osSteps('Windows', 'x', K));
  assert.deepEqual(t[0], ['Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0', 'Start-Service sshd', 'Set-Service sshd -StartupType Automatic']);
  assert.ok(t[1][0].startsWith('New-Item') && t[1][1].startsWith('Add-Content') && t[1][1].includes(`'${K}'`));
  assert.ok(t[2][0].startsWith('Add-Content') && t[2][0].includes(`'${K}'`) && t[2][1].startsWith('icacls'));
});

test('textos de cada paso y claves de ayuda existen en es y en', () => {
  for (const L of [ES, EN]) {
    for (const k of ['keyhelp.inOrder', 'keyhelp.pickOne']) assert.ok(L[k], k);
    for (const [os, d] of CASES) for (const s of osSteps(os, d, K)) for (const x of ['title', 'hint']) assert.ok(L[`keyhelp.step.${s.id}.${x}`], `${s.id}.${x}`);
  }
});
