"""1.4.13 static checks: bottom control bar (Quality, Subtitles, Audio, PiP, Full screen), see-through look."""
import os, re
B = os.path.join(os.path.dirname(__file__), "..", "app")
html = open(os.path.join(B, "static", "index.html")).read()
css = open(os.path.join(B, "static", "style.css")).read()
js = open(os.path.join(B, "static", "app.js")).read()
ver = open(os.path.join(B, "version.py")).read()
fails = 0
def check(c, m):
    global fails
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails += 1
check(tuple(int(x) for x in re.search(r'"([0-9.]+)"', ver).group(1).split(".")) >= (1, 4, 13), "version 1.4.13 or later")
bar = html[html.index('id="pl-bar"'):html.index('id="pl-pop"')]
order = [bar.index('id="%s"' % i) for i in ("pl-seek", "pl-bplay", "pl-bback", "pl-bfwd", "pl-mute", "pl-vol", "pl-time", "pl-bq", "pl-bcc", "pl-baud", "pl-pip", "pl-fs")]
check(order == sorted(order), "bottom bar order: seek, play, -10, +10, volume, time ... Quality, CC, Audio, PiP, Full screen")
top = html[html.index('class="pl-top"'):html.index('id="pl-bar"')]
check('id="pl-close"' in top and 'id="pl-title"' in top and 'id="pl-pip"' not in top, "top bar keeps close + title only")
check('class="pl-opts" hidden' in html and all('id="%s"' % s in top for s in ("pl-quality", "pl-audio", "pl-subs")), "the three selects stay as hidden state holders")
check('role="slider"' in bar and 'id="pl-buf"' in bar and 'id="pl-tip"' in bar, "seek slider with buffered range and hover time")
check('role="menu"' in html and 'id="pl-pop"' in html, "one popover for the menus")
m = re.search(r"\n\.pl-bar\{[^}]*\}", css); bc = m.group(0) if m else ""
check("rgba(0,0,0,.45)" in bc and "linear-gradient(rgba(0,0,0,0)" in bc and "background:#" not in bc, "bar: no solid background, soft transparent -> .45 gradient")
m = re.search(r"\.pl-cb\{[^}]*\}", css); cb = m.group(0) if m else ""
check("rgba(0,0,0,.3)" in cb and "blur(8px)" in cb and "border-radius:999px" in cb and "44px" in cb, "buttons: translucent 44 px circles/pills with blur")
check("drop-shadow(0 1px 2px rgba(0,0,0,.55))" in css, "white icons with a soft shadow")
m = re.search(r"\.pl-pop\{[^}]*\}", css); pc = m.group(0) if m else ""
check("rgba(20,20,20,.55)" in pc and "blur(14px)" in pc, "popover: rgba(20,20,20,.55) with blur")
check("text-shadow" in css[css.index(".pl-bar"):], "text shadow for bright scenes")
check(".player:not(.ov-on)" in css or ".player.ov-on .pl-bar{opacity:1}" in css, "bar fades with the overlay")
check("(max-width:640px),(pointer:coarse) and (max-width:900px)" in css and ".pl-wide-only" in css, "phone: compact bar")
check("html.android-pip .pl-bar,html.android-pip .pl-pop{display:none!important}" in css, "hidden in Android PiP")
check(".pl-status:empty{display:none}" in css, "no empty status pill")
check("const BAR = (() =>" in js and "function openPop(" in js and "function closePop(" in js, "BAR module with popovers")
check("RATES" in js and "defaultPlaybackRate" in js, "playback speed inside the Quality menu")
check('localStorage.setItem("pl-vol"' in js or "pl-vol" in js and "pl-muted" in js, "volume / mute remembered")
check("dispatchEvent(new Event(\"change\"))" in js, "menu picks drive the existing select handlers")
check("video.controls = false" in js and "video.controls = true" not in js, "no native controls")
check("P.lastSave = 0" in js, "a seek saves the resume point")
check("function liftCues(" in js and 'c.line = "auto"' in js, "subtitles lift above the bar while it shows")
check("langName(" in js and "Intl.DisplayNames" in js, "subtitle codes shown as language names")
check('e.key === "Escape" && BAR.popOpen()' in js, "Esc closes a menu before the player")
check("shutAt" in js, "a click outside an open menu only closes it")
print("%d failure(s)" % fails)
raise SystemExit(1 if fails else 0)
