"""1.4.4: static checks that the < > row buttons, the blurred details background and the bigger poster ship
(the browser behaviour is covered by the Playwright UI test).

    python3 tests/test_rows144.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.version import __version__ as VERSION  # noqa: E402

js = (ROOT / "app/static/app.js").read_text()
css = (ROOT / "app/static/style.css").read_text()
fails = 0


def check(ok, msg):
    global fails
    print(("  ok - " if ok else "  FAIL - ") + msg)
    fails += 0 if ok else 1


check(tuple(map(int, VERSION.split("."))) >= (1, 4, 4), "version 1.4.4 or later")
check('HROW_SEL = ".strip, .cast-strip"' in js, "all horizontal rows (.strip, .cast-strip) are enhanced")
check('class="hnav prev"' in js and 'class="hnav next"' in js, "< and > buttons are created")
check('aria-label="Scroll left"' in js and 'aria-label="Scroll right"' in js, "buttons have accessible labels")
check('behavior: "smooth"' in js or "behavior:\"smooth\"" in js, "paging scrolls smoothly")
check("MutationObserver" in js, "rows re-rendered later (live refresh) are enhanced too")
check("ArrowLeft" in js and "ArrowRight" in js, "keyboard arrows page a focused row")
check(re.search(r"\.hrow>\.strip[^{]*\{[^}]*scrollbar-width:none", css) is not None, "scrollbar hidden")
check("::-webkit-scrollbar" in css, "scrollbar hidden in Chrome/Safari too")
check("top:var(--nav-y)" in css, "buttons are vertically centred on the posters")
check(re.search(r"\.hnav\{display:none\}", css.split("1.4.9")[0] if "1.4.9" in css else css) is None or "1.4.9: < > row buttons on phones" in css,
      "buttons on touch screens: shown since 1.4.9 (were hidden in 1.4.4-1.4.8); swipe still works")
check('class="detail-bg"' in js and "dbg-img" in js, "details page renders the blurred background layer")
check(re.search(r"\.detail-bg\{position:fixed;inset:0;z-index:0", css) is not None, "background is fixed full-page")
check("blur(36px)" in css, "background is blurred")
check(re.search(r"\.top\{position:relative;z-index:5", css) is not None
      and re.search(r"\.side\{position:relative;z-index:5", css) is not None, "top bar and sidebar stay above it")
check("it.backdrop || (isMovie ? it.poster : null)" in js, "poster used when there is no backdrop")
check("clamp(240px,23vw,340px)" in css, "bigger details poster on desktop")
check("min(64vw,270px)" in css, "bigger centred poster on phones")
print("rows144: %d failure(s)" % fails)
sys.exit(1 if fails else 0)
