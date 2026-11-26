# Changelog

The full server history (1.0 to 1.9) is in [server/CHANGELOG.md](server/CHANGELOG.md). This file covers the
repository as a whole and the Android app.

## 2.0.2 -- 2026-11-25

Server 2.0.2 and Android app 2.0.2 (`versionCode` 9). Schema stays 11. Details are in [server/CHANGELOG.md](server/CHANGELOG.md).

- **Sign in on a TV with your phone:** the TV shows a short code and a QR code; approve it from a phone that's already signed in and the TV gets its own session. Codes last about 10 minutes and work once. Username and password still work.
- **Stay signed in:** sessions refresh while you use them (30 days from last activity).
- **Find the server:** the server advertises itself on the local network (`_movinite._tcp`, plus `/.well-known/movinite.json`); the 2.0.2 app lists servers it finds during setup. Typing the address still works.
- **Sign out with the remote:** Up from the first row reaches the header; the account button opens a menu with Sign out. Settings > My account also has a Sign out button.

## 2.0.1 -- 2026-11-25

Server 2.0.1 is a quick fix on 2.0. The Android app is unchanged (its WebView uses the same JS). Details are in [server/CHANGELOG.md](server/CHANGELOG.md).

- **2.0.1 — TV player settings are reachable with the remote:** Left and Right walk every player control, including the settings gear at the bottom right (quality, picture and speed). Up and Down move between the seek bar and the button row. The settings menu is navigable; Back closes the menu, then hides the controls, then returns to the details page. When the controls are hidden, Left and Right still skip 10 seconds and OK pauses.

## 2.0 -- 2026-11-25

Server 2.0 (schema 11) builds on 1.9.2 and adds offline downloads in the Android app. Details are in [server/CHANGELOG.md](server/CHANGELOG.md).

- **2.0 — offline downloads in the Android app:** people with Viewer + Downloads (and admins) can download films and episodes, play them offline, and manage devices and quotas from Settings > Downloads. Downloads are encrypted on the phone; licences last 30 days and can be taken back. The Android app 2.0 (`org.movinite.app`, versionCode 8) also includes the TV home-screen banner and WebView zoom fix for 4K sets. Opening a title on a television focuses Resume or Play, and the TV layout is sized for a 1920-wide page (1.9.2).

## 1.9.2 -- 2026-11-25

Server 1.9.2 is a quick fix on 1.9.1. Details are in [server/CHANGELOG.md](server/CHANGELOG.md).

- **1.9.2 — TV details focus and 4K layout:** opening a movie or show focuses Resume or Play instead of jumping to Similar movies. Up and down stay inside the details. The TV page is laid out at 1920×1080 and scaled to the WebView's CSS size so a 4K television does not look zoomed in. The wide banner on the Android TV home screen ships with app 2.0.

## 1.9.1 -- 2026-11-25

Server 1.9.1 is a quick fix on 1.9. The Android app is unchanged (its WebView uses the same JS); a Leanback launcher and `isTv()` bridge are planned for app 2.0. Details are in [server/CHANGELOG.md](server/CHANGELOG.md).

- **1.9.1 — TV remote / D-pad navigation:** library tiles and movie posters are focusable, so an Android TV remote no longer skips the library list and the movie rows. Arrow keys move a large purple focus ring within and between rows; OK or Enter opens the focused item; Back closes the player or goes back. Televisions are detected automatically.

## 1.9 -- 2026-11-25

Server 1.9 adds email invites, roles, per-library access, a device list, Settings > Activity, and a fix for sign-in lockouts behind a proxy (schema 10). The Android app is unchanged (its WebView uses the same JS). Details are in [server/CHANGELOG.md](server/CHANGELOG.md).

- **1.9 — invite people from your Gmail, roles, Activity, and the real visitor address:** Settings > Users can invite someone by email as a Viewer or Viewer + Downloads, with optional library limits. Invites are sent from your own Gmail with a 16-letter app password (Connect Gmail remains under Advanced). Without email, you get a one-time link and a QR code. My account lists signed-in devices with remote sign-out. Settings > Activity shows who is playing and a filterable timeline. Behind a reverse proxy, list the proxy under Settings > System > Trusted proxies so lockouts and Activity use the real client address instead of treating every visitor as the proxy. Existing accounts keep their access; sessions stay signed in (tokens are now stored hashed).

## 1.8.1 -- 2026-11-25

Server 1.8.1 is a quick fix on 1.8. The Android app is unchanged (its WebView uses the same JS). Details are in [server/CHANGELOG.md](server/CHANGELOG.md).

- **1.8.1 — play playlists, mute and volume, frosted-glass chrome:** Play and Shuffle are on the playlist list as well as the playlist page, and you can start a playlist from any song in it. A mute button sits next to the volume control (M toggles it) and remembers the last level. Volume sits with the play controls; on a phone a vertical slider opens above the mini player. The top bar, mini player, and phone tab bar use the same frosted glass as the Server status popup.

## 1.8 -- 2026-11-25

Server 1.7.3 through 1.8 were not published as separate GitHub releases. This update brings the repository to **server 1.8**. The Android app is unchanged. Details are in [server/CHANGELOG.md](server/CHANGELOG.md).

- **1.8 — themed server status, and background jobs that yield to play:** the header shows compact CPU and RAM icons with percentages (the full RAM size is in the tooltip and the dropdown). The status panel uses the purple theme, with ring gauges, wrapping disk names, a clear note when a share does not report used space, "Idle · GPU" when the card is ready, and a separate line for background cache work. Pressing play immediately stops an in-flight subtitle extract, remux probe, or opening-clip prefetch so it no longer delays the first picture.

## 1.7.9 -- 2026-11-25

Server 1.7.3 through 1.7.9 were not published as separate GitHub releases. This update brings the repository to **server 1.7.9**. The Android app is unchanged. Details are in [server/CHANGELOG.md](server/CHANGELOG.md).

- **1.7.9 — faster first picture, and caches:** the first HLS clip is 2 seconds (with matching keyframes) instead of 6, and ffmpeg starts when the playlist is requested. Subtitles, remux cut points, rotation and HDR colour info are prepared in the background. Recently added titles and Continue Watching can have their first 6 seconds pre-made at 1080p (Settings → Transcoding, default 2 GB cache). The GPU encoder is warmed after a restart. Versioned app files are cached for a year; API and HLS are not. Schema 9 (a backup of the database is written first).

## 1.7.8 -- 2026-11-25

Server 1.7.3 through 1.7.8 were not published as separate GitHub releases. This update brings the repository to **server 1.7.8**. The Android app is unchanged. Details are in [server/CHANGELOG.md](server/CHANGELOG.md).

- **1.7.8 — cap quality to the device, and pause transcodes that are far ahead:** the player reports the screen size (and a decode check when the browser supports it). A 1920×1200 tablet is sent 1080p even if 4K was saved earlier. Direct play and remux are used only when the file fits that cap. The player shows "Auto-capped to 1080p", and Settings → My account can turn the cap off on this device. ffmpeg also pauses again once it is far enough ahead of the player (a bug after old segments were deleted had left it running at full speed).

## 1.7.7 -- 2026-11-25

Server 1.7.7 added concurrent 4K on the GPU and same-account playback on two devices. The Android app is unchanged. Details for each step are in [server/CHANGELOG.md](server/CHANGELOG.md).

- **1.7.7 — concurrent 4K and same-account devices:** two 4K HEVC transcodes can stay on an Intel Arc GPU (`-extra_hw_frames 64`, `-low_power 1`, `tonemap_vaapi` when available). A stream that cannot stay on the GPU falls back once, with the reason logged, and does not flip back and forth or park the card for everyone. The same login can play on two devices at once (a cap, default 4, is under Settings > Transcoding). ffmpeg warnings and the last 50 lines of a failed job are copied into the journal. Auto quality prefers direct play or remux, including HEVC remux to fMP4.
- **1.7.6 — music player and playlists:** themed now-playing chrome, top controls that fade after a few seconds, a beat-reactive purple ring mixed with a smaller logo (no square tile), and per-user playlists (schema 8).
- **1.7.5 — player polish:** pinch to fit or fill on a phone, captions that load promptly and stay see-through, and a glass 2×2 stats panel at the top of the player (the GPU badge stays a solid purple pill).
- **1.7.4 — outlined library icons** in the purple theme, on the Libraries tab, sidebar, headings, Settings, and the Add library type picker.
- **1.7.3 — previous/next and the equalizer:** themed skip buttons in the video player, and a 10-band equalizer with a Dynamic preset in the music player.

## 1.6 -- 2026-11-24

From 1.6, versions have two parts (1.6, 1.7, ...); a third digit is only for quick fixes (1.6.1).
This release includes the server changes from 1.5.4 and 1.5.5, which were not published separately.
Details are in [server/CHANGELOG.md](server/CHANGELOG.md).

- **Server 1.6:**
  - **Libraries in your order:** admins drag (or, on touch screens, move up/down) libraries in Settings -> Libraries.
    The order is used in the side menu, phone tabs, home rows and the Android app. New libraries default to
    Movies, TV Shows, Other videos, Music. New `PUT /api/libraries/order`; new `libraries.sort_order` column (automatic).
  - **Settings tabs** in this order: Libraries, Scan activity, Poster Sounds, Metadata, Transcoding, Users, My account, System.
  - **Share status dot** next to network-share libraries in the side menu (online / slow / offline), checked every 45 s
    with a 3 s limit so a hung share never stalls the server. `GET /api/libraries` returns `health`;
    `POST /api/libraries/health` checks on demand.
- **Server 1.5.5:** artwork saved to folders for TV shows (show, season and episode images, `tvshow.nfo`);
  Poster Sounds moved to its own Settings tab; Continue watching and Recently added show only Movies and TV.
- **Server 1.5.4:** sharper H.264 2K/4K from HEVC/AV1/VP9 sources (1.8x source bitrate, at least 12 Mbps for 4K);
  dropped-frame counter in the player status pill; HLS MPEG-TS segments start exactly on their playlist time.
- **Android app 1.6:** unchanged. Release builds are now signed by CI with the project's release key.

## 1.5.3 -- first public release

- Movinite is now open source under the **GNU AGPL-3.0**.
- **Server 1.5.3**, unchanged in behaviour. The examples in the UI and docs now use documentation addresses (`192.0.2.10`, `example.com`).
  Developer tooling: `scripts/pack-server.sh` and `server/tests/make_testmedia.sh` (synthetic test media).
- **Android app 1.6** (package `org.movinite.app`):
  - **First-run setup:** on first launch the app asks for your server's address and tests it, then shows the sign-in screen.
    There is no built-in default server any more. The gear on the sign-in screen still opens Server settings to change it.
  - `build-apk.sh` makes a debug-signed APK when no release key is set up, and a signed release APK when one is
    (a properties file, or `MOVINITE_*` environment variables for CI).
- **GitHub Actions** (`.github/workflows/release.yml`): pushing a `v*` tag builds the server tarball and the Android
  APK, adds checksums and attaches them to a GitHub Release.

## Android app history (before the public release)

- **1.5:** the sign-in screen matches the web sign-in page (full logo in a translucent card). Back closes the account menu
  of the phone layout.
- **1.4:** renamed to Movinite, with the purple theme, the M logo as an adaptive and themed launcher icon, and rotate-to-full-screen in the player.
- **1.3:** picture-in-picture (Android 8+).
- **1.2:** a gear icon on the sign-in screen for server settings.
- **1.1:** a native username/password sign-in screen, handing the session cookie to the WebView.
- **1.0:** the first release, a WebView app with a server-address setup screen.
