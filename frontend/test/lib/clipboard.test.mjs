// copyText sin API moderna: el campo temporal no debe colgar de <body> o, al enfocarlo, el popup del perfil ve salir el foco y se cierra.
import test from 'node:test';
import assert from 'node:assert/strict';
import { copyText } from '#src/lib/clipboard.js';

const fakeDom = () => {
  const mk = (name) => ({
    name,
    children: [],
    style: {},
    appendChild(c) {
      c.parentNode = c.parentElement = this;
      this.children.push(c);
      return c;
    },
    removeChild(c) {
      this.children = this.children.filter((x) => x !== c);
    },
    select() {
      this.selectedUnder = this.parentNode;
    },
  });
  const body = mk('body');
  const popup = body.appendChild(mk('popup'));
  const button = popup.appendChild(mk('button'));
  const created = [];
  globalThis.document = {
    body,
    activeElement: button,
    createElement: () => {
      const ta = mk('textarea');
      created.push(ta);
      return ta;
    },
    execCommand: () => true,
  };
  Object.defineProperty(globalThis, 'navigator', {
    value: { clipboard: { writeText: () => Promise.reject(new Error('http')) } },
    configurable: true,
  });
  return { body, popup, created };
};

test('fallback: el campo temporal se monta junto al elemento enfocado, no en body', async () => {
  const { popup, created } = fakeDom();
  assert.equal(await copyText('k'), true);
  assert.equal(created[0].selectedUnder, popup);
  assert.equal(popup.children.includes(created[0]), false, 'se retira al acabar');
});

test('fallback: sin elemento enfocado usa body', async () => {
  const { body, created } = fakeDom();
  globalThis.document.activeElement = null;
  assert.equal(await copyText('k'), true);
  assert.equal(created[0].selectedUnder, body);
});
