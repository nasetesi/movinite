"""1.4.2: server status for the top bar -- CPU, memory, swap, disks, uptime, streams. Reads /proc only.

A small sampler thread runs only while someone is looking (stops 60 s after the last request), samples every
3 s and keeps a short history for the sparkline. Every client gets the same cached snapshot.
"""
import os
import shutil
import threading
import time
from collections import deque

from . import config, db

SAMPLE_S = 2.0
IDLE_STOP_S = 60
HISTORY = 40
_lock = threading.Lock()
_state = {"snap": None, "last_req": 0.0, "thread": None, "prev": None}
_hist = deque(maxlen=HISTORY)
PROC = os.environ.get("MS_PROC_DIR", "/proc")


def _read(path):
    with open(os.path.join(PROC, path)) as f:
        return f.read()


def _cpu_times():
    """-> [(total, idle)] for 'cpu' then each core."""
    out = []
    try:
        text = _read("stat")
    except OSError:          # no /proc (e.g. a bare chroot): report what we can
        return out
    for line in text.splitlines():
        if not line.startswith("cpu"):
            break
        v = [int(x) for x in line.split()[1:]]
        idle = v[3] + (v[4] if len(v) > 4 else 0)            # idle + iowait
        total = sum(v[:8])                                    # without guest (already in user)
        out.append((total, idle))
    return out


def _pct(a, b):
    dt, di = b[0] - a[0], b[1] - a[1]
    return round(max(0.0, min(100.0, 100.0 * (dt - di) / dt)), 1) if dt > 0 else 0.0


def _meminfo():
    m = {}
    try:
        text = _read("meminfo")
    except OSError:
        return m
    for line in text.splitlines():
        k, _, rest = line.partition(":")
        try:
            m[k] = int(rest.split()[0]) * 1024
        except (ValueError, IndexError):
            pass
    return m


def _rss(pid):
    try:
        for line in _read("%s/status" % pid).splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


def _ffmpeg():
    n, rss = 0, 0
    try:
        pids = [p for p in os.listdir(PROC) if p.isdigit()]
    except OSError:
        return 0, 0
    for p in pids:
        try:
            if _read("%s/comm" % p).strip() == "ffmpeg":
                n += 1
                rss += _rss(p)
        except OSError:
            continue
    return n, rss


def _disk(path):
    try:
        du = shutil.disk_usage(path)
        return {"total": du.total, "used": du.total - du.free, "free": du.free}
    except OSError:
        return None


def _sample():
    t0 = _cpu_times()
    prev = _state["prev"]
    if t0 and (not prev or time.time() - prev[0] > 30):     # first look: measure over a short window
        time.sleep(0.25)
        prev = (time.time() - 0.25, t0)
        t0 = _cpu_times()
    if t0 and prev and prev[1]:
        cpu = _pct(prev[1][0], t0[0])
        cores = [_pct(a, b) for a, b in zip(prev[1][1:], t0[1:])]
    else:
        cpu, cores = None, []
    _state["prev"] = (time.time(), t0)
    m = _meminfo()
    total = m.get("MemTotal", 0)
    avail = m.get("MemAvailable", m.get("MemFree", 0))
    try:
        la = [float(x) for x in _read("loadavg").split()[:3]]
    except (OSError, ValueError):
        la = [0, 0, 0]
    try:
        up = float(_read("uptime").split()[0])
    except (OSError, ValueError):
        up = 0
    ff_n, ff_rss = _ffmpeg()
    disks = [dict(name="Data (%s)" % config.DATA_DIR, **(_disk(str(config.DATA_DIR)) or {}))]
    try:
        from . import shares
        for s in db.rows("SELECT id, name FROM shares ORDER BY id"):
            mp = shares.mount_point(s["id"])
            if os.path.ismount(mp):
                d = _disk(mp)
                if d:
                    disks.append(dict(name="Share %s" % s["name"], **d))
    except Exception:
        pass
    try:
        from . import transcode
        running = [t for t in transcode.list_sessions() if t.get("running")]
        streams = len(running)
        gpu = [t for t in running if t.get("encoder") not in (None, "cpu")]   # 1.5.2
    except Exception:
        streams, gpu = 0, []
    try:
        from . import hwaccel
        hw = {"streams": len(gpu), "method": gpu[0]["encoder"] if gpu else None,
              "label": hwaccel.LABEL.get(gpu[0]["encoder"], "") if gpu else "",
              "name": hwaccel.card_name(gpu[0]["hw_device"]) if gpu else "", "mode": hwaccel.mode()}
    except Exception:
        hw = {"streams": 0, "method": None, "label": "", "name": "", "mode": "off"}
    snap = {"at": time.time(), "cpu": cpu, "cores": cores, "ncpu": len(cores) or os.cpu_count() or 1,
            "load": la, "mem": {"total": total, "used": total - avail, "available": avail},
            "swap": {"total": m.get("SwapTotal", 0), "used": m.get("SwapTotal", 0) - m.get("SwapFree", 0)},
            "disks": [d for d in disks if d.get("total")], "uptime_s": int(up),
            "app_rss": _rss("self"), "ffmpeg": {"count": ff_n, "rss": ff_rss}, "streams": streams, "hw": hw}
    _hist.append([round(snap["at"]), cpu or 0, round(100.0 * snap["mem"]["used"] / total, 1) if total else 0])
    return snap


def _loop():
    while time.time() - _state["last_req"] < IDLE_STOP_S:
        try:
            snap = _sample()
            with _lock:
                _state["snap"] = snap
        except Exception:
            pass
        time.sleep(SAMPLE_S)
    with _lock:
        _state["thread"] = None


def status():
    """Cached snapshot (at most ~2 s old) plus the recent history."""
    now = time.time()
    with _lock:
        _state["last_req"] = now
        snap = _state["snap"]
        start = _state["thread"] is None
        if start:
            _state["thread"] = threading.Thread(target=_loop, name="sysstat", daemon=True)
    if snap is None or now - snap["at"] > SAMPLE_S * 2:
        snap = _sample()            # first request (or the sampler just stopped): answer right away
        with _lock:
            _state["snap"] = snap
    if start:
        _state["thread"].start()
    out = dict(snap)
    out["history"] = list(_hist)
    out["sample_s"] = SAMPLE_S
    return out
