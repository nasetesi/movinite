"""2.4.2: shared purple popover chrome; opening one dropdown closes the other."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "app/static/style.css").read_text()
JS = (ROOT / "app/static/app.js").read_text()
TV = (ROOT / "app/static/tv-plex.css").read_text()

def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL: " + msg)
    print("  ok", msg)


def test_version():
    from app.version import __version__
    parts = tuple(int(x) for x in __version__.split(".")[:3])
    check(parts >= (2, 4, 2), "version is 2.4.2 or later, got " + __version__)


def test_shared_tokens():
    from app.version import __version__
    parts = tuple(int(x) for x in __version__.split(".")[:3])
    for tok in ("--pop-bg:", "--pop-border:", "--pop-shadow:", "--pop-blur:", "--pop-radius:",
                "--pop-row-hover:", "--pop-divider:"):
        check(tok in CSS, "token %s is defined" % tok)
    bg = CSS[CSS.index("--pop-bg:"):CSS.index("--pop-bg:") + 280]
    check("linear-gradient(" in bg, "popover fill is a gradient")
    check("inset 0 1px 0" in CSS[CSS.index("--pop-shadow:"):CSS.index("--pop-shadow:") + 200],
          "a soft inner highlight is on the shadow")
    grouped = ".ss-panel,.acct-menu,.more-menu,.ml-menu,.pl-pop,.ab-vol-pop{"
    check(grouped in CSS, "one shared rule covers the header and page dropdowns")
    chunk = CSS[CSS.index(grouped):CSS.index(grouped) + 400]
    check("background:var(--pop-bg)" in chunk and "border:1px solid var(--pop-border)" in chunk
          and "backdrop-filter:var(--pop-blur)" in chunk and "box-shadow:var(--pop-shadow)" in chunk,
          "the shared rule applies the glass chrome")
    check("var(--pop-row-hover)" in CSS, "row hover uses the shared token")
    check("var(--pop-divider)" in CSS, "dividers use the shared rule")
    check(".acct-menu .danger-t{color:#ff9d96}" in CSS or "danger-t{color:#ff" in CSS,
          "Sign out stays a readable red")
    # individual menus no longer carry the pre-2.4.2 solid gray fill
    acct = CSS[CSS.index(".acct-menu{position:absolute"):CSS.index(".acct-menu{position:absolute") + 280]
    check("rgba(23,26,33" not in acct and "var(--line)" not in acct,
          "the profile menu no longer uses the old solid gray panel fill")
    check("background: rgba(22, 22, 26, .96)" in TV,
          "the TV slide-out keeps its own panel (it is not this component)")
    if parts < (2, 5, 1):
        check("rgba(52,24,86" in bg, "popover fill is a deep purple gradient")
        check("var(--acc-rgb)" in CSS[CSS.index("--pop-row-hover:"):CSS.index("--pop-row-hover:") + 80],
              "row hover uses the shared purple tint")


def test_exclusive_open():
    check("function closeSiblingPops(" in JS, "closeSiblingPops is defined")
    sys = JS.split("function setSysOpen(")[1].split("function stopSysstat")[0]
    check('closeSiblingPops("sys")' in sys, "opening server status closes the other menus")
    mob = JS.split("function open(v)")[1].split("function setup()")[0]
    check('closeSiblingPops("acct")' in mob, "opening the profile menu closes the other menus")
    check('closeSiblingPops("more")' in JS, "the details More menu joins the exclusive-open set")
    check('closeSiblingPops("ml")' in JS, "the library More menu joins the exclusive-open set")


def test_241_kept():
    check("function shortGpuName(" in JS, "2.4.1 short GPU names remain")
    check("minmax(0,1fr) minmax(0,1fr)" in CSS, "2.4.1 stats grid shrink remains")


if __name__ == "__main__":
    print("2.4.2 shared popovers")
    test_version()
    test_shared_tokens()
    test_exclusive_open()
    test_241_kept()
    print("all ok")
