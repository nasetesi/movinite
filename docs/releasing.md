# Releasing

1. Bump the versions:
   - Server: `server/app/version.py` and `server/CHANGELOG.md`
   - Android (if changed): `versionCode`/`versionName` in `android/app/build.gradle`, `VERSION` in
     `android/app/src/main/java/org/movinite/app/BuildConfigInfo.java`, and `CHANGELOG.md`
2. Run the tests (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
3. Commit, then tag and push:

   ```bash
   git tag -a v1.5.3 -m "Movinite 1.5.3"
   git push origin main --tags
   ```

4. The **Release** workflow (`.github/workflows/release.yml`) builds:
   - `media-server-verX.Y.Z.tar.gz` and `.sha256`, using `scripts/pack-server.sh`
   - `movinite-android-vX.Y.apk` and `.sha256`, signed with the repository secrets (see
     [android-signing.md](android-signing.md)), or `...-debug.apk` if those aren't set

   It then creates a **draft** GitHub Release for the tag with these files attached. Review the notes, then publish it.

To build locally instead, run `bash scripts/pack-server.sh dist/` and `cd android && ./build-apk.sh ../dist`.

The tarball's top folder is `media-server/`, and the file name stays `media-server-verX.Y.Z.tar.gz`. That keeps
`install.sh` / `update.sh` (which look for `media-server-ver*.tar.gz`) working for existing installs.
