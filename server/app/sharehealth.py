"""1.6: is each network-share library still reachable?  Shown as a dot next to the library in the side menu.

Cheap and cached: a background loop checks every share library every CHECK_EVERY_S seconds (and on demand,
at most once per MIN_GAP_S).  A check never blocks the server: the share's mount is looked up in /proc/self/mounts,
then the library folder is listed in a separate daemon thread that gets LIST_TIMEOUT_S seconds -- a hung CIFS/NFS
mount just leaves that thread waiting (and no second one is started for the same library until it returns).

States: online (green), slow (amber: answered, but took > SLOW_MS), stuck (amber: no answer within the timeout),
offline (red: not mounted, folder missing or an error), checking (grey: not checked yet).
Nothing here remounts a share or changes its settings (the existing share watchdog is unchanged).
Local-folder libraries are not checked (no dot).
"""
import logging
import os
import threading
import time

from . import db, shares

log = logging.getLogger("media-server.sharehealth")
CHECK_EVERY_S = 45
LIST_TIMEOUT_S = 3.0
SLOW_MS = 1500
MIN_GAP_S = 5

_lock = threading.Lock()
_state = {}        # lib_id -> {"state", "reason", "checked_at", "ms"}
_probes = {}       # lib_id -> Thread still listing (a hung mount)
_last_all = 0.0


def _list_dir(path, box):
    try:
        with os.scandir(path) as it:
            for _ in it:
                break
        box["ok"] = True
    except FileNotFoundError:
        box["err"] = "folder not found on the share"
    except PermissionError:
        box["err"] = "no permission to read the folder"
    except OSError as e:
        box["err"] = e.strerror or str(e)


def check(lib):
    """Check one library row (dict with id, path, share_id).  Returns and caches its state."""
    lid = lib["id"]
    now = time.time()
    if not lib.get("share_id"):
        return None
    if not shares.is_mounted(lib["share_id"]):
        st = {"state": "offline", "reason": "share not mounted", "ms": None}
    else:
        with _lock:
            prev = _probes.get(lid)
        if prev is not None and prev.is_alive():
            st = {"state": "stuck", "reason": "the share is not answering (an earlier check is still waiting)", "ms": None}
        else:
            box = {}
            t = threading.Thread(target=_list_dir, args=(lib["path"], box), daemon=True, name="share-probe-%d" % lid)
            t0 = time.monotonic()
            t.start()
            t.join(LIST_TIMEOUT_S)
            ms = int((time.monotonic() - t0) * 1000)
            if t.is_alive():
                with _lock:
                    _probes[lid] = t
                st = {"state": "stuck", "reason": "the share did not answer within %g s" % LIST_TIMEOUT_S, "ms": None}
            elif box.get("ok"):
                with _lock:
                    _probes.pop(lid, None)
                st = {"state": "slow" if ms > SLOW_MS else "online", "reason": ("slow to answer (%d ms)" % ms) if ms > SLOW_MS else "", "ms": ms}
            else:
                with _lock:
                    _probes.pop(lid, None)
                st = {"state": "offline", "reason": box.get("err") or "unreachable", "ms": ms}
    st["checked_at"] = now
    with _lock:
        old = _state.get(lid)
        _state[lid] = st
    if old and old["state"] != st["state"]:
        log.info("library %d share: %s -> %s %s", lid, old["state"], st["state"], st["reason"])
    return st


def check_all(force=False):
    """Check every share library, in parallel.  Rate-limited unless force."""
    global _last_all
    with _lock:
        if not force and time.time() - _last_all < MIN_GAP_S:
            return False
        _last_all = time.time()
    libs = [dict(r) for r in db.rows("SELECT id, path, share_id FROM libraries WHERE share_id IS NOT NULL")]
    ts = [threading.Thread(target=check, args=(l,), daemon=True) for l in libs]
    for t in ts:
        t.start()
    for t in ts:
        t.join(LIST_TIMEOUT_S + 2)
    with _lock:
        for lid in [k for k in _state if k not in {l["id"] for l in libs}]:
            _state.pop(lid, None)
    return True


def get(lib):
    """What the API shows for a library: None for local folders; age_s = seconds since the check."""
    if not lib.get("share_id"):
        return None
    with _lock:
        st = dict(_state.get(lib["id"]) or {"state": "checking", "reason": "", "ms": None, "checked_at": None})
    st["age_s"] = int(time.time() - st["checked_at"]) if st.get("checked_at") else None
    st.pop("checked_at", None)
    return st


def loop(stop):
    time.sleep(3)
    while not stop():
        try:
            check_all(force=True)
        except Exception:
            log.exception("share health check")
        for _ in range(CHECK_EVERY_S):
            if stop():
                return
            time.sleep(1)
