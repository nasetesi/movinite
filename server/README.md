# Movinite

*(internally still `media-server`: service, folder, tarball and API names are unchanged)*

A self-hosted media server (a simplified Plex / Jellyfin) for an Ubuntu Server VM.
Add folders or network shares (SMB / NFS) as libraries, it scans them, shows posters and
thumbnails in a web UI, and plays everything in the browser -- direct play when the browser
can, a remux (video copied as-is) when only the container or audio is the problem, and live ffmpeg
transcoding (HLS) for the rest. With a free TMDB key it also downloads posters, backdrops,
descriptions and episode titles.

- **Stack:** Python 3 + FastAPI + uvicorn, SQLite, ffmpeg/ffprobe, plain HTML/JS UI (hls.js bundled, no CDN)
- **Default port:** `8099`  ->  `http://<server-ip>:8099`
- **Service:** systemd unit `media-server`, runs as the locked-down user `media-server`

## Install (fresh Ubuntu 22.04 / 24.04 server)

```bash
sudo mkdir -p /opt
sudo tar -xzf media-server-ver1.0.tar.gz -C /opt
cd /opt/media-server
sudo bash install.sh                 # or: sudo bash install.sh --port 8096
```

Shortcut: copy `install.sh` and the tarball into the same folder on the server and run `sudo bash install.sh`
there -- it extracts the newest `media-server-ver*.tar.gz` into `/opt/media-server` and carries on.

The installer apt-installs python3/venv, ffmpeg, cifs-utils, nfs-common; creates the service user,
the virtualenv, the database, the systemd service; and prints the URL plus a **random admin password**
(also saved in `/opt/media-server/ADMIN_PASSWORD`, root-only). Sign in as `admin` with it; you will be
asked to choose your own password. Then delete the file: `sudo rm /opt/media-server/ADMIN_PASSWORD`.

Safe to re-run at any time (it never overwrites `.env`, the database or an existing admin).

## Update

Copy the new tarball to the server, then:

```bash
cd /opt/media-server
sudo bash update.sh /path/to/media-server-ver1.1.tar.gz
# or just  sudo bash update.sh   -> uses the newest media-server-ver*.tar.gz in the current dir or /opt
```

update.sh backs up the code, `.env` and the database to `backups/`, mirrors in the new code, updates
Python packages, upgrades the database, restarts and checks the new version is serving. If anything
fails it puts the previous version back automatically. Undo an update:

```bash
sudo bash update.sh --rollback backups/media-server-pre-1.1-YYYYMMDD-HHMMSS.tgz
```

## Adding media

Settings -> Libraries -> **Add library**, pick a type (Movies, TV shows, Music, Other videos) and a source:

| Source | What to enter | Notes |
|---|---|---|
| Folder on this server | `/mnt/media/movies` (browse button) | Local disk or a share you mounted yourself in `/etc/fstab`. The `media-server` user must be able to read it. |
| SMB / Windows share | `//192.0.2.10/Media`, optional sub-folder, username / password / domain, SMB version | Mounted **read-only** at `/srv/media-server/shares/<id>` with a systemd mount unit, so it is back after a reboot. Leave username empty for guest. |
| NFS share | `192.0.2.10:/volume1/media`, optional sub-folder | Mounted read-only at `/srv/media-server/shares/<id>`. The NFS server must allow the VM's IP. |

SMB passwords are stored in `/etc/media-server/credentials/share-<id>.cred` (root:root, mode 600), never
in the database or in the unit file. The web service runs unprivileged; the only root action it can take is
`/usr/local/sbin/media-server-mount` (allowed by `/etc/sudoers.d/media-server`), which validates its input
and only manages units for `/srv/media-server/shares/<id>`.

Libraries are rescanned every 6 hours by default (changeable per library) and on demand with **Scan**.
**Full rescan** re-probes every file and regenerates thumbnails.

### Folder naming that scans best

```
Movies/Inception (2010)/Inception (2010).mkv        poster.jpg / folder.jpg next to it is used as the poster
Movies/The.Matrix.1999.1080p.BluRay.x264.mkv
TV/Breaking Bad/Season 01/Breaking.Bad.S01E01.Pilot.mkv     (also 1x01, "Season 1 Episode 1")
TV/Breaking Bad/poster.jpg                                  show poster
Music/Artist/Album/01 - Track.flac                          embedded tags + cover art win; cover.jpg / folder.jpg used too
Movie.en.srt next to Movie.mkv                              external subtitles
```

## Movie & TV info from TMDB (optional)

Without a key everything works from file and folder names. With a key, movies and TV shows get posters,
backdrops, descriptions, genres, ratings, episode titles and episode stills from
[The Movie Database (TMDB)](https://www.themoviedb.org/).

1. Create a free account at themoviedb.org, then open **Settings -> API** (https://www.themoviedb.org/settings/api)
   and request an API key (choose "Developer", personal use).
2. Copy either the **API Key** (v3, 32 characters) or the **API Read Access Token** (v4, the long `eyJ...` one).
   Either works.
3. In Media Server: **Settings -> Metadata**, paste it, **Test key**, **Save**. Matching starts right away
   and then runs after every scan.

Or put it in the config file instead (handy for scripted installs):

```bash
sudo nano /opt/media-server/.env        # add:  MS_TMDB_KEY=your_key_or_token
                                        # optional: MS_TMDB_LANGUAGE=de-DE
sudo systemctl restart media-server
```

A key saved in the UI wins over the one in `.env`. The key stays on the server (the UI only shows
`abcd...wxyz`).

- **Matching** uses the cleaned file/folder name and year (`Movie Name (2019).mkv`, `Show Name/Season 01/...`).
  Wrong match? Open the movie or show and click **Fix match**: search TMDB and pick the right title,
  **Use file name** to switch TMDB off for that title, or **Automatic** to try again. Your choice is kept on
  later scans.
- Titles that found no match are retried after 7 days (or with **Refresh metadata** in Settings -> Metadata).
- A local `poster.jpg` / `folder.jpg` next to the file always wins over the TMDB poster.
- Images are cached in `/opt/media-server/data/thumbs/`, details in the database -- nothing is fetched
  while you browse. If TMDB is down or the key stops working, the cached info keeps showing.
- Requests are throttled (20/s, `MS_TMDB_MAX_RPS`, 4 lookups in flight `MS_TMDB_WORKERS`) and TMDB's `429 Retry-After` is honoured.
- Matching that was interrupted (restart/update) or never started resumes on its own at startup and every 5 minutes.
  Settings -> Metadata shows how many titles are still waiting and has **Match missing** (only what is missing)
  next to **Refresh metadata** (re-download everything).
- Library grids sort **Posters first** by default (titles with a TMDB poster or local poster.jpg, then the rest);
  titles move up live as posters arrive. Other sorts: Title, Recently added, Year.
- **Editions** (Director's Cut, Unrated, Extended, Remastered, IMAX...) in a file name are stripped before
  searching and shown as a label instead.
- **Needs review** (movie libraries, filter next to the sort menu): matches the matcher was not sure about --
  low confidence, a TMDB year more than a year away from the file name, or nothing safe to apply but a film
  with the same title from another year. The movie page explains why and offers **Accept** (switch to the
  suggestion), **Looks right**, or **Fix match**. "No TMDB match" and "Special editions" filters are there too.
- This product uses the TMDB API but is not endorsed or certified by TMDB.

## Home rows (v1.4.1)

Home shows, in this order: **Continue watching** (only when you have part-watched movies; click to resume),
**Recommended for you**, **Recently released**, **Recently added**, **Top movies**, then a row per top genre.
"See all" opens the full list; the same lists are tabs on the Movies page.
Since 1.5.5, Continue watching and the Recently added rows come only from **Movies** and **TV Shows** libraries
(music, home videos and other libraries are left out; open them from Libraries).

| Row | How movies get there |
|---|---|
| Recommended | Per user. Movies similar to what you watched (TMDB recommendations, shared genres / collections, recent watches count more) and the next film of a franchise after you finish one. Watched and started movies are skipped. No history yet: highly rated, well-known films across your top genres. Changes when you watch something or once a day. |
| Recently released | TMDB release date, newest first, last 2 years, no future dates. |
| Recently added | Date the file was added to the library. |
| Top movies | Weighted TMDB score: (v/(v+500))·R + (500/(v+500))·C, where R = score, v = votes, C = library average; at least 50 votes. |

Admins can pin a movie to Recommended / Top movies or keep it out: movie page -> **Home rows**.

## Movie details page (v1.4.3 - v1.4.6)

Clicking a movie anywhere opens its details page: description, **Cast** (top-billed actors with photos; click
one to see their other movies in your library), **Similar movies** from your library (TMDB recommendations,
then the same collection, then shared genres), file details (collapsed) and, for admins, Fix match / Home rows /
tags. To play straight from a grid, hover a poster and click the round play button. (v1.4.3 had the file details and admin
buttons at the bottom of the page; since v1.4.5 they are in the ... menu.) Cast comes from TMDB with
the other movie details; actor photos are downloaded the first time they are shown and cached in `data/thumbs`.
From v1.4.4 the page has a large poster and the movie's artwork, blurred, as the page background.
From v1.4.5 file details and admin tools are in the **...** button next to Play: Fix match, Home rows, + Tag,
Artwork settings (admins), Download file, TMDB and File info (everyone). Similar movies use bigger posters.
From v1.4.6 the poster is up to 550 px wide (TMDB's 780 px poster, downloaded on first view and cached), the
description is 19 px, cast photos are 186 px wide (632 px-tall images) and Similar posters up to 330 px.

## Rows: < and > buttons (v1.4.4), big posters and hover (v1.4.7)

Horizontal rows (Home, Cast, Similar movies) have no scrollbar; use the round < and > buttons in the middle
of the row (one screen-width per click), Tab + Enter, or the Left/Right arrow keys. On phones and tablets swipe
the row or tap the buttons (shown on touch screens too since v1.4.9). From v1.5.1 the buttons are hidden on phones
narrower than 600 px (swipe the row) and small and subtle on tablets.
From v1.4.7 Home posters are up to 330 px wide, and posters everywhere pop out on mouse hover or keyboard focus
(Tab to a poster, Enter opens it). "Reduce motion" in the operating system turns the movement off.

## Offline downloads in the Android app (2.0)

Needs the **Movinite Android app 2.0** (`movinite-android-v2.0.apk`, installs over 1.x and keeps the sign-in) and server 2.0.

* **Who can download:** admins and people with the **Viewer + Downloads** role. Turn the feature on or off and set the
  limits in **Settings > Downloads** (defaults: 20 titles or 100 GB per person, 3 devices, admins unlimited).
* **In the app:** a **Download** button on detail pages. You pick a quality each time (720p suggested; 1080p, 720p and
  480p are prepared by the server on the GPU and pause while anyone is watching; **Original** only when the phone can
  play the file as it is). The **Downloads** tab (it replaces My List in the bottom tabs; My List stays on Home and in
  the account menu) shows progress, storage, quota and what is ready to watch.
* **Offline:** when the server can't be reached the app opens its offline screen after you confirm with your
  fingerprint, face or screen lock (or a 6-digit Movinite PIN; one is required if the phone has no screen lock).
  Films are stored encrypted inside the app and play only in its own player. Progress is sent back at the next sync.
* **Licences:** each download has a 30-day licence signed by the server key and tied to that phone. It renews whenever
  the app syncs. A download is deleted at the next sync if it is removed from the server, the person loses the role or
  the library, or the device is removed (**Settings > Downloads**, or **My account > Devices & downloads**). After 30
  days without a sync, or on sign-out, the app removes every download.
* **Honest limits:** this is trust-based protection for family and friends, not studio-grade DRM. A determined person
  with a rooted phone could copy a film; screenshots and screen recording of the player are blocked.
* Prepared versions are cached in `data/offline` (200 GB by default, oldest removed first). `update.sh` saves
  `data/media-server.db.pre-schema11` before the schema 11 upgrade.

## Android TV remote (1.9.1, 1.9.2)

The web app (including the Android 1.5 WebView on a television) can be driven with a D-pad: arrow keys move a large purple focus ring across the sidebar, rows, posters and player controls; OK or Enter opens the focused item; Back closes the player or goes back. Televisions are detected automatically. On a browser you can turn it on with `localStorage.msTvMode = 1` and reload (set it to `0` to turn it off).

From 1.9.2, opening a movie or show focuses Resume or Play (not the Similar movies row). Up and down stay inside the details: buttons, then cast or episodes, then Similar movies. The page is laid out at 1920×1080 and scaled to the WebView's CSS size, so a 4K television does not look zoomed in. The wide banner on the Android TV home screen comes from the app (2.0), not this server release.

From 2.0.1, while a film is playing the remote shows the player controls and can reach every button, including the settings gear at the bottom right (quality, picture and speed). Up and down move between the seek bar and the button row; Left and Right walk the row you are on. The settings menu itself is navigable, and Back hides the controls before leaving the player.

## Easier TV sign-in (2.0.2)
Typing a server address and a password with the TV remote is awkward. From 2.0.2 the television shows a short code and a QR code. On a phone that's already signed in, scan the code or open `https://192.0.2.10/pair?code=XXXXXX` and tap Approve. The TV signs in as that person and stays signed in (the session refreshes while you use it). You can still use a username and password, and you can sign out from the menu.

The sign-in screen lists Movinite servers you've used before, and the server advertises itself on the LAN (`_movinite._tcp`) so a future Android app build can offer a picker instead of typing the address. The installed 2.0 Android app still uses its native setup and password screens until a 2.0.2 app is sideloaded; stay-signed-in already works with this server release.

On a television, Up from the first row reaches the header. Left and Right move across search, sounds and the account button; OK opens the account menu (including Sign out). Settings > My account also has a Sign out button.


## Television home (2.1)

**2.1.1:** a signed-out television shows only the phone-code (or password) sign-in screen, not the home chrome. Sign-in codes are reused until they expire (10 new codes per address per 10 minutes). The top bar uses the same dark color as the side menu.

**2.1.3:** the TV waits about 3 seconds between approval checks, backs off instead of showing “Too many checks,” and stops checking when you open the password form. The check limit is per code and address, and is large enough for a 10-minute code. **2.1.2:** the web header (search, poster sounds, server status, account button) is hidden on a television. Desktop and phone keep it. Search, Sign out and Settings stay in the slide-out menu. The TV tab bar is transparent over the backdrop. Moving the remote onto a tab or a menu item opens that view after a short pause (Sign out still needs OK). Opening a title focuses Resume or Play with the page scrolled to the top.

On a TV, Movinite uses a Plex-style home: a large backdrop of the focused title, details and a short synopsis, a slim icon rail on the left that slides out into a full menu, tabs across the top, and rows of posters underneath. The menu lists your libraries as *Movies / NAS* (or the share's real name), and shared libraries from another server as *Movies / Harbor*. Desktop and phone layouts are unchanged. The 2.0.2 Android TV app works as-is; the layout comes from the server.

Remote: Left from the rows or from the tabs opens the menu; Up from the tabs stays on the tabs; Up/Down move in the menu; OK selects; Right or Back closes it. Up from the first row reaches the tabs. Sign out is on the profile row in the slide-out menu.

## Sharing libraries between servers (2.1)

Two Movinite servers can share libraries with no central service.

1. On the owner, open **Settings > Sharing**, set a short server name if you want, tick the libraries, and press **Share libraries**. You get a one-time link and a code (for example `7K3Q-M9PX-2TQA`), valid 48 hours.
2. On the other server, **Settings > Sharing > Add a shared library**, paste the link (or the address plus the code), check the fingerprint, and accept.
3. The shared libraries show up in that server's library list, search, home and the TV menu, labelled with the owner's name.

The servers then trust each other with signed requests using each server's Ed25519 identity. Public addresses must be HTTPS, for example `https://media.example.com`. A LAN address an admin types may use plain HTTP, for example `http://192.0.2.10:8099`.

The first start of 2.1 copies the database to `data/media-server.db.pre-schema12` (mode 600) before applying schema 12.


## Phones and admin-only tools (v1.4.9)

Settings work on phones: there is one swipeable line of tabs, each panel is a single column, tables become cards
and every control is at least 44 px. From v1.4.10 values with several parts (a share, its badge and folder) stack under their label, and paths wrap only after "/". The ⋯ menu on a movie page (Fix match, Home rows, tags, Download, File info)
is only shown to admins, and the server refuses downloads from other users. Streaming is not affected.

## Poster Sounds (v1.4.8, own tab since 1.5.5)

Quiet sounds made in the browser, with no audio files:
- a soft tick when you hover over a poster or Tab to it;
- a whoosh and chime when you open a movie;
- a rising tone for Play / Resume;
- a swish for the < > buttons.

They are on by default at 30% volume and never play while a video is open. The speaker button in the top bar
mutes or unmutes them. **Settings > Poster Sounds** (its own tab since 1.5.5; before that it was under My account) has an on/off switch, separate Hover and Select
switches, a volume slider and a Test button. Settings are saved for each user in each browser. Sound starts
after your first click or key press, as browsers require. Phones get no hover sounds, and tap sounds are off by default.

## Server status (v1.4.2)

The top-right corner shows live CPU % and RAM used/total; hover or click it for per-core CPU, load average,
memory/swap, free disk space (data folder and mounted shares), uptime, active streams / ffmpeg processes and
the app's own memory. It turns amber at 60% CPU / 75% RAM and red at 85% / 90%. Only admins see it unless
**Settings > System > Show server status to all users** is on. The numbers come from `/proc`
(`GET /api/system/status`, cached ~2 s).

## Browsing movies by category (v1.4)

Movie libraries have a **Movies / Collections** switch and a category bar under the toolbar:

- **Genres** -- click chips to filter (several = movies with all of them); numbers are counts within what you
  picked. **Decade**, **age rating** and **tag** menus next to them; **Clear** resets.
- Works together with the search box, the sort menu (Posters first / Title / Recently added / Year /
  TMDB score) and the Needs review / No TMDB match / Special editions menu.
- **Collections** -- TMDB collections/franchises you own; click one to see its movies in release order.
- **Home** shows a row per top genre; genre chips on a movie page open the library filtered by that genre.
- **Tags** (admins) -- "+ Tag" on a movie page, or **Select** on the Movies page, pick movies, type a tag
  (e.g. Kids) and **Add tag** / **Remove tag**.

Categories come from TMDB. After updating from 1.3.x, genres appear immediately (from the cached data) and
collections / age ratings are fetched in the background -- one request per movie, about 2-4 minutes for 2,000
movies; the top-bar pill shows "Fetching categories". Movies without a TMDB match have no categories (tags
still work).

## Saving artwork into the movie folders (optional, v1.3)

Off by default. When on, Media Server writes the TMDB poster (optionally the backdrop as fanart and a
Kodi / Jellyfin / Plex-compatible `.nfo`) next to each matched movie, so other players -- and a re-install --
find them.

| Movie sits... | Files written |
|---|---|
| alone in its own folder (`Movies/Heat (1995)/Heat (1995).mkv`, cd1/cd2 or several versions of the same movie are fine) | `poster.jpg`, `fanart.jpg`, `movie.nfo` |
| in a folder with other movies, or directly in the library folder | `<file name>-poster.jpg`, `<file name>-fanart.jpg`, `<file name>.nfo` |

- Nothing that already exists is replaced (any `poster.jpg` / `folder.jpg` / `cover.jpg` / `<name>-poster.jpg`
  counts as an existing poster) unless you tick **Overwrite**; even then only the names above are
  rewritten, in place, so the file keeps its owner and permissions. New files are `0644`.
- Video files are never touched, renamed or moved.

**Turning it on for a library on a network share:**

1. **Settings -> Libraries -> Artwork** on the movie library.
2. Tick **Allow writing (artwork only)** for the share and confirm. The share is remounted read-write (all
   other shares stay read-only). The SMB/NFS user must also be allowed to write on the NAS -- if it is not,
   you get "The server refused to write in ... (permission denied)" right away and nothing is written.
3. Tick **Save artwork** (and fanart / .nfo if you want them), **Save settings**.
4. **Preview (dry run)** -- lists every file that would be created, overwritten or skipped, writes nothing.
5. **Write artwork for all matched items now** -- runs in the background; progress shows in the top pill and
   under Settings -> Scan activity (with Stop). From then on, newly matched movies get their artwork automatically.

To go back: untick **Save artwork**, then untick **Allow writing** (the share is remounted read-only;
files already written stay). Local folders (not shares) only need the `media-server` user to have write
permission there.

## Playback

- **Direct play** (no CPU) for MP4/MOV/WebM/MKV with H.264 (8-bit) / VP9 / AV1 video and AAC / MP3 / Opus /
  FLAC audio. MKV and HEVC are tried directly and fall back to transcoding automatically if the browser can't.
- **Remux** (new in 1.1) for MKV/MP4/MOV with 8-bit H.264 video when the container or the audio is what the
  browser can't play (typically MKV with AC3/DTS/TrueHD audio, or a second audio track): the video is copied
  untouched into HLS and only the audio is converted to AAC stereo. Almost no CPU, original picture quality,
  and seeking still works (segments are cut on the file's own keyframes). Shown as "Original (remux, no
  re-encode)" in the quality menu; if a remux fails the player falls back to transcoding by itself.
  `.ts`/`.m2ts`/AVI files and HEVC/10-bit video still transcode.
- **Transcoding** for everything else (AVI, HEVC on most browsers, 10-bit H.264, HDR): ffmpeg -> H.264/AAC HLS in 6-second segments, 1080p / 720p / 480p / 360p. Seeking anywhere works
  (ffmpeg restarts at the requested segment). ffmpeg is paused when it is far ahead of the player and
  killed 90 s after the player stops.
- Resume position per user, "Continue watching", next-episode autoplay, subtitle selection (external
  .srt/.vtt/.ass and embedded text subtitles), audio track selection, music player bar with album queue.
- On-screen controls (v1.4.11): tap the picture for big see-through ↺10 / Play-Pause / ↻10 buttons and a translucent
  CPU/RAM status pill; they fade after ~3 s. Double-tap the left/right side to skip 10 s. The full-screen button
  keeps the buttons and status visible (also in the Android app).
- From v1.4.12 the top bar (close, title, quality / audio / subtitles) fades with them and the mouse pointer hides.
  Picture in picture: the PiP button or P pops the film into a small window while you keep browsing (Chrome, Edge,
  Safari, Chrome on Android, and the Android app v1.3+). Firefox users use Firefox's own PiP (Ctrl+Shift+]).
- From v1.4.13 the player has its own see-through bottom bar instead of the browser's controls: seek bar (buffered
  range, hover time), time, play/pause, -/+10 s, volume, then **Quality** (with playback speed), **Subtitles**,
  **Audio** (only when a film has several tracks), **PiP** and **Full screen** as separate buttons. The top bar keeps
  only close and the title. Menus open above their button (as a bottom sheet on phones); subtitles move up while the
  bar shows.
- Keyboard in the player: space/k = pause, arrows or j/l = -/+ 10 s, f = fullscreen, p = picture in picture,
  m = mute, Esc = close an open menu, else close the player.

## Scan progress

While a library scans, a pill at the top of every page shows what is happening, e.g.
**Scanning Movies -- 312 / 2,021 · ETA 41 min · current file**. Click it for **Settings -> Scan activity**:

- per library: phase (discovering files / processing / done / cancelled / error), files found, new or changed,
  unchanged (skipped), processed, added, updated, removed, errors, files per minute, ETA, the files being
  worked on right now, the last error and the recent log lines;
- **Cancel scan** -- stops after the files in progress; everything found so far stays, nothing is removed.
  The next scan carries on where it stopped (already-scanned files are skipped).

Movies appear in the library and in "Recently added" while the scan runs (the page updates itself every
few seconds and keeps your scroll position), and posters fill in as TMDB matches them -- shown as a
separate **Fetching posters** step. A message pops up when a scan finishes with the added / updated /
removed counts.

How a scan works: one thread walks the folders and hands each new or changed file to a small pool of
workers (`MS_SCAN_WORKERS` in `.env`, default: half the CPU cores, 2-4) that run ffprobe and grab one
keyframe for the thumbnail; results are saved in small batches. Unchanged files (same size and date) are
skipped without opening them. Files ffprobe can't read are added anyway (counted under errors) and are not
retried until they change or you run a **Full rescan**. Rough speed: a few seconds per file for big 4K
files over SMB on the first scan, a couple of seconds for the whole library on later scans.

If some folders can't be read during a scan (share hiccup), nothing is removed from the library that time.

## Automatic scans

Each library has an **Automatic scan** setting: Off, Hourly, Every 6 hours (default) or Daily
(Settings -> Libraries -> Edit, or when adding a library). It runs inside the service -- no cron job.
The libraries table shows when the next scan is due. A scan only reads new or changed files, so an
hourly scan of a big share is cheap. **Scan** / **Full rescan** still work any time.

## HTTPS / access from outside (reverse proxy)

Media Server speaks plain HTTP on port 8099. For HTTPS put Caddy or nginx in front of it. Notes that apply
to both:

- **Video** is either one big file with HTTP Range requests (direct play) or HLS: a playlist plus many small
  `.ts` segments. The first segment of a transcode can take a few seconds, so use **long read timeouts**
  (5 min) and **turn off response buffering**, or the proxy will hold segments back.
- **No WebSockets** are used -- nothing special is needed for them. (If you reuse a config that upgrades
  connections, it does no harm.)
- Pass **`X-Forwarded-Proto`** so the sign-in cookie is marked `Secure` over HTTPS.
- **1.9:** tell Movinite which proxy to trust so it sees the real visitor address (sign-in lockouts, Activity and
  the device list use it): **Settings > System > Trusted proxies** (for example `192.0.2.10`), or
  `MS_TRUSTED_PROXIES=192.0.2.10` in `.env`. The proxy should send `X-Real-IP` / `X-Forwarded-For`; behind
  Cloudflare, `CF-Connecting-IP` is used. Requests from 127.0.0.1 are always trusted.
- Uploads are not used, so `client_max_body_size` doesn't matter.
- Once the proxy works, you can stop the direct port from being reachable from other machines:

  ```bash
  sudo systemctl edit media-server
  # add these three lines, save:
  [Service]
  ExecStart=
  ExecStart=/opt/media-server/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8099 --no-access-log --timeout-graceful-shutdown 5
  # then
  sudo systemctl restart media-server
  ```

  (Skip that if the proxy runs on a different machine -- use a firewall rule instead, e.g.
  `sudo ufw allow from <proxy-ip> to any port 8099`.)

### Caddy (automatic Let's Encrypt certificates)

```bash
sudo apt install -y caddy
sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
media.example.com {
    encode gzip
    reverse_proxy 127.0.0.1:8099 {
        flush_interval -1          # stream segments as they come, no buffering
        transport http {
            read_timeout 300s
        }
    }
}
EOF
sudo systemctl reload caddy
```

Caddy sets `X-Forwarded-Proto` by itself. Ports 80 and 443 must reach the VM for the certificate.
For a LAN-only name use `tls internal` inside the site block (self-signed by Caddy's local CA).

### nginx

```nginx
# /etc/nginx/sites-available/media-server   (then: ln -s ../sites-available/media-server /etc/nginx/sites-enabled/)
server {
    listen 80;
    server_name media.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;                       # Ubuntu 22.04/24.04 nginx; on nginx >= 1.25.1 you may write "listen 443 ssl;" + "http2 on;"
    server_name media.example.com;

    ssl_certificate     /etc/letsencrypt/live/media.example.com/fullchain.pem;   # e.g. from: certbot --nginx
    ssl_certificate_key /etc/letsencrypt/live/media.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8099;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_buffering off;                    # HLS segments + range requests go straight through
        proxy_request_buffering off;
        proxy_read_timeout 300s;                # first transcode segment can take a while
        proxy_send_timeout 300s;
        proxy_max_temp_file_size 0;
    }
}
```

`sudo nginx -t && sudo systemctl reload nginx`. Get a certificate with `sudo apt install certbot
python3-certbot-nginx && sudo certbot --nginx -d media.example.com`.

## Where things live

| Path | What |
|---|---|
| `/opt/media-server/` | code, `.venv`, scripts |
| `/opt/media-server/.env` | settings (port is on the systemd unit; transcode preset, max transcodes, `MS_TMDB_KEY`, `MS_SCAN_WORKERS`...) |
| `/opt/media-server/data/media-server.db` | SQLite: users, libraries, items, watch progress |
| `/opt/media-server/data/secrets/` | 1.9: server identity key and encrypted Gmail sign-ins (owner-only; included in update.sh backups) |
| `/opt/media-server/data/thumbs/` | generated thumbnails + cached TMDB posters, backdrops, stills |
| `/opt/media-server/data/transcode/` | temporary HLS segments (wiped automatically) |
| `/opt/media-server/backups/` | backups made by update.sh (newest 10) |
| `/srv/media-server/shares/<id>` | mount points of shares added in the UI |
| `/etc/media-server/` | mount helper config + SMB credentials (root-only) |
| `/etc/systemd/system/media-server.service` | the service |

## Building a new release (developers)

The source lives in `src/` of the project folder. Bump `app/version.py` (and CHANGELOG.md), then run
`bash src/pack.sh /path/to/output` -> `media-server-verX.Y.tar.gz` + `.sha256`.

## Handy commands

```bash
sudo bash /opt/media-server/status.sh          # service, version, URL, shares
sudo systemctl restart media-server
journalctl -u media-server -e                  # logs
sudo bash /opt/media-server/reset-admin.sh     # new random password for admin (prints it)
```

To let the service read a folder you mounted yourself (e.g. owned by another user), add the
`media-server` user to that folder's group, e.g. `sudo usermod -aG mediagroup media-server && sudo systemctl restart media-server`.

## Known limitations (v1.4.12)

- Sound settings are kept in the browser (per user), so they don't follow you to another device.

- The blurred background uses CSS blur; on very old browsers without `filter` support it shows sharp but darkened.
- Recommendations use your own library and TMDB's lists only; ratings/likes are not collected yet.

- Categories are for movie libraries; TV shows show their genres but have no genre filter or collections yet.

- Artwork saving is for movies and TV shows (not music) and the .nfo has no cast/crew.
- Online metadata is TMDB for movies and TV only. Music comes from file tags and embedded/folder art
  (no MusicBrainz). Cast/crew are not downloaded.
- Remux needs 8-bit H.264 in MKV/MP4/MOV; other files still transcode.
- Hardware transcoding (1.5.2): no HDR -> SDR tone-mapping on the GPU (HDR films look washed out, as on the CPU path);
  Intel QSV needs `libmfx-gen1.2` (VAAPI does not); NVENC is implemented but untested on real NVIDIA hardware.
  Expect about 1-2 cores per 1080p stream with the default `veryfast` preset.
- HDR sources are transcoded without tone-mapping (colours look washed out); image subtitles (PGS/VobSub)
  are not shown.
- One transcode per user at a time (starting another stream replaces the first).
- Built-in HTTP only; for HTTPS use a reverse proxy (see above).


## Movinite 1.5: name, logo, theme

- The app is called **Movinite**. Logo files: `app/static/logo-full.png` (sign-in page), `logo-bar.png` (menu),
  `logo-mark.png` (phone top bar), `favicon.ico` / `favicon-16|32|48.png`, `apple-touch-icon.png`,
  `icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, `manifest.webmanifest` (add to home screen).
- Theme colours are CSS variables at the top of `style.css`: `--acc` #9637FA (from the logo), `--acc-fill` #8424EA
  (buttons, white text), `--acc-fill-h` #6A16C4 (hover), `--acc-text` #B07CFF (purple text on dark), `--warn` amber.

## Browsing a share when adding a library (1.5)

Settings -> Libraries -> Add library -> SMB: type `//server` (or `//server/share`), the username and password, then
**Browse**. Pick the share, click through to the media folder, **Select this folder**. NFS: `server:/export` +
Browse. Local folder: Browse from `/`. Edit library -> Browse changes the folder inside the existing share and
rescans. SMB uses `smbclient` (installed by install.sh / update.sh); NFS uses a temporary read-only mount
(`media-server-mount browse`, removed right after).

## Rotate to full screen (1.5)

On a phone or tablet, turning the device sideways while a film plays goes full screen; upright leaves it. Leaving
full screen with the button while sideways is respected until the next turn. The Android app (1.4+) follows the
phone's rotation while the player is open and hides the system bars sideways.

## Phone layout (1.5.1)

On phones and small tablets (up to 820 px wide, in the browser and in the Android app) the menu button is replaced
by a **tab bar at the bottom**: Home, Libraries (every library with its categories and collections), Search,
My List (films you are watching and the ones you watched last, from `GET /api/mylist`) and Settings (Account for
non-admin users). The active tab is purple. The tab bar hides while the player is open and comes back when the film
is minimised (PiP) or closed.

The top bar shows the M logo, a search icon (opens the Search tab), the server-status dot (tap it for CPU / RAM)
and a round **avatar** with your initial. Tap the avatar for My account, Settings, Poster sounds on/off and
Sign out. Home rows have bold titles with a ">" that opens the full list, the library name under them, about
2.3 posters across, 8 px rounded corners, title + year under each poster, a thin progress bar and a check on
watched films. Desktop and wide tablets look exactly as before.

The Android app 1.5 signs in on a screen that looks like the web sign-in page: the full Movinite logo, the purple
glow, the same card, fields and button.

## Hardware transcoding (1.5.2)

Settings -> **Transcoding** (admins). A video card converts the videos that cannot be played directly, using far
less CPU (on the Intel Arc A310: ~2 s of CPU per 30 s of 4K video instead of ~70 s).

- **Hardware transcoding:** Auto (default: VAAPI, then Intel QSV, then NVIDIA NVENC -- the first that passes a test),
  Intel QSV, VAAPI, NVIDIA NVENC or Off (CPU). **Video card:** which render node to use (/dev/dri/renderD128 ...).
- **Test** runs a 2-second 1080p -> 720p encode with that method and shows passed + fps, or the ffmpeg error and the
  fix (e.g. QSV on Arc: `sudo apt install libmfx-gen1.2`). **Scan for video cards again** after adding a card.
- If the card fails on a video, that stream continues on the CPU by itself (GPU decode -> CPU decode + GPU encode
  -> CPU), the log says why, and the page shows the last fallback. A method that failed completely is paused for
  10 minutes (Save or a passing Test turns it back on).
- While a stream runs on the card the status pill shows a purple GPU badge (a purple ring around the dot on phones).
- **install.sh** finds the card, installs its drivers (Intel: intel-media-va-driver-non-free, vainfo, libvpl2,
  libmfx-gen1.2; AMD: mesa-va-drivers), adds the service user to the video/render groups, tests and saves the result.
  **update.sh** only does this when nothing is saved yet, so your choice is kept. A server updated from 1.5.1 or
  older is scanned on the first start of 1.5.2.
- Check by hand: `vainfo --display drm --device /dev/dri/renderD128` (lists VAEntrypointEncSlice*), and
  `journalctl -u media-server | grep -i hardware`.
- NVIDIA needs the proprietary driver (`sudo ubuntu-drivers install`, then reboot); the service user needs no group.

## Phone library pages (1.5.3)

On phones (<= 820 px, browser and app) a library page has a compact header:
- the title and count, then search, a filter funnel (its badge shows how many filters are on) and sort, plus a ⋯
  menu for admins (Select movies to tag, Scan library)
- the categories in one swipe row
- the filters in a bottom sheet with Apply / Reset (genres, decade, rating, tag, show; sort; view for music)
- removable chips for the active filters, and a 3-column grid

The Back button or a drag down closes the sheet. Desktop layout is unchanged.

## 2K and 4K (1.5.3)

With hardware transcoding on (Settings -> Transcoding), the quality menu in the player offers **4K (2160p)** and
**2K (1440p)** for films at least that big. It never upscales; scope films keep their shape. Without a video card
the entries are greyed out. The player uses HEVC (fMP4 HLS) when the device supports `hvc1`, else H.264, and steps
down by itself if HEVC fails.

| Quality | H.264 | HEVC |
|---|---|---|
| 4K 3840x2160 | 25 Mbps | 16 Mbps |
| 2K 2560x1440 | 12 Mbps | 8 Mbps |

These are peak rates. HEVC output, and H.264 from an H.264 source, are capped at 1.2x the source bitrate (at least
6 Mbps). **1.5.4:** H.264 from an HEVC / AV1 / VP9 source averages 1.8x the source (at least 12 Mbps for 4K and
8 Mbps for 2K, peak 1.25x the average, never above the table), because H.264 needs more bits for the same picture.
HDR films are sent without tone-mapping (colours may look flat; the player says so).

The player's status pill shows **Dropped N / total** video frames while the controls are up (1.5.4). A high count
means the device or its display can't keep up. Films are 24 fps, so a 30 Hz display judders; 60, 72 or 24 Hz is
better.

**How many at once (Intel Arc A310, a short preliminary run on 2026-11-24 with HEVC 10-bit 4K films on the full GPU path; the full benchmark is still to come):**

| Output | H.264: max streams >= 1.1x | HEVC: max streams >= 1.1x | Speed with 1 stream |
|---|---|---|---|
| 4K | 6 (1.21x each) | 6 (1.36x) | 4.3x / 4.7x |
| 2K | 10 (1.19x) | 10 (1.16x) | 8.0x / 7.7x |
| 1080p | 12 (1.16x) | 12 (1.11x) | 9.3x / 8.8x |

Each stream uses about one CPU thread. Mixes add up roughly (one 4K is about two 1080p). Direct play and remux use
no GPU. HDR10 (HEVC Main 10, PQ) decoding runs on the card too.

## Add a library from an existing connection (1.5.3)

Settings -> Libraries -> Add library. Once any share is set up, **Existing connection** is the first choice. It
lists each share (server/share, the username, which libraries use it), never the password.

1. Pick the connection and press **Browse**: the picker opens on that share, so there's nothing to log in to.
2. Pick a folder, or press **Up** to see all shares on that server and pick another one. It uses the same login.
3. **Add library.**

How it works:
- The password stays in `/etc/media-server/credentials/share-<id>.cred` (root only). The mount helper reads it
  itself (`browse-as`, `shares-as`, `add-as`), so the web app never gets it back.
- A library on the **same share** shares the existing mount. The mount is removed only when the last library on it
  is deleted.
- A library on **another share** of the server gets its own mount and its own copy of the login, so deleting one
  library never breaks another.
- Edit share (new password etc.) changes that one share for all of its libraries.
- Listing a server's shares needs `smbclient` on the server. Without it, type `//server/Share` into the Share field
  and Browse.

## TV show artwork, Poster Sounds tab, home rows (1.5.5)

**Artwork for TV shows.** The *Save artwork to folders* feature (1.3) now works for TV libraries too:
**Settings -> Libraries -> Artwork** on the TV library (all matched shows), or the **Artwork** button on a show's page
(admins; adds **Write for this show**). It writes into the show's folder (the first folder under the library):

| File | What |
|---|---|
| `poster.jpg` | TMDB show poster |
| `season01-poster.jpg`, `season-specials-poster.jpg` | TMDB season posters |
| `fanart.jpg` | backdrop (if *Fanart* is on) |
| `tvshow.nfo` | title, year, plot, genres, TMDB / IMDb ids (if *.nfo* is on) |
| `<episode file name>-thumb.jpg` | TMDB episode still, next to the episode (if *Episode thumbnails* is on) |

Same rules as movies: *Preview (dry run)* first, existing files are never replaced unless *Overwrite existing
files* is on, *Save automatically for new matches* also covers newly matched shows, and a share has to allow writing.
Episodes straight in the library root, or folders holding more than one show, get no show-level files.
A `poster.jpg` / `folder.jpg` you put in a show folder yourself is shown in the grid and on the show page and is kept
on rescans (it wins over TMDB). To go back to TMDB art, delete the file (or write again with *Overwrite* on) and rescan.

**Poster Sounds.** The interface sounds moved from My account to their own tab, **Settings -> Poster Sounds**
(viewers too). Your existing on/off, hover, select and volume settings carry over.

**Home rows.** Continue watching and Recently added list only Movies and TV Shows (web, phone and Android app).

## Shares, versions and copies (1.7)

- **Side menu:** libraries are grouped under their network share's name (status dot on the heading); local
  folders are under "This server". Settings -> Libraries: the arrows on a share's heading move the group,
  **Rename** changes the heading's name only.
- **Versions:** files of the same film in one library are one poster, highest resolution first (4K > 2K > 1080p >
  720p > SD, then bitrate, then size). The details page has a **Version** picker. The best version plays unless
  your saved quality is a smaller transcode (then the smallest version at least that size) or the server has no
  GPU 2K/4K transcoding and the browser can't play the big file directly (then a smaller version it can).
- **Copies on two shares:** home page (one section per set of mirrored libraries), Continue watching, My List and
  search show each title once, from a share that is online. Watch progress is saved on every copy and version.
  When a share is offline, the copy on the other share is used.

## Library order, settings tabs, share status (1.6)

From 1.6 versions have two parts (1.6, 1.7); a third digit means a quick fix (1.6.1). `update.sh` compares them as numbers.

**Library order.** **Settings -> Libraries** (admins): drag a row by the handle at its left, or use the up / down arrows
(the only control on touch screens). The order is the same for everyone and is used in the side menu, the phone
Libraries tab, the home page and the Android app. By default libraries are ordered by type:

| Position | Type in Add library | Internal type |
|---|---|---|
| 1 | Movies | `movies` |
| 2 | TV shows | `tv` |
| 3 | Other videos | `other` |
| 4 | Music | `music` |

A new library goes after the last library of its type, so your own arrangement stays as it is.

**Settings tabs:** Libraries, Scans, Activity, Poster Sounds, Metadata, Transcoding, Users, Email, My account, System (1.9).

**Share status.** A dot after a network-share library in the side menu (and on the phone Libraries tab) shows whether
the share answers: green online, amber slow / not answering, red offline, grey checking. Hover it for the reason and
when it was checked. Checked every 45 s; checks time out after 3 s and never remount the share.


## Users, invites, Gmail and Activity (1.9)

**Roles.** Admin (everything), **Viewer + Downloads** (watch; offline downloads arrive with the Android app 2.0) and
**Viewer** (watch). Non-admins can be limited to picked libraries; they never see the others anywhere.
Settings > Users: add or invite people, change role or libraries, reset a password, sign a person out everywhere,
turn an account off, or delete it.

**Invites.** Settings > Users > **Invite**: email, role, libraries, optional note, expiry (7 days by default). The link
works once. With email set up the invite is sent from your address with your name on it (up to 20 an hour,
100 a day); otherwise copy the link or show the QR code. The person opens the link, picks a username and password,
and is signed in. They can also sign in with their email address.

**Email.** Settings > Email: your Gmail address plus a Google **app password** (turn on 2-Step Verification, then
create one at https://myaccount.google.com/apppasswords), and the From name. Press **Send test email to myself**.
Any other SMTP provider works too. The password is stored encrypted in `data/secrets/`. Step by step:
[`docs/gmail-setup.md`](docs/gmail-setup.md). Advanced: **Connect Gmail** with Google sign-in (OAuth) instead, which
needs your own Google Cloud project; redirect URIs `https://<your public address>/api/gmail/callback` and
`http://localhost/movinite-gmail-callback` (paste mode).

**Devices.** My account lists the browsers and phones signed in to your account, with Sign out for each.

**Activity.** Settings > Activity (admins): Now playing, then a timeline of sign-ins, failed sign-ins, plays,
invites, account and settings changes, with filters and CSV export. Kept 90 days by default; IP addresses are
blanked after 30 days. My account > My activity shows your own.
