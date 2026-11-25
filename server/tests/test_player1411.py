"""1.4.11: static checks -- on-screen player controls (tap to show, skip 10 s, double-tap), see-through server status, player full screen"""
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
check(tuple(map(int, VERSION.split("."))) >= (1, 4, 11), "version >= 1.4.11")
for i in ("pl-stage", "pl-tap", "pl-ov", "pl-back", "pl-pp", "pl-fwd", "pl-ss", "pl-rip-l", "pl-rip-r", "pl-fs"):
    check('id="%s"' % i in html, "player has #%s" % i)
st = html.split('id="pl-stage"')[1].split('<div id="audiobar"')[0]
check('id="video"' in st and 'id="pl-ss"' in st and 'id="pl-ov"' in st, "video, buttons and status share one box inside #player (so they go full screen together)")
check('controlslist="nofullscreen' in html, "native video full screen button off (it would hide the overlays)")
check("pl.requestFullscreen || pl.webkitRequestFullscreen" in js and "video.webkitEnterFullscreen" in js, "full screen = the whole player; iPhone falls back to the bare video")
check("function skip(d, side)" in js and "Math.min(t, Math.max(0, dur - 0.5))" in js and "t = Math.max(0, t)" in js, "skip clamps to 0 .. end")
check("P.lastSave = 0;" in js.split("function skip(d, side)")[1][:900], "skip saves the resume point on the next timeupdate")
check('skip(10, "right")' in js and 'skip(-10, "left")' in js, "Left / Right arrows skip 10 s")
check('if (e.target.tagName === "BUTTON" && e.key === " ") return;' in js, "Space on a focused button isn't handled twice")
check(("hideT = setTimeout(hide, 3000)" in js or "hideT = setTimeout(() => { if (held()) arm(); else hide(); }, 3000)" in js) and "if (!video.paused)" in js, "auto-hide after 3 s while playing, stays while paused")
check('e.stopPropagation(); fn();' in js, "button taps don't reach the tap layer")
check('now - lastTap < 320' in js and "tapT = setTimeout" in js, "double-tap left/right skips, single tap waits for it")
check(".player.ov-on .pl-bar .pl-seek" in css and "pointer-events:auto" in css, "seek bar stays usable while shown (1.4.13: own bottom bar)")
check(".pl-big{" in css and "width:64px;height:64px" in css and "rgba(0,0,0,.45)" in css, "big round see-through buttons, >= 56 px")
check((".pl-ss{" in css and "backdrop-filter:blur(" in css.split(".pl-ss{")[1][:500] and ".player.ov-on .pl-ss{opacity:1}" in css), "status panel: translucent/blurred, fades with the buttons")
r = js.split("function renderPlayerStat()")[1].split("function renderSysPanel")[0]
check("api(" not in r and "fetch(" not in r and "setTimeout" not in r and "setInterval" not in r, "player status makes no requests of its own (reuses the 4 s top-bar poll)")
check("ME.show_status" in r and "!P" in r, "status only for people allowed to see it, only while a video is open")
check("renderPlayerStat();\n}" in js.split("function renderSysstat()")[1].split("function renderPlayerStat")[0], "refreshed with every top-bar update")
check("OV.reset();" in js.split("function closePlayer()")[1][:300], "closing the player resets the overlay")
check('const playing = () => { const p = document.getElementById("player"); return !!(p && !p.classList.contains("hidden"))' in js, "1.4.8 sounds still silent while the player is open")
print("FAILS:", fails); sys.stdout.flush(); os._exit(1 if fails else 0)
