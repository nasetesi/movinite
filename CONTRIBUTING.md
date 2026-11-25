# Contributing to Movinite

Thanks for helping! Bug reports, fixes, translations and ideas are all welcome.

## Ground rules

- By contributing, you agree that your contribution is licensed under the project's license, the **AGPL-3.0**.
- Be kind and constructive in issues and reviews.
- **Never put secrets in issues or pull requests.** That includes passwords, API keys, keystores, `.env` files, real
  server addresses and share names. Use `example.com`, `192.0.2.x` and fake usernames in examples and tests.
- Report security problems privately (see [SECURITY.md](SECURITY.md)), not in public issues.

## Repository layout

| Path | What |
|---|---|
| `server/` | The server: FastAPI app (`app/`), static web UI (`app/static/`), `install.sh`, `update.sh`, root mount helper (`helpers/`), tests |
| `android/` | The Android app (Java, Gradle, no AndroidX) |
| `scripts/pack-server.sh` | Builds `media-server-verX.Y.Z.tar.gz` and its `.sha256` |
| `docs/` | Screenshots, signing and release notes |
| `.github/workflows/` | CI: release build on tags |

## Running the server for development

```bash
cd server
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
sudo apt install ffmpeg            # ffprobe/ffmpeg are needed for scans and playback
MS_DATA_DIR=/tmp/movinite-dev MS_SHARES_DIR=/tmp/movinite-shares python -m uvicorn main:app --host 127.0.0.1 --port 8150
# open http://127.0.0.1:8150 and create the first admin account
```

SMB and NFS shares need the root mount helper and sudoers rule that `install.sh` sets up. For development, local
folders are easiest.

## Tests

The tests are plain Python scripts that print `ok` / `FAIL` lines and exit non-zero on failure:

```bash
cd server
bash tests/make_testmedia.sh                 # once: generates tests/testmedia/ with ffmpeg (synthetic clips)
for t in tests/test_*.py; do python3 "$t" || echo "FAILED: $t"; done
```

Some tests start a mock TMDB server (`tests/mock_tmdb.py`), so no real TMDB key is needed. Android-related static checks
read `../android` (override with `ANDROID_SRC=`).

## Pull requests

1. Fork, then create a branch from `main`.
2. Keep changes focused, and match the existing style: plain JS/CSS, no build step and no new frontend dependencies.
3. Add or update tests for behaviour changes, and run them.
4. Update `server/CHANGELOG.md` (server) or `CHANGELOG.md` (Android/repo), and the docs if behaviour changes.
5. If the database schema changes, `update.sh` must upgrade existing installs, and rollback must keep working.

## Building

- Server tarball: `bash scripts/pack-server.sh dist/`
- Android APK: `cd android && ./build-apk.sh ../dist` (debug-signed without a key; see `docs/android-signing.md`)
