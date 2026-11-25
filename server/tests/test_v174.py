"""1.7.4: outlined purple library icons replace the emoji, everywhere they appear.

    python3 tests/test_v174.py
"""
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
js = (ROOT / "app/static/app.js").read_text()
css = (ROOT / "app/static/style.css").read_text()
ver = (ROOT / "app/version.py").read_text()
server = (ROOT / "app/server.py").read_text()

fails = []


def check(ok, msg):
    print(("  ok - " if ok else "  FAIL - ") + msg, flush=True)
    if not ok:
        fails.append(msg)


def main():
    check(tuple(int(x) for x in __import__("re").search(r'__version__ = "([0-9.]+)"', ver).group(1).split(".")) >= (1, 7, 4), "version is 1.7.4 or later")
    check((ROOT / "install.sh").is_file() and (ROOT / "update.sh").is_file(),
          "install.sh and update.sh are still in the tree")

    print("outlined icons in app.js")
    check("const ico = (body)" in js and "viewBox=\"0 0 24 24\"" in js
          and "stroke=\"currentColor\"" in js and "stroke-width=\"1.75\"" in js,
          "ico() helper draws 24px-grid currentColor outlined SVGs")
    for kind, token in (
        ("movies", "M5.25 10.25h12.5"),
        ("tv", "M5 3.75h14"),
        ("music", 'cx="8.35" cy="17.35"'),
        ("other", "M3.55 8.45h11.15"),
    ):
        check(f"{kind}:" in js[js.index("const KIND_ICON"):js.index("const KIND_ICON") + 4000]
              and token in js, "KIND_ICON.%s uses the outlined SVG" % kind)
    kind_src = js[js.index("const KIND_ICON"):js.index("};", js.index("const KIND_ICON")) + 2]
    check("&#127916;" not in kind_src and "&#128250;" not in kind_src
          and "&#127925;" not in kind_src and "&#128193;" not in kind_src
          and "k-ic" in kind_src and "${ico(`" in kind_src,
          "KIND_ICON is outlined ico() SVGs, not the old emoji")
    check("KIND_ICON[l.kind] || KIND_ICON.other" in js, "unknown kinds fall back to the Videos icon")

    print("share / local headings")
    ico_block = js[js.index("const ICO_SHARE"):js.index("const ICO_SHARE") + 1600]
    check("M4.25 3.85h15.5" in ico_block and "cy=\"7.8\"" in ico_block,
          "ICO_SHARE is the outlined stacked-rack SVG")
    check("M4.25 3.35h15.5" in ico_block and "M8.4 19.7h7.2" in ico_block,
          "ICO_LOCAL is the outlined monitor + keyboard SVG")
    check("width=\"14\" height=\"14\"" not in ico_block,
          "heading icons are sized by CSS, not a hardcoded 14px")

    print("everywhere the icons appear")
    check('id="navlibs"' not in js or "KIND_ICON[l.kind]" in js,
          "sidebar / grouped nav uses KIND_ICON")
    check('class="lib-ic"' in js and "KIND_ICON[l.kind]" in js, "Libraries tab rows use KIND_ICON")
    check("lib-head" in js and "KIND_ICON[lib.kind]" in js, "library page headings use KIND_ICON")
    check("${KIND_ICON.movies}<span>Movies</span>" in js
          and "${KIND_ICON.tv}<span>TV shows</span>" in js
          and "${KIND_ICON.music}<span>Music</span>" in js
          and "${KIND_ICON.other}<span>Other videos</span>" in js,
          "Add library type picker includes the outlined icons")
    check('b.querySelector("span") || b).textContent.trim()' in js,
          "Add library auto-name uses the label, not the SVG")

    print("theme CSS")
    check(".lib-ic" in css and "color:var(--acc-text)" in css
          and ".lib-ic .k-ic,.lib-ic svg{width:28px;height:28px}" in css,
          "Libraries row icons are 28px in --acc-text")
    check(".k-ic{" in css and "color:var(--acc-text)" in css, ".k-ic carries the accent colour")
    check(".side nav a .k-ic svg{width:16px;height:16px}" in css, "sidebar icons are 16px")
    check(".ng-ic" in css and "color:var(--acc-text)" in css
          and ".ng-ic svg{display:block;width:16px;height:16px;overflow:visible}" in css,
          "share / this-server heading icons are 16px in the accent colour")
    check(".seg#al-kind button{display:inline-flex;align-items:center;gap:8px}" in css,
          "Add library type buttons lay out the icon and label")

    print("cache-busting")
    check("?v=%s" in server and "sw.js?v=%s" in server,
          "server stamps static assets and sw.js with the running version")
    check(tuple(int(x) for x in __import__("re").search(r'__version__ = "([0-9.]+)"', ver).group(1).split(".")) >= (1, 7, 4), "stamped version is 1.7.4 or later")


main()
print("FAILS: %d" % len(fails) if fails else "ALL OK")
raise SystemExit(1 if fails else 0)
