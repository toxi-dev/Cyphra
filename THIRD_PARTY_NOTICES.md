# Third-party notices

Cyphra's original launcher, browser chrome, configuration overrides, and integration code are licensed under MPL-2.0. The top-left C/shield logo is original Cyphra branding. Cyphra is an independent distribution and is not endorsed by Mozilla, LibreWolf, Ghostery, or EasyList. It contains no Brave code, Electron, or Chromium engine.

## Gecko / LibreWolf / Firefox

The staged engine uses the verified executable/library payload from LibreWolf **158.0-1**, based on Firefox/Gecko **158.0**. Its configuration is deliberately modified for Cyphra. The original runtime license notices and `about:license` content are preserved, including licenses of Mozilla and third-party components. The exact inherited Mozilla source revision and platform build IDs remain in each bundled `application.ini`/`platform.ini`; these identifiers are not replaced by Cyphra branding. See `engine-lock.json` for exact binary archive URLs, hashes, and source locations.

The verified upstream Windows and Linux archives both identify Mozilla source revision `eb9a6e3a736802c8e080a76c44dc81f409d99d54`. Windows application/platform **INI** build IDs are `20261013185353` / `20261013200924`; Linux application/platform **INI** build IDs are `20261013185131` / `20261013200303`. Gecko's native `Services.appinfo.platformBuildID` instead returns the compiled toolkit identifier: `20261013185353` on Windows and `20261013185131` on Linux. These independently recorded facts are not interchangeable. Original INI member hashes/contents, native source semantics, full Windows `xul.dll` hash and candidate-only Linux native observations are recorded in `docs/desktop-engine-158-provenance.json`. They do not establish final release/UI or native Windows qualification.

- LibreWolf source/build scripts: https://librewolf.dev/librewolf/source and https://librewolf.dev/librewolf/bsys6
- Exact LibreWolf source archive: https://librewolf.dev/api/packages/librewolf/generic/librewolf-source/158.0-1/librewolf-158.0-1.source.tar.gz
- License statement: https://librewolf.net/license-disclaimers/

The corresponding source code for the unmodified engine is available at the exact upstream source location above. Cyphra's matching source archive contains all original integration modifications, configuration changes, and build instructions. Provide both the Cyphra archive and this engine source location to binary recipients. Cyphra has not rebuilt or re-signed the inherited engine; installed interface resources and application metadata are rebranded as Cyphra. Upstream legal attribution, source identifiers, compatibility identifiers and original binary filenames remain.

## Local filter matcher

`@ghostery/adblocker` and its MPL-2.0 helpers are used as a bundled local JavaScript parser/matcher, not as the Ghostery extension or analytics service. MIT domain-parsing dependencies retain their notices. Full runtime matcher dependency license texts are bundled in `browser/vendor/LICENSES.txt`; exact versions/resolved source archives are pinned in `package-lock.json`. Generated legal comments are preserved in `browser/vendor/adblock.js.LEGAL.txt`.

Source projects: https://github.com/ghostery/adblocker and https://github.com/remusao/tldts . The runtime bundle is reproducible with `npm ci --ignore-scripts && npm run bundle`. No dependency modifications are made. Covered dependency source is available from its upstream repository and exact npm source archive named in the lockfile.

## EasyList and EasyPrivacy

Attribution: **The EasyList authors**, https://easylist.to/ . Unchanged bundled files are separate local filter data, with exact official URLs, hashes, and timestamp in `browser/filters/manifest.json`. The lists are offered under GPL-3.0-or-later OR CC-BY-SA-3.0-or-later; Cyphra selects **CC-BY-SA-3.0** for these unchanged copies. Preserve their original headers and attribution. The selected license is included in `docs/CC-BY-SA-3.0.txt`. A compiled, integrity-checked matcher snapshot is generated from these lists with unsafe cosmetic rules removed. Source data files remain unchanged; their attribution and license also apply to the generated snapshot.

Sources: https://easylist.to/easylist/easylist.txt and https://easylist.to/easylist/easyprivacy.txt . License statement: https://easylist.to/pages/licence.html .

## Native launcher / installer and development tools

The Windows launcher uses the MinGW-w64 startup/runtime code and Windows system APIs. Preserve the MinGW runtime notices, including ZPL-2.1 and public-domain/per-file notices, in `docs/licenses/mingw-runtime.txt`. The NSIS installer stub uses its respective licenses and distribution exception; preserve `docs/licenses/NSIS.txt`. There is no included proprietary DRM plugin, updater service, or commercial SDK.

Build-only tools retain their licenses: esbuild (MIT), MinGW-w64 (its per-file notices), NSIS (its component notices), and Mozilla Marionette (MPL-2.0). They are not browser telemetry clients. The browser runtime does not include the development Python or Node toolchains.

Redistribute these notices, Cyphra's MPL license, all inherited runtime notices, the matcher notices, exact filter source files/manifest, and corresponding source locations with the matching application source archive. This text does not replace upstream license requirements.


## Windows executable branding

Cyphra's Windows packaging starts from the verified upstream LibreWolf/Gecko
executable. The packaged copy receives Cyphra icon and Windows version-info
resource changes so the taskbar and shell identify the running product as
Cyphra. This resource branding does not replace Gecko executable code and does
not remove the upstream licensing and attribution notices.

## Mozilla OneCRL security data

The release contains Mozilla’s signed OneCRL records, signature metadata and certificate chain from the official Firefox Remote Settings security-state collection. The snapshot is dated, verified offline and installed into Gecko certificate storage. See `browser/security/README.md` and its manifest for source URLs, hashes and provenance. Mozilla source/data retain applicable Mozilla licensing and attribution. No Mozilla service connection is made by this runtime loader.

## Build-only resource editor

Windows icon/version resources are edited with rcedit 2.0.0 (MIT), https://github.com/electron/rcedit/tree/v2.0.0 . Exact binary input is pinned in `tools-lock.json`; license is in `docs/licenses/rcedit-MIT.txt`. The resource editor itself is not shipped in the browser runtime. Native engine code sections remain unchanged by resource branding.
