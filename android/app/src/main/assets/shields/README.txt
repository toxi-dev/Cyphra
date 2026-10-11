Cyphra Shields for Android

The bundled Ghostery adblocker engine is MPL-2.0. Its notices and dependency
licenses are in vendor/LICENSES.txt and vendor/adblock.js.LEGAL.txt.
EasyList and EasyPrivacy are by the EasyList authors (https://easylist.to/),
licensed CC-BY-SA-3.0. The pinned original lists, sizes, hashes, update date,
and source URLs are in filters/. No lists or configuration are fetched from
the network. The engine and snapshot must pass SHA-256 verification before
Cyphra permits normal browsing.

The JavaScript bridge runs in an isolated extension world. Web pages cannot
change protection, execute native commands, or send arbitrary Android intents.
Statistics count requests actually cancelled by this extension. Native Gecko
blocking events are exposed separately to avoid counting the same request twice.
Counts and bounded blocked hostnames live in memory for the current navigation;
there is no remote reporting, inferred time saved, or bandwidth estimate.

Work mode additionally blocks third-party active resources. Personal mode uses
the filter lists without that extra restriction. A user-selected site exception
disables these optional protections for that exact hostname. Telemetry endpoint
denials remain active even when a site exception is enabled.
