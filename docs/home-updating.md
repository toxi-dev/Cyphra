# Cyphra Home updates

Home accepts only the `toxi-dev/Cyphra-Home` repository, the Home ECDSA key and `Cyphra-Home` assets. Settings → Updates checks without a GitHub token; automatic checks default off. Downloads and installation require an explicit action. Package names, versions, sizes and hashes are checked against signed metadata before the updater is launched.

On Windows, close Home and run `Cyphra-Home-<version>-win-x64.exe` at the existing `%LOCALAPPDATA%\Programs\CyphraHome` location. Your profile stays at `%LOCALAPPDATA%\CyphraHome\Profile-Personal`.

On Linux, close Home and run `./Cyphra/cyphra-update --archive /path/to/Cyphra-Home-<version>-linux-x64.tar.gz` as the desktop user who owns the installation. Your profile stays at `${XDG_CONFIG_HOME:-~/.config}/cyphra-home/profile-personal`. Python 3.9+ and util-linux `flock` are required.

Both updaters reject cross-edition packages, downgrades, active profile locks, unsafe archives and collisions with unknown saved files. Application replacement is staged on the same filesystem with rollback; profile data lives outside the application folder. Internal manifests detect corruption and do not authenticate a file sent by an unknown person: obtain offline files from a trusted, signed release source. Cyphra release signatures are separate from Windows Authenticode; the Windows installer is not Authenticode-signed.

Android uses the separate `android-v<version>` release series, verifies its APK certificate as well as the signed release metadata, and installs only through Android's package installer. The application ID `org.cyphra.browser.home` keeps its data separate from the other editions.
