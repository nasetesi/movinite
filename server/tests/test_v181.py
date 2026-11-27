"""1.8.1: play playlists, music mute, reachable volume, and frosted-glass chrome."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MS_DATA_DIR", str(HERE / "tmp-v181"))

from app.version import __version__


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_v181():
    check(tuple(int(x) for x in __version__.split(".")) >= (1, 8, 1), "version is 1.8.1 or later")
    ver = (ROOT / "app/version.py").read_text()
    check(('__version__ = "%s"' % __version__) in ver, "version.py matches")
    ch = (ROOT / "CHANGELOG.md").read_text()
    check(ch.find("## 1.8.1") < ch.find("## 1.8 --"), "CHANGELOG 1.8.1 is above 1.8")
    check("Play and Shuffle are on the playlist list" in ch and "Mute and a volume control" in ch
          and "Frosted-glass chrome" in ch,
          "CHANGELOG describes playlist play, volume/mute, and glass chrome")

    js = (ROOT / "app/static/app.js").read_text()
    css = (ROOT / "app/static/style.css").read_text()
    html = (ROOT / "app/static/index.html").read_text()

    print("playlist play")
    check("function playPlaylist(" in js and "data-pl-play" in js and "data-pl-shuffle" in js,
          "playlist list has Play and Shuffle hooks")
    check('id="pl-play"' in js and 'id="pl-shuffle"' in js and "ICO_PLAY" in js and "ICO_SHUFFLE" in js,
          "playlist detail Play and Shuffle use themed icons")
    check("class=\"iconbtn ab-tool pli-play\"" in js and "Play from here" in js,
          "each playlist track has a play-from-here button")
    check("playQueue(tracks, +b.dataset.track)" in js or "playQueue(tracks, +el.dataset.track)" in js,
          "play-from-track starts the queue at that index")
    check("Q.list = (list || []).slice();" in js, "playQueue copies the list so on-screen order is unchanged")
    check("const t = (list || []).slice();" in js, "shuffled() copies the list")
    check('r.draggable = false' in js and "pointer: coarse" in js,
          "touch screens do not use HTML5 drag on playlist rows")
    check(".pli-card-actions" in css and ".pli-play{" in css, "playlist play controls are styled")

    print("mute and volume")
    check('id="ab-mute"' in html and 'id="ab-volw"' in html and 'id="ab-vol-pop"' in html
          and 'id="ab-vol"' in html and 'id="ab-vol-open"' in html and 'id="ab-vol-v"' in html,
          "mute, inline slider, and a vertical popover are in the music bar")
    check('class="i-vol"' in html and 'class="i-muted"' in html, "mute has volume and muted icons")
    check("function toggleAudioMute(" in js and "AB_VOL_KEY" in js and "AB_MUTE_KEY" in js,
          "mute remembers the last volume in localStorage")
    check('title="Mute (M)"' in html and "toggleAudioMute()" in js
          and ('e.key === "m"' in js and "audioOpen" in js),
          "M toggles music mute when the audio bar is open")
    check("ab-transport" in html and ".ab-transport{" in css, "volume sits with the transport controls")
    check("#ab-vol{\n  width:140px;height:44px" in css or "height:44px" in css[css.index("#ab-vol{"):css.index("#ab-vol{")+200],
          "inline volume slider has a larger hit area")
    # Must not hide volume on the phone mini bar without a replacement control
    phone = css.split("@media (max-width:820px)")[1] if "@media (max-width:820px)" in css else ""
    check("#ab-vol-open{display:inline-flex}" in css, "phone mini bar offers a volume popover button")
    check(".ab-vol-pop{" in css and "bottom:calc(100% + 10px)" in css,
          "phone volume popover opens above the bar")
    check("html.af-open .ab-transport{" in css and "grid-row:5" in css,
          "full now-playing volume is grouped with the play controls")
    check("html.af-open #ab-vol{display:block" in css, "full now-playing shows the inline slider")
    # The old bottom-row placement should be gone
    check("html.af-open #ab-vol{display:block;grid-column:1/-1;grid-row:6" not in css
          and "html.af-open #ab-vol{grid-column:1/-1;grid-row:6" not in css,
          "volume is no longer a lone bottom grid row")
    check("accent-color:var(--acc)" in css[css.index(".ab-volw"):css.index(".ab-volw")+1800],
          "volume uses the purple theme accent")
    check("#ab-mute.muted .i-muted{display:block}" in css, "muted state shows the muted icon")

    print("frosted glass chrome")
    check("--glass-bg:" in css and "--glass-border:" in css and "--glass-shadow:" in css and "--glass-blur:" in css,
          "shared glass tokens are defined")
    check(("--pop-bg:" in css and ".ss-panel,.acct-menu" in css) or
          ("background:var(--glass-bg)" in css[css.index(".ss-panel{"):css.index(".ss-panel{")+500]),
          "status panel uses the shared popover or glass tokens")
    top = css[css.index(".top{"):css.index(".top{")+500]
    check(("background:var(--glass-bg)" in top and "backdrop-filter:var(--glass-blur)" in top)
          or ("background:var(--panel)" in top),
          "top bar is themed (glass or the solid panel used since 2.1.1)")
    ab = css[css.index(".audiobar{"):css.index(".audiobar{")+500]
    check("background:var(--glass-bg)" in ab and "backdrop-filter:var(--glass-blur)" in ab
          and "border:1px solid var(--glass-border)" in ab and "border-radius:16px" in ab,
          "mini music bar is floating frosted glass")
    check("html.af-open .audiobar{" in css and "background:var(--bg)" in css[css.index("html.af-open .audiobar{"):css.index("html.af-open .audiobar{")+400]
          and "backdrop-filter:none" in css[css.index("html.af-open .audiobar{"):css.index("html.af-open .audiobar{")+400],
          "full now-playing stays a solid page")
    # 2.4.2: volume popover shares --pop-* chrome (grouped rule may precede the layout rule)
    check(("background:var(--pop-bg)" in css and ".ab-vol-pop" in css.split("background:var(--pop-bg)")[0][-200:])
          or ("background:var(--glass-bg)" in css[css.index(".ab-vol-pop{"):css.index(".ab-vol-pop{")+500]),
          "volume popover uses the shared popover or glass tokens")
    i = css.index(".tabbar{display:grid")
    check("background:var(--glass-bg)" in css[i:i+700] and "backdrop-filter:var(--glass-blur)" in css[i:i+700],
          "phone tab bar uses the glass tokens")
    check("function syncTopH(" in js and "--top-h" in js, "header height is measured so content clears the overlay bar")

    print("ok")


if __name__ == "__main__":
    test_v181()
    print("all checks passed")
