"""1.9: user activity (Settings > Activity).

Events are queued in memory and written in batches every ~2 s by one thread, so sign-in and playback never wait
on the database.  "Now playing" is an in-memory registry fed by the request guard (HLS playlist/segments, direct
file reads, progress heartbeats); a sweep turns an idle entry into a play_stop event.

Retention (Settings > Activity): events 90 days by default, failed sign-ins 30 days, IP addresses blanked after
30 days.  Never stored: passwords, tokens, cookies, setting values.
"""
import csv
import io
import json
import logging
import threading
import time

from . import db, settings

log = logging.getLogger("media-server")

KINDS = {
    "signin": ("login", "login_failed", "logout", "password_changed", "session_revoked", "signed_out_everywhere"),
    "playback": ("play_start", "play_stop"),
    "accounts": ("invite_created", "invite_sent", "invite_send_failed", "invite_accepted", "invite_revoked",
                 "user_created", "user_deleted", "role_changed", "libraries_changed", "user_disabled", "user_enabled",
                 "password_reset", "gmail_connected", "gmail_disconnected", "gmail_error", "email_error", "email_test"),
    "downloads": ("device_registered", "device_revoked", "download_requested", "download_ready", "download_started",
                  "download_complete", "download_deleted", "download_revoked", "download_failed"),
    "server": ("library_added", "library_removed", "scan_started", "settings_changed", "server_started"),
}
KIND_GROUP = {k: g for g, ks in KINDS.items() for k in ks}
RETENTION_CHOICES = (30, 90, 180, 365, 0)    # 0 = keep forever
IDLE_STOP_S = 90                              # no request for this long = playback stopped

_q = []
_qlock = threading.Lock()
_now_playing = {}
_nplock = threading.Lock()
_stop = False


def retention_days():
    try:
        v = int(settings.get("activity_retention_days", "90"))
    except (TypeError, ValueError):
        v = 90
    return v if v in RETENTION_CHOICES else 90


def record(kind, user=None, item=None, ip=None, device=None, detail=None, actor=None, user_id=None):
    """Queue one event. user: a dict with id/username; item: a dict with id/library_id/title (any may be None)."""
    try:
        uid = user_id if user_id is not None else ((user or {}).get("id"))
        name = actor or (user or {}).get("username")
        ev = (int(time.time()), uid, name, kind,
              (item or {}).get("id"), (item or {}).get("library_id"), _title(item),
              ip, device, json.dumps(detail, separators=(",", ":")) if detail else None)
        with _qlock:
            _q.append(ev)
            if len(_q) > 20000:          # never grow without bound if the writer is stuck
                del _q[:5000]
    except Exception:
        log.exception("activity record")


def _title(item):
    if not item:
        return None
    t = item.get("title") or ""
    if item.get("show"):
        se = ""
        if item.get("season") is not None:
            se += "S%02d" % item["season"]
        if item.get("episode") is not None:
            se += "E%02d" % item["episode"]
        t = "%s %s%s" % (item["show"], se, (" · " + item["episode_title"]) if item.get("episode_title") else "")
    elif item.get("artist") and item.get("media_type") == "audio":
        t = "%s — %s" % (item["artist"], t)
    return t[:300] or None


def flush():
    with _qlock:
        batch = list(_q)
        _q.clear()
    if not batch:
        return 0
    try:
        with db.tx() as c:
            c.executemany("INSERT INTO activity(ts,user_id,actor,kind,item_id,library_id,title,ip,device,detail) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?)", batch)
    except Exception:
        log.exception("activity flush")
        with _qlock:
            _q[:0] = batch[-5000:]
        return 0
    return len(batch)


def prune(now=None):
    now = int(now or time.time())
    days = retention_days()
    with db.tx() as c:
        if days:
            c.execute("DELETE FROM activity WHERE ts < ?", (now - days * 86400,))
        c.execute("DELETE FROM activity WHERE kind='login_failed' AND ts < ?", (now - 30 * 86400,))
        c.execute("UPDATE activity SET ip=NULL WHERE ip IS NOT NULL AND ts < ?", (now - 30 * 86400,))
        c.execute("DELETE FROM gmail_sends WHERE ts < ?", (now - 2 * 86400,))


# ---------------------------------------------------------------- now playing
def touch(user, item, mode, profile=None, player="", ip=None, device=None, position=None):
    """Called on every streaming request (cheap: an in-memory dict update)."""
    if not user or not item:
        return
    key = (user["id"], item["id"], (player or "")[:64])
    now = time.time()
    start_ev = False
    with _nplock:
        e = _now_playing.get(key)
        if e is None:
            # the same user + item on another player id within a few seconds (e.g. a playlist reload) is one play
            e = {"user_id": user["id"], "username": user.get("username"), "item": _item_brief(item),
                 "player": key[2], "started": now, "last": now, "mode": mode, "profile": profile,
                 "ip": ip, "device": device, "position": position, "requests": 0}
            _now_playing[key] = e
            start_ev = True
        e["last"] = now
        e["requests"] += 1
        if mode and mode != "progress":
            e["mode"] = mode
        if profile:
            e["profile"] = profile
        if position is not None:
            e["position"] = position
        if ip:
            e["ip"] = ip
    if start_ev:
        record("play_start", user=user, item=item, ip=ip, device=device,
               detail={k: v for k, v in (("mode", mode if mode != "progress" else None), ("quality", profile)) if v})


def _item_brief(it):
    return {k: it.get(k) for k in ("id", "library_id", "title", "show", "season", "episode", "episode_title",
                                   "artist", "media_type", "kind", "duration", "poster", "thumb", "year")}


def sweep(now=None):
    now = now or time.time()
    ended = []
    with _nplock:
        for k, e in list(_now_playing.items()):
            if now - e["last"] > IDLE_STOP_S:
                ended.append(_now_playing.pop(k))
    for e in ended:
        watched = int(max(0, e["last"] - e["started"]))
        record("play_stop", user={"id": e["user_id"], "username": e["username"]}, item=e["item"], ip=e.get("ip"),
               device=e.get("device"), detail={"watched_s": watched, "position": int(e["position"] or 0) if e.get("position") else None,
                                               "mode": e.get("mode"), "quality": e.get("profile")})
    return len(ended)


def end_player(user_id, item_id, player=""):
    """The player said it closed: end now rather than after the idle timeout."""
    with _nplock:
        for k, e in list(_now_playing.items()):
            if k[0] == user_id and k[1] == item_id and (not player or k[2] == player):
                e["last"] = time.time() - IDLE_STOP_S - 1
    sweep()


def now_playing():
    from . import transcode
    try:
        sess = list(getattr(transcode, "_sessions", {}).values())
    except Exception:
        sess = []
    out = []
    now = time.time()
    with _nplock:
        items = list(_now_playing.values())
    for e in items:
        enc = None
        for s in sess:
            try:
                if s.item["id"] == e["item"]["id"] and getattr(s, "user_id", None) == e["user_id"]:
                    enc = {"encoder": s.encoder, "stage": s.stage if s.profile != "remux" else "copy",
                           "profile": s.profile, "paused": s.paused,
                           "fallback": s.fallbacks[-1]["reason"] if s.fallbacks else None}
                    break
            except Exception:
                continue
        it = e["item"]
        dur = it.get("duration") or 0
        out.append({"user_id": e["user_id"], "username": e["username"], "item": it, "player": e["player"],
                    "started": int(e["started"]), "idle_s": int(now - e["last"]), "mode": e["mode"],
                    "profile": (enc or {}).get("profile") or e.get("profile"), "transcode": enc,
                    "ip": e.get("ip"), "device": e.get("device"),
                    "position": e.get("position"), "progress": (e["position"] / dur) if (dur and e.get("position")) else None})
    out.sort(key=lambda x: -x["started"])
    return out


def loop(stop_flag):
    last_prune = 0
    record("server_started")
    while not stop_flag():
        time.sleep(2)
        try:
            sweep()
            flush()
            if time.time() - last_prune > 6 * 3600:
                prune()
                last_prune = time.time()
        except Exception:
            log.exception("activity loop")
    try:
        sweep(time.time() + IDLE_STOP_S + 1)
        flush()
    except Exception:
        pass


# ---------------------------------------------------------------- queries
def query(user_id=None, group=None, kinds=None, q=None, since=None, until=None, before_id=None, limit=100):
    flush()
    cond, args = ["1"], []
    if user_id:
        cond.append("user_id=?")
        args.append(int(user_id))
    ks = list(kinds or [])
    if group and group in KINDS:
        ks += list(KINDS[group])
    if ks:
        cond.append("kind IN (%s)" % ",".join("?" * len(ks)))
        args += ks
    if q:
        cond.append("(title LIKE ? OR actor LIKE ? OR ip LIKE ? OR device LIKE ? OR detail LIKE ?)")
        like = "%" + q.replace("%", "").replace("_", "") + "%"
        args += [like] * 5
    if since:
        cond.append("ts>=?")
        args.append(int(since))
    if until:
        cond.append("ts<?")
        args.append(int(until))
    if before_id:
        cond.append("id<?")
        args.append(int(before_id))
    limit = max(1, min(int(limit or 100), 1000))
    rows = db.rows("SELECT * FROM activity WHERE " + " AND ".join(cond) + " ORDER BY id DESC LIMIT ?", args + [limit])
    for r in rows:
        try:
            r["detail"] = json.loads(r["detail"]) if r.get("detail") else None
        except ValueError:
            r["detail"] = None
        r["group"] = KIND_GROUP.get(r["kind"], "other")
    return rows


def summary(days=30):
    flush()
    since = int(time.time()) - days * 86400
    users = db.rows("SELECT id, username, role FROM users ORDER BY username")
    out = []
    for u in users:
        plays = db.row("SELECT COUNT(*) n FROM activity WHERE user_id=? AND kind='play_start' AND ts>=?", (u["id"], since))["n"]
        secs = 0
        for r in db.rows("SELECT detail FROM activity WHERE user_id=? AND kind='play_stop' AND ts>=?", (u["id"], since)):
            try:
                secs += int((json.loads(r["detail"] or "{}") or {}).get("watched_s") or 0)
            except ValueError:
                pass
        last = db.row("SELECT MAX(ts) t FROM activity WHERE user_id=?", (u["id"],))["t"]
        seen = db.row("SELECT MAX(last_seen) t FROM sessions WHERE user_id=?", (u["id"],))["t"]
        out.append({"id": u["id"], "username": u["username"], "role": u["role"], "plays": plays,
                    "hours": round(secs / 3600, 1), "last_active": max(last or 0, seen or 0) or None})
    return out


def to_csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time_utc", "user", "event", "title", "ip", "device", "details"])
    for r in rows:
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r["ts"])), _csv_safe(r.get("actor")), r["kind"],
                    _csv_safe(r.get("title")), _csv_safe(r.get("ip")), _csv_safe(r.get("device")),
                    _csv_safe(json.dumps(r["detail"]) if r.get("detail") else "")])
    return buf.getvalue()


def _csv_safe(v):
    v = "" if v is None else str(v)
    return ("'" + v) if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v
