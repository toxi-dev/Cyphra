# Cyphra home and security news

The new-tab page uses Brave Search and a local magnifying-glass submit button. It contains links to the private Cyphra repository, PortSwigger Web Security Academy, OWASP's Web Security Testing Guide and MITRE ATT&CK. The shortcuts section reads up to 12 ordinary HTTP(S) bookmarks directly from the native bookmarks toolbar. It does not read history or fetch favicons.

Security briefing shows real RSS headlines from [CISA](https://www.cisa.gov/cybersecurity-advisories/alerts.xml), [NCSC](https://www.ncsc.gov.uk/api/1/services/v1/all-rss-feed.xml) and [PortSwigger Research](https://portswigger.net/research/rss). Select **Load headlines** or **Refresh** to contact those three publishers. A newly opened tab reads its saved headlines from this device; it makes no news request. Private windows can read that saved public briefing but cannot refresh it.

The page loads no remote images, fonts, styles or scripts. It has no content-facing API. A Gecko window actor handles only the exact top-level Cyphra home resource and its trusted controls. The actor can read the native toolbar bookmarks, toggle the native bookmarks sidebar or ask the parent process to refresh the three fixed feed URLs. A webpage cannot supply a different URL, change the private-window flag or request another privileged operation.

Feed requests omit credentials and referrers, reject redirects, time out after 12 seconds and cap each response at 512 KiB. RSS parsing rejects document types and entities, scans at most 200 items and accepts at most six entries per publisher. Article links must use HTTPS on the publisher's known host, without credentials or a custom port. Titles are bounded plain text; article HTML, descriptions, scripts and tracking images are never rendered.

The profile's `cyphra-news.json` stores a maximum of 18 public article titles, links, publication dates and the actual refresh time. The file uses owner-only permissions where the operating system supports them. The visible briefing shows up to eight current entries and links to their publishers. The cache is revalidated when read. Failed feeds keep their previous headlines and report their actual errors; an unsuccessful refresh does not invent a new timestamp. News is not included in device sync.

News publishers and Brave Search receive the requests you explicitly make to them. Cyphra sends no browsing history, cookies, passwords, settings or device identifier with feed requests. The host running Cyphra's DNS resolver necessarily receives DNS queries as configured elsewhere in the browser.
