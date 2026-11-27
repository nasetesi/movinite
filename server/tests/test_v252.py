"""2.5.2: phone details header is transparent over the backdrop, then frosted on scroll."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "app/static/style.css").read_text()
JS = (ROOT / "app/static/app.js").read_text()
HTML = (ROOT / "app/static/index.html").read_text()
CHANGELOG = (ROOT / "CHANGELOG.md").read_text()
README = (ROOT / "README.md").read_text()


def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL: " + msg)
    print("  ok", msg)


def test_version_and_schema():
    from app.version import __version__
    from app.db import SCHEMA_VERSION
    check(__version__ == "2.5.2", "version is 2.5.2, got " + __version__)
    check(SCHEMA_VERSION == 15, "schema stays at 15, got %s" % SCHEMA_VERSION)


def test_css_phone_only():
    check("@media (max-width:820px)" in CSS and "html.detail-top:not(.tv-mode) .top{" in CSS,
          "the transparent header is limited to phone widths and not TV")
    start = CSS.index("/* 2.5.2:")
    chunk = CSS[start:]
    phone = chunk[chunk.index("@media (max-width:820px)"):chunk.index("@media (min-width:821px)")]
    check("background:transparent" in phone,
          "at the top of a details page the phone header is transparent")
    check("linear-gradient(180deg,rgba(0,0,0," in phone,
          "a dark top-down scrim keeps the icons readable")
    check("drop-shadow(" in phone and "text-shadow:" in phone,
          "icons and status text have a shadow")
    check("html.detail-top.detail-top-scrolled:not(.tv-mode) .top{" in phone,
          "a scrolled class switches the header to frosted glass")
    check("var(--detail-tint" in phone and "backdrop-filter:blur(" in phone,
          "the scrolled bar is frosted and uses the artwork tint, with a dark fallback")
    check(".detail-bg-phone{display:none}" in chunk,
          "show-page phone-only blurs are hidden on desktop")
    # desktop / TV chrome stays as it was
    check("html.tv-mode .top{background:var(--panel);border-bottom:1px solid var(--line)" in CSS,
          "the TV top bar stays a solid panel")
    top_desktop = CSS[CSS.index(".top{position:absolute;left:0;right:0;top:0;z-index:25;display:flex"):]
    top_desktop = top_desktop[:top_desktop.index("}")]
    check("background:var(--panel)" in top_desktop,
          "the default (desktop) top bar is still the solid panel")


def test_js_hooks():
    check("function setDetailTop(" in JS, "setDetailTop is defined")
    check("function clearDetailTop(" in JS, "clearDetailTop is defined")
    check("function extractDetailTint(" in JS, "the tint is taken from the backdrop in the browser")
    check("getImageData(" in JS and "getContext(\"2d\"" in JS,
          "average color is read from a canvas")
    check("function syncDetailTopScroll(" in JS and "detail-top-scrolled" in JS,
          "scrolling toggles the frosted state")
    check("clearDetailTop();" in JS.split("function route()")[1].split("try {")[0],
          "leaving a page clears the details header")
    item = JS.split("async function viewItem")[1].split("async function viewPerson")[0]
    check("setDetailTop(bgImg ? thumbUrl(bgImg) : null)" in item,
          "movie and shared-title details enable the header when there is artwork")
    show = JS.split("async function viewShow")[1].split("async function viewAlbum")[0]
    check("detail-bg detail-bg-phone" in show, "show pages get a phone-only backdrop blur")
    check("setDetailTop(showBg ? thumbUrl(showBg) : null)" in show,
          "show details enable the header when there is artwork")
    check('bindDetailTopScroll();' in JS, "scroll listening is set up when the shell opens")
    check('meta[name="theme-color"]' in JS, "theme-color is updated when a tint is found")
    check('content="#0b0612"' in HTML or "content='#0b0612'" in HTML or 'content="#0b0612"' in HTML,
          "the default theme-color is still the dark app color")


def test_docs():
    check("## 2.5.2" in CHANGELOG, "CHANGELOG has a 2.5.2 section")
    body = CHANGELOG.split("## 2.5.2")[1].split("## 2.5.1")[0].lower()
    check("backdrop" in body and "phone" in body, "CHANGELOG describes the phone details header")
    check("no new android app" in body or "no new android" in body,
          "CHANGELOG notes no new Android app")
    check("**2.5.2:**" in README, "README What's new mentions 2.5.2")


if __name__ == "__main__":
    print("2.5.2 phone details header")
    test_version_and_schema()
    test_css_phone_only()
    test_js_hooks()
    test_docs()
    print("all ok")
