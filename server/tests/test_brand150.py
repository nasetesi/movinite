"""1.5.0 static checks: Movinite name, purple theme (WCAG AA), icons + manifest, rotate-to-full-screen (web + Android)."""
import os, re, json, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, ".."); S = os.path.join(ROOT, "app", "static")
rd = lambda *p: open(os.path.join(*p), encoding="utf-8").read()
js, css, html = rd(S, "app.js"), rd(S, "style.css"), rd(S, "index.html")
srv, ver = rd(ROOT, "app", "server.py"), rd(ROOT, "app", "version.py")
inst, upd = rd(ROOT, "install.sh"), rd(ROOT, "update.sh")
fails = 0
def check(c, m):
    global fails
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails += 1
def lum(h):
    h = h.lstrip("#"); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
def ratio(a, b):
    la, lb = sorted([lum(a), lum(b)], reverse=True); return (la + 0.05) / (lb + 0.05)
check(tuple(int(x) for x in re.search(r'"([0-9.]+)"', ver).group(1).split(".")) >= (1, 5), "version (1, 5) or later (numeric; 1.6 > 1.5.5)")
# ---- name
check("<title>Movinite</title>" in html and 'name="application-name" content="Movinite"' in html, "page title + application-name Movinite")
check('src="/static/logo-bar.png" alt="Movinite"' in html and 'src="/static/logo-full.png" alt="Movinite"' in js and 'class="top-brand"' in html, "official logo: compact in the menu / phone top bar, full on the sign-in page")
from PIL import Image
for f, mx in [("logo-full.png", 260000), ("logo-bar.png", 80000), ("logo-mark.png", 80000)]:
    p = os.path.join(S, f); im = Image.open(p)
    check(im.mode in ("RGBA", "P") and os.path.getsize(p) < mx, "%s: transparent background, %d KB" % (f, os.path.getsize(p) // 1024))
check(Image.open(os.path.join(S, "logo-bar.png")).height >= 90, "top-bar logo sharp at 3x (30 px tall)")
check("Movinite" in srv and 'title="Movinite"' in srv, "API title / start log say Movinite")
check("Media Server" not in html and not re.search(r'["`>]Media Server', js), "no visible 'Media Server' left in the web app")
check("Movinite" in inst and "Movinite" in upd, "install.sh / update.sh messages say Movinite")
check('APP_NAME="media-server"' in inst and "/opt/media-server" in inst and 'SVC_USER="media-server"' in inst, "internal names (service, folder) unchanged")
# ---- purple + contrast
root = css.split(":root", 1)[1].split("}", 1)[0]
v = dict(re.findall(r"--([\w-]+):\s*([^;]+);", root))
check(v.get("acc", "").upper() == "#9637FA" and v.get("acc-fill", "").upper() == "#8424EA" and v.get("acc-text", "").upper() == "#B07CFF", "theme variables from the logo: #9637FA / #8424EA / #B07CFF")
check("#e5a00d" not in root.lower().replace("--warn:#e5a00d", ""), "amber only kept as the warning colour")
check(v.get("warn", "").lower() == "#e5a00d", "warnings keep amber")
check(ratio("#FFFFFF", v["acc-fill"]) >= 4.5, "white on filled purple buttons %.1f:1 (AA)" % ratio("#FFFFFF", v["acc-fill"]))
check(ratio("#FFFFFF", v["acc-fill-h"]) >= 4.5, "white on hovered buttons %.1f:1 (AA)" % ratio("#FFFFFF", v["acc-fill-h"]))
bg = re.search(r"--bg:\s*(#[0-9a-fA-F]{6})", root); panel = re.search(r"--panel:\s*(#[0-9a-fA-F]{6})", root)
for nm, m in [("page", bg), ("panel", panel)]:
    if m: check(ratio(v["acc-text"], m.group(1)) >= 4.5, "purple text on the %s %.1f:1 (AA)" % (nm, ratio(v["acc-text"], m.group(1))))
check("rgba(229,160,13" not in css.replace(" ", "") or css.count("rgba(229,160,13") <= 0, "no hard-coded amber tints left (use --acc-rgb)")
check("rgba(var(--acc-rgb)" in css, "tints use --acc-rgb")
check("::selection" in css, "text selection purple")
# ---- icons + manifest
ico = open(os.path.join(S, "favicon.ico"), "rb").read()
check(ico[:4] == b"\x00\x00\x01\x00" and int.from_bytes(ico[4:6], "little") == 3, "favicon.ico with 16/32/48")
check(not os.path.exists(os.path.join(S, "favicon.svg")), "old generated favicon.svg gone")
for f, n in [("favicon-16.png", 16), ("favicon-32.png", 32), ("favicon-48.png", 48), ("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512), ("icon-maskable-512.png", 512)]:
    check(Image.open(os.path.join(S, f)).size == (n, n), "%s is %dx%d" % (f, n, n))
mk = Image.open(os.path.join(S, "icon-maskable-512.png")).convert("RGBA")
check(all(mk.getpixel(c)[3] == 255 for c in [(0, 0), (511, 0), (0, 511), (511, 511)]), "maskable icon is full-bleed (no transparent corners)")
px = [mk.getpixel((x, y)) for x in range(512) for y in (60,)]  # a row in the outer 12 %: background only
check(max(p[0] + p[1] + p[2] for p in px) < 200, "maskable icon: the M stays inside the safe zone")
for f in ["icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png"]:
    p = os.path.join(S, f); check(os.path.exists(p) and open(p, "rb").read(8) == b"\x89PNG\r\n\x1a\n", "icon " + f)
m = json.loads(rd(S, "manifest.webmanifest"))
check(m.get("name") == "Movinite" and m.get("theme_color", "").lower() == "#0b0612" and any(i.get("purpose") == "maskable" for i in m["icons"]), "manifest: Movinite, purple, maskable icon")
check('rel="manifest"' in html and 'rel="icon"' in html and "apple-touch-icon" in html and 'name="theme-color" content="#0b0612"' in html, "index.html links manifest/icons + theme colour")
check("application/manifest+json" in srv, "manifest served with its MIME type")
# ---- rotate to full screen
rot = js.split("const ROT = (() =>", 1)[1].split("const OV = (() =>", 1)[0] if "const ROT = (() =>" in js else ""
check(bool(rot), "ROT module present")
check("(hover: none) and (pointer: coarse)" in rot, "only on touch devices (never desktop)")
check('screen.orientation.addEventListener("change"' in rot and "orientationchange" in rot and '"(orientation: landscape)"' in rot, "listens to orientation changes (3 ways)")
check("requestFullscreen" in rot and "pl-pseudo-fs" in rot, "real full screen, CSS fallback")
check('addEventListener("pointerup"' in rot, "a tap retries real full screen while on the fallback")
check("manual = true" in rot and "if (!force && l === last) return;" in rot, "leaving full screen by hand is respected until the next rotation")
check("ROT.open()" in js and "ROT.close()" in js and "ROT.manualExit()" in js, "player open / close / full-screen button wired")
check("MSAndroid.player" in rot, "tells the Android app (1.4+) when the player opens / closes")
check("html.pl-pseudo-fs #player" in css and "100dvh" in css, "pseudo full screen CSS")
# ---- Android source (if this copy ships it)
A = os.environ.get("ANDROID_SRC", "/workspace/media-server/android/src")
if os.path.isdir(A):
    R = os.path.join(A, "app", "src", "main"); g = rd(A, "app", "build.gradle"); ma = rd(R, "java", "com", "tukuia", "mediaserver", "MainActivity.java")
    _vc = re.search(r"versionCode (\d+)", g); _vn = re.search(r"versionName '1\.(\d+)'", g)
    check(_vc and int(_vc.group(1)) >= 5 and _vn and int(_vn.group(1)) >= 4 and "com.tukuia.mediaserver" in g, "Android: 1.4+ (code %s), same package" % (_vc and _vc.group(1)))   # 1.5.1: app 1.5 = code 6
    check('<string name="app_name">Movinite</string>' in rd(R, "res", "values", "strings.xml"), "Android: app name Movinite")
    check("#9637FA" in rd(R, "res", "values", "colors.xml") and os.path.exists(os.path.join(R, "res", "drawable-nodpi", "logo.png")) and not os.path.exists(os.path.join(R, "res", "drawable", "logo.xml")), "Android: logo purple + the official M mark (no wording)")
    for d in ["mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi"]:
        check(all(os.path.exists(os.path.join(R, "res", "mipmap-" + d, f)) for f in ["ic_launcher.png", "ic_launcher_round.png", "ic_launcher_foreground.png", "ic_launcher_monochrome.png"]), "Android: launcher icons for " + d)
    check("SCREEN_ORIENTATION_FULL_SENSOR" in ma and "onConfigurationChanged" in ma and "public void player(boolean open)" in ma, "Android: follows rotation while the player is open, immersive sideways")
    check("movinite-android-v" in rd(A, "build-apk.sh"), "Android: APK named movinite-android-v*.apk")
print("\n%s (%d failed)" % ("PASS" if not fails else "FAIL", fails)); sys.exit(1 if fails else 0)
