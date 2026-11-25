"""1.4.10: static checks -- settings cards on phones: multi-part values stacked, no mid-word breaks, tidy buttons"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from version import __version__ as VERSION
S = os.path.join(os.path.dirname(__file__), "..", "app", "static")
js = open(os.path.join(S, "app.js")).read(); css = open(os.path.join(S, "style.css")).read()
fails = 0
def check(c, m):
    global fails
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails += 1
check(tuple(map(int, VERSION.split("."))) >= (1, 4, 10), "version >= 1.4.10")
check('function wbrPath(p) { return esc(p || "").replace(/\\//g, "/<wbr>"); }' in js, "paths get a break opportunity after each /")
check("${wbrPath(l.share.remote)}" in js and "${wbrPath(l.path)}" in js and "${wbrPath(s.data_dir)}" in js, "share, library path and data folder use it")
check('<span class="chip ok pill">mounted &middot; ${l.share.mount_mode === "rw" ? "writable" : "read-only"}</span>' in js, "compact 'mounted · writable' pill")
check(".chip.pill{white-space:nowrap" in css, "pill never wraps")
check("word-break:break-all" not in css.split(".aw-code")[0] and ".lib-tbl .src .help{word-break:normal" in css, "no break-all on library paths / System values")
check(".tech b{color:var(--text);font-weight:500;word-break:normal" in css, "System values wrap between words")
check('cv.className = "cv"' in js and 'td.classList.toggle("multi"' in js, "cell values wrapped; multi-part cells marked")
check("table.stack-tbl td.multi{display:block" in css and "td.multi::before{display:block" in css, "multi-part: label on top, value full width")
check("flex-direction:column" in css.split("1.4.10: settings cards")[1], "parts stack vertically")
check(".row-actions{display:grid;grid-template-columns:repeat(auto-fill,minmax(112px,1fr))" in css and ".row-actions .btn.danger{grid-column:1/-1}" in css, "library buttons in a grid, Remove on its own last row")
check('td.classList.add("btns")' in js and "td.btns .btn.danger{grid-column:1/-1}" in css, "other button cells tidy too")
print("FAILS:", fails); sys.stdout.flush(); os._exit(1 if fails else 0)
