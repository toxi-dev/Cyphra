# Cyphra Public updates

Settings → Updates checks the public `toxi-dev/Cyphra` releases without a GitHub token. Automatic checks default off; download and installation require explicit action. The browser verifies its pinned public-edition ECDSA signature, repository, version, package filename, byte size and SHA-256 before launching the installer. Stable releases only; drafts and prereleases are skipped. These signatures are separate from Windows Authenticode, which the current installer does not provide.

Offline Windows updates accept `Cyphra-Public-<version>-win-x64.exe`. Close both modes, then run the installer at the existing `%LOCALAPPDATA%\Programs\CyphraPublic` location. Profiles remain under `%LOCALAPPDATA%\Cyphra\Profile` (Work) and `Profile-Personal`. The uninstaller leaves both profiles intact.

On Linux, close both modes and run `./Cyphra/cyphra-update --archive /path/to/Cyphra-Public-<version>-linux-x64.tar.gz` as the owning desktop account. Python 3.9+ and util-linux flock are required. Profiles remain in `${XDG_CONFIG_HOME:-~/.config}/cyphra-public/profile` and `profile-personal`.

Updates refuse cross-edition packages, downgrades, active browser profiles, corrupt/unsafe packages and collisions with unknown saved files. They stage the application on the same filesystem, preserve unknown installation files, remove obsolete shipped files and attempt rollback on activation failure. A failed rollback reports the preserved backup location. Internal file manifests detect corruption, not an untrusted offline sender; use a trusted signed release source. Native Windows qualification remains necessary; Wine helper tests do not establish physical Windows compatibility.
