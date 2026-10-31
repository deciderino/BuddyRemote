# Changelog

All notable changes to BuddyRemote are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions are plain numbers (`1.0`, `1.2`, `1.3`, `1.3.1`); there was no 1.1 release.

## [Unreleased] - 1.3.1 (draft)

A maintenance release with two small additions; no changes to pairing, wake or shut down.

### Added

- **Use a custom MoonDeck CLI (Options → Files).** The bundled CLI stays the default. "Choose custom CLI …" checks the file right away (it must start and report a version); a file that does not start is rejected and nothing changes. "Back to the bundled CLI" switches back. If the custom CLI later fails to start or is gone, BuddyRemote falls back to the bundled one, shows an amber note with a **Settings** button and keeps your choice; the status bar then shows "Custom CLI ⚠". Works in the AppImage and from source.
- **Options → Updates shows BuddyRemote and the MoonDeck CLI side by side** (one below the other in a narrow window), with one "Check now" button, "Last checked" and the states "checking …" and "check failed". The CLI check is part of the existing update check: it compares the MoonDeck nightly with the bundled CLI and only shows a note with a **Release page** button – nothing is downloaded (a newer CLI comes with the next BuddyRemote update). The automatic note appears once per new nightly. If the app and the CLI are both newer, you get one combined note. With a custom CLI active the check still refers to the bundled CLI.
- **Buddy version mismatch warning.** BuddyRemote reads the Buddy API version (`/apiVersion`, expected: 9) and also recognises the CLI's "MoonDeck/Buddy needs update!". On a mismatch the host gets an orange dot, a hint line with "ⓘ Details" that says which side needs updating (Buddy on the host is older → update Buddy; Buddy is newer → update BuddyRemote), and only **Start Steam** is disabled (with a tooltip). Wake, shut down, restart, standby and hibernate keep working. No blinking, no pop-ups.

### Changed

- **AppImage: the MoonDeck CLI runs straight from the AppImage.** It is no longer copied to `~/.config/BuddyRemote/cli/`. Every AppImage therefore uses exactly the CLI it was built and checked with. The CLI starts in `~/.config/BuddyRemote/` and gets your own `LD_LIBRARY_PATH` back (like `ping` already did), not the AppImage's internal libraries. A `cli/` folder left there by 1.3 is no longer used; BuddyRemote leaves it alone and you can delete it.
- **Options → MoonDeck CLI** reads the version info only from the AppImage.
- **Default settings file.** The shipped first-start defaults are now `packaging/default-config.json`. Your own `config.json` (and `cli/`, `.attributed`, `.instance.lock`, the log and `window.ini`) is no longer part of the repository and is ignored by git. Running from source, `config.json` is created from the defaults on first start.
- **"Start minimized" is off by default** everywhere, also for a settings file without this option (it already was for new installs). Turn it on in Options if you want it.
- **Language "automatic"** is decided in one place for the start and the Options dialog (same behaviour as before).

### Removed

- Leftovers from the 1.3 development: the unused compact mode, the old status-update path, unused helpers and translation strings (`status`, `unknown`, `online`, `offline`, `error` in all eight languages), and the layout migration steps for draft-only layouts that were never released. Hosts from 1.2 still get a template; 1.3 layouts are kept as they are.
- Running from source: the old `cli/cli.py` fallback. The CLI binary from the first-start download is used, as before.

### Upgrading from source

- `config.json` is no longer tracked. If you changed it in your checkout, back it up before `git pull` (git refuses to overwrite it otherwise), then put it back.

## [1.3] - 2026-10-31

### Highlights

- **A whole new look.** Every PC is a clean card with big tiles. One status dot tells you at a glance: green = ready, orange = on but MoonDeck Buddy isn't answering, grey = off.
- **Make it yours.** Press ✎ and drag tiles where you want them. The other tiles make room. Resize, duplicate or hide tiles, reorder your PCs, and undo any step. Or just pick a template: Standard, Minimal, Server or Gaming.
- **As slim as you like.** Collapse the toolbar and the log, hide IP addresses and the Steam status, and BuddyRemote fits in a tiny window.
- **You see what happens.** A tile says "Waking …" until the PC is up, then a short toast confirms it.
- **Works on more Linux systems.** The update check in the AppImage now works on Fedora, Bazzite, openSUSE and others.
- **Eight languages.** Spanish, French, Italian, Czech, Japanese and Korean join German and English.
- **Your setup is kept.** Hosts and pairings from 1.2 are migrated automatically.


### Added

- **Tiles per host.** Each host card is a 4-column grid of tiles: online status, Wake, Shut down, Restart, Standby, Hibernate and Steam start/close. Tiles come in four fixed sizes: small 1×1, medium 2×1, wide 4×1 and large 2×2. New positions are checked for collisions.
- **Edit mode in the main window.** "Edit" in the toolbar (Ctrl+E) or a touch long press (~350 ms) on a tile switches all cards into edit mode. The ✎ button in the toolbar turns into a coloured "✓ Done" (the only Done button; Esc also leaves), a hint bar with undo/redo appears, and the status bar says "Edit mode active". Tiles are dragged directly on the cards. A click selects a tile, the arrow keys move it, and a blocked move is reported. A slim edit toolbar (size, duplicate, hide, show hidden, template, layout ▾ incl. auto-arrange) is only visible in edit mode. Every change is saved at once.
- **Templates:** Standard, Minimal, Server (without Steam) and Gaming. You can pick one when adding a host or apply it later. Templates hide tiles; they never delete them.
- **Undo** after deleting a host, via a button in the toast (8 s).
- **Drag and drop** in edit mode: tiles snap to the grid cells, other tiles make room with a short animation (160 ms, OutBack) and a placeholder shows the target. A ghost follows the pointer and the target cells light up in the accent colour, or red if the drop is not possible; an invalid drop springs back. Touch: press and hold (~350 ms), drag, release. Esc cancels a running drag. The arrow keys are the alternative to dragging.
- **Right-click menu** on a tile in edit mode: size, duplicate, hide. Everything in it is also reachable without right click, through the edit toolbar.
- **Duplicates:** an action can be on a card up to 3 extra times. "Remove" deletes a duplicate and hides an original tile.
- **Undo/redo for the layout** (Ctrl+Z, Ctrl+Y / Ctrl+Shift+Z and 48 × 48 px buttons in the hint bar): move, resize, show/hide, template, layout, auto-arrange, duplicate, remove. The history covers one edit session; "Done" ends it.
- **Layouts "Compact" and "Spacious"** (sizes and arrangement; which tiles are visible stays up to the template) and **auto-arrange by usage** per host (falls back to the default order without usage data).
- **Calm status in the card header.** One dot next to the name: green = ready, orange (#fb8c00, light theme #f57c00) = PC on but MoonDeck Buddy not answering, grey = off. The tooltip on the dot and the name shows ping, Buddy port and the time of the last check. Only in the problem state a line "Buddy not answering · ⓘ Details" appears; "▶ Steam running" is only shown while Steam runs. Automatic status checks (`auto_status`) work as before.
- **Reorder cards by drag and drop** in edit mode: grab a card by its header or an empty area (touch: hold ~350 ms), a ghost follows, an insertion line shows the target, the card slides into place and the order is saved. Ctrl+↑/↓ moves the focused card. Undo/redo covers it.
- **Resizable log.** The log is separated by a splitter with a 14 px touch-friendly handle instead of a fixed 150 px height. The height is saved in `window.ini` (`log_height`); double-click on the handle resets it. Works at every window size.
- **Collapsible main toolbar.** The toolbar shows icon-only 48 px buttons ＋ ⟳ ✎ ☰; the tooltips give label and shortcut. ⌃ at the right collapses it with a short slide animation into a slim full-width grip ⌄ that expands it again. The state is saved (`toolbar_collapsed`). Shortcuts (Ctrl+N, F5, Ctrl+E, …) work while collapsed, and edit mode expands the bar automatically (and collapses it again afterwards).
- **"App controls" group in edit mode:** the toolbar buttons can be resized (small = icon, medium = icon + label), reordered by drag or Ctrl+←/→ and undone/redone. They cannot be hidden or removed (the app would become unusable): this is shown disabled in the right-click menu and the edit bar, and Delete shows a toast.
- **Third-party licenses viewer** in Settings (Qt, PyQt6, ICU, SDL2, MoonDeck CLI …); About shows the version and the MoonDeck thanks with a link.
- **Languages:** Spanish, French, Italian, Czech, Japanese and Korean in addition to German and English (machine translations, review by native speakers pending). The language list in Settings shows each language by its own name.

- **Edit mode, concept 2.** Everything that can be moved (tiles, cards, the app-control icons including "✓ Done") has the same ⠿ grip and a calm lifted look (shadow, no animation). What cannot be edited in edit mode (IP, log, status bar, the collapse arrow) is dimmed to 40 %. Section labels "App controls · drag to arrange" and "Tiles · drag to arrange". While dragging, only valid drop areas light up: a tile shows its slots ("drop here" / "original place"), a toolbar icon opens a gap with a marker, a card opens a gap with an insertion line. The hint text follows the state (idle, tile selected, dragging a tile / icon / card). The card grip has a tooltip.
- **"Show IP address"** switch in Settings (global). When off, the IP is only in the tooltip of the status dot.
- **"Show 'Steam running'"** switch in Settings (global) for "▶ Steam running" in the card header.
- **"📂 Open data folder"** in Settings opens the folder with config.json, the log, window.ini and cli/ in the system file manager (QDesktopServices, platform neutral). The path is shown next to it and can be selected; if opening fails, the dialog itself says so below the button ("⚠ Could not open the data folder" with the hint to copy the path) and the path turns red, so nothing is hidden behind the dialog.
- **Empty start:** without hosts, a large "＋ Add first host" tile in the middle of the window.
- **Action feedback in the tile:** after a click the tile says e.g. "Waking …" until the status changes (at most 90 s; without automatic status checks until the action returns), then a toast "{Host}: {Action} sent". Failures end the feedback at once and show an error toast.

### Changed

- **Card buttons:** ✎ became ⚙ and opens the connection settings only (name, IP, MAC, Buddy port, delete). The tile preview and arrow buttons are gone from the dialog. The ↑ ↓ buttons for the host order are gone (cards are reordered by drag and drop, see Added), so ⚙ is the only button on the card; its glyph is larger, the button stays 48 × 48 px. The settings button in the toolbar is now ☰. Adding a host still lets you choose a template.
- **Status tiles hidden by migration.** Existing layouts are migrated once (`layout_rev` 2): the online and Steam status tiles are hidden, the remaining tiles keep their positions, and a status row that becomes empty is removed. The online status tile stays available as an optional tile ("Show hidden"); the Steam status tile was removed later (see below). Templates no longer contain them visibly.
- **Deleting a host** moved from the ✕ on the card into the ⚙ dialog ("Delete host…"). It asks for confirmation with a red button, and Cancel is the default.
- The config gets an `aktionen` list per host. 1.2 configs are migrated automatically to the Standard template. No automatic backup copy is written any more. Tile types BuddyRemote doesn't know are kept unchanged; tile entries that are no object at all (hand-edited config) are dropped on load.
- **Edit hint wraps** instead of being cut off at narrow widths.
- **Wake is no longer highlighted when the PC answers.** It is greyed out with the reason "PC is already on" as tooltip; highlighted only when the PC is off.
- **Fewer tooltips.** Kept: toolbar, ⚙, status dot/name, undo/redo, Done, log, licenses and the reasons on disabled buttons. Removed: action tiles, ⓘ Details, check time, edit-bar tool buttons, drag hints and the edit hint. The "duplicate limit reached" note is now a toast.
- **Removed the automatic config backup** (`config.1.2-backup.json`); the 1.2 migration itself is unchanged.
- The two-line compact mode of the card was removed; the grid replaces it.
- The status bar shows only the state: Ready, Action running …, Editing.
- Info messages appear as toasts; dialogs are only used for confirmations.
- All remaining hard-coded UI texts (CLI checksum rows, pairing wait dialog, theme names) are translated.
- The config gets `nutzung` (usage counts) per host, and tiles can carry a `dup` index. The host entry also gets `layout_rev`. 1.2 ignores all three, so going back to 1.2 drops duplicates and usage counts.

- **Steam status tile removed** (not optional any more). Existing layouts lose it on load (`REMOVED_TYPES`); rows that become empty only because of that are removed. "▶ Steam running" in the card header replaces it.
- **Log grip** sits directly on the top edge of the log and is only there while the log is open; "▸ Log (Ctrl+L)" is on the left of the same 48 px row.
- **Settings in sections:** Display / Behaviour / Updates / Files.
- **Consistent wording** in all 8 languages: "Edit" throughout (status bar "Editing"), "Delete" only for permanent things, "Hide" for tiles, "Wake" everywhere, short "Buddy", one success pattern "{Host}: {Action} sent", template "Custom", typographic quotes, unified state texts ("Checking …", "Action running …"). Unused language keys were removed (each checked by grep).

### Fixed

- **Layouts with gaps are saved exactly.** Before, completely empty rows (between tiles or above them) were packed away when saving, so tiles moved up after OK or a restart. Positions are now saved as arranged. On the card, empty rows keep the height of one tile, and the template name only matches when the positions match exactly.
- **Light theme: dropdowns, context menus and tooltips are readable.** With a dark Plasma colour scheme, combo box entries were dark on dark, because popups used the desktop palette. The app now sets a full palette (all roles, including disabled) and explicit popup, menu and tooltip styles for both themes. Hover and selection in combo popups are highlighted, and disabled entries are greyed out.
- **Update check in the AppImage on Fedora, Bazzite, openSUSE and others:** fixes the certificate error "unable to get local issuer certificate". The bundled OpenSSL only searched Debian paths. The system CA store is now found explicitly:
  - `SSL_CERT_FILE` / `SSL_CERT_DIR` first.
  - Then `/etc/pki/tls/certs/ca-bundle.crt`, `/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem`, `/etc/ssl/certs/ca-certificates.crt`, `/etc/ssl/cert.pem`, `/etc/ssl/ca-bundle.pem`, `/var/lib/ca-certificates/ca-bundle.pem`.
  - Then hashed certificate directories.

  Verification always stays on and no CA list is bundled. The same applies to the CLI checksum check. MoonDeck Buddy's self-signed connection is unchanged.
- The update check failure toast is shorter and clearer ("No connection or certificate problem"), or says that no system certificate store was found. The cause and the CA store in use are written to the log.
- **"✓ Done" keeps its accent colour** after it is moved in the app controls (the "selected" style no longer overrides it).
- Entering edit mode no longer briefly creates a stray top-level window (IP pill), which took the focus away from the main window and its shortcuts.
- Esc now cancels a toolbar-icon or card drag even while the dragged button holds the mouse grab.
- The edit-mode hint ("… · Esc cancels") stays readable while dragging; the drop-focus dimming no longer covers it.
- When the cards are rebuilt (for example on leaving edit mode), the old cards disappear at once instead of staying painted until the next event-loop turn. The dragged card's ghost is also less transparent, so its labels no longer mix with the card below.
- **Hand-edited or damaged config.json no longer crashes the app:** tile entries that are no object are dropped, hosts that are no object are dropped, hosts without a usable `id` get a new one (saved, so it stays stable), and `status_interval` is read as a whole number of seconds within 10–300 (otherwise 30). Connection data (IP, MAC, Buddy port, pairing) is not touched.
- **"Start minimized" no longer hides the window** when there is no host yet (the empty start with "＋ Add first host" is always shown) or when the desktop has no system tray (the window could not be brought back).
- **Changing "Show IP address" or "Show 'Steam running'" while an action runs** keeps the tile feedback ("Waking …", busy state, error line) instead of resetting it when the cards are rebuilt.
- **Settings: the "Open data folder" error is shown in the dialog** instead of a toast that was hidden behind the modal dialog.
- **Settings: the checkboxes have a 48 px touch target** (were 42 px).
- **The card grip in edit mode is painted** like the tile and toolbar grips instead of the "⠿" font glyph (looks the same on every platform and font).

## [1.2] - 2026-10-29

### Added

- **Live host status.** Each host is checked in its own thread. BuddyRemote pings the PC (ICMP, system `ping`) and queries the MoonDeck Buddy API at the same time. If Buddy answers, it also asks the MoonDeck CLI for the Steam status (`steam status`).
  - Every host card shows three chips: **PC** (online / online (Ping) / offline), **Buddy** (reachable / not reachable) and **Steam** (Big Picture / running / off), plus the time of the last check.
  - "(Ping)" plus a red hint appears when the PC answers ping but MoonDeck Buddy doesn't.
  - The check interval can be set from 10 to 300 s (default 30 s).
  - Hosts are checked again 3 s and 15 s after an action, and after adding or editing a host.
- **Hibernate** action (`host hibernate`), in the host card and the tray menu. It asks for confirmation first, if confirmations are on.
- **Steam start / close** on the host (`steam launch` / `steam close client`). It is one toggle button whose label follows the Steam status. Closing asks for confirmation, because running games are closed too.
- **Update check.** On startup, BuddyRemote asks the GitHub releases API (`releases/latest`, 5 s timeout) whether a newer version exists. If so, a blue notice with **Download** (opens the release page in the browser) and ✕ appears in the bottom right for about 30 s. Nothing is downloaded or installed automatically.
  - Options adds "Check for updates at startup" (on by default), "Check for updates now" and "Last checked: … – up to date / X available / failed".
  - The automatic check fails silently. A manual check reports its result.
- **Language setting.** German and English, or "auto" (follows the system locale), selectable in Options. A complete German translation is included (`lang/de.json`). Qt's own dialog buttons (Yes/No, Cancel) are translated as well.
- **Version display.** The app version is shown in About and Options.
- **Gamepad support** through SDL2, so Steam doesn't need to be running. The D-pad / left stick moves, A selects, B goes back. It only works while a BuddyRemote window is active. Requires the optional `PySDL2` and `pysdl2-dll` packages when running from source.
- **Keyboard navigation.** Arrow keys, Tab, Enter and Escape work throughout the main window and dialogs. There is a visible focus ring that hides while the mouse is used, and shortcuts F5 (refresh), Ctrl+N (add host), Ctrl+, (options) and Ctrl+L (log).
- **Dialog fields with navigation vs. edit mode.** A/Enter starts editing, Enter accepts, Escape reverts. Clicking or typing edits directly.
- **Toast notifications** (green = success, red = error) with a tray balloon when the window is hidden. Every message is also written to the log and the status bar.
- **Toolbar and status bar.** The status bar shows the last message, the host count / online count, the auto-refresh interval and the CLI state. The log is collapsible.
- The window's size (and its position on X11) is remembered in `window.ini`. A restored window is kept on screen.

### Changed

- **Host cards redesigned for touch screens.** Each card has three lines:
  - status dot, name, IP, then ↑ ↓ ✎ and a separate ✕ (remove) button;
  - the status chips;
  - a **Power** group (wake, shut down, restart, standby, hibernate) and a **Steam** group.
- All touch targets are at least 48 × 48 px, with more spacing between them.
- All buttons stay visible. Buttons that can't be used right now are greyed out, skipped by keyboard/gamepad navigation, and their tooltip says why:
  - **Wake** only works while the PC is offline;
  - **power and Steam actions** only work while MoonDeck Buddy is reachable;
  - before the first check, or with automatic status checks off, every button stays enabled.
- In narrow windows, the group labels move above their buttons. The minimum window size is computed from the real layout.
- The tray icon is "online" when MoonDeck Buddy is reachable on at least one host.
- Confirmations for destructive actions (shut down, restart, standby, hibernate, close Steam, remove host) default to **No**, which is safer with a gamepad or the Enter key.
- Success and error messages name the action (e.g. "hibernate sent", or "hibernate failed" with a hint to enable hibernation on the PC) instead of a generic "Done".
- A second start of BuddyRemote brings the running window to the front (QLockFile + local socket) instead of only refusing to start.
- `config.json` defaults to `"language": "auto"`. An old `"en"` that was never chosen in Options also counts as "auto".
- README updated:
  - new features;
  - how to allow ping on Windows hosts (firewall rule "File and Printer Sharing (Echo Request - ICMPv4-In)");
  - enabling hibernation on the host;
  - window position on Wayland.

### Fixed

- Wake reported its success message based on the host name rather than the action. Action results are now matched by host id and action.
- An invalid Buddy port in the host dialog crashed the app. It is now validated (1–65535) with an inline error.
- The single-instance check could delete another running instance's lock file or check a reused PID (`os.kill`). It now uses an atomic QLockFile.
- The language setting in `config.json` had no effect, and the UI was always English.
- A status line could push the status bar labels out of the window.

### Removed

- The status check no longer treats "TCP connection to the Buddy port succeeded" as online. It now checks ICMP ping plus the Buddy API (see Added).
- Purely informational pop-ups ("Done", "Wake signal sent", "Checksum verified", …) were replaced by non-blocking toasts. Confirmations, the pairing PIN dialog, About and the attribution notice are still dialogs.
- In the AppImage only: the "CLI checksum" display, the "Verify checksum" button and the automatic MoonDeck CLI download, because the AppImage ships a pinned CLI. Running from source still downloads and verifies the CLI as before.

### Packaging

- **New Linux AppImage** (`BuddyRemote-x86_64.AppImage`), built with `packaging/linux/build-appimage.sh` (PyInstaller onedir + appimagetool):
  - **Contents.** Bundles Python, PyQt6/Qt 6 (xcb and wayland platform plugins), libSDL2 for gamepads, and the MoonDeck CLI (nightly, commit 00f8c31). The CLI's SHA-256 is checked at build time.
  - **Version file.** The build writes `bundled/moondeck-cli.version` (version, commit, sha256). Options shows "MoonDeck CLI: bundled (nightly, commit 00f8c31)". When a newer AppImage brings a different CLI, the user copy is replaced.
  - **Requirements.** Needs glibc 2.34 or newer (e.g. Ubuntu 22.04, Debian 12, Fedora 35, Bazzite / SteamOS).
  - **Settings location.** Settings, CLI copy and logs live in `~/.config/BuddyRemote/` (or `$XDG_CONFIG_HOME/BuddyRemote/`).
  - **Licences.** Licence texts for MoonDeck CLI (GPL-3.0), PyQt6, Qt, SDL2, PySDL2, Python and the bundled xcb-util libraries are included under `usr/share/licenses/BuddyRemote/`.
  - **Ping.** The system `ping` is started with the original `LD_LIBRARY_PATH`, so it doesn't load the bundled libraries.
- `requirements.txt`: optional `PySDL2` and `pysdl2-dll` for gamepad support.
- `.gitignore`: build output (`build/`, `dist/`, `AppDir/`) and `window.ini`.

## [1.0]

- First release: a Linux GUI for MoonDeck Buddy with wake, shut down, restart and suspend, pairing with automatic MAC detection, multiple hosts, a tray icon, an automatic MoonDeck CLI download with checksum verification, and optional logging.

[Unreleased]: https://github.com/deciderino/BuddyRemote/compare/1.3...HEAD
[1.3]: https://github.com/deciderino/BuddyRemote/compare/1.2...1.3
[1.2]: https://github.com/deciderino/BuddyRemote/compare/1.0...1.2
[1.0]: https://github.com/deciderino/BuddyRemote/releases/tag/1.0
