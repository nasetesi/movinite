# Changelog

## 2.6.9 -- 2026-11-27
A fix on top of 2.6.8 so a mid-watch resume can start, and so an HEVC remux can start at all. Schema stays at 15. No new client is needed.

- **Resuming a transcode no longer returns HTTP 500 on the first segment.** `playlist()` always listed a VOD from segment 0, even when `kickoff()` started ffmpeg later (for example segment 47 at 1:34). The 2.6.7 guard correctly refused to rewind that run for a stray `seg0` request, but `get_segment(0)` then returned `None` and `_hls_segment_response()` raised HTTP 500 "Transcode failed". ExoPlayer on Android TV reported `ERROR_CODE_IO_BAD_HTTP_STATUS` and dropped back to the details page, even though ffmpeg was writing segments from the playhead. The playlist now uses `#EXT-X-MEDIA-SEQUENCE` at the session's `start_seg` and lists only from that segment, including when a later playlist reload arrives with `start=0` and kickoff keeps the playhead. A still-ignored early segment request returns 404, not a fake transcode failure.
- **An HEVC remux no longer 500s on `Session.start()`.** Remux does not enable hardware (`profile == "remux"`), so `stages` started as `["cpu"]`, and the no-CPU-HEVC filter then left `[]`. Logging `self.stage` in `start()` raised `IndexError: list index out of range` from `hls_playlist` -> `kickoff` -> `start`. The filter is skipped for remux (it is stream copy, not a CPU HEVC encode), and an empty `stages` list falls back to `["cpu"]`. This was already present in 2.6.7 and was not introduced by 2.6.8.
- **Regression test:** `tests/test_v269.py` pins the mid-start playlist shape, the 404-vs-500 status for an ignored backward segment, and a non-empty `stages` list on an HEVC remux session.

## 2.4.7 -- 2026-11-27
A follow-up to the Android TV Settings screen in 2.4.6 (versionCode 15). The phone UI and the native player are unchanged.

- **Sign out and Change server stay on screen.** 2.4.6 laid the Settings page out as one tall unscrollable column with 72dp paddings and 72dp buttons. A 1080p Android TV often reports density 320, so the screen is only 540dp tall (720p at that density is 360dp) and both actions were clipped below the fold — Sign out never appeared, and neither button was in the focus tree. The actions are now pinned in a footer so they stay visible and D-pad focusable, and the user/server/version details can scroll if needed.

## 2.4.6 -- 2026-11-27
An Android TV-only app update on top of 2.4.4 (versionCode 14). The native ExoPlayer is unchanged from 2.4.4 — this is not the shelved 2.4.5 player redesign. The phone UI is unchanged. Schema is unchanged (already 15 on 2.6.8 servers).

- **The TV menu has four entries: Home, Search, Libraries and Settings.** My List, the account avatar, Activity, Downloads, Invites, Server status, Poster Sounds and the admin Settings pages are hidden on television. Libraries still opens the library list, which playback needs. The phone app is not affected.
- **Settings shows the signed-in user, the server (name and address) and the app version (version name and build), with Change server and Sign out.** Change server opens the existing server picker and keeps the session if the address is the same server, or clears it if the host changes. Sign out asks for confirmation, ends the session, and returns to the TV sign-in screen. Back from Settings returns to Home. The remote can move between the two buttons; nothing is left unreachable.

## 2.6.8 -- 2026-11-27
A fix on top of 2.6.7 so **remux delivery works for HEVC titles**. Schema stays at 15. No new client is needed; the Roku channel can re-enable remux with a one-line change (`RemuxEnabled()`), and the native Android TV player benefits with no APK change.

- **An HEVC remux now plays instead of producing no picture at all.** `_remux_cmd()` deliberately muxes HEVC as fMP4 (`init0.mp4` + `seg0.m4s`, cut at `-hls_time SEG`) because hls.js cannot play HEVC in MPEG-TS, but the playlist served for a remux was built by `playlist()`'s bounded branch, which hardcodes `seg%d.ts`, pins `#EXT-X-VERSION:3` and ignores its own `fmp4_init` argument. So the playlist advertised `.ts` names with no `#EXT-X-MAP`, the `.ts` segment route has no codec guard and returned the `.m4s` bytes anyway, and the client was handed fMP4 fragments with no init segment. It could never decode a first frame, so every HEVC title badged "Remux ready" burned the client's start timeout and then fell back to transcoding. H.264 8-bit remux was unaffected, which is why this looked intermittent rather than broken. `hls_playlist()` now passes `bounds=None` whenever the stream needs an init segment, taking the generic branch that already emits `#EXT-X-MAP`, `.m4s` names and `#EXT-X-VERSION:7` -- the same playlist shape an HEVC *transcode* has always used successfully. The session still gets its keyframe plan: `get_session()` derives bounds itself.
- **The tail of an HEVC remux no longer 404s.** `Session.nseg` was `len(bounds)` whenever a keyframe plan existed, but an HEVC remux is cut by the hls muxer at `-hls_time SEG`, not at those bounds -- and a real plan is sparser than the muxer's segments (`probe_bounds()` keeps a split point only 3 s or more past the last one, while `SEG` is 2 s). A 30 s title has 15 segments but about 10 bounds, so segments past that count were rejected by `n >= s.nseg`. The HEVC-remux case now uses the duration-based count; H.264 remux still uses the plan.
- **Regression test:** `tests/test_remux_hevc_268.py` pins both, plus a guard that the bounded branch really cannot carry fMP4 (which is why the route must null `bounds`) and that H.264 remux still segments at the probed keyframes. The nseg test fails on 2.6.7 and passes here.

## 2.6.7 -- 2026-11-27
A fix on top of 2.6.6 so a mid-watch transcode is not torn down and restarted from the opening. Schema stays at 15. No new Android app is needed (the native Android TV player, the in-page player, and the Roku channel all benefit from the server change).

- **A stray start-at-zero request no longer rewinds a transcode that is already running later in the title.** The HLS playlist is a VOD list from segment 0, so a client such as the Android TV ExoPlayer can ask for `start=0` or segment 0 while you are an hour in. The server used to stop ffmpeg and start again at the opening, which wiped the playhead segments and made the player exit. A live or paused encode now keeps its place. If ffmpeg has already exited, it restarts at the playhead, not at the opening.
- **Leftover later segments from the previous run no longer look like a huge buffer ahead of a restart at 0.** That false “ahead” figure was pausing the new encode before the first segment was written, so hardware fallback could sit on “no output after 20s.” `highest_done()` now ignores those leftovers.

## 2.6.6 -- 2026-11-27
A small player change on top of 2.6.5: the first-load wait no longer shows a “Buffering…” line. Schema stays at 15. No new Android app is needed (the in-page player, including the phone WebView and a TV web session, is served by this package). The Roku channel and the native Android TV ExoPlayer are unchanged.

- **A centered circular progress ring in the Movinite purple accent replaces the first-load “Buffering…” message.** Mid-play rebuffers use the same ring, without that word. The ring is determinate when the player has a real readiness signal: seconds already buffered versus a 2-second start threshold, HLS fragments loaded versus the one segment needed to start, or the server’s new `/api/items/{id}/play-start` count of transcode/remux segments ready for this viewer. If none of those are known yet, the ring spins and no percentage is invented. The 12-second no-picture fallback is unchanged, and the overlay hides only once `videoWidth > 0`.

## 2.6.5 -- 2026-11-27
A fix on top of 2.6.4 so Direct Play and transcode are not starved by a looping transcode, and so the phone web player does not get stuck on Direct Play for HEVC and 4K. Schema stays at 15. No new Android app is needed (the in-page player is served by this package). The Roku channel itself is unchanged in this release.

- **Bogus client display sizes no longer cap a title at 360p.** A Roku channel bug sent `disp=88 dec=88`, and the server treated 88 pixels as a real screen, so a 4K file was transcoded to 360p and stalled. Values below 480 pixels are ignored. If the client reported only a bogus size, the cap is 1080p. A missing size is still no cap. The channel bug itself is not fixed here.
- **A transcode that produces no output no longer tears down and restarts in a tight loop.** After a VAAPI stall the session still falls back to CPU and stays there. Empty starts of the same session are rate-limited (three in 60 seconds, then a 45-second backoff). The wait loop no longer extends its deadline forever when a restart is skipped. Opening a new stream, including Direct Play of the same file, pauses a runaway transcode that still has no output, so it cannot keep the share busy.
- **Destroying a session no longer raises `FileNotFoundError` on `ffmpeg.log`.** If the session directory is already gone, `start()` logs a warning and returns instead of crashing.
- **The phone web player treats `direct_maybe` for HEVC or 4K as a transcode, not Direct Play.** The 12-second no-picture watchdog now clears only once `videoWidth > 0`, not on `canplay` or `readyState` alone, so a silent first-byte event cannot cancel the fallback.

## 2.6.4 -- 2026-11-27
A quick fix on top of 2.6.3 so the Roku app (and other non-browser clients) can finish sign-in. Schema stays at 15. No new Android app is needed. The Roku channel 0.1.4 reads this new JSON field and still accepts the cookie if a later server already set it.

- **Password sign-in and phone-code approval now return the session token in the JSON body, as well as the `ms_session` cookie.** In 2.0–2.6.3 `/api/login` and an approved `/api/pair/poll` only set the httponly cookie and (for poll) removed `token` from the JSON. The web player is unaffected because it uses the cookie. Roku's `roUrlTransfer` often does not expose `Set-Cookie` in response headers, so the channel could sign in successfully and then show "Signed in, but no session cookie was returned," and a phone approval of the TV code never completed on the TV. The cookie is still set, so browsers and the Android app are unchanged.

## 2.6.3 -- 2026-11-27
A quick fix on top of 2.6.2 plus a sideloadable Roku channel. Schema stays at 15. The Android app is unchanged; the new Roku app is sideloaded and is not a store release.

- **A native Roku app (BrightScript / SceneGraph) can be sideloaded (the channel source is not in this tree yet).** It talks to the existing Movinite API: server URL (default `https://media.tukuia.com`), phone-code or password sign-in, Home rows with the same poster rules as 2.5.10, Libraries, a remote Search keyboard, a details page, resume / progress, HLS playback, Direct Play of MP4 when the Roku can decode it, text subtitles as WebVTT, and PGS / VobSub burn-in. It reports real device caps (`native=1`, HEVC, audio, HDR, display size) and always sends `mkv=0`, because Roku cannot Direct Play Matroska.
- **`mkv=0` is now honored when a native player advertises caps.** In 2.4–2.6.2 a missing `mkv` flag defaulted to “Matroska is fine,” but an explicit `mkv=0` was also treated as true (`_flag(...) or True`). Roku clients can now tell the server not to offer Matroska as Direct Play.
- **Sign-in tokens work as a Bearer header or `ms_session` query, not only as a cookie.** Roku’s Video and Poster nodes do not keep a browser-style cookie jar, so the channel sends `Authorization: Bearer …` and, for HLS segments and artwork, `?ms_session=`. Playlists only embed that query when the client asks (`embed_session=1`, a `Movinite-Roku` user-agent, or a request that already had `ms_session`). The web player is unchanged and still uses the cookie alone. Device lists show “Movinite app (Roku)” for this channel.

## 2.6.2 -- 2026-11-27
A quick fix on top of 2.6.1 for Direct Play sitting on “Starting direct play — Waiting for the first picture…” until you change the quality. Schema stays at 15. No new Android app is needed.

- **Direct Play now stops background remux and subtitle work, the same way a transcode already did.** Prefetch of remux cut points kept reading the library share after you pressed Play on the original file, so the first picture could hang (The Iceman, a 1080p H.264/AAC MP4 that was already set up for streaming, was one case). The web player only fell back on an error, not on a hang, so the wait overlay stayed up until you picked a transcode quality, which starts immediately because a transcode already yields that background work. Direct Play now yields too, and counts as “busy” for 20 seconds after each read so the NAS stays free while you watch.
- **If the first picture still does not arrive within 12 seconds, the player switches to remux or transcode on its own.** That is the automatic version of changing the quality.
- **The 2.4.4 phone app no longer advertises itself as the native TV player.** `playNative` exists on phones but returns ok=false, so Play uses the in-page player. The web app was still sending `native=1`, which could offer Direct Play of HEVC Matroska files the phone WebView cannot start reliably. Television ExoPlayer is unchanged.


## 2.6.1 -- 2026-11-27
A quick fix on top of 2.6 for Heart of the Beast playback and for picture-based captions turning the video green. Schema stays at 15. No new Android app is needed.

- **Heart of the Beast is no longer treated as HDR.** The file is 10-bit BT.709 (its own tags say so) with leftover HDR mastering-display metadata copied into the file. 2.6 read that metadata and converted the picture as if it were HDR10, which made the colors green, yellow and cyan and forced a slow software conversion that could not keep up (the player sat on “Transcoding 1080p · HDR10 with GPU tone-mapping · buffering…”). 2.6.1 trusts an explicit BT.709 label and leaves the file alone, so the picture looks natural and the GPU just scales it (about 9–10× real time). Titles that were already stored as mistagged HDR are re-checked on the next play and by the idle backfill.
- **Dolby Vision 8.1 (One Last Shot and similar) still gets a real HDR-to-SDR conversion, now fast enough to play smoothly.** The conversion runs at 1080p with libplacebo (or zscale + hable if that filter is missing) after a CPU decode, then encodes on the GPU, at about 1.6× real time. Well-tagged HDR10 like Joker is unchanged and still uses the GPU tone-map (about 7× real time).
- **Turning on picture-based captions (PGS / VobSub) no longer turns the video solid green on Intel GPU servers.** In 2.3–2.6 the burn-in decoded on one VAAPI device and uploaded the subtitle plane to a second one, then mixed them with `overlay_vaapi`. On the Arc A310 that produced a solid green picture (seen on Zootopia and John Adams from the phone). 2.6.1 uses one shared device: decode, scale and (when on) HDR tone-map on the GPU, download to normal video, overlay the subtitle on the CPU, then upload for the GPU encoder. `overlay_vaapi` is no longer used. 4K to 1080p with subtitles stays above real time. Text subtitles (SRT / ASS / WebVTT) are unchanged: they are still served as sidecars and never restart the transcode. The TV app uses the same burn-in path, so it gets the same fix.

## 2.6 -- 2026-11-27
An HDR detection update on top of 2.5.10. After 2.5.10 the version rolls to the next minor (the third digit maxes out at .10). Schema stays at 15: additive `hdr_type` and `hdr_primaries` columns are added on items, with no schema bump. No new Android app is needed.

- **Tone-mapping now also applies to Dolby Vision 8.1 and mistagged HDR10 files.** 2.2 already converted properly tagged HDR10 and HLG (transfer `smpte2084` or `arib-std-b67`) when **Settings → Transcoding → HDR to SDR** is on. Files that only carry a Dolby Vision configuration record (profile 8.1, whose base layer is PQ even when flagged as bt709) or HDR10 mastering-display / content-light metadata with BT.2020 or P3 primaries on a 10-bit stream were treated as ordinary video and looked washed out. Those are now detected and converted too.
- **Genuine 10-bit SDR is left alone.** Detection uses the transfer function, the DOVI record, and mastering / content-light side data — not “10-bit 4K” by itself.
- **The detected type is stored** (`hdr10`, `hlg`, `dv5`, `dv7`, `dv8`, `hdr10-mistagged`, or `sdr`) along with the mastering primaries when they are known (`hdr_primaries`, for example `smpte432` for Display P3), so playback does not have to probe the file again. Unclassified 4K Main 10 titles are filled in by a light idle job. Both columns are additive; schema stays at 15.
- **Conversion uses VAAPI `tonemap_vaapi` when it is available**, with a software zscale + hable fallback. Mistagged files have their input transfer set to smpte2084, and their primaries set to the file’s mastering display (Display P3 / `smpte432` for Heart of the Beast, not BT.2020). Dolby Vision 8.1 is mapped in software (then uploaded for a GPU encode) because Intel’s `tonemap_vaapi` needs mastering-display metadata that those files often lack. Dolby Vision profile 5 has no HDR10 base layer: it is skipped (with a log line) unless ffmpeg’s libplacebo filter is present.

## 2.5.10 -- 2026-11-27
A poster-art fix on top of 2.5.9, for the phone, the television, and the desktop. Schema stays at 15. No new Android app is needed — browsing on the television uses the WebView, so these are server/web changes only.

- **Everywhere an episode, show, or season is shown, the 2:3 poster is used when one is available.** 2.5.8 already did this for Continue Watching, My List, Recently added, search results, and other home-style rows. This version extends that to the episode details page and the episode list on a show details page, and uses the same fallbacks everywhere else an episode image appears (including Up Next and the now-playing card): the series poster first, then the season poster, then the episode still as a last resort. If only a still is available, the still stays in a 16:9 box so it is not cropped into a tall frame.
- **Episode details show the show's poster, not the wide still.** The poster is a centered 2:3 image (about 55–60% of the phone width; on a television it keeps the existing first-screen cast layout). The page backdrop uses the series backdrop when one exists. Movie details poster size is unchanged.
- **The show details episode list uses the same poster, with SxxExx and the episode name laid out as a clean list** (portrait thumb, episode code, title, duration, and the play button). The list API now includes the series and season art so the client can pick the right image.
- **Fixed: on the Android TV, some 4K movies with many subtitle tracks stayed on "Transcode 1080p".** Subtitles now load in the background in one pass, and playback starts right away. No new Android app needed.

## 2.5.9 -- 2026-11-27
A television search and slide-out fix on top of 2.5.8. Schema stays at 15. No new Android app is needed — browsing on the television uses the WebView, so these are server/web changes only. Phone and desktop search are unchanged.

- **TV Search works with a dark page and an on-screen keyboard.** Opening Search used to show a solid blue screen with a faint, unfocused input and no way to type except Back. Search now stays on the dark #0F1115 theme with the slim rail still visible, autofocuses a D-pad keyboard (A–Z, 0–9, space, backspace, clear) with a white focus, and updates live results as poster rows (movies, shows, episodes using the series poster, and music). Up from the results returns to the keyboard; Left from the first key or the first result goes to the rail; Back goes home.
- **You can move past Search in the slide-out menu.** Pausing on a menu row no longer auto-opens it, which had jumped focus back to Home as soon as you pressed Down from Search and made Libraries and Settings unreachable. Up and Down now walk every item (Profile, Home, Search, My List, each library, Settings) while the menu stays open. Right or Back closes it and returns focus to where you were. Opening with Left focuses the matching item (Home opens on Home, Search on Search, and so on) without a brief focus loss.
- **The slide-out and the slim rail show the same items, and the open menu is wider.** The rail is Profile at the top, with Home, Search, My List, Libraries, and Settings centered below, matching the slide-out order. Because the menu is tucked away when closed, it now uses about 28% of the screen (~538px at 1080) with larger type and taller rows so library names like "Northshore Feature Films" are no longer cut off. The page behind it stays dimmed.


## 2.5.8 -- 2026-11-27
A card-art fix on top of 2.5.7, for the phone, the television, and the desktop. Schema stays at 15 (new optional columns on the shared-title cache only). No new Android app is needed.

- **TV episode cards in home-style rows use the show's poster, not the episode still.** Continue Watching, My List, Recently watched, Recently added, search results, and other rows showed a wide 16:9 still ("the clip") for an episode, next to tall movie posters. Those cards now use the parent series' 2:3 poster, in the same size as a movie. The card title is the series name; the subtitle is SxxExx, plus the episode name when it fits. The progress bar and the watched check are unchanged. If the series has no poster, the season poster is used, then the episode still (still in a tall card). Shared (remote) episodes use the same art once both servers are on this version. Episode lists on a show details page still use the stills.
- **On a television, focusing an episode in a row uses the series backdrop in the hero,** with the series title (and the episode code in the facts line). The show details page is unchanged.


## 2.5.7 -- 2026-11-26
A typography and layout fix on top of 2.5.6, for the television and for phones. Schema stays at 15. No new Android app is needed — browsing on the television uses the WebView, so these are server/web changes only. Desktop is unchanged.

- **The first TV home poster is no longer cut off by the left rail, and the rail is slimmer.** In every home row, the first poster's left edge (and its white focus border) used to sit under the solid rail. Rows now start after the rail with a safe gap, and focusing a poster scrolls the strip so the scaled card and its border stay fully visible. The collapsed rail is narrower (about 3.5–4% of the screen) with slimmer icons. The profile icon stays pinned at the top and can be focused with the remote; the Search, Home and Libraries icons are vertically centered in the remaining space. The slide-out menu is a little narrower too.
- **TV focus uses a single white style, not a double border.** Action buttons (Resume, Play from start, Mark watched, Download), slide-out items, and rail icons no longer draw a thick white outline plus a purple or white outer ring. Focused buttons fill white with dark text; posters and rail icons use one solid white border. The leftover "N of the top-billed" count above Cast on a movie details page is hidden on TV.
- **The see-through phone top bar is on every screen, not just movie pages.** Home, Libraries, Search, Downloads, Settings, and lists use the same transparent header as the details pages from 2.5.4 (a soft top fade and icon shadows over the #0F1115 page, never a gray or frosted bar). Content scrolls under the bar. The bottom tab bar is unchanged. The Android app's system status bar is still the app's dark color — matching that area would need a new app build, and is not part of this update.


## 2.5.6 -- 2026-11-26
A typography and first-load fix for the television, on top of 2.5.5. Schema stays at 15. No new Android app is needed — browsing on the television uses the WebView, so this is a server/web change only. Phone and desktop are unchanged.

- **The TV home no longer shows a white vertical line or a solid blue flash on first load.** Before the first backdrop arrived, the page sat on a bright solid color and the slim left rail had a visible 1px seam down the screen. The page, the rail, and the hero now use an opaque #0F1115 fill (the same dark color as the rest of the app) until the artwork loads, and the rail no longer draws a right-edge border.
- **White title text stays readable on a bright backdrop.** The left-to-right fade behind the hero text (and on the movie and show details pages) is stronger on the left, and stays relatively clear on the right.
- **Cast photos fit on the first screen of a movie details page.** The empty gap under the poster and synopsis is gone, the poster is about 35–40% of the screen tall, the synopsis is limited to four lines, and the cast row (photos about 16–18% of the screen tall, with names) sits fully on screen at 1920×1080 and on a short 960×540 TV WebView, with no scrolling required. Focus rings stay visible and unclipped. On a show page, season tabs and episodes can still scroll below.

## 2.5.5 -- 2026-11-26
A typography and spacing fix for the television, on top of 2.5.4. Schema stays at 15. No new Android app is needed — browsing on the television uses the WebView, so this is a server/web change only. Phone and desktop are unchanged.

- **The TV home title and posters are larger, and the top tabs are hidden.** The For You / Recently Added / Libraries tabs are turned off for now (the code stays behind a flag so they can come back). With that bar gone, the movie title starts farther down the screen (about 8%) and is about 11% of the 1080-tall layout (~119px), a little larger than the first 2.5.5 pass, and long titles can wrap to two lines without being cut off mid-letter. Short TV WebViews (960×540 CSS at DPR 2) use that same 1080 layout, scaled to the window, so the title and posters look the same size as on a 1080 preview. The year, duration, genre, rating and description scale up with it. Posters are about 24% of the screen tall, and the next row still peeks at the bottom (~15%). The focused poster keeps a full white border: the row leaves room for the 13% scale, so the top is no longer clipped and the poster no longer overlaps its row label. The left rail icons are larger and sit in from the edge (about 4% TV safe area). The hero backdrop starts updating as soon as a poster is focused, and neighboring backdrops are preloaded. The hero text still sits above the focused row.
- **The TV details page fills the screen the same way the home does.** Opening a movie, a show, an episode, or a shared title uses the 1080 layout (scaled on a short WebView). The backdrop is full-bleed and sharp, with a left-to-right fade and a fade into the rows below. The title, year, synopsis, buttons, cast and episode list are large and readable, with a visible white focus border that is not clipped. The first screen is filled; the lower sections scroll normally. The phone details bar from 2.5.4 is unchanged, and scrolling on the phone still keeps that bar see-through.

## 2.5.4 -- 2026-11-26
A visual fix on top of 2.5.3, for phones and the television. Schema stays at 15. No new Android app is needed — browsing on the television uses the WebView, so both changes are server/web only.

- **The phone details top bar stays see-through while you scroll.** On a movie, episode, or show details page, the header (logo, search, server status, avatar) stays transparent over the backdrop at every scroll position. It no longer switches to frosted gray or tinted glass after you scroll. A slightly stronger dark fade and icon shadows keep the controls readable over the page underneath. Other phone pages (home, libraries, and the rest) still use the solid charcoal bar. Desktop is unchanged. The bottom tab bar is unchanged. The Android app's system status bar is still the app's dark color.
- **The TV home matches a Plex-style fixed hero and a single row slot.** The selected movie stays in the top ~62% of the screen (title, year, duration, genre, rating and a short description on the left; a vibrant backdrop on the right, with a heavy left-to-right fade into the dark background and a fade down into the rows — no uniform dark overlay). The page itself does not scroll. The focused poster row always sits in the bottom ~38%; moving down slides the previous row away completely and leaves the top of the next row peeking at the bottom. The row title sits above the posters. The focused poster scales up about 13% with a solid white border and no glow; titles and captions under the cards (including “Because you watched…” and “Picked by an admin”) are hidden. Unfocused posters stay at normal brightness. The For You / Recently Added / Libraries tabs show on load, slide up and hide when you move down from the first row, and come back when you press Up from that row. Hero text and the backdrop update immediately when you move left or right (a short debounce still covers rapid key-repeat). This also fixes the 2.5.3 bug where a 560px reserved top on a shorter TV WebView (for example 960×540 CSS pixels at 2× density) left a black lower half with no posters. The layout fills the window with a fixed pane and moves a rows track by a pixel pitch (no 100vh, clip-path, or mask). The rail and the 2.1.4 Left / rail / slide-out behavior are unchanged; the screen dims more heavily while the slide-out is open. Details and player pages still scroll normally. Phone browsing (aside from the details bar above) and desktop are unchanged.

## 2.5.3 -- 2026-11-26
A TV-home layout fix on top of 2.5.2. Schema stays at 15. No new Android app is needed — browsing on the television uses the WebView, so this is a server/web change only.

- **The top of the TV home stays reserved for the selected movie.** On the Plex-style TV home (For You, Recently Added, and Libraries), the backdrop, title, details, description and cast stay in a fixed area at the top. Only the poster rows below that line scroll. Moving down to a lower row (for example Recommended for you) snaps that row up just under the hero; earlier rows scroll away above the line and are clipped, instead of sliding over the title and colliding with the tabs. Hero updates on focus are still debounced as in 2.1.4. The rail, the tabs, and the Left / rail / slide-out behavior are unchanged. Phone and desktop are unchanged.

## 2.5.2 -- 2026-11-26
A visual fix on top of 2.5.1, for phones only. Schema stays at 15. No new Android app is needed.

- **The phone top bar matches the movie backdrop.** On a movie, episode, or show details page, the header (logo, search, server status, avatar) is transparent so the page's blurred backdrop continues up behind it, with a soft dark fade so the icons stay readable. As you scroll, the bar becomes frosted glass tinted to the artwork's color (taken from the backdrop in the browser; a dark glass is used if that isn't available). Other phone pages keep the current solid bar. Desktop and TV are unchanged. The bottom tab bar is unchanged. The Android app's system status bar is still the app's dark color — matching that area would need a new app build, and is not part of this update.

## 2.5.1 -- 2026-11-26
A visual fix on top of 2.5: the profile menu and the server status dropdown (and the other page dropdowns that already shared that chrome) use a glossy charcoal-to-graphite style instead of the 2.4.2 purple glass. Schema stays at 15. No new Android app is needed.

- **Glossy gray dropdowns.** The shared popover fill is a charcoal-to-graphite gradient (about #2b2e35 at the top to #16181d) with a faint white sheen across the top third, a 1px light highlight on the top edge, a frosted blur, a fine light border, and a soft shadow. Text stays readable. Hovered rows go light gray, not purple. The avatar and the status dots keep their purple accents. Opening one menu still closes the others. The TV slide-out is unchanged. The CPU and RAM tiles inside the server status panel use the same glossy gray; the rings, dots and usage bars keep their purple accents.

## 2.5 -- 2026-11-26
Watch progress for titles played from a shared (remote) server, on top of 2.4.4. Schema 15. No new Android app is needed — the phone, the TV app and the web UI all use the same progress API.

- **Shared titles show up in Continue watching.** Playing a film or episode from another Movinite server used to leave no trace: progress was posted with the shared item's negative API id, which could not be stored in the local `progress` table (that table only accepts ids from this server's `items` list, and foreign keys are on). The player swallowed the error, so resume was always 0 and the title never appeared in Continue watching or My List, on the web, the phone or the TV. Progress is now kept in a `remote_progress` table, and those titles appear in Continue watching and My List with their poster and resume position. Resume opens at the saved spot. Opening the details page for a shared title no longer fails (it expected local-only fields such as audio streams and the cast list).
- **The row stays one card per title.** If you also have a local copy of the same film (matched by TMDB id, or by title and year), the shared and local progress are merged and the local copy is preferred. The Movies / TV-only filter is unchanged. Titles you have finished, marked watched, or watched past about 95%, drop off the same way as local ones; a start under 30 seconds is ignored, as before.
- **If the other server is offline, the card stays, marked Offline.** Home and My List never fail just because a peer is down (they only read the local catalog). Opening Play shows a short message instead of an error, and the title will play again when that server is back. Libraries that have been unshared are hidden.

The first start of 2.5 copies the database to `data/media-server.db.pre-schema15` (mode 600) before applying schema 15.


## 2.4.4 -- 2026-11-26
A phone-app-only update on top of 2.4.3 (schema stays 14; no server change and no database upgrade).

- **On phones, Play uses the in-page web player again**, the same tap-to-show controls as before 2.4. After 2.4.3 fixed the "Source error," tapping the picture in the native player did nothing: that player was built for a TV remote (the on-screen chrome was toggled only by D-pad keys, and there was no touch handler). The 2.4.4 app (versionCode 12) keeps the native Media3 player on Android TV / leanback devices, and on phones and other non-television devices `playNative` returns `ok=false` so the existing in-page player takes over. Installed server 2.4.3 already honors that, so no server install is needed.
- **If the native player is opened anyway, taps work too.** A single tap on empty video shows or hides the controls (they still auto-hide after about four seconds while playing), the buttons and seek bar stay tappable, a double-tap on the left or right third seeks ±10 seconds, pinch or the Fill/Fit button toggles crop, and Close exits. TV D-pad behavior is unchanged.

## 2.4.3 -- 2026-11-26
A playback fix on top of 2.4.2 (schema stays 14; no database upgrade). The native Android player also gets a small update (versionCode 11).

- **Native playback works again.** After installing the 2.4 APK, Play handed off to the native player, which asked for a 2K HEVC transcode. The server started ffmpeg successfully, then crashed on every fMP4 (`.m4s`) segment request with `TypeError: hls_segment() takes from 3 to 11 positional arguments but 12 were given`. ExoPlayer showed "Can't play this title: Source error" and sat at 0:00. The `.m4s` route was passing `acopy` into the `.ts` handler, which did not accept that argument (and the `.ts` handler itself referenced `acopy` without declaring it). Both routes now share one helper that takes `acopy`, so HEVC fMP4 and H.264 MPEG-TS segments are served normally.
- **The native player no longer dead-ends on a source error.** If HEVC fails it retries the same height as H.264, and if that fails it opens the in-page web player. A small debug line shows the real error (for example `ERROR_CODE_IO_BAD_HTTP_STATUS · HTTP 500`) instead of only "Source error".

The 2.4.2 purple dropdown chrome is unchanged.
## 2.4.2 -- 2026-11-26
A small visual fix on top of 2.4.1 (schema stays 14; no database upgrade). No new Android app is needed.

- **Dropdowns share one purple, classier style.** The profile menu was a dark gray glass panel while the server status popup used a purple glass fill, so they looked like two different products (and could both be open at once, overlapping). They now use the same tokens (`--pop-bg` and friends): a deep aubergine-to-violet gradient, a frosted blur, a fine light-purple border with a soft inner highlight, and a soft shadow. Hovered rows get a gentle purple tint, and dividers match. Sign out stays a readable red. The same chrome is used for the details "More" menu, the library More menu, the in-page player options menu, and the music volume popover. The TV slide-out is a different component and is unchanged.
- **Opening one dropdown closes the other.** Tapping the avatar closes server status, and opening server status closes the profile menu (and the other page menus listed above).

The 2.4.1 stats overlay fix (short GPU name, more see-through player stats) is unchanged.

## 2.4.1 -- 2026-11-26
A small layout fix on top of 2.4 (schema stays 14; no database upgrade). No new Android app is needed.

- **The player stats overlay keeps each value in its own column.** On a phone (and any other narrow width) the Encoder line used to print the full PCI name of the video card — for example `Idle · GPU (VAAPI) (Intel Corporation DG2 [Arc A310])` — and run over the Dropped count. The visible name is now a short label such as `Arc A310`, on a second line, with the full name in a tooltip. The 2×2 grid can shrink (`minmax(0, 1fr)` and `min-width: 0`), and cell text wraps or ellipsizes instead of painting over the next column. This is the in-page (WebView) player used by the phone app, desktop browsers, and a 2.0.2 TV app. The native 2.4 player has no stats overlay, so no new APK is included.
- **The same overlay is more see-through.** The fill is about 26% opaque (it was 38%), with a light blur and a text shadow so CPU, RAM, Encoder and Dropped stay readable on a bright scene, and more of the picture shows through.

The 2.4 native player, 2.3 Skip Intro / image-subtitle burn-in, 2.2 playback behaviour, and 2.1.4 TV remote navigation are unchanged.

## 2.4 -- 2026-11-26
Builds on 2.3 (schema stays 14; no database upgrade). A new Android TV app is included.

- **Online playback on the Android TV app uses a native player (Media3 / ExoPlayer), not the WebView.** Browse, search and the 2.1.4 remote navigation stay in the WebView. Pressing Play (or Resume) hands the title to a full-screen native player through the app bridge. The login session is the WebView cookie, applied to media requests on the native side — it is not passed through JavaScript.
- **The app reports real decoder, display and audio capabilities** (HEVC Main10, AV1, HDR10 / HLG / Dolby Vision display modes, 4K, and AC3 / EAC3 / DTS / TrueHD through AudioCapabilities). The server prefers Direct Play of HEVC, HDR and surround when those caps are present, then remux, then transcode. Remux can bitstream-copy AC3 / EAC3 when the player can passthrough. DTS and TrueHD are Direct Played in the original file when the TV or AVR reports them. The 2.0.2 app and ordinary browsers keep the previous, safer rules (no `native=1`), so a 2.0.2 APK still works against this server.
- **The native player matches the 2.2 / 2.3 playback features:** resume and progress reporting, seek-bar thumbnails, an Up Next countdown with Play now and Cancel, Skip Intro and Skip Credits buttons that take focus on the remote, a subtitle menu (text tracks are soft WebVTT; image subtitles still use a transcode burn-in), and an audio and quality menu. The on-screen controls are built for a D-pad.

Desktop and phone browsers are unchanged (they still use the in-page player). TV home-screen navigation from 2.1.4 is unchanged. 2.3 Skip Intro / image-subtitle burn-in and 2.2 playback behaviour are unchanged on the web player.


## 2.3 -- 2026-11-26
Builds on 2.2. Schema 14 (a `media-server.db.pre-schema14` backup, mode 600, is written once before the bump).

- **Skip Intro and Skip Credits.** When a season's episodes share an opening, or a file has intro/credits chapters, a Skip Intro button appears (focusable on a television; OK skips). A Skip Credits button appears when the ending starts and opens the 2.2 Up Next card (or jumps to the end if there is no next episode). Detection runs in the background, yields when someone is watching, and uses chapters first, then audio fingerprints across a season (fpcalc if it is installed, otherwise ffmpeg), then black/silence at the end of the file for credits. Settings > Account has Auto-skip intros and Auto-skip credits, saved per user and off by default.
- **Image subtitles (PGS / VobSub) are burned in when you pick them.** They are listed in the subtitle menu. Choosing one starts a transcode and overlays the pictures on the GPU when `overlay_vaapi` is available (the subtitle plane is rendered on the CPU and uploaded); otherwise the subtitle is overlaid on the CPU and the frame is uploaded for GPU encode. Text subtitles stay soft (WebVTT). Remux and direct play still cannot show image subtitles.

The installed 2.0.2 Android TV app works as-is; this is a server update. Desktop and phone layouts are otherwise unchanged. TV remote navigation from 2.1.4 is unchanged. 2.2 playback behaviour (immediate start when remux is not ready, 5.1 audio, seek-bar thumbnails, Up Next, the 4K TV cap, and HDR tone mapping off by default) is unchanged.


## 2.2 -- 2026-11-26
Builds on 2.1.4. Schema 13 (a `media-server.db.pre-schema13` backup, mode 600, is written once before the bump).

- **Play starts on the first try when remux is not ready.** Remux (copy the original video into HLS) is only offered when a keyframe plan is already cached. If the plan is missing, the player starts a transcode immediately instead of trying remux, getting an error, and falling back. An idle, low-priority job fills missing plans (and yields the moment someone presses play).
- **Surround sound is kept.** When the client can play AAC, remux copies 5.1 (or 7.1) AAC and transcodes other surround formats (EAC3, AC3, DTS) to AAC 5.1. Transcodes also keep 5.1 AAC. Stereo is used only when the client cannot play surround, or when the source is already stereo.
- **HDR to SDR tone mapping is available on the GPU, off by default.** Settings > Transcoding has a toggle. When it is on, HDR10 and HLG titles that have to be transcoded use `tonemap_vaapi`. 10-bit SDR (bt709) is never tone-mapped. It is off until it has been checked on a real HDR film (a library sample during planning was 10-bit SDR). Colour tags (`color_transfer`, `color_primaries`, `color_space`) are backfilled in the background.
- **Seek-bar thumbnails.** While the server is idle it builds a sprite strip (about one picture every 10 seconds) on the GPU. Hovering or dragging the seek bar shows the picture. Cache size is in Settings > Transcoding (default 3 GB; 0 turns it off). Work stops when someone starts playback.
- **Up Next.** At the end of an episode (or any title with a next item) a card counts down from about 15 seconds with Play now and Cancel. Cancel leaves you on the current title.
- **4K televisions are not capped at 1080p** just because the web view reports 1920×1080. Auto on a TV treats that as a 4K display so 4K remux and transcode stay available. Settings > Account has Auto / This is a 4K display / This is 1080p or smaller.
- **An honest start overlay** names the mode (direct play, remux, or transcode) and shows when it is waiting for the first picture. hls.js prefetches the first segment.

The installed 2.0.2 Android TV app works as-is; this is a server update. Desktop and phone layouts are otherwise unchanged. TV remote navigation from 2.1.4 is unchanged (first Left focuses the slim rail, second Left opens the slide-out, the top tabs are selectable).


## 2.1.4 -- 2026-11-26
Builds on 2.1.3 (schema stays 12; no database upgrade).

- **The first Left from a row goes to the slim left rail, not the slide-out menu.** In 2.1.3, Left from the first poster, a tab, or the rail opened the slide-out immediately, so the rail icons never kept focus and the menu appeared whenever you tried to use the left side. 2.1.4 moves Left within a row to the previous poster; Left on the first poster focuses the current section's rail icon (with a clear focus ring) and leaves the menu closed; a second Left on the rail opens the slide-out. Right or Back from the slide-out closes it and returns to the rail (or the last poster). Right from the rail returns to that poster. Up and Down walk the rail icons; OK activates them. Sign out still needs OK.
- **The top tabs (For You, Recently Added, Libraries) are selectable.** Up from the first row reaches the tabs with a visible focus pill. Left and Right move between tabs; after a short pause (~250 ms) that section opens, but the tab keeps focus. Down returns to the posters. Left from For You goes to the rail, not the menu. The Libraries tab scrolls to the library rows instead of opening the slide-out. If focus is ever lost, it is restored to a poster, a tab, or the rail so the outline does not disappear.
- **The home screen responds faster to the remote.** Hero backdrop changes wait about 300 ms and crossfade instead of jumping on every poster. Neighbour artwork is preloaded. On a television, page and row scrolling is instant (no stacked smooth-scroll), and the home remote only considers on-screen posters plus the tabs and rail, so each key does less work. The slide-out opens immediately even if the library list is still loading.

The installed 2.0.2 Android TV app works as-is; this is a server update. Desktop and phone layouts are unchanged. Opening a title still focuses Resume or Play at the top of the page (2.1.2).



## 2.1.3 -- 2026-11-26
Builds on 2.1.2 (schema stays 12; no database upgrade).

- **The TV no longer hits "Too many checks; wait a moment" while waiting for a phone approval.** In 2.1.2 the television asked the server every 1.5 seconds whether the code had been approved, but the server only allowed 90 checks per address in 10 minutes — not enough for a 10-minute code (about two minutes of waiting tripped the limit). On a 429 the TV also showed that error and kept checking just as often. 2.1.3 checks about every 3 seconds, slows down further if the server asks it to wait, and does not show that error on the sign-in screen.
- **The check limit is now per code and real client address**, and is large enough for a full 10-minute code (400 checks per code+address in 10 minutes, with a separate coarser cap per address). The real client address behind a trusted proxy is still used (CF-Connecting-IP, then X-Real-IP, then X-Forwarded-For).
- **Sign in with a username and password stays available.** Opening the password form stops the approval checks, so a "too many checks" message can no longer appear on (or block) the password screen. Password sign-in is not part of the check limit.

The installed 2.0.2 Android TV app works as-is; this is a server update.


## 2.1.2 -- 2026-11-26
Builds on 2.1.1 (schema stays 12; no database upgrade).

- **The web top bar is hidden on a television.** Search, poster sounds, server status and the account button in the web header stay on desktop and phone only. On a TV, the Plex-style tabs (For You, Recently Added, Libraries) and the clock remain. Search, Sign out (on the profile row) and Settings are in the slide-out menu on the left. The desktop and phone header still uses the same dark color as the sidebar (2.1.1).
- **The TV tab bar is transparent** over the backdrop, with a soft fade and text shadow so the tabs and clock stay readable.
- **Moving the remote around the tabs or the slide-out menu changes the view without pressing OK.** After a short pause (~250 ms) on a tab or a menu item, that section or page opens. Sign out (and other destructive or confirm-only actions) still need OK. Back is unchanged.
- **Remote: Up from the tabs stays put; Left opens the menu.** From the first poster row, Up still reaches the tabs; Down from the tabs still reaches the posters; Right still moves between tabs.
- **Opening a title on a television focuses Resume or Play again.** In 2.1 the Plex home's tall top padding was still applied when the movie page first focused Play, then dropped away, which scrolled the page down and hid the button (the same symptom as 1.9.2). 2.1.2 applies the movie-page layout first, pins the page at the top, and focuses Resume or Play.

The installed 2.0.2 Android TV app works as-is; this is a server update.


## 2.1.1 -- 2026-11-26
Builds on 2.1 (schema stays 12; no database upgrade).

- **Signed-out TV shows only the sign-in screen.** In 2.1 the Plex-style home chrome (hero, For You / Recently Added / Libraries tabs, clock, left rail) was drawn on top of the phone-code sign-in card, so the code and most of the card were hidden. A signed-out television now hides that chrome and keeps the sign-in / password screens on top, fully reachable with the remote. The password button stays usable even after a sign-in-code rate limit.
- **Sign-in codes are requested once per screen.** The TV reuses the current code until it expires (or you tap Get a new code). The server also reuses a still-valid code for the same address and app. New codes are limited to 10 per address per 10 minutes, using the real client address behind a trusted proxy (CF-Connecting-IP, then X-Real-IP, then X-Forwarded-For). Password sign-in is not part of that limit.
- **The top menu bar matches the side menu.** The header on desktop, phone, and TV (the 2.1 tab bar on a television, and the top bar on other layouts) uses the same dark color as the left sidebar / slide-out menu, instead of the purple glass mix.

The installed 2.0.2 Android TV app works as-is; this is a server update.


## 2.1 -- 2026-11-26
Builds on 2.0.2. This is a schema 12 release. The first start after an update copies the current database to `data/media-server.db.pre-schema12` (mode 600) before applying the new tables.

- **Plex-style TV home.** On a television, the home screen uses a full-bleed backdrop of the focused title, with the name (a typographic logo when one is stored, otherwise large text), year, runtime, genres, rating, a short synopsis and cast, a slim icon rail on the left, pill tabs (For You, Recently Added, Libraries) and a clock. Focused posters are outlined and slightly enlarged. Desktop and phone layouts are unchanged.
- **Slide-out menu.** Left from the rows opens a rounded menu over a dimmed home screen: your profile (with Sign out), My Lists, Search, Home, a Libraries list, and Settings. Each library is shown as *Name / source* — the local share name, or the other server's name for a shared library. Up/Down move, OK selects, Right or Back closes the menu and returns focus. The 2.0.2 account / Sign out path still works.
- **Library sharing between Movinite servers.** In Settings > Sharing, an admin shares one or more libraries by creating a one-time link and code (48 hours, single use; only a hash is stored). The other server pastes the link, checks the fingerprint, and accepts. After that, the two servers authenticate with Ed25519-signed HTTP requests (this server's existing identity key). Pairing is one-way; share back with the same flow the other way. HTTPS is required for public addresses; plain HTTP is allowed only for a LAN address an admin types, for example `http://192.0.2.10:8099`.
- **Shared libraries** appear in the library list, search, home rows and the TV menu with the source server's name. Playback uses a short-lived ticket: the player streams directly from the owner when it can, or through this server when the owner is only reachable on the LAN (toggle per peer). The owner can cap quality and simultaneous streams, and can stop sharing at any time (tickets fail immediately). Downloads by the other server's users stay off unless you turn them on.
- **Android TV app.** The installed 2.0.2 Android TV app works as-is. The new layout and sharing are served by the server in the WebView, so you do not need a new APK for 2.1.


## 2.0.2 -- 2026-11-25
Builds on 2.0.1, plus easier sign-in on a television:

- **Sign in with a phone code, like Netflix.** The TV sign-in screen shows a 6-character code (no easily confused letters) and a QR code. Scan it with a phone that's already signed in to Movinite, or open the link and tap **Approve**. The approval page names the television. The TV picks up its own session for that person — no typing a username or password with the remote. Codes last about 10 minutes, work once, and new codes are rate-limited. You can still sign in with a username and password if you want.
- **The TV remembers the server and stays signed in.** After this, the session is refreshed while you use it (30 days from last activity, same cookie as other devices). Sign out is still in the menu.
- **Servers you've used are listed** on the sign-in screen, so you can pick one instead of typing the address again. On the local network the server also advertises itself (`_movinite._tcp`) for the Android app and other LAN tools. The first time you enter a server address in the 2.0 Android app still uses the typed field (see below). Manual entry remains the fallback.
- **The remote can move through the new screens** (Get a new code, Sign in with a password, Approve / Don't approve), with the same purple focus ring as the rest of TV mode.
- **The remote can reach Sign out.** Up from the first row of posters (or from Home in the sidebar) moves to the header. Left and Right walk search, poster sounds, the status pill and the account button in the top-right corner. OK opens the account menu; Up and Down move through My account, Settings, poster sounds and Sign out; Back closes the menu and returns to the account button. Settings > My account also has a Sign out button. The Sign out link at the bottom of the sidebar is reachable too.

**Android app:** the installed 2.0 app (`movinite-android-v2.0.apk`) already keeps the server address and the session cookie, so "stay signed in" works with this server release alone. It does **not** show the code-and-QR screen on first sign-in or after sign-out: when there is no session it opens the native username/password form and never loads the web page. First-run server discovery (listing Movinite servers on the LAN) also needs the app: the 2.0 Setup screen has no network discovery. A source patch for app 2.0.2 (TV loads the web sign-in when signed out; Setup lists LAN servers; remote-friendly) is included with this release. It is not a signed APK — use the 2.0 app until a signed 2.0.2 build is issued. Typing a password on the TV web page is still available as a fallback.

**Schema stays 11.** A `pair_codes` table is created on startup (`CREATE TABLE IF NOT EXISTS`); there is no migrate() snapshot and no `pre-schema12` file. Library sharing in 2.1 can still use schema 12.


## 2.0.1 -- 2026-11-25
Builds on 2.0, plus D-pad control of the video player on a television:

- **The remote can reach every player control, including the settings gear at the bottom right.** In 2.0, Left and Right while a film was playing often landed on the full-width seek bar and then only skipped ±10 seconds, so Quality, Subtitles, Audio and Full screen on the right of the bar were hard or impossible to reach. Any key now shows the controls. Left and Right walk the current row (the centre Play / Skip buttons, or every button on the bottom bar, including the settings gear). Up and Down move between the seek bar and the button row (and the close button above). While the seek bar is focused, Left and Right still skip ±10 seconds. OK activates the focused control. Each control shows a purple focus ring.
- **The settings menu is navigable.** Opening Quality / speed, Subtitles or Audio focuses the current option. Up and Down move through the list (Left and Right move between the speed chips). OK selects; Back closes the menu and returns to the gear. The controls stay up while the menu is open or any player control is focused, so the overlay no longer hides mid-adjustment.
- **Back and hidden-control shortcuts.** When the controls are hidden, Left and Right skip ±10 seconds and OK pauses or resumes (and the controls appear). Back with the controls shown hides them; Back again leaves the player and returns to the details page with Resume or Play focused.

No database schema change. This release does not need a new migrate() snapshot.



## 2.0 -- 2026-11-25
Builds on 1.9.2 (TV remote navigation, TV details focus and the 1920-wide TV layout), plus offline downloads in the Android app (schema 11):

- **Download films and episodes in the Android app 2.0.** People with the **Viewer + Downloads** role (and admins) get a **Download** button on detail pages in the app. Pick a quality each time (**720p** is suggested; 1080p and 480p are made by the server; **Original** only when the phone can play the file as-is), and the audio track when there are several. Downloads continue in the background with a notification, resume after a dropped connection, and use Wi-Fi only unless you allow mobile data.
- **A Downloads tab** replaces My List in the app's bottom tabs: storage used and free, your quota, what's downloading (with pause, resume and cancel), what's ready to watch offline (with resume position), and anything needing attention. My List is still there as a Home row and in the account menu. Browsers don't change.
- **Watch offline.** Downloads are stored encrypted inside the app and play in its own player (Media3/ExoPlayer) with subtitles and resume. When the server can't be reached, the app opens an offline screen after you unlock it with your fingerprint, face or screen lock, or a Movinite PIN you set. Watch progress made offline is sent to the server at the next sync.
- **Licences you can take back.** Each download carries a licence signed by the server key, tied to that phone's own key, valid **30 days** and renewed whenever the app syncs (on launch and every few hours). A download is deleted at the next sync when it's removed from the server, the person loses access to the library or the download role, or the device is removed. If the app hasn't reached the server for 30 days, or on sign-out, it removes the offline profile and every download. This is trust-based protection for family and friends, not studio-grade DRM, and the app says so.
- **Server-prepared versions.** 1080p, 720p and 480p are transcoded on the GPU (VAAPI, also Quick Sync or NVENC when that's what Transcoding uses, otherwise CPU), one at a time, and pause whenever anyone starts watching, like the 1.8 background jobs. A finished version is kept in `data/offline` and shared by everyone who picks the same quality, up to a cache size you set (200 GB by default; oldest removed first).
- **Quotas.** By default each person can keep **20 titles or 100 GB**, on up to **3 devices**; admins are unlimited. Change the defaults in **Settings > Downloads** or per person (**Limits**).
- **Settings > Downloads** (admin): turn downloads on or off, the limits, licence and offline sign-in windows, the cache, the preparation queue, and every person's devices and downloads with **Revoke** and **Remove device**.
- **My account > Devices & downloads**: see and remove your own download devices and downloads from any browser, to free quota.
- **Activity** records devices set up and removed, download requests, prepared, started, finished, deleted, revoked and failed, with a **Downloads** filter.

- **Android app 2.0** (`movinite-android-v2.0.apk`, versionCode 8, same signing key as 1.5, installs over it): the downloads, offline screen and player above, plus the TV changes from 1.9.1 and 1.9.2 (remote focus, Back for the TV web app, the Movinite wordmark banner for the Android TV home screen at mdpi and xhdpi, and, on televisions, WebView text zoom pinned at 100% with a wide viewport so 4K sets show the 1920-wide layout instead of a zoomed-in page). Signing out in the app removes all downloads and tells the server to remove that device.

**Schema 11.** `update.sh` saves a checked copy of the database to `data/media-server.db.pre-schema11` before migrating (and still makes its usual backup). Rolling back to 1.9 works; the new tables are ignored.

## 1.9.2 -- 2026-11-25
Builds on 1.9.1, plus TV details focus, a 1920-wide TV layout, and a TV home-screen banner (app patch):

- **Opening a title on a television focuses Resume or Play.** In 1.9.1, OK on a poster opened the details page, then spatial nav focused the first Similar movies card and scrolled the play buttons off the screen. Up from that row jumped to the search box. 1.9.2 focuses the primary action (Resume if you were part-way through, otherwise Play) and keeps that section in view. Up and down move through the details in order: buttons, then season/episode or album tracks and cast if they are there, then Similar movies. Up from Similar goes back to the buttons; left and right move between the buttons; up from the buttons, or Back, closes the details and returns to the poster you came from. Search is not a vertical-nav target unless you are already at the top of the page (the sidebar or the top bar). The same pattern applies to TV show and music album pages, and closing the player returns focus to Resume or Play.
- **TV layout is no longer zoomed in.** Some Android TV WebViews (especially on 4K sets) report a CSS viewport of 960×540 or treat a 1920×1080 UI as magnified, so posters looked huge and only a few fitted on a row. In TV mode the page is laid out at 1920×1080 and scaled to `window.innerWidth` (not physical pixels), and Home / Similar posters are sized so about seven or eight fit on a 1080p-wide row. The purple focus ring stays. In TV mode, movie posters prefer the high-res (w780) artwork so they stay sharp on a 4K panel (typical WebView DPR 2), falling back to the regular 500–600 px thumb.
- No database schema change. Settings and libraries are untouched.

The Android TV home-screen tile (the wide banner) is not a server change: the installed 1.5 app has no `android:banner` or Leanback launcher. A source-only patch (banner + WebView zoom settings) is staged for app 2.0.


## 1.9.1 -- 2026-11-25
Builds on 1.9, plus TV remote navigation for the web app (and the Android 1.5 WebView):

- **TV mode (D-pad / spatial navigation).** The Android TV remote could move around the chrome, but it skipped the library list and the movie rows: those posters live in a horizontal scroller, and the WebView's built-in D-pad nav jumps over overflow rows. Library tiles and poster cards are now explicitly focusable (`tabindex=0`). 1.9.1 detects a television (the Android app's `isTv()` bridge, common TV user-agent strings, or the installed app / an Android WebView on a large screen — including when the UA still says `Mobile`) and turns the arrows into spatial focus. Left and Right stay inside a poster row (the row scrolls as you go; the row's own < > buttons are not D-pad targets). Right from the sidebar enters the first poster or library tile; Down from a row heading enters that row. A large purple focus ring follows the selection; OK / Enter opens the focused item; Back closes the player, a dialog, or goes back a page. Hover-only overlays stay visible on the focused poster. The player arrows move between Play, seek, quality and the other controls (Left/Right still skip when the seek bar is focused).
- No database schema change. Settings and libraries are untouched.

## 1.9 -- 2026-11-25
Builds on 1.8.1, plus invites, roles, per-library access, a device list, and Settings > Activity (schema 10):

- **Roles and per-library access.** Every account is an **Admin**, a **Viewer + Downloads**, or a **Viewer**, and non-admins can be limited to picked libraries. A limited user never sees the other libraries anywhere: library lists, Home, search, collections, playlists, recommendations, and direct links all answer as if the titles do not exist. Existing accounts keep what they had (admins stay admins; everyone else becomes a Viewer with every library). Plain file downloads stay admin-only; offline downloads for Viewer + Downloads arrive with the Android app 2.0.
- **Invite people by email.** Settings > Users > **Invite**: their address, a role, the libraries, an optional note, and an expiry (24 hours, 3 days, **7 days** by default, or 30 days). The invite link works once; only a hash of it is stored. The person opens the link, sees who invited them and what they will get, and picks a username and password. Pending invites can be resent (a new link), copied, or revoked. Sending a new invite to the same address replaces the old one.
- **Invites from your own email.** Settings > Email: enter your **Gmail address and an app password** (Google requires 2-Step Verification; the tab links to myaccount.google.com/apppasswords) and a **From name**, prefilled with your name (or your Google account's name when Movinite knows it). Invites go out through smtp.gmail.com (STARTTLS) with your Gmail address as From and Reply-To, so people know who sent it. **Send test email to myself** checks it. Other providers work too (SMTP server, port, STARTTLS / SSL/TLS / none, username, From address). The password is stored encrypted on the server and never shown again or logged. Clear messages for a wrong app password (535), "app password required" (534), rate limits (421, retried with backoff), Gmail's daily limit, and unreachable servers. Up to **20 invites an hour and 100 a day**. Without email set up, on an error, or past the limit, you get the link and a **QR code** to share yourself.
- **Advanced: Connect Gmail.** The Google sign-in (OAuth, send-only permission) option is still there under Settings > Email > Advanced, for hosters who prefer it to an app password; it needs a Google Cloud project (see `docs/gmail-setup.md`).
- **Signed-in devices.** My account lists every browser and phone signed in to your account (device, address, last active) with **Sign out** per device or **Sign out all others**. Admins can do the same for any user, and turn an account off without deleting it. Session tokens are now stored hashed, and existing sessions keep working after the update.
- **Settings > Activity.** A **Now playing** strip (who, what, direct or transcoding, which device, progress; admins can stop a stream) above a timeline of sign-ins, failed sign-ins, plays, invites, account changes, and library and settings changes. Filter by person, kind, date, or text, and export CSV. History is kept 90 days by default (30, 180, 365 days, or forever); IP addresses are blanked after 30 days and failed sign-ins are kept 30 days. Everyone can see their own activity under My account. The old Scan activity tab is now **Scans**.
- **Sign-in lockout behind a proxy fixed.** Behind Cloudflare and a reverse proxy every visitor looked like the proxy, so a few wrong passwords from anyone locked everyone out for 5 minutes. Movinite now uses the real client address from trusted proxies (Settings > System > **Trusted proxies**, or `MS_TRUSTED_PROXIES` in `.env`). When a private address sends forwarded headers without being trusted, System shows a one-click **Trust** hint.
- **Server key.** The server creates its own Ed25519 identity key (`data/secrets/server_ed25519`, owner-only) with a short fingerprint like `MOVI-ABCD-EFGH-JKLM`, used to encrypt secrets at rest now and for offline sign-in and server-to-server sharing later.
- Python package `cryptography` is now required; `update.sh` installs it.

**Schema 10.** `update.sh` backs up the database to `data/media-server.db.pre-schema10` before migrating and keeps `data/secrets` in its backups. Rolling back to 1.8.1 works, but signs everyone out once (old releases can't read hashed sessions).


## 1.8.1 -- 2026-11-25
Builds on 1.8, plus music playback, volume fixes, and frosted-glass chrome:

- **Play and Shuffle are on the playlist list and the playlist page.** You could already add playlists in 1.7.6, and the detail page had Play / Shuffle, but the playlist list (the first place you land after creating one) had no play control — only a card that opened the page. Those buttons were also easy to miss, and on a phone a tap on a track often started a drag instead of playing. The list now has Play and Shuffle on each playlist, the detail page uses the same themed play and shuffle icons as albums, and each track has a play button that starts the playlist from that song, in playlist order. On touch screens the row is no longer a drag handle, so a tap plays. Shuffle still uses a copy of the list, so the page order does not change.
- **Mute and a volume control you can actually use.** The music player had no mute button, and M only muted the video player. On a phone the volume slider was hidden on the mini bar and sat on the very bottom row of the full now-playing screen, where it is hard to drag. The slider now sits with the play controls, with a larger hit area, in the purple theme. A mute button next to it remembers the last volume and shows a muted icon; M toggles mute while music is playing. On a phone the mini bar shows mute plus a vertical volume popover that opens above the bar, so you are not reaching the bottom edge.
- **Frosted-glass chrome.** The top status bar, the mini music player, and the phone tab bar use the same translucent purple glass, blur, border, and inset highlight as the Server status popup. The mini player is a floating glass bar so the list can show through; the volume popover and equalizer use the same tokens. The full now-playing screen stays a solid page.

No database schema change.



## 1.8 -- 2026-11-25
Builds on 1.7.9, plus a themed Server status panel and background-cache yield:

- **Themed Server status.** The header pill and dropdown use the purple theme: a glass-dark pill, CPU and RAM ring gauges, a purple sparkline with a soft fill, and bars that stay purple at normal use and shift amber or red when high. Outlined icons mark disks and background work. Disk names wrap in full (with a tooltip) instead of being cut off. Sizes at or above about 1 TB are shown in TB.
- **CPU and RAM icons.** The header status control uses clear 18px outlined chip and memory-module icons (same 24px stroke language as the library icons, in `#B07CFF`) each followed by a compact percent, on desktop and phone — for example a chip + "3%" and a stick + "1%". The full RAM figure (e.g. "3.6 / 379 GB") is in the tooltip and in the dropdown panel, not on the toolbar. The icons sit directly on the header with no rounded border, fill, pill container, or usage bars. Hover or an open panel adds only a faint purple underline and a soft icon glow; the control stays clickable. The old sparkline and mini progress bars are gone from the toolbar. The dropdown panel still has the same icons centred in its CPU and RAM rings, with usage bars and the RAM figure kept on one line.
- **Share used space.** Some network shares report free space equal to their total size, so the bar looked empty even though the label said the share was entirely free. Those shares are now marked as "used space is not reported" and the bar is left empty instead of pretending the disk is unused or full.
- **Transcoding vs background work.** When nothing is playing, the panel shows the card that is ready, for example "Idle · GPU (VAAPI)", not "CPU". Background subtitle, remux, and opening-clip jobs are listed separately as "Background: N jobs (…)", so a cache job is not mistaken for a viewer transcode.
- **Background jobs yield to play.** Pressing play immediately stops an in-flight subtitle extract, remux probe, or opening-clip prefetch (they used to run to completion and could delay the first picture by a few seconds while they held the NAS). New cache work already waited until the stream was idle; this also interrupts the job that is running.

No database schema change. This release does not need a new migrate() snapshot.


## 1.7.9 -- 2026-11-25
Builds on 1.7.8, plus faster first picture (schema 9):
- **2-second HLS segments** with matching keyframes, so the first clip is about a third as long to make and to download. ffmpeg only restarts if the player jumps more than 60 seconds past what is already made (was a 4-segment, 24-second window that would have been too tight at 2 seconds). The pause-when-ahead logic now uses 150 and 72 seconds rather than a segment count, so the NAS still gets the same break.
- **ffmpeg starts when the playlist is requested**, not when the first segment is asked for, so encoding overlaps the player's next request.
- **Subtitles are cached.** A library scan or a low-priority idle job extracts them once. At play time the player is served from the cache, or gets a "try again in a moment" (HTTP 202) so a full-file extract never races the first video encode on the NAS.
- **Remux cut points are computed in the background**, in small NAS-friendly chunks. A missing or odd keyframe no longer marks the file as permanently un-remuxable; the plan can be partial and is retried later. Play itself never waits on this probe.
- **Rotation and HDR colour info are saved at scan time** and reused on play. Opening a movie from its details page reuses the item already loaded, and play is no longer blocked on the decoder probe.
- **Opening-clip cache.** While the server is idle and nobody is streaming, it pre-makes the first ~6 seconds (three 2-second clips) at 1080p for recently added titles and Continue Watching resume points. Size is capped (Settings → Transcoding, default 2 GB, oldest clips removed first). A matching play copies those clips in and starts ffmpeg after them.
- **The GPU encoder is warmed** with two black frames after the service starts, so the first movie after a restart is not a cold start.
- **Versioned app files** (JS, CSS, logos, icons, the manifest) carry long cache headers, and the service worker precaches them. API and HLS responses are not cached.

update.sh still writes a full code+database tarball first. migrate() also writes `data/media-server.db.pre-schema9` (mode 600) before the new tables.


## 1.7.8 -- 2026-11-25
Builds on 1.7.7, plus:
- **Quality is capped to the device.** The player reports the screen's longer side times `devicePixelRatio` (and, when the browser supports it, a `MediaCapabilities` 4K / 2K decode check for HEVC and H.264). The server clamps the chosen or saved quality so a 1920×1200 tablet (for example a Lenovo Tab TB311FU) gets 1080p even if 4K was saved earlier. Direct play and remux are offered only when the file itself fits that cap and the decoder can play it. The quality menu and the player stats show the effective quality, for example "Auto-capped to 1080p". Settings → My account has a "Cap quality to this screen" switch (on by default) if you want to allow a higher quality on this device. The Android app is unchanged: its JS bridge has no MediaCodec list, so the cap uses the screen size and `MediaCapabilities` only.
- **Transcode pause works again after old segments are deleted.** ffmpeg is supposed to pause (`SIGSTOP`) when it is more than 25 segments ahead of the player, so the NAS and the GPU get a break. After the first few minutes of a long film, housekeep deletes segments older than the playhead, and `highest_done()` then started counting from a now-missing first segment and returned -1, so the pause never fired again (seen in the 25 Nov 2026 two-device 4K test around 8:50 AM MST). It now finds the remaining contiguous run. Re-fetching a segment that is already on disk also no longer resumes a paused ffmpeg.


## 1.7.7 -- 2026-11-25
Builds on 1.7.6, plus:
- **Two 4K transcodes stay on the GPU.** Playing two 4K HEVC 10-bit films at once could exhaust VAAPI surfaces (the ffmpeg log was only "ffmpeg exited"). The player then restarted the same GPU attempt, so the stats badge flipped between CPU and GPU, and a full-stage failure could drop the stream to CPU decode (or, after a later encode failure, park the card for 10 minutes for everyone). The hardware path now passes `-extra_hw_frames 64` and `-low_power 1` (the Arc A310 only exposes the low-power / VDENC encoder, which is also what Plex uses). HDR10 / HLG uses `tonemap_vaapi` when ffmpeg has the filter, otherwise `scale_vaapi`. A fallback is sticky for that stream, with the reason logged, and no longer disables the card for other devices. A later seek or playlist reload of the same stream resumes at the stage that actually works. The VM is unchanged (`hw_transcode` off, libx264).
- **Same account, two devices.** A transcode is limited per player (browser or app), not per login, so two devices signed in as the same user can watch at once. Switching title or quality on one device only replaces that device's session. There is a server-wide cap (default 4, change it under Settings > Transcoding or with `MS_MAX_TRANSCODES`). Hitting the cap is logged and the oldest idle session is evicted.
- **ffmpeg errors stay visible.** ffmpeg is run at loglevel warning, and when it exits with an error the last 50 lines of `ffmpeg.log` are copied into the journal with the session id before the session directory is deleted. Session destroy is also logged with a reason (idle, client close, replaced, cap, error, shutdown).
- **No more restart loops.** After an unexpected VAAPI/NVENC exit the same hardware stage is retried once (after a short backoff). If it fails again, that stream falls back stickily with the logged reason and does not bounce back to the failing stage.
- **Prefer direct play or remux, like Plex.** Auto quality no longer starts a 4K-to-4K transcode just because a 2K/4K quality was saved earlier. If the device can play the original codec, Movinite uses direct play or remux (copy the video, convert only the container/audio). HEVC (including 10-bit) in MKV/MP4 can now be remuxed to fMP4 when the player reports HEVC support (hls.js cannot play HEVC in MPEG-TS). Each player sends a device id and codec capabilities (HEVC MSE, Main10, MKV, AC3) with the playlist request, and those are logged.


## 1.7.6 -- 2026-11-25
Builds on 1.7.5, plus:
- **Themed now-playing chrome.** The equalizer and close (X) buttons in the full music player use the same rounded-square, purple-accent style and the outlined 24px-grid icon language as the 1.7.4 library icons. Previous and next are the same brightness (mirrored SVGs, shared colour and disabled opacity). A matching add-to-playlist button sits with them.
- **Top controls auto-hide.** In the full now-playing view, the top-right close button (and the rest of the top chrome: back, add, visualizer toggle, equalizer) fade out after about 3 seconds with no interaction. A tap or touch brings them back with a short fade. The mini player at the bottom of the screen keeps its close button visible.
- **Beat-reactive visualizer, mixed with the logo.** A radial frequency ring is drawn around the album art with `requestAnimationFrame`, using a Web Audio `AnalyserNode` tapped off the existing equalizer graph (one AudioContext, no second `createMediaElementSource`). The bars use a slowly rotating gradient in the theme purples (`#9637FA`, `#6A16C4`, `#D4BBFF`, magenta, indigo), with bass warmer and brighter, highs lighter, and a soft glow on the bars. A faint matching wash stays on the ring (not a busy page background). The art pulses on bass-energy beats. When a track has no artwork, a smaller transparent Movinite logo floats in the middle of the ring with no square tile. The animation pauses when the full player is closed, the tab is hidden, or the screen is off; it respects `prefers-reduced-motion`; and it can be turned off from the top chrome (saved on this device).
- **Playlists.** You can create, rename and delete playlists, add a track from a track list (plus button or long-press) or from now playing, remove and reorder tracks, and play or shuffle a playlist. Playlists are stored per user on the server (schema 8, `/api/playlists`, login required). A Playlists section is in the Music library (Albums / Tracks / Playlists) on phone and desktop. The migration takes a one-time snapshot of the database (`media-server.db.pre-schema8`, mode 600) before creating the new tables, and is safe to run more than once.


## 1.7.5 -- 2026-11-25
Builds on 1.7.4, plus:
- **Pinch to fill the picture on a phone.** In the video player you can pinch out to zoom the picture so it covers the whole screen (`object-fit: cover`) and pinch in to fit the whole picture (`contain`). The choice is remembered on this device. Fit / Fill is also in the Quality (gear) menu. The player tap layer no longer uses `touch-action: manipulation`, which was blocking pinch gestures in the Android WebView; double-tap left/right still skips 10 seconds.
- **Captions come up promptly and stay on.** Turning subtitles on used to wait for a `<track>` element that was often dropped when the HLS stream (or a quality change) replaced the video source, and the first ffmpeg conversion of an embedded track can take a while, so cues appeared late or vanished on seek. The player now fetches and caches the WebVTT (with the login cookie), paints a custom overlay, prefetches tracks when the film starts, and re-applies them after an HLS attach, a quality change, and on seek. A short "Loading subtitles…" hint shows until the file is ready.
- **Captions are see-through.** Native `::cue` and the custom overlay use a light translucent box (`rgba(0,0,0,0.25)`) and white text with a strong black outline, so they stay readable on bright scenes without the old opaque black caption bar. The custom overlay is the Android WebView fallback, because WebView often ignores `::cue` (and the cue backdrop).
- **Server status in the player is a glass panel at the top.** It sits under the title bar, centered, as a compact 2×2 grid (CPU and RAM with small bars, GPU/encoder status, and dropped frames) on a blurred translucent background, and still fades with the other controls so it does not sit on the title on a phone. The **GPU** badge stays the solid purple pill.


## 1.7.4 -- 2026-11-25
- **Outlined library icons in the purple theme.** The emoji used for Movies, TV Shows, Music and
  Other videos (and the share / this-server heading marks) are replaced by the outlined 24px-grid
  SVG set chosen from the 1.7.3 icon preview. They use `currentColor` and the theme accent
  (`--acc-text`, `--acc`) so they match the tab bar and the rest of the chrome. They appear in the
  Libraries tab (phone and desktop), the sidebar, library page headings, Settings -> Libraries,
  Scan activity, and the Add library type picker. Cache-busting is stamped `?v=1.7.4` (including
  `sw.js`) so phones pick up the new icons on the next load.


## 1.7.3 -- 2026-11-24
Builds on 1.7.1, and includes the unreleased 1.7.2 phone work, plus:
- **Fix match now really changes the poster when the movie's folder has artwork from an old match.** A poster.jpg
  next to a movie wins over the TMDB poster. When Media Server had saved artwork (poster.jpg + movie.nfo) for an
  earlier, wrong automatic match, that poster stayed after you fixed the match -- e.g. "Adore (2013)" kept the
  poster of "Je t'adore" after being matched to Adoration. Now, when the folder's .nfo names a different TMDB film
  than the current match, the folder poster is set aside and the TMDB poster of the match is shown (cards, details
  page incl. the large poster, home rows, search). Matching back to the .nfo's film, unmatching, or a folder with no
  .nfo / a matching .nfo keep showing the folder poster as before. Nothing in the folder is changed.
  - New columns `items.art_poster` / `items.art_tmdb`; libraries from before 1.7.3 are checked once in the
    background after start (reads the small .nfo files only, skips shares that are not online).
  - Fix match re-reads the .nfo of every version and copy, so it takes effect at once.
- **Artwork saving replaces its own leftovers.** With "Save artwork" on (and the share allowed to write), a
  poster.jpg / fanart.jpg / movie.nfo that Media Server/Movinite itself wrote for a *different* TMDB film is
  rewritten for the current match even without "Overwrite". Files written by other tools are never touched.
- **Phone Libraries tab, kept simple.** The Collections, Recommended, Recently added and Top movies chips
  under each movie library are gone, so every library is just its card -- the same as TV, Music and Other.
  The list is still grouped under your share headings (Sunset Server, Waimea Server, ...) and movie libraries
  still say how many films they hold (1,967 movies), not how many files.
  (Those two were already in 1.7. If the phone still showed a flat list and "2,022 items", it was keeping an
  older copy of the page; see cache-busting below.)
- **The mini music player no longer covers the last library.** On phones, every page leaves room for the
  player and the tab bar, so you can scroll Music (and anything else) fully into view.
- **The phone mini-player progress bar stays on the screen.** The bar used to be one crowded row, so on
  a 360–430 px phone the slider ran off the right edge and the end time disappeared. It is now two rows:
  title and controls on top, elapsed time, slider and total time on the row below, all inside the player.
  Dragging the slider still seeks. The full-screen video player's seek bar already fits the width of the
  phone. When Picture-in-Picture is available, the extra button used to push the last controls off the
  right edge on a 360 px screen; the time now sits on its own line under the seek bar so every button
  stays on screen.
- **Phones pick up an update the next time they load the page.** The page itself is never stored; `app.js` and
  `style.css` URLs include the version (`?v=1.7.3`); a request for an old URL (`?v=1.6`) is not cached, so the
  phone revalidates and gets this release. A small service worker (`/sw.js?v=1.7.3`) also fetches the page and
  those files from the network. After installing, use the Android app's **Reload** shortcut if the Libraries tab
  still looks like the old one; no new APK is needed (the app is a WebView of this page).
- **Previous and next match the purple theme.** The mini player's back and forward buttons were Unicode
  glyphs (often drawn as a default white or system emoji, so they ignored the theme colour). They are now
  the same SVG style as the rest of the app, in the purple accent, with hover, active and disabled states.
  The play button matches. The video player's skip-back / skip-forward buttons already used SVGs; their
  hover state now uses the same purple tint. Playback itself is unchanged.
- **Music equalizer.** The now-playing view (tap the artwork or title; on a computer the EQ button is also
  on the mini bar) opens a 10-band equalizer (32 Hz–16 kHz, ±12 dB) built with the Web Audio API, plus an
  on/off switch, a reset button, and presets: Flat, Bass Boost, Treble Boost, Vocal, Rock, Pop, Jazz,
  Classical, Dynamic and Custom. Dynamic is a loudness-style curve (+6, +5, +3, 0, −2, −2, 0, +3, +5, +6 dB)
  with a gentle compressor and modest makeup gain so it stays loud without clipping. Settings are saved on
  this device. The AudioContext starts on a tap so it works in the phone layout and the Android app. Only
  the music player is connected; video is left alone. Streams stay on this server, so hooking up the
  equalizer does not silence playback.


## 1.7.1 -- 2026-11-24
Builds on 1.7, plus:
- **Poster updates when you Fix match.** On a movie that needed review, picking the right TMDB film (Fix match or
  Accept suggestion) now refreshes the poster on the details page and on every card for that film. Two things were
  getting in the way:
  - The big details-page poster is loaded from `/api/items/{id}/poster-large`, a URL that did not change when the
    match changed, and the browser was told to cache it for a week -- so it often kept showing the old (or
    placeholder) image. The URL now includes the poster file (`?v=...`), so a new match is a new URL.
  - Only the file you had open was updated. A 1080p version of the same film, or the copy on the other share, kept
    the old match and the old poster. Fix match / Accept / Automatic / Use file name now apply to every version and
    copy of that title.


## 1.7 -- 2026-11-24
Builds on 1.6, plus:
- **Side menu grouped by network share.** Libraries are listed under a heading per share (its name, with the
  share's status dot on the heading); folders on the server itself get their own group, "This server". Each
  library stays separate -- nothing from two shares is merged into one library. A library only gets its own dot
  when its state differs from its share (e.g. its folder is missing). Same grouping on the phone Libraries tab
  and in **Settings -> Libraries**, where the arrows on a share's heading move the whole group and a library's
  arrows / drag and drop move it within its group. **Rename** on a share's heading changes the name shown (new
  `PUT /api/shares/{id}/name`); the share's address, login and write setting are not touched.
- **The same film on two shares is shown once** in the views that span libraries:
  - **Home page:** libraries of one type holding (mostly) the same titles -- at least half of the smaller one --
    are treated as mirrors and get ONE section, from the first of them (library order) whose share is online,
    marked "same films as <other library>". A library with different films keeps its own section.
  - **Continue watching, My List, search** (films, shows, episodes, albums): each title once.
  - **Watch progress is kept on every copy and version** of a title (both shares, 4K and 1080p), so it resumes
    wherever it is played; "Mark watched" does the same. On the first start of 1.7, existing progress is copied
    to the other files of the same title that have none (inserts only -- no existing row changes).
  - **A share goes offline:** those views switch to the copy on the share that is online; a details page on the
    offline share says so and **Play** uses the online copy.
  - "Same title" = the same TMDB film (+ edition, so a Director's Cut stays separate); unmatched films by title +
    year; episodes by show folder + season + episode.
- **Versions: highest resolution first.** Several files of one film in a library (e.g. `Heat (1995) - 2160p.mkv`
  and `Heat (1995) - 1080p.mp4`) are now ONE poster, always ordered 4K > 2K (1440p) > 1080p > 720p > SD, then
  bitrate, then file size; the poster opens and plays the best one. Same for the home rows (Recommended, Top
  movies, Recently added, genre rows used to pick the first file found), Similar movies, an actor's films and two
  files of one episode on a show page. Movie libraries count films, not files ("1,965 movies"; the files are in
  the tooltip); collections and genre counts too.
  - **Poster badge:** "4K" (or "2K") on 4K/2K films; "+1", "+2" when there are more versions (tooltip lists them).
  - **Version picker** on the details page lists the versions best first (resolution, codec, bitrate, size);
    picking one opens and plays that file as-is.
  - **When the best version is not played:** your saved player quality is a transcode size (e.g. 720p) -> the
    smallest version still at least that big is used (same picture, less work); or the server has no GPU 2K/4K
    transcoding and this browser can't play the 4K file as-is -> a smaller version it can play directly is used
    (a short note says which). With GPU transcoding on (the Arc server) the 4K file plays as before.
- Database: schema 7 (an index on `items.tmdb_id`; the progress copy above). No columns removed, nothing deleted.
  `update.sh --rollback` restores 1.6. The shares' write settings are unchanged.

## 1.6 -- 2026-11-24
Builds on 1.5.5, plus:
- **Version numbers:** two parts from now on (1.6, 1.7, ...); a third digit only for quick fixes (1.6.1).
  update.sh compares numerically (1.5.5 < 1.6 < 1.6.1), and picking the newest tarball uses `sort -V`, which agrees.
- **Libraries in your order.** Admins arrange the libraries in **Settings -> Libraries**: drag a row by its handle
  (desktop) or use the up / down arrows (touch screens and phones). One order for everyone; it is used in the side
  menu, the phone Libraries tab, the home page rows, Settings and the Android app (`GET /api/libraries`). New API:
  `PUT /api/libraries/order {"ids": [...]}` (admins).
- **Default order by type:** Movies, TV Shows, Other videos, Music (types `movies`, `tv`, `other`, `music`; any other
  type goes last). On the first start of 1.6 existing libraries are ordered that way (then by name). A library you add
  later goes right after the last library of its type (with none yet: just before the first library of a later type),
  without changing the rest of your order. Database: new `libraries.sort_order` column (added automatically).
- **Settings tabs** left to right: Libraries, Scan activity, Poster Sounds, Metadata, Transcoding, Users, My account,
  System. Viewers see Poster Sounds and My account in that order. Settings opens on the first tab you can see.
- **Share status dot.** Libraries on a network share (SMB / NFS) get a dot after their name in the side menu and on
  the phone Libraries tab: green online, amber slow or not answering, red offline (not mounted, folder missing, error),
  grey while the first check runs. Hover for details, e.g. "Share online · checked 12s ago" or "Share offline: share
  not mounted". Local-folder libraries get no dot. The server checks every 45 s in the background (and on demand,
  `POST /api/libraries/health`); each check lists the folder in its own thread with a 3 s limit, so a hung share can
  never stall the server, and `GET /api/libraries` now uses the cached result for share libraries (it used to touch the
  share on every request). The check never remounts anything; the existing share watchdog is unchanged.

## 1.5.5 -- 2026-11-24
Builds on 1.5.4, plus:
- **Artwork for TV shows.** *Save artwork to folders* now works for TV libraries: the show poster (`poster.jpg`),
  season posters (`season01-poster.jpg`, `season-specials-poster.jpg`), optional `fanart.jpg`, `tvshow.nfo` and
  episode thumbnails (`<file>-thumb.jpg`, new *Episode thumbnails* switch) go into each matched show's folder.
  Open it from **Settings -> Libraries -> Artwork** (all shows) or the new **Artwork** button on a show page
  (admins, desktop and phone) with **Write for this show**. Dry-run preview, never overwrites unless asked, and
  newly matched shows get artwork automatically when *Save automatically* is on (also after Fix match). Season
  posters cost one TMDB request per show. Your own `poster.jpg` in a show folder is kept on rescans.
- **Poster Sounds tab.** The interface sounds have their own Settings tab, *Poster Sounds* (for viewers too); My
  account links to it. The speaker button and account menu say "Poster sounds". Saved settings carry over.
- **Home page: Movies and TV only.** Continue watching and the Recently added rows (web, phone, Android app and the
  My List in-progress list) leave out music, home videos and other libraries. If that leaves the home page empty
  it points to Libraries.

## 1.5.4 -- 2026-11-24
Builds on 1.5.3, plus:
- **Sharper 2K / 4K in H.264 from HEVC, AV1 and VP9 films.** H.264 needs roughly 1.5-2x the bitrate of those codecs
  for the same picture, so the 1.5.3 cap (1.2x the source) made a 6.7 Mbps HEVC 4K film a soft 6.4 Mbps H.264
  stream. For such sources the H.264 average is now **1.8x the source**, at least **12 Mbps for 4K** and
  **8 Mbps for 2K**, and never above the profile ceiling (4K 25 Mbps / 2K 12 Mbps peak). Peak (`maxrate`) is
  1.25x the average and the buffer 2x the peak. Example, The Return of the King (HEVC 6.7 Mbps): 4K
  6.4 -> 12.0 Mbps average (15 peak), 2K 9.6 Mbps average (12 peak). H.264 sources, HEVC output and 1080p and below
  are unchanged. The GPU (VAAPI / QSV / NVENC) and CPU paths use the same numbers; the CPU fallback of a 2K/4K
  stream (1080p) no longer shrinks its rate a second time for wide-screen films.
- **Dropped frames in the player.** The see-through status pill (top right, shown with the controls) now ends
  with `Dropped N / total`: the video frames this browser dropped and showed since the stream started, amber
  from 1 %, red from 5 %. Everyone sees it (the CPU/RAM part is still only for people allowed to see server
  status). Many dropped frames mean the device or display can't keep up, not the server or network.
- **HLS segments start on time.** MPEG-TS segments used to start ~1.4 s after their playlist time (the muxer's
  default delay). They now start exactly on it (`-muxdelay 0 -muxpreload 0`), on every run after a seek too.
  HEVC (fMP4) segments and remux are unchanged.
- Tip for jumpy film playback: 24 fps films judder on a 30 Hz display. Use 60, 72 or 24 Hz (72 and 24 are smooth).

## 1.5.3 -- 2026-11-24
Builds on 1.5.2, plus:
- **Tidier library pages on phones** (<= 820 px, browser and Android app; the desktop is unchanged, checked
  pixel by pixel), laid out like the Plex app:
  - **Header:** the title and a grey count (`N of M` while filtered), then icons for search, filters (with a badge
    showing how many are on) and sort, plus a ⋯ menu for admins with *Select movies to tag* and *Scan library*.
  - **Categories** (All / Top / Collections / genres...) sit in one row you swipe sideways.
  - **Filter sheet:** a bottom sheet with chips for genres, decade, rating, tag and show (plus sort, and the view for
    music). *Apply* and *Reset* buttons; it closes on the backdrop, Esc, the Back button or a drag down.
  - Active filters show as removable chips, and the grid has 3 columns.
  - TV, music, smart and collection pages get the same header.
- **2K and 4K quality.** With hardware transcoding on, the player's quality menu adds *4K (2160p)* and
  *2K (1440p)*:
  - Only sizes up to the source are offered, never upscaled. A 3840x1600 scope film counts as 4K and stays
    3840x1600; 2K of it is 2560x1066.
  - On servers without a video card both entries are shown greyed out ("needs GPU transcoding") and the API
    answers 409.
  - The default quality is still 1080p or direct play.
  - **HEVC** is used when the device can play it (`hvc1` support, e.g. Safari, Edge, Android TV/phones with HEVC);
    otherwise H.264. HEVC is sent as fragmented-MP4 HLS, because hls.js can't play HEVC in MPEG-TS. If HEVC fails
    on a device, the player steps down to H.264 at the same size by itself, then to 1080p.
  - **Bitrates:** H.264 4K 25 Mbps / 2K 12 Mbps; HEVC 4K 16 Mbps / 2K 8 Mbps. They are capped at 1.2x the
    source's bitrate (minimum 6 Mbps), so a 7 Mbps 4K file is sent at about 8 Mbps instead of 25.
  - **HDR:** HDR10/HLG films are converted without tone-mapping, so colours can look flat. The player's status
    says so.
  - **Preliminary benchmark on the Arc A310** (a short read-only run; the full test is deferred): up to **6 x 4K, 10 x 2K or 12 x 1080p**
    simultaneous transcodes with >= 10 % headroom, in H.264 or HEVC, using about one CPU thread per stream.
    HEVC 10-bit/HDR10 decoding runs on the card. The full table is in the README.
- **Add library -> Existing connection.** When a share has already been set up, *Add library* offers *Existing
  connection* first. It lists the shares (server + share, the SMB username, which libraries use them; never the
  password), next to the usual *Folder* / *SMB* / *NFS* choices.
  - Pick one and press **Browse**: the folder picker opens straight on that share. There is no login to type.
  - Go **Up** to see every share on that server and browse any of them with the same login.
  - The password never comes back to the browser. The root mount helper reads it from the root-only credentials
    file, using the new helper actions `add-as`, `browse-as` and `shares-as`.
  - **The same share** (or a folder in it): the new library uses the existing mount; nothing is mounted again.
    The mount is removed only when the *last* library using it is deleted.
  - **Another share on the same server:** a new mount, and the helper copies the login into that share's own
    credentials file. Deleting either library never breaks the other.
  - Changing a login later (Edit share) applies to every library on that one share, not to copies made for
    other shares. A saved login can't be used for a different server.
  - Admin only (`GET /api/connections`; `/api/browse` and `POST /api/libraries` accept
    `{"type": "existing", "share_id": N, "remote": "//server/share"}`).
  - Listing the shares of a server needs `smbclient` on the server, as before; if it is missing, type
    `//server/Share` in the Share field.
- No database schema change. Rollback works as before.

## 1.5.2 -- 2026-11-24
Builds on 1.5.1, plus:
- **Hardware transcoding on a video card.** Videos that have to be converted (HEVC, 10-bit, AVI, ...) can now be
  encoded on the GPU: **VAAPI** (Intel incl. Arc, AMD), **Intel QSV** and **NVIDIA NVENC**. Each stream first tries
  the full GPU path (GPU decode + scale + H.264 encode; phone videos are rotated on the GPU), then CPU decode +
  GPU encode, and finally the CPU (libx264, as before). The switch happens by itself within a few seconds (a run
  that exits without output, or makes no segment in 20 s) and is written to the log; after a stream had to go all
  the way back to the CPU that method is paused for 10 minutes. Same 6-second HLS segments, qualities and seeking.
- **Settings -> Transcoding (admins):** Hardware transcoding = Auto / Intel QSV / VAAPI / NVIDIA NVENC / Off (CPU),
  which video card to use, the detected cards (PCI id, driver, render node, methods; e.g. the Matrox BMC chip shows
  "no video encoder"), a **Test** button per method (a 2 s 1080p -> 720p encode, shows passed + fps or the ffmpeg
  error and the fix), **Scan for video cards again**, what is in use now, who set it up (install / first start /
  you) and the last fallback. Auto tries VAAPI, then QSV, then NVENC. New admin-only API: `GET/PUT /api/hw`,
  `POST /api/hw/test`, `POST /api/hw/scan`.
- **GPU badge:** while a stream runs on the card the server-status pill shows a purple **GPU** badge (a purple ring
  around the dot on phones), the status popover gets a "Transcoding: GPU VAAPI - 1 stream" row, the player's status
  pill shows GPU, and Settings -> System lists each stream's encoder.
- **install.sh** (new step 7) scans for video cards (sysfs / lspci, /dev/dri, nvidia-smi), installs the drivers best
  effort -- Intel: intel-media-va-driver-non-free (or intel-media-va-driver), vainfo, libvpl2, libmfx-gen1.2; AMD:
  mesa-va-drivers, vainfo; NVIDIA: a hint to install the driver if nvidia-smi is missing -- adds the service user to
  the video + render groups, runs a test encode and saves the first method that works (or Off) in Settings. It never
  fails the install. The logic lives in the new `hwsetup.sh` (shared with update.sh).
- **update.sh** does the same scan only when nothing is saved yet; a value saved by install or in Settings is never
  changed ("kept your setting"). Servers updated with an OLDER update.sh (1.5.1 and before, e.g. now) get the scan at
  the **first start of 1.5.2** instead (no package installs then; the GPU server already has the VAAPI driver).
- Machines without a video card (the VM) stay on the CPU exactly as before (setting saved as Off).
- Verified on the real Arc A310 (ffmpeg 6.1.1, iHD 24.1): VAAPI full and CPU-decode paths, incl. a 4K60 phone video
  (rotated) -> 1080p using ~2 s of CPU per 30 s of video instead of ~70 s with libx264. Two fixes came from that:
  single-threaded GPU decoding (otherwise the last ~15 frames failed at the end of a file) and GPU rotation.
- `MS_HWACCEL` in .env (decode-only, experimental since 1.0) is superseded by the setting; it is still honoured on
  the CPU path. No database schema change (three new rows in settings). Rollback works as before.

## 1.5.1 -- 2026-11-24
Builds on 1.5.0, plus:
- **Phone layout like the Plex app.** On phones and small tablets (<= 820 px, browser and Android app) the menu
  button is replaced by a fixed **bottom tab bar** (icon + label, 62 px + the phone's safe area): Home, Libraries,
  Search, My List, Settings (Account for non-admins); the active tab is Movinite purple. It hides while the player is
  open (back when the film is minimised to PiP or closed); the audio bar, PiP chip and messages sit above it.
- **Slim top bar on phones:** M logo, a search icon (opens the Search tab, which has its own search box), the
  server-status dot (tap = CPU / RAM, as before) and a round avatar with your initial. Tap the avatar for
  My account, Settings, Interface sounds on/off and Sign out (closes on a tap outside, Esc / Back or navigation).
- **New Libraries tab** (each library with its item count, plus Collections / Recommended / Recently added / Top
  movies) and **My List tab** (Continue watching + Watched, newest first) backed by the new `GET /api/mylist`
  (signed-in users, 401 otherwise; it shares the continue-watching query with /api/home).
- **Home rows on phones:** bold 21 px titles with a ">" that opens the full list, the library (or library + count)
  in gray underneath, about 2.3 posters across (swipe), 8 px rounded posters, title + year under each poster, a thin
  rounded progress bar inset at the bottom and a check in a dark square for watched films.
- **Row arrows:** hidden on phones under 600 px wide (swipe instead), small (34 px) and subtle on tablets
  (600-820 px). In 1.4.9 they were 44 px on phones; this follows the Plex layout you asked for.
- **Desktop unchanged** (pixel-compared against 1.5.0: only the version label differs).
- **Android app 1.5** (`movinite-android-v1.5.apk`, versionCode 6, same package + signing key, installs over 1.4):
  the native Sign in screen now matches the web sign-in page -- the full Movinite logo with the MOVINITE wordmark
  (300 dp, in the card), the purple glow on near-black, the translucent card with the purple border, the same
  fields (purple border when focused) and the full-width purple button; max 380 dp wide on tablets / landscape.
  Back closes the phone account menu. Gear (Server settings), PiP and rotation unchanged. Launcher icon / splash
  stay the M mark without wording.
- No database change; install.sh / update.sh unchanged. Update and rollback work as for 1.5.0.

## 1.5.0 -- 2026-11-24  (Movinite)
Builds on 1.4.13, plus:
- **New name: Movinite.** The web app, sign-in page, browser tab, home-screen icon, installer / updater messages and
  the Android app are now called Movinite and use the official Movinite logo: the full logo on the sign-in page,
  a compact M + MOVINITE logo in the menu, the M mark in the phone top bar, and the M as favicon (16/32/48 + .ico),
  Apple touch icon and installable-app (PWA) icons (incl. a maskable one). The app can be added to a phone's home
  screen. **Behind the scenes nothing is renamed:** the service is still `media-server`, the folder
  `/opt/media-server`, the port 8099, the tarball `media-server-verX.Y.Z.tar.gz`, so updates and rollback work as before.
- **Purple theme.** The accent colour is the logo's purple (#9637FA); buttons are #8424EA with white text (6.1:1,
  WCAG AA), purple text on the dark panels is #B07CFF (>= 5.9:1). Warnings and errors stay amber / red.
- **Browse a share's folders in Settings -> Libraries.** Add library -> SMB / NFS / Local folder now has a
  **Browse** button: after entering the share login it lists the server's shares, then the folders (with the number
  of videos in each), and you click through and **Select** the media folder instead of typing the sub-folder.
  Wrong password, unreachable server, missing share and "access denied" are shown as plain messages, with
  "Edit the login" / "Try again". Edit library has the same browser ("Change folder", rescans afterwards).
  Works on phones (full-screen sheet, big rows) with the see-through look. The library type is suggested from the
  folder name (Movies / TV Shows / Music). Admin only; the login is never logged or sent back; ".." and other
  escapes are refused; browsing never changes existing mounts. SMB is browsed with `smbclient` (new dependency,
  installed by install.sh and, best effort, by update.sh); NFS (and SMB without smbclient) via a temporary read-only
  mount by the mount helper.
- **Turn the phone sideways = full screen.** While a film plays on a phone or tablet, turning it sideways makes the
  player full screen and turning it upright leaves full screen. If the browser refuses full screen without a tap,
  the player fills the screen anyway and the next tap makes it real full screen. Leaving full screen by hand is
  respected until the next rotation. Never on desktop.
- **Android app 1.4** (`movinite-android-v1.4.apk`, installs over 1.3, same signing key): called Movinite, purple,
  the M logo (no wording) as launcher icon (adaptive + themed), on the Sign in screen and the splash. While the player
  is open the app follows the phone's rotation: sideways hides the status and navigation bars (immersive full
  screen), upright brings them back.
- No database change. Updating from 1.4.12 or 1.4.13 keeps all data; `update.sh --rollback` restores the previous
  version. The share's write setting is unchanged.

## 1.4.13 -- 2026-11-24
Builds on 1.4.12, plus:
- **New bottom control bar in the player.** The browser's own controls are replaced by the player's bar, so Quality,
  Subtitles and picture in picture sit at the bottom as their own buttons (not inside the ⋯ menu):
  - left: play/pause, -10 s, +10 s, volume / mute (remembered), current / total time;
  - right: **Quality** (gear + current choice, e.g. "Original" or "720p"; the menu also has playback speed
    0.5×-2×), **Subtitles** (CC; lit while subtitles are on; language codes shown as names, e.g. "English (en)"),
    **Audio** (only for films with more than one audio track), **PiP**, **Full screen**;
  - above them a seek bar with the buffered range, a draggable knob and the time under the mouse. Seeking works for
    direct play, remux and transcoded (HLS) streams and saves the resume point.
  - The top bar keeps only close and the title.
- **See-through look.** No solid bar: a soft gradient from clear to 45% black at the very bottom, buttons as
  translucent blurred circles / pills with white shadowed icons (like the status pill and the round skip buttons),
  menus as frosted glass, and text shadows so labels stay readable on bright scenes.
- Everything fades with the overlay ~3 s after the last tap / mouse move / key, and stays while a menu is open, while
  dragging the seek bar or while paused. A click beside an open menu just closes it. Esc closes a menu first.
- Subtitles move up above the bar while it shows and drop back when it fades.
- Works in full screen, on phones (compact icons, 44 px targets, menus as bottom sheets) and in the Android app
  (hidden in Android's PiP window). New key: m = mute. The empty status label no longer shows as a dark dot.
- No database change. Updating from 1.4.11 or 1.4.12 keeps all data; `update.sh --rollback` restores the previous
  version. The share's write setting is unchanged.

## 1.4.12 -- 2026-11-24
Builds on 1.4.11 (on-screen skip buttons and the see-through status pill), plus:
- **The player's top bar fades away too.** The close button, the title, the Original / quality picker, the audio and
  subtitles pickers and the full-screen button now float over the picture and fade out together with the round
  buttons and the status pill: about 3 s after the last tap, mouse move or key press while the film plays. They
  come back on a tap, a mouse move or any key, and stay while the film is paused. The fade is smooth, and hidden
  controls can't be clicked by accident, so a tap on the picture always just brings them back. Works the same in
  and out of full screen, on desktop and on phones.
  - The bar stays up while you use it: while a picker's list is open or focused, or while the mouse rests on the bar.
  - On desktop the mouse pointer disappears with the controls and comes back when you move the mouse.
  - The see-through status pill sits just under the bar, whatever its height (it wraps to two lines on phones).
- **Picture in picture.** A new PiP button in the top bar (or the P key) pops the film out into a small
  always-on-top window (Chrome, Edge, Safari, Chrome on Android).
  - The player steps aside so you can keep browsing the library. A small bar at the bottom right shows what's
    playing, with **Back to player** and **✕** (stop and close).
  - Closing the PiP window with its own buttons brings the full player back. Closing the player, or starting
    another film, ends PiP cleanly.
  - Playback, the resume point and transcoded (HLS) streams keep working in PiP. Interface sounds stay silent while
    a film plays in PiP, and the player's keyboard shortcuts leave the page alone while you browse.
  - Firefox has no PiP option for web pages. There the button explains Firefox's own PiP (Ctrl+Shift+], or
    Cmd+Option+Shift+] on a Mac, or the PiP toggle on the video). Where PiP isn't possible at all, the button is hidden.
  - In the Android app (v1.3 or later) the button uses Android's own picture in picture, and pressing Home while a
    film plays does the same. Older app versions simply don't show the button.
- No database change. Updating from 1.4.10 or 1.4.11 keeps all data; `update.sh --rollback` restores the previous
  version. The share's write setting is unchanged.

## 1.4.11 -- 2026-11-24
- **On-screen skip buttons in the player.** Tap (or click) the picture while a film plays and three large round
  buttons appear in the middle: **↺ 10** (back 10 s), **Play/Pause** and **↻ 10** (forward 10 s). They are
  see-through (dark glass), at least 64 px on phones and 76-92 px on bigger screens.
  - The buttons, the browser's seek bar and the title bar fade out on their own after about 3 s of playback.
    Tap again to hide them sooner. They stay up while the film is paused. Moving the mouse over the picture also
    shows them.
  - Tapping a button never also pauses or hides the film.
  - **Double-tap** the left or right side of the picture to jump back or forward 10 s, YouTube style. A "−10s" or
    "+10s" bubble shows the jump, and quick repeated taps add up ("+20s", "+30s").
  - Skipping works for direct play and for transcoded (HLS) streams, and the resume point is saved right away.
  - Keyboard: Left/Right (or J/L) = ∓10 s, Space (or K) = pause/play, F = full screen, Esc = close (Esc only
    leaves full screen when the film is full screen).
- **See-through server status in the player.** A small translucent pill at the top right of the picture shows
  "CPU x% · RAM used/total GB" (amber/red when busy). It appears and fades together with the buttons. It reuses
  the top-bar status check (every 4 s), so the player adds no extra server requests, and it stops when the player
  closes. It follows the existing "Show server status" setting.
- **Full screen keeps the buttons and the status.** The new full-screen button (top right of the player, or F)
  makes the whole player full screen instead of the bare video, so the overlay is still there. On phones it also
  turns to landscape where the browser allows it. This works in the Android app too.
- Interface sounds stay silent while a film is open.
- No database change. Updating from 1.4.10 keeps all data; `update.sh --rollback` restores the previous version.
  The share's write setting is unchanged.

## 1.4.10 -- 2026-11-24
- **Settings cards on phones read cleanly.** In 1.4.9 a value made of several parts was squeezed into narrow
  side-by-side columns that broke mid-word. That affected a library's Source (share, "mounted" badge and folder),
  Last scan (time and result) and Auto scan (interval and next run). Now:
  - **Multi-part or long values** get their label on top, use the full card width, and stack their parts
    underneath: share, then badge, then folder; "4 h ago", then "added 1, updated 0, ..."; "Every 6 hours", then
    "next in 2 h". Short values (Type, Items, Role, Created) keep the label on the left and the value on the right.
  - **The badge** is a compact pill that never wraps: "mounted · writable" / "mounted · read-only" (was
    "mounted (writable)").
  - **Paths and share addresses** wrap only after a "/" (or at a hyphen), never inside a folder name. This covers
    the library folder, the share and the System data folder. Previously library paths and System values were
    allowed to break anywhere.
  - **Action buttons** sit in a tidy grid of 44 px buttons: Scan / Full rescan, Remount / Credentials, Artwork /
    Edit. Remove (and Delete for users) is on its own full-width row at the end. The Users and Metadata buttons
    are tidied the same way.
  - Checked on every card table: Libraries, Metadata > Libraries, Users and System > Active transcodes, plus the
    System details. Tested at 360, 390 and 430 px with an SMB and an NFS share library.
  - The desktop table is unchanged apart from the new pill text.
- No database change. Updating from 1.4.8 or 1.4.9 keeps all data; `update.sh --rollback` restores the previous
  version. The share's write setting is unchanged.

## 1.4.9 -- 2026-11-24
- **The ⋯ menu on the movie page is for admins only.** Non-admin users no longer see the button, so they have no
  Download file and no File info. Play, Mark watched, the description, cast and similar movies are unchanged.
  The server enforces this too:
  - Downloading a file (`/api/items/{id}/file?download=1`) now needs an admin (403 otherwise). Streaming for
    playback is unchanged.
  - Non-admins no longer get the file name; the folder and path were already hidden from them.
  - Fix match, Home rows, tags and settings already required an admin.
- **< and > row buttons on phones and tablets too.** They are 44 px touch targets placed just inside the screen
  edge and centred on the posters. They light up while pressed, with no "stuck" hover, and are hidden when a row
  fits. Swiping the rows still works and keeps the buttons in step.
- **Mobile-friendly Settings.** On narrow screens (820 px and below):
  - **Tab bar:** the tabs sit on one line that you can swipe sideways (no wrapping), each tab is at least 44 px
    tall, the open tab is scrolled into view, and the edges fade where there are more tabs.
  - **Panels** (Libraries, Scan activity, Metadata, My account incl. Sounds, Users, System) use one column, with
    full-width inputs (16 px text, so iPhones don't zoom in).
  - **Tap targets:** every button, input, checkbox row and switch row is at least 44 px. The checkbox labels can
    be tapped.
  - **Tables** (libraries, users, metadata, transcodes) become one card per row, with each value labelled.
  - System details are stacked with long paths wrapping, so nothing needs sideways scrolling. Tested at 360,
    375, 390 and 430 px wide.
  - Non-admins only see the My account tab; before, there was a Libraries tab that just showed My account.
- No database change. Updating from 1.4.7 or 1.4.8 keeps all data; `update.sh --rollback` restores the previous
  version. The share's write setting is unchanged.

## 1.4.8 -- 2026-11-24
- **Interface sounds.** Short, quiet sounds made in the browser (Web Audio; no sound files):
  - **Hover:** a soft tick when the mouse moves onto a poster or you Tab to one. Its pitch varies a little each
    time, and when you sweep quickly across a row you get at most one tick every 70 ms. Moving around inside the
    same poster stays silent.
  - **Select:** an airy whoosh and a two-note chime when you open a movie (click or Enter).
  - **Play / Resume** (and the quick-play button on posters): a soft low thump and a rising three-note tone.
  - **< and > row buttons:** a quick swish, up for > and down for <.
- **Never during playback:** no sounds play while the video player is open.
- **On by default at a low volume (30%).**
- **Speaker button** in the top bar, next to the server status: one click mutes or unmutes. A chime confirms
  that sound is back on.
- **Settings > My account > Sounds:**
  - Interface sounds on/off.
  - Separate switches for hover sounds and for select sounds (select also covers play and arrows).
  - A volume slider.
  - A Test button.
  - Settings are saved for each user in that browser.
- **Browser rules:** browsers only allow sound after you click or press a key, so the audio starts at your first
  click or key press (for example signing in). Before that nothing is played and no errors are shown.
- **Phones and tablets:** no hover sounds, and tap sounds are off by default. You can turn select sounds on in
  Settings.
- No database change. Updating from 1.4.6 or 1.4.7 keeps all data, and `update.sh --rollback` restores the
  previous version. The share's write setting is unchanged.

## 1.4.7 -- 2026-11-24
- **330 px posters on Home.** Every Home row (Continue watching, Recommended, Recently released, Recently added,
  Top movies, genre rows) shows posters 330 px wide on large windows (from about 1600 px; was 150 px). They shrink
  with the window: about 297 px at 1440, 227 px at 1100, 156 px on a phone (was 120). TV rows with landscape
  pictures grow too (up to 440 px, was 240). The 500 px TMDB posters already cached are used, so they stay sharp.
  The < > buttons stay centred.
- **Posters pop out on hover.** With a mouse, a poster grows a little (8%), lifts, gets a bigger shadow and a soft
  gold glow, brightens slightly, and fades in the title, year and TMDB score plus the play button. The animation
  takes 0.2 s. Rows have extra room so the enlarged poster isn't cut off, and the posters next to it don't move.
  It works everywhere posters appear: Home, the Movies grid, Collections, Similar movies, actor pages and search.
- **Keyboard:** posters can be reached with Tab and get the same pop-out; Enter opens the movie.
- If "reduce motion" is turned on in the operating system, posters just get the highlight without moving. Phones
  and tablets have no hover effect; tapping a poster opens it as before.
- No database change. Updating from 1.4.5 or 1.4.6 keeps all data; `update.sh --rollback` restores the previous
  version. The share's write setting is unchanged.

## 1.4.6 -- 2026-11-24
- **Bigger movie details page.** All sizes are on-screen widths:
  - **Poster: 550 px** on large windows (from about 1600 px wide; 1.4.5 maxed out at 340 px). It shrinks with
    the window (about 495 px at 1440, 380 px at 1100) so the title and description still fit beside it; phones
    get about 270 px, centred (was 250).
  - **Description: 19 px** text with 1.6 line spacing (was 15.5 px). Tagline 17 px and Directed by / Written by
    16 px (were about 14 px); title up to 38 px (was 28). Phones: 17 px description.
  - **Cast photos: 186 x 279 px** (was 124 x 186, so 1.5x), same portrait style and < > buttons; 130 px on phones (was 100).
  - **Similar movies posters: 330 px** on large windows (was 215), shrinking on smaller ones (about 297 px at
    1440); about 170 px on phones. The < > buttons stay centred.
- **Sharper artwork for the bigger sizes.** The details poster now uses TMDB's 780 px-wide poster (the cached one is
  500 px). It is downloaded the first time a movie's page is opened and then kept in `data/thumbs`; the 500 px
  poster shows until it arrives, or if TMDB can't be reached. Cast photos use TMDB's 632 px-tall image (was 185 px
  wide); photos cached by 1.4.3-1.4.5 are upgraded the first time they are shown (old ones stay if TMDB is down).
  About 150 KB extra per movie page and 40 KB per actor, only for pages people open.
- No database change. Updating from 1.4.4 or 1.4.5 keeps all data; `update.sh --rollback` restores the previous
  version. The share's write setting is unchanged.

## 1.4.5 -- 2026-11-24
- **Cleaner movie details page.** The "File & playback" section and the "Admin" card are gone from the page.
  Their actions moved into a small **...** (more) button next to Play / Mark watched. It opens a menu with:
  - for admins: **Fix match** (with a small "Needs review" badge when the match is flagged, plus "Accept
    suggestion" / "Match looks right" when they apply), **Home rows**, **+ Tag**, **Artwork settings**
  - for everyone: **Download file**, **TMDB**, **File info**
  **File info** opens a small window with the file name, folder, size, container, resolution, video and audio
  codecs, subtitles, bitrate and whether it plays directly or is converted. Other users see only Download, TMDB and
  File info. The menu works with the keyboard (Enter / arrow keys / Esc) and opens as a sheet at the bottom on phones.
  The same applies to TV episode, video and music track pages.
- **Bigger Similar movies posters:** about 215 px wide on a large screen (was 150), still with the < > buttons;
  about 155 px on a phone (was 120). The Cast row keeps its size.
- Fix: the resolution label uses the width as well, so a 1920x800 widescreen film shows 1080p (was 720p).
- No database change. Updating from 1.4.3 or 1.4.4 keeps all data; `update.sh --rollback` restores the previous
  version. The share's write setting is unchanged.

## 1.4.4 -- 2026-11-24
- **Rows scroll with < and > buttons instead of a sideways scrollbar.** Every horizontal row (Home rows,
  Recommended, Cast, Similar movies, ...) has round < and > buttons in the middle of the posters, left and right.
  Each click moves one screen-width of posters with a smooth slide. < is hidden at the start, > at the end, and
  both when the whole row fits. The scrollbar is gone. Keyboard: Tab to a button and press Enter, or use the
  Left/Right arrow keys on a row. Phones and tablets keep swiping (the buttons are hidden on touch screens).
- **Blurred background on the movie details page.** The movie's backdrop (or its poster if it has none) fills
  the whole page behind the details, softly blurred and darkened so text stays readable. It stays in place while
  you scroll, and goes away when you leave the page. Movies with no artwork keep the plain dark background.
- **Bigger poster on the details page:** about 330 px wide on a large screen (was 240), scaling down on smaller
  windows; on a phone it is centred above the title (about 250 px, was 150). Same 2:3 shape, sharp image.
- No database change. Updating from 1.4.2 or 1.4.3 keeps all data; `update.sh --rollback` restores the
  previous version. The share's write setting is unchanged.

## 1.4.3 -- 2026-11-24
- **Clicking a movie opens its details page instead of playing.** This applies everywhere: Home rows, Continue
  watching, the Movies grid, Collections, search and the new actor pages. Hovering a poster shows a small round
  play button for quick play (it resumes where you stopped); phones and tablets just open the details.
- **New details page layout:**
  - backdrop, poster, title, year, age rating, runtime, genres, TMDB score and tagline
  - big **Resume from mm:ss** / **Play from start** (or **Play**) buttons, plus Mark watched
  - "Directed by / Written by", then the description
  - **Cast**: the top-billed actors (up to 20) with photo, name and character, scrolling sideways. Click an actor
    (or the director / writer) to see the other movies in your library they are in
  - **Similar movies** from your library: TMDB's recommendations first, then the same collection, then movies
    sharing the most genres. Each one says why, and clicking it opens its details
  - **File & playback** (resolution, codec, audio, subtitles, download) collapsed at the bottom
  - an **Admin** box with Fix match, Home rows, + Tag, Artwork settings and the TMDB link (admins only)
- **Cast & crew from TMDB.** They are read in the same details request as categories (no extra calls). After
  updating, the background pass runs once more for movies you already have; the top bar shows "Fetching cast &
  details". It takes about one request per movie, 2-4 minutes for 2,000 movies, and can be resumed. Pages work
  during the pass and say the cast is on its way. Actor photos are downloaded the first time someone opens a
  page that shows them, then served from the local cache.
- Database schema 6 (people, movie_cast, movie_crew). Updating from 1.4.x keeps all data;
  `update.sh --rollback` restores the previous version and database. The share's write setting is unchanged.

## 1.4.2 -- 2026-11-24
- **Server status in the top-right corner** of every page: live CPU % with a small sparkline and RAM used/total
  with a bar (e.g. "CPU 12% · RAM 6.2/31 GB"). Green normally, amber from 60% CPU / 75% RAM, red from 85% / 90%.
  Refreshes every 4 s and stops while the browser tab is hidden. Sits next to the scan pill without
  overlapping; on a phone it shrinks to a coloured dot.
- Hover (or click to keep it open) for details: CPU overall and per core, load average, memory and swap,
  free space on the data disk and each mounted share, uptime, active streams and running ffmpeg processes,
  and the media server's own memory.
- New `GET /api/system/status`. Reads /proc directly (no new dependencies); a small sampler refreshes the
  numbers every 2 s only while someone is watching and every client shares the same cached result.
- Admin-only by default. Settings > System > **Show server status to all users** lets everyone see it.
- No database schema change; nothing else changed.

## 1.4.1 -- 2026-11-24
- Home is reorganised. Order: **Continue watching** (only when something is part-watched), **Recommended for
  you**, **Recently released**, **Recently added**, **Top movies**, then the genre rows. Every row has
  "See all"; the same lists are tabs on the Movies page (All movies / Recommended / Recently released /
  Recently added / Top movies / Collections).
  - Continue watching: movies (and episodes) you started but did not finish, most recent first, with a
    progress bar and "N min left"; clicking a poster resumes where you stopped.
  - Recommended (per user): built from your watch history -- TMDB's "people who liked this also liked" list
    for the movies you watched, shared genres and collections, weighted toward what you watched most recently,
    plus the next film of a franchise after you finish one ("Next in The Matrix Collection"). Each poster says
    why ("Because you watched Heat"). Finished and started movies are left out. With no history yet it shows
    well-known, highly rated movies mixed across your top genres. The list is cached and only changes when
    you watch something, the library changes, or the day changes.
  - Recently released: newest TMDB release date first, last 2 years, never future dates (topped up with the
    next-newest when the library has fewer than 12 recent films).
  - Recently added: newest additions to the library.
  - Top movies: TMDB score weighted by number of votes (IMDb's formula, m = 500 votes, at least 50 votes), so a
    film with three 10/10 votes does not top the list; unreleased films are left out.
- Admins: "Home rows" on a movie page pins a movie to Recommended or Top movies (always include, shown first)
  or keeps it out; "Automatic" undoes it.
- TMDB recommendations are read in the same request as the 1.4 categories (no extra calls). After updating,
  the background "Fetching categories" pass runs once more: about one request per movie, 2-4 minutes for
  2,000 movies, resumable. Rows work right away and get more personal when it finishes.
- Fix: closing the player when a stream never started no longer resets the movie's resume position.
- Database schema 5 (movie_recs, home_pins, rec_cache). Updating from 1.3.x or 1.4 keeps all data;
  `update.sh --rollback` restores the previous version and database.

## 1.4 -- 2026-11-23
- Movie categories. For every matched movie Media Server now keeps its TMDB genres, collection / franchise
  (e.g. "The Matrix Collection"), age rating (your TMDB language's country, else US), runtime and TMDB score.
  - Right after the update, genres work at once (built from what is already cached, no TMDB calls). The rest
    is fetched in the background: one TMDB request per movie (posters are already cached), at most 20/s with
    4 lookups at a time, resumable across restarts. The top-bar pill and Settings -> Scan activity show
    "Fetching categories ... done / total".
  - New matches get the categories straight away; Fix match choices are kept exactly as they are.
- Movies page: a **Movies / Collections** switch and a category bar.
  - Genre chips with counts -- pick several to narrow down (movies that have all of them); counts follow
    what you picked. Decade, age rating and tag menus. **Clear** resets them. Choices are remembered while
    the tab is open.
  - Everything combines with search, the sort menu (new: TMDB score), Needs review / No match / Special
    editions, and Posters first.
  - Collections: a poster grid of the franchises you own (movie count and years); open one to see its
    movies in release order.
- Home: after "Recently added", a row for each of the library's biggest genres (best rated first) with
  "See all" opening the filtered library.
- Movie page: genres are links to the filtered library; age rating chip; "Part of <collection>" link.
- Your own tags (admins): "+ Tag" on a movie page, or **Select** on the Movies page to tag many movies at once
  (Select all shown / Add tag / Remove tag). Filter by tag from the category bar. Tags vanish when no movie
  uses them.
- Database schema 4 (new tables movie_genres, collections, tags, item_tags; four new metadata columns).
  Updating keeps all data; rolling back to 1.3.x with `update.sh --rollback` restores the old database.
- Unchanged: artwork saving stays off, share writing stays off, matching rules are the same.

## 1.3.1 -- 2026-11-23
- Redesigned the "Artwork in movie folders" dialog (Settings -> Libraries -> Artwork): a short intro and three
  clear steps -- 1 Share access (switch + Read-only / Writable badge, the fine print under "Details"),
  2 What to save (aligned switches with a one-line hint each: poster, fanart, .nfo, how files are named,
  save automatically for new matches, overwrite existing), 3 Run (Preview is secondary; "Write artwork" is
  the only primary button and stays disabled until the share is writable and your settings are saved;
  preview results show inline with paths relative to the library). Wider (680px), 14px+ text, better
  contrast, scrolls inside on small screens, works on phones.
- Libraries table: action buttons wrap neatly in two rows instead of running off the edge; long share paths
  wrap; the table scrolls sideways on narrow screens.
- No behaviour changes: same defaults (artwork saving and share writing stay off), same files written.

## 1.3 -- 2026-11-23
- Better automatic TMDB matching for movies:
  - Edition words in file names (Director's Cut / DIRECTORS CUT / DC, Unrated, Extended, "EXTENDED and UNRATED",
    Remastered, Theatrical, IMAX, Final Cut, Special Edition, {edition-...}) are no longer searched for; they
    show as a small edition label on the card and the movie page (filter: "Special editions").
  - Results from the file's year win; an exact title that is more than a year off is never applied
    automatically -- it is offered as a suggestion under "Needs review".
  - Retries with shorter titles: without "The Movie", without "Episode IV -", each side of a dash or colon,
    the series name for sequels ("Die Hard 3", "Iron Man Three" -> picked by year), and spelling slips
    ("Dinosour", "The Matrx") when the year agrees. When several films share a title, the better-known one
    wins near-ties.
  - Library sorting and search use the TMDB title once a movie is matched.
  - Your Fix match choices are never changed by automatic matching or "Refresh metadata".
- "Needs review" filter in movie libraries (with counts), plus "No TMDB match" and "Special editions".
  Unsure matches get a "?" badge; the movie page says why and offers **Accept** (switch to the suggested
  film) or **Looks right** (keep it).
- Save artwork into the movie folders (off by default, per library: Settings -> Libraries -> **Artwork**):
  poster.jpg, optional fanart.jpg and a Kodi / Jellyfin / Plex-compatible movie.nfo. Movies that share a
  folder with other movies (or sit in the library root) get `<file name>-poster.jpg` / `-fanart.jpg` /
  `<file name>.nfo` instead. Existing artwork / .nfo files are never replaced unless you tick Overwrite (and
  then only our own file names, rewritten in place so owner and permissions stay). **Preview (dry run)**
  lists every file first; **Write artwork for all matched items now** runs in the background with progress
  in the top pill and Settings -> Scan activity; new matches are written automatically while the option is on.
- Shares: per-share **Allow writing (artwork only)** switch that remounts the share read-write (shares stay
  read-only by default). A read-only share or a NAS that refuses writes stops the run with a clear message
  instead of failing file by file.
- Database schema 3 (applied automatically on update; existing titles with edition words are split and
  re-matched once, manual matches are kept).

## 1.2.1 -- 2026-11-23
- Fix: TMDB matching that was interrupted (e.g. by the update restart right after saving the key) or never
  started now resumes by itself -- at startup and every 5 minutes, whenever titles are still waiting for a
  lookup. Before, it only restarted after the next scan, so posters stopped filling in and the "Fetching
  posters" pill never appeared.
- Posters first: library grids default to titles with real artwork (TMDB poster or local poster.jpg) first,
  then the rest under "Without a poster yet"; as TMDB finds posters, titles move up live without losing your
  scroll position. Sort menu: Posters first / Title (A-Z) / Recently added / Year (also for TV); the choice is
  remembered per library. Home's "Recently added" shows titles with posters first.
- Faster matching: 4 lookups in flight (`MS_TMDB_WORKERS`), still within the 20 req/s limit; the pill shows
  time left.
- Settings -> Metadata: "N not looked up yet" per library and a "Match missing" button (looks up only what
  is missing; "Refresh metadata" still re-downloads everything).
- index.html stamps every JS/CSS URL with the running version automatically, so browsers always load the new
  code after an update.

## 1.2 -- 2026-11-23
- Scan progress you can see: a live pill at the top of every page ("Scanning Movies -- 312 / 2,021 · ETA ·
  current file"), a "Discovering files... N found" phase, "Fetching posters" for TMDB, and a pop-up when a
  scan finishes (added / updated / removed / errors).
- Settings -> Scan activity: per-library phase, counts, speed, ETA, files in progress, last error, recent
  log lines, and a Cancel scan button (keeps what was found; the next scan resumes).
- Movies show up while the scan runs: items are saved in small batches, the library grid and Home update
  every few seconds without losing your scroll position, posters fill in as TMDB matches (matching now
  also runs during the scan, not only at the end).
- Faster scans of big SMB libraries: folder walk and processing run at the same time, a bounded worker pool
  (MS_SCAN_WORKERS), thumbnails from a single keyframe (~10x less CPU on 4K/HEVC), unreadable files are not
  re-probed on every scan, and nothing is removed if some folders couldn't be read.
- Libraries with more than 1,000 items now list everything (was capped at 1,000); posters load lazily.
- "Recently added" uses the time each file was added, not the scan start.

## 1.1 -- 2026-11-23
- TMDB metadata for movies and TV shows: posters, backdrops, description, tagline, genres, rating,
  episode titles and stills. Key (v3 API key or v4 read token) in Settings -> Metadata or `MS_TMDB_KEY`
  in .env. Automatic matching after each scan, "Fix match" on movie/show pages (search, pick, use file
  name, automatic), Refresh metadata per library, throttled requests with 429 handling, everything
  cached locally, works without a key exactly like 1.0. TMDB attribution in the UI.
- Remux: MKV/MP4/MOV with H.264 video and audio the browser can't play (AC3, DTS, TrueHD, multichannel)
  or another audio track -> the video is copied into HLS and only the audio is converted. Seeking works;
  falls back to transcoding automatically.
- Automatic library scans: Off / Hourly / Every 6 hours / Daily, with the next scan time in Settings.
- File-name parsing: titles containing words like "Web", "Remux", "Proper" (e.g. "Charlotte's Web") are no
  longer cut short; "1917.2019.mkv" and "Blade Runner 2049 (2017)" get the right title and year.
  Already-scanned files keep their old title until a Full rescan (TMDB matching corrects most of them anyway).
- README: Caddy and nginx HTTPS reverse-proxy examples.
- Database schema 2 (migrated automatically by update.sh; existing data kept).

## 1.0 -- 2026-11-23
First release.
- Libraries: Movies, TV shows, Music, Other videos from a local folder or an SMB / NFS share mounted
  from the UI (read-only systemd mount units, root-only credentials file, sudo-restricted helper).
- Scanner: filename parsing (title/year, SxxEyy / 1x01 / season folders, track numbers), ffprobe
  (duration, codecs, resolution, audio/subtitle tracks, tags), ffmpeg thumbnails, local poster/cover
  images, embedded album art, external subtitles, incremental rescans, scheduled rescans, safe against
  an offline share (items are kept).
- Web UI: home (continue watching, recently added), poster grids, shows -> seasons -> episodes,
  albums -> tracks, search, item details, settings (libraries, shares, users, account, system).
- Playback: direct play with HTTP range/seeking; HLS transcode fallback (1080p/720p/480p/360p) with
  seek-anywhere; audio-track and subtitle selection; music player with queue; resume + watched state.
- Users: admin created at install with a random password (forced change at first sign-in),
  extra admin/viewer users, reset-admin.sh.
- install.sh / update.sh (backup, mirror, migrate, health check, auto-restore, --rollback) / status.sh.
