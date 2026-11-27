"""2.6.1: captions turned the picture solid green on the GPU server (PGS burn-in on VAAPI).

Root cause: the 2.6 burn chain decoded on one VAAPI device (-hwaccel_device /dev/dri/...)
and uploaded the subtitle plane to a second one (-init_hw_device vaapi=hw:...), then mixed
the two in overlay_vaapi. On the Arc A310 / iHD 24.1 / ffmpeg 6.1.1 every output frame was
solid green; even on one device overlay_vaapi drew a pink box behind each line.
Fix: one shared device, GPU decode/scale/tonemap -> hwdownload -> CPU overlay -> hwupload.
"""
import os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="ms-gs261-"))
(TMP / "data").mkdir()
os.environ["MS_DATA_DIR"] = str(TMP / "data")
os.environ.pop("MS_TMDB_KEY", None)

failed = 0
def check(cond, msg):
    global failed
    if cond:
        print("  ok  ", msg)
    else:
        failed += 1
        print("  FAIL", msg)

from app import db, transcode, hwaccel, settings, hdr as hdrmod
from app.server import playback_info
db.migrate()

DEV = "/dev/dri/renderD128"
hwaccel._filters = {"scale_vaapi", "tonemap_vaapi", "overlay_vaapi", "zscale", "tonemap", "hwupload", "hwdownload"}
_real_active = hwaccel.active
hwaccel.active = lambda: ("vaapi", DEV)
transcode.hdr_kind = lambda it, probe=True: it.get("hdr_type", "")

def film(**extra):
    it = {"id": 1, "path": "/tmp/f.mkv", "width": 1920, "height": 1080, "vcodec": "hevc",
          "media_type": "video", "duration": 6000, "bitrate": 8000000, "mtime": 1.0,
          "container": "matroska,webm", "pix_fmt": "yuv420p10le",
          "audio_streams": "[]", "subtitle_streams": "[]", "external_subs": "[]", "acodec": "aac"}
    it.update(extra)
    return it

def cmd_for(it, stage, burn=2, profile="1080p", start=1887):
    s = transcode.Session("t", it, profile, 0, burn=burn)
    if stage not in s.stages:
        return None, s
    s.stage_i = s.stages.index(stage)
    return s._cmd(start), s

def fc_of(cmd):
    return cmd[cmd.index("-filter_complex") + 1] if "-filter_complex" in cmd else ""

def opt(cmd, name):
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == name and i + 1 < len(cmd)]

print("one VAAPI device for decode + filters (John Adams S01E01, 1080p HEVC 10-bit, PGS)")
ja = film()
cmd, s = cmd_for(ja, "full")
check(cmd is not None and "full" in s.stages, "burn keeps the full GPU stage on VAAPI")
check(opt(cmd, "-init_hw_device") == ["vaapi=hw:%s" % DEV], "exactly one -init_hw_device")
check(opt(cmd, "-hwaccel_device") == ["hw"], "decoder uses the named device, not a second open of the path")
check(opt(cmd, "-filter_hw_device") == ["hw"], "filters upload to that same device")
check(cmd.index("-init_hw_device") < cmd.index("-hwaccel_device") < cmd.index("-i"),
      "device is created before the decoder references it")
fc = fc_of(cmd)
check("overlay_vaapi" not in fc, "no overlay_vaapi (green / pink box on the Arc)")
check("scale_vaapi=w=-2:h=1080:format=nv12,hwdownload,format=nv12[base]" in fc, "GPU decode+scale, then download NV12")
check("[0:2]format=yuva420p" in fc and "color=black@0[sub]" in fc, "subtitle plane rendered on the CPU with alpha")
check("[base][sub]overlay=0:0:eof_action=pass:repeatlast=0,format=nv12,hwupload=extra_hw_frames=64[vout]" in fc,
      "CPU overlay, then upload for h264_vaapi")
check("h264_vaapi" in cmd and "-sn" not in cmd, "encodes on the GPU; subtitle stream is not dropped")
check(cmd.count("-ss") == 1 and opt(cmd, "-ss") == ["3774.000"], "restart at the seek offset keeps one input seek")

print("4K SDR ultra-wide (Zootopia 3840x1608) at 1080p")
zo = film(width=3840, height=1608, color_transfer="bt709")
cmd, _ = cmd_for(zo, "full", start=30)
fc = fc_of(cmd)
check("scale=2578:1080" in fc and "pad=2578:1080" in fc, "subtitle plane matches the 2578x1080 output")
check("tonemap" not in fc, "10-bit SDR is not tone-mapped")

print("HDR tone-map paths keep working with burn-in")
settings.put("hdr_tonemap", "1")
jk = film(width=3840, height=2160, color_transfer="smpte2084", color_primaries="bt2020", hdr_type=hdrmod.KIND_HDR10)
cmd, _ = cmd_for(jk, "full", start=314)
fc = fc_of(cmd)
check("tonemap_vaapi=format=nv12" in fc and fc.index("tonemap_vaapi") < fc.index("hwdownload,format=nv12[base]"),
      "HDR10: tonemap_vaapi (P010 -> NV12) before the download and overlay")
check(opt(cmd, "-hwaccel_device") == ["hw"], "HDR10 burn shares one device")
mis = film(width=3840, height=2160, color_transfer="bt709", hdr_type=hdrmod.KIND_MISTAGGED)
fc = fc_of(cmd_for(mis, "full", start=314)[0])
check("setparams=" in fc and fc.rstrip().count("hwdownload") == 2 and "overlay_vaapi" not in fc,
      "mistagged HDR10: setparams chain, then download for the overlay")
dv8 = film(width=3840, height=2160, color_transfer="smpte2084", color_primaries="bt2020", hdr_type=hdrmod.KIND_DV8)
fc = fc_of(cmd_for(dv8, "full", start=314)[0])
check("tonemap=tonemap=" in fc and fc.endswith("[vout]") and "hwdownload,format=nv12[base]" in fc,
      "Dolby Vision 8.1: software tone-map inside the full chain, then overlay")
cmd, _ = cmd_for(jk, "enc", start=314)
fc = fc_of(cmd)
check("zscale=" in fc and "tonemap=" in fc and fc.index("tonemap=") < fc.index("[base]"),
      "enc stage keeps the software tone-map (2.6 dropped it when burning)")
check(fc.split("[base]")[0].count("hwupload") == 0 and "hwupload=extra_hw_frames=64[vout]" in fc,
      "enc stage overlays before the single upload")
cmd, _ = cmd_for(jk, "cpu", start=314)
fc = fc_of(cmd)
check("tonemap=" in fc and "libx264" in cmd and "hwupload" not in fc, "CPU stage keeps the tone-map, no upload")
settings.put("hdr_tonemap", "0")
fc = fc_of(cmd_for(jk, "full", start=314)[0])
check("tonemap" not in fc, "tone-map stays off when the setting is off")

print("no burn = unchanged 2.6 command")
cmd, _ = cmd_for(ja, "full", burn=0)
check("-sn" in cmd and "-filter_complex" not in cmd and opt(cmd, "-hwaccel_device") == [DEV],
      "text subs / no subs: -sn, no filter_complex, original device args")

print("text subtitles stay WebVTT sidecars (no transcode restart, phone and TV)")
import json
subs = json.dumps([{"index": 2, "codec": "subrip", "lang": "eng", "title": "English", "text": True},
                   {"index": 3, "codec": "hdmv_pgs_subtitle", "lang": "eng", "title": "English", "text": False}])
pb = playback_info(film(subtitle_streams=subs))
k = {x["key"]: x for x in pb["subtitles"]}
check(not k["s2"].get("burn") and k["s2"]["kind"] == "text", "SRT track is a soft text track")
check(k["s3"].get("burn") and k["s3"]["kind"] == "image", "PGS track is burned in")
appjs = (ROOT / "app/static/app.js").read_text()
check("if (P && (wasBurn || nowBurn))" in appjs and "addSubTrack(key);" in appjs,
      "web player restarts only when a burned track is involved; text tracks load as VTT")

print("helpers")
check(hwaccel.vaapi_one_device(["-threads", "1", "-hwaccel", "vaapi", "-hwaccel_device", DEV,
                                "-init_hw_device", "vaapi=x:" + DEV, "-filter_hw_device", "x"], DEV)
      == ["-init_hw_device", "vaapi=hw:" + DEV, "-threads", "1", "-hwaccel", "vaapi", "-hwaccel_device", "hw",
          "-filter_hw_device", "hw"], "vaapi_one_device drops stray devices and names one")
check(hwaccel._strip_hwupload("scale=1:2,format=nv12,hwupload=extra_hw_frames=64") == "scale=1:2,format=nv12",
      "_strip_hwupload removes only a trailing upload")
check(hwaccel._strip_hwupload("hwdownload,format=p010le,hwupload,scale_vaapi=w=1:h=2") ==
      "hwdownload,format=p010le,hwupload,scale_vaapi=w=1:h=2", "_strip_hwupload keeps a mid-chain upload")
check(hwaccel.burn_needs_hw_device("full", "vaapi") and hwaccel.burn_needs_hw_device("enc", "vaapi")
      and not hwaccel.burn_needs_hw_device("cpu", "cpu"), "burn_needs_hw_device")

hwaccel.active = _real_active
hwaccel._filters = None
print()
if failed:
    print("%d failed" % failed)
    sys.exit(1)
print("all passed")
