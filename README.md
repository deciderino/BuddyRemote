# BuddyRemote

Download. Extract. Run. Pair. Done.
Simple remote PC control. No complicated setup.
BuddyRemote is a lightweight, free and open-source Linux application for remotely controlling Windows and Linux PCs through a simple graphical interface using MoonDeck Buddy.
Wake up, shut down, restart, or suspend your PCs without configuring SSH, manually looking up MAC addresses, or dealing with complicated command-line tools.
Designed with simplicity in mind, BuddyRemote is especially useful for Linux HTPCs, Steam Deck Desktop Mode, and home game streaming setups.
No active Steam, Sunshine, Apollo, or Moonlight session required.
Why I created BuddyRemote
I use a small Linux mini-PC as an HTPC in my living room, mainly for streaming games from my more powerful gaming PCs.
My setup works great with Moonlight and Sunshine/Apollo, but I was missing one simple thing: an easy way to turn my gaming PCs on and off directly from my Linux desktop.
Sure, there are other ways to do this. Wake-on-LAN utilities, SSH, scripts, mobile apps… But I didn't want another complicated solution. I wanted a small graphical application that I could just open, click a button, and be done.
I was already familiar with MoonDeck Buddy and its ability to manage remote PCs. So I thought: why not make those features accessible through a simple, standalone Linux GUI? That's how BuddyRemote started.
Built with AI, driven by an idea
I'm not a software developer. I created BuddyRemote with the help of AI by describing what I wanted, testing the results, reporting problems, and gradually adding new features.
There were quite a few iterations before everything worked the way I imagined.
Originally, BuddyRemote was intended purely for my personal setup. But after using it successfully, I figured other Linux users might find it useful too, especially those who just want a straightforward way to manage their gaming PCs without diving into networking tools or command-line configuration.
So I decided to share it as an open-source project.
Features
    • • Wake-on-LAN — Wake up your Windows or Linux PC remotely.
    • • Remote power control — Shut down, restart, or suspend your PC.
    • • Multiple hosts — Manage several computers from one interface.
    • • Automatic MAC detection — No need to manually find or enter MAC addresses.
    • • Easy pairing — Enter your host's IP address and complete the MoonDeck Buddy pairing process.
    • • Portable application — No traditional system-wide installation required.
    • • Automatic setup — Creates its own Python virtual environment and installs the required dependencies.
    • • Automatic MoonDeck CLI download — Retrieves the required CLI, with checksum verification when available.
    • • System tray support — Keep BuddyRemote accessible without leaving the main window open.
    • • Optional logging — Enable logs when troubleshooting.
Getting started
Download. Extract. Run. Pair. Done.
1. Install MoonDeck Buddy on your host PC
MoonDeck Buddy is available for Windows and Linux.
2. Download BuddyRemote
Download the latest release and extract the archive on your Linux device.
3. Run BuddyRemote
./BuddyRemote
On its first launch, BuddyRemote automatically creates a Python virtual environment, installs its dependencies, and downloads the MoonDeck CLI.
4. Pair your PC
Enter your host's IP address and complete the pairing process. BuddyRemote automatically retrieves the host's MAC address through the CLI.
5. Done!
Your PC is ready to be controlled directly from the graphical interface.
Requirements
    • • Linux with Python 3.10+ and working venv support
    • • MoonDeck Buddy installed on the Windows or Linux host
    • • Both devices connected to a trusted local network
    • • Wake-on-LAN enabled on the host if you want to wake it remotely
Note: An internet connection is required for the initial setup to download dependencies and the MoonDeck CLI. After setup, BuddyRemote works entirely on your local network.
Compatibility
BuddyRemote has been tested on Bazzite Linux.
It is designed to be portable across Linux distributions, but compatibility with other distributions has not yet been extensively tested.
Reports from Ubuntu, Fedora, Arch, Linux Mint, Pop!_OS, SteamOS, and other distributions are very welcome.
Who is BuddyRemote for?
    • • Linux HTPC and living-room PC users
    • • Steam Deck users in Desktop Mode
    • • Moonlight / Sunshine / Apollo setups
    • • Steam Remote Play users
    • • Multi-PC gaming environments
    • • Anyone looking for simple remote PC power control
You don't actually need a game streaming setup to use BuddyRemote. As long as MoonDeck Buddy is running on the host, BuddyRemote can control its power functions independently of streaming software.
Security and intended use
BuddyRemote is intended for trusted local home networks only.
BuddyRemote uses MoonDeck Buddy's existing authentication and communication mechanisms. It does not implement its own hardened remote access protocol.
MoonDeck Buddy prioritizes convenient use in home networks and should not be considered a replacement for SSH or security-focused remote administration tools.
For safe operation:
    • • Use BuddyRemote only on networks you trust.
    • • Do not expose MoonDeck Buddy's service port directly to the public internet.
    • • Avoid using it on untrusted or public networks.
    • • Keep your host systems and MoonDeck Buddy up to date.
BuddyRemote is designed for convenience and simplicity, not internet-facing remote administration.
Free & Open Source
BuddyRemote is a personal, community-oriented project.
It is free to use, modify, and share under the GNU General Public License v3.0, once the license is included in the published repository.
Bug reports, feature suggestions, contributions, and compatibility feedback are welcome.
My goal is simple: Keep BuddyRemote lightweight, easy to install, and easy to use.
No unnecessary complexity. Just a convenient remote for your PCs.
BuddyRemote is an independent project using MoonDeck Buddy. It is not an official MoonDeck application and is not affiliated with the MoonDeck developers.
