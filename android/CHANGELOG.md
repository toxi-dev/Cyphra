# Android releases

## 0.1.2 — 18 October 2026

- Update the pinned native engine to GeckoView 158 / Gecko 158.0, including Mozilla's 13 October security fixes.
- Add the separate Cyphra Home APK with one Personal profile, system DNS by default, optional manual sync and its own installation, signing and update identities. Public and Byte Team keep both modes and their security tools.
- Refine the native new tab, toolbar, bookmark shortcuts, customization preview and Shields across all three editions, retaining the original logo and measured filtering counters.
- Explain the actual Gecko connection failure: unresolved hosts, offline connections, timeouts, TLS and proxy failures receive distinct messages. Other failures no longer get labeled as encrypted-DNS failures, and DNS settings remain unchanged.
- Profile-local Graphite, Black, Light and System themes with restrained accent choices.
- Live native appearance preview, compact/comfortable density, text scale and toolbar controls.
- Home bookmark grid/list, limits and security-reading visibility.
- Consistent palettes across native chrome, Shields, website prompts and dialogs.
- Scoped visual reset preserves browsing data, DNS, privacy, sync and update credentials.
- Attachment downloads retain the existing document and avoid requesting the download again after restart.
- Keep the active GeckoView attached during ordinary navigation, avoiding unnecessary display-surface teardown.
- Cross-host attachments preserve the live document's site exceptions and measured Shields counts; late responses cannot replace a newer page's protection context.
- A pinned, reproducible Gecko source-module overlay preserves running page timers when an app-initiated navigation becomes an attachment. General script hang protection remains enabled and verified.
- Keep live ordinary and private sessions through Android Activity recreation; wait for native initialization before requesting runtime shutdown.
- Add strict bounded-clock navigation evidence and Home's three Personal lifecycle cases; Public and Byte Team retain all six lifecycle cases. Source tests do not establish native behavior.

These notes describe the prepared source. Final APK qualification and publication are tracked separately in the release evidence. The desktop OneCRL snapshot refresh is not an Android feature.

## 0.1.1 — 11 October 2026

- Dark native Shields sheet with live counters, a readable cancellation breakdown, separate Gecko events and visible DNS settings.
- Restore the last selected ordinary tab and native Home tabs; private tabs remain excluded.
- Keep saved tabs intact when Android backgrounds Cyphra during protection startup.
- Honor safe download filenames and MIME metadata; report success only after Android publishes the file.
- Android 12 splash resources use versioned themes for Android 10/11 compatibility.
- Bind Android permission responses to the original request; reject overlaps and verify actual OS grants.
- Signed same-key APK upgrades retain existing profiles and settings.

## 0.1.0 — 11 October 2026

- Initial native Android/GeckoView Team and Public APKs, independent of desktop versions.
- Isolated Work and Personal profiles with guarded shutdown/switching, private tabs and saved ordinary tabs/bookmarks.
- Brave-only search, local security-reading links, native toolbar, downloads, permissions and local tools.
- Authenticated local filtering with actual Shields counters and persistent per-site exceptions; telemetry denial remains active.
- Browser DNS choices, strict encrypted DNS without silent fallback, verified startup privacy policy.
- Keystore-protected manual v2 bookmark sync and pinned-signature GitHub APK checks, package and certificate verification.
- GMS runtime excluded and passkeys disabled; no DRM or desktop inspector in this release.
