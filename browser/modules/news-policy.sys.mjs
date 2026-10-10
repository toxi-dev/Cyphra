/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. https://mozilla.org/MPL/2.0/ */

export const NEWS_FEEDS = Object.freeze([
  Object.freeze({ id: 'cisa', label: 'CISA', url: 'https://www.cisa.gov/cybersecurity-advisories/alerts.xml', home: 'https://www.cisa.gov/news-events/cybersecurity-advisories', hosts: ['www.cisa.gov', 'cisa.gov'] }),
  Object.freeze({ id: 'ncsc', label: 'NCSC', url: 'https://www.ncsc.gov.uk/api/1/services/v1/all-rss-feed.xml', home: 'https://www.ncsc.gov.uk/section/keep-up-to-date', hosts: ['www.ncsc.gov.uk', 'ncsc.gov.uk'] }),
  Object.freeze({ id: 'portswigger', label: 'PortSwigger', url: 'https://portswigger.net/research/rss', home: 'https://portswigger.net/research', hosts: ['portswigger.net'] }),
]);
export const MAX_FEED_BYTES = 512 * 1024;
export const MAX_ARTICLES = 18;

const ENTITIES = Object.freeze({ amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' });
function decodeEntities(value) {
  return value.replace(/&(#(?:x[0-9a-f]+|\d+)|[a-z]+);/gi, (whole, entity) => {
    if (entity[0] !== '#') return ENTITIES[entity.toLowerCase()] ?? whole;
    const hex = entity[1]?.toLowerCase() === 'x';
    const cp = Number.parseInt(entity.slice(hex ? 2 : 1), hex ? 16 : 10);
    return cp > 0 && cp <= 0x10ffff && !(cp >= 0xd800 && cp <= 0xdfff) ? String.fromCodePoint(cp) : '';
  });
}
export function headlineText(value) {
  if (typeof value !== 'string') return '';
  return decodeEntities(value.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, '$1').replace(/<[^>]*>/g, ' '))
    .replace(/<[^>]*>/g, ' ').replace(/[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069]/g, ' ')
    .replace(/\s+/g, ' ').trim().slice(0, 200);
}
export function safeHomeURL(value) {
  if (typeof value !== 'string' || value.length > 2048 || /[\u0000-\u0020\u007f]/.test(value)) return null;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    return url.href;
  } catch { return null; }
}
export function normalizeArticle(value, now = Date.now()) {
  if (!value || typeof value !== 'object') return null;
  const feed = NEWS_FEEDS.find(item => item.id === value.source);
  const title = headlineText(value.title);
  const urlString = safeHomeURL(value.url);
  if (!feed || !title || !urlString) return null;
  const url = new URL(urlString);
  if (url.protocol !== 'https:' || url.port || !feed.hosts.includes(url.hostname)) return null;
  url.hash = '';
  const parsed = typeof value.published === 'number' ? value.published : Date.parse(value.published || '');
  const published = Number.isFinite(parsed) && parsed > 0 && parsed <= now + 86400000 ? parsed : null;
  return { source: feed.id, publisher: feed.label, title, url: url.href, published };
}
export function parseNewsFeed(xml, source, now = Date.now()) {
  if (typeof xml !== 'string' || xml.length > MAX_FEED_BYTES || /<!\s*(?:DOCTYPE|ENTITY)\b/i.test(xml)) throw new Error('The publisher returned an unsafe or oversized feed.');
  if (!NEWS_FEEDS.some(item => item.id === source) || !/<rss\b/i.test(xml)) throw new Error('The publisher did not return an RSS feed.');
  const field = (item, tag) => item.match(new RegExp(`<${tag}(?:\\s[^>]*)?>([\\s\\S]*?)<\\/${tag}\\s*>`, 'i'))?.[1] || '';
  const result = [];
  const seen = new Set();
  const items = xml.matchAll(/<item(?:\s[^>]*)?>([\s\S]*?)<\/item\s*>/gi);
  let scanned = 0;
  for (const match of items) {
    if (++scanned > 200) break;
    const rawURL = decodeEntities(field(match[1], 'link').replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, '$1').trim());
    const article = normalizeArticle({ source, title: field(match[1], 'title'), url: rawURL, published: field(match[1], 'pubDate') || field(match[1], 'dc:date') }, now);
    if (!article || seen.has(article.url)) continue;
    result.push(article); seen.add(article.url);
    if (result.length === 6) break;
  }
  if (!result.length) throw new Error('No valid headlines were found in this feed.');
  return result;
}
export function normalizeNewsCache(value, now = Date.now()) {
  if (!value || typeof value !== 'object') return { updated: null, articles: [] };
  const updated = Number.isFinite(value.updated) && value.updated > 0 && value.updated <= now ? value.updated : null;
  const articles = Array.isArray(value.articles) ? value.articles.slice(0, MAX_ARTICLES).map(item => normalizeArticle(item, now)).filter(Boolean) : [];
  return { updated, articles };
}
