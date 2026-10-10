/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */
import { NEWS_FEEDS, MAX_FEED_BYTES, MAX_ARTICLES, parseNewsFeed, normalizeNewsCache } from './news-policy.sys.mjs';
import { setTimeout, clearTimeout } from 'resource://gre/modules/Timer.sys.mjs';

const activeRequests = new Map();
let cachePromise;
let refreshPromise;
let lastErrors = [];
const cachePath = () => PathUtils.join(PathUtils.profileDir, 'cyphra-news.json');
async function readCache() {
  if (!cachePromise) cachePromise = (async () => {
    try {
      if ((await IOUtils.stat(cachePath())).size > MAX_FEED_BYTES) return normalizeNewsCache(null);
      return normalizeNewsCache(await IOUtils.readJSON(cachePath()));
    } catch { return normalizeNewsCache(null); }
  })();
  return cachePromise;
}
async function fetchFeed(feed) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  activeRequests.set(feed.url, (activeRequests.get(feed.url) || 0) + 1);
  try {
    const response = await fetch(feed.url, {
      method: 'GET', credentials: 'omit', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', signal: controller.signal,
      headers: { Accept: 'application/rss+xml, text/xml;q=0.9, application/xml;q=0.8' },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    if (Number(response.headers.get('content-length')) > MAX_FEED_BYTES) throw new Error('The feed is too large.');
    if (!response.body) throw new Error('The publisher returned an empty response.');
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8', { fatal: true });
    let bytes = 0;
    let xml = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > MAX_FEED_BYTES) { await reader.cancel(); throw new Error('The feed is too large.'); }
      xml += decoder.decode(value, { stream: true });
    }
    xml += decoder.decode();
    return parseNewsFeed(xml, feed.id);
  } finally {
    clearTimeout(timeout);
    const left = (activeRequests.get(feed.url) || 1) - 1;
    if (left) activeRequests.set(feed.url, left); else activeRequests.delete(feed.url);
  }
}
export const News = {
  isActiveFeedRequest(url, method) { return method === 'GET' && activeRequests.has(url); },
  async state() { return { ...(await readCache()), errors: [...lastErrors], busy: Boolean(refreshPromise), sources: NEWS_FEEDS.map(({ id, label, home }) => ({ id, label, home })) }; },
  async refresh({ isPrivate = false } = {}) {
    if (isPrivate) throw new Error('News refresh is available in a normal window. Private tabs make no news requests.');
    if (refreshPromise) return refreshPromise;
    refreshPromise = (async () => {
      const previous = await readCache();
      const results = await Promise.allSettled(NEWS_FEEDS.map(fetchFeed));
      const articles = [];
      lastErrors = [];
      let succeeded = 0;
      results.forEach((result, index) => {
        const feed = NEWS_FEEDS[index];
        if (result.status === 'fulfilled') { articles.push(...result.value); succeeded += 1; }
        else {
          lastErrors.push({ source: feed.label, message: String(result.reason?.message || 'Feed request failed.').slice(0, 180) });
          articles.push(...previous.articles.filter(item => item.source === feed.id));
        }
      });
      articles.sort((a, b) => (b.published || 0) - (a.published || 0));
      const updated = succeeded ? Date.now() : previous.updated;
      const cache = normalizeNewsCache({ updated, articles: articles.slice(0, MAX_ARTICLES) });
      if (succeeded) {
        await IOUtils.writeJSON(cachePath(), cache, { tmpPath: `${cachePath()}.tmp` });
        await IOUtils.setPermissions(cachePath(), 0o600);
        cachePromise = Promise.resolve(cache);
      }
      return { ...cache, errors: [...lastErrors], busy: false, sources: NEWS_FEEDS.map(({ id, label, home }) => ({ id, label, home })) };
    })();
    try { return await refreshPromise; } finally { refreshPromise = null; }
  },
};
