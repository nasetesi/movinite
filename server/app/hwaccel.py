"""1.5.2: hardware video encoding (Intel Quick Sync / VAAPI, NVIDIA NVENC) for transcodes.

Setting `hw_transcode` = auto | vaapi | qsv | nvenc | off   (unset = auto)
Setting `hw_device`    = a render node such as /dev/dri/renderD128 (empty = the first suitable one)

A fresh install (and the first start after an update, if the setting was never set) scans for video cards,
test-encodes a few frames with each candidate and writes the first method that works (or "off" when there is
no usable card).  A value chosen in Settings is never overwritten.

Every hardware stream falls back on its own: full GPU (decode + scale + encode) -> CPU decode + GPU encode ->
CPU (libx264).  That fallback is sticky for the stream and is logged; it does not turn the card off for
everyone else, and a later restart of the same stream will not hop back to a stage that just failed.
"""
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time

from . import config, settings

log = logging.getLogger("media-server.hwaccel")

MODES = ("auto", "vaapi", "qsv", "nvenc", "off")
LABEL = {"auto": "Auto", "vaapi": "VAAPI", "qsv": "Intel QSV", "nvenc": "NVIDIA NVENC", "off": "Off (CPU)", "cpu": "CPU"}
ENCODER = {"vaapi": "h264_vaapi", "qsv": "h264_qsv", "nvenc": "h264_nvenc"}
VENDORS = {"0x8086": "intel", "0x10de": "nvidia", "0x1002": "amd", "0x1022": "amd", "0x102b": "matrox", "0x1a03": "aspeed"}
VENDOR_NAME = {"intel": "Intel", "nvidia": "NVIDIA", "amd": "AMD", "matrox": "Matrox", "aspeed": "ASPEED"}
KNOWN = {"8086:56a6": "Intel DG2 [Arc A310]", "8086:56a5": "Intel DG2 [Arc A380]", "8086:56a1": "Intel DG2 [Arc A750]",
         "8086:56a0": "Intel DG2 [Arc A770]", "8086:e20b": "Intel Battlemage [Arc B580]", "102b:0534": "Matrox G200eR2"}
FAIL_HOLD_S = 600          # after a stream fell all the way back to the CPU, skip that method for 10 min
TEST_TIMEOUT_S = 25

_lock = threading.Lock()
_det = None                # cached detect() result
_auto = None               # cached auto choice: (method, device) or (None, None)
_failed = {}               # (method, device) -> (time, reason)
_last_test = {}            # (method, device) -> result dict
_setup_running = False


def _sysfs():
    return os.environ.get("MS_HW_SYSFS") or "/sys"


def _devroot():
    return os.environ.get("MS_HW_DEV") or "/dev"


def _read(p):
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return ""


def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.returncode, r.stdout.decode(errors="replace"), r.stderr.decode(errors="replace")
    except subprocess.TimeoutExpired:
        return 124, "", "timed out after %ds" % timeout
    except OSError as e:
        return 127, "", str(e)


def _lspci_name(slot):
    if not shutil.which("lspci") or os.environ.get("MS_HW_SYSFS"):
        return ""
    rc, out, _ = _run(["lspci", "-s", slot], timeout=5)
    if rc == 0 and ": " in out:
        name = out.strip().split(": ", 1)[1]
        return re.sub(r"\s*\(rev [0-9a-f]+\)$", "", name)
    return ""


def _ffmpeg_caps():
    rc, out, _ = _run([config.FFMPEG, "-hide_banner", "-encoders"], timeout=15)
    enc = set(re.findall(r"^\s*V\S*\s+(h264_(?:vaapi|qsv|nvenc))\b", out, re.M)) if rc == 0 else set()
    rc, out, _ = _run([config.FFMPEG, "-hide_banner", "-hwaccels"], timeout=15)
    acc = [l.strip() for l in out.splitlines()[1:] if l.strip()] if rc == 0 else []
    return enc, acc


def detect(refresh=False):
    """Video cards on this machine and what ffmpeg can do with them (cached)."""
    global _det
    with _lock:
        if _det is not None and not refresh:
            return _det
    sysfs, dev = _sysfs(), _devroot()
    cards, seen = [], set()
    drm = os.path.join(sysfs, "class", "drm")
    try:
        nodes = sorted(n for n in os.listdir(drm) if re.match(r"^renderD\d+$", n))
    except OSError:
        nodes = []
    for n in nodes:
        d = os.path.realpath(os.path.join(drm, n, "device"))
        slot = os.path.basename(d)
        vendor = VENDORS.get(_read(os.path.join(d, "vendor")).lower(), "other")
        drv = os.path.basename(os.path.realpath(os.path.join(d, "driver"))) if os.path.exists(os.path.join(d, "driver")) else ""
        path = os.path.join(dev, "dri", n)
        seen.add(slot)
        cards.append({"slot": slot, "vendor": vendor, "pci_id": "%s:%s" % (_read(os.path.join(d, "vendor"))[2:], _read(os.path.join(d, "device"))[2:]),
                      "name": _lspci_name(slot), "driver": drv, "render": path if os.path.exists(path) else "",
                      "access": os.access(path, os.R_OK | os.W_OK) if os.path.exists(path) else False})
    # display controllers without a render node (server VGA chips, an NVIDIA card with the proprietary driver)
    pci = os.path.join(sysfs, "bus", "pci", "devices")
    try:
        slots = sorted(os.listdir(pci))
    except OSError:
        slots = []
    for s in slots:
        if s in seen or not _read(os.path.join(pci, s, "class")).startswith("0x03"):
            continue
        vendor = VENDORS.get(_read(os.path.join(pci, s, "vendor")).lower(), "other")
        drv = os.path.basename(os.path.realpath(os.path.join(pci, s, "driver"))) if os.path.exists(os.path.join(pci, s, "driver")) else ""
        cards.append({"slot": s, "vendor": vendor, "pci_id": "%s:%s" % (_read(os.path.join(pci, s, "vendor"))[2:], _read(os.path.join(pci, s, "device"))[2:]),
                      "name": _lspci_name(s), "driver": drv, "render": "", "access": False})
    nv_dev = os.path.exists(os.path.join(dev, "nvidia0"))
    nv_names = []
    if shutil.which("nvidia-smi") and not os.environ.get("MS_HW_SYSFS"):
        rc, out, _ = _run(["nvidia-smi", "-L"], timeout=10)
        if rc == 0:
            nv_names = [re.sub(r"\s*\(UUID.*$", "", l.split(": ", 1)[1]) for l in out.splitlines() if ": " in l]
    enc, acc = _ffmpeg_caps()
    for c in cards:
        if not c["name"]:
            c["name"] = KNOWN.get(c["pci_id"]) or "%s display adapter [%s]" % (VENDOR_NAME.get(c["vendor"], "Unknown"), c["pci_id"])
        m = []
        if c["vendor"] == "intel" and c["render"]:
            m = ["vaapi", "qsv"]
        elif c["vendor"] == "amd" and c["render"]:
            m = ["vaapi"]
        elif c["vendor"] == "nvidia":
            m = ["nvenc"] if nv_dev else []
        elif c["vendor"] == "other" and c["render"]:
            m = ["vaapi"]
        c["methods"] = [x for x in m if ENCODER[x] in enc]
        if c["vendor"] == "nvidia" and not nv_dev:
            c["note"] = "NVIDIA driver not loaded (install the NVIDIA driver, then Scan again)"
        elif not m:
            c["note"] = "no video encoder"
        elif c["render"] and not c["access"]:
            c["note"] = "the service cannot open %s (add the service user to the 'render' group)" % c["render"]
        if c["vendor"] == "nvidia" and nv_names:
            c["name"] = nv_names[0]
    res = {"cards": cards, "encoders": sorted(enc), "hwaccels": acc, "nvidia_device": nv_dev, "at": int(time.time())}
    with _lock:
        _det = res
    return res


def candidates(det=None):
    """(method, device, card name) in the order Auto tries them: VAAPI, then QSV on Intel/AMD; NVENC on NVIDIA."""
    det = det or detect()
    out = []
    for c in det["cards"]:
        for m in c.get("methods", []):
            out.append((m, c["render"] if m != "nvenc" else (c["render"] or "nvidia"), c["name"]))
    order = {"vaapi": 0, "qsv": 1, "nvenc": 2}
    return sorted(out, key=lambda x: order[x[0]])


# ---------------------------------------------------------------------------------------- ffmpeg arguments
def rotation(item_or_path):
    """Display rotation of the first video stream in degrees as ffprobe reports it (0, 90, -90, 180 ...).

    The CPU path rotates automatically; frames that stay on the GPU do not, so the full GPU stage has
    to rotate itself (phone videos are usually stored sideways with a -90 display matrix).

    1.7.9: if an item dict already has a rotation from the library scan, use that and skip ffprobe.
    """
    path = item_or_path
    item = None
    if isinstance(item_or_path, dict):
        item = item_or_path
        if item.get("rotation") not in (None, ""):
            try:
                return int(item["rotation"]) % 360
            except (TypeError, ValueError):
                pass
        path = item.get("path")
    if not path:
        return 0
    try:
        r = subprocess.run([config.FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream_side_data=rotation:stream_tags=rotate", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=15)
        for tok in re.split(r"[,\s]+", r.stdout):
            if re.fullmatch(r"-?\d+(\.\d+)?", tok or ""):
                v = int(round(float(tok))) % 360
                if v and item and item.get("id"):
                    try:
                        from . import db
                        with db.tx() as c:
                            c.execute("UPDATE items SET rotation=? WHERE id=?", (v, item["id"]))
                    except Exception:
                        pass
                return v
    except Exception:
        pass
    return 0


def _vaapi_turn(rot):
    """transpose_vaapi for a display rotation (ffprobe value mod 360) -- the same as ffmpeg's autorotate."""
    return {270: "transpose_vaapi=dir=clock,", 90: "transpose_vaapi=dir=cclock,",
            180: "transpose_vaapi=dir=reversal,"}.get(rot % 360, "")



_filters = None  # cached set of ffmpeg filter names; tests may assign this



def hdr_tonemap_enabled():
    """2.2: HDR10/HLG -> SDR on the GPU is off by default until a visual check on a real HDR title."""
    try:
        from . import settings
        return settings.get("hdr_tonemap", "0") == "1"
    except Exception:
        return False


def ffmpeg_filters():
    """Filter names this ffmpeg build actually has (cached)."""
    global _filters
    if _filters is None:
        rc, out, _ = _run([config.FFMPEG, "-hide_banner", "-filters"], timeout=15)
        found = set()
        if rc == 0:
            for line in out.splitlines():
                parts = line.split()
                # typical: " ... tonemap_vaapi   V->V    VAAPI VPP for tone-mapping"
                for i, tok in enumerate(parts):
                    if "->" in tok and i > 0:
                        found.add(parts[i - 1])
                        break
        _filters = found
    return _filters


def has_filter(name):
    return name in ffmpeg_filters()


def _hdr_kind(hdr, item=None):
    """Accept 2.2 labels (HDR10/HLG) and 2.6 kinds."""
    from . import hdr as hdrmod
    if not hdr:
        return hdrmod.kind_from_item(item or {})
    if hdr in ("HDR10", "hdr10"):
        return hdrmod.KIND_HDR10
    if hdr in ("HLG", "hlg"):
        return hdrmod.KIND_HLG
    if hdr in ("DV", "DoVi", "DV5", hdrmod.KIND_DV5):
        return hdrmod.KIND_DV5
    return hdr


def _vaapi_scale(gw, height, hdr="", item=None):
    """Keep frames on the GPU: scale_vaapi, plus tonemap_vaapi for HDR when the filter exists."""
    # 2.2/2.6: only real HDR (never 10-bit SDR / bt709), and only when the admin has turned the setting on.
    from . import hdr as hdrmod
    kind = _hdr_kind(hdr, item)
    if not hdr_tonemap_enabled() or not kind or kind == hdrmod.KIND_SDR:
        return "scale_vaapi=w=%s:h=%d:format=nv12" % (gw, height)
    if kind == hdrmod.KIND_DV5:
        if has_filter("libplacebo"):
            # libplacebo is a software filter; download, map, upload as nv12.
            log.info("HDR DV profile 5: tone-mapping with libplacebo (no HDR10 base layer)")
            return ("hwdownload,format=p010le," + hdrmod.libplacebo_tonemap_vf(kind, scale="") +
                    ",format=nv12,hwupload=extra_hw_frames=64,scale_vaapi=w=%s:h=%d:format=nv12" % (gw, height))
        log.info("HDR DV profile 5: skipping tone-map (no libplacebo; no HDR10 base layer)")
        return "scale_vaapi=w=%s:h=%d:format=nv12" % (gw, height)
    # Intel tonemap_vaapi requires mastering-display metadata. Dolby Vision
    # 8.1 files often have none (One Last Shot: "No mastering display data
    # from input" / EINVAL). Map those in software, then upload for encode.
    if kind in (hdrmod.KIND_DV8, hdrmod.KIND_DV7) and hdrmod.can_tonemap(kind) \
            and has_filter("zscale") and has_filter("tonemap"):
        log.info("HDR %s: tone-mapping in software (tonemap_vaapi needs mastering display data)", kind)
        return ("hwdownload,format=p010le," +
                hdrmod.software_tonemap_vf(kind, item, scale="") +
                ",format=nv12,hwupload=extra_hw_frames=64,scale_vaapi=w=%s:h=%d:format=nv12" % (gw, height))
    if has_filter("tonemap_vaapi") and hdrmod.can_tonemap(kind):
        return hdrmod.vaapi_tonemap_vf(kind, item, gw, height)
    return "scale_vaapi=w=%s:h=%d:format=nv12" % (gw, height)


def software_scale(height, width=None, hdr="", item=None):
    """CPU scale, with zscale+tonemap when HDR tone-mapping is on and filters exist."""
    from . import hdr as hdrmod
    scale = "scale=-2:'min(%d,ih)'" % height if not width else "scale=%d:%d" % (width, height)
    kind = _hdr_kind(hdr, item)
    if not hdr_tonemap_enabled() or not kind or kind == hdrmod.KIND_SDR:
        return scale + ",format=yuv420p"
    if kind == hdrmod.KIND_DV5:
        if has_filter("libplacebo"):
            log.info("HDR DV profile 5: tone-mapping with libplacebo (CPU)")
            return hdrmod.libplacebo_tonemap_vf(kind, scale=scale)
        log.info("HDR DV profile 5: skipping tone-map (no libplacebo; no HDR10 base layer)")
        return scale + ",format=yuv420p"
    if hdrmod.can_tonemap(kind) and has_filter("zscale") and has_filter("tonemap"):
        return hdrmod.software_tonemap_vf(kind, item, scale=scale)
    return scale + ",format=yuv420p"



def _even(n):
    n = int(n or 0)
    return n - (n % 2)


def output_size(item, height, box=None, rot=0):
    """Even output width/height for a transcode (and for subtitle overlay pad)."""
    if box:
        return _even(box[0]), _even(box[1])
    sw = int(item.get("width") or 0) or 0
    sh = int(item.get("height") or 0) or 0
    if rot in (90, 270):
        sw, sh = sh, sw
    out_h = _even(min(height, sh) if sh else height)
    if sw and sh:
        out_w = _even(max(2, int(round(sw * out_h / float(sh)))))
    else:
        out_w = _even(int(out_h * 16 / 9))
    return out_w, out_h


def burn_filter_complex(stage, method, out_w, out_h, sub_index, base_video_f=None):
    """Build a -filter_complex that burns an image subtitle into the picture.

    Prefer overlay_vaapi (CPU-render the subtitle plane, hwupload, overlay on
    the GPU). If that filter is missing, overlay on the CPU and hwupload the
    composited frame. Works with ffmpeg 6.1.x (overlay_vaapi is detected).
    Returns the filter_complex string ending in [vout].
    """
    w, h, si = _even(out_w), _even(out_h), int(sub_index)
    # Scale/pad the subtitle plane on the CPU; keep alpha for overlay.
    sub = ("[0:%d]format=yuva420p,scale=%d:%d:force_original_aspect_ratio=decrease,"
           "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black@0[sub]" % (si, w, h, w, h))
    use_ova = method == "vaapi" and stage == "full" and has_filter("overlay_vaapi")
    if use_ova:
        # Upload only the subtitle plane; video stays on the GPU.
        sub = ("[0:%d]format=bgra,scale=%d:%d:force_original_aspect_ratio=decrease,"
               "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
               "hwupload=extra_hw_frames=64[sub]" % (si, w, h, w, h))
        vid = base_video_f or ("scale_vaapi=w=%d:h=%d:format=nv12" % (w, h))
        if not vid.startswith("[0:"):
            vid = "[0:v:0]" + vid
        if "[base]" not in vid:
            vid = vid + "[base]"
        return "%s;%s;[base][sub]overlay_vaapi=eof_action=pass:repeatlast=0[vout]" % (vid, sub)
    # CPU overlay of the subtitle, then hwupload when this stage encodes on the GPU.
    vid = base_video_f
    if stage in ("full", "enc") and method in ("vaapi", "qsv"):
        # If a full-GPU chain was passed, download first so overlay can run on CPU.
        if vid and "vaapi" in vid:
            if not vid.startswith("[0:"):
                vid = "[0:v:0]" + vid
            vid = vid + ",hwdownload,format=nv12[base]" if "[base]" not in vid else vid
        else:
            vid = "[0:v:0]scale=%d:%d,format=nv12[base]" % (w, h)
        ov = "[base][sub]overlay=0:0:eof_action=pass:repeatlast=0,format=nv12,hwupload=extra_hw_frames=64[vout]"
        if method == "qsv":
            ov = ("[base][sub]overlay=0:0:eof_action=pass:repeatlast=0,format=nv12,"
                  "hwupload=extra_hw_frames=64,format=qsv[vout]")
        return "%s;%s;%s" % (vid, sub, ov)
    # Pure CPU (libx264) or nvenc-enc (nvenc full uses cuda filters; fall back to CPU overlay).
    vid = "[0:v:0]scale=%d:%d,format=yuv420p[base]" % (w, h)
    ov = "[base][sub]overlay=0:0:eof_action=pass:repeatlast=0,format=yuv420p[vout]"
    if method == "nvenc" and stage == "enc":
        # nvenc enc path encodes from yuv420p software frames
        pass
    return "%s;%s;%s" % (vid, sub, ov)


def burn_needs_hw_device(stage, method):
    """True when the burn chain hwuploads (needs -init_hw_device / -filter_hw_device)."""
    if method == "vaapi" and stage == "full" and has_filter("overlay_vaapi"):
        return True
    if method in ("vaapi", "qsv") and stage in ("full", "enc"):
        return True
    return False

def stage_args(method, device, stage, height, kbps, rot=0, width=None, codec="h264", hdr="", item=None):
    """ffmpeg arguments for one transcode stage.

    stage "full": decode, scale and encode on the GPU.  stage "enc": CPU decode + scale, GPU encode.
    Returns (before_input, video_filter, video_codec_args).  `height` is the output height (already capped).
    1.5.3: `width` given = exact output size (2K / 4K, fitted by the caller); codec "hevc" = HEVC Main
    (8-bit, tagged hvc1 for fMP4) instead of H.264 High.
    """
    rate = ["-b:v", "%dk" % int(kbps * 0.8), "-maxrate", "%dk" % kbps, "-bufsize", "%dk" % (kbps * 2)]
    sw_scale = "scale=-2:'min(%d,ih)'" % height if not width else "scale=%d:%d" % (width, height)
    gw = "-2" if not width else str(width)
    hevc = codec == "hevc"
    tag = ["-tag:v", "hvc1"] if hevc else []
    if method == "vaapi":
        if stage == "full":
            # -threads 1: with frame-threaded decoding the last ~15 frames fail at end of file
            # ("Error while filtering: Cannot allocate memory", seen on the Arc A310, ffmpeg 6.1.1)
            # -extra_hw_frames 64: two 4K HEVC 10-bit decodes otherwise run out of VAAPI surfaces
            # ("ffmpeg exited", badge flipping CPU/GPU as the player restarts the same stage).
            pre = ["-threads", "1", "-noautorotate", "-hwaccel", "vaapi", "-hwaccel_device", device,
                   "-hwaccel_output_format", "vaapi", "-extra_hw_frames", "64"]
            vf = _vaapi_turn(rot) + _vaapi_scale(gw, height, hdr, item=item)
        else:
            pre = ["-init_hw_device", "vaapi=hw:%s" % device, "-filter_hw_device", "hw"]
            vf = software_scale(height, width, hdr, item=item) + ",format=nv12,hwupload=extra_hw_frames=64"
        # Arc (and other recent Intel) only exposes the low-power / VDENC entry (EncSliceLP).
        return pre, vf, (["-c:v", "hevc_vaapi", "-profile:v", "main"] if hevc else ["-c:v", "h264_vaapi", "-profile:v", "high"]) + ["-rc_mode", "VBR", "-low_power", "1"] + rate + tag
    if method == "qsv":
        init = ["-init_hw_device", "vaapi=va:%s" % device, "-init_hw_device", "qsv=qs@va", "-filter_hw_device", "qs"]
        if stage == "full":
            pre = init + ["-threads", "1", "-noautorotate", "-hwaccel", "vaapi", "-hwaccel_device", "va",
                          "-hwaccel_output_format", "vaapi", "-extra_hw_frames", "64"]
            vf = _vaapi_turn(rot) + _vaapi_scale(gw, height, hdr, item=item) + ",hwmap=derive_device=qsv,format=qsv"
        else:
            pre = init
            vf = sw_scale + ",format=nv12,hwupload=extra_hw_frames=64,format=qsv"
        if hevc:
            return pre, vf, ["-c:v", "hevc_qsv", "-preset", "veryfast", "-profile:v", "main", "-low_power", "1", "-forced_idr", "1"] + rate + tag
        return pre, vf, ["-c:v", "h264_qsv", "-preset", "veryfast", "-profile:v", "high", "-low_power", "1", "-forced_idr", "1", "-look_ahead", "0"] + rate
    if method == "nvenc":
        if stage == "full":
            pre = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
            vf = "scale_cuda=%s:%d:format=yuv420p" % (gw, height)
        else:
            pre = []
            vf = sw_scale + ",format=yuv420p"
        return pre, vf, ["-c:v", "hevc_nvenc" if hevc else "h264_nvenc", "-preset", "p4", "-profile:v", "main" if hevc else "high", "-rc", "vbr", "-forced-idr", "1"] + rate + tag
    raise ValueError("unknown method %r" % method)


# ---------------------------------------------------------------------------------------- test encode
def test(method, device):
    """Encode 2 s of a 1080p test picture to 720p with this method (CPU decode + GPU encode).  Never raises."""
    t0 = time.time()
    try:
        pre, vf, venc = stage_args(method, device, "enc", 720, 3000)
    except ValueError as e:
        return {"ok": False, "method": method, "device": device, "error": str(e)}
    cmd = ([config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error"] + pre +
           ["-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=2", "-vf", vf] + venc +
           ["-frames:v", "60", "-an", "-f", "null", "-"])
    rc, out, err = _run(cmd, timeout=TEST_TIMEOUT_S)
    secs = time.time() - t0
    res = {"ok": rc == 0, "method": method, "device": device, "seconds": round(secs, 2),
           "fps": round(60 / secs) if rc == 0 and secs > 0 else None, "at": int(time.time())}
    if rc != 0:
        lines = [l for l in (err or out).strip().splitlines() if l.strip()]
        res["error"] = (" | ".join(lines[-3:]) or "ffmpeg exit %d" % rc)[:400]
        if method == "qsv" and ("-1313558101" in res["error"] or "Device creation failed" in res["error"] or "unsupported" in res["error"].lower()):
            res["hint"] = "Intel QSV on Arc / 12th-gen+ needs the oneVPL GPU runtime: sudo apt install libmfx-gen1.2  (VAAPI works without it)"
        log.warning("hardware test %s on %s failed: %s", method, device, res["error"])
    else:
        with _lock:
            _failed.pop((method, device), None)
        log.info("hardware test %s on %s OK (%.2fs)", method, device, secs)
    with _lock:
        _last_test[(method, device)] = res
    return res


def choose(det=None):
    """Try the candidates in order and return (method, device, name, tests)."""
    tests = []
    for m, d, name in candidates(det):
        r = test(m, d)
        r["name"] = name
        tests.append(r)
        if r["ok"]:
            return m, d, name, tests
    return None, None, None, tests


# ---------------------------------------------------------------------------------------- settings
def mode():
    m = (settings.get("hw_transcode") or "").strip()
    return m if m in MODES else "auto"


def is_set():
    return (settings.get("hw_transcode") or "").strip() in MODES


def setup(if_unset=True, by="install"):
    """Scan + test + write hw_transcode / hw_device.  Keeps a value that is already set when if_unset."""
    global _setup_running, _auto
    det = detect(refresh=True)
    if if_unset and is_set():
        info = _info()
        info.update({"rescanned_at": int(time.time())})
        settings.put("hw_setup_info", json.dumps(info))
        return {"kept": True, "mode": mode(), "device": settings.get("hw_device") or "", "det": det, "tests": []}
    _setup_running = True
    try:
        m, d, name, tests = choose(det)
    finally:
        _setup_running = False
    settings.put("hw_transcode", m or "off")
    settings.put("hw_device", d if d and d != "nvidia" else "")
    settings.put("hw_setup_info", json.dumps({"by": by, "at": int(time.time()), "mode": m or "off", "device": d or "",
                                              "name": name or "", "tests": tests,
                                              "cards": [c["name"] for c in det["cards"]]}))
    with _lock:
        _auto = (m, d) if m else (None, None)
    log.info("hardware transcoding set up by %s: %s %s", by, m or "off", d or "")
    return {"kept": False, "mode": m or "off", "device": d or "", "name": name, "det": det, "tests": tests}


def _info():
    try:
        return json.loads(settings.get("hw_setup_info") or "{}")
    except ValueError:
        return {}


def save(new_mode, device=""):
    global _auto
    if new_mode not in MODES:
        raise ValueError("Hardware transcoding must be one of: %s" % ", ".join(MODES))
    if device and not re.match(r"^(/dev/dri/renderD\d+|%s/dri/renderD\d+)$" % re.escape(_devroot()), device):
        raise ValueError("Device must be a render node like /dev/dri/renderD128")
    settings.put("hw_transcode", new_mode)
    settings.put("hw_device", device or "")
    info = _info(); info["changed_by_user_at"] = int(time.time()); info["user_mode"] = new_mode
    settings.put("hw_setup_info", json.dumps(info))
    with _lock:
        _auto = None
        _failed.clear()
    _resolve_soon()


def _resolve_soon():
    """Auto: find the working method in the background so Settings can show it (tests take ~1 s)."""
    if mode() == "auto":
        threading.Thread(target=_auto_choice, name="hw-auto", daemon=True).start()


def rescan():
    global _auto
    with _lock:
        _auto = None
    det = detect(refresh=True)
    _resolve_soon()
    return det


# ---------------------------------------------------------------------------------------- runtime choice
def _auto_choice():
    global _auto
    with _lock:
        if _auto is not None:
            return _auto
    m, d, _, _ = choose()
    with _lock:
        _auto = (m, d) if m else (None, None)
        return _auto


def active():
    """(method, device) the next transcode should try, or (None, None) for the CPU."""
    md = mode()
    if md == "off":
        return None, None
    if md == "auto":
        m, d = _auto_choice()
    else:
        d = (settings.get("hw_device") or "").strip()
        if not d or not os.path.exists(d):
            c = [x for x in candidates() if x[0] == md]
            d = c[0][1] if c else ("nvidia" if md == "nvenc" else "")
        m = md if d else None
    if not m:
        return None, None
    # A failed stream keeps its own sticky stage (see transcode.py). Do not take the
    # card away from every other stream -- that is what made the GPU/CPU badge flip.
    return m, d


def note_failure(method, device, stage, reason):
    """A stream had to leave `stage`. Recorded for Settings; it does not disable the card globally."""
    log.warning("hardware %s (%s) stage %s failed, falling back: %s", method, device, stage, reason)
    with _lock:
        _last_fail.update({"method": method, "device": device, "stage": stage, "reason": reason[:400], "at": int(time.time())})


_last_fail = {}


def card_name(device):
    for c in (_det or {}).get("cards", []):
        if c.get("render") == device or (device == "nvidia" and c["vendor"] == "nvidia"):
            return c["name"]
    return device or ""


def state():
    """Everything the Settings page shows."""
    det = detect()
    m, d = active() if mode() != "auto" or _auto is not None else (None, None)
    with _lock:
        held = [{"method": k[0], "device": k[1], "since": int(v[0]), "reason": v[1][:300]} for k, v in _failed.items()
                if time.time() - v[0] < FAIL_HOLD_S]
        tests = list(_last_test.values())
        lf = dict(_last_fail)
    return {"mode": mode(), "is_set": is_set(), "device": settings.get("hw_device") or "", "modes": list(MODES),
            "labels": LABEL, "active": {"method": m, "device": d, "name": card_name(d) if m else "",
                                        "resolving": mode() == "auto" and _auto is None},
            "detect": det, "candidates": [{"method": a, "device": b, "name": c} for a, b, c in candidates(det)],
            "setup": _info(), "held": held, "last_failure": lf, "tests": tests}


def warm_up():
    """Background at start: first start after an update with no setting yet -> scan + set; else resolve Auto.

    1.7.9: after the card is known, run a tiny VAAPI/NVENC encode so the first real movie is not a cold start.
    """
    try:
        if not is_set():
            setup(if_unset=True, by="first start of v%s" % _version())
        elif mode() == "auto":
            _auto_choice()
        else:
            detect()
        _warm_encoder()
    except Exception:
        log.exception("hardware detection failed")


def _warm_encoder():
    """Encode two black frames with the active method so the driver and encoder are resident."""
    m, dev = active()
    if not m or not dev:
        return
    # lavfi -> hwupload keeps this off the NAS and takes well under a second once the driver is up.
    cmd = [config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=30:d=0.2"]
    if m == "vaapi":
        cmd += ["-vaapi_device", dev, "-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi",
                "-frames:v", "2", "-f", "null", "-"]
    elif m == "nvenc":
        cmd += ["-c:v", "h264_nvenc", "-frames:v", "2", "-f", "null", "-"]
    elif m == "qsv":
        cmd += ["-init_hw_device", "qsv=hw:%s" % dev, "-filter_hw_device", "hw",
                "-vf", "format=nv12,hwupload=extra_hw_frames=16", "-c:v", "h264_qsv",
                "-frames:v", "2", "-f", "null", "-"]
    else:
        return
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=20)
        if r.returncode == 0:
            log.info("warmed %s on %s", m, dev)
        else:
            log.info("encoder warm-up skipped (%s): %s", m, (r.stderr or b"").decode(errors="replace")[:200])
    except (subprocess.TimeoutExpired, OSError) as e:
        log.info("encoder warm-up skipped: %s", e)


def _version():
    try:
        from .version import __version__
        return __version__
    except Exception:
        return "?"
