"""2.4.1: player stats overlay — long GPU names stay inside the Encoder cell."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app/static/app.js").read_text()
CSS = (ROOT / "app/static/style.css").read_text()

def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL: " + msg)
    print("  ok", msg)


def test_version():
    from app.version import __version__
    check(__version__ == "2.4.1", "version is 2.4.1")


def short_gpu_name(name):
    """Python mirror of shortGpuName() in app.js."""
    s = re.sub(r"\s+", " ", str(name or "")).strip()
    if not s:
        return ""
    m = re.search(r"\[([^\]]+)\]", s)
    if m and m.group(1).strip():
        return m.group(1).strip()
    s = re.sub(r"^Intel Corporation\s+", "", s, flags=re.I)
    s = re.sub(r"^NVIDIA Corporation\s+", "NVIDIA ", s, flags=re.I)
    s = re.sub(r"^Advanced Micro Devices,?\s*Inc\.?\s*", "AMD ", s, flags=re.I)
    return s.strip()


def test_short_names():
    cases = {
        "Intel Corporation DG2 [Arc A310]": "Arc A310",
        "Intel Corporation DG2 [Arc A310 ]": "Arc A310",
        "Arc A310": "Arc A310",
        "NVIDIA GeForce RTX 4070": "NVIDIA GeForce RTX 4070",
        "NVIDIA Corporation GeForce RTX 4070": "NVIDIA GeForce RTX 4070",
        "Advanced Micro Devices, Inc. Radeon RX 6800": "AMD Radeon RX 6800",
        "": "",
        None: "",
    }
    for raw, want in cases.items():
        got = short_gpu_name(raw)
        check(got == want, "shortGpuName(%r) -> %r" % (raw, got))
    # JS has the same rules
    check("function shortGpuName(" in JS, "shortGpuName is in app.js")
    check(r"match(/\[([^\]]+)\]/)" in JS, "JS prefers the name in [brackets]")
    check("Intel Corporation" in JS and "NVIDIA Corporation" in JS, "JS strips vendor prefixes")
    check("hw.name" in JS and "title=" in JS.split("function transcodeLabel")[1].split("function backgroundLabel")[0],
          "full GPU name is kept as a tooltip")


def test_overlay_layout():
    rule = CSS[CSS.index(".pl-ss{"):CSS.index(".pl-ss{") + 1200]
    check("white-space:nowrap" not in rule.split(".player.ov-on")[0],
          "the 2x2 stats panel no longer forces nowrap on the whole grid")
    check("minmax(0,1fr) minmax(0,1fr)" in rule,
          "grid columns can shrink below their content (min-width:0)")
    check("min-width:0" in CSS[CSS.index(".pl-ss-cell{"):CSS.index(".pl-ss-cell{") + 400],
          "each cell has min-width:0")
    check("overflow:hidden" in CSS[CSS.index(".pl-ss-cell{"):CSS.index(".pl-ss-cell{") + 500],
          "cell content cannot paint over the next column")
    check(".pl-ss-cell .ss-gpu-name" in CSS and "overflow-wrap:anywhere" in CSS,
          "a long GPU name wraps or ellipsizes inside its cell")
    check("@media (max-width:420px)" in CSS and ".pl-ss{" in CSS.split("@media (max-width:420px)")[1][:200],
          "narrow phone widths tighten the panel gap")
    check("white-space:nowrap" in CSS[CSS.index(".pl-ss-fr{"):CSS.index(".pl-ss-fr{") + 280],
          "the dropped-only pill still stays on one line")
    import re
    bg = re.search(r"background:rgba\(16,12,22,\.(\d+)\)", rule)
    got = bg.group(1) if bg else "?"
    check(bg and 18 <= int(bg.group(1)) <= 32,
          "the stats panel fill is more see-through than the old 38 percent, now ." + got)
    check("text-shadow:" in rule, "labels have a text shadow so they stay readable on a bright scene")
    check("backdrop-filter:blur(" in rule, "a subtle backdrop blur is still applied")


def test_render_uses_short_name():
    r = JS.split("function renderPlayerStat()")[1].split("function renderSysPanel")[0]
    check("{ parts: true }" in r and "t.name" in r,
          "the Encoder cell puts the short GPU name on a second line")
    check("Idle · GPU" in JS, "idle encoder still says Idle · GPU")
    # The raw PCI name must not be interpolated into the visible label
    idle = JS.split("function transcodeLabel")[1].split("function backgroundLabel")[0]
    check("${esc(hw.name)}" not in idle and "esc(hw.name)" not in idle,
          "the visible label does not use the raw PCI device name")
    check("function transcodeLabel" in JS and "Off (CPU)" in JS, "CPU-off wording is unchanged")


if __name__ == "__main__":
    print("2.4.1 player stats overlay")
    test_version()
    test_short_names()
    test_overlay_layout()
    test_render_uses_short_name()
    print("all ok")
