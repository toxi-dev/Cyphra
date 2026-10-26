# Cyphra

An independent, open-source Gecko browser for Windows and Linux. Version **0.7.3** uses verified LibreWolf 158.0.1-2 / Gecko 158.0.1 engine inputs. Cyphra has no Chromium runtime, browser telemetry, advertisements on its home page, or required team account.

For everyday browsing without the security workspace, [Cyphra Home](https://github.com/toxi-dev/Cyphra-Home) is a separate edition with one Personal profile, a simpler new tab and the same core ad blocking and update checks. This Cyphra edition keeps its Work mode and tools.

## Install

Download a complete package from [Cyphra 0.7.3 releases](https://github.com/toxi-dev/Cyphra/releases/tag/v0.7.3).

- Windows x64: run [Cyphra-Public-0.7.3-win-x64.exe](https://github.com/toxi-dev/Cyphra/releases/download/v0.7.3/Cyphra-Public-0.7.3-win-x64.exe), or extract the entire [Windows ZIP](https://github.com/toxi-dev/Cyphra/releases/download/v0.7.3/Cyphra-Public-0.7.3-win-x64.zip) and run `Cyphra.exe`.
- Linux x64: extract [Cyphra-Public-0.7.3-linux-x64.tar.gz](https://github.com/toxi-dev/Cyphra/releases/download/v0.7.3/Cyphra-Public-0.7.3-linux-x64.tar.gz), then run `./Cyphra/cyphra` as your desktop account. GTK/NSS desktop libraries, Python 3.9+ and util-linux `flock` are required.

The public edition installs separately from Cyphra Team and does not use its profiles, sync server, update credentials, or releases.

## Personal and Work

Personal is the public edition's default. It uses balanced local filtering, native cookie partitioning and fingerprint protection, with WebGL available for compatibility. Work starts with Strict Shields, stronger fingerprint resistance and WebGL disabled. Neither mode disables certificate validation, the content sandbox or the telemetry deny rules.

The profile control opens the other mode in its own browser process. Cookies, logins, bookmarks, history and settings stay separate. On Windows, profiles live under `%LOCALAPPDATA%\Cyphra\Profile` (Work) and `Profile-Personal`. On Linux, they live under `${XDG_CONFIG_HOME:-~/.config}/cyphra-public/profile` and `profile-personal`. Installers retain them across updates. A mode is a collection of defaults, not a promise of perfect security; explicit choices in that profile are retained.

## Appearance

Choose Graphite, Black, Light or System themes, restrained accents, toolbar density, rail/sidebar sizes and home layouts from Settings → Appearance. Changes apply immediately and are saved separately in each profile. Reset clears visual choices while keeping browsing data, DNS, privacy, sync and update credentials. See [all customization controls](docs/desktop-customization.md).

## Browsing

Brave Search is the sole search provider. Cyphra Shields shows actual blocked requests, with site exceptions and optional details. Focus view removes the rail and bookmarks toolbar while keeping navigation and the address bar visible. Tools offers native page inspection, network monitoring, console, screenshots, tab search and local URL/Base64/JSON/SHA-256 utilities. Import browser data only when you choose it.

The script-free home page can show local bookmark shortcuts and cached security headlines. CISA, NCSC and PortSwigger news fetches run only on a manual refresh; no remote images, scripts or fonts are loaded. Private windows cannot refresh news or manage sync/update credentials.

## DNS, sync and updates

Settings → DNS lets you choose System DNS, Quad9, Cloudflare, Toxitech or your own HTTPS endpoint. Public Cyphra initially follows system DNS. Selecting an encrypted resolver uses strict DNS-over-HTTPS with no silent plaintext fallback. The diagnostic queries the actual selected resolver. These controls change only Cyphra's profile, never the computer's network configuration.

Optional sync requires a server you configure and a private pairing code. New vaults bind to the edition and mode, so Work and Personal cannot accidentally share a vault. Bookmarks, selected ordinary preferences and mode-specific Shield exceptions are encrypted before upload; passwords, cookies, history, tabs, DNS choices and fingerprint/WebGL mode defaults are excluded.

Public GitHub updates do not need a token. Automatic checks default off. A release must match the pinned public-edition ECDSA signature and package hash/size before installation; checks never install silently. Windows and Linux updates preserve external profiles and refuse downgrades or active installations. The Windows installer is unsigned: the release signature is separate from Windows Authenticode.

## Android

Cyphra Android **0.1.2** uses native Android controls and GeckoView, with separate Work/Personal profiles, local Shields, Brave Search, selectable DNS, manual encrypted bookmark sync and verified APK updates. Android 10 or later is required. See [Android installation, build and privacy details](android/README.md). Android releases use `android-v0.1.2` independently of desktop releases.

## Build

Use Linux, Node 22+, Python 3.12+, MinGW-w64 and NSIS 3.11+, plus Wine for Windows resource branding. Engine and tool downloads are pinned by SHA-256. Build-only toolchains are not browser runtimes.

```sh
npm ci --ignore-scripts
npm run bundle
npm test
python3 scripts/fetch-engine.py
python3 scripts/fetch-branding-tools.py
python3 scripts/stage.py windows linux --edition public
python3 scripts/build-windows.py --edition public
python3 scripts/build-linux.py --edition public
python3 scripts/build-source.py --edition public
```

Output is in `dist/0.7.3/public/`. The release signer requires the separately held maintainer key; no private signing key is present here.

## Privacy and licenses

Browser telemetry, upstream data reporting, studies and upstream update services are disabled. Known telemetry endpoints remain blocked even with site Shields off. Local filters and a signed offline certificate-revocation snapshot ship with the application. They require maintenance in new releases; this browser does not currently provide a full phishing/malware URL database or continuously refreshed CRLite coverage. Website tracking cannot be universally prevented by endpoint lists.

Original Cyphra code uses MPL-2.0. Gecko, local matcher dependencies and filters retain their licenses and source attribution in `THIRD_PARTY_NOTICES.md`, `engine-lock.json` and `package-lock.json`. Give binary recipients matching Cyphra source and the exact upstream engine source listed there.

Check the release’s qualification records for completed native Windows and Linux tests and any pending checks. Supplementary Wine checks do not establish native Windows compatibility. Compatibility on individual PCs and independent security auditing are outside those checks.
