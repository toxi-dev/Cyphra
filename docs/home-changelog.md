# Cyphra Home changes

## Desktop 0.7.3 / Android 0.1.2 — 11 November 2026 (source preparation)

- Adds a separate everyday edition for Windows, Linux and Android, with its own profiles, application IDs, releases and signing identity.
- Keeps Brave Search, real ad and tracker blocking, bookmarks, private browsing, downloads, customization, manual encrypted sync and signed updates.
- Uses one Personal profile and system DNS by default, with explicit resolver choices. Cybersecurity tools, Work mode and the security briefing are absent.
- Refines browser spacing, local bookmark shortcuts, settings and the Shields panel while preserving the original Cyphra logo.
- Adds live native Android appearance controls and an offline new tab with a clearer Home identity; connection errors explain the observed Gecko failure without treating every failure as a DNS problem.
- Uses LibreWolf 160.0-1 / Gecko 160.0 on desktop and pinned GeckoView 160.0 on Android. Desktop bundles the authenticated OneCRL snapshot fetched 11 November and enforces all 1,959 published revocation records, including 697 with `enabled: false` metadata. Android retains its official packaged startup data and does not port the desktop maintenance system.
- Adds first-release Windows install/reinstall checks and Android's actual Home menu, filtering, customization, durable data and same-version reinstall checks. Home has no historical upgrade claim. Three Personal navigation trials and all three Personal lifecycle cases are required separately for its APK.

These notes describe the prepared source. Dated 158.0.1-2 certificate checks remain historical candidate observations. Final Gecko 160 desktop package/runtime qualification and platform publication remain separate work; see the exact release evidence for completed checks and limitations.
