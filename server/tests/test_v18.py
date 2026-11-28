"""1.8: themed Server status panel, disk used_unknown, background jobs, yield-on-play.

    python3 tests/test_v18.py
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import namedtuple
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="ms-v18-")
FAKE = tempfile.mkdtemp(prefix="ms-v18-proc-")
os.environ.update({"MS_DATA_DIR": TMP, "MS_PROC_DIR": FAKE})

from app.version import __version__  # noqa: E402
from app import db, preload, sysstat, transcode  # noqa: E402

fails = []


def check(cond, msg):
    print(("  ok - " if cond else "  FAIL - ") + msg, flush=True)
    if not cond:
        fails.append(msg)


def main():
    check(tuple(int(x) for x in __version__.split(".")) >= (1, 8), "version is 1.8 or later (%s)" % __version__)
    ver = (ROOT / "app/version.py").read_text()
    check(('__version__ = "%s"' % __version__) in ver, "version.py matches %s" % __version__)
    ch = (ROOT / "CHANGELOG.md").read_text()
    check(ch.find("## 1.8") < ch.find("## 1.7.9"), "CHANGELOG 1.8 is above 1.7.9")
    check("Idle · GPU" in ch and "yield" in ch.lower() and "used space is not reported" in ch.lower()
          and "CPU and RAM icons" in ch and "3.6 / 379 GB" in ch,
          "CHANGELOG describes the panel, icons, yield, and share used-space fix")

    js = (ROOT / "app/static/app.js").read_text()
    css = (ROOT / "app/static/style.css").read_text()
    tc = (ROOT / "app/transcode.py").read_text()
    pl = (ROOT / "app/preload.py").read_text()
    st = (ROOT / "app/sysstat.py").read_text()

    print("themed panel")
    check("sysRing" in js and "ss-gauges" in js and "ss-disk-name" in js, "JS draws ring gauges and wrapping disk names")
    check("SS_CPU_ICO" in js and "SS_RAM_ICO" in js and "ss-ring-ico" in js, "outlined CPU chip and RAM stick sit inside the rings")
    check("ss-pill-ico" in js and "ss-metric" in js and "${ramPct}" in js,
          "toolbar uses CPU/RAM icons with a compact percent on all widths")
    check("sysSpark" not in js[js.find("$(\"#ss-pill\").innerHTML"):js.find("$(\"#ss-pill\").title")],
          "header pill no longer includes a sparkline")
    pill_js = js[js.find('$("#ss-pill").innerHTML'):js.find('$("#ss-pill").title')]
    check("sysBar" not in pill_js, "toolbar status has icons and values only, no usage bars")
    check("function ssMem" in js and "} / ${" in js, "RAM value is formatted on one line with spaces around the slash")
    check("ss-ring-ico" in css and "ss-pill-ico" in css and "white-space:nowrap" in css, "CSS centres the icons and keeps RAM on one line")
    check("justify-content:center;width:18px;height:18px" in css,
          "toolbar CPU/RAM icons are 18px")
    pill = css.split(".ss-pill{")[1].split("}", 1)[0].replace(" ", "")
    check("background:transparent" in pill and "border:0" in pill and "border-radius:0" in pill,
          "toolbar status has no rounded border, fill, or pill container")
    check("box-shadow:0 1px 0" in css and "drop-shadow" in css,
          "toolbar hover is a faint purple underline and icon glow")
    check("fmtDisk" in js and "1099511627776" in js, "disk sizes can be shown in TB")
    check("used_unknown" in js and "Used space is not reported" in js, "JS explains unreported share used space")
    check("backgroundLabel" in js and "Background:" in js, "JS labels background cache jobs")
    check("transcodeLabel" in js and "Idle · GPU" in js and "Off (CPU)" in js, "idle transcoding names the card, not CPU")
    check("var(--acc-text)" in css and "ss-gauges" in css and "overflow-wrap:anywhere" in css, "CSS is themed and lets names wrap")
    check("linear-gradient(90deg,var(--acc-fill),var(--acc-text))" in css.replace(" ", ""),
          "healthy bars use the theme purple")
    pill_src = js[js.find('$("#ss-pill").innerHTML'):js.find('$("#ss-pill").title')]
    check("${ramPct}" in pill_src and "ss-ram-abs" not in pill_src,
          "toolbar visible values are percents only")
    check('title="RAM ${ssMem(d)} (${ramPct})"' in pill_src
          and "RAM ${fmtGB(d.mem.used)} of ${fmtGB(d.mem.total)} GB" in js,
          "full RAM size is provided in the tooltip")
    print("sysstat disk + idle GPU + background")
    check("used_unknown" in st and "hwaccel.active()" in st and "preload.jobs()" in st,
          "sysstat reports used_unknown, idle method, and background jobs")
    DU = namedtuple("DU", "total used free")
    orig = shutil.disk_usage
    try:
        shutil.disk_usage = lambda path: DU(10_000_000_000, 0, 10_000_000_000)
        d = sysstat._disk("/x")
        check(d["used_unknown"] is True and d["free"] == 10_000_000_000, "CIFS-like share is used_unknown")
        shutil.disk_usage = lambda path: DU(10_000_000_000, 4_000_000_000, 6_000_000_000)
        d = sysstat._disk("/x")
        check(d["used_unknown"] is False and d["used"] == 4_000_000_000, "normal disk uses shutil.used")
    finally:
        shutil.disk_usage = orig

    db.migrate()
    snap = sysstat.status()
    check("background" in snap and "kind" in snap["background"], "status includes a background block")
    check(snap["disks"] and snap["disks"][0]["name"].startswith("Data"), "data disk is named Data (not truncated)")
    check("used_unknown" in snap["disks"][0], "disk rows include used_unknown")

    import app.hwaccel as hwaccel
    orig_active, orig_mode = hwaccel.active, hwaccel.mode
    try:
        hwaccel.active = lambda: ("vaapi", "/dev/dri/renderD128")
        hwaccel.mode = lambda: "auto"
        sysstat._state["snap"] = None
        snap = sysstat.status()
        check(snap["hw"]["method"] == "vaapi" and snap["hw"]["streams"] == 0,
              "idle status still reports VAAPI as the ready method")
        check(snap["hw"]["label"], "idle VAAPI has a label")
    finally:
        hwaccel.active, hwaccel.mode = orig_active, orig_mode

    print("yield on play")
    check("def yield_to_playback" in pl and "def jobs" in pl and "def run_cmd" in pl, "preload exposes yield/jobs/run_cmd")
    check("subprocess.Popen" in pl and 'start_new_session=True' in pl, "subtitle extract is a killable Popen")
    check("preload.yield_to_playback(" in tc, "Session.start and kickoff yield to playback")
    check("if busy():" in pl and "time.time() - t0 > 8" not in pl, "prefetch abandons as soon as a viewer arrives")

    p = subprocess.Popen(["sleep", "30"], start_new_session=True)
    preload._register("subtitles", p)
    jobs = preload.jobs()
    check(jobs["running"] == 1 and jobs["kind"] == "subtitles", "jobs() reports the in-flight extract")
    preload.yield_to_playback()
    # wait briefly for the signal to land
    for _ in range(20):
        if p.poll() is not None:
            break
        time.sleep(0.05)
    check(p.poll() is not None, "yield_to_playback stops the background process")
    check(preload.jobs()["running"] == 0, "jobs() is clear after yield")
    if p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except Exception:
            p.kill()

    if fails:
        print("\n%d failed" % len(fails))
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
