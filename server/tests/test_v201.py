"""2.0.1: TV D-pad can reach the player settings gear and navigate its menu.

    python3 tests/test_v201.py
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
rd = (ROOT / "README.md").read_text()
fails = 0


def check(cond, msg):
    global fails
    if cond:
        print("  ok ", msg)
    else:
        print("FAIL", msg)
        fails += 1


print("version and docs")
check(VERSION == "2.0.1", "version is 2.0.1 (%s)" % VERSION)
check("## 2.0.1" in ch and ch.find("## 2.0.1") < ch.find("## 2.0 --"), "CHANGELOG has 2.0.1 above 2.0")
check("settings gear" in ch.lower() or "bottom right" in ch.lower(), "changelog mentions the player settings gear")
check("Back" in ch and ("hides" in ch.lower() or "hide" in ch.lower()), "changelog describes Back hiding controls first")
check("2.0.1" in rd and "settings gear" in rd, "README mentions 2.0.1 player gear navigation")
check("192.168.1.10" not in rd + js + (ROOT / "app/browse.py").read_text(),
      "public examples use 192.0.2.10, not 192.168.1.10")

print("player D-pad")
check("moveInPlayer" in js and "playerControls" in js, "player zone helpers exist")
check("playerVisibleChrome" in js, "player chrome stays a target while the overlay fades in")
tv = js[js.find("const TV = {"):]
check('if (playerOn) return $("#pl-bplay") || $("#pl-pp")' in tv,
      "preferred start on the player is the bottom-bar play button")
# Left/Right on the seek bar still skip, but no longer by falling through to the page handler
onkey = js[js.find("  onKey(e) {"):js.find("  ensureFocusable()")]
check("moveInPlayer" in onkey, "onKey uses moveInPlayer while a film is playing")
check("if (playerOn && onSeek" not in onkey, "onKey no longer early-returns Left/Right on the seek bar to the page skip handler")
check("skip(-10" in onkey and "skip(10" in onkey and "wasOn" in onkey, "hidden controls: Left/Right seek ±10s")
check("togglePlay" in onkey and "wasOn" in onkey, "hidden controls: OK toggles pause")
mip = js[js.find("moveInPlayer(dir)"):js.find("preferredStart(items)")]
check("z.seek.includes" in mip and "skip(" in mip, "Left/Right on the seek bar skip in moveInPlayer")
check("z.menu.length" in mip, "Up/Down move through the open settings menu")
check("do not fall through" in mip or "return true;   // do not fall through" in mip or "return true;" in mip,
      "Left/Right on the button row are consumed (no accidental skip)")

print("settings menu and Back")
check("(!SFX.COARSE || (window.TV && TV.on))" in js, "opening a picker focuses an item on a TV even when the pointer is coarse")
check("BAR.popOpen" in js[js.find("  back() {"):js.find("  back() {")+800], "Back closes the settings menu before hiding or leaving")
back = js[js.find("  back() {"):js.find("  onKey(e) {")]
# player branch must hide overlay before closePlayer
check("ov-on" in back and "OV.hide" in back, "Back with controls shown hides them")
check(back.find("BAR.popOpen") < back.find("OV.hide"), "Back closes the menu before hiding the overlay")
check(back.find("OV.hide") < back.find("closePlayer"), "Back hides the overlay before leaving the player")
check("pl.contains(document.activeElement)" in js, "auto-hide is held while a player control is focused")
check("TV.focus(anchor)" in js or "TV.focus(anchor)" in js, "closing the menu returns focus to the gear")

print("focus rings")
check("html.tv-mode .pl-pop button:focus" in css, "settings menu items have a TV focus ring")
check("html.tv-mode #pl-vol:focus" in css or "html.tv-mode #pl-vol:focus-visible" in css, "volume slider has a TV focus ring")
check("html.tv-mode .pl-cb:focus" in css and "html.tv-mode #pl-seek:focus" in css, "bar buttons and the seek bar keep a focus ring")

print("1.9.2 / 2.0 hooks still present")
check("const TV = {" in js and "window.TV = TV" in js, "TV module still exported")
check("isDetailView" in js and "detailPrimaryAction" in js, "details focus helpers still present")
check("fitLayout" in js and "1920" in js, "1920 TV layout still present")

if fails:
    print("\n%d failed" % fails)
    sys.exit(1)
print("\nall ok")
