# Movinite

**A self-hosted media server for your own movies, TV shows and music.** You run it on an Ubuntu server and watch in
any browser or in the Android app. It's free and open source under the [AGPL-3.0](LICENSE).

Add a folder or a network share (SMB/NFS) as a library. Movinite scans it, fetches posters and descriptions from TMDB
(optional, with a free API key) and plays everything in the browser. It plays a file directly when the browser can,
remuxes it when only the container or audio doesn't fit, and otherwise transcodes it live with ffmpeg (HLS).
On servers with a supported video card, transcoding can run on the GPU.

| Home | Movie details |
|---|---|
| ![Home](docs/screenshots/web-home.png) | ![Details](docs/screenshots/web-details.png) |
| **Player with 2K / 4K quality** | **Add a library from an existing share** |
| ![Player quality menu with 4K options, screen cap turned off](docs/screenshots/web-player-quality-4k.png) | ![Add library](docs/screenshots/web-add-library-existing-connection.png) |
| **Now playing** | **Music equalizer** |
| ![Now playing](docs/screenshots/web-nowplaying.png) | ![Equalizer](docs/screenshots/web-equalizer.png) |
| **Playlists with Play and Shuffle** | **A playlist, ready to play** |
| ![Playlists](docs/screenshots/web-playlists.png) | ![Playlist detail](docs/screenshots/web-playlist-detail.png) |
| **Glass music player and status** | **Phone libraries** |
| ![Glass chrome and music bar](docs/screenshots/web-chrome-glass.png) | ![Phone libraries](docs/screenshots/phone-libraries.png) |
| ![Quality auto-capped to 1080p on a 1920×1200 tablet](docs/screenshots/tablet-player-quality-capped-1080p.png) | ![Settings: cap quality to this screen](docs/screenshots/web-settings-quality-cap.png) |
| ![Settings: transcoding and opening-clip cache](docs/screenshots/web-settings-transcoding.png) | ![Opening-clip cache size](docs/screenshots/web-settings-opening-clip-cache.png) |
| **Server status toolbar** | **Server status panel** |
| ![Header with compact CPU and RAM icons and percentages](docs/screenshots/status-toolbar-desktop.png) | ![Themed server status panel](docs/screenshots/status-panel-desktop.png) |
| **Users and email invites** | **Invite someone** |
| ![Users with roles and Invite by email](docs/screenshots/web-users.png) | ![Invite dialog](docs/screenshots/web-invite.png) |
| **Send invites from your Gmail** | **Activity** |
| ![Email settings with a Gmail app password](docs/screenshots/web-email.png) | ![Activity with Now playing and a timeline](docs/screenshots/web-activity.png) |
| **Signed-in devices** | **Join from an invite** |
| ![Signed-in devices](docs/screenshots/web-account-devices.png) | ![Join page](docs/screenshots/web-join.png) |
| **Trusted proxies** | **Android TV (4K home)** |
| ![Trusted proxies in System](docs/screenshots/web-system-proxies.png) | ![Home on a 4K TV (1920-wide layout, eight posters in a row)](docs/screenshots/tv-home-1920x1080-dpr2.png) |
| **Movie details on a TV, Resume focused** | **Settings > Downloads** |
| ![Movie details on a TV with Resume focused](docs/screenshots/tv-details-resume-1920x1080-dpr2.png) | ![Settings > Downloads](docs/screenshots/web-settings-downloads.png) |
| **Player settings gear focused on a TV** | **Player settings menu on a TV** |
| ![Player with the settings gear focused](docs/screenshots/tv-player-settings-gear-1920x1080.png) | ![Player settings menu open with an option focused](docs/screenshots/tv-player-settings-menu-1920x1080.png) |
| **Download dialog** | **Devices and downloads** |
| ![Download quality dialog](docs/screenshots/web-download-dialog.png) | ![My account, Devices and downloads](docs/screenshots/web-account-devices-downloads.png) |
| **TV sign-in with a phone code (2.0.2)** | **Approve on the phone** |
| ![TV sign-in with a short code and QR code](docs/screenshots/2.0.2/tv-pair-code-qr-1920x1080.png) | ![Approve a TV from a signed-in phone](docs/screenshots/2.0.2/phone-pair-approve.png) |
| **TV account menu with Sign out** | **Settings > My account, Sign out** |
| ![Account menu on a TV with Sign out focused](docs/screenshots/2.0.2/tv-account-menu-signout-1920x1080.png) | ![My account with a Sign out button](docs/screenshots/2.0.2/tv-settings-account-signout-1920x1080.png) |
| **Plex-style TV home (2.1)** | **TV slide-out menu** |
| ![Television home with a backdrop hero and Continue watching](docs/screenshots/2.1/tv-home-continue-first.png) | ![Slide-out menu listing libraries as Name / NAS and Movies / Harbor](docs/screenshots/2.1/tv-menu-open.png) |
| **Settings > Sharing** | **A one-time share link** |
| ![Settings, Sharing, with a library shared by Harbor](docs/screenshots/2.1/sharing-overview.png) | ![Creating a share link and code](docs/screenshots/2.1/sharing-link.png) |
| **Signed-out TV sign-in (2.1.1)** | **Top bar matches the side menu** |
| ![Signed-out television showing only the phone-code sign-in screen](docs/screenshots/2.1.1/tv-signin-signed-out.png) | ![Desktop header in the same dark color as the sidebar](docs/screenshots/2.1.1/desktop-header-after.png) |
| **TV tab bar (2.1.1)** | |
| ![Television tab bar in the same dark color as the slide-out menu](docs/screenshots/2.1.1/header-after.png) | |
| **Transparent TV tab bar (2.1.2)** | **Movie page, Resume/Play focused** |
| ![Television home with a transparent tab bar over the backdrop](docs/screenshots/2.1.2/tv-home.png) | ![Movie details on a TV scrolled to the top with Resume focused](docs/screenshots/2.1.2/tv-details-play.png) |
| **TV slide-out menu with Sign out (2.1.2)** | |
| ![Slide-out menu open with Sign out focused](docs/screenshots/2.1.2/tv-menu-signout.png) | |

<p>
<img src="docs/screenshots/phone-home.png" width="200" alt="Phone home">
<img src="docs/screenshots/phone-libraries-player.png" width="200" alt="Phone libraries with the music mini player">
<img src="docs/screenshots/phone-nowplaying.png" width="200" alt="Phone now playing with the beat ring">
<img src="docs/screenshots/phone-equalizer.png" width="200" alt="Phone music equalizer with the Dynamic preset">
<img src="docs/screenshots/phone-playlists.png" width="200" alt="Phone playlists with Play and Shuffle">
<img src="docs/screenshots/phone-playlist-detail.png" width="200" alt="Phone playlist with play-from-track">
<img src="docs/screenshots/phone-player-bar.png" width="200" alt="Phone glass music mini player with mute">
<img src="docs/screenshots/phone-player-volume.png" width="200" alt="Phone volume popover above the mini player">
<img src="docs/screenshots/phone-chrome-glass.png" width="200" alt="Phone glass chrome and server status">
<img src="docs/screenshots/phone-library-filters.png" width="200" alt="Phone library filters">
<img src="docs/screenshots/status-toolbar-phone.png" width="200" alt="Phone header with CPU and RAM icons">
<img src="docs/screenshots/status-panel-phone.png" width="200" alt="Phone server status panel">
<img src="docs/screenshots/android-01-first-run.png" width="200" alt="Android first run">
<img src="docs/screenshots/android-03-sign-in.png" width="200" alt="Android sign in">
<img src="docs/screenshots/phone-users.png" width="200" alt="Phone Users tab with Invite by email">
<img src="docs/screenshots/phone-invite.png" width="200" alt="Phone invite dialog">
<img src="docs/screenshots/phone-email.png" width="200" alt="Phone Email tab with a Gmail app password">
<img src="docs/screenshots/phone-activity.png" width="200" alt="Phone Activity tab">
<img src="docs/screenshots/phone-account-devices.png" width="200" alt="Phone signed-in devices">
<img src="docs/screenshots/phone-join.png" width="200" alt="Phone join page">
<img src="docs/screenshots/phone-downloads-tab.png" width="200" alt="Phone Downloads tab">
<img src="docs/screenshots/phone-download-dialog.png" width="200" alt="Phone download dialog">
<img src="docs/screenshots/phone-settings-downloads.png" width="200" alt="Phone Settings, Downloads">
<img src="docs/screenshots/phone-offline.png" width="200" alt="Phone offline downloads list">
<img src="docs/screenshots/phone-offline-locked.png" width="200" alt="Phone offline unlock">
<img src="docs/screenshots/phone-offline-playing.png" width="200" alt="Phone playing a download offline">
</p>

*The screenshots use generated test media, placeholder posters, and made-up names at example.com. The 4K quality-menu shot was taken with **Cap quality to this screen** turned off, so 4K options stay visible; the tablet shot shows the default cap at 1080p. The 1.9 shots show Users and Invite, Email (Gmail app password), Activity, signed-in devices, Trusted proxies, and the join page, with documentation addresses such as 192.0.2.10. The 1.9.1 shot shows the Home row on a 1920×1080 television with the purple D-pad focus ring on a poster. The 2.0 shots show the 4K TV home and a movie page with Resume focused, the Downloads tab, the download dialog, Settings > Downloads, and the offline screens. The 2.0.1 shots show the video player on a television with the settings gear focused, and the settings menu open with an option focused. The 2.0.2 shots show TV sign-in with a short code and QR code, approving it from a phone, and reaching Sign out with the remote. The 2.1 shots show the Plex-style TV home and slide-out menu (libraries labelled with their source, including a library shared by another server) and Settings > Sharing. The 2.1.1 shots show a signed-out television with only the phone-code sign-in screen, and the top bar (TV tab bar and desktop header) in the same dark color as the side menu. The 2.1.2 shots show the TV tab bar transparent over the backdrop, the slide-out menu with Sign out, and a movie page opened at the top with Resume or Play focused.*

## Features

- **Libraries** for movies, TV shows, music and other videos, from a local folder, an SMB/Windows share or an NFS export.
  Shares are mounted **read-only**. A folder browser lets you pick the folder, and once you've signed in to a share you can reuse it for more libraries.
- **Scanning** with progress, resume and scheduled rescans. Names are parsed from files and folders (title, year,
  edition, `S01E02`).
- **TMDB metadata (optional):** posters, backdrops, overviews, cast, collections, similar movies and episode titles.
- **Playback in the browser:** direct play, remux (including HEVC to fMP4) or HLS transcode with quality choices (360p to 1080p, plus 2K/4K with a GPU). Auto quality prefers direct play or remux over a transcode. Subtitles (`.srt`, embedded) are see-through and stay on after a seek or quality change; pinch to fit or fill the picture on a phone. The music player has a beat-reactive visualizer, playlists with Play and Shuffle (and play-from-track), mute and a reachable volume control, and a 10-band equalizer with presets (including Dynamic). The top bar, mini player and phone tab bar use the same frosted glass as the server status popup.
- **Hardware transcoding:** Intel VAAPI/QSV (plus AMD VAAPI and NVIDIA NVENC, both untested). Video cards are detected on install. Concurrent 4K streams use extra GPU surfaces and the card's low-power encoder; a stream that cannot stay on the GPU falls back once and stays there, with the reason logged. The same account can play on more than one device at a time.
- **Home rows** (Continue watching, Recently added, Recommended), My List, search, genres, decades, tags and collections.
- **Phone layout** with a bottom tab bar and filter sheets, plus an installable web app (PWA) and a native **Android app**. On a television, a D-pad moves a purple focus ring across libraries, poster rows and player controls (1.9.1). Opening a title focuses Resume or Play (1.9.2), and the TV layout is authored at 1920×1080 so a 4K set is not zoomed in. While a film is playing, the remote reaches every player control, including the settings gear at the bottom right (2.0.1). A TV can sign in by scanning a code with a phone that's already signed in, stays signed in, and the remote reaches the account menu and Sign out (2.0.2). On a TV, 2.1 uses a Plex-style home: a backdrop of the focused title, a slim left rail that slides out into a full menu, and tabs across the top. In 2.1.1 a signed-out TV shows only the sign-in screen, sign-in codes are reused until they expire, and the top bar uses the same dark color as the side menu. In 2.1.2 the web header is hidden on a television, the TV tab bar is transparent, moving the remote onto a tab or menu item opens that view without OK (Sign out still needs OK), and opening a title keeps Resume or Play on screen. The 2.0.2 Android TV app works as-is.
- **Multiple users** with Admin, Viewer, and Viewer + Downloads roles, per-library access, email invites sent from your own Gmail (or a copyable link and QR code), a signed-in device list, and Settings > Activity (now playing and a timeline). Existing accounts keep their access after the update. A themed server status panel shows CPU and RAM icons and rings, disks, idle GPU, and background cache jobs that pause when you press play.
- **Library sharing between servers (2.1):** an admin shares one or more libraries with another Movinite server by sending a one-time link and code. After that, the two servers trust each other with signed requests (no central service). Shared libraries appear in the other server's list, search, home and TV menu, labelled with the owner's name. Public addresses must use HTTPS (for example `https://media.example.com`); a LAN address may use plain HTTP (for example `http://192.0.2.10:8099`).
- **Offline downloads (2.0, Android app):** people with Viewer + Downloads (and admins) can download films and episodes to the app, play them with the phone's network off, and manage devices and quotas from Settings > Downloads or My account. Downloads are encrypted on the phone; licences last 30 days and can be taken back.

## Requirements

- **Ubuntu Server 24.04 LTS** (22.04 also works), x86-64, with `sudo`. A VM is fine.
- About 1 GB RAM plus 1 CPU core per CPU transcode (or a supported GPU), and disk space for thumbnails and the transcode cache.
- The installer pulls in Python 3, ffmpeg, cifs-utils, nfs-common and smbclient from Ubuntu's repositories.

## Quick install

Download `media-server-verX.Y.Z.tar.gz` (and its `.sha256`) from the [Releases](../../releases) page onto the server, then run:

```bash
sha256sum -c media-server-verX.Y.Z.tar.gz.sha256
tar -xzf media-server-verX.Y.Z.tar.gz media-server/install.sh --strip-components=1
sudo bash install.sh                 # or: sudo bash install.sh --port 8096
```

The installer unpacks into `/opt/media-server`, creates a locked-down service user and the systemd service `media-server`,
then prints the address (`http://<server-ip>:8099`) and a **random admin password**. That password is also saved, readable by root only,
in `/opt/media-server/ADMIN_PASSWORD`. Sign in as `admin` and choose your own password, then delete the file.

*(Internally the app is still called `media-server`: the service, folder, tarball and API names are unchanged.)*

## Update

```bash
sudo bash /opt/media-server/update.sh /path/to/media-server-verX.Y.Z.tar.gz
```

`update.sh` checks the `.sha256` file if it's next to the tarball, then backs up the code, `.env` and the database to
`/opt/media-server/backups/`. It then installs the new code, upgrades the database, restarts the service and confirms the new version is running.
If any step fails, it rolls back automatically. To undo an update yourself:

```bash
sudo bash /opt/media-server/update.sh --rollback /opt/media-server/backups/media-server-pre-X.Y.Z-YYYYMMDD-HHMMSS.tgz
```

## GPU transcoding

- On install and the first start, Movinite looks for video cards and turns on the first method that passes a short test encode.
  You can change it any time in **Settings → Transcoding**, which has *Auto*, *VAAPI*, *Intel QSV*, *NVIDIA* and *Off (CPU)*
  options and a *Test* button for each.
- **Intel (Arc, iGPU):** the installer adds `intel-media-va-driver-non-free`, `vainfo` and the oneVPL runtime
  (`libvpl2`, `libmfx-gen1.2`) when they're available, and gives the service access to `/dev/dri/renderD*`. VAAPI works out of the box.
  If the QSV test fails, run `sudo apt install libmfx-gen1.2`.
- **AMD:** VAAPI through `mesa-va-drivers` (detected, but not tested on real hardware).
- **NVIDIA:** install the proprietary driver first. NVENC support is included but hasn't been tested on real hardware yet.
- **2K/4K** quality is offered only when the GPU is in use, and only for sources at least that size. Movinite never upscales.
  HEVC is used when the device can play it, otherwise H.264.
- **HDR** sources are converted without tone-mapping, so their colours can look flat.
- In a short preliminary test, an Intel Arc A310 handled about 6 × 4K, 10 × 2K or 12 × 1080p transcodes at once.
  Results depend on the source; see [server/README.md](server/README.md#2k-and-4k-153).

## Android app

The app is in [`android/`](android/). On first launch it asks for your server's address (for example
`https://movies.example.com` or `http://192.0.2.10:8099` on your home network) and then shows a native sign-in screen.
To change the server later, tap the gear on the sign-in screen. Picture-in-picture and rotate-to-full-screen are built in.
Version **2.0** adds offline downloads (a Downloads tab, encrypted storage, and playback with the network off), a
Movinite banner for the Android TV home screen, and WebView zoom settings so a 4K TV is not magnified.
Version **2.1.2** hides the web header on a television, makes the TV tab bar transparent, opens a tab or menu item when you pause on it (Sign out still needs OK), and keeps Resume or Play in view when you open a title. Version **2.1.1** keeps the 2.1 Plex-style TV home and library sharing, and fixes signed-out TV sign-in (the home chrome no longer covers the code, and codes are reused until they expire). The top bar matches the side menu. Version **2.1** keeps the 2.0.2 code-and-QR TV sign-in and adds the Plex-style TV home and library sharing. Version **2.0.2** shows the code-and-QR sign-in on a TV (no typing with the remote) and lists Movinite servers found on
your network during setup (`_movinite._tcp`); you can still type the address.

To install it, download `movinite-android-vX.Y.apk` from [Releases](../../releases) onto your phone or TV, then open it
from the **Files** app. Allow "Install unknown apps" when Android asks. A TV also needs the 2.0 app sideloaded for the
home-screen banner. To build it yourself, see [android/README.md](android/README.md). This repository does not include
pre-built APKs.

## Access from outside your network

Put Movinite behind a reverse proxy with HTTPS, such as Caddy or nginx. The examples are in
[server/README.md](server/README.md#https--access-from-outside-reverse-proxy).
In **Settings > System > Trusted proxies**, list the proxy's address (for example `192.0.2.10`) so Movinite sees each visitor's real address for sign-in lockouts, the device list, and Activity.

## Documentation

- [server/README.md](server/README.md): full server guide (libraries, naming, TMDB, playback, shares, proxy, file locations)
- [docs/gmail-setup.md](docs/gmail-setup.md): send invites from your Gmail (app password, or Connect Gmail)
- [CHANGELOG.md](CHANGELOG.md) and [server/CHANGELOG.md](server/CHANGELOG.md)
- [docs/android-signing.md](docs/android-signing.md): making a release key for the Android app
- [docs/releasing.md](docs/releasing.md): building and publishing a release (GitHub Actions)
- [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## License

Movinite is free software under the **GNU Affero General Public License v3.0** ([LICENSE](LICENSE)). You may use,
study, change and share it. If you share a changed version, or run one for other people over a network, you must make
its source code available under the same license.

This product uses the TMDB API but is not endorsed or certified by TMDB.
