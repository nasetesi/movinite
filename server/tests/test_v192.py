"""1.9.2: TV details focus, 1920-wide TV layout, search not stealing Up.

    python3 tests/test_v192.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.version import __version__ as VERSION  # noqa: E402

js = (ROOT / "app/static/app.js").read_text()
css = (ROOT / "app/static/style.css").read_text()
ch = (ROOT / "CHANGELOG.md").read_text()
fails = 0


def check(cond, msg):
    global fails
    if cond:
        print("  ok ", msg)
    else:
        print("FAIL", msg)
        fails += 1


print("version and docs")
check(tuple(int(x) for x in VERSION.split(".")) >= (1, 9, 2), "version is 1.9.2 or later (%s)" % VERSION)
check("## 1.9.2" in ch and ch.find("## 1.9.2") < ch.find("## 1.9.1"), "CHANGELOG has 1.9.2 above 1.9.1")
check("Resume" in ch and "Similar" in ch, "changelog describes details focus")
check("1920" in ch and ("zoomed" in ch.lower() or "viewport" in ch.lower() or "4K" in ch or "4k" in ch), "changelog describes TV scale")
check("192.168.1.10" not in (ROOT / "README.md").read_text() + (ROOT / "app/static/app.js").read_text() + (ROOT / "app/browse.py").read_text(),
      "public examples use 192.0.2.10, not 192.168.1.10")

print("details focus")
check("isDetailView" in js and "detailPrimaryAction" in js, "detail helpers exist")
check('("#resume")' in js or '$("#resume")' in js, "primary action prefers Resume")
check("moveInDetail" in js and "detailZones" in js, "details have their own spatial zones")
check("rememberOrigin" in js and "originEl" in js, "origin poster is remembered for Back")
check("isSearchChrome" in js, "search is identified so vertical nav can skip it")
check("GoBack" in js and "Backspace" in js, "Back includes GoBack and Backspace")
check("afterRoute" in js and "detailPrimaryAction" in js and js.find("isDetailView") < js.find("afterRoute() {") + 800, "afterRoute can prefer the detail action")
# afterRoute should focus the primary action on detail views before generic cards
ar = js[js.find("afterRoute() {"):]
check("isDetailView()" in ar and "detailPrimaryAction" in ar, "afterRoute focuses Resume/Play on a details page")

print("1920-wide TV layout")
check("fitLayout" in js and "1920" in js and "innerWidth" in js, "fitLayout keys off innerWidth, target 1920")
check("devicePixelRatio" not in js[js.find("fitLayout"):js.find("fitLayout")+800], "fitLayout does not key off devicePixelRatio")
check("tv-scaled" in css and "--tv-scale" in css, "CSS scales the 1920 layout to the CSS viewport")
check("html.tv-mode .strip.hs:not(.wide){grid-auto-columns:200px" in css or "grid-auto-columns:200px" in css, "TV home posters are ~200px so about 7–8 fit")
check("4px" in css and ("#resume:focus" in css or ".actions .btn:focus" in css), "play buttons get a 4px purple focus ring")
check("data-bg-hi" in js and "/api/items/" in js and "poster-large" in js and "function artBg" in js,
      "TV mode loads high-res posters at high DPR")

print("TV 1.9.1 hooks still present")
check("const TV = {" in js and "window.TV = TV" in js, "TV module still exported")
check("MSAndroid.isTv" in js, "isTv bridge still detected")

if fails:
    print("\n%d failed" % fails)
    sys.exit(1)
print("\nall ok")
