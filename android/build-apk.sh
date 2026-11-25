#!/usr/bin/env bash
# build-apk.sh -- build the Movinite Android app.
#   ./build-apk.sh [output-dir]          (default output: ../dist)
#
# Signing:
#   * With a release key (keystore/keystore.properties, KEYSTORE_PROPS=/path/to/keystore.properties, or the
#     MOVINITE_KEYSTORE_FILE / MOVINITE_KEYSTORE_PASSWORD / MOVINITE_KEY_ALIAS / MOVINITE_KEY_PASSWORD environment
#     variables) it builds a signed release APK:   movinite-android-v<version>.apk
#   * Without one it builds a debug-signed APK:     movinite-android-v<version>-debug.apk
#     (installs fine for testing, but can't be updated later by a release-signed build -- uninstall first).
#   See ../docs/android-signing.md for making your own key. Never commit the key or its passwords.
#
# Needs JDK 17 and the Android SDK (platform 34, build-tools 34.0.0): set JAVA_HOME and ANDROID_HOME.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$PWD"
[ -n "${JAVA_HOME:-}" ] && export PATH="$JAVA_HOME/bin:$PATH"
command -v java >/dev/null || { echo "JDK 17 not found (set JAVA_HOME)"; exit 1; }
[ -n "${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}" ] || { echo "Android SDK not found (set ANDROID_HOME)"; exit 1; }
export ANDROID_HOME="${ANDROID_HOME:-$ANDROID_SDK_ROOT}"; export ANDROID_SDK_ROOT="$ANDROID_HOME"
BT="$ANDROID_HOME/build-tools/34.0.0"
[ -d "$BT" ] || { echo "Android build-tools 34.0.0 not found in $ANDROID_HOME"; exit 1; }
OUT="${1:-$HERE/../dist}"; mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
[ -z "${KEYSTORE_PROPS:-}" ] && [ -f "$HERE/keystore/keystore.properties" ] && export KEYSTORE_PROPS="$HERE/keystore/keystore.properties"
echo "sdk.dir=$ANDROID_HOME" > local.properties
V="$(sed -n "s/^ *versionName '\(.*\)'/\1/p" app/build.gradle)"
grep -q "VERSION = \"$V\"" app/src/main/java/org/movinite/app/BuildConfigInfo.java || { echo "BuildConfigInfo.VERSION must match versionName $V"; exit 1; }
chmod +x gradlew 2>/dev/null || true
if [ -n "${KEYSTORE_PROPS:-}" ] || [ -n "${MOVINITE_KEYSTORE_FILE:-}" ]; then
  bash ./gradlew --no-daemon -q clean assembleRelease
  APK="app/build/outputs/apk/release/app-release.apk"; DEST="$OUT/movinite-android-v$V.apk"
  [ -f "$APK" ] || { echo "no signed APK produced -- check the signing settings"; exit 1; }
else
  echo "No release key configured -> building a debug-signed APK (see docs/android-signing.md)."
  bash ./gradlew --no-daemon -q clean assembleDebug
  APK="app/build/outputs/apk/debug/app-debug.apk"; DEST="$OUT/movinite-android-v$V-debug.apk"
  [ -f "$APK" ] || { echo "no APK produced"; exit 1; }
fi
"$BT/apksigner" verify --print-certs "$APK" | grep -E "Signer #1 certificate (DN|SHA-256)" || { echo "apksigner verify FAILED"; exit 1; }
cp "$APK" "$DEST"
( cd "$OUT" && sha256sum "$(basename "$DEST")" > "$(basename "$DEST").sha256" )
echo "$DEST"; cat "$DEST.sha256"
