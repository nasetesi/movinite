"""1.4.9: static checks -- admin-only "..." menu (UI + server), < > arrows on touch screens, mobile-friendly Settings"""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from version import __version__ as VERSION
A = os.path.join(os.path.dirname(__file__), "..", "app")
js = open(os.path.join(A, "static", "app.js")).read(); css = open(os.path.join(A, "static", "style.css")).read(); srv = open(os.path.join(A, "server.py")).read()
fails = 0
def check(c, m):
    global fails
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails += 1
check(tuple(map(int, VERSION.split("."))) >= (1, 4, 9), "version >= 1.4.9")
check('const moreMenu = !ME.is_admin ? "" :' in js, '"..." menu rendered for admins only')
check('if ($("#fileinfo")) $("#fileinfo").onclick' in js, "no File info binding without the menu")
check('raise HTTPException(403, "Only admins can download files")' in srv and srv.index("Only admins can download") > srv.index("def direct_file"), "server: download=1 is admin-only")
check('out["filename"] = os.path.basename(it["path"]) if u["is_admin"] else None' in srv, "server: file name hidden from non-admins")
check('out["folder"] = os.path.dirname(it["path"]) if u["is_admin"] else None' in srv, "server: folder still hidden from non-admins")
for fn in ("pin_item", "apply_tags", "match_item", "match_show", "put_settings"):
    m = re.search(r"def %s\(.*?\):\n" % fn, srv)
    check(m and "require_admin" in m.group(0), "server: %s needs an admin" % fn)
check("@media (hover:none) and (pointer:coarse){.hnav{display:none}}" not in css, "arrows no longer hidden on touch screens")
m = re.search(r"/\* 1\.4\.9: < > row buttons on phones.*?\n@media \(hover:none\),\(pointer:coarse\)\{(.*?)\n\}", css, re.S)
check(m and "width:44px;height:44px" in m.group(1) and ".hnav.prev{left:-6px}" in m.group(1), "touch arrows are 44 px and inside the screen")
check(m and ".hnav:hover{" in m.group(1) and "transform:none" in m.group(1), "no sticky hover on touch")
check('v.dataset.view = parts[0] || "home"' in js, "#view knows which page it shows")
check('class="tabs set-tabs" role="tablist"' in js and 'aria-selected=' in js, "settings tabs are a tablist")
check("function settingsMobile(v)" in js and 'setAttribute("data-label"' in js, "table cells labelled for stacked cards")
check(".set-tabs{flex-wrap:nowrap;overflow-x:auto" in css and "scroll-snap-type:x proximity" in css, "tabs: one swipeable line on phones")
check(".set-tabs button{flex:none;min-height:44px" in css, "tabs: 44 px tap targets")
check("width:100%!important;max-width:none!important;min-height:44px" in css, "inputs full width, 44 px")
check("table.stack-tbl tr.thead-row{display:none}" in css and "content:attr(data-label)" in css, "tables become cards")
check('<label class="chk"><input type="checkbox" id="te"' in js and ('<label class="chk"><input type="checkbox" id="nua"' in js or '<select id="nur">' in js), "checkbox text is tappable (1.9: the admin checkbox became a role picker)")
print("FAILS:", fails); sys.stdout.flush(); os._exit(1 if fails else 0)
