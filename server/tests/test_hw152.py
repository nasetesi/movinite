"""1.5.2: hardware transcoding -- detection (fake sysfs/dev trees), ffmpeg arguments per method/stage, setup that
never overrides a saved choice, validation, install/update wiring and the Settings UI pieces.  Needs no GPU:
uses ../test/mockhw (mksys.sh + ffmpeg-hw-mock.py) when it exists."""
import json, os, re, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, ".."); APP = os.path.join(ROOT, "app")
MOCK = os.path.abspath(os.path.join(ROOT, "..", "test", "mockhw"))
fails = []
def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok: fails.append(msg)
rd = lambda *p: open(os.path.join(*p)).read()
js = rd(APP, "static", "app.js"); css = rd(APP, "static", "style.css"); srv = rd(APP, "server.py"); tc = rd(APP, "transcode.py")
inst = rd(ROOT, "install.sh"); upd = rd(ROOT, "update.sh"); hws = rd(ROOT, "hwsetup.sh")

tmp = tempfile.mkdtemp(prefix="hw152-")
os.environ["MS_DATA_DIR"] = os.path.join(tmp, "data")
have_mock = os.path.exists(os.path.join(MOCK, "mksys.sh"))
if have_mock:
    for kind in ("intel", "nvidia", "none"):
        subprocess.run(["bash", os.path.join(MOCK, "mksys.sh"), os.path.join(tmp, kind), kind], check=True, capture_output=True)
    os.environ["MS_FFMPEG"] = os.path.join(MOCK, "ffmpeg-hw-mock.py")
    os.environ["MOCK_HW_STATE"] = os.path.join(tmp, "state"); os.environ["MOCK_HW_LOG"] = os.path.join(tmp, "calls.log")
def use(kind):
    os.environ["MS_HW_SYSFS"] = os.path.join(tmp, kind, "sys"); os.environ["MS_HW_DEV"] = os.path.join(tmp, kind, "dev")
use("intel")
sys.path.insert(0, ROOT)
from app import config, db, hwaccel, settings  # noqa: E402
db.migrate()
def mstate(s): open(os.environ.get("MOCK_HW_STATE", "/dev/null"), "w").write(s + "\n")

# ---- ffmpeg arguments
pre, vf, enc = hwaccel.stage_args("vaapi", "/dev/dri/renderD128", "full", 720, 4000)
check(pre[:2] == ["-threads", "1"] and "-noautorotate" in pre and pre[pre.index("-hwaccel") + 1] == "vaapi" and "-hwaccel_output_format" in pre,
      "vaapi full: hw decode, single decode thread (Arc EOF fix), no autorotate")
check(pre[pre.index("-extra_hw_frames") + 1] == "64", "vaapi full: extra_hw_frames 64 for concurrent 4K surfaces")
check(vf == "scale_vaapi=w=-2:h=720:format=nv12" and enc[:2] == ["-c:v", "h264_vaapi"] and enc[enc.index("-low_power") + 1] == "1"
      and "-b:v" in enc and enc[enc.index("-maxrate") + 1] == "4000k",
      "vaapi full: scale_vaapi + h264_vaapi low_power at the profile bitrate (%s)" % vf)
_, vfr, _ = hwaccel.stage_args("vaapi", "/dev/dri/renderD128", "full", 1080, 8000, 270)
check(vfr.startswith("transpose_vaapi=dir=clock,scale_vaapi"), "rotated phone video (-90) turned on the GPU before scaling")
check(hwaccel._vaapi_turn(90).startswith("transpose_vaapi=dir=cclock") and "reversal" in hwaccel._vaapi_turn(180) and hwaccel._vaapi_turn(0) == "",
      "rotation mapping 90/180/0")
hwaccel._filters = {"scale_vaapi", "tonemap_vaapi", "transpose_vaapi"}
_, vfh, _ = hwaccel.stage_args("vaapi", "/dev/dri/renderD128", "full", 1080, 8000, hdr="HDR10")
check("tonemap_vaapi" in vfh and "format=p010" in vfh, "HDR10 stays on the GPU with tonemap_vaapi (%s)" % vfh)
_, vfs, _ = hwaccel.stage_args("vaapi", "/dev/dri/renderD128", "full", 1080, 8000, hdr="")
check(vfs == "scale_vaapi=w=-2:h=1080:format=nv12", "SDR stays on scale_vaapi to nv12")
hwaccel._filters = set()  # filter not in this ffmpeg
_, vfn, _ = hwaccel.stage_args("vaapi", "/dev/dri/renderD128", "full", 1080, 8000, hdr="HDR10")
check(vfn == "scale_vaapi=w=-2:h=1080:format=nv12", "HDR falls back to scale_vaapi when tonemap_vaapi is missing")
hwaccel._filters = None
pre, vf, enc = hwaccel.stage_args("vaapi", "/dev/dri/renderD128", "enc", 720, 4000)
check("-init_hw_device" in pre and "-hwaccel" not in pre and vf.endswith("format=nv12,hwupload=extra_hw_frames=64") and "min(720,ih)" in vf,
      "vaapi enc: CPU decode + scale, hwupload with extra surfaces")
pre, vf, enc = hwaccel.stage_args("qsv", "/dev/dri/renderD128", "full", 720, 4000)
check("qsv=qs@va" in pre and "hwmap=derive_device=qsv" in vf and enc[1] == "h264_qsv", "qsv full: vaapi decode mapped to qsv")
pre, vf, enc = hwaccel.stage_args("nvenc", "nvidia", "full", 720, 4000)
check(pre == ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] and vf.startswith("scale_cuda") and enc[1] == "h264_nvenc", "nvenc full: cuda decode + scale_cuda")
try:
    hwaccel.stage_args("bogus", "", "full", 720, 1); check(False, "unknown method rejected")
except ValueError:
    check(True, "unknown method rejected")
check(hwaccel.rotation("/nonexistent/file.mkv") == 0, "rotation() of a missing file = 0 (never raises)")

# ---- transcode wiring
check("hwaccel.stage_args(self.hw[0], self.hw[1], self.stage, h, hk, self.rot" in tc and '["full", "enc", "cpu"]' in tc, "Session uses full -> enc -> cpu stages")
check("HW_STALL_S = 20" in tc and "no output after %ds" in tc and "_handle_not_running" in tc, "fallback on exit-without-output and on a 20 s stall (one HW retry, then sticky)")
check('self.stages = ["enc", "cpu"]' in tc, "NVENC skips the full stage for rotated videos")
check('"libx264"' in tc and "config.HWACCEL" in tc, "CPU path (libx264) unchanged")

if have_mock:
    # ---- detection
    det = hwaccel.detect(refresh=True)
    names = [c["name"] for c in det["cards"]]
    arc = [c for c in det["cards"] if c["vendor"] == "intel"]
    check("Intel DG2 [Arc A310]" in names and "Matrox G200eR2" in names, "intel tree: Arc + Matrox found (%s)" % names)
    check(arc and arc[0]["render"].endswith("/dri/renderD128") and arc[0]["methods"] == ["vaapi", "qsv"], "Arc: render node + VAAPI/QSV")
    mx = [c for c in det["cards"] if c["vendor"] == "matrox"][0]
    check(mx["methods"] == [] and mx["note"] == "no video encoder", "Matrox BMC: no methods")
    check([c[0] for c in hwaccel.candidates(det)] == ["vaapi", "qsv"], "auto order VAAPI then QSV")
    use("nvidia"); det = hwaccel.detect(refresh=True)
    nv = [c for c in det["cards"] if c["vendor"] == "nvidia"]
    check(nv and "nvenc" in nv[0]["methods"], "nvidia tree: NVENC offered (%s)" % (nv and nv[0].get("note")))
    use("none"); det = hwaccel.detect(refresh=True)
    check(all(not c["methods"] for c in det["cards"]) and hwaccel.candidates(det) == [], "no GPU: nothing offered (old VM stays on CPU)")
    # ---- setup
    use("intel"); hwaccel.detect(refresh=True); mstate("vaapi=ok\nqsv=ok")
    r = hwaccel.setup(if_unset=True, by="install")
    check(r["mode"] == "vaapi" and not r["kept"] and settings.get("hw_transcode") == "vaapi", "fresh setup: VAAPI tested and saved (%s)" % r["mode"])
    info = json.loads(settings.get("hw_setup_info") or "{}")
    check(info.get("by") == "install" and info.get("tests") and info["tests"][0]["ok"], "setup info records who/when/test")
    settings.put("hw_transcode", "off")
    r = hwaccel.setup(if_unset=True, by="update")
    check(r["kept"] and settings.get("hw_transcode") == "off", "--if-unset never overrides a saved value (off kept)")
    settings.put("hw_transcode", "")
    mstate("vaapi=fail\nqsv=fail"); r = hwaccel.setup(if_unset=True, by="install")
    check(r["mode"] == "off" and any(t.get("hint") for t in r["tests"]), "every test fails -> off + QSV hint")
    settings.put("hw_transcode", ""); mstate("vaapi=fail\nqsv=ok"); r = hwaccel.setup(if_unset=True, by="install")
    check(r["mode"] == "qsv", "VAAPI fails, QSV passes -> qsv")
    use("none"); hwaccel.detect(refresh=True); settings.put("hw_transcode", "")
    r = hwaccel.setup(if_unset=True, by="install"); check(r["mode"] == "off", "no card -> off")
    use("intel"); hwaccel.detect(refresh=True); mstate("vaapi=ok")
    # ---- save validation / active / hold
    for bad in [("turbo", ""), ("vaapi", "/etc/passwd"), ("vaapi", "/dev/dri/../sda")]:
        try:
            hwaccel.save(*bad); check(False, "save refuses %s" % (bad,))
        except ValueError:
            check(True, "save refuses %s" % (bad,))
    dev = os.path.join(os.environ["MS_HW_DEV"], "dri", "renderD128")
    hwaccel.save("vaapi", dev); check(hwaccel.active() == ("vaapi", dev), "saved VAAPI is active")
    hwaccel.note_failure("vaapi", dev, "full", "x"); check(hwaccel.active() == ("vaapi", dev), "a full-stage failure does not hold the method")
    hwaccel.note_failure("vaapi", dev, "enc", "boom"); check(hwaccel.active() == ("vaapi", dev),
          "an enc-stage failure stays per-stream and does not turn the card off for everyone")
    st = hwaccel.state(); check(st["last_failure"]["reason"] == "boom" and not st["held"], "state() records the last failure without a global hold")
    r = hwaccel.test("vaapi", dev); check(r["ok"] and hwaccel.active() == ("vaapi", dev), "a passing Test still leaves the card active")
    hwaccel.save("off", ""); check(hwaccel.active() == (None, None), "Off = CPU")
    # ---- CLI as install.sh calls it
    env = dict(os.environ); settings.put("hw_transcode", "")
    out = subprocess.run([sys.executable, "-m", "app.cli", "hw-setup", "--if-unset", "--by", "install"], cwd=ROOT, env=env, capture_output=True, text=True).stdout
    check("HW_MODE=vaapi" in out and "HW_KEPT=no" in out and "HW_CARD=Intel DG2 [Arc A310]" in out, "cli hw-setup output for install.sh")
    out = subprocess.run([sys.executable, "-m", "app.cli", "hw-get"], cwd=ROOT, env=env, capture_output=True, text=True).stdout.strip()
    check(out == "vaapi", "cli hw-get = %s" % out)
else:
    print("skip detection/setup tests (no ../test/mockhw)")

# ---- install / update
check('. "$PROJECT_DIR/hwsetup.sh"' in inst and "hw_choose install" in inst and "hw_step ||" in inst, "install.sh runs the GPU step, best effort")
check(inst.index("hw_choose install") > inst.index("app.cli init") and inst.index("hw_step ||") < inst.index("systemd service '$APP_NAME'"), "GPU step after the DB init, before the service starts")
check("hw-get" in upd and 'kept your setting' in upd and "hw_choose update" in upd and "hw_update_step ||" in upd, "update.sh: scan only when unset, otherwise keep")
for pkg in ("intel-media-va-driver-non-free", "intel-media-va-driver", "vainfo", "libvpl2", "libmfx-gen1.2", "mesa-va-drivers", "pciutils"):
    check(pkg in hws, "hwsetup.sh installs %s (best effort)" % pkg)
check("nvidia-smi" in hws and "ubuntu-drivers" in hws and "usermod -aG" in hws and "--if-unset" in hws, "NVIDIA driver hint, groups, if-unset")
check("for g in video render" in inst, "service user in video + render (install)")
r = subprocess.run(["bash", "-n", os.path.join(ROOT, "hwsetup.sh")]); check(r.returncode == 0, "hwsetup.sh syntax")
# ---- API + UI
for route in ('@app.get("/api/hw")', '@app.put("/api/hw")', '@app.post("/api/hw/test")', '@app.post("/api/hw/scan")'):
    i = srv.index(route); check("auth.require_admin" in srv[i:i + 200], "%s is admin-only" % route)
check('threading.Thread(target=hwaccel.warm_up' in srv or 'target=hwaccel.warm_up' in srv, "first start of 1.5.2 scans when unset (servers updated with an older update.sh)")
check('["transcoding", "Transcoding"' in js and '["system", "System"' in js and "async function viewTranscoding" in js, "Settings > Transcoding tab")
check('["auto", "qsv", "vaapi", "nvenc", "off"].map(opt)' in js and 'auto: "Auto", qsv: "Intel QSV", vaapi: "VAAPI", nvenc: "NVIDIA NVENC", off: "Off (CPU)"' in js, "mode choices Auto / Intel QSV / VAAPI / NVIDIA NVENC / Off (CPU)")
check('data-hwtest=' in js and '"/api/hw/test"' in js and '"/api/hw/scan"' in js and 'id="hw-save"' in js, "Test, Scan again and Save buttons")
check('class="hw-badge ss-gpu"' in js and "d.hw.streams" in js and 'row("Transcoding"' in js, "GPU badge in the status pill, popover row, player overlay")
check(".hw-badge{" in css and ".ss-pill.gpu{box-shadow:0 0 0 2px var(--acc)}" in css, "badge styles (+ ring on the phone dot)")
check("<th>Encoder</th>" in js and "function encName" in js, "System tab shows each stream's encoder")
shutil.rmtree(tmp, ignore_errors=True)
print("\n%d FAILED" % len(fails) if fails else "\nALL OK")
sys.exit(1 if fails else 0)
