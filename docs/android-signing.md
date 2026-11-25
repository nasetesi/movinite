# Signing the Android app

Android only installs an update over an existing app when **both APKs are signed with the same key**. Make one release
key, keep it private, and **back it up**. If you lose it, users have to uninstall the app before they can install your next build.

Without a key, `android/build-apk.sh` builds a **debug-signed** APK (`movinite-android-vX.Y-debug.apk`). That's fine for
testing, but don't publish it as a release.

## 1. Create a keystore (once)

You need the JDK's `keytool` (JDK 17):

```bash
mkdir -p android/keystore && cd android/keystore      # android/keystore/ is in .gitignore
keytool -genkeypair -v -keystore movinite-release.jks -alias movinite \
        -keyalg RSA -keysize 4096 -validity 10000 \
        -dname "CN=Your Name, O=Movinite"
# keytool asks for the keystore password and the key password. Use strong ones and store them in a password manager.
```

## 2. Local builds: `keystore.properties`

Create `android/keystore/keystore.properties` (also ignored by git):

```properties
storeFile=movinite-release.jks
storePassword=<keystore password>
keyAlias=movinite
keyPassword=<key password>
```

Then run `cd android && ./build-apk.sh ../dist` to get a signed `movinite-android-vX.Y.apk` and its `.sha256`.
You can also point to the file from anywhere with `KEYSTORE_PROPS=/path/to/keystore.properties ./build-apk.sh`.

## 3. GitHub Actions: repository secrets

In the repository, go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Value |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | the keystore file, base64-encoded: `base64 -w0 movinite-release.jks` |
| `ANDROID_KEYSTORE_PASSWORD` | the keystore password |
| `ANDROID_KEY_ALIAS` | the key alias (e.g. `movinite`) |
| `ANDROID_KEY_PASSWORD` | the key password |

The release workflow decodes the keystore into a temporary file. It passes the values to Gradle as the
`MOVINITE_KEYSTORE_FILE`, `MOVINITE_KEYSTORE_PASSWORD`, `MOVINITE_KEY_ALIAS` and `MOVINITE_KEY_PASSWORD` environment variables,
then deletes the file. If the secrets aren't set, the workflow still runs and attaches a **debug-signed** APK instead.

## Checking a signed APK

```bash
$ANDROID_HOME/build-tools/34.0.0/apksigner verify --print-certs movinite-android-vX.Y.apk
```

Publish the certificate's SHA-256 digest in the release notes so users can check it.
