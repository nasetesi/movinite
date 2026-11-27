"""2.5.1: shared glossy-gray popover chrome; exclusive-open kept; no schema bump."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "app/static/style.css").read_text()
JS = (ROOT / "app/static/app.js").read_text()
TV = (ROOT / "app/static/tv-plex.css").read_text()
CHANGELOG = (ROOT / "CHANGELOG.md").read_text()
README = (ROOT / "README.md").read_text()


def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL: " + msg)
    print("  ok", msg)


def _chunk(css, start, length=320):
    i = css.index(start)
    return css[i:i + length]


def test_version_and_schema():
    from app.version import __version__
    from app.db import SCHEMA_VERSION
    parts = tuple(int(x) for x in __version__.split(".")[:3])
    check(parts >= (2, 5, 1), "version is 2.5.1 or later, got " + __version__)
    check(SCHEMA_VERSION == 15, "schema stays at 15, got %s" % SCHEMA_VERSION)


def test_glossy_gray_tokens():
    for tok in ("--pop-bg:", "--pop-border:", "--pop-shadow:", "--pop-blur:", "--pop-radius:",
                "--pop-row-hover:", "--pop-divider:"):
        check(tok in CSS, "token %s is defined" % tok)
    bg = _chunk(CSS, "--pop-bg:", 420)
    # charcoal #2b2e35 = rgb(43,46,53); graphite #16181d = rgb(22,24,29)
    check("43,46,53" in bg and "22,24,29" in bg,
          "popover fill is charcoal-to-graphite (#2b2e35 to #16181d)")
    check("rgba(52,24,86" not in bg and "26,12,46" not in bg and "16,8,30" not in bg,
          "the 2.4.2 aubergine-to-violet fill is gone")
    check("rgba(255,255,255" in bg.split("linear-gradient")[1] if "linear-gradient" in bg else False,
          "a faint white sheen sits over the top of the fill")
    shadow = _chunk(CSS, "--pop-shadow:", 200)
    check("inset 0 1px 0 rgba(255,255,255" in shadow,
          "a 1px light inset line is on the top edge")
    check("212,187,255" not in shadow and "6,2,16" not in shadow,
          "the shadow is no longer purple-tinted")
    border = _chunk(CSS, "--pop-border:", 80)
    check("255,255,255" in border and "acc2" not in border,
          "the border is a fine light line, not a purple mix")
    hover = _chunk(CSS, "--pop-row-hover:", 80)
    check("255,255,255" in hover and "acc-rgb" not in hover,
          "hovered rows go light gray, not purple")
    div = _chunk(CSS, "--pop-divider:", 80)
    check("acc2" not in div, "dividers are not purple")
    grouped = ".ss-panel,.acct-menu,.more-menu,.ml-menu,.pl-pop,.ab-vol-pop{"
    check(grouped in CSS, "one shared rule still covers the header and page dropdowns")
    chunk = CSS[CSS.index(grouped):CSS.index(grouped) + 500]
    check("background:var(--pop-bg)" in chunk and "border:1px solid var(--pop-border)" in chunk
          and "backdrop-filter:var(--pop-blur)" in chunk and "box-shadow:var(--pop-shadow)" in chunk,
          "the shared rule applies the glossy gray chrome")
    check("var(--pop-row-hover)" in CSS, "row hover uses the shared light-gray token")
    check(".acct-menu .danger-t{color:#ff9d96}" in CSS or "danger-t{color:#ff" in CSS,
          "Sign out stays a readable red")
    check("background: rgba(22, 22, 26, .96)" in TV,
          "the TV slide-out keeps its own panel (it is not this component)")


def test_gauge_tiles_are_gray():
    i = CSS.index(".ss-gauge{")
    chunk = CSS[i:i + 500]
    check("43,46,53" in chunk and "22,24,29" in chunk,
          "CPU and RAM tiles use the same charcoal-to-graphite fill")
    check("rgba(20,10,36" not in chunk and "var(--acc)" not in chunk.split(".ss-gauge")[1][:280],
          "the purple-tinted tile backgrounds are gone")
    check("255,255,255" in chunk,
          "the tiles have a light sheen or light border")
    # rings, core bars and usage bars keep the purple accent
    check("color:var(--acc-text)" in CSS[CSS.index(".ss-ring-wrap{position"):CSS.index(".ss-ring-wrap{position") + 120],
          "the gauge rings stay purple")
    bar = CSS[CSS.index(".ss-bar i{display:block;height:100%;background:linear-gradient"):]
    bar = bar[:200]
    check("var(--acc-fill)" in bar or "var(--acc-text)" in bar,
          "usage bars keep the purple accent")
    check("var(--acc-text)" in CSS[CSS.index(".ss-cores i{"):CSS.index(".ss-cores i{") + 200]
          or "var(--acc-fill)" in CSS[CSS.index(".ss-cores i{"):CSS.index(".ss-cores i{") + 200],
          "the load bars keep the purple accent")


def test_exclusive_open_kept():
    check("function closeSiblingPops(" in JS, "closeSiblingPops is defined")
    sys = JS.split("function setSysOpen(")[1].split("function stopSysstat")[0]
    check('closeSiblingPops("sys")' in sys, "opening server status closes the other menus")
    mob = JS.split("function open(v)")[1].split("function setup()")[0]
    check('closeSiblingPops("acct")' in mob, "opening the profile menu closes the other menus")
    check('closeSiblingPops("more")' in JS, "the details More menu joins the exclusive-open set")
    check('closeSiblingPops("ml")' in JS, "the library More menu joins the exclusive-open set")


def test_docs():
    check("## 2.5.1" in CHANGELOG, "CHANGELOG has a 2.5.1 section")
    check("glossy" in CHANGELOG.split("## 2.5.1")[1].split("## 2.5 ")[0].lower()
          or "charcoal" in CHANGELOG.split("## 2.5.1")[1].split("## 2.5 ")[0].lower(),
          "CHANGELOG describes the glossy gray menus")
    check("**2.5.1:**" in README, "README What's new mentions 2.5.1")
    check("Schema stays at 15" in CHANGELOG or "schema stays at 15" in CHANGELOG.lower()
          or "No schema" in CHANGELOG.split("## 2.5.1")[1][:800],
          "CHANGELOG notes schema is unchanged")


if __name__ == "__main__":
    print("2.5.1 glossy gray popovers")
    test_version_and_schema()
    test_glossy_gray_tokens()
    test_gauge_tiles_are_gray()
    test_exclusive_open_kept()
    test_docs()
    print("all ok")
