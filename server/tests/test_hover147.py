"""1.4.7: static checks -- 330 px Home posters and the poster pop-out on hover / keyboard focus
(the browser behaviour is covered by the Playwright UI test).

    python3 tests/test_hover147.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.version import __version__ as VERSION  # noqa: E402

js = (ROOT / "app/static/app.js").read_text()
css = (ROOT / "app/static/style.css").read_text()
home = js[js.index("async function viewHome(live) {"):]
home = home[:home.index("\n}\n")]
fails = 0


def check(ok, msg):
    global fails
    print(("  ok - " if ok else "  FAIL - ") + msg)
    fails += 0 if ok else 1


check(tuple(map(int, VERSION.split("."))) >= (1, 4, 7), "version >= 1.4.7")
check('<div class="strip">' not in home and '<div class="strip hs cw">' in home and home.count('<div class="strip hs') >= 5,
      "every Home row (Continue watching, smart rows, genre rows, libraries) is a Home strip")
check(".strip.hs:not(.wide){grid-auto-columns:clamp(150px,20.6vw,330px)" in css, "Home posters up to 330 px")
check("@media (max-width:820px){\n  .strip.hs:not(.wide){grid-auto-columns:min(40vw,160px)" in css, "phones: up to 160 px")
check(re.search(r"\.hrow>\.strip\{padding:34px 20px 18px;margin:-34px -20px -8px", css) is not None, "rows have room so a popped-out poster isn't cut off")
check("@media (hover:hover) and (pointer:fine){\n  .card:hover{z-index:4}\n  .card:hover .art{transform:translateY(-6px) scale(1.08)" in css,
      "hover: scale 1.08 and lift, only with a real mouse")
check(".card:focus-visible .art{transform:translateY(-6px) scale(1.08)" in css, "keyboard focus gets the same pop-out")
check("transition:transform .2s cubic-bezier" in css, "200 ms ease-out transition on transform")
m = re.search(r"\.card \.art\{transition:([^}]*)\}", css)
check(m is not None and "width" not in m.group(1) and "height" not in m.group(1) and "left" not in m.group(1),
      "animates only transform / shadow / filter (no layout properties, so neighbours don't move)")
check("@media (prefers-reduced-motion:reduce)" in css and ".card:hover .art,.card:focus-visible .art{transform:none}" in css, "reduced motion respected")
check("@media (hover:none),(pointer:coarse){.card .hov{display:none}}" in css, "no hover overlay on touch screens")
check('<div class="hov" aria-hidden="true">' in js, "title / year / score overlay on posters")
check(js.count('tabindex="0" data-href=') >= 4, "posters are keyboard-focusable (items, shows, albums, collections)")
check('e.key !== "Enter"' in js and 'classList.contains("card")' in js, "Enter opens a focused poster")
print("hover147: %d failure(s)" % fails)
sys.exit(1 if fails else 0)
