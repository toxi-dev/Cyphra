/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */
'use strict';
// getRandomValues also works on ordinary HTTP pages; randomUUID is restricted
// to secure contexts and would break Personal-mode protection on those pages.
const documentId = [...crypto.getRandomValues(new Uint8Array(16))].map(value=>value.toString(16).padStart(2,'0')).join('');

// This isolated content world does not install a window-message listener,
// expose native objects, inspect form values, or receive commands from websites.
async function relay(message) {
  if (message?.type !== 'stats' || !message.snapshot || !Number.isInteger(message.tabId)) return;
  await browser.runtime.sendNativeMessage('cyphra', {type: 'bind', tabId: message.tabId, documentId, snapshot: message.snapshot}).catch(() => {});
}

browser.runtime.onMessage.addListener(message => {
  if(message?.type === 'document-context') return Promise.resolve({url: location.href, documentId});
  relay(message);
});
browser.runtime.sendMessage({type: 'snapshot', documentId}).then(message => relay({...message, type: 'stats'})).catch(() => {});
window.addEventListener('pageshow', event => {
  if (event.persisted) browser.runtime.sendMessage({type: 'snapshot', documentId}).then(message => relay({...message, type: 'stats'})).catch(() => {});
});

async function cosmetics() {
  const classes = new Set();
  const ids = new Set();
  for (const element of [...document.querySelectorAll('[class], [id]')].slice(0, 2048)) {
    if (element.id) ids.add(element.id);
    for (const token of element.classList) if (classes.size < 2048) classes.add(token);
  }
  const response = await browser.runtime.sendMessage({type: 'cosmetics', classes: [...classes], ids: [...ids]}).catch(() => null);
  const css = response?.styles;
  if (typeof css !== 'string' || !css || /@(?:import|namespace)|url\s*\(|\/\*/i.test(css)) return;
  const style = document.createElement('style');
  style.textContent = css;
  (document.head || document.documentElement)?.appendChild(style);
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', cosmetics, {once: true});
else cosmetics();
