"""On-demand HLS transcoding with ffmpeg.

The playlist for an item is generated up-front as a VOD playlist (fixed SEG-second segments covering the
whole duration), so the browser can seek anywhere. One ffmpeg process per session produces segments
from a start segment onward; a request for a segment far from what is being produced restarts ffmpeg at
that segment (that is how seeking works). Keyframes are forced every SEG seconds and timestamps are
offset to the segment start, so segments from different ffmpeg runs line up.
"""
import logging
import math
import os
import shutil
import signal
import subprocess
import threading
import time
import hashlib
import json

from . import config, db, hwaccel

log = logging.getLogger("media-server.transcode")

SEG = 2.0                 # 1.7.9: short segments so the first picture can appear sooner
IDLE_KILL_S = 90          # no segment requests for this long -> kill + delete session
AHEAD_PAUSE_S = 150.0     # pause ffmpeg when it is this far (seconds) ahead of the player
AHEAD_RESUME_S = 72.0
AHEAD_PAUSE = AHEAD_PAUSE_S   # name kept; value is seconds (was a 6s-segment count)
AHEAD_RESUME = AHEAD_RESUME_S
RESTART_AHEAD_S = 60.0    # restart ffmpeg only if the request is this far past the produced tip
HW_STALL_S = 20          # 1.5.2: a GPU run that makes no segment in this long falls back
HW_RETRY_MAX = 1          # 1.7.7: one extra hardware launch after an unexpected VAAPI/NVENC exit
HW_RETRY_BACKOFF_S = 1.5  # wait before that retry so we never tight-loop
LOG_TAIL_N = 50           # ffmpeg stderr lines to copy into the journal on a non-zero exit

PROFILES = {
    # name: (max height, video kbps, audio kbps)
    "2160p": (2160, 25000, 192),     # 1.5.3: 4K and 2K, GPU only (see HIRES)
    "1440p": (1440, 12000, 192),
    "1080p": (1080, 8000, 192),
    "720p": (720, 4000, 160),
    "480p": (480, 1500, 128),
    "360p": (360, 800, 96),
    "audio": (0, 0, 192),
}
# 1.5.3: 2K / 4K. Offered only while hardware transcoding is on and never above the source. The picture is fitted
# into the box (a 3840x1600 scope film stays 3840x1600 at "4K", 2560x1066 at "2K"). "<name>.hevc" is the same
# quality as HEVC in fMP4 segments (hls.js / Safari can't take HEVC in MPEG-TS), for players that decode HEVC.
# Bitrates: H.264 4K 25 Mbps, 2K 12 Mbps; HEVC 4K 16 Mbps, 2K 8 Mbps (HEVC needs about 35 % less);
# never more than 1.2x the source's own bitrate (min 6 Mbps).
HIRES = {"2160p": (3840, 2160), "1440p": (2560, 1440)}
HEVC_KBPS = {"2160p": 16000, "1440p": 8000}
# 1.5.4: H.264 needs roughly 1.5-2x the bitrate of HEVC / AV1 / VP9 for the same picture, so 1.2x such a source was too
# little (a 6.7 Mbps HEVC 4K film became a smeary 6.4 Mbps H.264 stream).  For those sources the H.264 average is now
# 1.8x the source, at least the floor below, and never more than the profile's own ceiling.  H.264 sources and HEVC
# output keep the 1.5.3 rule.  Values are the average (-b:v) in kbps; maxrate is 1.25x that and bufsize 2x maxrate.
MODERN_CODECS = ("hevc", "h265", "av1", "vp9")
MODERN_FACTOR = 1.8
H264_FLOOR_KBPS = {"2160p": 12000, "1440p": 8000}   # 1080p and below already get the full profile rate
CPU_FALLBACK_BOX = (1920, 1080)   # a 2K/4K H.264 stream that loses the GPU carries on at 1080p on the CPU


def split_profile(profile):
    base, _, vc = (profile or "").partition(".")
    return base, vc


def valid_profile(profile):
    base, vc = split_profile(profile)
    return base in PROFILES and (vc == "" or (vc == "hevc" and base in HIRES))


def video_kbps(item, base, hevc_out=False, cpu=False):
    """Maxrate (kbps) for a video transcode.  stage_args / libx264 use it as -maxrate (GPU: -b:v is 0.8x of it)."""
    maxh, vk, _ak = PROFILES.get(base, PROFILES["720p"])
    src_kbps = int((item.get("bitrate") or 0) / 1000)
    modern = (item.get("vcodec") or "").lower() in MODERN_CODECS
    if base in HIRES:
        if hevc_out:
            vk = HEVC_KBPS[base]
        if src_kbps > 0:
            if modern and not hevc_out:
                avg = max(H264_FLOOR_KBPS[base], int(src_kbps * MODERN_FACTOR))
                vk = min(vk, int(avg * 1.25))
            else:
                vk = min(vk, max(6000, int(src_kbps * 1.2)))
        if cpu:
            vk = min(vk, PROFILES["1080p"][1])
    return vk


def is_hires(profile):
    return split_profile(profile)[0] in HIRES


def fit_box(w, h, bw, bh):
    """Output size inside bw x bh keeping the aspect ratio, never larger than the source, even numbers."""
    if not w or not h:
        return None
    sc = min(1.0, bw / float(w), bh / float(h))
    return max(2, int(w * sc) // 2 * 2), max(2, int(h * sc) // 2 * 2)



# 1.7.8: cap quality to the device's screen (and decoder, when the player reports one).
# Longer side of each profile's 16:9 box. A 1920x1200 tablet caps at 1080p (1920), not 1440p (2560).
PROFILE_LONG = {"360p": 640, "480p": 854, "720p": 1280, "1080p": 1920, "1440p": 2560, "2160p": 3840}
QUALITY_LADDER = ("360p", "480p", "720p", "1080p", "1440p", "2160p")


def profile_rank(base):
    try:
        return QUALITY_LADDER.index(base)
    except ValueError:
        return -1


def device_cap_base(disp_px=0, dec_px=0):
    """Highest profile whose box longer side fits the tightest of the display and decoder limits.

    disp_px / dec_px are 0 or missing when unknown (no cap from that source).
    A few pixels of slack cover odd sizes like 1918.
    """
    limit = 0
    for v in (disp_px, dec_px):
        try:
            v = int(v or 0)
        except (TypeError, ValueError):
            v = 0
        if v > 0:
            limit = v if limit <= 0 else min(limit, v)
    if limit <= 0:
        return None
    cap = "360p"
    for p in QUALITY_LADDER:
        if PROFILE_LONG[p] <= limit + 16:
            cap = p
        else:
            break
    return cap


def source_long_px(item):
    return max(int(item.get("width") or 0), int(item.get("height") or 0))


def source_fits_cap(item, cap_base):
    """True when the file's longer side fits the cap profile's box (or there is no cap)."""
    if not cap_base or cap_base not in PROFILE_LONG:
        return True
    long = source_long_px(item)
    if long <= 0:
        return True
    return long <= PROFILE_LONG[cap_base] + 16


def parse_cap_args(disp=0, dec=0, nocap=0):
    def n(v):
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0
    return n(disp), n(dec), bool(n(nocap))


def clamp_profile(profile, item, disp_px=0, dec_px=0, nocap=False):
    """Return (effective_profile, cap_base or None, changed).

    remux/direct are refused (effective_profile is None) when the source is larger than the cap.
    """
    cap = None if nocap else device_cap_base(disp_px, dec_px)
    if not cap:
        return profile, None, False
    if profile in ("remux", "direct"):
        if source_fits_cap(item, cap):
            return profile, cap, False
        return None, cap, True
    if profile == "audio" or not valid_profile(profile):
        return profile, cap, False
    base, vc = split_profile(profile)
    if profile_rank(base) <= profile_rank(cap):
        return profile, cap, False
    new = cap + (".hevc" if vc == "hevc" and cap in HIRES else "")
    return new, cap, True


def hires_ok(item, base):
    """Is the source at least this big (by width or height)?  A 3840x1600 film counts as 4K."""
    w, h = item.get("width") or 0, item.get("height") or 0
    bw, bh = HIRES[base]
    return w >= bw * 0.94 or h >= bh * 0.94


_hdr_cache = {}


def _hdr_from_transfer(t):
    t = (t or "").strip().rstrip(",")
    return "HDR10" if t == "smpte2084" else "HLG" if t == "arib-std-b67" else ""


def hdr_info(item):
    """'HDR10' / 'HLG' / '' for a video item (10-bit sources only).

    1.7.9: prefer color_transfer saved at library-scan time so play does not ffprobe the NAS.
    """
    pf = item.get("pix_fmt") or ""
    if item.get("media_type") != "video" or ("10" not in pf and "12" not in pf):
        return ""
    if item.get("color_transfer"):
        v = _hdr_from_transfer(item.get("color_transfer"))
        _hdr_cache[(item.get("path"), item.get("mtime"))] = v
        return v
    key = (item.get("path"), item.get("mtime"))
    if key in _hdr_cache:
        return _hdr_cache[key]
    v = ""
    try:
        o = subprocess.run([config.FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=color_transfer", "-of", "csv=p=0", item["path"]], capture_output=True, timeout=20)
        t = o.stdout.decode(errors="replace").strip().splitlines()
        t = t[0].strip().rstrip(",") if t else ""
        v = _hdr_from_transfer(t)
        if t and item.get("id") and v:
            try:
                with db.tx() as c:
                    c.execute("UPDATE items SET color_transfer=? WHERE id=?", (t, item["id"]))
            except Exception:
                pass
    except (OSError, subprocess.TimeoutExpired):
        v = ""
    if len(_hdr_cache) > 2000:
        _hdr_cache.clear()
    _hdr_cache[key] = v
    return v


class Session:
    def __init__(self, sid, item, profile, audio_idx, bounds=None):
        self.sid = sid
        self.bounds = bounds            # remux: segment start times (keyframes)
        self.item = item
        self.profile = profile
        self.audio_idx = audio_idx
        self.dir = config.TRANSCODE_DIR / sid
        self.dir.mkdir(parents=True, exist_ok=True)
        self.proc = None
        self.start_seg = 0
        self.last_req = 0
        self.last_access = time.time()
        self.paused = False
        self.lock = threading.Lock()
        # 1.5.2: hardware encoding -- try full GPU, then CPU decode + GPU encode, then the CPU (libx264)
        self.hw = (None, None)
        self.base, self.vc = split_profile(profile)
        src_hevc = (item.get("vcodec") or "").lower() in ("hevc", "h265")
        self.hevc = self.vc == "hevc" or (profile == "remux" and src_hevc)
        self.ext = "m4s" if self.hevc else "ts"
        self.failed = None
        self.player_id = ""
        self.hw_retries = {}      # stage -> number of unexpected hardware retries already used
        self.last_rc = None
        self._planned_stop = False
        if profile not in ("remux", "audio") and item.get("vcodec") and item.get("media_type") == "video":
            self.hw = hwaccel.active()
        if self.base in HIRES and not self.hw[0]:
            raise ValueError("2K / 4K need hardware transcoding")
        self.rot = 0
        self.stages = ["full", "enc", "cpu"] if self.hw[0] else ["cpu"]
        if self.hw[0]:
            self.rot = hwaccel.rotation(item)
            if self.rot and self.hw[0] == "nvenc":
                self.stages = ["enc", "cpu"]     # no GPU rotate filter for CUDA frames in ffmpeg 6.1
        if self.hevc:
            self.stages = [x for x in self.stages if x != "cpu"]   # no CPU HEVC: the player steps down instead
        self.stage_i = 0
        self.fallbacks = []
        self.started_at = 0
        if bounds:
            self.nseg = len(bounds)
        else:
            self.nseg = max(1, math.ceil((item.get("duration") or SEG) / SEG))

    # --- ffmpeg -----------------------------------------------------------
    def _audio_copy_or_aac(self, cmd):
        auds = json.loads(self.item.get("audio_streams") or "[]")
        a = auds[self.audio_idx] if self.audio_idx < len(auds) else (auds[0] if auds else {})
        if a.get("codec") in ("aac", "mp3") and (a.get("channels") or 2) <= 2:
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", "aac", "-ac", "2", "-b:a", "192k", "-ar", "48000"]
        return cmd

    def _remux_cmd(self, start):
        """Copy the video, convert only the audio if needed; cut exactly at the probed keyframes.

        H.264 is remuxed to MPEG-TS. HEVC is remuxed to fMP4 (hls.js cannot play HEVC in MPEG-TS).
        """
        it = self.item
        b = self.bounds
        cmd = [config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "warning"]
        seek = 0.0
        if start > 0:
            # ffmpeg seeks a little before -ss for formats with B-frames; +0.2 s lands exactly on keyframe b[start]
            seek = b[start] + 0.2
            cmd += ["-ss", "%.3f" % seek]
        cmd += ["-i", it["path"], "-map", "0:v:0", "-map", "0:a:%d?" % self.audio_idx, "-sn", "-dn", "-c:v", "copy"]
        if self.hevc:
            cmd += ["-tag:v", "hvc1"]
        cmd = self._audio_copy_or_aac(cmd)
        if self.hevc:
            # HLS fMP4, split on keyframes near SEG; init + m4s, same layout as a HEVC transcode.
            cmd += ["-max_muxing_queue_size", "4096", "-f", "hls", "-hls_time", str(int(SEG)),
                    "-hls_list_size", "0", "-hls_segment_type", "fmp4",
                    "-hls_fmp4_init_filename", "init%d.mp4" % start,
                    "-hls_segment_options", "movflags=+frag_discont",
                    "-hls_flags", "temp_file+independent_segments",
                    "-start_number", str(start), "-output_ts_offset", "%.3f" % seek,
                    "-hls_segment_filename", str(self.dir / "seg%d.m4s"),
                    str(self.dir / "ffmpeg.m3u8")]
            return cmd
        # split points relative to the first packet; -0.25 s so float rounding can never skip a keyframe
        times = ["%.3f" % max(0.05, t - b[start] - 0.25) for t in b[start + 1:]]
        cmd += ["-max_muxing_queue_size", "4096", "-f", "segment", "-segment_format", "mpegts"]
        if times:
            cmd += ["-segment_times", ",".join(times)]
        else:
            cmd += ["-segment_time", "100000"]
        cmd += ["-segment_start_number", str(start), "-segment_list", str(self.dir / ("list%d.csv" % start)),
                "-segment_list_type", "csv", "-output_ts_offset", "%.3f" % seek,
                str(self.dir / "seg%d.ts")]
        return cmd

    @property
    def stage(self):
        return self.stages[self.stage_i]

    @property
    def encoder(self):
        """'cpu' or the hardware method this run uses."""
        return "cpu" if self.profile == "remux" or self.stage == "cpu" else self.hw[0]

    def _fallback(self, seg, reason):
        """The GPU run failed: log it, move to the next stage and restart at `seg`."""
        method, dev = self.hw
        old = self.stage
        if not self.hevc:      # an HEVC-only problem must not take the card away from H.264 streams
            hwaccel.note_failure(method, dev, old, reason)
        self.fallbacks.append({"stage": old, "reason": reason[:300], "at": int(time.time())})
        if self.stage_i + 1 >= len(self.stages):
            # 1.5.3: HEVC 2K/4K has no CPU stage -- the session fails and the player switches to H.264
            self.failed = reason[:300]
            log.warning("transcode %s: %s stage %s failed (%s), no more stages", self.sid, method, old, reason[:200])
            self.stop()
            return
        self.stage_i += 1
        nxt = "CPU" if self.stage == "cpu" else "CPU decode + %s encode" % method
        log.warning("transcode %s: %s stage %s failed (%s) -> %s (sticky for this stream)",
                    self.sid, method, old, reason[:200], nxt)
        remember_stage(self.sid, self.stage, reason, failed=old)
        self.start(seg)

    def _log_tail(self, n=3, joiner=" | "):
        try:
            lines = [l for l in (self.dir / "ffmpeg.log").read_text(errors="replace").splitlines() if l.strip()]
            return joiner.join(lines[-n:]) or "ffmpeg exited"
        except OSError:
            return "ffmpeg exited"

    def _start_with_backoff(self, n):
        if self.last_rc not in (None, 0) and time.time() - (self.started_at or 0) < 8:
            time.sleep(HW_RETRY_BACKOFF_S)
        if getattr(self, "destroyed", False):
            return
        self.start(n)

    def _handle_not_running(self, n):
        """ffmpeg is not running and segment n is not ready: seek, one hardware retry, or sticky fallback."""
        rc = self._reap(planned=False)
        if self.failed or getattr(self, "destroyed", False):
            return
        died_empty = (self.started_at and self.profile != "remux" and not self._ready(self.start_seg))
        unexpected = (self.started_at and not self._planned_stop
                      and (died_empty or (rc not in (None, 0) and rc is not True)))
        if self.profile == "remux" or self.stage == "cpu" or not self.hw[0]:
            self._start_with_backoff(n)
            return
        if unexpected:
            reason = self._log_tail(8) or "ffmpeg exited"
            used = self.hw_retries.get(self.stage, 0)
            if used < HW_RETRY_MAX:
                self.hw_retries[self.stage] = used + 1
                log.warning("transcode %s: %s stage %s exited (%s), retrying hardware once after %.1fs",
                            self.sid, self.encoder, self.stage, reason[:200], HW_RETRY_BACKOFF_S)
                time.sleep(HW_RETRY_BACKOFF_S)
                if getattr(self, "destroyed", False) or self.failed:
                    return
                self.start(n)
                return
            self._fallback(n, reason)
            return
        self.start(n)

    def _cmd(self, start):
        if self.profile == "remux":
            return self._remux_cmd(start)
        it = self.item
        maxh, vk, ak = PROFILES.get(self.base, PROFILES["720p"])
        audio_only = self.profile == "audio" or not it.get("vcodec")
        box = None          # 1.5.3: 2K / 4K -- explicit output size fitted into the box
        if self.base in HIRES and not audio_only:
            vk = video_kbps(it, self.base, self.hevc, self.stage == "cpu")
            sw, sh = it.get("width") or 0, it.get("height") or 0
            if self.rot in (90, 270):
                sw, sh = sh, sw
            bw, bh = HIRES[self.base] if self.stage != "cpu" else CPU_FALLBACK_BOX
            box = fit_box(sw, sh, bw, bh)
        t0 = start * SEG
        cmd = [config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "warning"]
        hw = None
        if not audio_only and self.stage != "cpu":
            src_h = it.get("height") or maxh
            h = min(maxh, src_h) if src_h else maxh
            hk = vk
            if src_h and src_h < maxh:
                hk = max(600, int(vk * (src_h / maxh) ** 1.5))
            if box:
                h, hk = box[1], vk
            hw = hwaccel.stage_args(self.hw[0], self.hw[1], self.stage, h, hk, self.rot,
                                    width=box[0] if box else None, codec="hevc" if self.hevc else "h264",
                                    hdr=hdr_info(it))
            cmd += hw[0]
        elif config.HWACCEL and not audio_only:
            cmd += ["-hwaccel", config.HWACCEL]
        cmd += ["-ss", "%.3f" % t0, "-i", it["path"]]
        if audio_only:
            cmd += ["-map", "0:a:%d?" % self.audio_idx, "-vn", "-sn", "-dn"]
        else:
            cmd += ["-map", "0:v:0", "-map", "0:a:%d?" % self.audio_idx, "-sn", "-dn"]
            src_h = it.get("height") or maxh
            h = min(maxh, src_h) if src_h else maxh
            # scale bitrate down for small sources
            if src_h and src_h < maxh and not box:      # 1.5.4: 2K/4K already sized for the fitted box
                vk = max(600, int(vk * (src_h / maxh) ** 1.5))
            vf = "scale=-2:'min(%d,ih)',format=yuv420p" % h
            if box:
                vf = "scale=%d:%d,format=yuv420p" % box
            if hw:
                cmd += ["-vf", hw[1]] + hw[2] + ["-force_key_frames", "expr:gte(t,n_forced*%g)" % SEG, "-g", "%d" % int(SEG * 30)]
            else:
                cmd += ["-vf", vf, "-c:v", "libx264", "-preset", config.X264_PRESET, "-profile:v", "high",
                        "-level:v", "4.1", "-crf", "21", "-maxrate", "%dk" % vk, "-bufsize", "%dk" % (vk * 2),
                        "-force_key_frames", "expr:gte(t,n_forced*%g)" % SEG, "-sc_threshold", "0",
                        "-g", "%d" % int(SEG * 30)]
        cmd += ["-c:a", "aac", "-ac", "2", "-b:a", "%dk" % ak, "-ar", "48000",
                "-max_muxing_queue_size", "2048",
                "-f", "hls", "-hls_time", "%g" % SEG, "-hls_list_size", "0"]
        if self.hevc:
            # frag_discont: tfdt carries the real time (with -output_ts_offset); without it every run starts at 0
            # and a seek lands at the wrong place in hls.js.  The init segments of all runs are then identical.
            cmd += ["-hls_segment_type", "fmp4", "-hls_fmp4_init_filename", "init%d.mp4" % start,
                    "-hls_segment_options", "movflags=+frag_discont"]
        else:
            # 1.5.4: -muxdelay/-muxpreload 0 -- the MPEG-TS muxer otherwise starts every run ~1.4 s late (seg88 began at
            # 529.4 instead of 528.0).  Now each segment starts on its playlist time (first DTS = t0 - one B-frame).
            cmd += ["-hls_segment_type", "mpegts", "-muxdelay", "0", "-muxpreload", "0"]
        cmd += ["-hls_flags", "temp_file+independent_segments", "-start_number", str(start),
                "-output_ts_offset", "%.3f" % t0,
                "-hls_segment_filename", str(self.dir / ("seg%d." + self.ext)), str(self.dir / "ffmpeg.m3u8")]
        return cmd

    def start(self, seg):
        self.stop()
        if getattr(self, "destroyed", False):
            return
        if self.profile == "remux":
            # a partly written segment from the killed run must not be served
            for f in self.dir.glob("seg*.ts"):
                if not self._ready(int(f.stem[3:])):
                    f.unlink(missing_ok=True)
            (self.dir / ("list%d.csv" % seg)).unlink(missing_ok=True)
        self.start_seg = seg
        self.started_at = time.time()
        cmd = self._cmd(seg)
        log.info("transcode %s start seg %d [%s/%s]: %s", self.sid, seg, self.encoder, self.stage, " ".join(cmd))
        errf = open(self.dir / "ffmpeg.log", "ab")
        self._planned_stop = False
        self.last_rc = None
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=errf, start_new_session=True)
        errf.close()
        self.paused = False

    def stop(self):
        p = self.proc
        self._planned_stop = True
        if p and p.poll() is None:
            try:
                if self.paused:
                    os.killpg(p.pid, signal.SIGCONT)
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        self.proc = None
        self.paused = False
        for f in self.dir.glob("*.tmp"):
            f.unlink(missing_ok=True)

    def _journal_ffmpeg(self, rc):
        """Copy the last lines of ffmpeg.log into the journal, then leave the file in place."""
        tail = self._log_tail(LOG_TAIL_N, joiner="\n")
        log.warning("transcode %s: ffmpeg exited rc=%s [%s/%s]\n%s",
                    self.sid, rc, self.encoder, self.stage, tail or "(ffmpeg.log empty)")

    def _reap(self, planned=False):
        """If ffmpeg has exited, journal its stderr on an unexpected non-zero exit. Returns rc or None if running/absent."""
        p = self.proc
        if p is None:
            return self.last_rc
        rc = p.poll()
        if rc is None:
            return None
        self.proc = None
        self.paused = False
        self.last_rc = rc
        if not planned and not self._planned_stop and rc != 0:
            self._journal_ffmpeg(rc)
        return rc

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def highest_done(self):
        """Highest contiguous finished segment of the current run.

        housekeep deletes segments older than last_req-40, so a walk from
        start_seg would stop immediately and return -1. That both disabled
        AHEAD_PAUSE (ffmpeg kept running far ahead) and could restart ffmpeg
        (live 4K test, 2026-11-25 ~8:50 AM MST).
        """
        nums = []
        for f in self.dir.glob("seg*." + self.ext):
            try:
                nums.append(int(f.stem[3:]))
            except ValueError:
                continue
        if not nums:
            return -1
        cand = [n for n in nums if n >= self.start_seg]
        if not cand:
            return -1
        n = min(cand)
        hi = -1
        while (self.dir / ("seg%d.%s" % (n, self.ext))).exists():
            hi = n
            n += 1
        return hi

    def seg_path(self, n):
        return self.dir / ("seg%d.%s" % (n, self.ext))

    def _ready(self, n):
        if self.profile != "remux" or self.hevc:
            # with hls temp_file the .ts/.m4s appears only once complete (HEVC remux uses the same muxer)
            return self.seg_path(n).exists()
        # segment muxer: a segment is complete once it is listed in the csv of the run that made it
        name = "seg%d.ts," % n
        if not self.seg_path(n).exists():
            return False
        for lf in self.dir.glob("list*.csv"):
            try:
                if any(line.startswith(name) for line in lf.read_text().splitlines()):
                    return True
            except OSError:
                pass
        return False

    def get_segment(self, n, timeout=60):
        self.last_access = time.time()
        self.last_req = n
        with self.lock:
            if self._ready(n):
                # A ready segment must not SIGCONT a paused ffmpeg: players re-request
                # already-buffered segments often enough to cancel AHEAD_PAUSE.
                return self.seg_path(n)
            hi = self.highest_done()
            if not self.running():
                # Do not relaunch the same failing GPU stage in a loop (that flipped the badge).
                self._handle_not_running(n)
            elif n < self.start_seg or (n - max(hi, self.start_seg)) * SEG > RESTART_AHEAD_S:
                self.start(n)
            self._resume_if_needed()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._ready(n):
                return self.seg_path(n)
            if self.failed or getattr(self, "destroyed", False):
                return None
            if not self.running():
                if self._ready(n):
                    return self.seg_path(n)
                with self.lock:
                    if not self.running() and not self._ready(n) and not self.failed and not getattr(self, "destroyed", False):
                        self._handle_not_running(n)
                deadline = max(deadline, time.time() + timeout)
                continue
            if (self.stage != "cpu" and self.profile != "remux" and time.time() - self.started_at > HW_STALL_S
                    and not self._ready(self.start_seg)):
                with self.lock:
                    if self.stage != "cpu" and not self._ready(self.start_seg) and time.time() - self.started_at > HW_STALL_S:
                        self._fallback(n, "no output after %ds" % HW_STALL_S)
                deadline = max(deadline, time.time() + timeout)
                continue
            time.sleep(0.1)
        return None

    def get_init(self, hint=0, timeout=60):
        """1.5.3 (HEVC, fMP4): the init segment.  Each ffmpeg run writes its own init<start>.mp4 (same encoder
        settings, so any of them fits every segment); serve one whose first segment is done, else start a run at
        the player's start segment and wait for it."""
        self.last_access = time.time()
        with self.lock:
            done = [f for f in self.dir.glob("init*.mp4") if f.stem[4:].isdigit() and self._ready(int(f.stem[4:]))]
            if done:
                return max(done, key=lambda f: f.stat().st_mtime)
            if not self.running() and not self.failed and not getattr(self, "destroyed", False):
                self._handle_not_running(max(0, min(hint, self.nseg - 1)))
            first = self.start_seg
        if not self.get_segment(first, timeout):
            return None
        f = self.dir / ("init%d.mp4" % first)
        return f if f.exists() else None

    def _resume_if_needed(self):
        if self.paused and self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGCONT)
            except Exception:
                pass
            self.paused = False

    def housekeep(self):
        """Throttle ffmpeg when far ahead; delete old segments."""
        if not self.running():
            return
        hi = self.highest_done()
        try:
            ahead_s = (hi - self.last_req) * SEG if hi >= 0 else 0
            if not self.paused and ahead_s > AHEAD_PAUSE_S:
                os.killpg(self.proc.pid, signal.SIGSTOP)
                self.paused = True
                log.info("transcode %s pause (ahead %.0fs, last_req %d)", self.sid, ahead_s, self.last_req)
            elif self.paused and ahead_s < AHEAD_RESUME_S:
                os.killpg(self.proc.pid, signal.SIGCONT)
                self.paused = False
                log.info("transcode %s resume (ahead %.0fs, last_req %d)", self.sid, ahead_s, self.last_req)
        except Exception:
            pass
        for f in self.dir.glob("seg*." + self.ext):
            try:
                n = int(f.stem[3:])
            except ValueError:
                continue
            if n < self.last_req - 40:
                f.unlink(missing_ok=True)

    def destroy(self, reason=""):
        self.destroyed = True      # 1.5.3: a request still waiting on this session must not restart ffmpeg
        log.info("transcode %s destroy (%s)", self.sid, reason or "unspecified")
        self.stop()
        # ffmpeg.log has already been copied into the journal on an unexpected exit; now the dir can go
        shutil.rmtree(self.dir, ignore_errors=True)


_sessions = {}
_slock = threading.Lock()
# Per-stream fallback, keyed by session id (item + quality + audio + user). Survives a
# destroy/recreate (seek, idle retry, playlist reload) so the stream does not hop back to
# a GPU stage that just failed. Expires so a later, quieter playback can try full GPU again.
STICKY_S = 1800
_sticky = {}
_sticky_lock = threading.Lock()


def remember_stage(sid, stage, reason, failed=""):
    with _sticky_lock:
        _sticky[sid] = {"stage": stage, "failed": failed, "reason": (reason or "")[:300], "at": time.time()}
    log.info("transcode %s: sticky stage %s after %s failed (%s)", sid, stage, failed or "?", (reason or "")[:200])


def apply_sticky(session):
    with _sticky_lock:
        st = _sticky.get(session.sid)
    if not st:
        return
    if time.time() - st["at"] > STICKY_S:
        with _sticky_lock:
            _sticky.pop(session.sid, None)
        return
    if st["stage"] in session.stages:
        session.stage_i = session.stages.index(st["stage"])
        if st.get("reason"):
            session.fallbacks.append({"stage": st.get("failed") or "full", "reason": st["reason"],
                                      "at": int(st["at"]), "sticky": True})
        log.info("transcode %s: staying on %s (%s)", session.sid, session.stage, st["reason"][:200])


def normalize_player(player_id):
    s = "".join(c for c in (player_id or "") if c.isalnum() or c in "-_")
    return s[:64]


def session_id(item_id, profile, audio_idx, user_id, player_id=""):
    return hashlib.sha1(("%s|%s|%s|%s|%s" % (item_id, profile, audio_idx, user_id, normalize_player(player_id))).encode()).hexdigest()[:16]


def max_transcodes():
    """Server-wide cap (hardware and software). Setting overrides MS_MAX_TRANSCODES (default 4)."""
    try:
        from . import settings
        raw = settings.get("max_transcodes")
        if raw not in (None, ""):
            n = int(raw)
            if 1 <= n <= 32:
                return n
    except (ValueError, TypeError, Exception):
        pass
    return config.MAX_TRANSCODES


def get_session(item, profile, audio_idx, user_id, player_id=""):
    pid = normalize_player(player_id)
    sid = session_id(item["id"], profile, audio_idx, user_id, pid)
    bounds = None
    if profile == "remux":
        bounds = remux_bounds(item)
        if not bounds:
            raise ValueError("not remuxable")
    with _slock:
        s = _sessions.get(sid)
        if s is None:
            # One transcode per player-session: the same login on two devices can stream at once.
            # Switching title or quality on one device replaces only that device's session.
            for k, other in list(_sessions.items()):
                if other.user_id == user_id and getattr(other, "player_id", "") == pid:
                    other.destroy("replaced")
                    _sessions.pop(k, None)
            cap = max_transcodes()
            if _sessions and len(_sessions) >= cap:
                oldest = min(_sessions.values(), key=lambda x: x.last_access)
                log.warning("transcode cap reached (%d of %d), evicting %s (%s, idle %ds)",
                            len(_sessions), cap, oldest.sid, oldest.item.get("title") or "?",
                            int(time.time() - oldest.last_access))
                oldest.destroy("cap")
                _sessions.pop(oldest.sid, None)
            s = Session(sid, item, profile, audio_idx, bounds)
            s.user_id = user_id
            s.player_id = pid
            apply_sticky(s)
            _sessions[sid] = s
        return s


def kickoff(session, start_seg=0):
    """1.7.9: start ffmpeg at start_seg (after copying any opening-clip cache) without waiting for output."""
    if session is None or session.failed or getattr(session, "destroyed", False):
        return
    start_seg = max(0, min(int(start_seg or 0), max(0, session.nseg - 1)))
    try:
        from . import preload
        preload.apply_to_session(session, start_seg)
    except Exception:
        log.exception("prefetch apply")
    if session.running() or session.failed or getattr(session, "destroyed", False):
        return
    first = start_seg
    while session._ready(first) and first < session.nseg - 1:
        first += 1
    if not session._ready(start_seg) or (first < session.nseg and not session._ready(first)):
        session.start(first)


def stop_session(sid, reason="client_close"):
    with _slock:
        s = _sessions.pop(sid, None)
    if s:
        s.destroy(reason)


def note_client(player_id, user, request=None, caps=""):
    """Log what this player advertised (once per playlist load)."""
    ua = ""
    if request is not None:
        ua = request.headers.get("user-agent") or ""
    uname = (user or {}).get("username") or (user or {}).get("id") or "?"
    log.info("transcode client player=%s user=%s caps=%s ua=%s",
             normalize_player(player_id) or "-", uname, caps or "-", ua[:400])


def playlist(item, query="", bounds=None, fmp4_init=None):
    dur = item.get("duration") or SEG
    if bounds:
        durs = [(bounds[i + 1] if i + 1 < len(bounds) else dur) - bounds[i] for i in range(len(bounds))]
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:%d" % math.ceil(max(durs) + 0.5),
                 "#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-INDEPENDENT-SEGMENTS"]
        for i, d in enumerate(durs):
            lines.append("#EXTINF:%.3f," % max(d, 0.001))
            lines.append("seg%d.ts%s" % (i, query))
        lines.append("#EXT-X-ENDLIST")
        return "\n".join(lines) + "\n"
    n = max(1, math.ceil(dur / SEG))
    lines = ["#EXTM3U", "#EXT-X-VERSION:%d" % (7 if fmp4_init else 3), "#EXT-X-TARGETDURATION:%d" % math.ceil(SEG),
             "#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-INDEPENDENT-SEGMENTS"]
    if fmp4_init:
        lines.append('#EXT-X-MAP:URI="%s"' % fmp4_init)
    for i in range(n):
        d = min(SEG, dur - i * SEG)
        if d <= 0.05:
            break
        lines.append("#EXTINF:%.3f," % d)
        lines.append("seg%d.%s%s" % (i, "m4s" if fmp4_init else "ts", query))
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def list_sessions():
    return [{"sid": s.sid, "item_id": s.item["id"], "title": s.item.get("title"), "profile": s.profile,
             "running": s.running(), "paused": s.paused, "start_seg": s.start_seg, "last_req": s.last_req,
             "idle_s": int(time.time() - s.last_access), "encoder": s.encoder, "stage": s.stage if s.profile != "remux" else "copy",
             "hw_device": s.hw[1] if s.encoder != "cpu" else None,
             "fallback": s.fallbacks[-1]["reason"] if s.fallbacks else None} for s in list(_sessions.values())]


def janitor_loop(stop_flag):
    # wipe leftovers from a previous run
    for d in config.TRANSCODE_DIR.glob("*"):
        shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink(missing_ok=True)
    while not stop_flag():
        now = time.time()
        with _slock:
            for sid, s in list(_sessions.items()):
                if now - s.last_access > IDLE_KILL_S:
                    s.destroy("idle")
                    _sessions.pop(sid, None)
                else:
                    s.housekeep()
        time.sleep(2)


def shutdown():
    with _slock:
        for s in _sessions.values():
            s.destroy("shutdown")
        _sessions.clear()


# ---------------------------------------------------------------------------
# remux support (v1.1)
# ---------------------------------------------------------------------------
REMUX_CONTAINERS = ("matroska", "mp4", "mov")   # demuxers with a keyframe index -> exact seeking


def remux_codec(item):
    """'h264' / 'hevc' if this file can be remuxed (video copied, no re-encode), else ''."""
    if item.get("media_type") != "video" or (item.get("duration") or 0) <= 1:
        return ""
    c = item.get("container") or ""
    if not any(x in c for x in REMUX_CONTAINERS):
        return ""
    v = (item.get("vcodec") or "").lower()
    if v == "h264" and (item.get("pix_fmt") or "yuv420p") in ("yuv420p", "yuvj420p"):
        return "h264"
    if v in ("hevc", "h265"):
        return "hevc"   # 10-bit is fine: we copy the bitstream into fMP4 (hls.js cannot play HEVC in MPEG-TS)
    return ""


def remux_eligible(item):
    """H.264 8-bit or HEVC (any bit depth) in a container we can seek precisely -> copy video instead of re-encoding."""
    return bool(remux_codec(item))


def probe_bounds(path, duration, start_time=0.0):
    """Segment start times at real keyframes, about every SEG seconds.

    Asks ffprobe to seek to 0, SEG, 2*SEG, ... and report the first video packet after each seek.
    1.7.9: seeks are issued in chunks with a short pause so a long film does not hammer the NAS;
    a non-keyframe at one seek is skipped so irregular GOPs can still get a partial plan.
    """
    import subprocess
    n = max(1, int(math.ceil((duration or 0) / SEG)))
    pts = []
    chunk = 40
    for off in range(0, n, chunk):
        intervals = ",".join("%.3f%%+#1" % ((off + i) * SEG) for i in range(min(chunk, n - off)))
        try:
            out = subprocess.run([config.FFPROBE, "-v", "error", "-select_streams", "v:0",
                                  "-read_intervals", intervals, "-show_entries", "packet=pts_time,flags",
                                  "-of", "csv=p=0", path],
                                 capture_output=True, timeout=60, check=False)
        except (subprocess.TimeoutExpired, OSError):
            break
        if out.returncode != 0:
            break
        for line in out.stdout.decode(errors="replace").splitlines():
            parts = line.strip().split(",")
            if len(parts) < 2 or parts[0] in ("", "N/A"):
                continue
            if not parts[1].startswith("K"):
                continue
            try:
                pts.append(float(parts[0]) - (start_time or 0.0))
            except ValueError:
                continue
        if off + chunk < n:
            time.sleep(0.25)
    if not pts:
        return None
    ks = sorted({round(max(0.0, p), 3) for p in pts})
    bounds = [0.0]
    for k in ks:
        if k - bounds[-1] >= 3.0 and k < (duration or 0) - 0.5:
            bounds.append(k)
    if len(bounds) < 2:
        return None
    return bounds


def remux_bounds(item, probe=False):
    """Cached per item (+mtime). Returns list or None.

    The play path must pass probe=False (the default): a missing or stale cache is a
    miss, not a 180s ffprobe on the NAS. The idle preload job fills the cache with probe=True.
    Failures are stored as status=retry, never as a permanent empty row.
    """
    row = db.row("SELECT mtime, data, status, checked_at, attempts FROM keyframes WHERE item_id=?", (item["id"],))
    if row and row["mtime"] == item.get("mtime"):
        if row.get("data") and row["data"] != "null":
            try:
                b = json.loads(row["data"])
                if isinstance(b, list) and len(b) >= 2:
                    return b
            except (TypeError, ValueError):
                pass
        if not probe:
            return None
        # retry backoff: 15 min, then 1 h, then 6 h
        delay = {0: 0, 1: 900, 2: 3600}.get(int(row.get("attempts") or 0), 21600)
        if row.get("checked_at") and time.time() - float(row["checked_at"] or 0) < delay:
            return None
    if not remux_eligible(item):
        return None
    if not probe:
        return None
    start_time = 0.0
    try:
        import subprocess
        o = subprocess.run([config.FFPROBE, "-v", "error", "-show_entries", "format=start_time", "-of", "csv=p=0",
                            item["path"]], capture_output=True, timeout=30)
        start_time = float(o.stdout.decode().strip() or 0)
    except (ValueError, OSError, Exception):
        start_time = 0.0
    bounds = probe_bounds(item["path"], item["duration"] or 0, start_time)
    now = int(time.time())
    attempts = int((row or {}).get("attempts") or 0) + 1
    if bounds:
        status = "ok" if len(bounds) >= max(2, int(((item.get("duration") or 0) / max(SEG, 1)) * 0.5)) else "partial"
        payload = json.dumps(bounds)
    else:
        status, payload = "retry", None
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO keyframes(item_id, mtime, data, status, checked_at, attempts) "
                  "VALUES(?,?,?,?,?,?)",
                  (item["id"], item.get("mtime"), payload, status, now, attempts if not bounds else 0))
    return bounds
