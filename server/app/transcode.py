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

SEG = 6.0
IDLE_KILL_S = 90          # no segment requests for this long -> kill + delete session
AHEAD_PAUSE = 25          # pause ffmpeg when it is this many segments ahead of the player
AHEAD_RESUME = 12
HW_STALL_S = 20          # 1.5.2: a GPU run that makes no segment in this long falls back

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
CPU_FALLBACK_BOX = (1920, 1080)   # a 2K/4K H.264 stream that loses the GPU carries on at 1080p on the CPU


def split_profile(profile):
    base, _, vc = (profile or "").partition(".")
    return base, vc


def valid_profile(profile):
    base, vc = split_profile(profile)
    return base in PROFILES and (vc == "" or (vc == "hevc" and base in HIRES))


def is_hires(profile):
    return split_profile(profile)[0] in HIRES


def fit_box(w, h, bw, bh):
    """Output size inside bw x bh keeping the aspect ratio, never larger than the source, even numbers."""
    if not w or not h:
        return None
    sc = min(1.0, bw / float(w), bh / float(h))
    return max(2, int(w * sc) // 2 * 2), max(2, int(h * sc) // 2 * 2)


def hires_ok(item, base):
    """Is the source at least this big (by width or height)?  A 3840x1600 film counts as 4K."""
    w, h = item.get("width") or 0, item.get("height") or 0
    bw, bh = HIRES[base]
    return w >= bw * 0.94 or h >= bh * 0.94


_hdr_cache = {}


def hdr_info(item):
    """'HDR10' / 'HLG' / '' for a video item (10-bit sources only; one ffprobe, cached per path + mtime)."""
    pf = item.get("pix_fmt") or ""
    if item.get("media_type") != "video" or "10" not in pf and "12" not in pf:
        return ""
    key = (item.get("path"), item.get("mtime"))
    if key in _hdr_cache:
        return _hdr_cache[key]
    v = ""
    try:
        o = subprocess.run([config.FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=color_transfer", "-of", "csv=p=0", item["path"]], capture_output=True, timeout=20)
        t = o.stdout.decode(errors="replace").strip().splitlines()
        t = t[0].strip().rstrip(",") if t else ""
        v = "HDR10" if t == "smpte2084" else "HLG" if t == "arib-std-b67" else ""
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
        self.hevc = self.vc == "hevc"
        self.ext = "m4s" if self.hevc else "ts"
        self.failed = None
        if profile not in ("remux", "audio") and item.get("vcodec") and item.get("media_type") == "video":
            self.hw = hwaccel.active()
        if self.base in HIRES and not self.hw[0]:
            raise ValueError("2K / 4K need hardware transcoding")
        self.rot = 0
        self.stages = ["full", "enc", "cpu"] if self.hw[0] else ["cpu"]
        if self.hw[0]:
            self.rot = hwaccel.rotation(item.get("path"))
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
    def _remux_cmd(self, start):
        """Copy the H.264 video, convert only the audio if needed; cut exactly at the probed keyframes."""
        it = self.item
        b = self.bounds
        cmd = [config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error"]
        seek = 0.0
        if start > 0:
            # ffmpeg seeks a little before -ss for formats with B-frames; +0.2 s lands exactly on keyframe b[start]
            seek = b[start] + 0.2
            cmd += ["-ss", "%.3f" % seek]
        cmd += ["-i", it["path"], "-map", "0:v:0", "-map", "0:a:%d?" % self.audio_idx, "-sn", "-dn", "-c:v", "copy"]
        auds = json.loads(it.get("audio_streams") or "[]")
        a = auds[self.audio_idx] if self.audio_idx < len(auds) else (auds[0] if auds else {})
        if a.get("codec") in ("aac", "mp3") and (a.get("channels") or 2) <= 2:
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", "aac", "-ac", "2", "-b:a", "192k", "-ar", "48000"]
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
        log.warning("transcode %s: %s stage %s failed (%s) -> %s", self.sid, method, old, reason[:200],
                    "CPU" if self.stage == "cpu" else "CPU decode + %s encode" % method)
        self.start(seg)

    def _log_tail(self):
        try:
            lines = [l for l in (self.dir / "ffmpeg.log").read_text(errors="replace").splitlines() if l.strip()]
            return " | ".join(lines[-3:]) or "ffmpeg exited"
        except OSError:
            return "ffmpeg exited"

    def _cmd(self, start):
        if self.profile == "remux":
            return self._remux_cmd(start)
        it = self.item
        maxh, vk, ak = PROFILES.get(self.base, PROFILES["720p"])
        audio_only = self.profile == "audio" or not it.get("vcodec")
        box = None          # 1.5.3: 2K / 4K -- explicit output size fitted into the box
        if self.base in HIRES and not audio_only:
            if self.hevc:
                vk = HEVC_KBPS[self.base]
            src_kbps = int((it.get("bitrate") or 0) / 1000)
            if src_kbps > 0:
                vk = min(vk, max(6000, int(src_kbps * 1.2)))
            sw, sh = it.get("width") or 0, it.get("height") or 0
            if self.rot in (90, 270):
                sw, sh = sh, sw
            bw, bh = HIRES[self.base] if self.stage != "cpu" else CPU_FALLBACK_BOX
            if self.stage == "cpu":
                vk = min(vk, PROFILES["1080p"][1])
            box = fit_box(sw, sh, bw, bh)
        t0 = start * SEG
        cmd = [config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error"]
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
                                    width=box[0] if box else None, codec="hevc" if self.hevc else "h264")
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
            if src_h and src_h < maxh:
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
            cmd += ["-hls_segment_type", "mpegts"]
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
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=errf, start_new_session=True)
        errf.close()
        self.paused = False

    def stop(self):
        p = self.proc
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

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def highest_done(self):
        hi = -1
        n = self.start_seg
        while (self.dir / ("seg%d.%s" % (n, self.ext))).exists():
            hi = n
            n += 1
        return hi

    def seg_path(self, n):
        return self.dir / ("seg%d.%s" % (n, self.ext))

    def _ready(self, n):
        if self.profile != "remux":
            # with hls temp_file the .ts appears only once complete
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
                self._resume_if_needed()
                return self.seg_path(n)
            hi = self.highest_done()
            if not self.running() or n < self.start_seg or n > max(hi, self.start_seg) + 4:
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
                if self.stage != "cpu" and self.profile != "remux" and not self._ready(self.start_seg):
                    # 1.5.2: the GPU run died without making a single segment -> next stage, same segment
                    with self.lock:
                        if not self.running() and not self._ready(n) and self.stage != "cpu":
                            self._fallback(n, self._log_tail())
                    deadline = max(deadline, time.time() + timeout)
                    continue
                # ffmpeg ended without producing it
                return None
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
            if not self.running() and not self.failed:
                self.start(max(0, min(hint, self.nseg - 1)))
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
            if not self.paused and hi - self.last_req > AHEAD_PAUSE:
                os.killpg(self.proc.pid, signal.SIGSTOP)
                self.paused = True
            elif self.paused and hi - self.last_req < AHEAD_RESUME:
                os.killpg(self.proc.pid, signal.SIGCONT)
                self.paused = False
        except Exception:
            pass
        for f in self.dir.glob("seg*." + self.ext):
            try:
                n = int(f.stem[3:])
            except ValueError:
                continue
            if n < self.last_req - 40:
                f.unlink(missing_ok=True)

    def destroy(self):
        self.destroyed = True      # 1.5.3: a request still waiting on this session must not restart ffmpeg
        self.stop()
        shutil.rmtree(self.dir, ignore_errors=True)


_sessions = {}
_slock = threading.Lock()


def session_id(item_id, profile, audio_idx, user_id):
    return hashlib.sha1(("%s|%s|%s|%s" % (item_id, profile, audio_idx, user_id)).encode()).hexdigest()[:16]


def get_session(item, profile, audio_idx, user_id):
    sid = session_id(item["id"], profile, audio_idx, user_id)
    bounds = None
    if profile == "remux":
        bounds = remux_bounds(item)
        if not bounds:
            raise ValueError("not remuxable")
    with _slock:
        s = _sessions.get(sid)
        if s is None:
            # one transcode per user: switching item/quality/audio track replaces the old session
            for k, other in list(_sessions.items()):
                if other.user_id == user_id:
                    other.destroy()
                    _sessions.pop(k, None)
            if _sessions and len(_sessions) >= config.MAX_TRANSCODES:
                oldest = min(_sessions.values(), key=lambda x: x.last_access)
                oldest.destroy()
                _sessions.pop(oldest.sid, None)
            s = Session(sid, item, profile, audio_idx, bounds)
            s.user_id = user_id
            _sessions[sid] = s
        return s


def stop_session(sid):
    with _slock:
        s = _sessions.pop(sid, None)
    if s:
        s.destroy()


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
                    log.info("transcode %s idle, removing", sid)
                    s.destroy()
                    _sessions.pop(sid, None)
                else:
                    s.housekeep()
        time.sleep(2)


def shutdown():
    with _slock:
        for s in _sessions.values():
            s.destroy()
        _sessions.clear()


# ---------------------------------------------------------------------------
# remux support (v1.1)
# ---------------------------------------------------------------------------
REMUX_CONTAINERS = ("matroska", "mp4", "mov")   # demuxers with a keyframe index -> exact seeking


def remux_eligible(item):
    """H.264 8-bit video in a container we can seek precisely -> copy video instead of re-encoding."""
    c = item.get("container") or ""
    return (item.get("media_type") == "video" and item.get("vcodec") == "h264"
            and (item.get("pix_fmt") or "yuv420p") in ("yuv420p", "yuvj420p")
            and any(x in c for x in REMUX_CONTAINERS) and (item.get("duration") or 0) > 1)


def probe_bounds(path, duration, start_time=0.0):
    """Segment start times at real keyframes, about every SEG seconds.

    Asks ffprobe to seek to 0, 6, 12, ... and report the first video packet after each seek: with an
    indexed container that is the keyframe at or before the target, which is exactly where ffmpeg will
    land when we later start a run there. Returns None if the container does not seek to keyframes.
    """
    import subprocess
    n = max(1, int(math.ceil(duration / SEG)))
    intervals = ",".join("%.3f%%+#1" % (i * SEG) for i in range(n))
    try:
        out = subprocess.run([config.FFPROBE, "-v", "error", "-select_streams", "v:0", "-read_intervals", intervals,
                              "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", path],
                             capture_output=True, timeout=180, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    pts = []
    for line in out.stdout.decode(errors="replace").splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2 or parts[0] in ("", "N/A"):
            continue
        if not parts[1].startswith("K"):
            return None          # landed on a non-keyframe: container can't be cut precisely
        try:
            pts.append(float(parts[0]) - (start_time or 0.0))
        except ValueError:
            return None
    if not pts:
        return None
    ks = sorted({round(max(0.0, p), 3) for p in pts})
    bounds = [0.0]
    for k in ks:
        if k - bounds[-1] >= 3.0 and k < duration - 0.5:
            bounds.append(k)
    return bounds


def remux_bounds(item):
    """Cached per item (+mtime). Returns list or None."""
    row = db.row("SELECT mtime, data FROM keyframes WHERE item_id=?", (item["id"],))
    if row and row["mtime"] == item.get("mtime"):
        return json.loads(row["data"]) if row["data"] else None
    if not remux_eligible(item):
        return None
    start_time = 0.0
    try:
        import subprocess
        o = subprocess.run([config.FFPROBE, "-v", "error", "-show_entries", "format=start_time", "-of", "csv=p=0",
                            item["path"]], capture_output=True, timeout=30)
        start_time = float(o.stdout.decode().strip() or 0)
    except (ValueError, OSError, Exception):
        start_time = 0.0
    bounds = probe_bounds(item["path"], item["duration"], start_time)
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO keyframes(item_id, mtime, data) VALUES(?,?,?)",
                  (item["id"], item.get("mtime"), json.dumps(bounds) if bounds else None))
    return bounds
