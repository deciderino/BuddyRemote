# Changelog

All notable changes to BuddyRemote are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions are plain numbers (`1.0`, `1.2`); there was no 1.1 release.

## [1.2] - Unreleased

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

[1.2]: https://github.com/deciderino/BuddyRemote/compare/1.0...HEAD
[1.0]: https://github.com/deciderino/BuddyRemote/releases/tag/1.0
