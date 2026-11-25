"""1.4.8: static checks -- interface sounds (Web Audio, no audio files), top-bar toggle, Sounds settings panel"""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from version import __version__ as VERSION
S = os.path.join(os.path.dirname(__file__), "..", "app", "static")
js = open(os.path.join(S, "app.js")).read(); css = open(os.path.join(S, "style.css")).read(); html = open(os.path.join(S, "index.html")).read()
fails = 0
def check(c, m):
    global fails
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails += 1
check(tuple(map(int, VERSION.split("."))) >= (1, 4, 8), "version >= 1.4.8")
check("const SFX_BUILD" in js and "const SFX = (" in js, "SFX module present")
for k in ("hover(ctx", "select(ctx", "play(ctx", "arrow(ctx"):
    check(k in js, "synth builder " + k.split("(")[0])
check(not re.search(r"\.(wav|mp3|ogg)\b", js) and not any(f.endswith((".wav", ".mp3", ".ogg")) for f in os.listdir(S)), "no audio files shipped / referenced")
check(re.search(r'\["pointerdown", "keydown", "touchend"\]\.forEach\(ev => window\.addEventListener\(ev, unlock', js) is not None, "AudioContext created only on a user gesture")
check("new AC()" in js and js.count("new AC()") == 1 and js.index("new AC()") > js.index("function unlock()"), "AudioContext constructed only inside unlock()")
check('ctx.state !== "running"' in js, "silently skips while locked/suspended")
check("now - lastHover < 70" in js, "hover throttled to 70 ms")
check("Math.random() * 2 - 1" in js, "hover pitch varies")
check('matchMedia("(hover: none), (pointer: coarse)")' in js and "select: !COARSE" in js, "touch devices: no hover sounds, tap sounds off by default")
check('e.pointerType && e.pointerType !== "mouse"' in js, "hover sound only for a mouse pointer")
check(':focus-visible' in js and 'focusin' in js, "keyboard focus ticks")
check('vol: 0.3' in js and 'on: true' in js, "default on at low volume (30%)")
check('"ms-sound:" + (user' in js and "SFX.load(ME.username)" in js, "settings per user in localStorage")
check('p.classList.contains("hidden")' in js and "playing()" in js, "no sounds while the video player is open")
check('if (c.classList.contains("card")) SFX.select()' in js, "select chime when a poster opens")
check("SFX.play(); playItem(+pl.dataset.play)" in js and "SFX.play(); playItem(id, 0)" in js and "SFX.play(); playItem(id, it.position)" in js, "play sound on quick-play, Play and Resume")
check("SFX.arrow(-1); page(-1)" in js and "SFX.arrow(1); page(1)" in js, "swish on < >")
check('id="sndbtn"' in html and html.index('id="sndbtn"') < html.index('id="sysstat"'), "speaker toggle in the top bar, before the server status")
check('$("#sndbtn").onclick = () => SFX.toggle()' in js and "aria-pressed" in js, "toggle wired, aria-pressed kept in sync")
for i in ("snd-on", "snd-hover", "snd-select", "snd-vol", "snd-test"):
    check(('id="%s"' % i in js) or ('swr("%s"' % i in js), "settings control #" + i)
check(".snd-btn{" in css and ".snd-vol" in css, "css for toggle and panel")
print("FAILS:", fails); sys.stdout.flush(); os._exit(1 if fails else 0)
