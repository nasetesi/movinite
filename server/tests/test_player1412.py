"""1.4.12: static checks -- the player's top bar fades with the controls, hidden mouse pointer, picture in picture"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from version import __version__ as VERSION
S = os.path.join(os.path.dirname(__file__), "..", "app", "static")
js = open(os.path.join(S, "app.js")).read(); css = open(os.path.join(S, "style.css")).read(); html = open(os.path.join(S, "index.html")).read()
fails = 0
def check(c, m):
    global fails
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails += 1
check(tuple(map(int, VERSION.split("."))) >= (1, 4, 12), "version >= 1.4.12")
check(".player.ov-on .pl-top{opacity:1}" in css and "pointer-events:none;opacity:0;transition:opacity .3s ease" in css, "top bar fades (opacity transition, no clicks while hidden)")
check(".player.ov-on .pl-top>*{pointer-events:auto}" in css, "top bar controls usable while shown")
check(".player:not(.ov-on),.player:not(.ov-on) *{cursor:none!important}" in css, "mouse pointer hidden with the controls")
check("top:calc(var(--pltop,56px) + 4px)" in css and '"--pltop"' in js, "status pill follows the top bar height")
check(".player:fullscreen .pl-top{" not in css, "same fade in and out of full screen (no full-screen-only rule)")
check("const held = () =>" in js and "BAR.busy()" in js and "overTop" in js, "an open menu, a drag or the mouse on a bar keeps it up (1.4.13)")
check("if (held()) arm(); else hide();" in js, "auto-hide waits while held")
check('OV.show();   // 1.4.12: any key' in js, "any key shows the controls")
check('id="pl-pip"' in html and "disablepictureinpicture" not in html, "PiP button; the video allows PiP")
check('id="pip-chip"' in html and 'id="pip-chip-back"' in html and 'id="pip-chip-close"' in html, "PiP chip: back to player / stop")
check("const PIP = (() =>" in js and "requestPictureInPicture" in js and "exitPictureInPicture" in js, "PiP via the browser API")
check('e.key === "p" || e.key === "P"' in js, "P key toggles PiP")
check("Ctrl+Shift+]" in js and "firefox" in js, "Firefox: tooltip / hint for its own PiP")
check('btn.classList.toggle("hidden", m === "none")' in js, "button hidden where PiP isn't possible")
check("enterpictureinpicture" in js and "leavepictureinpicture" in js and 'pl.classList.toggle("pip-min", on)' in js, "player steps aside in PiP and returns after")
cp = js.split("function closePlayer() {")[1].split("\n}")[0]
check("PIP.leave()" in cp, "closing the player leaves PiP")
check("PIP.minimized()" in js.split('document.addEventListener("keydown", (e) => {\n  if (!P')[1].split("\n")[0], "player keys ignored while browsing in PiP")
check("if (P) { saveProgress(); PIP.leave(); teardownVideo(true); }" in js, "starting another film from PiP is clean")
check("MSAndroid.pipAvailable" in js and "MSAndroid.pip(" in js and "MSAndroid.playing(" in js and "__msAndroidPip" in js, "Android app bridge for native PiP")
check("html.android-pip .pl-top" in css, "Android PiP window shows only the picture")
check("!!document.pictureInPictureElement" in js, "interface sounds silent while a film plays in PiP")
print("\n%d failure(s)" % fails); sys.exit(1 if fails else 0)
