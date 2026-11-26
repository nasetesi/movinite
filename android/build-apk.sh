#!/usr/bin/env bash
# build-apk.sh -- build and sign the Movinite Android app (release APK).
#   ./build-apk.sh [output-dir]      (default output: the folder above this one, i.e. the Media-Server folder)
# Needs JDK 17 and the Android SDK (platform 34, build-tools 34.0.0):
#   JAVA_HOME / ANDROID_HOME from the environment, else the box defaults below.
# Signs with keystore/keystore.properties + keystore/media-server-release.jks (override with KEYSTORE_PROPS=...).
# Always sign updates with the SAME key, otherwise Android refuses to install them over the installed app.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$PWD"
export JAVA_HOME="${JAVA_HOME:-/workspace/tools/jdk-17.0.21.1+2}"
export ANDROID_HOME="${ANDROID_HOME:-/workspace/tools/android-sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$JAVA_HOME/bin:$PATH"
export KEYSTORE_PROPS="${KEYSTORE_PROPS:-$HERE/keystore/keystore.properties}"
BT="$ANDROID_HOME/build-tools/34.0.0"
OUT="${1:-$HERE/..}"
[ -x "$JAVA_HOME/bin/java" ] || { echo "JDK 17 not found (set JAVA_HOME)"; exit 1; }
[ -d "$BT" ] || { echo "Android build-tools 34.0.0 not found (set ANDROID_HOME)"; exit 1; }
[ -f "$KEYSTORE_PROPS" ] || { echo "keystore.properties not found: $KEYSTORE_PROPS"; exit 1; }
echo "sdk.dir=$ANDROID_HOME" > local.properties
V="$(sed -n "s/^ *versionName '\(.*\)'/\1/p" app/build.gradle)"
grep -q "VERSION = \"$V\"" app/src/main/java/org/movinite/app/BuildConfigInfo.java || { echo "BuildConfigInfo.VERSION must match versionName $V"; exit 1; }
chmod +x gradlew 2>/dev/null || true
bash ./gradlew --no-daemon -q clean assembleRelease
APK="app/build/outputs/apk/release/app-release.apk"
[ -f "$APK" ] || { echo "no signed APK produced -- check keystore.properties"; exit 1; }
"$BT/apksigner" verify --print-certs "$APK" | grep -E "Signer #1 certificate (DN|SHA-256)" || { echo "apksigner verify FAILED"; exit 1; }
DEST="$OUT/movinite-android-v$V.apk"
cp "$APK" "$DEST"
( cd "$(dirname "$DEST")" && sha256sum "$(basename "$DEST")" > "$(basename "$DEST").sha256" )
echo "$DEST"; cat "$DEST.sha256"
