<div align="center">

# BuddyRemote

### Download. Extract. Run. Pair. Done.

**Simple remote PC control. No complicated setup.**

A lightweight, free and open-source **Linux GUI** for controlling **Windows and Linux PCs** on your home network via [MoonDeck Buddy](https://github.com/FrogTheFrog/moondeck-buddy).

[**Download the latest release**](https://github.com/deciderino/BuddyRemote/releases) · [Report an issue](https://github.com/deciderino/BuddyRemote/issues)

</div>

---

## What is BuddyRemote?

BuddyRemote lets you **wake, shut down, restart, or suspend** your PCs from a simple graphical interface on Linux.

It was made for **Linux HTPCs, Steam Deck Desktop Mode, and home game streaming setups**—but you don't need a game streaming session to use it. Power controls work independently of Steam, Sunshine, Apollo, and Moonlight, as long as MoonDeck Buddy is available on the host.

**No SSH configuration. No manual MAC address lookup. No complicated command-line setup.**

> [!IMPORTANT]
> **For trusted local home networks only.** BuddyRemote uses MoonDeck Buddy's existing security model. Do not expose MoonDeck Buddy's service port directly to the internet.

<!-- Add a real screenshot from the app here, for example:
![BuddyRemote main window](docs/screenshots/main-window.png)
-->

## Features

| Feature | What it does |
| --- | --- |
| **Wake-on-LAN** | Wake your Windows or Linux host remotely. |
| **Power controls** | Shut down, restart, or suspend a host. |
| **Multiple hosts** | Manage several PCs from one window. |
| **Easy pairing** | Enter the host IP address and complete MoonDeck Buddy pairing. |
| **Automatic MAC detection** | Retrieve the host's MAC address through the MoonDeck CLI. |
| **Portable launch** | Run from an extracted folder without a traditional system-wide app installation. |
| **Automatic setup** | Create a Python virtual environment and install required dependencies on first launch. |
| **MoonDeck CLI setup** | Download the required CLI automatically, with checksum verification when available. |
| **System tray** | Keep BuddyRemote conveniently accessible. |
| **Optional logs** | Enable application logging for troubleshooting. |

## Getting started

**Download. Extract. Run. Pair. Done.**

**1. Set up MoonDeck Buddy on the host**

Install [MoonDeck Buddy](https://github.com/FrogTheFrog/moondeck-buddy) on the **Windows or Linux PC you want to control**.

**2. Download BuddyRemote**

Get the archive from [GitHub Releases](https://github.com/deciderino/BuddyRemote/releases) and extract it on your **Linux client**.

**3. Run it**

Open a terminal in the extracted folder and start:

```bash
./BuddyRemote
```

The launcher sets up its own Python virtual environment, installs the required Python dependencies, and downloads the MoonDeck CLI when needed.

**4. Pair your host**

Enter the host's **IP address** and follow the pairing instructions. BuddyRemote retrieves the MAC address automatically through the CLI.

**5. Done!**

Control your host from the BuddyRemote GUI.

### Requirements

- **Client:** Linux with Python **3.10+** and working `venv` support.
- **Host:** Windows or Linux with **MoonDeck Buddy** installed.
- Both devices connected to a **trusted local network**.
- Wake-on-LAN supported and enabled on the host if you want remote wake-up.

> **First launch:** Internet access is needed to download Python dependencies and the MoonDeck CLI. After setup, BuddyRemote operates over your local network without requiring an ongoing internet connection.
>
> **Debian/Ubuntu-based systems:** If `venv` isn't available, you may need to install `python3-venv` through your package manager.

## Why I created BuddyRemote

I use a small Linux mini-PC as an **HTPC in my living room**, mainly to stream games from my more powerful gaming PCs.

Moonlight with Sunshine/Apollo works great for that. But I was missing something simple: **a convenient way to switch my gaming PCs on and off from the Linux desktop**.

Of course there are other ways—Wake-on-LAN utilities, SSH, scripts, phone apps. But I didn't want another complicated setup. I wanted a small GUI that I could open, click, and be done.

I already knew MoonDeck Buddy could handle remote power controls, so I wondered: **Why not make those features available through a simple standalone Linux interface?**

That's how BuddyRemote started.

### Built with AI, driven by an idea

I'm not a software developer. I built BuddyRemote with the help of AI: describing what I wanted, testing the results, reporting problems, and gradually adding features until the application worked the way I imagined.

At first it was just a tool for my own setup. After using it, I decided to share it in case it could help other Linux users who want straightforward PC control without extra configuration.

## Compatibility and intended audience

BuddyRemote has been **tested on Bazzite Linux**. It is designed to work across Linux distributions, but other distributions haven't been extensively tested yet. Reports from Ubuntu, Fedora, Arch, Linux Mint, Pop!_OS, SteamOS, and others are welcome.

It may be especially useful for:

- Linux HTPC and living-room PC users
- Steam Deck users in **Desktop Mode**
- Moonlight / Sunshine / Apollo setups
- Steam Remote Play users
- Multi-PC gaming setups
- Anyone who wants a simple LAN power-control GUI

**Streaming software is optional.** MoonDeck Buddy is required on each host, but Steam, Moonlight, Sunshine, and Apollo do not need to be running for remote power controls.

### Window position on Wayland

On Wayland, BuddyRemote remembers its window size, but the position is chosen by the compositor, just like other native Wayland apps (Dolphin, Kate, Firefox). On X11 the position is remembered as well.

**KDE tip:** to always open BuddyRemote at a fixed spot, add a KWin window rule: *System Settings → Window Management → Window Rules → Add New*, window class `buddyremote`, then set **Position** and **Size** to **Remember**.

### Keyboard and gamepad

BuddyRemote is a normal desktop app, but it can also be used with the keyboard (arrow keys, Enter, Esc) or a gamepad: D-pad / left stick to move, **A** to select, **B** to go back. Gamepads (Xbox, PlayStation, Switch Pro, 8BitDo, Steam Deck, ...) are read directly through SDL2, so Steam does not need to be running. The input only applies while the BuddyRemote window is active. Moving or clicking the mouse hides the focus highlight; the next key or gamepad press brings it back without triggering anything.

When running from source, gamepad support needs the optional `PySDL2` and `pysdl2-dll` packages from `requirements.txt` (an existing `.venv` can be updated with `.venv/bin/pip install -r requirements.txt`). Without them, the app works as before, just without gamepad input.

## Security and intended use

**BuddyRemote is intended for trusted local home networks only.**

It relies on MoonDeck Buddy and the MoonDeck CLI for communication and authentication. It does not provide its own hardened remote administration protocol and **is not a replacement for SSH** or other security-focused solutions.

- Only use it on networks you trust.
- **Never expose MoonDeck Buddy's service port directly to the public internet.**
- Avoid using it on public or untrusted networks.
- Keep MoonDeck Buddy and your systems updated.

The goal is **convenience in a home setup**, not internet-facing remote administration.

## Free & open source

BuddyRemote is a small personal open-source project. Suggestions, bug reports, contributions, and compatibility feedback are welcome.

**The goal stays the same: keep it lightweight, easy to install, and easy to use.**

See the repository's [`LICENSE`](LICENSE) file for the applicable license terms.

---

<sub>BuddyRemote is an independent project using MoonDeck Buddy. It is not an official MoonDeck application and is not affiliated with the MoonDeck developers.</sub>
