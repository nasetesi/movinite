# Third-party notices

Movinite is licensed under the GNU AGPL-3.0 (see [LICENSE](LICENSE)). It includes or uses the following third-party
components, each under its own license.

## Bundled in this repository and in the release files

| Component | Where | License | Notes |
|---|---|---|---|
| **hls.js** 1.5.17 (Dailymotion and contributors) | `server/app/static/hls.min.js` | Apache-2.0 | Unmodified minified build. License text: [server/licenses/hls.js-LICENSE.txt](server/licenses/hls.js-LICENSE.txt), [Apache-2.0](server/licenses/Apache-2.0.txt) |
| **Gradle Wrapper** | `android/gradlew`, `android/gradle/wrapper/` | Apache-2.0 | Downloads Gradle 8.7 at build time |
| **TMDB logo** | `server/app/static/tmdb-logo.svg` | TMDB brand assets | Used only for the attribution TMDB requires. Use is governed by the [TMDB API terms](https://www.themoviedb.org/api-terms-of-use) and logo guidelines. Not covered by the AGPL. |
| **Movinite logo and icons** | `server/app/static/logo-*.png`, `icon-*.png`, `favicon*`, `android/app/src/main/res/**/ic_launcher*`, `logo*.png` | See below | Project branding |

**Branding:** the Movinite name and logo identify this project. *(Maintainer to confirm: the logo's ownership and
redistribution rights, and whether it falls under the AGPL like the code or under a separate trademark/branding
policy.)*

**Fonts:** no font files are bundled. The web UI uses the device's system fonts (`system-ui`, `ui-monospace`), and the
Android app uses the platform default font.

## Python packages (installed by `install.sh` from PyPI, not bundled)

The versions below were checked with a clean `pip install -r server/requirements.txt` (unpinned sub-dependencies may change).

| Package | License |
|---|---|
| fastapi 0.115.6 | MIT |
| starlette | BSD-3-Clause |
| pydantic, pydantic-core | MIT |
| annotated-types | MIT |
| typing-extensions | PSF-2.0 |
| anyio | MIT |
| typing-inspection | MIT |
| idna | BSD-3-Clause |
| uvicorn[standard] 0.34.0 | BSD-3-Clause |
| click | BSD-3-Clause |
| h11 | MIT |
| httptools | MIT |
| uvloop | MIT or Apache-2.0 |
| watchfiles | MIT |
| websockets | BSD-3-Clause |
| python-dotenv | BSD-3-Clause |
| PyYAML | MIT |

## System packages (installed from Ubuntu's repositories, not bundled)

| Package | License |
|---|---|
| **FFmpeg / ffprobe** (Ubuntu build) | LGPL-2.1+ and GPL-2.0+ (Ubuntu's build enables GPL parts such as libx264/libx265) |
| Python 3 | PSF-2.0 |
| cifs-utils, nfs-common, smbclient (Samba) | GPL-2.0+/GPL-3.0+ |
| intel-media-va-driver(-non-free), libvpl2, libmfx-gen1.2, vainfo, mesa-va-drivers | MIT / BSD-style |

Movinite calls ffmpeg as a separate program. It doesn't link to it or redistribute it.

## Online services

- **The Movie Database (TMDB):** optional metadata and images, using your own API key.
  *This product uses the TMDB API but is not endorsed or certified by TMDB.*
