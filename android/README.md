# Movinite for Android

A native Android app for your Movinite server. It has a native sign-in screen, and once you're signed in it shows
the server's web app in a WebView, with picture-in-picture, rotate-to-full-screen, and (from 2.0) offline downloads.

* Package `org.movinite.app`, Android 7.0+ (minSdk 24, targetSdk 34). **2.0** is `versionCode` 8.
* **First launch:** a welcome screen asks for your server's address (for example `https://movies.example.com`, or
  `http://192.0.2.10:8099` on your home network). **Test** checks it with the server's `/api/health`, and **Connect** saves it.
  Then the native **Sign in** screen appears.
* **Sign in:** username and password, with Show/Hide. The app calls the server's `/api/login` and passes the session
  cookie to the WebView. It never stores your password; the session cookie keeps you signed in (30 days by default on the server).
* **Change the server later:** use the gear icon at the top right of the Sign in screen. You can also long-press the logo,
  or long-press the app icon and choose **Server settings**. Plain `http://` is only allowed for the server you entered.
* **Picture in picture** (Android 8+): tap the PiP button in the player, or press Home while a film plays.
* **Rotate = full screen:** while the player is open, turning the phone sideways hides the system bars and makes the player
  full screen. Turning it upright brings the bars back.
* **2.0 — offline downloads:** people with the Viewer + Downloads role (and admins) can download films and episodes in the app.
  A **Downloads** tab replaces My List in the bottom tabs (My List stays on Home and in the account menu). Downloads run in
  the background over Wi-Fi by default, are stored encrypted, and play in the app's own player when you're offline. Unlock
  with your fingerprint, face, screen lock, or a Movinite PIN. Licences last 30 days and renew when the app syncs; sign-out,
  revoke, or 30 days without a sync removes the downloads. This is trust-based protection for family and friends, not
  studio-grade DRM, and the app says so.
* **2.0 — Android TV:** the app includes a Leanback launcher and a Movinite wordmark banner for the TV home row, plus
  WebView zoom settings (`setTextZoom(100)` on televisions only, wide viewport) so a 4K TV shows the server's 1920-wide
  layout instead of a zoomed-in page. The D-pad uses the server's TV remote navigation (1.9.1 and 1.9.2).

## Build

    ./build-apk.sh [output-dir]      # default output: ../dist

This needs JDK 17 and the Android SDK (platform 34, build-tools 34.0.0), with `JAVA_HOME` and `ANDROID_HOME` set.

* **No signing key configured:** you get a debug-signed `movinite-android-v<version>-debug.apk`, which is fine for trying the app.
* **Release key configured:** you get a signed `movinite-android-v<version>.apk`.

To make a release key, see [../docs/android-signing.md](../docs/android-signing.md).
Never commit a keystore or its passwords; `.gitignore` already excludes `keystore/`, `*.jks` and `keystore.properties`.

For a new version, bump `versionCode` / `versionName` in `app/build.gradle` and `VERSION` in `BuildConfigInfo.java`.

> Android only installs an update over an existing app when both are signed with the **same key**.
> Keep your release keystore backed up.
