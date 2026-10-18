# Desktop 0.7.3 security update preparation

This records the combined candidate as of 18 October 2026. Final package
qualification and publication remain pending. Published 0.7.2 assets, tags,
manifests, signatures, visibility and latest-release pointers remain immutable.
Finish the Android release and its historical-desktop checks before changing
desktop release state.

The candidate includes three isolated editions: Byte Team, Public and the new
everyday Home edition. Browser controls, new-tab spacing, bookmark shortcuts and
Shields are refined across all three. Home has one Personal profile and its own
installation, update and sync identities; the security editions retain both
modes and their tools. Android 0.1.2 separately adds Home and explains actual
connection errors without assuming every failure is encrypted DNS.

The desktop OneCRL snapshot was fetched and authenticated on 18 October, with
1,901 records and 1,256 enabled revocations. Candidate-only Gecko 158 checks
verified the Mozilla production signature chain, tamper rejection and native
revocation storage. [The security-data record](security-data-2026-10-18.json)
preserves that scope. It does not replace final-package qualification or add
the desktop offline snapshot system to Android.

## Verified inputs on 17 October 2026

The official LibreWolf release API reports stable `158.0-1`, published
`2026-10-13T22:08:40Z`, with the same x64 package formats used by Cyphra.

- Release API: https://librewolf.dev/api/v1/repos/librewolf/bsys6/releases/latest
- Exact release: https://librewolf.dev/librewolf/bsys6/releases/tag/158.0-1
- Official combined checksums: https://dl.librewolf.net/librewolf/158.0-1/sha256sums.txt
- Mozilla security advisory: https://www.mozilla.org/en-US/security/advisories/mfsa2026-106/

Mozilla rates this advisory **high**, announced 13 October 2026 and fixed in
Firefox 158. Its shared browser-engine fixes justify upgrading Cyphra's inherited
157.0.1 engine; the advisory does not establish exploitability of each individual
issue under Cyphra's configuration. Do not describe the advisory as critical.

| Input | Verified bytes | SHA-256 |
| --- | ---: | --- |
| Windows x64 package ZIP | 171165374 | `2934abbdf51fd82f60afb29728d82d562eeeeea69a8808d642a5449c3bb67d5f` |
| Linux x64 package tar.xz | 103856740 | `34bb7296feec0c6823abdfaf4fd50e47e9eada9cb4a5ed16e111a951dc9eb16c` |

The exact archive and checksum URLs are:

- https://dl.librewolf.net/librewolf/158.0-1/librewolf-158.0-1-windows-x86_64-package.zip
- https://dl.librewolf.net/librewolf/158.0-1/librewolf-158.0-1-windows-x86_64-package.zip.sha256sum
- https://dl.librewolf.net/librewolf/158.0-1/librewolf-158.0-1-linux-x86_64-package.tar.xz
- https://dl.librewolf.net/librewolf/158.0-1/librewolf-158.0-1-linux-x86_64-package.tar.xz.sha256sum

Both complete archives were fetched into this isolated checkout's ignored
`cache/` and verified against those official checksums. This initial input
inspection did not unpack, execute, rebrand or package them. A later, separately
scoped Linux candidate observation is recorded below. The hashes in
`engine-lock.json` now pin these exact inputs; `scripts/fetch-engine.py` refuses
a mismatched file and `scripts/stage.py` validates the unmodified native
executable/library payload before branding.

The matching official source endpoint returned HTTP 200 with Content-Length
1181473241:
https://librewolf.dev/api/packages/librewolf/generic/librewolf-source/158.0-1/librewolf-158.0-1.source.tar.gz

That 1.18 GB source archive was not downloaded or hashed. Preserve this exact
corresponding-source link and Cyphra's integration source archive for recipients;
a successful HEAD request is availability evidence, not source-content or
license-completeness verification. The previous release's Mozilla source stamp
and Linux build ID are not reused as identifiers for the new engine. Read the
actual new `application.ini` and `platform.ini` during staging and retain them
with the release provenance.

## Inspected original engine metadata

The initial metadata inspection read only the two original INI members in each
verified archive, without bulk extraction or a runtime launch. Both platforms
identify Mozilla release revision `eb9a6e3a736802c8e080a76c44dc81f409d99d54`.

| Platform | Application INI BuildID | Platform INI BuildID | Compiled toolkit / native platformBuildID |
| --- | --- | --- | --- |
| Windows x64 | `20261013185353` | `20261013200924` | `20261013185353` |
| Linux x64 | `20261013185131` | `20261013200303` | `20261013185131` |

`docs/desktop-engine-158-provenance.json` preserves the exact member paths, SHA-256 hashes, sizes and parsed contents with the pinned archive identities. Staging and final package audit still need to prove that the actual shipped inputs match these values.

The native APIs and packaged INIs expose different facts. At the exact pinned
Mozilla revision, `nsXULAppInfo::GetAppBuildID` returns `gAppData->buildID`, while
`GetPlatformBuildID` returns `gToolkitBuildID`, generated from `MOZ_BUILDID` in the
native toolkit. The latter does not read `platform.ini`. Candidate-only Linux
execution measured both API IDs as `20261013185131` while its unchanged packaged
platform INI reads `20261013200303`. A complete hash-verified Windows archive
and `xul.dll` stream inspection found the sole 13 October build-date constant
`20261013185353`; actual Windows API execution remains pending. The Windows
migration harness separately reads the installed INIs and requires those pins
alongside both native API observations. No input identifier is rewritten to make
these separate observations agree.

## Remaining qualification and release work

Keep the combined Android, Home and desktop source changes when completing
release preparation. Their version schedules and signing identities remain
separate. Earlier isolated desktop preparation commits are now integrated;
their input inspection alone does not qualify the final combined source.

1. Inspect the verified archives' layout and actual native source/build IDs.
   Stage all three editions and both platforms. Confirm branding remains complete,
   native code stays unchanged apart from documented Windows presentation
   resources, source references match, no new default service makes unsolicited
   connections, and every locked privacy/DNS preference still applies.
2. Run source policy tests, Linux updater/rollback tests and native Gecko,
   Home, UI, profile isolation, Shields, appearance, Settings, Tools and sync
   checks for both security-edition modes and Home's Personal profile. Inspect ordinary-user native previews.
   Refresh dated security data only through its authenticated existing process
   if the current snapshot requires updating, then repeat affected checks.
3. Complete actual native Windows 0.7.2-to-0.7.3 migration in both profiles,
   fresh-profile install, same-version reinstall, profile retention and uninstall qualification. Repeat browser compatibility checks
   against Gecko 158; a matching archive hash does not prove compatibility.
   Home requires its separate first-release install/reinstall and preservation
   checks; no historical Home release exists for an upgrade claim.
4. Update README/public download names, release notes and validation records
   with actual 0.7.3 qualification results, then freeze all three repositories and
   produce matching source ZIPs. Candidate README download names now target
   0.7.3; published 0.7.2 assets remain unchanged until the new release is ready.
5. Build and sign new 0.7.3 update manifests with the appropriate separately held
   edition keys. Preserve the independent Android release family. Publish new
   desktop tags/releases, validate actual older-client GitHub updates, all remote
   assets/digests and all historical release invariants, then copy verified
   releases into `/mnt/mybook/cyphra/0.7.3/` and its `public/` subfolder.
   Never replace a 0.7.2 asset or reuse its signature for different bytes.

After sufficient disk space is reserved and the emulator is stopped, the initial
build commands are the existing interfaces:

```sh
python3 scripts/fetch-engine.py windows linux
python3 scripts/stage.py windows linux --edition team
python3 scripts/stage.py windows linux --edition public
python3 scripts/stage.py windows linux --edition home
python3 scripts/build-windows.py --edition team
python3 scripts/build-windows.py --edition public
python3 scripts/build-windows.py --edition home
python3 scripts/build-linux.py --edition team
python3 scripts/build-linux.py --edition public
python3 scripts/build-linux.py --edition home
python3 scripts/build-source.py --edition team
python3 scripts/build-source.py --edition public
python3 scripts/build-source.py --edition home
npm test
python3 -m unittest discover -s tests -p test_updates.py -v
```

Native checks must run sequentially on this host and use the installed
Marionette/X11 qualification environment. Existing `CYPHRA_TEST_EDITION` and
`CYPHRA_TEST_MODE` select the native smoke-test edition/mode. For appearance,
pass the actual Team or Public Linux stage to `tests/appearance-native.py`.
`tests/github-release-native.py --edition both --version 0.7.3` is an actual
published-release check and belongs after publication. The hosted Windows
workflow must use a fresh 0.7.3 source freeze and release evidence; do not edit
or reuse 0.7.2 attestations. New evidence directories and release-specific guards
must preserve all historical desktop/Android releases.
