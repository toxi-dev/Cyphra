# Desktop 0.7.3 preparation

This candidate combines the Home, Public and Byte Team editions. Home keeps one
Personal profile; Public and Byte Team retain Work/Personal profiles and tools.
The spacing, new tab, bookmark shortcuts, Shields and customization are refined
across all three. Final package, UI and updater qualification remain separate
from the source and engine observations recorded here.

## Current verified engine inputs

LibreWolf **158.0.1-2**, published 22 October 2026, inherits Gecko 158.0.1 and
Mozilla's [20 October security fixes](https://www.mozilla.org/en-US/security/advisories/mfsa2026-111/).
The `-2` revision backports startup installation of packaged OneCRL data, so
revocations do not depend on a remote sync completing. Both executable/library
payloads and their actual build identities changed from `-1`.

| Input | Verified bytes | SHA-256 |
| --- | ---: | --- |
| Windows x64 ZIP | 171256601 | `c6a13741379b5c44b32ab7cb9b88801506f1b9fd0007f87afa3d0fddc9d97e8b` |
| Linux x64 tar.xz | 103946728 | `de1522759855e849ba09839749e3871aa06820a2ce1418be4099ce388a93ef02` |

The complete versioned archives were downloaded and hashed against their
[official release checksums](https://dl.librewolf.net/librewolf/158.0.1-2/sha256sums.txt).
Old cached inputs and published releases remain unchanged. `engine-lock.json`
pins the exact URLs and hashes; original INIs and native hashes are retained in
[the engine provenance](desktop-engine-158-provenance.json).

Both application and platform INIs identify Mozilla revision
`48a735cc74a7e6d730f9bf59c3de58f750287a23`. The LibreWolf backport is an additional
upstream source modification; the base source stamp alone does not describe it.

| Platform | Application INI | Platform INI | Compiled toolkit | Native API observation |
| --- | --- | --- | --- | --- |
| Windows | `20261022000451` | `20261022011852` | `20261022000451` | Pending |
| Linux | `20261022000330` | `20261022011640` | `20261022000330` | App/Toolkit `20261022000330`, candidate only |

The toolkit IDs were read independently from the Windows PE `mozbldid` section
and Linux ELF `mzbldid` note. At the exact base source revision,
`Services.appinfo.appBuildID` returns application metadata;
`platformBuildID` returns compiled `gToolkitBuildID`, rather than `platform.ini`.
The final Windows and Linux packages must satisfy these separate identities.

The matching [LibreWolf source archive](https://librewolf.dev/api/packages/librewolf/generic/librewolf-source/158.0.1-2/librewolf-158.0.1-2.source.tar.gz)
returned HTTP 200 to HEAD, with 1182292355 bytes. Its official checksum sidecar
reports `dd1e782faf8e8da53267997c79f6b5c330ca0ca1cf1818c6d6faaeb08642f7db`.
The source archive body was not downloaded or hashed; availability does not
establish complete corresponding-source or license verification. The exact
source link and Cyphra's integration source must accompany releases.

## Authenticated certificate data

The desktop snapshot fetched 26 October contains 1,907 published revocation
records, signed 21 October at 22:34:01.776 UTC. The signed source metadata has
1,262 records with `enabled: true`; this count does not control enforcement.
Cyphra installs every published identity as revoked, matching Gecko, including
the 645 records with `enabled: false`. Six records with `enabled: true` were added;
none of the earlier records changed or disappeared. The pinned P-384 signature
and signer were verified through the existing strict preparation process.

The exact `-2` Linux engine ran as an ordinary user in a new network namespace
without external routes. Its native Mozilla production-root verifier accepted
the snapshot and rejected timestamp/record tampering. Native revocation storage
already had the bundled startup data; installation of the newly fetched snapshot
returned `NS_OK`. This is candidate-only engine/security evidence, without a
final Cyphra package, UI or Windows pass. [The dated observation](security-data-2026-10-26.json)
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

Android separately pins GeckoView 159.0 and retains that AAR's official packaged
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
