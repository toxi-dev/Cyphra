# Native Windows release qualification

The workflow in `.github/workflows/windows-release-native.yml` runs `tests/windows-release-native.py` on a fresh GitHub-hosted Windows runner. There is no separate PowerShell qualification script. Run the workflow in the repository for the edition being qualified after its matching stable release is published.

Before executing an installer, the harness retrieves that exact version tag and latest-release metadata, verifies the pinned edition-specific update signature, and checks the complete installer size and SHA-256. The update-manifest signature is separate from Windows Authenticode; an installer may remain unsigned in Windows even when its release manifest verifies.

The harness uses the actual per-user Windows known folders. It refuses an existing Cyphra profile rather than pretending that a changed `LOCALAPPDATA` environment variable isolates native browser data. Only fresh disposable runner profiles, a unique temporary application folder and a loopback web fixture are used.

The existing launcher, profile, updater and maintenance checks now include desktop appearance:

- Exercise the installed theme/accent buttons, selectors and checkbox handlers in both Work and Personal processes. The profiles deliberately receive different visual choices.
- Check actual chrome theme/density attributes, rail width, original C logo and navigation height. Settings and Tools must retain layout when the rail is hidden.
- Check the real local new tab’s light/black palette, original logo filter, layout, widget visibility, bookmark limit and protected links. Brave Search and the script-free page remain intact.
- Change layout while the same new tab stays open, requiring the home actor to deliver the update without navigation.
- Reset through the installed reset button, requiring all unmanaged visual overrides to clear while native bookmarks, DNS preferences and lock state, TLS, sandbox, telemetry flags, fingerprinting, WebGL, history, HTTPS upgrades, Global Privacy Control, selected site Shield exceptions and existing sync/update configuration remain unchanged.
- Restore the nondefault appearance choices, verify that reset did not affect the other profile, reinstall the exact released installer and restart both modes. Appearance and new-tab choices must survive together with the original security configuration and bookmarks.
- Uninstall only after comparing the complete external profiles; retained profile files must remain byte-for-byte identical.

Fixture bookmarks are created only in disposable test profiles. Neither installer assets nor release defaults are modified. The appearance checks do not start RSS refreshes, sync operations or update installations. They do not read sync secrets or browser credentials. The separate existing GitHub updater test uses its own ephemeral credential fixture and removes it.

The final JSON proof is printed in the workflow log and written to `RUNNER_TEMP/cyphra-windows-native-proof.json`. Its `appearance.work` and `appearance.personal` records describe requested choices, actual chrome/home observations, reset preservation and reinstall persistence. A `passed` flag is set only after the full installer/runtime/reinstall/uninstall sequence completes.

This runner uses native Windows Gecko in headless mode. Appearance checks qualify installed control wiring, computed style, layout, profile isolation and saved state; they do not establish GUI pixel presentation or physical input behavior. Desktop GUI review remains separate. Local Python/embedded-JavaScript syntax checks do not replace a passing Windows workflow.
