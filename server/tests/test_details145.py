"""1.4.5: static checks for the details page clean-up -- no File & playback section, no Admin card, a "..." menu with
the admin actions (admins only) plus Download / TMDB / File info, the review badge inside the menu only, and bigger
Similar movies posters. Browser behaviour is covered by the Playwright UI test.

    python3 tests/test_details145.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.version import __version__ as VERSION  # noqa: E402

js = (ROOT / "app/static/app.js").read_text()
css = (ROOT / "app/static/style.css").read_text()
vi = js[js.index("async function viewItem(id) {"):js.index("// 1.4.3: an actor / director")]
fails = 0


def check(ok, msg):
    global fails
    print(("  ok - " if ok else "  FAIL - ") + msg)
    fails += 0 if ok else 1


check(tuple(map(int, VERSION.split("."))) >= (1, 4, 5), "version 1.4.5 or later")
check('class="dsec fileinfo"' not in vi and "File &amp; playback" not in vi, "File & playback section removed from the page")
check('class="dsec admin"' not in vi and "<h3>Admin</h3>" not in vi, "Admin card removed")
check('class="review-box"' not in vi, "no review box on the page")
check('id="more"' in vi and 'aria-haspopup="menu"' in vi and "${moreMenu}" in vi, "'...' menu button in the main actions")
check(vi.index("${moreMenu}") > vi.index('id="watched"'), "'...' sits after Mark watched")
check("const adminItems = !ME.is_admin ? [] :" in vi, "admin items only for admins")
for ident, name in (("fixmatch", "Fix match"), ("homerows", "Home rows"), ("addtag2", "+ Tag"), ("fileinfo", "File info")):
    check('mi("%s"' % ident in vi, "menu item: " + name)
check('"Artwork settings"' in vi and "file?download=1" in vi and "tmdb_url" in vi, "menu items: Artwork settings, Download, TMDB link")
check('class="mbadge"' in vi and "Needs review" in vi, "review notice is a badge in the menu")
check('mi("accept-cand"' in vi and 'mi("confirm-match"' in vi, "review actions (Accept suggestion / Looks right) kept in the menu")
check('modal(`<h2>File info</h2>' in vi and "Resolution" in vi and "Container" in vi, "File info opens a small window")
check("function bindMoreMenu()" in js and '"Escape"' in js and '"ArrowDown"' in js, "menu: keyboard and Esc support")
check('class="strip sim"' in vi, "Similar movies uses the bigger strip")
m = re.search(r"\.strip\.sim\{grid-auto-columns:clamp\((\d+)px,[\d.]+vw,(\d+)px\)", css)
check(m is not None and int(m.group(2)) >= 200, "Similar posters up to %s px wide (was 150)" % (m and m.group(2)))
check(".cast-strip{display:grid;grid-auto-flow:column;grid-auto-columns:124px" in css, "cast size unchanged")
check(".more-menu[hidden]{display:none}" in css, "menu hidden until opened")
check('resName(1920' not in js and "function resName(w, h)" in js, "resolution label uses width too")
print("details145: %d failure(s)" % fails)
sys.exit(1 if fails else 0)
