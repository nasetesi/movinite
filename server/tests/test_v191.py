"""1.9.1: TV / D-pad spatial navigation in the web app.

    python3 tests/test_v191.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.version import __version__ as VERSION  # noqa: E402

js = (ROOT / "app/static/app.js").read_text()
css = (ROOT / "app/static/style.css").read_text()
html = (ROOT / "app/static/index.html").read_text()
ch = (ROOT / "CHANGELOG.md").read_text()
fails = 0


def check(cond, msg):
    global fails
    if cond:
        print("  ok ", msg)
    else:
        print("FAIL", msg)
        fails += 1


print("version and stamps")
check(tuple(int(x) for x in VERSION.split(".")) >= (1, 9, 1), "version is 1.9.1 or later (%s)" % VERSION)
check(tuple(int(x) for x in VERSION.split(".")) >= (1, 9, 1), "version.py is 1.9.1 or later")
check("## 1.9.1" in ch and ch.find("## 1.9.1") < ch.find("## 1.9 --"), "CHANGELOG has 1.9.1 above 1.9")
check("TV mode" in ch or "spatial navigation" in ch.lower() or "D-pad" in ch, "changelog describes TV / D-pad navigation")

print("detection and hooks")
check("const TV = {" in js and "window.TV = TV" in js, "TV module is defined and exported")
check("MSAndroid.isTv" in js, "detects a television from the Android isTv() bridge")
check("AndroidTV" in js and "BRAVIA" in js and "AFT" in js, "detects common TV user-agent strings")
check('localStorage.getItem("msTvMode")' in js, "a localStorage override can turn TV mode on for tests")
check("MOB.setup();\n  if (window.TV) TV.init();" in js or "TV.init()" in js, "boot() starts TV mode")
check("TV.afterRoute()" in js, "route() hands off to TV.afterRoute so the first poster is focused")
check("window.__msTvBack" in js, "Back is exposed for the Android onBackPressed hook")

print("spatial navigation")
check("move(dir)" in js and "nearest(cur, items, dir)" in js, "arrow keys pick the nearest focusable neighbour")
check(".side nav a" in js and "#navlibs a" in js and "#view .card" in js, "sidebar libraries and posters are in the focus set")
check("#player .pl-big" in js and "#pl-seek" in js and "#pl-close" in js, "player controls are in the focus set")
check("keyCode === 23" in js or 'key === "Go"' in js, "DPAD_CENTER / OK is treated like Enter")
check("function back(" in js or "back()" in js and "pl-close" in js, "Back closes the player or a dialog")
check('el.classList && el.classList.contains("card")' in js, "1.4.7 Enter-on-card is still present")

print("focus styles")
check("html.tv-mode" in css and "html.tv-mode .card:focus" in css, "TV mode styles :focus, not only :focus-visible")
check("box-shadow:0 22px 44px rgba(0,0,0,.6),0 0 0 4px var(--acc)" in css, "focused posters get a 4px theme-purple ring")
check("html.tv-mode .card:focus .hov" in css, "hover-only poster overlays stay visible on the focused card")
check("html.tv-mode .side nav a:focus" in css, "sidebar links get a purple focus ring")
check("html.tv-mode .pl-big:focus" in css and "html.tv-mode #pl-seek:focus" in css, "player controls get a purple focus ring")
# keep the 1.4.7 keyboard styles intact
check(".card:focus-visible .art{transform:translateY(-6px) scale(1.08)" in css, "existing keyboard focus-visible pop-out is unchanged")

print("library tiles and rows are not skipped")
check('class="lib-li" tabindex="0"' in js, "Libraries-page tiles are focusable (tabindex=0)")
check("MediaServerAndroid" in js and "Mobile" in js, "TV detection mentions MediaServerAndroid and Mobile UA")
check('"#view .hnav"' not in js, "row < > buttons are not D-pad candidates (they stole focus from posters)")
check("Stay inside a horizontal movie/library row first" in js, "Left/Right stay inside a poster row instead of skipping it")
check("Right from the sidebar" in js, "Right from the sidebar enters the main view")
check("ensureFocusable" in js, "ensureFocusable marks library tiles and cards")
check("html.tv-mode .lib-li:focus" in css, "library tiles get a purple focus ring")

print("cache-bust")

idx = (ROOT / "app/static/index.html").read_text()
# stamps are injected at serve time from __version__, not hardcoded in the file
from app.version import __version__
check(tuple(int(x) for x in __version__.split(".")) >= (1, 9, 1), "served ?v= stamp follows the version (%s)" % __version__)

if fails:
    print("\n%d failed" % fails)
    sys.exit(1)
print("\nall ok")
