# Cyphra Home

An everyday, open-source browser built on Gecko. Cyphra Home keeps browsing simple: Brave Search, local ad and tracker blocking, bookmarks, history, downloads, private windows and appearance controls. It has one Personal profile, with no Work workspace, cybersecurity briefing or research tools.

Cyphra Home is the third edition. [Cyphra](https://github.com/toxi-dev/Cyphra) remains the public browser with security tools and separate Work/Personal profiles. Byte Team's special edition stays separate and private. There is no Byte Team Home edition.

## Install and update

Use complete, signed-release packages from [Cyphra Home releases](https://github.com/toxi-dev/Cyphra-Home/releases). Windows packages are named `Cyphra-Home-<version>-win-x64.exe` or `.zip`; Linux packages are `Cyphra-Home-<version>-linux-x64.tar.gz`. Android packages are `Cyphra-Home-<version>-android-universal.apk` and require Android 10 or later.

On Windows, run the installer or extract the whole ZIP and open `Cyphra.exe`. On Linux, extract the whole archive and run `./Cyphra/cyphra` as your desktop user. GTK/NSS libraries, Python 3.9+ and util-linux `flock` are required. Android has its own version schedule and release tags.

Settings → Updates checks the public `toxi-dev/Cyphra-Home` repository without an account. Automatic checks start off. A download must match the Home edition's pinned ECDSA signature, repository, filename, size and SHA-256. Installing a new release preserves your external profile. Home refuses packages from the other editions. The Windows installer does not carry an Authenticode signature; Cyphra's release signature is separate.

## Your browser

The new tab contains Brave Search, your real pinned bookmarks and shortcuts to bookmarks, history and downloads. Pinned sites come from the bookmarks toolbar. It uses local assets and makes no news or advertising requests.

Settings → Appearance offers Graphite, Black, Light and System themes, five subtle accents, toolbar density, a slim shortcut rail, sidebar widths and a bookmarks toolbar. New-tab layout, search and pinned bookmarks are customizable. Resetting the appearance keeps browsing data and privacy settings.

Cyphra Shields shows requests actually blocked in the current tab. Use On/Off for site filtering, or open its details for strict filtering and recent blocked destinations. Known telemetry deny rules stay active even when filtering for a site is paused. There are no simulated performance, privacy or blocking statistics.

Home starts with balanced filtering, cookie partitioning, HTTPS upgrades and Global Privacy Control. Normal browsing history is saved on this device unless you turn it off in Settings → Privacy; private windows do not save history. WebGL stays available for compatible websites; stronger fingerprint resistance is not forced on everyday sites. Website compatibility still depends on the website, your settings and filters.

## DNS and device sync

Home follows the device's system DNS by default. Settings → DNS also offers Toxitech, Quad9, Cloudflare and a custom HTTPS resolver. An explicitly selected encrypted resolver fails visibly if it is unavailable and does not silently send the query through system DNS. These controls affect Cyphra only; they do not change the computer's network settings.

Optional device sync is manual and requires your own server and private pairing code. There is no preset Team server or required account. Bookmarks, selected ordinary settings and site filtering exceptions are encrypted before upload. Home vaults bind to `home.personal`; the other editions and Work profiles cannot pair with them. Passwords, cookies, history, tabs and DNS choices are excluded. Desktop and Android use the same scoped encrypted format.

## Separate data

Home can be installed alongside the other editions. Windows installs under `%LOCALAPPDATA%\Programs\CyphraHome` and keeps its profile at `%LOCALAPPDATA%\CyphraHome\Profile-Personal`. Linux keeps its profile in `${XDG_CONFIG_HOME:-~/.config}/cyphra-home/profile-personal`. Android's application ID is `org.cyphra.browser.home`. Home has separate update keys, profile locks, remoting names and sync vaults. Uninstalling the desktop application leaves the profile intact.

## Build and licenses

```sh
npm ci --ignore-scripts
npm run bundle
npm test
python3 scripts/fetch-engine.py
python3 scripts/fetch-branding-tools.py
python3 scripts/stage.py windows linux --edition home
python3 scripts/build-windows.py --edition home
python3 scripts/build-linux.py --edition home
python3 scripts/build-source.py --edition home
```

Build tools require Linux, Node 22+, Python 3.12+, MinGW-w64, NSIS 3.11+ and Wine for Windows resource branding. Android build instructions are in [the Android README](https://github.com/toxi-dev/Cyphra-Home/tree/main/android). Signing keys are held outside the repository and are never included in packages.

Original Cyphra code is MPL-2.0. Gecko, local matcher dependencies and filter lists retain their notices and corresponding-source references in `THIRD_PARTY_NOTICES.md`, `engine-lock.json` and `package-lock.json`. Upstream names in licenses and technical compatibility identifiers are retained where required.

Browser telemetry, studies and upstream update services are disabled. Filters and an offline certificate-revocation snapshot are bundled and maintained through releases. Cyphra does not currently provide a full phishing/malware URL database or continuously refreshed CRLite coverage; list-based blocking cannot stop every website tracker. Platform qualification and documented test results accompany each release. Automated checks are not an independent security audit.
