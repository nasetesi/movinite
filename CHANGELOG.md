# Changelog

The full server history (1.0 to 1.6) is in [server/CHANGELOG.md](server/CHANGELOG.md). This file covers the
repository as a whole and the Android app.

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
