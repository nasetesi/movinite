# Changelog

The full server history (1.0 to 1.5.3) is in [server/CHANGELOG.md](server/CHANGELOG.md). This file covers the
repository as a whole and the Android app.

## Unreleased: first public release

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
