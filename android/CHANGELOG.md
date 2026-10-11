# Android releases

## 0.1.1 — 11 October 2026

- Dark native Shields sheet with live counters, a readable cancellation breakdown, separate Gecko events and visible DNS settings.
- Restore the last selected ordinary tab and native Home tabs; private tabs remain excluded.
- Keep saved tabs intact when Android backgrounds Cyphra during protection startup.
- Skip redundant private-addon reloads when its permission is already verified.
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
