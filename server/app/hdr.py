"""2.6: detect HDR10, HLG, Dolby Vision, and mistagged HDR so tone-mapping can run.

Detection uses the bitstream's transfer function, a DOVI configuration record,
and mastering-display / content-light-level side data with BT.2020 or P3 primaries
on a 10- or 12-bit stream. Genuine SDR 10-bit (empty or bt709 tags, no HDR side
data) is left alone.

The detected kind is stored in items.hdr_type (additive column, schema stays at 15)
so the first play does not need a slow probe. A light idle backfill covers 4K Main 10
titles that were scanned before this version.
"""
from __future__ import annotations

import json
import logging
import subprocess

from . import config, db

log = logging.getLogger("media-server.hdr")

# Stored in items.hdr_type
KIND_HDR10 = "hdr10"
KIND_HLG = "hlg"
KIND_DV5 = "dv5"
KIND_DV7 = "dv7"
KIND_DV8 = "dv8"
KIND_MISTAGGED = "hdr10-mistagged"
KIND_SDR = "sdr"

PQ_KINDS = frozenset({KIND_HDR10, KIND_MISTAGGED, KIND_DV7, KIND_DV8})
TONEMAP_KINDS = frozenset({KIND_HDR10, KIND_HLG, KIND_MISTAGGED, KIND_DV7, KIND_DV8})
# Profile 5 has no HDR10 base layer; only libplacebo can map it correctly.
HDR_TRANSFERS = {
    "smpte2084": KIND_HDR10,
    "arib-std-b67": KIND_HLG,
}
WIDE_PRIMARIES = frozenset({
    "bt2020", "bt2020-ncl", "bt2020-cl", "bt2020nc", "bt2020c",
    "smpte432", "smpte431", "dci-p3", "dcip3", "p3d65", "p3-d65", "p3",
})
SDR_TRANSFERS = frozenset({"bt709", "bt470m", "bt470bg", "smpte170m", "smpte240m", "iec61966-2-1", "unknown", ""})

# Chromaticity (x, y) * 50000 as used in HEVC mastering display metadata.
# Match with a loose box so slight rounding still counts as P3 or BT.2020.
_P3_RGB = ((0.680, 0.320), (0.265, 0.690), (0.150, 0.060))
_BT2020_RGB = ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046))


def is_deep_bit(pix_fmt):
    pf = (pix_fmt or "").lower()
    return "10" in pf or "12" in pf or "p010" in pf or "p012" in pf


def kind_from_item(item):
    """Return the stored or inferred kind without probing the file."""
    k = (item.get("hdr_type") or "").strip()
    if k:
        return "" if k == KIND_SDR else k
    if not is_deep_bit(item.get("pix_fmt")):
        return ""
    return HDR_TRANSFERS.get((item.get("color_transfer") or "").strip().rstrip(","), "")


def needs_setparams(kind, item=None):
    """Mistagged or DV 8.1 files often advertise bt709 and need an input override."""
    if kind == KIND_MISTAGGED:
        return True
    if kind in (KIND_DV8, KIND_DV7):
        transfer = ((item or {}).get("color_transfer") or "").strip()
        return transfer not in ("smpte2084", "arib-std-b67")
    return False


def can_tonemap(kind, have_libplacebo=False):
    if kind in TONEMAP_KINDS:
        return True
    if kind == KIND_DV5 and have_libplacebo:
        return True
    return False


def classify_probe(info, pix_fmt=None):
    """Classify from an ffprobe stream (+ optional first-frame) dict.

    `info` is a video stream object, optionally with a `frames` list of
    ffprobe -show_frames objects used only for their side_data_list.
    """
    if info is None:
        return {"kind": "", "reason": "no-probe"}
    pf = pix_fmt or info.get("pix_fmt") or ""
    if not is_deep_bit(pf):
        return {"kind": "", "reason": "not-10bit"}

    side = list(info.get("side_data_list") or [])
    for fr in info.get("frames") or []:
        side.extend(fr.get("side_data_list") or [])

    dovi = _dovi(side)
    transfer = (info.get("color_transfer") or "").strip()
    primaries = (info.get("color_primaries") or "").strip()
    space = (info.get("color_space") or "").strip()
    wide = _wide_mastering(side) or primaries.lower() in WIDE_PRIMARIES
    cll = _content_light(side)
    mastering = _mastering(side)
    gamut = _gamut_from_side(side)

    if dovi:
        profile = dovi.get("profile")
        compat = dovi.get("compat")
        if profile == 5 or (profile is None and compat == 0):
            return {"kind": KIND_DV5, "reason": "dovi-profile-5", "dovi": dovi,
                    "transfer": transfer, "primaries": primaries, "space": space,
                    "hdr_primaries": gamut}
        if profile == 7:
            return {"kind": KIND_DV7, "reason": "dovi-profile-7", "dovi": dovi,
                    "transfer": transfer or "smpte2084", "primaries": primaries, "space": space,
                    "hdr_primaries": gamut}
        # Profile 8.x: 8.1 (compat 1) is PQ even when the base layer is flagged bt709.
        # 8.4 (compat 4) is HLG; 8.2 (compat 2) is an SDR-compatible base.
        if compat == 4 or transfer == "arib-std-b67":
            return {"kind": KIND_DV8, "reason": "dovi-profile-8-hlg", "dovi": dovi,
                    "transfer": "arib-std-b67", "primaries": primaries, "space": space,
                    "hdr_primaries": gamut}
        if compat == 2 and transfer in SDR_TRANSFERS and not wide and not mastering and not cll:
            # SDR-compatible DV 8.2 with no HDR side data: treat as SDR.
            return {"kind": KIND_SDR, "reason": "dovi-profile-8-sdr-compat", "dovi": dovi,
                    "transfer": transfer, "primaries": primaries, "space": space}
        # 8.1 or other profile 8 with PQ base (including mis-flagged bt709)
        kind = KIND_DV8
        reason = "dovi-profile-8-pq"
        if transfer != "smpte2084":
            reason = "dovi-profile-8-pq-mistagged"
        return {"kind": kind, "reason": reason, "dovi": dovi,
                "transfer": "smpte2084", "primaries": primaries or "bt2020", "space": space or "bt2020nc",
                "hdr_primaries": gamut}

    mapped = HDR_TRANSFERS.get(transfer)
    if mapped == KIND_HDR10:
        return {"kind": KIND_HDR10, "reason": "transfer-smpte2084",
                "transfer": transfer, "primaries": primaries, "space": space,
                "hdr_primaries": gamut if gamut != "bt2020" or (primaries or "").lower() in WIDE_PRIMARIES else (primaries or "bt2020")}
    if mapped == KIND_HLG:
        return {"kind": KIND_HLG, "reason": "transfer-hlg",
                "transfer": transfer, "primaries": primaries, "space": space,
                "hdr_primaries": gamut}

    # Mistagged HDR10: 10-bit stream tagged as SDR/bt709 (or unknown) but carrying
    # mastering-display or content-light-level data with BT.2020 / P3 primaries.
    if (mastering or cll) and (wide or _wide_mastering(side)):
        return {"kind": KIND_MISTAGGED, "reason": "mastering-or-cll-wide",
                "transfer": "smpte2084", "primaries": primaries or "bt2020",
                "space": space or "bt2020nc", "mastering": mastering, "cll": cll,
                "hdr_primaries": gamut}
    if (mastering or cll) and not wide:
        # Mastering present but primaries look like bt709 — still HDR if luminance is HDR-like.
        if _hdr_luminance(mastering, cll):
            return {"kind": KIND_MISTAGGED, "reason": "mastering-hdr-luminance",
                    "transfer": "smpte2084", "primaries": primaries or "bt2020",
                    "space": space or "bt2020nc", "mastering": mastering, "cll": cll,
                    "hdr_primaries": gamut}

    return {"kind": KIND_SDR, "reason": "sdr-10bit",
            "transfer": transfer, "primaries": primaries, "space": space}


def classify_path(path, frames=True):
    """Probe a file. Stream tags + side data first; optional first-frame side data."""
    info = probe_stream(path)
    if not info:
        return {"kind": "", "reason": "probe-failed"}
    result = classify_probe(info)
    # Frame side data only when the stream-level result is still ambiguous (SDR/empty
    # on a 10-bit file). Skip a slow decode when we already have a confident kind.
    if frames and result.get("kind") in ("", KIND_SDR) and is_deep_bit(info.get("pix_fmt")):
        frames_info = probe_frames(path)
        if frames_info:
            info["frames"] = frames_info
            result = classify_probe(info)
    return result


def probe_stream(path):
    try:
        o = subprocess.run(
            [config.FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_streams", "-print_format", "json", path],
            capture_output=True, timeout=30)
        if o.returncode != 0:
            return None
        data = json.loads(o.stdout or b"{}")
        streams = data.get("streams") or []
        return streams[0] if streams else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def probe_frames(path, count=2):
    """Read side data from the first few frames (no pixel decode of the whole file)."""
    try:
        o = subprocess.run(
            [config.FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-read_intervals", "%%+#%d" % count, "-show_frames",
             "-show_entries", "frame=side_data_list", "-print_format", "json", path],
            capture_output=True, timeout=45)
        if o.returncode != 0:
            return []
        data = json.loads(o.stdout or b"{}")
        return data.get("frames") or []
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []


def store(item_id, result):
    """Persist hdr_type and hdr_primaries (leave original color_* columns as probed)."""
    kind = result.get("kind") or KIND_SDR
    primaries = result.get("hdr_primaries") or None
    if not item_id:
        return
    try:
        with db.tx() as c:
            c.execute("UPDATE items SET hdr_type=?, hdr_primaries=? WHERE id=?", (kind, primaries, item_id))
    except Exception:
        log.exception("hdr store %s", item_id)


def hdr_info(item, probe=True):
    """Kind for a video item, preferring items.hdr_type so play does not ffprobe the NAS.

    Returns one of the KIND_* values, or "" for 8-bit / unknown.
    """
    if (item or {}).get("media_type") and item.get("media_type") != "video":
        return ""
    k = kind_from_item(item)
    if k:
        return k
    if not is_deep_bit(item.get("pix_fmt")) and item.get("pix_fmt"):
        return ""
    if not probe or not item.get("path"):
        return ""
    # Stream-only probe on first play (header, not a full decode).
    result = classify_path(item["path"], frames=False)
    kind = result.get("kind") or ""
    store(item.get("id"), result)
    if item is not None and kind:
        item["hdr_type"] = kind
        if result.get("hdr_primaries"):
            item["hdr_primaries"] = result["hdr_primaries"]
    return "" if kind == KIND_SDR else kind



def _gamut_from_side(side, item=None):
    """ffmpeg primaries name for tone-map input: smpte432 (P3-D65), smpte431 (DCI-P3), or bt2020."""
    if item:
        stored = (item.get("hdr_primaries") or "").strip()
        if stored in ("smpte432", "smpte431", "bt2020"):
            return stored
        # classify() result may already be on the item
        if item.get("mastering") or item.get("side_data_list"):
            side = list(side or [])
            if item.get("mastering") and not _mastering(side):
                side = side + [item["mastering"]]
            side = side + list(item.get("side_data_list") or [])
    rgb = _mastering_rgb(_mastering(side or []))
    if rgb and _matches_gamut(rgb, _P3_RGB, 0.06):
        wp = None
        md = _mastering(side or [])
        if md:
            wx = _num(md.get("white_point_x") if md.get("white_point_x") not in (None, "") else md.get("white_x"))
            wy = _num(md.get("white_point_y") if md.get("white_point_y") not in (None, "") else md.get("white_y"))
            wp = (wx, wy)
        # DCI-P3 illuminant (~0.314, 0.351); otherwise Display P3 / P3-D65 (typical).
        if wp and wp[0] is not None and wp[1] is not None and _close(wp, (0.314, 0.351), 0.01):
            return "smpte431"
        return "smpte432"
    if rgb and _matches_gamut(rgb, _BT2020_RGB, 0.06):
        return "bt2020"
    tagged = ((item or {}).get("color_primaries") or "").strip().lower()
    if tagged in WIDE_PRIMARIES:
        if tagged in ("smpte432", "p3d65", "p3-d65", "p3"):
            return "smpte432"
        if tagged in ("smpte431", "dci-p3", "dcip3"):
            return "smpte431"
        return "bt2020"
    return "bt2020"


def _input_color(kind, item=None):
    """(primaries, yuv matrix, transfer) for setparams / zscale input."""
    item = item or {}
    if kind == KIND_HLG or (kind == KIND_DV8 and item.get("color_transfer") == "arib-std-b67"):
        return "bt2020", "bt2020nc", "arib-std-b67"
    gamut = _gamut_from_side([], item)
    space = (item.get("color_space") or item.get("space") or "").strip().lower()
    if "2020" in space:
        minc = "bt2020nc"
    elif space in ("bt709", "smpte170m", "smpte240m", "bt601"):
        minc = "bt709"
    else:
        minc = "bt2020nc" if gamut == "bt2020" else "bt709"
    return gamut, minc, "smpte2084"


def software_tonemap_vf(kind, item=None, scale="scale=-2:'min(1080,ih)'"):
    """zscale + hable tonemap, with setparams when the file is mistagged."""
    pin, minc, tin = _input_color(kind, item)
    if kind == KIND_HLG or (kind == KIND_DV8 and (item or {}).get("color_transfer") == "arib-std-b67"):
        pre = ""
    else:
        pre = ("setparams=color_primaries=%s:color_trc=%s:colorspace=%s," % (pin, tin, minc)
               if needs_setparams(kind, item) else "")
    body = ("zscale=tin=%s:pin=%s:min=%s:t=linear:npl=100,format=gbrpf32le,"
            "tonemap=tonemap=hable:desat=0,"
            "zscale=t=bt709:m=bt709:p=bt709:r=tv,format=yuv420p" % (tin, pin, minc))
    if scale:
        return pre + body + "," + scale
    return pre + body


def vaapi_tonemap_vf(kind, item=None, gw="-2", height=1080):
    """GPU tone-map. Mistagged / DV8 with bt709 VUI: setparams on a downloaded P010 frame, then upload."""
    core = "scale_vaapi=w=%s:h=%d:format=p010,tonemap_vaapi=format=nv12:p=bt709:t=bt709:m=bt709" % (gw, height)
    if needs_setparams(kind, item):
        pin, minc, tin = _input_color(kind, item)
        return ("hwdownload,format=p010le,"
                "setparams=color_primaries=%s:color_trc=%s:colorspace=%s,"
                "hwupload=extra_hw_frames=64," + core) % (pin, tin, minc)
    return core


def libplacebo_tonemap_vf(kind, scale="scale=-2:'min(1080,ih)'"):
    """Best path for DV profile 5 when the filter exists."""
    vf = "libplacebo=tonemapping=hable:colorspace=bt709:color_trc=bt709:color_primaries=bt709:format=yuv420p"
    if scale:
        return vf + "," + scale
    return vf


# -------------------------------------------------------------------------------- side-data helpers

def _side_type(sd):
    return (sd.get("side_data_type") or sd.get("type") or "").lower()


def _dovi(side):
    for sd in side:
        t = _side_type(sd)
        if "dovi" in t or "dolby vision" in t:
            profile = _int(sd.get("dv_profile") or sd.get("profile"))
            level = _int(sd.get("dv_level") or sd.get("level"))
            compat = _int(sd.get("dv_bl_signal_compatibility_id")
                          or sd.get("bl_compatibility_id")
                          or sd.get("dv_bl_present") and None)
            # Some builds expose the record as a string in "dv_profile".
            return {"profile": profile, "level": level, "compat": compat, "raw": {k: sd[k] for k in sd}}
    return None


def _mastering(side):
    for sd in side:
        t = _side_type(sd)
        if "mastering" in t:
            return sd
    return None


def _content_light(side):
    for sd in side:
        t = _side_type(sd)
        if "content light" in t or t in ("cle", "cll"):
            return sd
    return None


def _xy(val):
    if val is None or val == "":
        return None
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        try:
            return float(val[0]), float(val[1])
        except (TypeError, ValueError):
            return None
    if isinstance(val, dict):
        try:
            return float(val.get("x")), float(val.get("y"))
        except (TypeError, ValueError):
            return None
    s = str(val)
    # "0.6800,0.3200" or "34000/50000"
    if "," in s:
        a, b = s.split(",", 1)
        try:
            return float(a), float(b)
        except ValueError:
            return None
    return None


def _mastering_rgb(sd):
    """Return [(rx,ry),(gx,gy),(bx,by)] from a mastering-display side-data object."""
    if not sd:
        return None
    # Common ffprobe keys
    keys = (
        ("red_x", "red_y", "green_x", "green_y", "blue_x", "blue_y"),
        None,
    )
    rx, ry = _num(sd.get("red_x")), _num(sd.get("red_y"))
    gx, gy = _num(sd.get("green_x")), _num(sd.get("green_y"))
    bx, by = _num(sd.get("blue_x")), _num(sd.get("blue_y"))
    if None not in (rx, ry, gx, gy, bx, by):
        return ((rx, ry), (gx, gy), (bx, by))
    # Some versions pack a string: G(13250,34500)B(7500,3000)R(34000,16000)WP(...)L(...)
    blob = sd.get("display") or sd.get("mastering_display") or ""
    if not blob:
        for v in sd.values():
            if isinstance(v, str) and "G(" in v and "R(" in v:
                blob = v
                break
    pts = _parse_mastering_string(blob)
    return pts


def _parse_mastering_string(blob):
    import re
    if not blob:
        return None
    found = {}
    for m in re.finditer(r"([RGB])\((\d+)\s*,\s*(\d+)\)", blob):
        found[m.group(1)] = (int(m.group(2)) / 50000.0, int(m.group(3)) / 50000.0)
    if set(found) >= {"R", "G", "B"}:
        return (found["R"], found["G"], found["B"])
    return None


def _close(pt, ref, tol=0.05):
    return abs(pt[0] - ref[0]) <= tol and abs(pt[1] - ref[1]) <= tol


def _matches_gamut(rgb, refs, tol=0.05):
    # refs is (R, G, B); allow any order? primaries should match by channel.
    if not rgb:
        return False
    return all(_close(rgb[i], refs[i], tol) for i in range(3))


def _wide_mastering(side):
    rgb = _mastering_rgb(_mastering(side))
    if not rgb:
        return False
    return _matches_gamut(rgb, _P3_RGB, 0.06) or _matches_gamut(rgb, _BT2020_RGB, 0.06)


def _hdr_luminance(mastering, cll):
    """True when max luminance / MaxCLL looks like HDR (well above SDR ~100 nits)."""
    nits = []
    if mastering:
        for key in ("max_luminance", "luminance_max", "max_luma"):
            v = _nits(mastering.get(key))
            if v:
                nits.append(v)
    if cll:
        for key in ("max_content", "max_cll", "max_average", "max_fall"):
            v = _nits(cll.get(key))
            if v:
                nits.append(v)
    return any(v >= 200 for v in nits)


def _nits(val):
    if val is None or val == "":
        return None
    s = str(val)
    if "/" in s:
        a, b = s.split("/", 1)
        try:
            return float(a) / float(b) if float(b) else float(a)
        except ValueError:
            return None
    try:
        v = float(s)
    except ValueError:
        return None
    # HEVC often stores luminance * 10000
    if v > 10000:
        v = v / 10000.0
    return v


def _num(val):
    if val is None or val == "":
        return None
    s = str(val)
    if "/" in s:
        a, b = s.split("/", 1)
        try:
            return float(a) / float(b) if float(b) else None
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _int(val):
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return None
