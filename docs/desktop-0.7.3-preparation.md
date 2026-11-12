# Desktop 0.7.3 preparation

This candidate combines the Home, Public and Byte Team editions. Home keeps one
Personal profile; Public and Byte Team retain Work/Personal profiles and tools.
The spacing, new tab, bookmark shortcuts, Shields and customization are refined
across all three. Final package, UI and updater qualification remain separate
from the source and engine observations recorded here.

## Current verified engine inputs

LibreWolf **160.0-1**, published 11 November 2026 at 02:28:59 UTC, inherits
Gecko 160.0 and Mozilla's [10 November security fixes](https://www.mozilla.org/en-US/security/advisories/mfsa2026-125/).
The upstream release includes the November security fixes and a LibreWolf
support-link correction. These upstream changes do not replace Cyphra's final UI checks.

| Input | Verified bytes | SHA-256 |
| --- | ---: | --- |
| Windows x64 ZIP | 173346524 | `c5a0de0c0ebe7d95659cbf2c4b2a012963d0587a8337b1ac19a7f870fdade5c3` |
| Linux x64 tar.xz | 105279732 | `7c751d4d279f05a2514298599ad3c43d4e85dd011ad2ecc07319c5a8c34a72e5` |

Both complete archives were downloaded, hashed against their official package
API, [release manifest](https://dl.librewolf.net/librewolf/160.0-1/sha256sums.txt)
and checksum sidecars, then separately read back from disk. Old engine inputs
and published releases remain unchanged. `engine-lock.json` pins the URLs and
hashes; exact original INIs, native payload hashes and source semantics are in
[the 160 engine provenance](desktop-engine-160-provenance.json).

Both platforms identify Mozilla revision
`d84e7a6936554efe26097d9d9b24a0e11330e630`.

| Platform | Application INI | Platform INI | Compiled toolkit | Native API observation |
| --- | --- | --- | --- | --- |
| Windows | `20261111005253` | `20261111005253` | `20261110235730` | Pending |
| Linux | `20261111003723` | `20261111003723` | `20261110235326` | Pending |

The toolkit IDs were read from the Windows PE `mozbldid` section and Linux
ELF `mzbldid` note in the complete verified original native files. At the exact
base source revision, `Services.appinfo.appBuildID` returns application metadata;
`platformBuildID` returns compiled `gToolkitBuildID`. Matching application and
platform INIs do not make the compiled toolkit ID equal. Final native Windows
and Linux checks must assert the separate exact values above.

The matching [LibreWolf source archive](https://librewolf.dev/api/packages/librewolf/generic/librewolf-source/160.0-1/librewolf-160.0-1.source.tar.gz)
returned HTTP 200 to HEAD, with 1189768011 bytes. The official package API and
checksum sidecar agree on
`a2901ce211dce6c250cbe04a1324f239f9bb99d87b288cfa8e09da206e684e38`.
The source archive body was not downloaded or hashed; availability does not
establish complete corresponding-source or license verification. The exact
source link and Cyphra's integration source must accompany releases.

The actual 160 AppConstants retain disabled data reporting, telemetry reporting,
crash reporting, Normandy and upstream updating, with the sandbox enabled.
The packaged Remote Settings client entry module is unchanged. Its `Utils` adds
an upstream environment-variable disable guard; Cyphra retains its existing
managed privacy policy and early request gate. The single Brave Search configuration and signed offline certificate loader
remain mandatory. Gecko 160 can choose a new search schema via a stored feature
preference. Cyphra explicitly binds both the native schema gate and collection
getter to its own bundled single-provider v2 data; an old v3 preference cannot
select upstream provider data. The unmodified native selector uses empty v2
overrides. The fresh-source routing regression tests cover both preference values. Small fixtures made from actual 160 resource bytes
verified the current branding/search transformations for every edition; these
bounded source checks do not qualify the complete staged resources or runtime.

## Authenticated certificate data

The maintained desktop snapshot fetched 11 November contains 1,959 published
records (1,955 unique identities), signed 10 November at 22:03:26.673 UTC. All
records are enforced, including 697 with `enabled: false` source metadata.
Every previously maintained identity and every identity in the official 160
packaged set is retained. The new P-384 signer was qualified on 12 November
using actual Gecko 160 `ContentSignatureProdRoot`: the exact signed data passed,
and changed timestamp/record data failed. The candidate loader submitted 1,959
ENFORCE states and zero UNSET states. Synthetic issuer/serial and subject/key
certificates became revoked while the untouched control stayed valid, including
after repeat installation. This is candidate signer/mapping qualification, not
a final branded package/UI pass or validation of every real certificate. The
[dated observation](security-data-2026-11-12.json) records the scope. No live
Mozilla service is contacted by the release-bundled loader.

The earlier 158.0.1-2 Linux candidate ran as an ordinary user in a new network namespace
without external routes. Its native Mozilla production-root verifier accepted
the snapshot and rejected timestamp/record tampering. Native revocation storage
already had the bundled startup data; installation of the newly fetched snapshot
returned `NS_OK`. This is historical candidate-only engine/security evidence; it does not
qualify Gecko 160, a final Cyphra package, UI or Windows. [The dated observation](security-data-2026-10-26.json)
records exact engine, data and report hashes. That earlier storage-completion
observation does not establish the corrected all-record mapping or a native
per-identity result. The [27 October candidate check](security-data-2026-10-27.json)
subsequently ran the corrected actual loader: all 1,907 published records
(1,903 unique identities) were submitted as enforced, with none unset. Synthetic
issuer/serial and subject/key targets changed from valid to revoked while an
untouched control remained valid, including after repeat installation. This
proves the tested identity mechanisms; it does not validate every real-world
certificate individually or qualify the final UI/packages. The historical
[18 October](security-data-2026-10-18.json) and
[21 October](security-data-2026-10-21.json) observations retain their original scope.

Android separately pins GeckoView 160.0 and retains that AAR's official packaged
OneCRL startup data. The desktop maintenance snapshot and its UI are not ported
to Android. No platform claims a continuously current revocation service.

## Release sequence and remaining checks

Finish Android 0.1.2 and its preservation checks before capturing the desktop
release boundary. Keep all published 0.7.2/0.1.1 tags, assets, signatures, bodies,
visibility and release pointers unchanged until a verified new release is ready.

1. Freeze all three corresponding source heads. Run fresh source checks and
   stage each edition on Windows and Linux from the pinned inputs.
2. Build and sign exact installers, Linux packages, corresponding source archives
   and update manifests with the separate existing edition keys.
3. Run native Gecko, UI, Home, Shields, appearance, DNS, tools, sync, isolation,
   persistence and updater/rollback checks on the actual final stages. Review
   ordinary-user screenshots. Home has its own first-release checks.
4. Qualify real Windows 0.7.2-to-0.7.3 migration of both existing modes, plus fresh
   install, same-version reinstall and uninstall with complete profile retention.
   Home has no historical upgrade claim; check its install/reinstall separately.
5. Publish new GitHub releases, exercise actual older clients against the signed
   published assets, verify every asset and all historical invariants, then copy
   exact releases with full readback to `/mnt/mybook/cyphra/0.7.3/`, including
   `public/` and `home/`. No earlier release asset may be replaced.

Candidate source checks and earlier native diagnostics cannot substitute for
these final package checks. Release evidence must record each actual source
commit, signed payload, execution time, result and material limitation.
