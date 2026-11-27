"""2.3: Skip Intro / Skip Credits markers.

Idle, low-priority work. Yields the moment someone presses play.
Intros: embedded chapters when present, otherwise audio-fingerprint
matching across episodes of the same season (fpcalc/chromaprint if the
binary is on the PATH, otherwise an ffmpeg PCM fingerprint).
Credits: chapters, a shared ending fingerprint, or black/silence at the
end of the file.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import struct
import subprocess
import time
from pathlib import Path

from . import config, db

log = logging.getLogger("media-server")

INTRO_WINDOW_S = 300          # first 5 minutes
CREDITS_WINDOW_S = 480        # last 8 minutes
FRAME_S = 0.20
SR = 5512
MIN_INTRO_S = 12
MAX_INTRO_S = 180
MIN_CREDITS_S = 20
MAX_START_S = 150             # intro should begin in the first 2.5 minutes
BANDS = (80, 160, 320, 640, 1280, 2000, 2600)  # Hz edges after 0
MAX_HAM = 1
RETRY_S = 6 * 3600
MAX_ATTEMPTS = 6

INTRO_RE = re.compile(
    r"\b(intro|opening(?:\s+(?:credits?|sequence|titles?|theme))?|title\s+sequence|main\s+title|theme\s+song)\b",
    re.I,
)
CREDITS_RE = re.compile(
    r"\b((?:end(?:ing)?|closing|final)\s+credits?|credits?|outro|ending)\b",
    re.I,
)
RECAP_RE = re.compile(r"\b(previously|recap|last\s+time)\b", re.I)


def intro_dir():
    p = config.DATA_DIR / "intros"
    p.mkdir(parents=True, exist_ok=True)
    return p


def fp_path(item_id):
    return intro_dir() / ("%d.fp" % int(item_id))


def public_markers(item_id):
    """Safe fields for the player (None when unknown)."""
    row = db.row("SELECT intro_start, intro_end, credits_start, status, method "
                 "FROM intro_cache WHERE item_id=?", (item_id,))
    if not row or row.get("status") not in ("ready", "none"):
        return {"intro_start": None, "intro_end": None, "credits_start": None,
                "status": (row or {}).get("status") or "pending"}
    def _n(v):
        return None if v is None else float(v)
    return {"intro_start": _n(row.get("intro_start")),
            "intro_end": _n(row.get("intro_end")),
            "credits_start": _n(row.get("credits_start")),
            "status": row["status"],
            "method": row.get("method") or ""}


# ---------------------------------------------------------------------------
# Chapters
# ---------------------------------------------------------------------------
def parse_chapters(text):
    """Parse ffprobe -show_chapters ini-style output into {start,end,title}."""
    out, cur = [], {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line == "[CHAPTER]":
            if cur:
                out.append(cur)
            cur = {}
            continue
        if line.startswith("[/") or line.startswith("["):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            cur[k.strip().lower()] = v.strip()
    if cur:
        out.append(cur)
    chs = []
    for c in out:
        try:
            start = float(c.get("start_time") or 0)
            end = float(c.get("end_time") or start)
        except (TypeError, ValueError):
            continue
        title = c.get("tags/title") or c.get("title") or ""
        # ffprobe TAG:title= shows up as TAG:title in some versions; also TITLE
        if not title:
            for k, v in c.items():
                if k.endswith("title"):
                    title = v
                    break
        chs.append({"start": start, "end": end, "title": title})
    return chs


def markers_from_chapters(chs, duration=0):
    """Return intro/credits from chapter titles, or None fields."""
    intro_s = intro_e = cred = None
    recap = None
    for c in chs or []:
        t = c.get("title") or ""
        if RECAP_RE.search(t) and recap is None and c["start"] < MAX_START_S:
            recap = c
        if intro_s is None and INTRO_RE.search(t) and c["start"] < MAX_START_S + 30:
            intro_s, intro_e = c["start"], c["end"]
        if cred is None and CREDITS_RE.search(t):
            # ignore a false "Opening credits"
            if INTRO_RE.search(t) and not re.search(r"\b(end|closing|final|outro)\b", t, re.I):
                continue
            cred = c["start"]
    if recap is not None and intro_s is not None and recap["end"] <= intro_s + 2:
        intro_s = recap["start"]
    if intro_s is not None and intro_e is not None:
        if intro_e - intro_s < MIN_INTRO_S or intro_e - intro_s > MAX_INTRO_S:
            intro_s = intro_e = None
    if cred is not None and duration and cred < duration * 0.5:
        # credits chapter in the first half is suspicious unless titled clearly
        cred = cred if duration - cred >= MIN_CREDITS_S else None
    return intro_s, intro_e, cred


def probe_chapters(path, timeout=25):
    from . import preload
    cmd = [config.FFPROBE, "-v", "error", "-show_chapters", "-of", "default=noprint_wrappers=0", path]
    try:
        rc, out, err = preload.run_cmd(cmd, timeout, kind="intro")
    except subprocess.TimeoutExpired:
        return []
    if rc != 0:
        return []
    return parse_chapters((out or b"").decode("utf-8", "replace"))


# ---------------------------------------------------------------------------
# Fingerprints (fpcalc or ffmpeg PCM)
# ---------------------------------------------------------------------------
def fpcalc_bin():
    return shutil.which("fpcalc") or shutil.which("chromaprint")


def _goertzel_power(samples, sr, freq):
    """Power at `freq` for a list/tuple of ints (Goertzel)."""
    n = len(samples)
    if n < 8:
        return 0.0
    k = int(0.5 + (n * freq) / sr)
    w = 2 * math.pi * k / n
    cw, sw = math.cos(w), math.sin(w)
    coeff = 2 * cw
    s0 = s1 = s2 = 0.0
    for x in samples:
        s0 = x + coeff * s1 - s2
        s2, s1 = s1, s0
    return s1 * s1 + s2 * s2 - coeff * s1 * s2


def frame_hash(samples, sr=SR):
    """8-bit mask of bands above the median (plus a loudness bit)."""
    if not samples:
        return 0
    acc = 0
    for x in samples:
        acc += x * x
    rms = math.sqrt(acc / len(samples))
    powers = []
    edges = (0,) + BANDS
    for i, hi in enumerate(BANDS):
        lo = edges[i]
        mid = (lo + hi) / 2
        powers.append(_goertzel_power(samples, sr, mid))
    med = sorted(powers)[len(powers) // 2] if powers else 0
    bits = 0
    for i, p in enumerate(powers):
        if p > med:
            bits |= 1 << i
    if rms > 400:
        bits |= 1 << 7
    return bits


def pcm_to_hashes(pcm, sr=SR, frame_s=FRAME_S):
    n = int(sr * frame_s)
    if n < 8:
        return []
    out = []
    # pcm is little-endian signed 16-bit
    mv = memoryview(pcm)
    nframes = len(pcm) // (n * 2)
    for i in range(nframes):
        off = i * n * 2
        chunk = struct.unpack_from("<%dh" % n, mv, off)
        out.append(frame_hash(chunk, sr))
    return out


def extract_pcm(path, start, duration, timeout=180):
    """Return raw s16le mono PCM, or b'' on failure / yield."""
    from . import preload
    cmd = [config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error",
           "-ss", "%.3f" % max(0, start), "-t", "%.3f" % max(0.5, duration),
           "-i", path, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    try:
        rc, out, err = preload.run_cmd(cmd, timeout, kind="intro")
    except subprocess.TimeoutExpired:
        log.info("intro pcm timed out for %s", path)
        return b""
    if rc != 0:
        return b""
    return out or b""


def extract_fpcalc(path, start, duration, timeout=180):
    """Raw chromaprint integers, or None if fpcalc is missing/fails."""
    bin = fpcalc_bin()
    if not bin:
        return None
    from . import preload
    cmd = [bin, "-raw", "-length", str(int(duration)), path]
    # fpcalc has no -ss on all builds; use ffmpeg pipe when start > 0
    if start > 0.5:
        # Some fpcalc builds read a file only; skip and use PCM.
        return None
    try:
        rc, out, err = preload.run_cmd(cmd, timeout, kind="intro")
    except subprocess.TimeoutExpired:
        return None
    if rc != 0:
        return None
    text = (out or b"").decode("utf-8", "replace")
    raw = None
    for line in text.splitlines():
        if line.startswith("FINGERPRINT="):
            raw = line.split("=", 1)[1].strip()
            break
    if not raw:
        return None
    try:
        return [int(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        return None


def build_fingerprint(path, duration):
    """Return a dict ready to dump, or None."""
    dur = float(duration or 0)
    intro_len = min(INTRO_WINDOW_S, max(30, dur * 0.4 if dur else INTRO_WINDOW_S))
    cred_start = max(0, dur - min(CREDITS_WINDOW_S, max(40, dur * 0.35 if dur else CREDITS_WINDOW_S)))
    cred_len = max(0, dur - cred_start) if dur else 0

    kind = "pcm"
    intro = extract_fpcalc(path, 0, intro_len)
    credits = None
    if intro is not None:
        kind = "chromaprint"
        # fpcalc from 0 only; credits stay PCM
    else:
        pcm_i = extract_pcm(path, 0, intro_len)
        if not pcm_i:
            intro = []
        else:
            intro = pcm_to_hashes(pcm_i)

    pcm_c = extract_pcm(path, cred_start, cred_len) if cred_len >= 20 else b""
    credits = pcm_to_hashes(pcm_c) if pcm_c else []

    if not intro and not credits:
        return None
    return {"kind": kind, "sr": SR, "frame": FRAME_S,
            "intro": intro, "credits": credits,
            "credits_window_start": cred_start, "duration": dur}


def save_fp(item, data):
    data = dict(data)
    data["mtime"] = item.get("mtime")
    fp_path(item["id"]).write_text(json.dumps(data, separators=(",", ":")))


def load_fp(item):
    p = fp_path(item["id"])
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    if data.get("mtime") != item.get("mtime"):
        return None
    return data


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def hamming(a, b):
    return bin((int(a) ^ int(b)) & 0xFFFFFFFF).count("1")


def longest_match(a, b, max_ham=MAX_HAM, max_offset=None):
    """Longest run of similar frames. Returns (offset_b_minus_a, start_a, end_a) or None.

    offset: index in B minus index in A for the aligned run (B[i+off] ~ A[i]).
    start_a, end_a are exclusive-end indices into A.
    """
    if not a or not b:
        return None
    na, nb = len(a), len(b)
    if max_offset is None:
        max_offset = max(na, nb) - 1
    best = None
    for off in range(-max_offset, max_offset + 1):
        # A[i] aligns with B[i+off]
        i0 = max(0, -off)
        i1 = min(na, nb - off)
        if i1 - i0 <= 0:
            continue
        run_s = None
        for i in range(i0, i1):
            ok = hamming(a[i], b[i + off]) <= max_ham
            if ok:
                if run_s is None:
                    run_s = i
            else:
                if run_s is not None:
                    cand = (off, run_s, i)
                    if best is None or (cand[2] - cand[1]) > (best[2] - best[1]):
                        best = cand
                    run_s = None
        if run_s is not None:
            cand = (off, run_s, i1)
            if best is None or (cand[2] - cand[1]) > (best[2] - best[1]):
                best = cand
    return best


def match_seconds(a, b, frame_s=FRAME_S, min_s=MIN_INTRO_S, max_s=MAX_INTRO_S,
                  start_cap_s=MAX_START_S, max_offset_s=90):
    """Intro-style match: a run that starts early in both files."""
    if not a or not b:
        return None
    max_off = int(max_offset_s / frame_s)
    chroma = any(int(x) > 255 for x in list(a[:8]) + list(b[:8]))
    hit = longest_match(a, b, max_ham=8 if chroma else MAX_HAM, max_offset=max_off)
    if not hit:
        return None
    off, s, e = hit
    dur = (e - s) * frame_s
    if dur < min_s or dur > max_s:
        return None
    start_a = s * frame_s
    start_b = (s + off) * frame_s
    if start_a < 0 or start_b < 0:
        return None
    if start_a > start_cap_s or start_b > start_cap_s:
        return None
    return {"start_a": start_a, "end_a": start_a + dur,
            "start_b": start_b, "end_b": start_b + dur, "duration": dur}


def median(xs):
    xs = sorted(xs)
    if not xs:
        return 0
    n = len(xs)
    if n % 2:
        return xs[n // 2]
    return (xs[n // 2 - 1] + xs[n // 2]) / 2


def consensus_intro(pairs_by_id):
    """pairs_by_id: {item_id: [(start, end), ...]}. Median if at least 2 agree."""
    out = {}
    for iid, runs in (pairs_by_id or {}).items():
        if len(runs) < 1:
            continue
        starts = [r[0] for r in runs]
        ends = [r[1] for r in runs]
        s, e = median(starts), median(ends)
        close = [r for r in runs if abs(r[0] - s) <= 2.5 and abs(r[1] - e) <= 2.5]
        if len(close) >= 1 and e - s >= MIN_INTRO_S:
            # require 2 agreeing runs when we have them
            if len(runs) >= 2 and len(close) < 2:
                continue
            out[iid] = (max(0, s), e)
    return out


def credit_match_start(a, a_window_start, a_dur, b, b_window_start, b_dur,
                       frame_s=FRAME_S, min_s=MIN_CREDITS_S):
    """Map a common ending run to credits_start in A (seconds from file start)."""
    if not a or not b:
        return None
    hit = longest_match(a, b, max_offset=int(90 / frame_s))
    if not hit:
        return None
    off, s, e = hit
    dur = (e - s) * frame_s
    if dur < min_s:
        return None
    start_a = a_window_start + s * frame_s
    # credits should live in the second half
    if a_dur and start_a < a_dur * 0.5:
        return None
    return start_a


# ---------------------------------------------------------------------------
# Black / silence credits
# ---------------------------------------------------------------------------
def parse_black_silence(text, duration, window_start):
    """Return a credits_start guess from ffmpeg blackdetect + silencedetect logs."""
    blacks, silences = [], []
    b_open = None
    s_open = None
    for line in (text or "").splitlines():
        if "black_start:" in line:
            m = re.search(r"black_start:\s*([0-9.]+)", line)
            if m:
                b_open = float(m.group(1))
            m2 = re.search(r"black_end:\s*([0-9.]+)", line)
            m3 = re.search(r"black_duration:\s*([0-9.]+)", line)
            if m2 and b_open is not None:
                blacks.append((b_open, float(m2.group(1))))
                b_open = None
            elif m3 and b_open is not None:
                blacks.append((b_open, b_open + float(m3.group(1))))
                b_open = None
        elif "black_end:" in line:
            m = re.search(r"black_end:\s*([0-9.]+)", line)
            if m and b_open is not None:
                blacks.append((b_open, float(m.group(1))))
                b_open = None
        if "silence_start:" in line:
            m = re.search(r"silence_start:\s*([0-9.\-]+)", line)
            if m:
                s_open = float(m.group(1))
        elif "silence_end:" in line:
            m = re.search(r"silence_end:\s*([0-9.\-]+)", line)
            if m and s_open is not None:
                end = float(m.group(1))
                silences.append((s_open, end))
                s_open = None
    dur = float(duration or 0)
    if b_open is not None:
        blacks.append((b_open, dur or (b_open + 30)))
    if s_open is not None:
        silences.append((s_open, dur or (s_open + 30)))

    def _abs(t):
        # -ss before -i: ffmpeg timestamps in filters are often 0-based in the window
        if t < window_start - 1:
            return t + window_start
        return t

    blacks = [(_abs(s), _abs(e)) for s, e in blacks if _abs(e) - _abs(s) >= 1.5]
    silences = [(_abs(s), _abs(e)) for s, e in silences if _abs(e) - _abs(s) >= 1.5]
    if not dur:
        return None
    cutoff = dur * 0.55
    # Prefer a black (or silence) stretch that starts in the last 40% and
    # continues close to EOF, or leaves only a short tail.
    cands = []
    for s, e in blacks + silences:
        if s < cutoff:
            continue
        if e - s < MIN_CREDITS_S and (dur - s) < MIN_CREDITS_S:
            continue
        # starts a credit-like run: remaining time is mostly this event or short tail
        if dur - s >= MIN_CREDITS_S and (e >= dur - 8 or e - s >= MIN_CREDITS_S):
            cands.append(s)
    if not cands:
        return None
    start = min(cands)
    if dur - start < MIN_CREDITS_S:
        return None
    return start


def detect_credits_black(path, duration, timeout=120):
    from . import preload
    dur = float(duration or 0)
    if dur < 60:
        return None
    win = min(CREDITS_WINDOW_S, max(60, dur * 0.3))
    start = max(0, dur - win)
    cmd = [config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "info",
           "-ss", "%.3f" % start, "-t", "%.3f" % (win + 1), "-i", path,
           "-vf", "blackdetect=d=2:pic_th=0.95:pix_th=0.12",
           "-af", "silencedetect=noise=-35dB:d=2",
           "-f", "null", "-"]
    try:
        rc, out, err = preload.run_cmd(cmd, timeout, kind="intro")
    except subprocess.TimeoutExpired:
        return None
    text = ((err or b"") + (out or b"")).decode("utf-8", "replace")
    return parse_black_silence(text, dur, start)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def _write_row(item, intro_s, intro_e, cred, method, status="ready"):
    now = int(time.time())
    with db.tx() as c:
        c.execute(
            "INSERT INTO intro_cache(item_id, intro_start, intro_end, credits_start, "
            "method, status, checked_at, attempts, mtime) VALUES(?,?,?,?,?,?,?,0,?) "
            "ON CONFLICT(item_id) DO UPDATE SET intro_start=excluded.intro_start, "
            "intro_end=excluded.intro_end, credits_start=excluded.credits_start, "
            "method=excluded.method, status=excluded.status, checked_at=excluded.checked_at, "
            "mtime=excluded.mtime",
            (item["id"], intro_s, intro_e, cred, method, status, now, item.get("mtime")),
        )


def _touch_retry(item, inc=True):
    now = int(time.time())
    with db.tx() as c:
        row = c.execute("SELECT attempts FROM intro_cache WHERE item_id=?", (item["id"],)).fetchone()
        att = (row[0] if row else 0) + (1 if inc else 0)
        status = "retry" if att < MAX_ATTEMPTS else "none"
        c.execute(
            "INSERT INTO intro_cache(item_id, status, checked_at, attempts, mtime) VALUES(?,?,?,?,?) "
            "ON CONFLICT(item_id) DO UPDATE SET status=?, checked_at=?, attempts=?, mtime=?",
            (item["id"], status, now, att, item.get("mtime"),
             status, now, att, item.get("mtime")),
        )


def _stale(row, item):
    if not row:
        return True
    if row.get("mtime") is not None and item.get("mtime") is not None and row.get("mtime") != item.get("mtime"):
        return True
    return False


def _needs_work(row, item):
    if _stale(row, item):
        return True
    st = (row or {}).get("status")
    if st in (None, "", "pending"):
        return True
    if st == "retry":
        when = int((row or {}).get("checked_at") or 0)
        return time.time() - when >= RETRY_S
    return False


# ---------------------------------------------------------------------------
# Idle tick
# ---------------------------------------------------------------------------
def _busy():
    from . import preload
    return preload.busy()


def _season_episodes(library_id, show, season):
    return db.rows(
        "SELECT id, path, mtime, duration, kind, show, season, episode, library_id, title "
        "FROM items WHERE library_id=? AND show=? AND season=? AND kind='episode' "
        "AND media_type='video' AND path IS NOT NULL ORDER BY episode, id",
        (library_id, show, season),
    )


def _pick_season():
    """A season with 2+ episodes that still needs markers."""
    seasons = db.rows(
        "SELECT i.library_id, i.show, i.season, COUNT(*) AS n "
        "FROM items i WHERE i.kind='episode' AND i.media_type='video' "
        "AND i.show IS NOT NULL AND i.show!='' AND i.season IS NOT NULL "
        "GROUP BY i.library_id, i.show, i.season HAVING n>=2 "
        "ORDER BY n DESC LIMIT 80"
    )
    for s in seasons or []:
        eps = _season_episodes(s["library_id"], s["show"], s["season"])
        need = False
        for it in eps:
            row = db.row("SELECT status, mtime, checked_at, attempts FROM intro_cache WHERE item_id=?",
                         (it["id"],))
            if _needs_work(row, it):
                need = True
                break
        if need:
            return eps
    return None


def _pick_standalone():
    """A movie or a lone episode that still needs chapters / credits."""
    rows = db.rows(
        "SELECT i.id, i.path, i.mtime, i.duration, i.kind, i.show, i.season, i.episode, "
        "i.library_id, i.title, ic.status, ic.mtime AS c_mtime, ic.checked_at, ic.attempts "
        "FROM items i LEFT JOIN intro_cache ic ON ic.item_id=i.id "
        "WHERE i.media_type='video' AND i.kind IN ('movie','episode','video') "
        "AND (ic.status IS NULL OR ic.status='pending' OR ic.status='retry' "
        "     OR (ic.mtime IS NOT NULL AND i.mtime IS NOT NULL AND ic.mtime!=i.mtime)) "
        "ORDER BY CASE i.kind WHEN 'movie' THEN 0 ELSE 1 END, i.id LIMIT 40"
    )
    for r in rows or []:
        if _needs_work(r, r):
            return r
    return None


def _combine(ch_intro, ch_end, ch_cred, fp_intro, fp_end, fp_cred, blk_cred):
    method = []
    intro_s = intro_e = cred = None
    if ch_intro is not None and ch_end is not None:
        intro_s, intro_e = ch_intro, ch_end
        method.append("chapter")
    elif fp_intro is not None and fp_end is not None:
        intro_s, intro_e = fp_intro, fp_end
        method.append("fingerprint")
    if ch_cred is not None:
        cred = ch_cred
        if "chapter" not in method:
            method.append("chapter")
    elif fp_cred is not None:
        cred = fp_cred
        if "fingerprint" not in method:
            method.append("fingerprint")
    elif blk_cred is not None:
        cred = blk_cred
        method.append("blackdetect")
    # Prefer the earlier of fingerprint/black when both exist and are close
    if fp_cred is not None and blk_cred is not None and ch_cred is None:
        if abs(fp_cred - blk_cred) <= 20:
            cred = min(fp_cred, blk_cred)
            method = [m for m in method if m != "blackdetect"] + (["blackdetect"] if "blackdetect" not in method else [])
            if "fingerprint" not in method:
                method.append("fingerprint")
    return intro_s, intro_e, cred, "+".join(method) if method else "none"


def _ensure_fp(it):
    data = load_fp(it)
    if data:
        return data, False
    if _busy():
        return None, False
    data = build_fingerprint(it["path"], it.get("duration") or 0)
    if _busy():
        return None, True
    if not data:
        return None, True
    save_fp(it, data)
    return data, True


def _analyze_season(eps):
    """Extract one missing fingerprint, or write markers for the whole season."""
    if not eps or _busy():
        return False
    # chapters are cheap: gather them as we go
    did = False
    fps = {}
    for it in eps:
        if not it.get("path") or not os.path.exists(it["path"]):
            continue
        if _busy():
            return did
        data, worked = _ensure_fp(it)
        if worked:
            did = True
            # one extract per tick
            if data is None:
                return True
            # continue collecting what's already cached after this extract? stop after one extract
            return True
        if data:
            fps[it["id"]] = data

    # All fingerprints we could get are cached. Match.
    if _busy():
        return did
    intro_runs = {it["id"]: [] for it in eps}
    cred_guess = {}
    ids = [it["id"] for it in eps if it["id"] in fps]
    for i, a_id in enumerate(ids):
        for b_id in ids[i + 1:]:
            a, b = fps[a_id], fps[b_id]
            if (a.get("kind") == "chromaprint") != (b.get("kind") == "chromaprint"):
                # mix of kinds: skip intro compare (credits are always PCM)
                pass
            else:
                hit = match_seconds(a.get("intro") or [], b.get("intro") or [])
                if hit:
                    intro_runs[a_id].append((hit["start_a"], hit["end_a"]))
                    intro_runs[b_id].append((hit["start_b"], hit["end_b"]))
            ca = credit_match_start(
                a.get("credits") or [], a.get("credits_window_start") or 0, a.get("duration") or 0,
                b.get("credits") or [], b.get("credits_window_start") or 0, b.get("duration") or 0,
            )
            cb = credit_match_start(
                b.get("credits") or [], b.get("credits_window_start") or 0, b.get("duration") or 0,
                a.get("credits") or [], a.get("credits_window_start") or 0, a.get("duration") or 0,
            )
            if ca:
                cred_guess.setdefault(a_id, []).append(ca)
            if cb:
                cred_guess.setdefault(b_id, []).append(cb)
    intros = consensus_intro(intro_runs)

    for it in eps:
        if _busy():
            return True
        ch_s = ch_e = ch_c = None
        if it.get("path") and os.path.exists(it["path"]):
            try:
                ch_s, ch_e, ch_c = markers_from_chapters(probe_chapters(it["path"]), it.get("duration") or 0)
            except Exception:
                log.exception("intro chapters %s", it["id"])
        fp_s = fp_e = None
        if it["id"] in intros:
            fp_s, fp_e = intros[it["id"]]
        fp_c = median(cred_guess[it["id"]]) if cred_guess.get(it["id"]) else None
        blk = None
        if ch_c is None and fp_c is None and it.get("path") and os.path.exists(it["path"]):
            if _busy():
                return True
            try:
                blk = detect_credits_black(it["path"], it.get("duration") or 0)
            except Exception:
                log.exception("intro blackdetect %s", it["id"])
        intro_s, intro_e, cred, method = _combine(ch_s, ch_e, ch_c, fp_s, fp_e, fp_c, blk)
        status = "ready" if (intro_s is not None or cred is not None or method != "none") else "none"
        if method == "none":
            status = "none"
        try:
            _write_row(it, intro_s, intro_e, cred, method, status)
            log.info("intro markers item %s %s intro=%s-%s credits=%s",
                     it["id"], method, intro_s, intro_e, cred)
        except Exception:
            log.exception("intro write %s", it["id"])
            _touch_retry(it)
        did = True
    return did


def _analyze_one(it):
    if not it.get("path") or not os.path.exists(it["path"]):
        _write_row(it, None, None, None, "none", "none")
        return True
    if _busy():
        return False
    try:
        ch_s, ch_e, ch_c = markers_from_chapters(probe_chapters(it["path"]), it.get("duration") or 0)
    except Exception:
        log.exception("intro chapters %s", it["id"])
        ch_s = ch_e = ch_c = None
    if _busy():
        return False
    blk = None
    if ch_c is None:
        try:
            blk = detect_credits_black(it["path"], it.get("duration") or 0)
        except Exception:
            log.exception("intro blackdetect %s", it["id"])
    if _busy():
        return False
    intro_s, intro_e, cred, method = _combine(ch_s, ch_e, ch_c, None, None, None, blk)
    status = "ready" if (intro_s is not None or cred is not None) else "none"
    _write_row(it, intro_s, intro_e, cred, method if status == "ready" else "none", status)
    log.info("intro markers item %s %s intro=%s-%s credits=%s", it["id"], method, intro_s, intro_e, cred)
    return True


def _do_one():
    """One unit of idle work. Returns True if something ran."""
    if _busy():
        return False
    eps = _pick_season()
    if eps:
        try:
            return _analyze_season(eps)
        except Exception:
            log.exception("intro season")
            return False
    it = _pick_standalone()
    if not it:
        return False
    try:
        return _analyze_one(it)
    except Exception:
        log.exception("intro one %s", it.get("id"))
        _touch_retry(it)
        return False
