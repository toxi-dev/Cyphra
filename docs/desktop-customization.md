# Desktop appearance and new tabs

Open the Settings gear in the navigation bar. Public and Team also offer **Tools → Appearance**. The Settings gear stays in the navigation bar when the tool rail is hidden or focus view is enabled. On a new tab, **Customize** opens the Home category.

All three editions offer themes, accents, density, rail/sidebar sizes and bookmark controls. Home uses a shortcut rail and one Personal profile; its new tab has search, pinned favorites and native library shortcuts, with no security briefing or publisher controls. It starts with System theme and up to eight pinned sites. Public and Byte Team keep their security workspace and appearance controls. Each existing Work or Personal profile saves its own choices. Appearance changes apply immediately to open browser windows and new tabs in that profile.

| Control | Choices |
| --- | --- |
| Theme | Graphite, Black, Light, or the device’s System theme |
| Accent | Slate, Blue, Teal, Amber, or Rose |
| Toolbar density | Compact, Comfortable, or Touch |
| Tool rail | Visible or hidden; 36, 39, or 46 px wide |
| Bookmarks sidebar | Starting width of 200, 260, 320, or 380 px; the divider remains draggable |
| Bookmarks toolbar | Hidden, shown on new tabs, or always visible |
| Focus view | Hide the rail and bookmarks toolbar while keeping navigation, Settings, Shields and Tools available |
| New-tab layout | Balanced columns, a wider page, or a focused single column |
| New-tab sections | Search, pinned bookmarks, security briefing, and publisher shortcuts |
| Pinned bookmarks | Show up to 4, 8, or 12 direct toolbar bookmarks |
| Headlines | Show up to 4, 6, or 8 cached headlines |
| Bookmark and article links | Open in the current tab or a new tab |

Theme previews show the actual neutral palettes. Light mode keeps the original C shield logo legible. Accent colors are confined to selection and focus indicators. Native toolbar density now changes the actual Cyphra toolbar heights as well as native control spacing.

**Reset appearance and new-tab layout** clears only the listed visual overrides. It keeps bookmarks, browsing data, DNS selection, privacy controls, Shield exceptions, sync configuration and update credentials. Managed appearance preferences remain managed.

The new tab still uses Brave Search. Pins use local toolbar bookmarks without fetching icons. Appearance changes and opening a new tab do not refresh security news. News refresh remains an explicit action and stays disabled in private windows. The installed home actor accepts only its own top-level local page; appearance messages contain allowlisted visual values and no credentials or arbitrary CSS.

## Verification

`node --test tests/appearance.test.mjs` verifies invalid-value refusal, profile separation, reset boundaries, contrast, live window binding and observer cleanup. Palette text has at least 4.5:1 contrast against its ordinary backgrounds; accent focus indicators have at least 3:1 contrast.

`python tests/appearance-native.py` exercises the existing Public and Team workspace using a disposable ordinary-user Gecko profile, checks real chrome and new-tab behavior, restarts to verify saved settings, and confirms that the original edition’s DNS, telemetry, fingerprinting, history, Shields and sandbox settings survive customization and reset. It checks native back/forward navigation, the original logo and actual zero counters on a local new tab. Fixture bookmarks are created only inside the disposable test profile.

For transparent GTK popup screenshots on a private Xvfb desktop, provide a normal desktop window manager and `xcompmgr` via `--compositor` or `CYPHRA_TEST_COMPOSITOR`. This test-only desktop composition does not change shipped graphics preferences. The optional `--overlay-source` copies only changed UI sources into the disposable application copy; shared build stages stay untouched. Native Windows presentation still needs release qualification.
