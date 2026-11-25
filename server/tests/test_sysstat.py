"""1.4.2: server status -- /proc parsing, caching, admin-only default and the "all users" toggle.

    python3 tests/test_sysstat.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
TMP = tempfile.mkdtemp(prefix="ms-sys-test-")
FAKE = tempfile.mkdtemp(prefix="ms-proc-")
os.environ.update({"MS_DATA_DIR": TMP, "MS_PROC_DIR": FAKE})


def w(path, text):
    p = Path(FAKE) / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def stat(busy):   # 2 cores; 'busy' jiffies of user time, idle grows 100 - busy per core per tick
    w("stat", "cpu  %d 0 0 %d 0 0 0 0 0 0\ncpu0 %d 0 0 %d 0 0 0 0 0 0\ncpu1 %d 0 0 %d 0 0 0 0 0 0\nintr 1\n"
      % (busy[0] + busy[1], 200 * TICK[0] - busy[0] - busy[1], busy[0], 100 * TICK[0] - busy[0], busy[1], 100 * TICK[0] - busy[1]))


TICK = [1]
stat((0, 0))
w("meminfo", "MemTotal:       32000000 kB\nMemFree:         1000000 kB\nMemAvailable:   24000000 kB\n"
  "SwapTotal:       2000000 kB\nSwapFree:        1500000 kB\n")
w("loadavg", "1.50 0.75 0.25 2/300 1234\n")
w("uptime", "93784.12 100.0\n")
w("self/status", "Name:\tpython3\nVmRSS:\t  204800 kB\n")
w("4321/comm", "ffmpeg\n"); w("4321/status", "VmRSS:\t  102400 kB\n")
w("4322/comm", "bash\n"); w("4322/status", "VmRSS:\t  1000 kB\n")

from fastapi import HTTPException  # noqa: E402
from app import db, server, settings, sysstat  # noqa: E402

db.migrate()
n_ok = 0


def check(cond, msg):
    global n_ok
    if not cond:
        print("FAIL -", msg); sys.exit(1)
    n_ok += 1; print("ok -", msg)


# first sample measures over a short window: make the second read show core0 50% busy, core1 100%
orig = sysstat._cpu_times
calls = [0]
def fake_times():
    calls[0] += 1
    if calls[0] >= 2:
        TICK[0] = 2; stat((50, 100))
    return orig()
sysstat._cpu_times = fake_times
s = sysstat.status()
sysstat._cpu_times = orig
check(s["cores"] == [50.0, 100.0], "per-core CPU from /proc/stat deltas (%s)" % s["cores"])
check(s["cpu"] == 75.0 and s["ncpu"] == 2, "overall CPU %s%% of %s cores" % (s["cpu"], s["ncpu"]))
check(s["mem"]["total"] == 32000000 * 1024 and s["mem"]["used"] == 8000000 * 1024, "memory used = total - available")
check(s["swap"] == {"total": 2000000 * 1024, "used": 500000 * 1024}, "swap")
check(s["load"] == [1.5, 0.75, 0.25] and s["uptime_s"] == 93784, "load average + uptime")
check(s["app_rss"] == 204800 * 1024, "app process RAM")
check(s["ffmpeg"] == {"count": 1, "rss": 102400 * 1024}, "ffmpeg processes counted (bash ignored)")
check(s["disks"] and s["disks"][0]["name"].startswith("Data") and s["disks"][0]["free"] > 0, "data disk free")
check(len(s["history"]) >= 1 and s["history"][-1][1] == 75.0, "history for the sparkline")

# cache: a burst of requests reuses the same snapshot
t = time.time()
same = all(sysstat.status()["at"] == s["at"] for _ in range(200))
check(same and time.time() - t < 0.5, "200 requests served from the cache (%.0f ms)" % ((time.time() - t) * 1000))
time.sleep(sysstat.SAMPLE_S + 0.6)
check(sysstat.status()["at"] > s["at"], "sampler thread refreshes every %ss while someone looks" % sysstat.SAMPLE_S)

# access: admin-only by default; toggle opens it to everyone
admin = {"id": 1, "username": "a", "is_admin": 1, "must_change_pw": 0}
user = {"id": 2, "username": "b", "is_admin": 0, "must_change_pw": 0}
check(server.me(admin)["show_status"] is True and server.me(user)["show_status"] is False, "/api/me: admin yes, user no (default)")
check("cpu" in server.system_status(admin), "admin can read /api/system/status")
try:
    server.system_status(user); check(False, "user blocked")
except HTTPException as e:
    check(e.status_code == 403, "normal user gets 403 by default")
check(server.get_settings(admin)["status_all_users"] is False, "setting defaults to off")
server.put_settings({"status_all_users": True}, admin)
check(settings.get("status_all_users") == "1" and server.me(user)["show_status"] is True, "toggle on: users see it")
check("mem" in server.system_status(user), "normal user can read status when allowed")
server.put_settings({"status_all_users": False}, admin)
try:
    server.system_status(user); check(False, "user blocked again")
except HTTPException as e:
    check(e.status_code == 403, "toggle off: blocked again")
check(settings.get("tmdb_enabled") == "1", "other settings untouched")
print("\n%d checks passed" % n_ok)
