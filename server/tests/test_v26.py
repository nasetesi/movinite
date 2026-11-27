"""2.6: HDR detection for Dolby Vision and mistagged HDR10, plus tone-map filters."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="ms-v26-"))
(TMP / "data").mkdir()
os.environ["MS_DATA_DIR"] = str(TMP / "data")
os.environ["MS_SESSION_DAYS"] = "30"
os.environ.pop("MS_TMDB_KEY", None)

failed = 0


def check(cond, msg):
    global failed
    if cond:
        print("  ok  ", msg)
    else:
        failed += 1
        print("  FAIL", msg)


from app.version import __version__
from app import db, hdr, hwaccel, transcode, settings

db.migrate()


def stream(**extra):
    s = {
        "codec_type": "video",
        "codec_name": "hevc",
        "profile": "Main 10",
        "pix_fmt": "yuv420p10le",
        "width": 3840,
        "height": 2160,
        "color_transfer": "bt709",
        "color_primaries": "bt709",
        "color_space": "bt709",
        "side_data_list": [],
    }
    s.update(extra)
    return s


def p3_mastering(nits=1000):
    # DCI-P3 primaries in ffprobe fractions (value / 50000)
    return {
        "side_data_type": "Mastering display metadata",
        "red_x": "34000/50000", "red_y": "16000/50000",
        "green_x": "13250/50000", "green_y": "34500/50000",
        "blue_x": "7500/50000", "blue_y": "3000/50000",
        "white_x": "15635/50000", "white_y": "16450/50000",
        "max_luminance": "%d/10000" % (nits * 10000),
        "min_luminance": "1/10000",
    }


def cll(max_cll=586, max_fall=346):
    return {
        "side_data_type": "Content light level metadata",
        "max_content": str(max_cll),
        "max_average": str(max_fall),
    }


def dovi(profile, compat=None, level=6):
    sd = {"side_data_type": "DOVI configuration record", "dv_profile": profile, "dv_level": level}
    if compat is not None:
        sd["dv_bl_signal_compatibility_id"] = compat
    return sd


print("version and schema")
check(__version__ == "2.6", "version is 2.6 (2.5.10 rolls to the next minor)")
dbpy = (ROOT / "app/db.py").read_text()
check("SCHEMA_VERSION = 15" in dbpy, "schema stays at 15")
check('("items", "hdr_type", "TEXT")' in dbpy, "additive hdr_type column, no schema bump")
check('("items", "hdr_primaries", "TEXT")' in dbpy, "additive hdr_primaries column, no schema bump")
db.row("SELECT hdr_primaries FROM items LIMIT 1")
check(True, "hdr_primaries column is queryable")
row = db.row("SELECT hdr_type FROM items LIMIT 1")
# table exists and column is selectable
check(True, "hdr_type column is queryable")

print("classify: well-tagged HDR10 (Joker)")
joker = stream(color_transfer="smpte2084", color_primaries="bt2020", color_space="bt2020nc")
r = hdr.classify_probe(joker)
check(r["kind"] == hdr.KIND_HDR10 and r["reason"] == "transfer-smpte2084", "Joker-like smpte2084 -> hdr10")
check(not hdr.needs_setparams(r["kind"], joker), "well-tagged HDR10 does not need setparams")
check(hdr.can_tonemap(r["kind"]), "hdr10 can tone-map")

print("classify: DV 8.1 mistagged bt709 (One Last Shot)")
ols = stream(side_data_list=[dovi(8, 1)])
r = hdr.classify_probe(ols)
check(r["kind"] == hdr.KIND_DV8, "DV profile 8.1 -> dv8 (got %s)" % r["kind"])
check("mistagged" in r.get("reason", "") or r.get("transfer") == "smpte2084",
      "8.1 base is treated as PQ even when flagged bt709: %s" % r.get("reason"))
check(hdr.needs_setparams(r["kind"], ols), "DV 8.1 with bt709 VUI needs setparams")

print("classify: mistagged HDR10 with P3 mastering (Heart of the Beast)")
hotb = stream(side_data_list=[p3_mastering(1000), cll(586, 346)])
r = hdr.classify_probe(hotb)
check(r["kind"] == hdr.KIND_MISTAGGED, "Heart of the Beast-like -> hdr10-mistagged (got %s %s)" % (r["kind"], r.get("reason")))
check(hdr.needs_setparams(r["kind"], hotb), "mistagged HDR needs setparams")
check(hdr.can_tonemap(r["kind"]), "mistagged HDR can tone-map")
check(r.get("hdr_primaries") == "smpte432", "P3-D65 mastering stores hdr_primaries smpte432 (got %s)" % r.get("hdr_primaries"))

print("classify: genuine SDR 10-bit is left alone")
sdr = stream()
r = hdr.classify_probe(sdr)
check(r["kind"] == hdr.KIND_SDR, "10-bit bt709 with no HDR side data -> sdr (got %s)" % r["kind"])
check(not hdr.can_tonemap(r["kind"]), "SDR is not tone-mapped")
check(not hdr.needs_setparams(r["kind"], sdr), "SDR does not need setparams")

print("classify: HLG, DV5, 8-bit, DV 8.4")
hlg = stream(color_transfer="arib-std-b67", color_primaries="bt2020")
check(hdr.classify_probe(hlg)["kind"] == hdr.KIND_HLG, "HLG transfer -> hlg")
dv5 = stream(side_data_list=[dovi(5, 0)])
r = hdr.classify_probe(dv5)
check(r["kind"] == hdr.KIND_DV5, "DV profile 5 -> dv5")
check(not hdr.can_tonemap(r["kind"], have_libplacebo=False), "DV5 without libplacebo is not tone-mapped")
check(hdr.can_tonemap(r["kind"], have_libplacebo=True), "DV5 with libplacebo can tone-map")
dv84 = stream(side_data_list=[dovi(8, 4)])
check(hdr.classify_probe(dv84)["kind"] == hdr.KIND_DV8, "DV 8.4 -> dv8")
eight = stream(pix_fmt="yuv420p", color_transfer="bt709")
check(hdr.classify_probe(eight)["kind"] == "", "8-bit is not classified as HDR")

print("kind_from_item uses stored hdr_type (no probe)")
it = {"media_type": "video", "pix_fmt": "yuv420p10le", "hdr_type": "hdr10-mistagged",
      "color_transfer": "bt709", "path": "/no/such/file.mkv"}
check(hdr.kind_from_item(it) == hdr.KIND_MISTAGGED, "stored hdr_type wins over bt709 tags")
check(hdr.hdr_info(it, probe=False) == hdr.KIND_MISTAGGED, "hdr_info does not probe when hdr_type is set")
it_sdr = {"media_type": "video", "pix_fmt": "yuv420p10le", "hdr_type": "sdr", "color_transfer": "bt709"}
check(hdr.hdr_info(it_sdr, probe=False) == "", "stored sdr is reported as empty/not-HDR")
it_j = {"media_type": "video", "pix_fmt": "yuv420p10le", "color_transfer": "smpte2084"}
check(hdr.kind_from_item(it_j) == hdr.KIND_HDR10, "smpte2084 color_transfer infers hdr10 without hdr_type")

print("tone-map filters")
sw_m = hdr.software_tonemap_vf(hdr.KIND_MISTAGGED, hotb, scale="scale=-2:'min(1080,ih)'")
check("setparams=" in sw_m and "color_trc=smpte2084" in sw_m, "software mistagged filter overrides to smpte2084")
check("color_primaries=smpte432" in sw_m, "P3 mastering uses Display P3, not BT.2020")
check("zscale=" in sw_m and "tonemap=hable" in sw_m and "bt709" in sw_m, "software path is zscale+hable to bt709")
sw_j = hdr.software_tonemap_vf(hdr.KIND_HDR10, joker, scale="scale=-2:'min(1080,ih)'")
check("setparams=" not in sw_j and "tonemap=hable" in sw_j, "well-tagged HDR10 software path has no setparams")
va_m = hdr.vaapi_tonemap_vf(hdr.KIND_MISTAGGED, hotb, gw="-2", height=1080)
check("setparams=" in va_m and "hwdownload" in va_m and "tonemap_vaapi" in va_m,
      "VAAPI mistagged path setparams then tonemap_vaapi")
check("color_primaries=smpte432" in va_m, "VAAPI mistagged path uses Display P3")
va_j = hdr.vaapi_tonemap_vf(hdr.KIND_HDR10, joker, gw="-2", height=1080)
check("setparams=" not in va_j and va_j.startswith("scale_vaapi") and "tonemap_vaapi" in va_j,
      "VAAPI well-tagged path stays on the GPU")
sw_dv = hdr.software_tonemap_vf(hdr.KIND_DV8, ols, scale="scale=-2:1080")
check("setparams=" in sw_dv, "DV 8.1 software path overrides bt709 VUI")

print("hwaccel wiring (setting off/on, SDR never mapped)")
saved_filters = hwaccel._filters
hwaccel._filters = {"scale_vaapi", "tonemap_vaapi", "zscale", "tonemap", "setparams"}
settings.put("hdr_tonemap", "0")
check("tonemap_vaapi" not in hwaccel._vaapi_scale("-2", 1080, "HDR10"), "tone-map stays off while the setting is off")
check("tonemap" not in hwaccel.software_scale(1080, hdr="hdr10-mistagged"), "CPU tone-map stays off while the setting is off")
settings.put("hdr_tonemap", "1")
check("tonemap_vaapi" in hwaccel._vaapi_scale("-2", 1080, "HDR10"), "HDR10 uses tonemap_vaapi when enabled")
check("tonemap_vaapi" in hwaccel._vaapi_scale("-2", 1080, "HLG"), "HLG uses tonemap_vaapi when enabled")
vf_m = hwaccel._vaapi_scale("-2", 1080, "hdr10-mistagged", item=hotb)
check("setparams=" in vf_m and "tonemap_vaapi" in vf_m, "mistagged uses setparams + tonemap_vaapi")
vf_dv_hw = hwaccel._vaapi_scale("-2", 1080, "dv8", item=ols)
check("tonemap_vaapi" not in vf_dv_hw, "DV 8.1 must not use tonemap_vaapi (no mastering data)")
check("setparams=" in vf_dv_hw and "tonemap=hable" in vf_dv_hw, "DV 8.1 VAAPI graph still setparams + hable")
check("hwupload" in vf_dv_hw and "hwdownload" in vf_dv_hw, "DV 8.1 software map is uploaded back to VAAPI")
vf_sdr = hwaccel._vaapi_scale("-2", 1080, "", item=sdr)
check("tonemap_vaapi" not in vf_sdr, "genuine SDR is not tone-mapped when the setting is on")
vf_cpu_sdr = hwaccel.software_scale(1080, hdr="", item={"pix_fmt": "yuv420p10le", "hdr_type": "sdr", "color_transfer": "bt709"})
check("tonemap" not in vf_cpu_sdr and "setparams" not in vf_cpu_sdr, "CPU path leaves SDR untouched")
vf_dv5 = hwaccel._vaapi_scale("-2", 1080, "dv5")
check("tonemap_vaapi" not in vf_dv5, "DV profile 5 without libplacebo is not tone-mapped")
# with libplacebo
hwaccel._filters = {"scale_vaapi", "tonemap_vaapi", "libplacebo"}
vf_dv5p = hwaccel._vaapi_scale("-2", 1080, "dv5")
check("libplacebo" in vf_dv5p, "DV profile 5 uses libplacebo when the filter exists")
hwaccel._filters = saved_filters
settings.put("hdr_tonemap", "0")

print("transcode labels")
check(transcode._hdr_label("hdr10") == "HDR10", "hdr10 labels as HDR10")
check(transcode._hdr_label("hdr10-mistagged") == "HDR10", "mistagged labels as HDR10 for caps")
check(transcode._hdr_label("dv8") == "HDR10", "dv8 PQ base labels as HDR10 for caps")
check(transcode._hdr_label("hlg") == "HLG", "hlg labels as HLG")
check(transcode._hdr_label("dv5") == "DV5", "dv5 labels as DV5")
check(transcode._hdr_label("sdr") == "", "sdr labels as empty")
it = {"media_type": "video", "pix_fmt": "yuv420p10le", "hdr_type": "hdr10", "color_transfer": "smpte2084"}
check(transcode.hdr_info(it) == "HDR10", "hdr_info still returns HDR10 for well-tagged files")
check(transcode.native_hdr_ok({"media_type": "video", "pix_fmt": "yuv420p10le", "hdr_type": "sdr"},
                             {"native": True, "hdr10": False}),
      "SDR 10-bit is allowed as Direct Play without an HDR panel")

print("preload backfill and scan hook")
pre = (ROOT / "app/preload.py").read_text()
med = (ROOT / "app/media.py").read_text()
scan = (ROOT / "app/scanner.py").read_text()
check("def _do_one_hdr" in pre and "if _do_one_hdr()" in pre, "idle job backfills hdr_type for 4K Main 10")
check("hdr_type IS NULL" in pre and "3840" in pre, "backfill is limited to unclassified 4K 10-bit items")
check("classify_probe" in med, "library scan classifies from stream side data")
check('"hdr_type"' in scan and '"hdr_primaries"' in scan, "scanner persists hdr_type and hdr_primaries")

if failed:
    print("FAILED", failed)
    raise SystemExit(1)

print("all ok")
