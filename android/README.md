# Movinite for Android

A small native Android app for your Movinite server. It has a native sign-in screen, and once you're signed in it shows
the server's web app in a WebView, with picture-in-picture and rotate-to-full-screen added.

* Package `org.movinite.app`, Android 7.0+ (minSdk 24, targetSdk 34).
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
