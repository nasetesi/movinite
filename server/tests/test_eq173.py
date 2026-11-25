"""1.7.3: themed prev/next buttons and the music equalizer (including Dynamic)."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
js = (HERE.parent / "app/static/app.js").read_text()
css = (HERE.parent / "app/static/style.css").read_text()
html = (HERE.parent / "app/static/index.html").read_text()
ver = (HERE.parent / "app/version.py").read_text()

fails = []


def check(ok, msg):
    print(("  ok - " if ok else "  FAIL - ") + msg, flush=True)
    if not ok:
        fails.append(msg)


def main():
    # 1.7.4+: still 1.7.3 or later (themed transport + EQ stay in this tree)
    check(tuple(int(x) for x in __import__("re").search(r'__version__ = "([0-9.]+)"', ver).group(1).split(".")) >= (1, 7, 3), "version is 1.7.3 or later")

    print("themed transport")
    bar = html[html.index('id="audiobar"'):html.index('id="eqpanel"')]
    check("&#9198;" not in bar and "&#9197;" not in bar and "&#9654;" not in bar,
          "mini-player prev/play/next are not Unicode glyphs")
    check('id="ab-prev"' in bar and "<svg" in bar[bar.index('id="ab-prev"'):bar.index('id="ab-play"')]
          and 'id="ab-next"' in bar and "<svg" in bar[bar.index('id="ab-next"'):],
          "prev and next are SVG icons")
    check('class="i-play"' in bar and 'class="i-pause"' in bar
          and 'innerHTML = "&#10074;' not in js and "$(\"#ab-play\").classList.add(\"playing\")" in js,
          "play/pause toggles an SVG class, not glyph innerHTML")
    check(".ab-ctl .iconbtn{" in css and "color:var(--acc-text)" in css
          and ".ab-ctl .iconbtn:hover{" in css and "var(--acc2)" in css
          and ".ab-ctl .iconbtn:active{" in css and "var(--acc-fill)" in css
          and ".ab-ctl .iconbtn:disabled{" in css,
          "prev/next use the purple accent on default, hover, active and disabled")
    check("#ab-play{background:var(--acc-fill)" in css, "play button is filled in the accent colour")
    check("syncAbButtons" in js and "$(\"#ab-prev\").disabled" in js, "prev/next get a disabled state at the ends of the queue")
    check("#pl-back:hover,#pl-fwd:hover{background:rgba(var(--acc-rgb),.42)}" in css
          or "#pl-bback:hover,#pl-bfwd:hover{background:rgba(var(--acc-rgb),.42)}" in css,
          "video skip-back / skip-forward hover uses the purple tint")
    check("createMediaElementSource(video)" not in js and "createMediaElementSource($(\"#video\")" not in js,
          "the equalizer does not connect the video element")

    print("equalizer")
    check('id="eqpanel"' in html and 'id="ab-eq"' in html and 'id="eq-on"' in html and 'id="eq-reset"' in html,
          "EQ panel, on/off, reset and an EQ button are in the page")
    check("createMediaElementSource(audio)" in js, "EQ graph is created from the music <audio> element")
    check("AudioContext" in js and "webkitAudioContext" in js and "eqResume" in js
          and "ctx.state === \"suspended\"" in js, "AudioContext is resumed on a user gesture")
    check("BiquadFilter" in js or "createBiquadFilter" in js, "bands are BiquadFilterNodes")
    check("EQ_FREQS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]" in js, "10 bands from 32 Hz to 16 kHz")
    check('min="-12"' in js and 'max="12"' in js, "each band is ±12 dB")
    for name in ("Flat", "Bass Boost", "Treble Boost", "Vocal", "Rock", "Pop", "Jazz", "Classical", "Dynamic", "Custom"):
        check(name in js and name in (js[js.index("EQ_PRESETS"):js.index("EQ_STORE") + 80] + "Custom"),
              "preset listed: %s" % name)
    check("Dynamic: [6, 5, 3, 0, -2, -2, 0, 3, 5, 6]" in js,
          "Dynamic is the loudness-style curve +6 +5 +3 0 -2 -2 0 +3 +5 +6")
    check("createDynamicsCompressor" in js and "makeup.gain.value = dyn ? 1.41" in js,
          "Dynamic adds a gentle compressor with modest ~+3 dB makeup")
    check('EQ_STORE = "movinite-eq-v1"' in js and "localStorage" in js, "settings are saved per device in localStorage")
    chunk = js[js.index("function eqEnsure"):js.index("function eqNamedPreset")]
    check("crossOrigin =" not in chunk and "audio.crossOrigin" not in chunk,
          "createMediaElementSource does not set crossOrigin (same-origin /api/ streams keep playing)")
    check(".eq-panel{" in css and ".eq-preset.on{background:var(--acc-fill)" in css
          and "accent-color:var(--acc)" in css, "EQ panel is themed purple")
    check("html.af-open" in css and 'classList.add("af-open")' in js, "a full now-playing view opens from the artwork")
    check('navigator.serviceWorker.register("/sw.js?v=%s")' in (HERE.parent / "app/server.py").read_text()
          or 'register("/sw.js?v=' in (HERE.parent / "app/server.py").read_text(),
          "cache-busting still stamps sw.js with the running version")


main()
print("FAILS: %d" % len(fails) if fails else "ALL OK")
raise SystemExit(1 if fails else 0)
