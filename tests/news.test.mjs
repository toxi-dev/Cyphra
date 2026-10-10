/* MPL-2.0 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { NEWS_FEEDS, MAX_FEED_BYTES, headlineText, safeHomeURL, normalizeArticle, parseNewsFeed, normalizeNewsCache } from '../browser/modules/news-policy.sys.mjs';

const now = Date.UTC(2026, 9, 4);
const rss = items => `<?xml version="1.0"?><rss version="2.0"><channel>${items}</channel></rss>`;
const item = (title, url, date = 'Fri, 02 Oct 2026 12:00:00 GMT') => `<item><title>${title}</title><link>${url}</link><pubDate>${date}</pubDate></item>`;

test('RSS titles are plain bounded text, including CDATA, escaped markup and control characters', () => {
  assert.equal(headlineText('<![CDATA[  Advisory <b>one</b> &amp; two ]]>' ), 'Advisory one & two');
  assert.equal(headlineText('&lt;img src=x onerror=alert(1)&gt;Safe\u202ereadable'), 'Safe readable');
  assert.equal(headlineText('A'.repeat(1000)).length, 200);
  assert.equal(headlineText('Invalid &#55296; &#0; &#x110000; text'), 'Invalid text');
});

test('articles must belong to the selected primary publisher and use ordinary HTTPS', () => {
  const valid = { source: 'cisa', title: 'Real advisory', url: 'https://www.cisa.gov/news/advisory#fragment', published: '2026-10-02T12:00:00Z' };
  assert.deepEqual(normalizeArticle(valid, now), { source: 'cisa', publisher: 'CISA', title: 'Real advisory', url: 'https://www.cisa.gov/news/advisory', published: Date.UTC(2026, 9, 2, 12) });
  for (const url of ['http://www.cisa.gov/a', 'https://www.cisa.gov.evil.example/a', 'https://www.cisa.gov@evil.example/a', 'https://user:secret@www.cisa.gov/a', 'https://www.cisa.gov:8443/a', 'javascript:alert(1)', 'https://portswigger.net/a']) {
    assert.equal(normalizeArticle({ ...valid, url }, now), null, url);
  }
  assert.equal(normalizeArticle({ ...valid, source: 'invented' }, now), null);
  assert.equal(normalizeArticle({ ...valid, published: '2999-01-01' }, now).published, null);
  assert.equal(normalizeArticle({ ...valid, published: 'bad date' }, now).published, null);
});

test('RSS parser deduplicates, bounds results and rejects unsafe or non-feed data', () => {
  const one = item('<![CDATA[Defensive <b>guidance</b>]]>', 'https://www.ncsc.gov.uk/guidance/one');
  const invalid = item('Bad publisher link', 'https://evil.example/article');
  const many = Array.from({ length: 12 }, (_, index) => item(`Article ${index}`, `https://www.ncsc.gov.uk/news/${index}`)).join('');
  const parsed = parseNewsFeed(rss(one + one + invalid + many), 'ncsc', now);
  assert.equal(parsed.length, 6);
  assert.equal(parsed[0].title, 'Defensive guidance');
  assert.equal(new Set(parsed.map(article => article.url)).size, 6);
  for (const value of [rss('<!DOCTYPE x SYSTEM "file:///etc/passwd">' + one), rss('<!ENTITY y "payload">' + one), 'X'.repeat(MAX_FEED_BYTES + 1), '<html><body>Not RSS</body></html>']) {
    assert.throws(() => parseNewsFeed(value, 'ncsc', now));
  }
  assert.throws(() => parseNewsFeed(rss(invalid), 'ncsc', now));
});

test('local cache is revalidated instead of trusting stored article URLs or timestamps', () => {
  const valid = { source: 'portswigger', title: 'Research', url: 'https://portswigger.net/research/one', published: null };
  const cached = normalizeNewsCache({ updated: now - 1000, articles: [valid, { ...valid, url: 'https://evil.example/' }] }, now);
  assert.equal(cached.articles.length, 1);
  assert.equal(cached.updated, now - 1000);
  assert.equal(normalizeNewsCache({ updated: now + 1, articles: null }, now).updated, null);
  assert.deepEqual(normalizeNewsCache(null, now), { updated: null, articles: [] });
});

test('bookmark shortcuts keep ordinary team HTTP(S) links and exclude executable or credential URLs', () => {
  assert.equal(safeHomeURL('http://127.0.0.1:8080/team'), 'http://127.0.0.1:8080/team');
  assert.equal(safeHomeURL('https://github.com/toxi-dev/Cyphra-Browser'), 'https://github.com/toxi-dev/Cyphra-Browser');
  for (const value of ['javascript:alert(1)', 'file:///tmp/local', 'data:text/html,test', 'https://token@example.com/', 'https://example.com/\nsecret', 'https://example.com/' + 'x'.repeat(2048)]) assert.equal(safeHomeURL(value), null);
  assert.equal(NEWS_FEEDS.length, 3);
  assert.equal(new Set(NEWS_FEEDS.map(feed => feed.url)).size, 3);
});
