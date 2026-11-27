"""FastAPI app: JSON API + static single-page UI."""
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import artwork, auth, browse, folderart, liborder, playlists, preload, sharehealth, titles, config, db, homerows, hwaccel, scanner, settings, shares, sysstat, tmdb, transcode, trickplay
from . import gmail, mailer, guard, invites, keys, netutil, offline, useractivity, pair, discover, fed
from .version import __version__

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("media-server")

STATIC = Path(__file__).parent / "static"
mimetypes.add_type("application/manifest+json", ".webmanifest")
app = FastAPI(title="Movinite", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(guard.Guard)    # 1.9: per-library access + Activity > Now playing
app.include_router(offline.router)  # 2.0: devices, offline grants, sync, Settings > Downloads
_stop = False


@app.on_event("startup")
def _startup():
    db.migrate()
    if keys.available():
        keys.ensure()                              # 1.9: this server's identity key (data/secrets, 0600)
    else:
        log.warning("Python package 'cryptography' is missing: Connect Gmail is unavailable until update.sh installs it")
    threading.Thread(target=useractivity.loop, args=(lambda: _stop,), daemon=True, name="activity").start()   # 1.9
    threading.Thread(target=transcode.janitor_loop, args=(lambda: _stop,), daemon=True, name="janitor").start()
    threading.Thread(target=scanner.scheduler_loop, daemon=True, name="scan-scheduler").start()
    # re-mount shares that dropped (e.g. NAS was down at boot)
    threading.Thread(target=_share_watchdog, daemon=True, name="share-watchdog").start()
    threading.Thread(target=sharehealth.loop, args=(lambda: _stop,), daemon=True, name="share-health").start()   # 1.6
    # 1.2.1: finish TMDB matching that was cut short (e.g. by the update restart) or never started
    threading.Thread(target=tmdb.resume_loop, args=(lambda: _stop,), daemon=True, name="tmdb-resume").start()
    # 1.5.2: video card scan (first start without a setting: scan, test, save; Auto: pick the card)
    threading.Thread(target=hwaccel.warm_up, daemon=True, name="hw-detect").start()
    folderart.start_backfill(lambda: _stop)    # 1.7.3
    preload.start_loop(lambda: _stop)          # 1.7.9: subtitle / remux / opening-clip caches
    threading.Thread(target=offline.loop, args=(lambda: _stop,), daemon=True, name="offline-jobs").start()   # 2.0
    threading.Thread(target=lambda: discover.start(lambda: _stop), daemon=True, name="mdns").start()          # 2.0.2
    threading.Thread(target=lambda: fed.sync_loop(lambda: _stop), daemon=True, name="fed-sync").start()      # 2.1
    log.info("Movinite (media-server) v%s started; data in %s", __version__, config.DATA_DIR)


@app.on_event("shutdown")
def _shutdown():
    global _stop
    _stop = True
    scanner._stop = True
    offline.stop()
    discover.stop()
    transcode.shutdown()


def _share_watchdog():
    time.sleep(20)
    while not _stop:
        try:
            for s in db.rows("SELECT id FROM shares"):
                if not shares.is_mounted(s["id"]):
                    ok, msg = shares.remount(s["id"])
                    with db.tx() as c:
                        c.execute("UPDATE shares SET last_status=?, last_error=? WHERE id=?",
                                  ("mounted" if ok else "error", None if ok else msg, s["id"]))
        except Exception:
            log.exception("share watchdog")
        for _ in range(60):
            if _stop:
                return
            time.sleep(5)


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/.well-known/movinite.json")
def movinite_discover(request: Request):
    """LAN / recent-server probe: confirms this is a Movinite server (no auth)."""
    return discover.info_payload(request)


@app.get("/api/setup-status")
def setup_status():
    n = db.row("SELECT COUNT(*) AS n FROM users")["n"]
    return {"needs_setup": n == 0, "version": __version__}


@app.post("/api/setup")
def setup(request: Request, response: Response, body: dict = Body(...)):
    """First-run: create the admin when the database has no users at all."""
    if db.row("SELECT COUNT(*) AS n FROM users")["n"] > 0:
        raise HTTPException(409, "Already set up")
    username, password = (body.get("username") or "").strip(), body.get("password") or ""
    _check_new_user(username, password)
    uid = auth.create_user(username, password, is_admin=True)
    _set_cookie(request, response, _new_session(request, uid))
    useractivity.record("user_created", user={"id": uid, "username": username}, ip=netutil.client_ip(request), detail={"role": "admin", "first_run": True})
    return {"ok": True}


def _check_new_user(username, password):
    if not re.match(r"^[A-Za-z0-9._@-]{2,40}$", username or ""):
        raise HTTPException(400, "Username: 2-40 letters, digits, . _ @ -")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")


def _new_session(request, uid):
    return auth.new_session(uid, netutil.client_ip(request), request.headers.get("user-agent"))


def _base_url(request):
    """Links in invites and the Gmail redirect use Settings > Email > Public address when set (never the Host
    header of an anonymous request).  Without it, the address the signed-in admin is using right now."""
    pu = (settings.get("public_url", "") or "").strip().rstrip("/")
    if pu:
        return pu
    peer = request.client.host if request.client else None
    proto = request.url.scheme
    if peer and netutil._is_trusted(peer, netutil.trusted_nets()):
        proto = (request.headers.get("x-forwarded-proto") or proto).split(",")[0].strip()
    host = request.headers.get("host") or request.url.netloc
    return "%s://%s" % (proto, host)


def _set_cookie(request, response, tok):
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(auth.COOKIE, tok, httponly=True, samesite="lax", secure=secure,
                        max_age=config.SESSION_DAYS * 86400, path="/")


@app.post("/api/login")
def login(request: Request, response: Response, body: dict = Body(...)):
    ip = netutil.client_ip(request)      # 1.9: the real client behind a trusted proxy (was the proxy's address)
    ua = request.headers.get("user-agent")
    if not auth.login_allowed(ip):
        raise HTTPException(429, "Too many failed sign-ins; wait 5 minutes")
    tried = (body.get("username") or "").strip()
    u = db.row("SELECT * FROM users WHERE username=?", (tried,))
    if not u and "@" in tried:
        u = db.row("SELECT * FROM users WHERE email=?", (tried,))     # 1.9: invited people may sign in with their email
    if not u or not auth.check_pw(body.get("password") or "", u["pw_hash"]):
        auth.login_failed(ip)
        useractivity.record("login_failed", user_id=u["id"] if u else None, actor=tried[:64] or "?", ip=ip,
                            device=auth._device_name(ua))
        raise HTTPException(401, "Wrong username or password")
    if u.get("disabled_at"):
        useractivity.record("login_failed", user=u, ip=ip, device=auth._device_name(ua), detail={"reason": "disabled"})
        raise HTTPException(403, "This account is turned off. Ask the server admin.")
    _set_cookie(request, response, auth.new_session(u["id"], ip, ua))
    useractivity.record("login", user=u, ip=ip, device=auth._device_name(ua))
    return {"ok": True, "must_change_pw": bool(u["must_change_pw"])}


@app.post("/api/pair/start")
def pair_start(request: Request, body: dict = Body(default={})):
    """TV: start a 6-character sign-in code (and QR URL) that a signed-in phone can approve."""
    return pair.start(request, _base_url(request), force=bool((body or {}).get("force")))


def _pair_poll_result(request, response, token):
    r = pair.poll(request, token or "")
    tok = r.pop("token", None)
    if tok:
        _set_cookie(request, response, tok)
    return r


@app.get("/api/pair/poll")
def pair_poll_get(request: Request, response: Response, token: str = ""):
    return _pair_poll_result(request, response, token)


@app.post("/api/pair/poll")
def pair_poll_post(request: Request, response: Response, body: dict = Body(default={})):
    return _pair_poll_result(request, response, (body or {}).get("token") or request.query_params.get("token") or "")


@app.get("/api/pair/info")
def pair_info(request: Request, code: str = "", u=Depends(auth.require_user)):
    return pair.info(request, code, u)


@app.post("/api/pair/approve")
def pair_approve(request: Request, body: dict = Body(...), u=Depends(auth.require_user)):
    return pair.approve(request, (body or {}).get("code") or "", u)


@app.post("/api/pair/deny")
def pair_deny(request: Request, body: dict = Body(...), u=Depends(auth.require_user)):
    return pair.deny(request, (body or {}).get("code") or "", u)


@app.post("/api/logout")
def logout(request: Request, response: Response):
    tok = request.cookies.get(auth.COOKIE)
    if tok:
        u = auth.user_from_token(tok)
        if u:
            useractivity.record("logout", user=u, ip=netutil.client_ip(request), device=auth._device_name(request.headers.get("user-agent")))
        auth.end_session(tok)
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(u=Depends(auth.require_user)):
    role = auth.norm_role(u.get("role"), u.get("is_admin"))
    return {"id": u["id"], "username": u["username"], "is_admin": bool(u["is_admin"]), "role": role,
            "role_label": auth.ROLE_LABEL.get(role), "email": u.get("email"),
            "all_libraries": u.get("libs") is None, "session_id": u.get("sid"),
            "must_change_pw": bool(u["must_change_pw"]), "version": __version__, "show_status": _status_visible(u),
            "can_download": offline.can_download(u) and offline.cfg("offline_enabled"),
            "auto_skip_intro": bool(u.get("auto_skip_intro")),
            "auto_skip_credits": bool(u.get("auto_skip_credits"))}


def _status_visible(u):
    """1.4.2: the top-bar server status is admin-only unless Settings > System shows it to everyone."""
    return bool(u["is_admin"]) or settings.get("status_all_users", "0") == "1"


@app.get("/api/system/status")
def system_status(u=Depends(auth.require_user)):
    if not _status_visible(u):
        raise HTTPException(403, "Server status is only shown to admins")
    return sysstat.status()


@app.post("/api/me/password")
def change_my_password(request: Request, response: Response, body: dict = Body(...), u=Depends(auth.require_user)):
    full = db.row("SELECT * FROM users WHERE id=?", (u["id"],))
    if not auth.check_pw(body.get("current_password") or "", full["pw_hash"]):
        raise HTTPException(400, "Current password is wrong")
    new = body.get("new_password") or ""
    if len(new) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    auth.set_password(u["id"], new)
    _set_cookie(request, response, _new_session(request, u["id"]))
    useractivity.record("password_changed", user=u, ip=netutil.client_ip(request))
    return {"ok": True}


@app.put("/api/me/prefs")
def set_my_prefs(body: dict = Body(...), u=Depends(auth.require_user)):
    """2.3: per-user auto-skip for intro and credits."""
    fields = {}
    for k in ("auto_skip_intro", "auto_skip_credits"):
        if k in body:
            v = body[k]
            fields[k] = 1 if v in (True, 1, "1", "true", "on", "yes") else 0
    if fields:
        with db.tx() as c:
            sets = ", ".join("%s=?" % k for k in fields)
            c.execute("UPDATE users SET %s WHERE id=?" % sets, list(fields.values()) + [u["id"]])
        auth.invalidate_cache()
    full = db.row("SELECT auto_skip_intro, auto_skip_credits FROM users WHERE id=?", (u["id"],)) or {}
    return {"auto_skip_intro": bool(full.get("auto_skip_intro")),
            "auto_skip_credits": bool(full.get("auto_skip_credits"))}


# ---------------------------------------------------------------------------
# users (admin)
# ---------------------------------------------------------------------------
@app.get("/api/users")
def list_users(u=Depends(auth.require_admin)):
    """1.9: role, email, libraries, last active, signed-in devices, Gmail state."""
    names = {r["id"]: r["name"] for r in db.rows("SELECT id, name FROM libraries")}
    libmap = {}
    for r in db.rows("SELECT user_id, library_id FROM user_libraries"):
        libmap.setdefault(r["user_id"], []).append(r["library_id"])
    now = int(time.time())
    out = []
    for x in db.rows("SELECT id, username, is_admin, role, email, all_libraries, disabled_at, invited_by, created_at FROM users ORDER BY username"):
        role = auth.norm_role(x.get("role"), x.get("is_admin"))
        libs = None if (role == "admin" or x.get("all_libraries")) else sorted(libmap.get(x["id"], []))
        sess = db.row("SELECT COUNT(*) n, MAX(last_seen) seen FROM sessions WHERE user_id=? AND expires_at>?", (x["id"], now))
        g = db.row("SELECT email, status FROM gmail_accounts WHERE user_id=?", (x["id"],))
        out.append({"id": x["id"], "username": x["username"], "is_admin": role == "admin", "role": role,
                    "role_label": auth.ROLE_LABEL[role], "email": x.get("email"), "libraries": libs,
                    "library_names": None if libs is None else [names.get(i, "?") for i in libs],
                    "disabled": bool(x.get("disabled_at")), "created_at": x["created_at"], "devices": sess["n"],
                    "last_seen": sess["seen"], "gmail": g})
    return out


def _parse_libs(body):
    if body.get("all_libraries", True) in (True, 1, "1", "true", None) and not body.get("libraries"):
        return None
    if body.get("all_libraries") in (True, 1, "1", "true"):
        return None
    ok = {r["id"] for r in db.rows("SELECT id FROM libraries")}
    libs = sorted({int(x) for x in (body.get("libraries") or []) if str(x).isdigit() and int(x) in ok})
    if not libs:
        raise HTTPException(400, "Pick at least one library, or choose All libraries")
    return libs


@app.post("/api/users")
def add_user(body: dict = Body(...), u=Depends(auth.require_admin)):
    username, password = (body.get("username") or "").strip(), body.get("password") or ""
    _check_new_user(username, password)
    if db.row("SELECT id FROM users WHERE username=?", (username,)):
        raise HTTPException(409, "That username exists")
    role = auth.norm_role(body.get("role"), bool(body.get("is_admin")))
    email = (body.get("email") or "").strip() or None
    if email and not invites.valid_email(email):
        raise HTTPException(400, "Enter a valid email address")
    if email and db.row("SELECT id FROM users WHERE email=?", (email,)):
        raise HTTPException(409, "Someone already has that email")
    libs = None if role == "admin" else _parse_libs(body)
    uid = auth.create_user(username, password, role=role, email=email, all_libraries=libs is None, libraries=libs,
                           invited_by=u["id"])
    useractivity.record("user_created", user=u, detail={"username": username, "role": role})
    return {"id": uid}


def _admins_left(excluding):
    return db.row("SELECT COUNT(*) n FROM users WHERE role='admin' AND disabled_at IS NULL AND id<>?", (excluding,))["n"]


@app.put("/api/users/{uid}")
def edit_user(uid: int, body: dict = Body(...), u=Depends(auth.require_admin)):
    """1.9: change role, libraries, email, or turn an account off / on."""
    t = db.row("SELECT * FROM users WHERE id=?", (uid,))
    if not t:
        raise HTTPException(404, "No such user")
    old_role = auth.norm_role(t.get("role"), t.get("is_admin"))
    role = auth.norm_role(body.get("role"), False) if body.get("role") else old_role
    if old_role == "admin" and role != "admin" and _admins_left(uid) < 1:
        raise HTTPException(400, "Keep at least one admin")
    if uid == u["id"] and role != "admin":
        raise HTTPException(400, "You can't remove your own admin role")
    with db.tx() as c:
        if role != old_role:
            c.execute("UPDATE users SET role=?, is_admin=? WHERE id=?", (role, 1 if role == "admin" else 0, uid))
        if "email" in body:
            email = (body.get("email") or "").strip() or None
            if email and not invites.valid_email(email):
                raise HTTPException(400, "Enter a valid email address")
            if email and c.execute("SELECT id FROM users WHERE email=? AND id<>?", (email, uid)).fetchone():
                raise HTTPException(409, "Someone else has that email")
            c.execute("UPDATE users SET email=? WHERE id=?", (email, uid))
        if role == "admin":
            c.execute("UPDATE users SET all_libraries=1 WHERE id=?", (uid,))
            c.execute("DELETE FROM user_libraries WHERE user_id=?", (uid,))
        elif "libraries" in body or "all_libraries" in body:
            libs = _parse_libs(body)
            c.execute("UPDATE users SET all_libraries=? WHERE id=?", (1 if libs is None else 0, uid))
            c.execute("DELETE FROM user_libraries WHERE user_id=?", (uid,))
            if libs:
                c.executemany("INSERT INTO user_libraries(user_id, library_id) VALUES(?,?)", [(uid, l) for l in libs])
        if "disabled" in body:
            if body.get("disabled"):
                if uid == u["id"]:
                    raise HTTPException(400, "You can't turn off your own account")
                if old_role == "admin" and _admins_left(uid) < 1:
                    raise HTTPException(400, "Keep at least one admin")
                c.execute("UPDATE users SET disabled_at=? WHERE id=?", (int(time.time()), uid))
                c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            else:
                c.execute("UPDATE users SET disabled_at=NULL WHERE id=?", (uid,))
    auth.invalidate_cache()
    if body.get("disabled"):
        offline.forget_user(uid, "account disabled")       # 2.0: its phones wipe their downloads on the next sync
    elif role != old_role and role == "view":
        offline.revoke_user_grants(uid, "role changed")     # 2.0: Viewer can't keep downloads
    if role != old_role:
        useractivity.record("role_changed", user=u, detail={"username": t["username"], "from": old_role, "to": role})
        if old_role == "admin":
            gmail.forget_user(uid)
    if "libraries" in body or "all_libraries" in body:
        useractivity.record("libraries_changed", user=u, detail={"username": t["username"]})
    if "disabled" in body:
        useractivity.record("user_disabled" if body.get("disabled") else "user_enabled", user=u, detail={"username": t["username"]})
    return {"ok": True}


@app.delete("/api/users/{uid}")
def delete_user(uid: int, u=Depends(auth.require_admin)):
    if uid == u["id"]:
        raise HTTPException(400, "You cannot delete yourself")
    target = db.row("SELECT * FROM users WHERE id=?", (uid,))
    if not target:
        raise HTTPException(404, "No such user")
    if auth.norm_role(target.get("role"), target.get("is_admin")) == "admin" and _admins_left(uid) < 1:
        raise HTTPException(400, "Cannot delete the last admin")
    gmail.forget_user(uid)
    offline.forget_user(uid, "account deleted")             # 2.0: tombstone devices so the phones wipe
    with db.tx() as c:
        c.execute("DELETE FROM users WHERE id=?", (uid,))
        c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        c.execute("DELETE FROM user_libraries WHERE user_id=?", (uid,))
    auth.invalidate_cache()
    useractivity.record("user_deleted", user=u, detail={"username": target["username"]})
    return {"ok": True}


@app.post("/api/users/{uid}/password")
def reset_user_password(uid: int, body: dict = Body(...), u=Depends(auth.require_admin)):
    pw = body.get("password") or ""
    if len(pw) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    t = db.row("SELECT id, username FROM users WHERE id=?", (uid,))
    if not t:
        raise HTTPException(404, "No such user")
    auth.set_password(uid, pw, must_change=uid != u["id"])
    useractivity.record("password_reset", user=u, detail={"username": t["username"]})
    return {"ok": True}


# ---- 1.9: signed-in devices
@app.get("/api/me/sessions")
def my_sessions(u=Depends(auth.require_user)):
    return auth.list_sessions(u["id"], u.get("sid"))


@app.delete("/api/me/sessions/{sid}")
def end_my_session(sid: str, request: Request, u=Depends(auth.require_user)):
    if not auth.end_session_by_id(u["id"], sid):
        raise HTTPException(404, "That device is already signed out")
    useractivity.record("session_revoked", user=u, ip=netutil.client_ip(request), detail={"device_id": sid, "self": sid == u.get("sid")})
    return {"ok": True, "was_current": sid == u.get("sid")}


@app.post("/api/me/sessions/others")
def end_my_other_sessions(request: Request, u=Depends(auth.require_user)):
    n = auth.end_all_sessions(u["id"], except_sid=u.get("sid"))
    useractivity.record("signed_out_everywhere", user=u, ip=netutil.client_ip(request), detail={"devices": n})
    return {"ok": True, "signed_out": n}


@app.get("/api/users/{uid}/sessions")
def user_sessions(uid: int, u=Depends(auth.require_admin)):
    return auth.list_sessions(uid, u.get("sid") if uid == u["id"] else None)


@app.delete("/api/users/{uid}/sessions/{sid}")
def end_user_session(uid: int, sid: str, u=Depends(auth.require_admin)):
    if not auth.end_session_by_id(uid, sid):
        raise HTTPException(404, "That device is already signed out")
    t = db.row("SELECT username FROM users WHERE id=?", (uid,))
    useractivity.record("session_revoked", user=u, detail={"username": t and t["username"], "device_id": sid})
    return {"ok": True}


@app.post("/api/users/{uid}/signout")
def signout_user(uid: int, u=Depends(auth.require_admin)):
    n = auth.end_all_sessions(uid, except_sid=u.get("sid") if uid == u["id"] else None)
    t = db.row("SELECT username FROM users WHERE id=?", (uid,))
    useractivity.record("signed_out_everywhere", user=u, detail={"username": t and t["username"], "devices": n})
    return {"ok": True, "signed_out": n}


# ---- 1.9: invites
def _inv_err(e):
    raise HTTPException(e.status, e.msg)


@app.get("/api/invites")
def list_invites(u=Depends(auth.require_admin)):
    return {"invites": invites.list_all(), "gmail": gmail.status_for(u["id"]), "mail": mailer.sender(u),
            "expiry_choices": invites.EXPIRY_CHOICES}


@app.post("/api/invites")
def create_invite(request: Request, body: dict = Body(...), u=Depends(auth.require_admin)):
    libs = None if body.get("all_libraries", True) in (True, 1, "1", "true") else (body.get("libraries") or [])
    try:
        iid, tok = invites.create(u, body.get("email"), body.get("role") or "view", libs, body.get("note") or "",
                                  int(body.get("days") or 7))
    except invites.InviteError as e:
        _inv_err(e)
    out = invites.deliver(u, iid, tok, _base_url(request)) if body.get("send", True) else \
        {"sent": False, "via": "link", "manual": True, "link": invites.link_for(_base_url(request), tok)}
    out["id"] = iid
    return out


@app.post("/api/invites/{iid}/resend")
def resend_invite(iid: int, request: Request, body: dict = Body(default={}), u=Depends(auth.require_admin)):
    try:
        tok = invites.renew(u, iid)
    except invites.InviteError as e:
        _inv_err(e)
    if body.get("send", True):
        out = invites.deliver(u, iid, tok, _base_url(request))
    else:
        out = {"sent": False, "via": "link", "manual": True, "link": invites.link_for(_base_url(request), tok)}
    out["id"] = iid
    return out


@app.delete("/api/invites/{iid}")
def revoke_invite(iid: int, u=Depends(auth.require_admin)):
    if not invites.revoke(u, iid):
        raise HTTPException(404, "That invite is no longer pending")
    return {"ok": True}


_inv_tries = {}


def _inv_rate(request):
    ip = netutil.client_ip(request)
    now = time.time()
    lst = [t for t in _inv_tries.get(ip, []) if now - t < 300]
    if len(lst) >= 30:
        raise HTTPException(429, "Too many tries; wait 5 minutes")
    lst.append(now)
    _inv_tries[ip] = lst
    if len(_inv_tries) > 5000:
        _inv_tries.clear()


@app.get("/api/invite/{token}")
def invite_preview(token: str, request: Request):
    _inv_rate(request)
    try:
        return invites.preview(token)
    except invites.InviteError as e:
        _inv_err(e)


@app.post("/api/invite/{token}/accept")
def invite_accept(token: str, request: Request, response: Response, body: dict = Body(...)):
    _inv_rate(request)
    try:
        uid = invites.accept(token, body.get("username"), body.get("password") or "")
    except invites.InviteError as e:
        _inv_err(e)
    _set_cookie(request, response, _new_session(request, uid))
    return {"ok": True}


# ---- 1.9: Connect Gmail (Settings > Email)
def _gmail_err(e):
    raise HTTPException(409 if e.reconnect else 400, e.message)


def _email_settings(request, u):
    base = _base_url(request)
    return {"public_url": settings.get("public_url", "") or "", "effective_base_url": base,
            "server_name": invites.server_name(),
            "client_id": gmail.client_id(), "client_secret_saved": gmail.has_secret() if keys.available() else False,
            "crypto": keys.available(), "redirect_uri": gmail.redirect_uri(base),
            "paste_redirect_uri": gmail.PASTE_REDIRECT,
            "redirect_ok": base.startswith("https://") or base.split("://", 1)[-1].startswith(("localhost", "127.0.0.1")),
            "scopes": gmail.SCOPES, "hourly_cap": gmail.caps()[0], "daily_cap": gmail.caps()[1],
            "me": gmail.status_for(u["id"]), "accounts": gmail.all_accounts(), "fingerprint": keys.fingerprint() if keys.available() else None,
            "mail_method": mailer.method(), "smtp": mailer.status(u), "sender": mailer.sender(u)}


@app.get("/api/settings/email")
def get_email_settings(request: Request, u=Depends(auth.require_admin)):
    return _email_settings(request, u)


@app.put("/api/settings/email")
def put_email_settings(request: Request, body: dict = Body(...), u=Depends(auth.require_admin)):
    changed = []
    if "public_url" in body:
        pu = (body.get("public_url") or "").strip().rstrip("/")
        if pu and not re.match(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?$", pu):
            raise HTTPException(400, "Public address looks like https://movies.example.com (no path)")
        settings.put("public_url", pu)
        changed.append("public_url")
    if "server_name" in body:
        settings.put("server_name", (body.get("server_name") or "").strip()[:60])
        changed.append("server_name")
    if "mail_method" in body:
        if body.get("mail_method") not in ("smtp", "gmail_oauth"):
            raise HTTPException(400, "Pick app password (SMTP) or Connect Gmail")
        settings.put("mail_method", body["mail_method"])
        changed.append("mail_method")
    if "hourly_cap" in body or "daily_cap" in body:
        for k, d in (("hourly_cap", gmail.HOURLY_CAP_DEFAULT), ("daily_cap", gmail.DAILY_CAP_DEFAULT)):
            if k in body:
                try:
                    v = max(1, min(int(body[k]), 2000))
                except (TypeError, ValueError):
                    raise HTTPException(400, "Limits are whole numbers")
                settings.put("gmail_" + k, str(v))
                changed.append("gmail_" + k)
    if "client_id" in body or body.get("client_secret"):
        if not keys.available():
            raise HTTPException(400, "This server is missing the Python 'cryptography' package; re-run update.sh")
        try:
            if gmail.set_client(body.get("client_id") if "client_id" in body else None, body.get("client_secret") or None):
                changed.append("gmail_client")
        except gmail.GmailError as e:
            _gmail_err(e)
    if changed:
        useractivity.record("settings_changed", user=u, detail={"keys": changed})   # names only
    return _email_settings(request, u)


# ---- 1.9: email over SMTP -- Gmail app password (default) or any SMTP server
def _mail_err(e):
    raise HTTPException(400, e.message)


@app.get("/api/mail/status")
def mail_status(u=Depends(auth.require_admin)):
    return mailer.sender(u)


@app.put("/api/settings/smtp")
def put_smtp(request: Request, body: dict = Body(...), u=Depends(auth.require_admin)):
    """Save the Gmail address + app password (or a generic SMTP server). The password is sealed in
    data/secrets/smtp.sealed and is never returned or logged."""
    try:
        changed = mailer.save(body)
    except mailer.MailError as e:
        _mail_err(e)
    if body.get("use", True) and mailer.method() != "smtp":
        settings.put("mail_method", "smtp")
        changed.append("mail_method")
    if changed:
        useractivity.record("settings_changed", user=u, detail={"keys": changed})   # names only, never values
    return _email_settings(request, u)


@app.delete("/api/settings/smtp")
def delete_smtp(request: Request, u=Depends(auth.require_admin)):
    mailer.forget()
    useractivity.record("settings_changed", user=u, detail={"keys": ["smtp_removed"]})
    return _email_settings(request, u)


@app.post("/api/smtp/test")
def smtp_test(request: Request, u=Depends(auth.require_admin)):
    """Send a sample invite to the sending address itself (no invite is created)."""
    st = mailer.status(u)
    if not st["configured"]:
        raise HTTPException(409, "Save your email address and app password first")
    base = _base_url(request)
    name = st["from_name"] or mailer.suggested_name(u)
    fake = {"email": st["from_addr"], "role": "view", "libraries": None,
            "note": "This is a test of Movinite invites. The link below is only a sample.",
            "expires_at": int(time.time()) + 7 * 86400}
    subject, text, html = invites.compose(fake, base + "/#/invite/sample-link-not-valid", name, base)
    try:
        mailer.send(st["from_addr"], "[Test] " + subject, text, html, from_name=name,
                    msgid_domain=__import__("urllib.parse").parse.urlparse(base).hostname)
    except mailer.MailError as e:
        useractivity.record("email_error", user=u, detail={"reason": e.code, "test": True})
        _mail_err(e)
    useractivity.record("email_test", user=u, detail={"to": st["from_addr"]})
    return {"ok": True, "to": st["from_addr"]}


@app.post("/api/gmail/connect")
def gmail_connect(request: Request, body: dict = Body(default={}), u=Depends(auth.require_admin)):
    try:
        return gmail.start(u, _base_url(request), paste=bool(body.get("paste")))
    except gmail.GmailError as e:
        _gmail_err(e)


def _gmail_done_page(ok, msg):
    body = ("<!doctype html><meta charset=utf-8><meta name=referrer content=no-referrer><title>Movinite</title>"
            "<body style='background:#0d0a14;color:#eee;font-family:sans-serif;padding:40px'><p>%s</p>"
            "<p><a style='color:#B07CFF' href='/#/settings/email'>Back to Settings &gt; Email</a></p>"
            "<script>setTimeout(function(){location.replace('/#/settings/email?%s')},%d)</script></body>"
            % (__import__("html").escape(msg), "connected=1" if ok else "error=1", 400 if ok else 6000))
    return HTMLResponse(body, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@app.get("/api/gmail/callback")
def gmail_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    u = auth.user_from_request(request)
    if not u or not u["is_admin"]:
        return _gmail_done_page(False, "Sign in to Movinite as an admin in this browser, then press Connect Gmail again.")
    if error:
        return _gmail_done_page(False, "Google sign-in was cancelled." if error == "access_denied" else "Google returned an error (%s)." % error)
    try:
        st = gmail.finish(u, code, state)
    except gmail.GmailError as e:
        useractivity.record("gmail_error", user=u, detail={"reason": e.code})
        return _gmail_done_page(False, e.message)
    useractivity.record("gmail_connected", user=u, detail={"email": st.get("email")})
    if not mailer.configured():          # nothing else set up: use the account they just connected
        settings.put("mail_method", "gmail_oauth")
    return _gmail_done_page(True, "Gmail connected as %s." % st.get("email"))


@app.post("/api/gmail/paste")
def gmail_paste(body: dict = Body(...), u=Depends(auth.require_admin)):
    """Connect when this server isn't reachable at an https address: the browser ends on
    http://localhost/movinite-gmail-callback?code=...&state=... (it may say the page can't be reached);
    the admin pastes that address here."""
    try:
        code, state = gmail.parse_pasted(body.get("url") or "")
        st = gmail.finish(u, code, state)
    except gmail.GmailError as e:
        useractivity.record("gmail_error", user=u, detail={"reason": e.code})
        _gmail_err(e)
    useractivity.record("gmail_connected", user=u, detail={"email": st.get("email")})
    if not mailer.configured():          # nothing else set up: use the account they just connected
        settings.put("mail_method", "gmail_oauth")
    return st


@app.get("/api/gmail/status")
def gmail_status(u=Depends(auth.require_admin)):
    return gmail.status_for(u["id"])


@app.post("/api/gmail/test")
def gmail_test(request: Request, u=Depends(auth.require_admin)):
    """Send a sample invite email to the admin's own connected address (no invite is created)."""
    st = gmail.status_for(u["id"])
    if st.get("status") != "connected":
        raise HTTPException(409, "Connect Gmail first")
    base = _base_url(request)
    fake = {"email": st["email"], "role": "view", "libraries": None, "note": "This is a test of Movinite invites. The link below is only a sample.",
            "expires_at": int(time.time()) + 7 * 86400}
    subject, text, html = invites.compose(fake, base + "/#/invite/sample-link-not-valid", st.get("display_name") or u["username"], base)
    try:
        gmail.send(u["id"], st["email"], "[Test] " + subject, text, html, msgid_domain=__import__("urllib.parse").parse.urlparse(base).hostname)
    except gmail.GmailError as e:
        _gmail_err(e)
    return {"ok": True, "to": st["email"]}


@app.delete("/api/gmail")
def gmail_disconnect(u=Depends(auth.require_admin)):
    ok = gmail.disconnect(u["id"])
    useractivity.record("gmail_disconnected", user=u, detail={"revoked_at_google": ok})
    return {"ok": True, "revoked": ok}


# ---- 1.9: user activity (Settings > Activity)
def _act_args(user, group, q, since, until, before_id, limit):
    return dict(user_id=user or None, group=group or None, q=(q or "").strip()[:100] or None, since=since or None,
                until=until or None, before_id=before_id or None, limit=limit)


@app.get("/api/admin/activity")
def admin_activity(user: int = 0, group: str = "", q: str = "", since: int = 0, until: int = 0, before_id: int = 0,
                   limit: int = 100, u=Depends(auth.require_admin)):
    rows = useractivity.query(**_act_args(user, group, q, since, until, before_id, limit))
    return {"events": rows, "more": len(rows) >= max(1, min(limit, 1000)), "retention_days": useractivity.retention_days()}


@app.get("/api/admin/activity/now")
def admin_now_playing(u=Depends(auth.require_admin)):
    return {"now": useractivity.now_playing(), "at": time.time()}


@app.get("/api/admin/activity/summary")
def admin_activity_summary(days: int = 30, u=Depends(auth.require_admin)):
    return {"users": useractivity.summary(max(1, min(days, 365))), "days": days}


@app.get("/api/admin/activity/export.csv")
def admin_activity_csv(user: int = 0, group: str = "", q: str = "", since: int = 0, until: int = 0,
                       u=Depends(auth.require_admin)):
    rows = useractivity.query(**_act_args(user, group, q, since, until, 0, 1000))
    for r in rows:
        pass
    data = useractivity.to_csv(rows)
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=movinite-activity-%s.csv" % time.strftime("%Y%m%d-%H%M"),
                             "Cache-Control": "no-store"})


@app.put("/api/admin/activity/settings")
def admin_activity_settings(body: dict = Body(...), u=Depends(auth.require_admin)):
    try:
        d = int(body.get("retention_days"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Pick a retention period")
    if d not in useractivity.RETENTION_CHOICES:
        raise HTTPException(400, "Pick 30, 90, 180 or 365 days, or keep forever")
    settings.put("activity_retention_days", str(d))
    useractivity.record("settings_changed", user=u, detail={"keys": ["activity_retention_days"]})
    useractivity.prune()
    return {"retention_days": d}


@app.post("/api/admin/activity/stop")
def admin_stop_stream(body: dict = Body(...), u=Depends(auth.require_admin)):
    """Stop a viewer's transcode from Activity > Now playing."""
    uid, iid = int(body.get("user_id") or 0), int(body.get("item_id") or 0)
    n = 0
    for s in list(transcode._sessions.values()):
        if s.item["id"] == iid and getattr(s, "user_id", None) == uid:
            transcode.stop_session(s.sid, "admin_stop")
            n += 1
    useractivity.end_player(uid, iid)
    return {"ok": True, "stopped": n}


@app.get("/api/me/activity")
def my_activity(before_id: int = 0, limit: int = 100, u=Depends(auth.require_user)):
    return {"events": useractivity.query(user_id=u["id"], before_id=before_id or None, limit=limit),
            "retention_days": useractivity.retention_days()}


# ---- 1.9: trusted proxies (Settings > System)
@app.get("/api/settings/network")
def get_network(request: Request, u=Depends(auth.require_admin)):
    hint = dict(netutil.last_proxy_hint)
    return {"trusted_proxies": settings.get("trusted_proxies", "") or "", "env": os.environ.get("MS_TRUSTED_PROXIES", ""),
            "your_ip": netutil.client_ip(request), "peer": request.client.host if request.client else None,
            "untrusted_proxy": hint if hint and time.time() - hint.get("at", 0) < 86400 else None}


@app.put("/api/settings/network")
def put_network(body: dict = Body(...), u=Depends(auth.require_admin)):
    spec = (body.get("trusted_proxies") or "").strip()
    bad = netutil.valid_spec(spec)
    if bad:
        raise HTTPException(400, "Not an IP address or network: %s" % ", ".join(bad[:3]))
    settings.put("trusted_proxies", spec)
    netutil.invalidate()
    netutil.last_proxy_hint.clear()
    useractivity.record("settings_changed", user=u, detail={"keys": ["trusted_proxies"]})
    return {"ok": True, "trusted_proxies": spec}


# ---------------------------------------------------------------------------
# libraries + shares
# ---------------------------------------------------------------------------
LIB_KINDS = ("movies", "tv", "music", "other")


def _snap(d):
    """Copy of a live status dict that another thread may be changing (safe to JSON-encode)."""
    if not d:
        return None
    d = dict(d)
    for k in list(d):
        if k.startswith("_"):
            d.pop(k)
        elif isinstance(d[k], list):
            d[k] = list(d[k])
    return d


def _meta_counts(lib):
    if lib["kind"] == "movies":
        r = db.row("SELECT COUNT(*) n, SUM(CASE WHEN tmdb_id IS NOT NULL THEN 1 ELSE 0 END) m FROM items "
                   "WHERE library_id=? AND kind='movie'", (lib["id"],))
        rv = db.row("SELECT COUNT(*) n FROM items WHERE library_id=? AND " + REVIEW_COND, (lib["id"],))["n"]
        nm = db.row("SELECT COUNT(*) n FROM items WHERE library_id=? AND kind='movie' AND meta_status='nomatch'",
                    (lib["id"],))["n"]
        return {"unit": "movies", "total": r["n"], "matched": r["m"] or 0, "review": rv, "nomatch": nm,
                "pending": tmdb.pending_count(lib["id"], "movies")}
    if lib["kind"] == "tv":
        n = db.row("SELECT COUNT(DISTINCT show) n FROM items WHERE library_id=? AND show IS NOT NULL", (lib["id"],))["n"]
        m = db.row("SELECT COUNT(*) m FROM show_matches WHERE library_id=? AND tmdb_id IS NOT NULL", (lib["id"],))["m"]
        return {"unit": "shows", "total": n, "matched": m, "pending": tmdb.pending_count(lib["id"], "tv")}
    return None


def _lib_out(lib):
    lib = dict(lib)
    lib["item_count"] = db.row("SELECT COUNT(*) n FROM items WHERE library_id=?", (lib["id"],))["n"]
    if lib["kind"] == "movies":   # 1.7: films (a 4K + a 1080p file of one film count once)
        lib["film_count"] = db.row("SELECT COUNT(DISTINCT " + titles.key_sql() + ") n FROM items WHERE library_id=?",
                                   (lib["id"],))["n"]
    lib["scan"] = _snap(scanner.status.get(lib["id"]))
    lib["meta"] = _snap(tmdb.status.get(lib["id"]))
    lib["meta_counts"] = _meta_counts(lib)
    lib["artwork"] = _snap(artwork.status.get(lib["id"]))
    h = lib.get("scan_interval_h") or 0
    lib["next_scan"] = (max(lib.get("last_scan") or 0, 0) + h * 3600) if h > 0 else None
    # 1.6: share libraries use the cached, timeout-guarded check (a hung CIFS mount must not stall this request)
    lib["health"] = sharehealth.get(lib)
    lib["online"] = lib["health"]["state"] not in ("offline", "stuck") if lib["health"] else os.path.isdir(lib["path"])
    if lib.get("share_id"):
        s = db.row("SELECT id,name,kind,remote,username,options,mount_point,last_status,last_error FROM shares WHERE id=?",
                   (lib["share_id"],))
        if s:
            s["mounted"] = shares.is_mounted(s["id"])
            s["mount_mode"] = shares.mount_mode(s["id"])
            s["allow_write"] = bool(db.row("SELECT allow_write FROM shares WHERE id=?", (s["id"],))["allow_write"])
        lib["share"] = s
    return lib


@app.get("/api/libraries")
def list_libraries(u=Depends(auth.require_user)):
    out = [_lib_out(l) for l in db.rows("SELECT * FROM libraries " + liborder.ORDER_SQL)]
    out.extend(fed.list_remote_libraries(user=u))
    return out


@app.post("/api/libraries/health")
def libraries_health(u=Depends(auth.require_user)):
    """1.6: check the network-share libraries now (at most every few seconds) and return {library_id: health}."""
    sharehealth.check_all()
    return {str(l["id"]): sharehealth.get(dict(l)) for l in db.rows("SELECT id, share_id FROM libraries WHERE share_id IS NOT NULL")}


@app.put("/api/libraries/order")
def order_libraries(body: dict = Body(...), u=Depends(auth.require_admin)):
    """1.6: {"ids": [3, 1, 2, ...]} -- every library once, top to bottom. One order for everyone."""
    ids = body.get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        raise HTTPException(400, "ids must be a list of library ids")
    try:
        with db.tx() as c:
            liborder.set_order(c, ids)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return [_lib_out(l) for l in db.rows("SELECT * FROM libraries " + liborder.ORDER_SQL)]


@app.post("/api/libraries")
def add_library(body: dict = Body(...), u=Depends(auth.require_admin)):
    name = (body.get("name") or "").strip()
    kind = body.get("kind")
    src = body.get("source") or {}
    stype = src.get("type", "local")
    if not name:
        raise HTTPException(400, "Give the library a name")
    if kind not in LIB_KINDS:
        raise HTTPException(400, "Type must be one of %s" % ", ".join(LIB_KINDS))
    interval = int(body.get("scan_interval_h", 6) or 0)
    now = int(time.time())
    share_id = None
    if stype == "local":
        path = os.path.realpath((src.get("path") or "").strip())
        if not src.get("path") or not os.path.isdir(path):
            raise HTTPException(400, "Folder not found on the server: %s" % src.get("path"))
        if not os.access(path, os.R_OK | os.X_OK):
            raise HTTPException(400, "The media-server service user cannot read %s" % path)
    elif stype in ("smb", "nfs"):
        try:
            remote = shares.validate(stype, src.get("remote"))
        except ValueError as e:
            raise HTTPException(400, str(e))
        opts = (src.get("options") or "").strip()
        if opts and not re.match(r"^[A-Za-z0-9_.=:,-]+$", opts):
            raise HTTPException(400, "Mount options may only contain letters, digits and _ . = : , -")
        with db.tx() as c:
            cur = c.execute("INSERT INTO shares(name,kind,remote,username,domain,options,mount_point,created_at) "
                            "VALUES(?,?,?,?,?,?,?,?)",
                            (name, stype, remote, src.get("username") or None, src.get("domain") or None,
                             opts or None, "", now))
            share_id = cur.lastrowid
            c.execute("UPDATE shares SET mount_point=? WHERE id=?", (shares.mount_point(share_id), share_id))
        ok, msg = shares.mount(share_id, stype, remote, opts, src.get("username"), src.get("password"),
                               src.get("domain"))
        if not ok:
            shares.unmount(share_id)
            with db.tx() as c:
                c.execute("DELETE FROM shares WHERE id=?", (share_id,))
            raise HTTPException(400, "Could not mount %s: %s" % (remote, msg))
        with db.tx() as c:
            c.execute("UPDATE shares SET last_status='mounted', last_error=NULL WHERE id=?", (share_id,))
        sub = (src.get("subpath") or "").strip().strip("/")
        if ".." in sub.split("/"):
            raise HTTPException(400, "Bad sub-folder")
        path = os.path.join(shares.mount_point(share_id), sub) if sub else shares.mount_point(share_id)
        if not os.path.isdir(path):
            raise HTTPException(400, "Mounted, but sub-folder %s does not exist" % sub)
    elif stype == "existing":
        sh = _connection(src)
        try:
            remote = _conn_remote(sh, src)
            sub = browse.clean_rel(src.get("subpath") or "")
            if sh["kind"] != "smb" or browse.parse_smb(remote)[1]:
                remote = shares.validate(sh["kind"], remote)
        except browse.BrowseError as e:
            raise HTTPException(400, e.msg)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if sh["kind"] == "smb" and not browse.parse_smb(remote)[1]:
            raise HTTPException(400, "Pick a share on %s" % _host_of("smb", remote))
        inside = _within(sh, remote)
        if inside is not None:
            sub = "/".join(x for x in (inside, sub) if x)
            share_id = sh["id"]                     # the same mount, shared (reference-counted by libraries)
            if not shares.is_mounted(share_id) and not os.path.isdir(shares.mount_point(share_id)):
                ok, msg = shares.remount(share_id)
                if not ok:
                    raise HTTPException(400, "The share %s isn't mounted and could not be remounted: %s" % (sh["remote"], msg))
        else:
            with db.tx() as c:
                cur = c.execute("INSERT INTO shares(name,kind,remote,username,domain,options,mount_point,created_at) "
                                "VALUES(?,?,?,?,?,?,?,?)",
                                (name, sh["kind"], remote, sh["username"], sh["domain"], sh["options"], "", now))
                share_id = cur.lastrowid
                c.execute("UPDATE shares SET mount_point=? WHERE id=?", (shares.mount_point(share_id), share_id))
            ok, msg = shares.mount_as(share_id, sh["id"], sh["kind"], remote, sh["options"] or "")
            if not ok:
                shares.unmount(share_id)
                with db.tx() as c:
                    c.execute("DELETE FROM shares WHERE id=?", (share_id,))
                raise HTTPException(400, "Could not mount %s: %s" % (remote, msg))
            with db.tx() as c:
                c.execute("UPDATE shares SET last_status='mounted', last_error=NULL WHERE id=?", (share_id,))
        path = os.path.join(shares.mount_point(share_id), sub) if sub else shares.mount_point(share_id)
        if not os.path.isdir(path):
            raise HTTPException(400, "Sub-folder %s does not exist on %s" % (sub, remote))
    else:
        raise HTTPException(400, "Unknown source type")
    with db.tx() as c:
        cur = c.execute("INSERT INTO libraries(name,kind,path,share_id,scan_interval_h,created_at) VALUES(?,?,?,?,?,?)",
                        (name, kind, path, share_id, interval, now))
        lib_id = cur.lastrowid
        liborder.assign_missing(c)      # 1.6: placed by type (Movies, TV, Other videos, Music), custom order kept
    scanner.request_scan(lib_id)
    useractivity.record("library_added", user=u, item={"library_id": lib_id, "title": name}, detail={"kind": kind})
    return _lib_out(db.row("SELECT * FROM libraries WHERE id=?", (lib_id,)))


@app.put("/api/libraries/{lib_id}")
def edit_library(lib_id: int, body: dict = Body(...), u=Depends(auth.require_admin)):
    lib = db.row("SELECT * FROM libraries WHERE id=?", (lib_id,))
    if not lib:
        raise HTTPException(404, "No such library")
    name = (body.get("name") or lib["name"]).strip()
    interval = int(body.get("scan_interval_h", lib["scan_interval_h"]) or 0)
    art = {k: int(bool(body[k])) if k in body else (lib.get(k) or 0)
           for k in ("art_write", "art_fanart", "art_nfo", "art_overwrite", "art_thumbs")}
    # 1.4.14: change the folder (inside the same share, or another local folder). The share mount is untouched.
    new_path = None
    if lib["share_id"] and "subpath" in body:
        root = os.path.realpath(shares.mount_point(lib["share_id"]))
        try:
            sub = browse.clean_rel(body.get("subpath"))
        except browse.BrowseError as e:
            raise HTTPException(400, e.msg)
        cand = os.path.realpath(os.path.join(root, sub)) if sub else root
        if cand != root and not cand.startswith(root + os.sep):
            raise HTTPException(400, "That folder is outside the share")
        if not os.path.isdir(cand):
            raise HTTPException(400, "Sub-folder %s does not exist on the share" % sub)
        new_path = os.path.join(root, sub) if sub else root
    elif not lib["share_id"] and body.get("path"):
        cand = os.path.realpath(str(body.get("path")).strip())
        if not os.path.isdir(cand):
            raise HTTPException(400, "Folder not found on the server: %s" % body.get("path"))
        if not os.access(cand, os.R_OK | os.X_OK):
            raise HTTPException(400, "The media-server service user cannot read %s" % cand)
        new_path = cand
    if new_path and os.path.normpath(new_path) == os.path.normpath(lib["path"]):
        new_path = None
    with db.tx() as c:
        c.execute("UPDATE libraries SET name=?, scan_interval_h=?, art_write=?, art_fanart=?, art_nfo=?, art_overwrite=?, "
                  "art_thumbs=? WHERE id=?", (name, interval, art["art_write"], art["art_fanart"], art["art_nfo"],
                                              art["art_overwrite"], art["art_thumbs"], lib_id))
        if new_path:
            c.execute("UPDATE libraries SET path=? WHERE id=?", (new_path, lib_id))
    if new_path:
        scanner.request_scan(lib_id, full=True)
    out = _lib_out(db.row("SELECT * FROM libraries WHERE id=?", (lib_id,)))
    if art["art_write"] and not lib.get("art_write"):
        out["write_ok"], out["write_message"] = artwork.check_writable(lib)
    return out


def _show_item_ids(lib_id, show):
    """1.5.5: the episode ids of one show (artwork for a single show), or None for the whole library."""
    if not show:
        return None
    ids = [r["id"] for r in db.rows("SELECT id FROM items WHERE library_id=? AND show=?", (lib_id, show))]
    if not ids:
        raise HTTPException(404, "No such show")
    return ids


@app.get("/api/libraries/{lib_id}/artwork/preview")
def artwork_preview(lib_id: int, limit: int = 500, show: str = "", u=Depends(auth.require_admin)):
    """Dry run: which files would be written (nothing is touched)."""
    try:
        lib, actions = artwork.plan_library(lib_id, _show_item_ids(lib_id, show))
    except ValueError as e:
        raise HTTPException(404, str(e))
    ok, msg = artwork.check_writable(lib) if os.path.isdir(lib["path"]) else (False, "library folder not reachable")
    todo = [a for a in actions if a["action"] != "skip"]
    return {"summary": artwork.summarize(actions), "writable": ok, "write_message": msg,
            "items": len({a["item_id"] for a in actions}),
            "actions": (todo + [a for a in actions if a["action"] == "skip"])[:max(1, min(limit, 5000))],
            "options": {k: bool(lib.get(k)) for k in ("art_write", "art_fanart", "art_nfo", "art_overwrite", "art_thumbs")}}


@app.post("/api/libraries/{lib_id}/artwork/write")
def artwork_write(lib_id: int, body: dict = Body(default={}), u=Depends(auth.require_admin)):
    lib = db.row("SELECT * FROM libraries WHERE id=?", (lib_id,))
    if not lib:
        raise HTTPException(404, "No such library")
    if lib["kind"] not in ("movies", "tv"):
        raise HTTPException(400, "Artwork saving is for movie and TV libraries")   # 1.5.5: + TV
    ok, msg = artwork.check_writable(lib)
    if not ok:
        raise HTTPException(400, msg)
    return {"started": artwork.start_library(lib_id, _show_item_ids(lib_id, (body or {}).get("show") if lib["kind"] == "tv" else None))}


@app.post("/api/libraries/{lib_id}/artwork/cancel")
def artwork_cancel(lib_id: int, u=Depends(auth.require_admin)):
    artwork.cancel(lib_id)
    return {"ok": True}


@app.delete("/api/libraries/{lib_id}")
def delete_library(lib_id: int, u=Depends(auth.require_admin)):
    lib = db.row("SELECT * FROM libraries WHERE id=?", (lib_id,))
    if not lib:
        raise HTTPException(404, "No such library")
    scanner.cancel_scan(lib_id)
    with db.tx() as c:
        c.execute("DELETE FROM libraries WHERE id=?", (lib_id,))
    scanner.status.pop(lib_id, None)
    scanner.logs.pop(lib_id, None)
    useractivity.record("library_removed", user=u, item={"title": lib["name"]}, detail={"kind": lib["kind"], "library_id": lib_id})
    if lib["share_id"]:
        others = db.row("SELECT COUNT(*) n FROM libraries WHERE share_id=?", (lib["share_id"],))["n"]
        if not others:
            shares.unmount(lib["share_id"])
            with db.tx() as c:
                c.execute("DELETE FROM shares WHERE id=?", (lib["share_id"],))
    return {"ok": True}


@app.post("/api/libraries/{lib_id}/scan")
def scan_library(lib_id: int, full: bool = False, u=Depends(auth.require_admin)):
    if not db.row("SELECT id FROM libraries WHERE id=?", (lib_id,)):
        raise HTTPException(404, "No such library")
    queued = scanner.request_scan(lib_id, full=full)
    if queued:
        useractivity.record("scan_started", user=u, item={"library_id": lib_id, "title": (db.row("SELECT name FROM libraries WHERE id=?", (lib_id,)) or {}).get("name")}, detail={"full": bool(full)})
    return {"queued": queued, "status": scanner.status.get(lib_id)}


@app.get("/api/scan-status")
def scan_status(u=Depends(auth.require_user)):
    return {str(k): _snap(v) for k, v in list(scanner.status.items())}


@app.post("/api/libraries/{lib_id}/scan/cancel")
def cancel_scan(lib_id: int, u=Depends(auth.require_admin)):
    if not scanner.cancel_scan(lib_id):
        raise HTTPException(409, "No scan is running for this library")
    return {"ok": True}


@app.get("/api/libraries/{lib_id}/scan/log")
def scan_log(lib_id: int, n: int = 60, u=Depends(auth.require_admin)):
    lines = list(scanner.logs.get(lib_id) or [])
    return lines[-max(1, min(n, 300)):]


@app.get("/api/activity")
def activity(u=Depends(auth.require_user)):
    """Everything the global scan indicator needs, cheap enough to poll every 1-2 s."""
    libs = {r["id"]: r for r in db.rows("SELECT id, name, kind FROM libraries")}
    scans, meta = [], []
    now = time.time()
    for lid, st in list(scanner.status.items()):
        if lid not in libs:
            continue
        st = _snap(st)
        recent = st.get("finished_at") and now - st["finished_at"] < 600
        if st.get("state") in ("queued", "scanning") or recent:
            st.update({"library_id": lid, "name": libs[lid]["name"], "kind": libs[lid]["kind"]})
            scans.append(st)
    for lid, st in list(tmdb.status.items()):
        if lid not in libs:
            continue
        st = _snap(st)
        if st.get("state") in ("queued", "running") or (st.get("finished_at") and now - st["finished_at"] < 600):
            st.update({"library_id": lid, "name": libs[lid]["name"], "kind": libs[lid]["kind"]})
            meta.append(st)
    arts = []
    for lid, st in list(artwork.status.items()):
        if lid not in libs:
            continue
        st = _snap(st)
        if st.get("state") in ("queued", "running") or (st.get("finished_at") and now - st["finished_at"] < 600):
            st.update({"library_id": lid, "name": libs[lid]["name"], "kind": libs[lid]["kind"]})
            arts.append(st)
    active = any(s.get("state") in ("queued", "scanning") for s in scans) or \
        any(m.get("state") in ("queued", "running") for m in meta) or \
        any(a.get("state") in ("queued", "running") for a in arts)
    return {"active": active, "scans": scans, "metadata": meta, "artwork": arts, "now": now}


@app.post("/api/shares/{share_id}/remount")
def remount_share(share_id: int, u=Depends(auth.require_admin)):
    if not db.row("SELECT id FROM shares WHERE id=?", (share_id,)):
        raise HTTPException(404, "No such share")
    ok, msg = shares.remount(share_id)
    with db.tx() as c:
        c.execute("UPDATE shares SET last_status=?, last_error=? WHERE id=?",
                  ("mounted" if ok else "error", None if ok else msg, share_id))
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True}


@app.put("/api/shares/{share_id}")
def edit_share(share_id: int, body: dict = Body(...), u=Depends(auth.require_admin)):
    """Change credentials/options of an existing share and remount it."""
    s = db.row("SELECT * FROM shares WHERE id=?", (share_id,))
    if not s:
        raise HTTPException(404, "No such share")
    try:
        remote = shares.validate(s["kind"], body.get("remote") or s["remote"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    opts = (body.get("options") if body.get("options") is not None else s["options"]) or ""
    if opts and not re.match(r"^[A-Za-z0-9_.=:,-]+$", opts):
        raise HTTPException(400, "Bad mount options")
    username = body.get("username") if body.get("username") is not None else s["username"]
    domain = body.get("domain") if body.get("domain") is not None else s["domain"]
    ok, msg = shares.mount(share_id, s["kind"], remote, opts, username, body.get("password") or "", domain,
                           allow_write=bool(s.get("allow_write")))
    with db.tx() as c:
        c.execute("UPDATE shares SET remote=?, options=?, username=?, domain=?, last_status=?, last_error=? WHERE id=?",
                  (remote, opts or None, username, domain, "mounted" if ok else "error", None if ok else msg, share_id))
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True}


@app.put("/api/shares/{share_id}/name")
def rename_share(share_id: int, body: dict = Body(...), u=Depends(auth.require_admin)):
    """1.7: the name shown as the share's heading in the side menu. Only the label changes (no remount)."""
    name = (body.get("name") or "").strip()
    if not name or len(name) > 60:
        raise HTTPException(400, "Give the share a name (up to 60 characters)")
    with db.tx() as c:
        if not c.execute("UPDATE shares SET name=? WHERE id=?", (name, share_id)).rowcount:
            raise HTTPException(404, "No such share")
    return {"ok": True, "name": name}


@app.post("/api/shares/{share_id}/access")
def share_access(share_id: int, body: dict = Body(...), u=Depends(auth.require_admin)):
    """1.3: {"allow_write": true} remounts the share read-write so artwork can be saved; false = read-only again."""
    s = db.row("SELECT * FROM shares WHERE id=?", (share_id,))
    if not s:
        raise HTTPException(404, "No such share")
    want = bool(body.get("allow_write"))
    if not want:
        for lib in db.rows("SELECT id FROM libraries WHERE share_id=?", (share_id,)):
            artwork.cancel(lib["id"])
    ok, msg = shares.set_access(share_id, want)
    if not ok:
        raise HTTPException(400, "Could not remount the share %s: %s" % ("read-write" if want else "read-only", msg))
    with db.tx() as c:
        c.execute("UPDATE shares SET allow_write=?, last_status='mounted', last_error=NULL WHERE id=?", (int(want), share_id))
    out = {"ok": True, "allow_write": want, "mount_mode": shares.mount_mode(share_id)}
    if want:   # the mount may be rw while the NAS still says no -- find out now, not halfway through a run
        for l in db.rows("SELECT id FROM libraries WHERE share_id=?", (share_id,)):
            if (artwork.status.get(l["id"]) or {}).get("state") == "error":
                artwork.status.pop(l["id"], None)   # let automatic writing try again right away
        lib = db.row("SELECT * FROM libraries WHERE share_id=? LIMIT 1", (share_id,))
        if lib:
            out["write_ok"], out["write_message"] = artwork.check_writable(lib)
    return out


# 1.4.14: "Browse" in Add library -- list a share's shares / folders before it is added (nothing is kept mounted).
# POST so the share password travels in the body, never in a URL or an access log line. Never echoed back.
def _browse_fail(e):
    # 400 (not 401: that would sign the admin out of the web app) with a machine-readable code for the UI
    return JSONResponse({"detail": e.msg, "code": e.code}, status_code=400)


# ---- 1.5.3: "Use an existing connection" in Add library. A connection = a share that is already set up (server,
# share, login). Its password stays in the root-only credentials file: the app never reads or returns it. Picking one
#  - on the SAME share: the new library shares that mount (same share id; the mount is removed only when the last
#    library using it is deleted -- reference count by libraries.share_id);
#  - on ANOTHER share of the same server: a new share is mounted and the root helper copies the login into its own
#    credentials file (add-as), so deleting either library never breaks the other.
def _host_of(kind, remote):
    if kind == "smb":
        return browse.parse_smb(remote)[0].lower()
    return remote.split(":", 1)[0].lower()


def _connection(src):
    try:
        sid = int(src.get("share_id"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Pick a connection")
    sh = db.row("SELECT * FROM shares WHERE id=?", (sid,))
    if not sh:
        raise HTTPException(404, "That connection no longer exists")
    return sh


def _conn_remote(sh, src):
    """The share the admin is looking at with this connection's login: its own (default) or another on the same server."""
    kind = sh["kind"]
    raw = (src.get("remote") or "").strip() or sh["remote"]
    if kind == "smb":
        host, share, sub = browse.parse_smb(raw)
        remote = "//%s" % host + ("/" + share if share else "") + ("/" + sub if share and sub else "")
    else:
        host, export = browse.parse_nfs(raw)
        remote = "%s:%s" % (host, export) if export else host
    if _host_of(kind, remote) != _host_of(kind, sh["remote"]):
        raise browse.BrowseError("bad", "This login can only be used for shares on %s." % _host_of(kind, sh["remote"]))
    return remote


def _within(sh, remote):
    """If `remote` is the connection's own share (or a folder inside it): the folder relative to its mount, else None."""
    if sh["kind"] == "smb":
        h1, s1, sub1 = browse.parse_smb(sh["remote"])
        h2, s2, sub2 = browse.parse_smb(remote)
        if h1.lower() != h2.lower() or s1.lower() != s2.lower():
            return None
    else:
        sub1, sub2 = sh["remote"].rstrip("/"), remote.rstrip("/")
    if sub2 == sub1:
        return ""
    if not sub1:
        return sub2.lstrip("/")
    return sub2[len(sub1) + 1:] if sub2.startswith(sub1 + "/") else None


@app.get("/api/connections")
def list_connections(u=Depends(auth.require_admin)):
    out, seen = [], set()
    for sh in db.rows("SELECT * FROM shares ORDER BY id"):
        key = (sh["kind"], sh["remote"].lower(), sh["username"] or "", sh["domain"] or "", sh["options"] or "")
        if key in seen:
            continue
        seen.add(key)
        libs = [l["name"] for l in db.rows("SELECT name FROM libraries WHERE share_id=? " + liborder.ORDER_SQL, (sh["id"],))]
        out.append({"id": sh["id"], "kind": sh["kind"], "remote": sh["remote"], "host": _host_of(sh["kind"], sh["remote"]),
                    "username": sh["username"] or "", "domain": sh["domain"] or "", "options": sh["options"] or "",
                    "guest": sh["kind"] == "smb" and not sh["username"], "libraries": libs,
                    "mounted": shares.is_mounted(sh["id"])})
    return out


def _browse_existing(src, rel):
    sh = _connection(src)
    kind, opts = sh["kind"], sh["options"] or ""
    remote = _conn_remote(sh, src)
    if kind == "smb":
        host, share, sub = browse.parse_smb(remote)
        browse.reach(host, browse.smb_port(opts))
        if not share:
            return {"mode": "shares", "remote": "//" + host, "path": "", "parent": None, "via": "saved",
                    "dirs": browse.helper_shares(sh["id"], host, opts), "videos": 0, "suggest": None, "share_id": sh["id"]}
    else:
        host, export = browse.parse_nfs(remote)
        if not export:
            d = browse.browse({"type": "nfs", "remote": host, "options": opts}, "")
            d["share_id"] = sh["id"]
            return d
    rel = browse.clean_rel(rel)
    inside = _within(sh, remote)
    if inside is not None and (shares.is_mounted(sh["id"]) or os.path.isdir(shares.mount_point(sh["id"]))):
        rel = "/".join(x for x in (inside, rel) if x)
        d = browse.list_local(rel, root=shares.mount_point(sh["id"]))      # already mounted: just look inside
        d.update(mode="dirs", remote=sh["remote"], path=rel, via="share")
        root = os.path.realpath(shares.mount_point(sh["id"]))
        d["dirs"] = [x for x in d.get("dirs", []) if os.path.realpath(os.path.join(root, rel, x["name"])).startswith(root + os.sep)]
    elif kind == "smb":
        host, share, sub = browse.parse_smb(remote)
        base = "//%s/%s" % (host, share)
        full = "/".join(x for x in (sub, rel) if x)
        dirs, videos, trunc = browse.helper_list("smb", base, full, opts, as_share=sh["id"])
        rel = full
        remote = base
        d = {"mode": "dirs", "remote": remote, "path": rel, "dirs": dirs, "videos": videos, "truncated": trunc, "via": "saved"}
    else:
        d = browse.browse({"type": "nfs", "remote": remote, "options": opts}, rel)
    d["parent"] = (d["path"].rsplit("/", 1)[0] if "/" in d["path"] else "") if d.get("path") else None
    d["suggest"] = browse.suggest_kind(os.path.basename((d.get("path") or "").rstrip("/")) or (d.get("remote") or "").rstrip("/").rsplit("/", 1)[-1])
    d["share_id"] = sh["id"]
    return d


@app.post("/api/browse")
def browse_source(body: dict = Body(...), u=Depends(auth.require_admin)):
    src = body.get("source") or {}
    try:
        if src.get("type") == "existing":
            return _browse_existing(src, body.get("path") or "")
        return browse.browse(src, body.get("path") or "")
    except browse.BrowseError as e:
        return _browse_fail(e)


@app.get("/api/libraries/{lib_id}/browse")
def browse_library(lib_id: int, path: str = "", u=Depends(auth.require_admin)):
    """Folders for Edit library -> Change folder: inside the library's existing share mount (never remounted)."""
    lib = db.row("SELECT * FROM libraries WHERE id=?", (lib_id,))
    if not lib:
        raise HTTPException(404, "No such library")
    try:
        if lib["share_id"]:
            if not shares.is_mounted(lib["share_id"]) and not os.path.isdir(shares.mount_point(lib["share_id"])):
                raise browse.BrowseError("unreachable", "The share isn't mounted right now (Settings -> Libraries -> Remount).")
            d = browse.list_local(path, root=shares.mount_point(lib["share_id"]))
            sh = db.row("SELECT remote FROM shares WHERE id=?", (lib["share_id"],)) or {}
            d.update(mode="dirs", remote=sh.get("remote"), via="share")
        else:
            d = browse.list_local(path or lib["path"])
            d.update(mode="dirs", via="local")
        d["suggest"] = browse.suggest_kind(os.path.basename(d["path"] or (d.get("remote") or "").rstrip("/")))
        return d
    except browse.BrowseError as e:
        return _browse_fail(e)


@app.get("/api/fs")
def browse_fs(path: str = "/", u=Depends(auth.require_admin)):
    """List sub-folders so the admin can pick a library folder."""
    p = os.path.realpath(path or "/")
    if not os.path.isdir(p):
        raise HTTPException(404, "Not a folder")
    try:
        entries = sorted(e.name for e in os.scandir(p) if e.is_dir(follow_symlinks=True) and not e.name.startswith("."))
    except PermissionError:
        entries = []
    return {"path": p, "parent": os.path.dirname(p) if p != "/" else None, "dirs": entries[:500]}


# ---------------------------------------------------------------------------
# browsing
# ---------------------------------------------------------------------------
ITEM_COLS = ("id, library_id, media_type, kind, title, year, show, season, episode, episode_title, artist, album, "
             "album_artist, track, disc, duration, thumb, poster, added_at, width, height, vcodec, acodec, tmdb_id, "
             "edition, meta_status, meta_confidence, bitrate, size")
# 1.3: "Needs review" = flagged by the matcher, low-confidence automatic matches, or a year far from the file's
REVIEW_COND = ("(kind='movie' AND (meta_status='review' OR (meta_status='matched' AND (COALESCE(meta_confidence,1) < %s "
               "OR EXISTS(SELECT 1 FROM metadata mr WHERE mr.kind='movie' AND mr.tmdb_id=items.tmdb_id AND "
               "items.year IS NOT NULL AND mr.year IS NOT NULL AND abs(mr.year-items.year) > 1)))))" % tmdb.REVIEW_BELOW)
# 1.2.1: "has real artwork" = a local poster.jpg/folder.jpg or a cached TMDB poster (not a video frame)
HAS_ART = ("(COALESCE(poster<>thumb, 0) OR EXISTS(SELECT 1 FROM metadata md WHERE md.kind='movie' "
           "AND md.tmdb_id=items.tmdb_id AND md.poster IS NOT NULL))")
SORTS = {"poster": HAS_ART + " DESC, sort_title COLLATE NOCASE, year",
         "title": "sort_title COLLATE NOCASE, year", "added": "added_at DESC, id DESC", "year": "year DESC, sort_title",
         "duration": "duration DESC"}


def _with_progress(items, user_id):
    if not items:
        return items
    try:
        tmdb.enrich(items)
    except Exception:  # metadata must never break browsing
        log.exception("enrich")
    ids = [i["id"] for i in items]
    prog = {}
    for chunk in range(0, len(ids), 500):
        part = ids[chunk:chunk + 500]
        for r in db.rows("SELECT item_id, position, duration, watched FROM progress WHERE user_id=? AND item_id IN (%s)"
                         % ",".join("?" * len(part)), [user_id] + part):
            prog[r["item_id"]] = r
    for i in items:
        p = prog.get(i["id"])
        i["position"] = p["position"] if p else 0
        i["watched"] = bool(p["watched"]) if p else False
    return items


# 1.4: categories ---------------------------------------------------------------------------------------
MOVIE_META = "(SELECT %s FROM metadata md WHERE md.kind='movie' AND md.tmdb_id=items.tmdb_id)"


def _cat_filters(genres="", decade="", collection=0, tag=0, cert=""):
    """-> (sql, args) narrowing items to the chosen categories. Several genres = movies that have ALL of them."""
    sql, args = "", []
    for g in [x.strip() for x in (genres or "").split("|") if x.strip()][:8]:
        sql += " AND tmdb_id IN (SELECT tmdb_id FROM movie_genres WHERE genre=?)"
        args.append(g)
    if decade and str(decade).isdigit():
        d = int(decade)
        sql += " AND COALESCE(" + (MOVIE_META % "md.year") + ", year) BETWEEN ? AND ?"
        args += [d, d + 9]
    if collection:
        sql += " AND tmdb_id IN (SELECT tmdb_id FROM metadata WHERE kind='movie' AND collection_id=?)"
        args.append(int(collection))
    if tag:
        sql += " AND id IN (SELECT item_id FROM item_tags WHERE tag_id=?)"
        args.append(int(tag))
    if cert:
        sql += " AND tmdb_id IN (SELECT tmdb_id FROM metadata WHERE kind='movie' AND certification=?)"
        args.append(cert)
    return sql, args


def _facets(cond, args):
    """Counts for the category chips, within the current selection."""
    base = "SELECT id, tmdb_id, year FROM items WHERE " + cond
    genres = db.rows("SELECT g.genre name, COUNT(DISTINCT f.id) n FROM (" + base + ") f JOIN movie_genres g ON g.tmdb_id=f.tmdb_id "
                     "GROUP BY g.genre ORDER BY n DESC, g.genre", args)
    decades = db.rows("SELECT (COALESCE(md.year, f.year)/10)*10 decade, COUNT(*) n FROM (" + base + ") f "
                      "LEFT JOIN metadata md ON md.kind='movie' AND md.tmdb_id=f.tmdb_id "
                      "WHERE COALESCE(md.year, f.year) IS NOT NULL GROUP BY 1 ORDER BY 1 DESC", args)
    certs = db.rows("SELECT md.certification name, COUNT(*) n FROM (" + base + ") f JOIN metadata md ON md.kind='movie' "
                    "AND md.tmdb_id=f.tmdb_id WHERE COALESCE(md.certification,'')<>'' GROUP BY 1 ORDER BY n DESC", args)
    tags = db.rows("SELECT t.id, t.name, COUNT(*) n FROM (" + base + ") f JOIN item_tags it ON it.item_id=f.id "
                   "JOIN tags t ON t.id=it.tag_id GROUP BY t.id ORDER BY t.name COLLATE NOCASE", args)
    return {"genres": genres, "decades": decades, "certifications": certs, "tags": tags}


@app.get("/api/libraries/{lib_id}/collections")
def library_collections(lib_id: int, q: str = "", u=Depends(auth.require_user)):
    """1.4: TMDB collections / franchises that have at least one movie in this library."""
    if not db.row("SELECT 1 x FROM libraries WHERE id=?", (lib_id,)):
        raise HTTPException(404, "No such library")
    rows = db.rows(
        "SELECT c.id, c.name, c.poster, COUNT(DISTINCT i.tmdb_id) n, MIN(md.year) year_from, MAX(md.year) year_to, "
        "(SELECT md2.poster FROM metadata md2 JOIN items i2 ON i2.tmdb_id=md2.tmdb_id AND i2.library_id=? "
        " WHERE md2.kind='movie' AND md2.collection_id=c.id AND md2.poster IS NOT NULL ORDER BY md2.year LIMIT 1) first_poster "
        "FROM collections c JOIN metadata md ON md.kind='movie' AND md.collection_id=c.id "
        "JOIN items i ON i.tmdb_id=md.tmdb_id AND i.library_id=? AND i.kind='movie' "
        "WHERE c.name LIKE ? GROUP BY c.id ORDER BY c.name COLLATE NOCASE", (lib_id, lib_id, "%" + q.strip() + "%"))
    for r in rows:
        r["poster"] = r["poster"] or r.pop("first_poster", None)
        r.pop("first_poster", None)
    pending = db.row("SELECT COUNT(DISTINCT tmdb_id) n FROM items WHERE library_id=? AND kind='movie' AND " + tmdb.CAT_PENDING,
                     (lib_id,))["n"]
    return {"collections": rows, "pending": pending}


def _smart_rows(lib_id, key, u, limit, offset=0):
    ranked, note = homerows.row(u["id"], lib_id, key)
    page = ranked[offset:offset + limit]
    ids = [i for i, _ in page]
    rows = {r["id"]: r for r in db.rows("SELECT " + ITEM_COLS + " FROM items WHERE id IN (%s)" % ",".join("?" * len(ids)),
                                          ids)} if ids else {}
    items = []
    for i, reason in page:
        if i in rows:
            r = dict(rows[i])
            if reason and key == "recommended":
                r["reason"] = reason
            items.append(r)
    return {"key": key, "title": homerows.ROWS[key], "note": note, "items": _with_progress(items, u["id"]),
            "total": len(ranked)}


@app.get("/api/libraries/{lib_id}/smart/{key}")
def library_smart(lib_id: int, key: str, limit: int = 100, offset: int = 0, u=Depends(auth.require_user)):
    """1.4.1: the full list behind a Home row (Recommended, Recently released, Recently added, Top movies)."""
    lib = db.row("SELECT * FROM libraries WHERE id=?", (lib_id,))
    if not lib or lib["kind"] != "movies":
        raise HTTPException(404, "No such movie library")
    if key not in homerows.ROWS:
        raise HTTPException(404, "No such view")
    out = _smart_rows(lib_id, key, u, max(1, min(limit, 500)), max(0, offset))
    out["library"] = _lib_out(lib)
    return out


@app.post("/api/items/{item_id}/pin")
def pin_item(item_id: int, body: dict = Body(...), u=Depends(auth.require_admin)):
    """{"row": "recommended"|"top", "mode": 1 (always include) | -1 (never) | 0 (automatic)}"""
    row = body.get("row")
    mode = int(body.get("mode") or 0)
    if row not in homerows.PIN_ROWS or mode not in (-1, 0, 1):
        raise HTTPException(400, "Bad row or mode")
    _get_item(item_id)
    with db.tx() as c:
        if mode:
            c.execute("INSERT OR REPLACE INTO home_pins(row, item_id, mode, created_at) VALUES(?,?,?,?)",
                      (row, item_id, mode, int(time.time())))
        else:
            c.execute("DELETE FROM home_pins WHERE row=? AND item_id=?", (row, item_id))
    return {"ok": True}


@app.get("/api/libraries/{lib_id}/genres")
def library_genres(lib_id: int, u=Depends(auth.require_user)):
    return _facets("library_id=? AND kind='movie'", [lib_id])


# custom tags (admin) ------------------------------------------------------------------------------------
@app.get("/api/tags")
def list_tags(u=Depends(auth.require_user)):
    return db.rows("SELECT t.id, t.name, COUNT(it.item_id) n FROM tags t LEFT JOIN item_tags it ON it.tag_id=t.id "
                   "GROUP BY t.id ORDER BY t.name COLLATE NOCASE")


def _tag_id(name):
    name = re.sub(r"\s+", " ", (name or "").strip())[:60]
    if not name:
        raise HTTPException(400, "Tag name is empty")
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO tags(name, created_at) VALUES(?,?)", (name, int(time.time())))
        return c.execute("SELECT id FROM tags WHERE name=? COLLATE NOCASE", (name,)).fetchone()[0]


@app.post("/api/tags/apply")
def apply_tags(body: dict = Body(...), u=Depends(auth.require_admin)):
    """{"item_ids": [..], "add": ["Kids"], "remove": [tag ids]} -- add / remove tags on many movies at once."""
    ids = [int(x) for x in (body.get("item_ids") or [])][:10000]
    if not ids:
        raise HTTPException(400, "No movies selected")
    add = [_tag_id(n) for n in (body.get("add") or [])][:20]
    rem = [int(x) for x in (body.get("remove") or [])][:50]
    with db.tx() as c:
        for t in add:
            c.executemany("INSERT OR IGNORE INTO item_tags(item_id, tag_id) SELECT id, ? FROM items WHERE id=?",
                          [(t, i) for i in ids])
        for t in rem:
            c.executemany("DELETE FROM item_tags WHERE item_id=? AND tag_id=?", [(i, t) for i in ids])
        c.execute("DELETE FROM tags WHERE NOT EXISTS (SELECT 1 FROM item_tags WHERE tag_id=tags.id)")
    return {"ok": True, "tags": list_tags(u)}


@app.put("/api/tags/{tag_id}")
def rename_tag(tag_id: int, body: dict = Body(...), u=Depends(auth.require_admin)):
    name = re.sub(r"\s+", " ", (body.get("name") or "").strip())[:60]
    if not name:
        raise HTTPException(400, "Tag name is empty")
    other = db.row("SELECT id FROM tags WHERE name=? COLLATE NOCASE AND id<>?", (name, tag_id))
    with db.tx() as c:
        if other:   # renaming onto an existing tag merges them
            c.execute("INSERT OR IGNORE INTO item_tags(item_id, tag_id) SELECT item_id, ? FROM item_tags WHERE tag_id=?",
                      (other["id"], tag_id))
            c.execute("DELETE FROM item_tags WHERE tag_id=?", (tag_id,))
            c.execute("DELETE FROM tags WHERE id=?", (tag_id,))
        else:
            c.execute("UPDATE tags SET name=? WHERE id=?", (name, tag_id))
    return {"ok": True}


@app.delete("/api/tags/{tag_id}")
def delete_tag(tag_id: int, u=Depends(auth.require_admin)):
    with db.tx() as c:
        c.execute("DELETE FROM item_tags WHERE tag_id=?", (tag_id,))
        c.execute("DELETE FROM tags WHERE id=?", (tag_id,))
    return {"ok": True}


@app.get("/api/libraries/{lib_id}/items")
def library_items(lib_id: int, sort: str = "poster", q: str = "", offset: int = 0, limit: int = 200,
                  view: str = "", filter: str = "", genres: str = "", decade: str = "", collection: int = 0,
                  tag: int = 0, cert: str = "", facets: int = 0, u=Depends(auth.require_user)):
    if lib_id < 0:
        return fed.library_items(lib_id, q=q, offset=offset, limit=limit, user=u)
    lib = db.row("SELECT * FROM libraries WHERE id=?", (lib_id,))
    if not lib:
        raise HTTPException(404, "No such library")
    limit = max(1, min(limit, 10000))
    like = "%" + q.strip() + "%"
    if lib["kind"] == "tv" and view != "files":
        rows = db.rows(
            "SELECT show, MIN(year) year, COUNT(*) episodes, COUNT(DISTINCT season) seasons, MAX(added_at) added_at, "
            "(SELECT poster FROM items i2 WHERE i2.library_id=items.library_id AND i2.show=items.show AND i2.poster IS NOT NULL "
            " ORDER BY (i2.poster<>i2.thumb) DESC, season, episode LIMIT 1) poster "
            "FROM items WHERE library_id=? AND kind='episode' AND show LIKE ? GROUP BY show ORDER BY %s LIMIT ? OFFSET ?"
            % {"added": "added_at DESC", "year": "MIN(year) DESC, show COLLATE NOCASE",
               "poster": "(EXISTS(SELECT 1 FROM show_matches sm JOIN metadata md ON md.kind='tv' AND md.tmdb_id=sm.tmdb_id "
                         "WHERE sm.library_id=items.library_id AND sm.show=items.show AND sm.status IN ('matched','manual') "
                         "AND md.poster IS NOT NULL) OR MAX(COALESCE(poster<>thumb,0))) DESC, show COLLATE NOCASE"
               }.get(sort, "show COLLATE NOCASE"),
            (lib_id, like, limit, offset))
        loose = db.rows("SELECT " + ITEM_COLS + " FROM items WHERE library_id=? AND kind<>'episode' AND title LIKE ? "
                        "ORDER BY sort_title LIMIT 200", (lib_id, like))
        _enrich_shows(lib_id, rows)
        return {"library": _lib_out(lib), "view": "shows", "shows": rows,
                "items": _with_progress(loose, u["id"])}
    if lib["kind"] == "music" and view not in ("tracks",):
        rows = db.rows(
            "SELECT COALESCE(album_artist, artist, 'Unknown artist') artist, COALESCE(album, 'Unknown album') album, "
            "MAX(year) year, COUNT(*) tracks, MAX(poster) poster, MAX(added_at) added_at, SUM(duration) duration "
            "FROM items WHERE library_id=? AND (title LIKE ? OR album LIKE ? OR artist LIKE ? OR album_artist LIKE ?) "
            "GROUP BY 1, 2 ORDER BY %s LIMIT ? OFFSET ?"
            % ("MAX(added_at) DESC" if sort == "added" else "1 COLLATE NOCASE, 2 COLLATE NOCASE"),
            (lib_id, like, like, like, like, limit, offset))
        return {"library": _lib_out(lib), "view": "albums", "albums": rows}
    order = SORTS.get(sort, SORTS["title"])
    cond = ("library_id=? AND (title LIKE ? OR artist LIKE ? OR show LIKE ? OR tmdb_id IN "
            "(SELECT tmdb_id FROM metadata WHERE kind='movie' AND title LIKE ?))")
    if filter == "review":
        cond += " AND " + REVIEW_COND
    elif filter == "nomatch":
        cond += " AND kind='movie' AND meta_status='nomatch'"
    elif filter == "edition":
        cond += " AND edition IS NOT NULL"
    args = [lib_id, like, like, like, like]
    if lib["kind"] == "movies" and view != "files":
        # 1.7: several files of one film (4K + 1080p ...) = one card, the highest resolution first
        cond += " AND " + titles.best_in_lib_cond("id")
        args.append(lib_id)
    csql, cargs = _cat_filters(genres, decade, collection, tag, cert)
    cond += csql
    args += cargs
    if collection and sort in ("poster", "title"):
        order = "COALESCE(" + (MOVIE_META % "md.release_date") + ", year), sort_title"   # a franchise in release order
    elif sort == "rating":
        order = "COALESCE(" + (MOVIE_META % "md.rating") + ", 0) DESC, sort_title COLLATE NOCASE"
    rows = db.rows("SELECT " + ITEM_COLS + ", " + REVIEW_COND + " AS needs_review, " + titles.key_sql() +
                   " AS title_key FROM items WHERE " + cond + " ORDER BY " + order + " LIMIT ? OFFSET ?", args + [limit, offset])
    total = db.row("SELECT COUNT(*) n FROM items WHERE " + cond, args)["n"]
    _mark_versions(lib_id, rows)
    out = {"library": _lib_out(lib), "view": "items", "items": _with_progress(rows, u["id"]), "total": total}
    if facets and lib["kind"] == "movies":
        out["facets"] = _facets(cond, args)
        if collection:
            out["collection"] = db.row("SELECT id, name, poster FROM collections WHERE id=?", (collection,))
        if tag:
            out["tag"] = db.row("SELECT id, name FROM tags WHERE id=?", (tag,))
    return out


def _mark_versions(lib_id, rows):
    """1.7: rows that are the best of several files get versions = n and vres = ['4K', '1080p', ...] (best first)."""
    if not rows:
        return rows
    vc = titles.version_counts(lib_id)
    for r in rows:
        k = r.pop("title_key", None)
        if k in vc:
            r["versions"] = len(vc[k])
            r["vres"] = [titles.RES_LABEL[x] for x in vc[k]]
    return rows


def _enrich_shows(lib_id, rows):
    for r in rows:
        try:
            m, _st = tmdb.show_meta(r.get("library_id") or lib_id, r["show"])
        except Exception:
            m = None
        if not m:
            continue
        has_local = db.row("SELECT 1 x FROM items WHERE library_id=? AND show=? AND poster IS NOT NULL AND poster<>thumb "
                           "LIMIT 1", (r.get("library_id") or lib_id, r["show"]))
        if m["poster"] and not has_local:
            r["poster"] = m["poster"]
        r["display_name"] = m["title"]
        if m["year"]:
            r["year"] = m["year"]
    return rows


@app.get("/api/show")
def show_detail(library_id: int, show: str, u=Depends(auth.require_user)):
    eps = db.rows("SELECT " + ITEM_COLS + ", " + titles.key_sql() + " AS title_key FROM items WHERE library_id=? AND show=? "
                  "ORDER BY season, episode, sort_title", (library_id, show))
    if not eps:
        raise HTTPException(404, "No such show")
    # 1.7: two files of one episode = one row (highest resolution), in the original order
    groups = {}
    for e in eps:
        groups.setdefault(e["title_key"], []).append(e)
    keep = []
    for e in eps:
        g = groups.get(e["title_key"])
        if g is None:
            continue
        g.sort(key=titles.version_sort_key)
        best = g[0]
        if len(g) > 1:
            best["versions"] = len(g)
            best["vres"] = [titles.RES_LABEL[titles.res_rank(x["width"], x["height"])] for x in g]
        keep.append(best)
        groups.pop(e["title_key"])
    eps = keep
    for e in eps:
        e.pop("title_key", None)
    eps = _with_progress(eps, u["id"])
    seasons = {}
    for e in eps:
        seasons.setdefault(e["season"] if e["season"] is not None else 0, []).append(e)
    local = db.row("SELECT poster FROM items WHERE library_id=? AND show=? AND poster IS NOT NULL AND poster<>thumb LIMIT 1",
                   (library_id, show))
    m, mstatus = tmdb.show_meta(library_id, show)
    poster = (local and local["poster"]) or (m and m["poster"]) or eps[0]["poster"]
    nxt = next((e for e in eps if not e["watched"]), eps[0])
    out = {"show": show, "library_id": library_id, "poster": poster,
           "year": (m and m["year"]) or min((e["year"] for e in eps if e["year"]), default=None),
           "seasons": [{"season": k, "episodes": v} for k, v in sorted(seasons.items())], "next": nxt,
           "match_status": mstatus, "tmdb": None, "tmdb_enabled": settings.tmdb_enabled()}
    if m:
        out["tmdb"] = {"id": m["tmdb_id"], "title": m["title"], "overview": m["overview"], "backdrop": m["backdrop"],
                       "genres": json.loads(m["genres"] or "[]"), "rating": m["rating"], "url": "https://www.themoviedb.org/tv/%d" % m["tmdb_id"]}
    return out


@app.get("/api/album")
def album_detail(library_id: int, artist: str, album: str, u=Depends(auth.require_user)):
    tracks = db.rows(
        "SELECT " + ITEM_COLS + " FROM items WHERE library_id=? AND COALESCE(album_artist, artist, 'Unknown artist')=? "
        "AND COALESCE(album, 'Unknown album')=? ORDER BY COALESCE(disc,1), COALESCE(track, 9999), sort_title",
        (library_id, artist, album))
    if not tracks:
        raise HTTPException(404, "No such album")
    return {"artist": artist, "album": album, "library_id": library_id,
            "poster": next((t["poster"] for t in tracks if t["poster"]), None),
            "year": max((t["year"] or 0 for t in tracks), default=None) or None,
            "duration": sum(t["duration"] or 0 for t in tracks), "tracks": tracks}


# 1.7.6: per-user playlists
def _playlist_item_cols():
    return ", ".join("i." + c.strip() for c in ITEM_COLS.split(","))


@app.get("/api/playlists")
def list_playlists(u=Depends(auth.require_user)):
    return playlists.list_for(u["id"])


@app.post("/api/playlists")
def create_playlist(body: dict = Body(...), u=Depends(auth.require_user)):
    ids = body.get("item_ids") or ([] if body.get("item_id") is None else [body.get("item_id")])
    return playlists.create(u["id"], body.get("name"), ids or None)


@app.get("/api/playlists/{pid}")
def playlist_detail(pid: int, u=Depends(auth.require_user)):
    return playlists.get(pid, u["id"], _playlist_item_cols())


@app.put("/api/playlists/{pid}")
def rename_playlist(pid: int, body: dict = Body(...), u=Depends(auth.require_user)):
    return playlists.rename(pid, u["id"], body.get("name"))


@app.delete("/api/playlists/{pid}")
def delete_playlist(pid: int, u=Depends(auth.require_user)):
    return playlists.delete(pid, u["id"])


@app.post("/api/playlists/{pid}/tracks")
def add_playlist_tracks(pid: int, body: dict = Body(...), u=Depends(auth.require_user)):
    ids = body.get("item_ids") or ([] if body.get("item_id") is None else [body.get("item_id")])
    return playlists.add_tracks(pid, u["id"], ids)


@app.delete("/api/playlists/{pid}/tracks/{entry_id}")
def remove_playlist_track(pid: int, entry_id: int, u=Depends(auth.require_user)):
    return playlists.remove_entry(pid, u["id"], entry_id)


@app.put("/api/playlists/{pid}/order")
def reorder_playlist(pid: int, body: dict = Body(...), u=Depends(auth.require_user)):
    return playlists.reorder(pid, u["id"], body.get("ids") or body.get("entry_ids") or [])


# 1.5.5: the home page (and so the Android app, which shows the same page) lists only Movies and TV Shows libraries in
# Continue watching and the Recently added rows -- music, home videos and "other" libraries stay in their own pages
HOME_KINDS = ("movies", "tv")
HOME_KINDS_SQL = "('movies','tv')"


def _dedupe(items, key_field=None):
    """1.7: one entry per title (versions and copies on other libraries), keeping the order; the entry shown is the
    best version from a library whose share is up (first in admin order)."""
    if not items:
        return items
    ids = [i["id"] for i in items]
    keys = {}
    for chunk in range(0, len(ids), 500):
        part = ids[chunk:chunk + 500]
        for r in db.rows("SELECT id, %s k FROM items WHERE id IN (%s)" % (titles.key_sql(), ",".join("?" * len(part))), part):
            keys[r["id"]] = r["k"]
    for i in items:
        i["title_key"] = keys.get(i["id"])
    # swap in a copy when the first one found is on a share that is down
    down = titles.lib_down()
    out = titles.collapse(items, down=down)
    if down:
        for n, i in enumerate(out):
            if down.get(i["library_id"]):
                tw = titles.online_twin(i["id"])
                if tw:
                    r = db.row("SELECT " + ITEM_COLS + " FROM items WHERE id=?", (tw,))
                    if r:
                        for k in ("position", "updated_at", "duration"):
                            if i.get(k) is not None and k != "duration":
                                r[k] = i[k]
                        out[n] = r
    for i in out:
        i.pop("title_key", None)
        i.pop("copies", None)
    return out


def _continue(u):
    cont = db.rows(
        "SELECT " + ", ".join("i." + c.strip() for c in ITEM_COLS.split(",")) + ", p.position, p.updated_at, p.duration pduration "
        "FROM progress p JOIN items i ON i.id=p.item_id JOIN libraries l ON l.id=i.library_id "
        "WHERE p.user_id=? AND p.watched=0 AND p.position>30 "
        "AND i.media_type='video' AND l.kind IN " + HOME_KINDS_SQL + " AND (COALESCE(p.duration, i.duration, 0) <= 0 OR "
        "p.position < 0.95 * COALESCE(p.duration, i.duration)) ORDER BY p.updated_at DESC LIMIT 80", (u["id"],))
    cont = _dedupe(cont)[:20]      # 1.7: progress is kept on every copy -- show each title once
    cont = _with_progress(cont, u["id"])
    for i in cont:   # the progress bar needs a length even when ffprobe could not read one
        i["duration"] = i.get("duration") or i.pop("pduration", None)
        i.pop("pduration", None)
    return cont


@app.get("/api/home")
def home(u=Depends(auth.require_user)):
    cont = _continue(u)
    libs = []
    # 1.7: libraries that hold the same titles (e.g. the same movies on two redundant shares) get ONE section,
    # from the first of them (admin order) whose share is up; the others are named under "mirrors"
    down = titles.lib_down()
    show_lib, mirrors = {}, {}
    for kind in HOME_KINDS:
        for g in titles.mirror_groups(kind):
            up = [l for l in g if not down.get(l)] or g
            show_lib[up[0]] = True
            mirrors[up[0]] = [l for l in g if l != up[0]]
    names = {r["id"]: r["name"] for r in db.rows("SELECT id, name FROM libraries")}
    for lib in db.rows("SELECT * FROM libraries " + liborder.ORDER_SQL):
        if lib["kind"] not in HOME_KINDS:      # 1.5.5: only movies and TV on the home page
            continue
        if not show_lib.get(lib["id"]):
            continue
        lib["mirrors"] = [names[m] for m in mirrors.get(lib["id"], [])]
        if lib["kind"] == "music":
            recent = db.rows(
                "SELECT COALESCE(album_artist, artist, 'Unknown artist') artist, COALESCE(album,'Unknown album') album, "
                "MAX(poster) poster, MAX(added_at) added_at, MAX(year) year FROM items WHERE library_id=? GROUP BY 1,2 "
                "ORDER BY MAX(added_at) DESC, 2 LIMIT 20", (lib["id"],))
            libs.append({"library": lib, "albums": recent})
        elif lib["kind"] == "tv":
            recent = db.rows("SELECT " + ITEM_COLS + " FROM items WHERE library_id=? AND " + titles.best_in_lib_cond("id") +
                             " ORDER BY added_at DESC, show, season DESC, episode DESC LIMIT 20", (lib["id"], lib["id"]))
            libs.append({"library": lib, "items": _with_progress(recent, u["id"])})
        else:
            # 1.2.1: among recent additions (last 7 days of this library's activity), artwork first
            recent = db.rows("SELECT " + ITEM_COLS + " FROM items WHERE library_id=? AND added_at >= "
                             "(SELECT COALESCE(MAX(added_at),0) - 7*86400 FROM items WHERE library_id=?) AND "
                             + titles.best_in_lib_cond("id") + " "
                             "ORDER BY " + HAS_ART + " DESC, added_at DESC, sort_title COLLATE NOCASE LIMIT 20",
                             (lib["id"], lib["id"], lib["id"]))
            entry = {"library": lib, "items": _with_progress(recent, u["id"])}
            # 1.4.1: Recommended / Recently released / Recently added / Top movies, in that order
            entry["smart_rows"] = []
            for key in ("recommended", "released", "added", "top"):
                try:
                    r = _smart_rows(lib["id"], key, u, 20) if key != "added" else \
                        {"key": "added", "title": homerows.ROWS["added"], "items": entry["items"], "note": ""}
                except Exception:   # a home row must never break the page
                    log.exception("home row %s", key)
                    continue
                entry["smart_rows"].append(r)
            # 1.4: a row for each of the library's biggest genres (best rated first, artwork first)
            rows = []
            for g in db.rows("SELECT g.genre, COUNT(DISTINCT i.tmdb_id) n FROM items i JOIN movie_genres g ON g.tmdb_id=i.tmdb_id "
                             "WHERE i.library_id=? AND i.kind='movie' GROUP BY g.genre ORDER BY n DESC LIMIT 6", (lib["id"],)):
                its = db.rows("SELECT " + ITEM_COLS + " FROM items WHERE library_id=? AND kind='movie' AND tmdb_id IN "
                              "(SELECT tmdb_id FROM movie_genres WHERE genre=?) AND " + titles.best_in_lib_cond("id") +
                              " ORDER BY " + HAS_ART + " DESC, COALESCE("
                              + (MOVIE_META % "md.rating") + ",0) DESC, sort_title COLLATE NOCASE LIMIT 20",
                              (lib["id"], g["genre"], lib["id"]))
                rows.append({"genre": g["genre"], "count": g["n"], "items": _with_progress(its, u["id"])})
            entry["genre_rows"] = rows
            libs.append(entry)
    try:
        tmdb.enrich(cont)
        for e in libs:
            tmdb.enrich(e.get("items") or [])
            for r in e.get("smart_rows") or []:
                tmdb.enrich(r.get("items") or [])
            for r in e.get("genre_rows") or []:
                tmdb.enrich(r.get("items") or [])
    except Exception:
        log.exception("home enrich")
    try:
        libs.extend(fed.home_sections(u))
    except Exception:
        log.exception("home remotes")
    return {"continue": cont, "libraries": libs}


@app.get("/api/mylist")
def mylist(u=Depends(auth.require_user)):
    """1.5.1: the phone's My List tab -- this user's films in progress and the ones watched most recently."""
    cont = _continue(u)
    watched = db.rows("SELECT " + ", ".join("i." + c.strip() for c in ITEM_COLS.split(",")) + " FROM progress p JOIN items i "
                      "ON i.id=p.item_id WHERE p.user_id=? AND p.watched=1 AND i.media_type='video' "
                      "ORDER BY p.updated_at DESC LIMIT 240", (u["id"],))
    return {"continue": cont, "watched": _with_progress(_dedupe(watched)[:60], u["id"])}


@app.get("/api/search")
def search(q: str, u=Depends(auth.require_user)):
    q = q.strip()
    if len(q) < 1:
        return {"items": [], "shows": [], "albums": []}
    like = "%" + q + "%"
    items = db.rows("SELECT " + ITEM_COLS + " FROM items WHERE kind IN ('movie','video') AND (title LIKE ? OR tmdb_id IN "
                    "(SELECT tmdb_id FROM metadata WHERE kind='movie' AND (title LIKE ? OR original_title LIKE ?))) "
                    "ORDER BY sort_title LIMIT 400", (like, like, like))
    items = _dedupe(items)[:60]          # 1.7: a film on two shares / in 4K and 1080p is one result
    eps = db.rows("SELECT " + ITEM_COLS + " FROM items WHERE kind='episode' AND (title LIKE ? OR episode_title LIKE ?) "
                  "ORDER BY show, season, episode LIMIT 200", (like, like))
    eps = _dedupe(eps)[:40]
    shows = db.rows("SELECT library_id, show, COUNT(*) episodes, MAX(poster) poster, MIN(year) year FROM items "
                    "WHERE kind='episode' AND (show LIKE ? OR (library_id, show) IN (SELECT sm.library_id, sm.show FROM show_matches sm "
                    "JOIN metadata m ON m.kind='tv' AND m.tmdb_id=sm.tmdb_id WHERE m.title LIKE ?)) "
                    "GROUP BY library_id, show ORDER BY show LIMIT 200", (like, like))
    shows = _dedupe_shows(shows)[:40]
    _enrich_shows(None, shows)
    albums = db.rows("SELECT library_id, COALESCE(album_artist, artist, 'Unknown artist') artist, "
                     "COALESCE(album,'Unknown album') album, MAX(poster) poster, MAX(year) year, COUNT(*) tracks FROM items "
                     "WHERE media_type='audio' AND (album LIKE ? OR artist LIKE ? OR album_artist LIKE ?) "
                     "GROUP BY 1,2,3 ORDER BY 2,3 LIMIT 200", (like, like, like))
    seen_al, al2 = set(), []
    for a in albums:                     # 1.7: the same album in two music libraries = one result
        k = (a["artist"].lower(), a["album"].lower())
        if k not in seen_al:
            seen_al.add(k)
            al2.append(a)
    albums = al2[:40]
    tracks = db.rows("SELECT " + ITEM_COLS + " FROM items WHERE media_type='audio' AND title LIKE ? ORDER BY sort_title LIMIT 40",
                     (like,))
    try:
        items = list(items) + fed.search_items(q, u)
    except Exception:
        log.exception("search remotes")
    return {"items": _with_progress(items, u["id"]), "episodes": _with_progress(eps, u["id"]), "shows": shows,
            "albums": albums, "tracks": tracks}


def _dedupe_shows(shows):
    """1.7: a show in two TV libraries (e.g. on two shares) once, from the first library (admin order) that is up."""
    down, order = titles.lib_down(), titles.lib_rank()
    best = {}
    for s in shows:
        k = (s["show"] or "").lower()
        cur = best.get(k)
        rank = (1 if down.get(s["library_id"]) else 0, order.get(s["library_id"], 999))
        if cur is None or rank < cur[0]:
            best[k] = (rank, s)
    seen, out = set(), []
    for s in shows:
        k = (s["show"] or "").lower()
        if k not in seen:
            seen.add(k)
            out.append(best[k][1])
    return out


def _get_item(item_id):
    if item_id < 0:
        it = fed.local_item(-item_id)
        if not it:
            raise HTTPException(404, "No such item")
        return it
    it = db.row("SELECT * FROM items WHERE id=?", (item_id,))
    if not it:
        raise HTTPException(404, "No such item")
    return it


BROWSER_V = {"h264", "vp8", "vp9", "av1"}
MAYBE_V = {"hevc"}                       # Safari / Edge / Chrome with hw support
BROWSER_A = {"aac", "mp3", "opus", "vorbis", "flac"}
MAYBE_A = {"ac3", "eac3", "alac", "pcm_s16le", "pcm_s24le"}
DIRECT_EXT_V = {".mp4", ".m4v", ".mov", ".webm", ".mkv"}
DIRECT_EXT_A = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wav", ".webm"}

MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
        ".mkv": "video/x-matroska", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
        ".flac": "audio/flac", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg", ".wav": "audio/wav",
        ".avi": "video/x-msvideo", ".ts": "video/mp2t", ".wmv": "video/x-ms-wmv"}


def playback_info(it, cap=None, client=None):
    ext = Path(it["path"]).suffix.lower()
    auds = json.loads(it["audio_streams"] or "[]")
    subs = json.loads(it["subtitle_streams"] or "[]")
    ext_subs = json.loads(it["external_subs"] or "[]")
    a0 = it["acodec"]
    native = bool(client and client.get("native"))
    if it["media_type"] == "audio":
        direct = ext in DIRECT_EXT_A and (a0 in BROWSER_A or a0 in ("pcm_s16le", "pcm_s24le", "alac")
                                          or (native and transcode.native_audio_ok(a0, client)))
        maybe = False
    elif native:
        # 2.4: the native ExoPlayer can Direct Play HEVC (Main / Main10), AV1, HDR, Matroska
        # and bitstream-passthrough AC3/EAC3/DTS/TrueHD when the client reported those caps.
        # 10-bit SDR (no HDR transfer) is still Direct Play when hevc10 is set.
        v_ok = transcode.native_video_ok(it, client)
        a_ok = (a0 is None) or transcode.native_audio_ok(a0, client)
        mkv_ok = ext != ".mkv" or client.get("mkv", True)
        hdr_ok = transcode.native_hdr_ok(it, client)
        direct = ext in DIRECT_EXT_V and v_ok and a_ok and mkv_ok and hdr_ok
        # If the panel didn't report this HDR mode, still offer a try — the TV may tone-map.
        maybe = ext in DIRECT_EXT_V and v_ok and a_ok and mkv_ok and not direct
        if not hdr_ok and ext in DIRECT_EXT_V and v_ok and a_ok and mkv_ok:
            maybe = True
    else:
        v_ok = it["vcodec"] in BROWSER_V and (it["vcodec"] != "h264" or (it["pix_fmt"] or "yuv420p") in ("yuv420p", "yuvj420p"))
        a_ok = (a0 is None) or a0 in BROWSER_A
        direct = ext in DIRECT_EXT_V and v_ok and a_ok
        maybe = ext in DIRECT_EXT_V and (it["vcodec"] in MAYBE_V or (it["vcodec"] in BROWSER_V and a0 in MAYBE_A))
    src_h = it["height"] or 0
    profiles = [p for p, (h, _, _) in transcode.PROFILES.items() if p != "audio" and p not in transcode.HIRES and (h <= max(src_h, 360))] or ["480p"]
    # 1.5.3: 2K / 4K (never above the source); only with hardware transcoding, else listed as unavailable
    hires, hires_off, hdr = [], None, ""
    if it["media_type"] == "video" and it["vcodec"]:
        big = [p for p in transcode.HIRES if transcode.hires_ok(it, p)]
        if big:
            if hwaccel.active()[0]:
                hires = big
            else:
                hires_off = {"profiles": big, "note": "2K and 4K need hardware transcoding (Settings > Transcoding)"}
        hdr = transcode.hdr_info(it)
    subtitle_tracks = []
    for i, s in enumerate(ext_subs):
        subtitle_tracks.append({"key": "e%d" % i, "label": s["label"] or "External", "lang": None,
                                "kind": "text", "burn": False})
    _img = {"hdmv_pgs_subtitle": "PGS", "pgssub": "PGS", "dvd_subtitle": "VobSub", "dvdsub": "VobSub",
            "dvb_subtitle": "DVB", "dvbsub": "DVB", "xsub": "XSUB"}
    for s in subs:
        label = s.get("title") or s.get("lang") or "Track %d" % s["index"]
        if s.get("text"):
            subtitle_tracks.append({"key": "s%d" % s["index"], "label": label, "lang": s.get("lang"),
                                    "kind": "text", "burn": False})
        else:
            kind = _img.get((s.get("codec") or "").lower(), "image")
            if kind not in label:
                label = "%s (%s)" % (label, kind)
            subtitle_tracks.append({"key": "s%d" % s["index"], "label": label, "lang": s.get("lang"),
                                    "kind": "image", "burn": True, "codec": s.get("codec")})
    eligible = it["media_type"] == "video" and transcode.remux_eligible(it)
    # 2.2: only advertise remux when a keyframe plan is already cached, so play does not
    # try remux, 409, then transcode.
    remux = eligible and transcode.remux_ready(it)
    remux_pending = eligible and not remux
    remux_codec = transcode.remux_codec(it) if eligible else ""
    # 1.7.8: hide qualities (and remux/direct of a larger file) above this device's cap
    src_fits = True
    if cap:
        profiles = [p for p in profiles if transcode.profile_rank(p) <= transcode.profile_rank(cap)] or ["360p"]
        hires = [p for p in hires if transcode.profile_rank(p) <= transcode.profile_rank(cap)]
        if hires_off:
            kept = [p for p in hires_off.get("profiles") or [] if transcode.profile_rank(p) <= transcode.profile_rank(cap)]
            hires_off = dict(hires_off, profiles=kept) if kept else None
        src_fits = transcode.source_fits_cap(it, cap)
        if not src_fits:
            remux, remux_pending, remux_codec, direct, maybe = False, False, "", False, False
    passthrough = []
    if native:
        for c, flag in (("ac3", "ac3"), ("eac3", "eac3"), ("dts", "dts"), ("truehd", "truehd")):
            if client.get(flag):
                passthrough.append(c)
    return {"direct": direct, "direct_maybe": maybe, "remux": remux, "remux_pending": remux_pending,
            "remux_codec": remux_codec,
            "mime": MIME.get(ext, "application/octet-stream"),
            "seg": transcode.SEG,
            "profiles": profiles, "hires": hires, "hires_off": hires_off, "hdr": hdr,
            "hdr_tonemap": hwaccel.hdr_tonemap_enabled(),
            "hdr_passthrough": bool(native and hdr and transcode.native_hdr_ok(it, client)),
            "hires_kbps": {p: {"h264": transcode.video_kbps(it, p), "hevc": transcode.video_kbps(it, p, True)} for p in hires},   # 1.5.4: real maxrate
            "audio_streams": auds, "subtitles": subtitle_tracks,
            "image_subs": [s for s in subs if not s.get("text")],
            "device_cap": cap, "source_fits_cap": src_fits,
            "native": native,
            "passthrough_audio": passthrough}



def _remote_item_detail(item_id, u):
    it = fed.local_item(-item_id, u)
    if not it:
        raise HTTPException(404, "No such item")
    out = dict(it)
    out["filename"] = None
    out["path"] = None
    out["folder"] = None
    out["tags"] = []
    out["pins"] = {}
    out["tmdb_enabled"] = settings.tmdb_enabled()
    out["playback"] = {"remote": True, "direct": False,
                       "src": "/api/items/%d/hls/1080p/index.m3u8" % item_id}
    out["library"] = fed._remote_lib_out(fed.get_remote_lib(it["library_id"], u))
    p = db.row("SELECT position, watched FROM progress WHERE user_id=? AND item_id=?", (u["id"], item_id))
    out["position"] = p["position"] if p else 0
    out["watched"] = bool(p["watched"]) if p else False
    out["next"] = None
    out["versions"] = []
    out["copies"] = 0
    out["similar"] = []
    return out


@app.get("/api/items/{item_id}")
def item_detail(item_id: int, request: Request, disp: int = 0, dec: int = 0, nocap: int = 0, u=Depends(auth.require_user)):
    if item_id < 0:
        return _remote_item_detail(item_id, u)
    it = _get_item(item_id)
    disp, dec, nocap_b = transcode.parse_cap_args(disp, dec, nocap)
    cap = None if nocap_b else transcode.device_cap_base(disp, dec)
    client = transcode.client_caps_from_params(request.query_params)
    out = {k: it[k] for k in it if k not in ("audio_streams", "subtitle_streams", "external_subs")}
    out["filename"] = os.path.basename(it["path"]) if u["is_admin"] else None   # 1.4.9: file details are admin-only
    out["tags"] = db.rows("SELECT t.id, t.name FROM item_tags x JOIN tags t ON t.id=x.tag_id WHERE x.item_id=? "
                          "ORDER BY t.name COLLATE NOCASE", (item_id,))
    out["pins"] = {r["row"]: r["mode"] for r in db.rows("SELECT row, mode FROM home_pins WHERE item_id=?", (item_id,))}
    out["folder"] = os.path.dirname(it["path"]) if u["is_admin"] else None
    if not u["is_admin"]:
        out.pop("path", None)
    out["playback"] = playback_info(it, cap=cap, client=client)
    try:
        tmdb.enrich([out])
    except Exception:
        log.exception("enrich")
    if it["kind"] == "movie":
        out["match_status"] = it.get("meta_status")
        out["match_confidence"] = it.get("meta_confidence")
        out["match_note"] = it.get("meta_note")
        if it.get("meta_candidate"):
            cm = tmdb.cached("movie", it["meta_candidate"])
            out["match_candidate"] = {"id": it["meta_candidate"], "title": cm and cm["title"], "year": cm and cm["year"],
                                      "url": "https://www.themoviedb.org/movie/%d" % it["meta_candidate"]}
        m0 = tmdb.cached("movie", it["tmdb_id"]) if it.get("tmdb_id") else None
        out["needs_review"] = bool(it.get("meta_status") == "review" or (
            it.get("meta_status") == "matched" and ((it.get("meta_confidence") or 1) < tmdb.REVIEW_BELOW or
                                                     (m0 and m0["year"] and it.get("year") and abs(m0["year"] - it["year"]) > 1))))
        if out.get("tmdb_id") and out.get("tmdb"):
            out["tmdb_url"] = "https://www.themoviedb.org/movie/%d" % out["tmdb_id"]
            m = tmdb.cached("movie", out["tmdb_id"])
            if m:
                out["runtime"] = m["runtime"]
                # 1.4.6: sharper poster for the big details-page poster (only when the poster shown is TMDB's)
                if m["poster_path"] and m["poster"] and out.get("poster") == m["poster"]:
                    # 1.7.1: ?v= the poster file so a new match is not hidden by the week-long
                    # browser cache of /api/items/{id}/poster-large (the path itself never changed).
                    out["poster_large"] = "/api/items/%d/poster-large?v=%s" % (item_id, m["poster"])
    elif it["kind"] == "episode":
        _m, out["match_status"] = tmdb.show_meta(it["library_id"], it["show"])
        if out.get("show_tmdb_id"):
            out["tmdb_url"] = "https://www.themoviedb.org/tv/%d/season/%s/episode/%s" % (
                out["show_tmdb_id"], it["season"], it["episode"])
    out["tmdb_enabled"] = settings.tmdb_enabled()
    p = db.row("SELECT position, watched FROM progress WHERE user_id=? AND item_id=?", (u["id"], item_id))
    out["position"] = p["position"] if p else 0
    out["watched"] = bool(p["watched"]) if p else False
    # neighbours for "next episode" / album autoplay
    nxt = None
    if it["kind"] == "episode":
        nxt = db.row("SELECT id, title, season, episode FROM items WHERE library_id=? AND show=? AND "
                     "(season > ? OR (season = ? AND episode > ?)) ORDER BY season, episode LIMIT 1",
                     (it["library_id"], it["show"], it["season"] or 0, it["season"] or 0, it["episode"] or 0))
    out["next"] = nxt
    try:
        from . import skipintro
        out["markers"] = skipintro.public_markers(item_id)
    except Exception:
        out["markers"] = {"intro_start": None, "intro_end": None, "credits_start": None, "status": "pending"}
    lib = db.row("SELECT id, name, kind FROM libraries WHERE id=?", (it["library_id"],))
    out["library"] = lib
    try:
        out.update(_versions(it, cap=cap, client=client))
    except Exception:   # never break the details page
        log.exception("versions")
    if it["kind"] == "movie":
        out.update(_movie_people(it))
        try:
            out["similar"] = _similar(it, u["id"])
        except Exception:   # similar movies are a nice-to-have
            log.exception("similar")
            out["similar"] = []
    return out


def _versions(it, cap=None, client=None):
    """1.7: {"versions": [this library's files of the title, best first], "copies": n other libraries,
    "fallback": id of a copy on a share that is up (only when this item's share is down)}."""
    ids = titles.same_title_ids(it["id"]) if it["kind"] in ("movie", "episode") else [it["id"]]
    down = titles.lib_down()
    out = {"versions": [], "copies": 0, "offline": bool(down.get(it["library_id"])), "fallback": None}
    if len(ids) <= 1:
        return out
    rows = db.rows("SELECT * FROM items WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
    mine = sorted([r for r in rows if r["library_id"] == it["library_id"]], key=titles.version_sort_key)
    out["copies"] = len({r["library_id"] for r in rows if r["library_id"] != it["library_id"]})
    if len(mine) > 1:
        for r in mine:
            pb = playback_info(r, cap=cap, client=client)
            out["versions"].append({
                "id": r["id"], "res": titles.RES_LABEL[titles.res_rank(r["width"], r["height"])],
                "width": r["width"], "height": r["height"], "vcodec": r["vcodec"], "acodec": r["acodec"],
                "bitrate": r["bitrate"], "size": r["size"], "container": r["container"],
                "playback": {"direct": pb["direct"], "direct_maybe": pb["direct_maybe"], "remux": pb["remux"],
                             "mime": pb["mime"], "hires": pb["hires"]}})
    if out["offline"]:
        out["fallback"] = titles.online_twin(it["id"])
        if out["fallback"]:
            fl = db.row("SELECT l.name FROM items i JOIN libraries l ON l.id=i.library_id WHERE i.id=?", (out["fallback"],))
            out["fallback_library"] = fl and fl["name"]
    return out


# 1.4.3: details page -- cast & crew, similar movies, an actor's movies ----------------------------------------
def _movie_people(it):
    tid = it.get("tmdb_id")
    if not tid or it.get("meta_status") not in ("matched", "manual", "review"):
        return {"cast": [], "directors": [], "writers": [], "credits_pending": False}
    cast = db.rows("SELECT p.id, p.name, c.character, (p.profile_path IS NOT NULL) has_photo FROM movie_cast c "
                   "JOIN people p ON p.id=c.person_id WHERE c.tmdb_id=? ORDER BY c.ord", (tid,))
    crew = db.rows("SELECT p.id, p.name, c.job FROM movie_crew c JOIN people p ON p.id=c.person_id WHERE c.tmdb_id=? "
                   "ORDER BY p.name", (tid,))
    m = db.row("SELECT cat_v FROM metadata WHERE kind='movie' AND tmdb_id=?", (tid,))
    for x in cast:
        x["has_photo"] = bool(x["has_photo"])
    seen = set()
    writers = [x for x in crew if x["job"] == "writer" and not (x["id"] in seen or seen.add(x["id"]))]
    return {"cast": cast, "directors": [x for x in crew if x["job"] == "director"], "writers": writers[:4],
            "credits_pending": bool(settings.tmdb_enabled() and (not m or (m["cat_v"] or 0) < tmdb.CAT_VERSION))}


SIMILAR_MAX = 20


def _similar(it, user_id):
    """Movies in the same library: TMDB recommendations first (both directions), then the same collection, then
    movies sharing the most genres (best rated first). One entry per TMDB movie; never the movie itself."""
    tid, lib = it.get("tmdb_id"), it["library_id"]
    lib_movies = {}
    for r in db.rows("SELECT id, tmdb_id FROM items WHERE library_id=? AND kind='movie' AND tmdb_id IS NOT NULL "
                     "AND meta_status IN ('matched','manual','review') ORDER BY " + titles.order_sql(), (lib,)):
        lib_movies.setdefault(r["tmdb_id"], r["id"])
    picked, reasons = [], {}

    def add(t, why):
        iid = lib_movies.get(t)
        if iid and t != tid and iid != it["id"] and iid not in reasons and len(picked) < SIMILAR_MAX:
            picked.append(iid)
            reasons[iid] = why
    if tid:
        for r in db.rows("SELECT rec_id t FROM movie_recs WHERE tmdb_id=? ORDER BY rank", (tid,)):
            add(r["t"], "TMDB recommends")
        for r in db.rows("SELECT tmdb_id t FROM movie_recs WHERE rec_id=? ORDER BY rank", (tid,)):
            add(r["t"], "TMDB recommends")
        m = db.row("SELECT collection_id, collection_name FROM metadata WHERE kind='movie' AND tmdb_id=?", (tid,))
        if m and m["collection_id"]:
            for r in db.rows("SELECT tmdb_id t FROM metadata WHERE kind='movie' AND collection_id=? ORDER BY year",
                             (m["collection_id"],)):
                add(r["t"], "Also in " + (m["collection_name"] or "the collection"))
        if len(picked) < SIMILAR_MAX:
            g = [r["genre"] for r in db.rows("SELECT genre FROM movie_genres WHERE tmdb_id=?", (tid,))]
            if g:
                need = 1 if len(g) == 1 else 2
                rows = db.rows(
                    "SELECT mg.tmdb_id t, COUNT(*) n, md.rating, md.vote_count FROM movie_genres mg "
                    "JOIN metadata md ON md.kind='movie' AND md.tmdb_id=mg.tmdb_id WHERE mg.genre IN (%s) AND mg.tmdb_id<>? "
                    "AND mg.tmdb_id IN (SELECT tmdb_id FROM items WHERE library_id=? AND kind='movie') "
                    "GROUP BY mg.tmdb_id ORDER BY n DESC, "
                    "(COALESCE(md.vote_count,0)*1.0/(COALESCE(md.vote_count,0)+500))*COALESCE(md.rating,0) DESC LIMIT 60"
                    % ",".join("?" * len(g)), g + [tid, lib])
                for r in rows:
                    if r["n"] >= need:
                        add(r["t"], "Similar genres")
                if len(picked) < 12:     # small libraries: one shared genre is better than an empty row
                    for r in rows:
                        if r["n"] < need:
                            add(r["t"], "Similar genres")
    if not picked:
        return []
    items = db.rows("SELECT " + ITEM_COLS + " FROM items WHERE id IN (%s)" % ",".join("?" * len(picked)), picked)
    items = _with_progress(items, user_id)
    order = {i: n for n, i in enumerate(picked)}
    items.sort(key=lambda x: order[x["id"]])
    for x in items:
        x["reason"] = reasons[x["id"]]
    return items


@app.get("/api/people/{person_id}/photo")
def person_photo(person_id: int, u=Depends(auth.require_user)):
    name = tmdb.person_photo(person_id) if settings.tmdb_enabled() else None
    if not name:
        raise HTTPException(404)
    return FileResponse(config.THUMB_DIR / name, media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=604800"})


@app.get("/api/people/{person_id}")
def person_detail(person_id: int, library_id: int = 0, u=Depends(auth.require_user)):
    """An actor / director and the movies in your library they are in."""
    p = db.row("SELECT id, name, (profile_path IS NOT NULL) has_photo FROM people WHERE id=?", (person_id,))
    if not p:
        raise HTTPException(404, "Unknown person")
    p["has_photo"] = bool(p["has_photo"])
    roles = {}
    for r in db.rows("SELECT tmdb_id, character FROM movie_cast WHERE person_id=?", (person_id,)):
        roles.setdefault(r["tmdb_id"], []).append(("as " + r["character"]) if r["character"] else "Actor")
    for r in db.rows("SELECT tmdb_id, job FROM movie_crew WHERE person_id=?", (person_id,)):
        roles.setdefault(r["tmdb_id"], []).append(r["job"].capitalize())
    if not roles:
        return {"person": p, "items": []}
    tids = list(roles)
    q = ("SELECT " + ITEM_COLS + " FROM items WHERE kind='movie' AND meta_status IN ('matched','manual','review') "
         "AND tmdb_id IN (%s)" % ",".join("?" * len(tids)))
    args = list(tids)
    if library_id:
        q += " AND library_id=?"
        args.append(library_id)
    items, seen = [], set()
    order, down = titles.lib_rank(), titles.lib_down()
    allx = db.rows(q, args)
    allx.sort(key=lambda x: (1 if down.get(x["library_id"]) else 0, order.get(x["library_id"], 999)) + titles.version_sort_key(x))
    for x in allx:      # 1.7: one card per film -- the best version, from a library that is up
        if x["tmdb_id"] in seen:
            continue
        seen.add(x["tmdb_id"])
        items.append(x)
    items = _with_progress(items, u["id"])
    for x in items:
        x["reason"] = ", ".join(dict.fromkeys(roles.get(x["tmdb_id"], [])))
    items.sort(key=lambda x: -(x.get("year") or 0))
    return {"person": p, "items": items}


@app.post("/api/items/{item_id}/progress")
def save_progress(item_id: int, body: dict = Body(...), u=Depends(auth.require_user)):
    it = _get_item(item_id)
    pos = float(body.get("position") or 0)
    dur = float(body.get("duration") or it["duration"] or 0)
    watched = 1 if (dur and pos / dur > 0.92) or body.get("ended") else 0
    if watched:
        pos = 0
    now = int(time.time())
    with db.tx() as c:
        # 1.7: the same position for every version and copy of the title (4K / 1080p, the other share)
        for iid in (titles.same_title_ids(item_id) or [item_id]):
            c.execute("INSERT INTO progress(user_id,item_id,position,duration,watched,updated_at) VALUES(?,?,?,?,?,?) "
                      "ON CONFLICT(user_id,item_id) DO UPDATE SET position=excluded.position, duration=excluded.duration, "
                      "watched=MAX(watched, excluded.watched), updated_at=excluded.updated_at",
                      (u["id"], iid, pos, dur, watched, now))
            if watched:
                c.execute("UPDATE progress SET position=0 WHERE user_id=? AND item_id=?", (u["id"], iid))
    return {"ok": True, "watched": bool(watched)}


@app.post("/api/items/{item_id}/watched")
def set_watched(item_id: int, body: dict = Body(...), u=Depends(auth.require_user)):
    _get_item(item_id)
    w = 1 if body.get("watched") else 0
    now = int(time.time())
    with db.tx() as c:
        for iid in (titles.same_title_ids(item_id) or [item_id]):     # 1.7: every version and copy
            c.execute("INSERT INTO progress(user_id,item_id,position,watched,updated_at) VALUES(?,?,0,?,?) "
                      "ON CONFLICT(user_id,item_id) DO UPDATE SET watched=excluded.watched, position=0, updated_at=excluded.updated_at",
                      (u["id"], iid, w, now))
    return {"ok": True}


# ---------------------------------------------------------------------------
# images + streaming
# ---------------------------------------------------------------------------
@app.get("/api/items/{item_id}/poster-large")
def item_poster_large(item_id: int, u=Depends(auth.require_user)):
    """1.4.6: w780 TMDB poster for the details page, fetched on first view and cached in data/thumbs."""
    it = _get_item(item_id)
    name = tmdb.large_poster("movie", it["tmdb_id"]) if it.get("tmdb_id") and it["kind"] == "movie" else None
    if not name or not (config.THUMB_DIR / name).is_file():
        raise HTTPException(404)
    return FileResponse(config.THUMB_DIR / name, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=604800"})


@app.get("/api/thumb/{name}")
def thumb(name: str, u=Depends(auth.require_user)):
    if not re.match(r"^[0-9a-f]{40}\.jpg$", name):
        raise HTTPException(404)
    p = config.THUMB_DIR / name
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=604800"})


def _range_response(path, request: Request, mime):
    try:
        size = os.path.getsize(path)
    except OSError:
        raise HTTPException(404, "File is not reachable (share offline?)")
    rng = request.headers.get("range")
    start, end = 0, size - 1
    status = 200
    if rng:
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        if not m:
            raise HTTPException(416)
        if m.group(1):
            start = int(m.group(1))
            if m.group(2):
                end = min(int(m.group(2)), size - 1)
        elif m.group(2):
            start = max(0, size - int(m.group(2)))
        if start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": "bytes */%d" % size})
        status = 206
    length = end - start + 1

    def gen():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(length), "Cache-Control": "private, no-transform"}
    if status == 206:
        headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)
    return StreamingResponse(gen(), status_code=status, media_type=mime, headers=headers)


@app.get("/api/items/{item_id}/file")
def direct_file(item_id: int, request: Request, download: int = 0, u=Depends(auth.require_user)):
    it = _get_item(item_id)
    ext = Path(it["path"]).suffix.lower()
    resp = _range_response(it["path"], request, MIME.get(ext) or mimetypes.guess_type(it["path"])[0]
                           or "application/octet-stream")
    if download:
        if not u["is_admin"]:    # 1.4.9: downloading is in the admin-only "..." menu; playback (no download=1) is unchanged
            raise HTTPException(403, "Only admins can download files")
        fn = os.path.basename(it["path"]).replace('"', "")
        resp.headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + __import__("urllib.parse").parse.quote(fn)
    return resp


def _profile_ok(profile):
    if not transcode.valid_profile(profile) and profile != "remux":
        raise HTTPException(400, "Unknown quality")
    if transcode.is_hires(profile) and not hwaccel.active()[0]:
        raise HTTPException(409, "2K and 4K need hardware transcoding")


def _player_query(audio, player, start=None, surr=0, burn=0, acopy=0):
    q = "?audio=%d" % audio
    if player:
        q += "&player=%s" % transcode.normalize_player(player)
    if start is not None:
        q += "&start=%d" % start
    if int(surr or 0) >= 6:
        q += "&surr=6"
    if int(burn or 0) > 0:
        q += "&burn=%d" % int(burn)
    if int(acopy or 0):
        q += "&acopy=1"
    return q


@app.get("/api/items/{item_id}/hls/{profile}/index.m3u8")
def hls_playlist(item_id: int, profile: str, request: Request, audio: int = 0, start: int = 0,
                 player: str = "", caps: str = "", hevc: str = "", hevc_mse: str = "",
                 hevc_el: str = "", mkv: str = "", ac3: str = "", eac3: str = "", hlsjs: str = "",
                 disp: int = 0, dec: int = 0, nocap: int = 0, surr: int = 0, burn: int = 0,
                 native: int = 0, acopy: int = 0, dts: str = "", truehd: str = "", hevc10: str = "",
                 u=Depends(auth.require_user)):
    if item_id < 0:
        info = fed.start_remote_play(u, item_id, profile, request)
        if info.get("proxy"):
            return RedirectResponse(info["src"], status_code=302)
        # Direct: a tiny playlist that points the player at the other server
        body = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=8000000\n%s\n" % info["src"]
        return PlainTextResponse(body, media_type="application/vnd.apple.mpegurl",
                                 headers={"Cache-Control": "private, no-store"})
    it = _get_item(item_id)
    if not os.path.exists(it["path"]):
        raise HTTPException(404, "File is not reachable (share offline?)")
    dpx, kpx, no_cap = transcode.parse_cap_args(disp, dec, nocap)
    new, device_cap, changed = transcode.clamp_profile(profile, it, dpx, kpx, no_cap)
    if new is None:
        raise HTTPException(409, "This file is larger than this device's quality cap; use a transcode quality")
    if changed:
        path = request.url.path.replace("/hls/%s/" % profile, "/hls/%s/" % new, 1)
        q = str(request.url.query or "")
        return RedirectResponse(path + (("?" + q) if q else ""), status_code=302)
    _profile_ok(profile)
    cap = caps or ("native=%s hevc=%s hevc10=%s hevc_mse=%s hevc_el=%s mkv=%s ac3=%s eac3=%s dts=%s truehd=%s hlsjs=%s disp=%s dec=%s acopy=%s" %
                   (native, hevc, hevc10, hevc_mse, hevc_el, mkv, ac3, eac3, dts, truehd, hlsjs, dpx or "", kpx or "", acopy)).strip()
    transcode.note_client(player, u, request, cap)
    if not acopy:
        cli = transcode.client_caps_from_params(request.query_params)
        if cli and cli.get("acopy"):
            acopy = 1
    bounds = None
    if profile == "remux":
        bounds = transcode.remux_bounds(it)
        if not bounds:
            raise HTTPException(409, "This file cannot be remuxed; use a transcode quality")
        if int(burn or 0) > 0:
            raise HTTPException(409, "Image subtitles need a transcode; remux cannot burn them in")
    need_init = transcode.split_profile(profile)[1] == "hevc" or (profile == "remux" and transcode.remux_codec(it) == "hevc")
    init = ("init.mp4" + _player_query(audio, player, max(0, start), surr, burn, acopy)) if need_init else None
    # 1.7.9: start ffmpeg as soon as the playlist is requested, so the first segment overlaps the player's next RTT
    if profile != "audio":
        try:
            s = transcode.get_session(it, profile, max(0, audio), u["id"], player, surr=surr, burn=burn, acopy=acopy)
            transcode.kickoff(s, max(0, start))
        except ValueError:
            pass
    return PlainTextResponse(transcode.playlist(it, _player_query(audio, player, surr=surr, burn=burn, acopy=acopy), bounds, init), media_type="application/vnd.apple.mpegurl",
                             headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


def _hls_session(item_id, profile, audio, u, player="", disp=0, dec=0, nocap=0, surr=0, burn=0, acopy=0):
    it = _get_item(item_id)
    dpx, kpx, no_cap = transcode.parse_cap_args(disp, dec, nocap)
    new, device_cap, changed = transcode.clamp_profile(profile, it, dpx, kpx, no_cap)
    if new is None:
        raise HTTPException(409, "This file is larger than this device's quality cap; use a transcode quality")
    profile = new
    _profile_ok(profile)
    try:
        return transcode.get_session(it, profile, max(0, audio), u["id"], player, surr=surr, burn=burn, acopy=acopy)
    except ValueError as e:
        raise HTTPException(409, "This file cannot be remuxed" if profile == "remux" else str(e))


@app.get("/api/items/{item_id}/hls/{profile}/init.mp4")
def hls_init(item_id: int, profile: str, audio: int = 0, start: int = 0, player: str = "",
             disp: int = 0, dec: int = 0, nocap: int = 0, surr: int = 0, burn: int = 0,
             acopy: int = 0, u=Depends(auth.require_user)):
    """1.5.3: init segment of an HEVC (fMP4) stream (transcode or HEVC remux)."""
    it = _get_item(item_id)
    if transcode.split_profile(profile)[1] != "hevc" and not (profile == "remux" and transcode.remux_codec(it) == "hevc"):
        raise HTTPException(404)
    s = _hls_session(item_id, profile, audio, u, player, disp, dec, nocap, surr, burn, acopy)
    p = s.get_init(max(0, start))
    if not p:
        raise HTTPException(500, "Transcode failed" + (": " + s.failed if s.failed else ""))
    return Response(p.read_bytes(), media_type="video/mp4", headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/api/items/{item_id}/hls/{profile}/seg{n}.m4s")
def hls_segment_m4s(item_id: int, profile: str, n: int, audio: int = 0, player: str = "",
                    disp: int = 0, dec: int = 0, nocap: int = 0, surr: int = 0, burn: int = 0,
                    acopy: int = 0, u=Depends(auth.require_user)):
    it = _get_item(item_id)
    if transcode.split_profile(profile)[1] != "hevc" and not (profile == "remux" and transcode.remux_codec(it) == "hevc"):
        raise HTTPException(404)
    return hls_segment(item_id, profile, n, audio, u, player, disp, dec, nocap, surr, burn, acopy)


@app.get("/api/items/{item_id}/hls/{profile}/seg{n}.ts")
def hls_segment(item_id: int, profile: str, n: int, audio: int = 0, u=Depends(auth.require_user),
                player: str = "", disp: int = 0, dec: int = 0, nocap: int = 0, surr: int = 0, burn: int = 0):
    s = _hls_session(item_id, profile, audio, u, player, disp, dec, nocap, surr, burn, acopy)
    if n < 0 or n >= s.nseg:
        raise HTTPException(404)
    p = s.get_segment(n)
    if not p:
        raise HTTPException(500, "Transcode failed; see %s" % (s.dir / "ffmpeg.log"))
    try:
        data = p.read_bytes()
    except FileNotFoundError:
        raise HTTPException(503, "Segment expired, retry")
    return Response(data, media_type="video/iso.segment" if s.hevc else "video/mp2t", headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.post("/api/items/{item_id}/stop")
def stop_stream(item_id: int, player: str = "", u=Depends(auth.require_user)):
    pid = transcode.normalize_player(player)
    for s in list(transcode._sessions.values()):
        if s.item["id"] == item_id and getattr(s, "user_id", None) == u["id"]:
            if pid and getattr(s, "player_id", "") != pid:
                continue
            transcode.stop_session(s.sid, "client_close")
    return {"ok": True}


@app.get("/api/items/{item_id}/subs/{key}.vtt")
def subtitles(item_id: int, key: str, u=Depends(auth.require_user)):
    """1.7.9: serve a cached VTT when we have one. Otherwise enqueue a low-priority extract
    and return 202 so this request never races the first video encode on the NAS."""
    it = _get_item(item_id)
    if not re.match(r"^[es]\d+$", key):
        raise HTTPException(404)
    if key.startswith("e"):
        ext_subs = json.loads(it["external_subs"] or "[]")
        if int(key[1:]) >= len(ext_subs):
            raise HTTPException(404)
    hit = preload.sub_get(it, key)
    if hit:
        return Response(hit.read_bytes(), media_type="text/vtt",
                        headers={"Cache-Control": "private, max-age=86400"})
    # Extract now only when it will not race a just-started video encode on the same NAS.
    if (not preload.busy()) or preload.first_segment_ready(it["id"]):
        preload.extract_sub(it, key)
        hit = preload.sub_get(it, key)
        if hit:
            return Response(hit.read_bytes(), media_type="text/vtt",
                            headers={"Cache-Control": "private, max-age=86400"})
        raise HTTPException(500, "Could not convert subtitles")
    preload.sub_enqueue(it, key, urgent=True)
    return Response(b"", status_code=202, media_type="text/vtt",
                    headers={"Retry-After": "1", "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


# ---------------------------------------------------------------------------
# settings + TMDB metadata (admin)
# ---------------------------------------------------------------------------
def _mask(key):
    if not key:
        return ""
    return key[:4] + "..." + key[-4:] if len(key) > 12 else "set"



@app.get("/api/items/{item_id}/markers")
def item_markers(item_id: int, u=Depends(auth.require_user)):
    _get_item(item_id)
    from . import skipintro
    return skipintro.public_markers(item_id)


@app.get("/api/items/{item_id}/trickplay")
def trickplay_info(item_id: int, u=Depends(auth.require_user)):
    """2.2: sprite-sheet metadata for the seek bar. Empty/pending until the idle job finishes."""
    it = _get_item(item_id)
    info = trickplay.public_info(it)
    if not info:
        return {"status": "pending", "interval": trickplay.INTERVAL, "count": 0, "sheets": [],
                "width": trickplay.THUMB_W, "height": 90, "columns": trickplay.COLS, "rows": trickplay.ROWS}
    return info


@app.get("/api/items/{item_id}/trickplay/sheet{n}.jpg")
def trickplay_sheet(item_id: int, n: int, u=Depends(auth.require_user)):
    it = _get_item(item_id)
    path = trickplay.sheet_path(item_id, n)
    if not path:
        raise HTTPException(404, "No trickplay sheet")
    trickplay.public_info(it, touch=True)
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/settings")
def get_settings(u=Depends(auth.require_admin)):
    db_key = settings.get("tmdb_key") or ""
    prefetch = preload.cache_stats()
    tp = trickplay.cache_stats()
    return {"tmdb_key_set": bool(settings.tmdb_key()), "tmdb_key_masked": _mask(settings.tmdb_key()),
            "tmdb_key_source": "settings" if db_key else ("env" if config.TMDB_KEY else None),
            "tmdb_language": settings.tmdb_language(), "tmdb_enabled": settings.get("tmdb_enabled", "1") != "0",
            "status_all_users": settings.get("status_all_users", "0") == "1",
            "prefetch_cache_gb": prefetch["gb"], "prefetch_cache_clips": prefetch["clips"],
            "prefetch_cache_bytes": prefetch["bytes"],
            "hdr_tonemap": settings.get("hdr_tonemap", "0") == "1",
            "trickplay_cache_gb": tp["gb"], "trickplay_cache_titles": tp["titles"],
            "trickplay_cache_bytes": tp["bytes"]}


@app.put("/api/settings")
def put_settings(body: dict = Body(...), u=Depends(auth.require_admin)):
    changed_key = False
    if "tmdb_key" in body:
        key = (body.get("tmdb_key") or "").strip()
        if key and not re.match(r"^[A-Za-z0-9._-]{16,1024}$", key):
            raise HTTPException(400, "That does not look like a TMDB API key or read access token")
        if key:
            ok, msg = tmdb.test_key(key)
            if not ok:
                raise HTTPException(400, msg)
        settings.put("tmdb_key", key)
        changed_key = True
    if "tmdb_language" in body:
        lang = (body.get("tmdb_language") or "").strip()
        if lang and not re.match(r"^[a-z]{2}(-[A-Z]{2})?$", lang):
            raise HTTPException(400, "Language looks like en-US")
        settings.put("tmdb_language", lang)
    if "tmdb_enabled" in body:
        settings.put("tmdb_enabled", "1" if body.get("tmdb_enabled") else "0")
    if "status_all_users" in body:
        settings.put("status_all_users", "1" if body.get("status_all_users") else "0")
    if "prefetch_cache_gb" in body:
        try:
            preload.set_cache_gb(body.get("prefetch_cache_gb"))
        except (TypeError, ValueError) as e:
            raise HTTPException(400, str(e))
    if "hdr_tonemap" in body:
        settings.put("hdr_tonemap", "1" if body.get("hdr_tonemap") else "0")
    if "trickplay_cache_gb" in body:
        try:
            trickplay.set_cache_gb(body.get("trickplay_cache_gb"))
        except (TypeError, ValueError) as e:
            raise HTTPException(400, str(e))
    keys_changed = sorted(body.keys())
    if keys_changed:
        useractivity.record("settings_changed", user=u, detail={"keys": keys_changed[:20]})   # names only, never values
    if changed_key or body.get("tmdb_enabled"):
        for lib in db.rows("SELECT id FROM libraries WHERE kind IN ('movies','tv')"):
            tmdb.queue_library(lib["id"])
    return get_settings(u)


@app.post("/api/settings/tmdb-test")
def tmdb_test(body: dict = Body(default={}), u=Depends(auth.require_admin)):
    ok, msg = tmdb.test_key((body.get("tmdb_key") or "").strip() or settings.tmdb_key())
    return {"ok": ok, "message": msg}


def _need_tmdb():
    if not settings.tmdb_enabled():
        raise HTTPException(400, "Set a TMDB API key in Settings -> Metadata first")


@app.get("/api/tmdb/search")
def tmdb_search(kind: str, q: str, year: int = 0, u=Depends(auth.require_admin)):
    _need_tmdb()
    if not q.strip():
        return []
    try:
        res = tmdb.search("movie" if kind == "movie" else "tv", q.strip(), year or None)
    except tmdb.TMDBError as e:
        raise HTTPException(502, str(e))
    out = []
    for r in res[:12]:
        out.append({"id": r.get("id"), "title": r.get("title") or r.get("name"),
                    "original_title": r.get("original_title") or r.get("original_name"),
                    "year": tmdb._year_of(r.get("release_date") or r.get("first_air_date")),
                    "overview": (r.get("overview") or "")[:300],
                    "poster_url": tmdb.image_url(r.get("poster_path"), "w92")})
    return out


@app.post("/api/items/{item_id}/match")
def match_item(item_id: int, body: dict = Body(...), u=Depends(auth.require_admin)):
    """body: {"tmdb_id": 603} to set a match, {"unmatch": true} to use file names, {"auto": true} to re-match."""
    it = _get_item(item_id)
    if it["kind"] == "episode":
        return match_show({"library_id": it["library_id"], "show": it["show"], **body}, u)
    if it["kind"] != "movie":
        raise HTTPException(400, "Only movies and TV shows can be matched")
    # 1.7.1: the 4K, the 1080p and the copy on the other share all follow this match
    ids = titles.movie_match_ids(item_id)
    try:      # 1.7.3: re-read the folder .nfo so a poster saved for an old match can be set aside
        folderart.refresh(ids)
    except Exception:
        log.exception("folder art")
    try:
        if body.get("unmatch"):
            tmdb.apply_movie_match(ids, None, "unmatched")
        elif body.get("auto"):
            _need_tmdb()
            r = tmdb.match_movie(it["title"], it["year"])
            if not tmdb.apply_match_result(ids, r):
                return {"ok": True, "matched": False, "status": r["status"], "note": r["note"]}
            tmdb.after_match_items(ids)
        elif body.get("accept_candidate"):
            _need_tmdb()
            if not it.get("meta_candidate"):
                raise HTTPException(400, "No suggestion to accept")
            tmdb.fetch_details("movie", it["meta_candidate"], force=True)
            tmdb.apply_movie_match(ids, it["meta_candidate"], "manual")
            tmdb.after_match_items(ids)
        else:
            _need_tmdb()
            tid = int(body.get("tmdb_id") or 0)
            if tid <= 0:
                raise HTTPException(400, "tmdb_id required")
            tmdb.fetch_details("movie", tid, force=True)
            tmdb.apply_movie_match(ids, tid, "manual")
            tmdb.after_match_items(ids)
    except tmdb.TMDBError as e:
        raise HTTPException(502, str(e))
    return {"ok": True, "matched": not body.get("unmatch")}


@app.post("/api/show/match")
def match_show(body: dict = Body(...), u=Depends(auth.require_admin)):
    lib_id, show = int(body.get("library_id") or 0), body.get("show") or ""
    if not db.row("SELECT 1 x FROM items WHERE library_id=? AND show=? LIMIT 1", (lib_id, show)):
        raise HTTPException(404, "No such show")
    try:
        if body.get("unmatch"):
            tmdb.apply_show_match(lib_id, show, None, "unmatched")
        else:
            _need_tmdb()
            if body.get("auto"):
                with db.tx() as c:
                    c.execute("DELETE FROM show_matches WHERE library_id=? AND show=?", (lib_id, show))
                tmdb.queue_library(lib_id, force=False)
                return {"ok": True, "queued": True}
            tid = int(body.get("tmdb_id") or 0)
            if tid <= 0:
                raise HTTPException(400, "tmdb_id required")
            tmdb.fetch_details("tv", tid, force=True)
            tmdb.apply_show_match(lib_id, show, tid, "manual")
            tmdb.match_show_seasons(lib_id, show, tid, force=True)
            tmdb._after_match(lib_id, [r["id"] for r in db.rows("SELECT id FROM items WHERE library_id=? AND show=?", (lib_id, show))])   # 1.5.5
    except tmdb.TMDBError as e:
        raise HTTPException(502, str(e))
    return {"ok": True}


@app.post("/api/libraries/{lib_id}/match-metadata")
def match_metadata(lib_id: int, u=Depends(auth.require_admin)):
    """Look up only what is missing (no re-download of what is already matched)."""
    _need_tmdb()
    if not db.row("SELECT id FROM libraries WHERE id=?", (lib_id,)):
        raise HTTPException(404, "No such library")
    return {"queued": tmdb.queue_library(lib_id, force=False)}


@app.post("/api/libraries/{lib_id}/refresh-metadata")
def refresh_metadata(lib_id: int, u=Depends(auth.require_admin)):
    _need_tmdb()
    if not db.row("SELECT id FROM libraries WHERE id=?", (lib_id,)):
        raise HTTPException(404, "No such library")
    return {"queued": tmdb.queue_library(lib_id, force=True)}


# ---------------------------------------------------------------------------
# 1.5.2: hardware transcoding (admin)
# ---------------------------------------------------------------------------
@app.get("/api/hw")
def hw_state(u=Depends(auth.require_admin)):
    st = hwaccel.state()
    st["streams"] = [t for t in transcode.list_sessions() if t.get("running")]
    st["max_transcodes"] = transcode.max_transcodes()
    return st


def _save_max_transcodes(raw):
    if raw is None or raw == "":
        return
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(400, "Max transcodes must be a number from 1 to 32")
    if not 1 <= n <= 32:
        raise HTTPException(400, "Max transcodes must be a number from 1 to 32")
    settings.put("max_transcodes", str(n))


@app.put("/api/hw")
def hw_save(body: dict = Body(...), u=Depends(auth.require_admin)):
    try:
        if body.get("mode") is not None or body.get("device") is not None:
            hwaccel.save((body.get("mode") or "").strip(), (body.get("device") or "").strip())
        if "max_transcodes" in body:
            _save_max_transcodes(body.get("max_transcodes"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    log.info("hardware transcoding set to %s %s by %s (max_transcodes=%s)",
             body.get("mode"), body.get("device") or "", u["username"], transcode.max_transcodes())
    return hw_state(u)


@app.post("/api/hw/test")
def hw_test(body: dict = Body(...), u=Depends(auth.require_admin)):
    method = (body.get("method") or "").strip()
    device = (body.get("device") or "").strip()
    if method not in hwaccel.ENCODER:
        raise HTTPException(400, "Pick VAAPI, Intel QSV or NVIDIA NVENC to test")
    if method != "nvenc" and not re.match(r"^/.*?/dri/renderD\d+$", device):
        raise HTTPException(400, "Pick the video card to test")
    if method == "nvenc" and not device:
        device = "nvidia"
    r = hwaccel.test(method, device)
    r["name"] = hwaccel.card_name(device)
    return r


@app.post("/api/hw/scan")
def hw_scan(u=Depends(auth.require_admin)):
    hwaccel.rescan()
    return hw_state(u)


# ---------------------------------------------------------------------------
# system (admin)
# ---------------------------------------------------------------------------
@app.get("/api/system")
def system_info(u=Depends(auth.require_admin)):
    try:
        ff = subprocess.run([config.FFMPEG, "-version"], capture_output=True, timeout=10).stdout.decode().splitlines()[0]
    except Exception:
        ff = "ffmpeg NOT FOUND"
    du = shutil.disk_usage(str(config.DATA_DIR))
    return {"version": __version__, "ffmpeg": ff, "data_dir": str(config.DATA_DIR),
            "data_disk_free_gb": round(du.free / 1e9, 1),
            "items": db.row("SELECT COUNT(*) n FROM items")["n"],
            "libraries": db.row("SELECT COUNT(*) n FROM libraries")["n"],
            "transcodes": transcode.list_sessions(), "mount_helper": shares.helper_available(),
            "tmdb": {"enabled": settings.tmdb_enabled(), "stats": tmdb.stats}}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
@app.middleware("http")
async def _asset_cache_headers(request: Request, call_next):
    """1.7.2: current app.js / style.css may be cached for a year (the URL already has ?v=the version).
    A request with no version, or an old one, is never stored, so a phone that still asks for
    app.js?v=1.6 will revalidate and receive this release's file."""
    resp = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") and path.endswith(
            (".js", ".css", ".webmanifest", ".png", ".svg", ".ico", ".jpg", ".jpeg", ".webp")):
        if request.query_params.get("v") == __version__:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"
    elif path.startswith("/api/"):
        # 1.7.9: playback and API are never cached (thumbs already set their own private max-age)
        if "Cache-Control" not in resp.headers:
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"
    return resp



# ---- 2.1 library sharing (federation) ---------------------------------------
def _base_url(request: Request) -> str:
    # Prefer the public origin the client used (trusting the already-configured proxy headers).
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return "%s://%s" % (proto, host)


@app.get("/api/fed/hello")
def fed_hello(c: str = ""):
    return fed.hello_public(c)


@app.post("/api/fed/pair")
async def fed_pair(request: Request):
    raw = await request.body()
    try:
        body = json.loads(raw.decode() or "{}")
    except Exception:
        raise HTTPException(400, "Bad JSON")
    request.state._fed_body = raw
    return fed.pair_incoming(request, body)


@app.get("/api/fed/libraries")
async def fed_libraries(request: Request):
    peer, _hid, _pub = fed.verify_signed(request, b"", require_peer=True)
    return fed.fed_libraries(peer)


@app.get("/api/fed/libraries/{lib_id}/items")
async def fed_lib_items(lib_id: int, request: Request, since: int = 0, offset: int = 0, limit: int = 200):
    peer, _hid, _pub = fed.verify_signed(request, b"", require_peer=True)
    return fed.fed_library_items(peer, lib_id, since=since, offset=offset, limit=limit)


@app.get("/api/fed/items/{item_id}")
async def fed_item(item_id: int, request: Request):
    peer, _hid, _pub = fed.verify_signed(request, b"", require_peer=True)
    return fed.fed_item(peer, item_id)


@app.get("/api/fed/thumb/{name}")
async def fed_thumb(name: str, request: Request):
    peer, _hid, _pub = fed.verify_signed(request, b"", require_peer=True)
    return fed.fed_thumb(peer, name)


@app.post("/api/fed/tickets")
async def fed_tickets(request: Request):
    raw = await request.body()
    try:
        body = json.loads(raw.decode() or "{}")
    except Exception:
        raise HTTPException(400, "Bad JSON")
    peer, _hid, _pub = fed.verify_signed(request, raw, require_peer=True)
    return fed.issue_ticket(peer, body)


@app.options("/api/fed/play/{ticket}/{name:path}")
def fed_play_options(ticket: str, name: str, request: Request):
    return fed.cors_preflight(request)


@app.get("/api/fed/play/{ticket}/index.m3u8")
def fed_play_index(ticket: str, request: Request):
    return fed.play_index(ticket, request)


@app.get("/api/fed/play/{ticket}/{name:path}")
def fed_play_part(ticket: str, name: str, request: Request):
    return fed.play_part(ticket, name, request)


@app.post("/api/fed/leave")
async def fed_leave(request: Request):
    raw = await request.body()
    peer, _hid, _pub = fed.verify_signed(request, raw, require_peer=True)
    return fed.leave_incoming(peer)


@app.get("/api/sharing")
def sharing_overview(u=Depends(auth.require_admin)):
    return {
        "me": fed.identity_payload(),
        "peers": fed.list_peers(),
        "codes": fed.list_codes(),
        "remote": fed.list_remote_libraries(),
        "libraries": [{"id": l["id"], "name": l["name"], "kind": l["kind"]}
                      for l in db.rows("SELECT id, name, kind FROM libraries " + liborder.ORDER_SQL)],
    }


@app.put("/api/sharing/name")
def sharing_name(body: dict = Body(...), u=Depends(auth.require_admin)):
    return fed.set_server_name(u, body.get("name") or "")


@app.post("/api/sharing/codes")
def sharing_create_code(request: Request, body: dict = Body(...), u=Depends(auth.require_admin)):
    return fed.create_share_code(u, body, _base_url(request))


@app.get("/api/sharing/codes")
def sharing_list_codes(u=Depends(auth.require_admin)):
    return fed.list_codes()


@app.delete("/api/sharing/codes/{code_id}")
def sharing_revoke_code(code_id: int, u=Depends(auth.require_admin)):
    return fed.revoke_code(code_id, u)


@app.post("/api/sharing/accept")
def sharing_accept(body: dict = Body(...), u=Depends(auth.require_admin)):
    return fed.accept_share(u, body)


@app.get("/api/sharing/peers")
def sharing_peers(u=Depends(auth.require_admin)):
    return fed.list_peers()


@app.post("/api/sharing/peers/{peer_id}/stop")
def sharing_stop(peer_id: int, body: dict = Body(None), u=Depends(auth.require_admin)):
    return fed.stop_sharing(u, peer_id, (body or {}).get("library_id"))


@app.put("/api/sharing/peers/{peer_id}/grants")
def sharing_grants(peer_id: int, body: dict = Body(...), u=Depends(auth.require_admin)):
    return fed.set_grants(u, peer_id, body.get("grants") or [])


@app.put("/api/sharing/peers/{peer_id}/proxy")
def sharing_proxy(peer_id: int, body: dict = Body(...), u=Depends(auth.require_admin)):
    return fed.set_proxy(u, peer_id, bool(body.get("proxy")))


@app.delete("/api/sharing/remote/{lib_id}")
def sharing_remove_remote(lib_id: int, u=Depends(auth.require_admin)):
    return fed.remove_remote(u, lib_id)


@app.put("/api/sharing/remote/{lib_id}/visible")
def sharing_visible(lib_id: int, body: dict = Body(...), u=Depends(auth.require_admin)):
    return fed.set_visible(u, lib_id, body.get("users"))


@app.post("/api/sharing/remote/{lib_id}/sync")
def sharing_sync(lib_id: int, u=Depends(auth.require_admin)):
    rl = fed.get_remote_lib(lib_id, u)
    if not rl:
        raise HTTPException(404, "No such shared library")
    fed.sync_peer(rl["peer_id"])
    return {"ok": True, "library": fed._remote_lib_out(fed.get_remote_lib(lib_id, u))}


@app.post("/api/sharing/play")
def sharing_play(request: Request, body: dict = Body(...), u=Depends(auth.require_user)):
    return fed.start_remote_play(u, int(body.get("item_id") or 0), body.get("profile") or "1080p", request, _base_url(request))


@app.get("/api/sharing/proxy/{ticket}/index.m3u8")
def sharing_proxy_index(ticket: str, request: Request, u=Depends(auth.require_user)):
    return fed.proxy_part(ticket, "index.m3u8", request)


@app.get("/api/sharing/proxy/{ticket}/{name:path}")
def sharing_proxy_part(ticket: str, name: str, request: Request, u=Depends(auth.require_user)):
    return fed.proxy_part(ticket, name, request)


@app.get("/api/logo/{name}")
def logo_file(name: str, u=Depends(auth.require_user)):
    """Optional typographic / studio logo for the TV hero (sha1-named PNG in data/logos)."""
    if not re.match(r"^[0-9a-f]{40}\.(png|svg|webp)$", name or ""):
        raise HTTPException(404)
    path = config.DATA_DIR / "logos" / name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(str(path), media_type="image/png" if name.endswith(".png") else "image/svg+xml")



app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache", "Expires": "0"}


def _index_response():
    """index.html with every /static/...?v= stamped with the running version, so a browser or the Android
    WebView can never keep old JS/CSS after an update. The page itself is never stored (no-store), a
    service worker (1.7.2) fetches this page and the JS/CSS from the network, and a meta tag + MS_VERSION
    let a client see the running version."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = re.sub(r'(/static/[A-Za-z0-9_./-]+\.(?:js|css|png|svg|ico|webmanifest|jpg|jpeg|webp))(\?v=[0-9A-Za-z._-]*)?"',
                  r'\1?v=%s"' % __version__, html)
    boot = ('<meta name="movinite-version" content="%s">\n'
            '<script>window.MS_VERSION=%r;'
            'if("serviceWorker"in navigator){navigator.serviceWorker.register("/sw.js?v=%s")}</script>\n'
            % (__version__, __version__, __version__))
    html = html.replace("</head>", boot + "</head>", 1)
    return HTMLResponse(html, headers=dict(NO_STORE))


@app.get("/sw.js")
def service_worker():
    """1.7.9: precache versioned app assets (long-cache URLs). HTML, API and HLS always come from the network.
    no-store on this file so the next version is picked up as soon as the page loads."""
    assets = [
        "/static/app.js?v=%s" % __version__,
        "/static/style.css?v=%s" % __version__,
        "/static/hls.min.js?v=%s" % __version__,
        "/static/qr.js?v=%s" % __version__,
        "/static/logo-bar.png?v=%s" % __version__,
        "/static/logo-mark.png?v=%s" % __version__,
        "/static/manifest.webmanifest?v=%s" % __version__,
        "/static/icon-192.png?v=%s" % __version__,
        "/static/favicon-32.png?v=%s" % __version__,
        "/static/tv-plex.css?v=%s" % __version__,
        "/static/tv-plex.js?v=%s" % __version__,
    ]
    body = (
        "const V=%r;\n"
        "const ASSETS=%s;\n"
        "const CACHE='movinite-'+V;\n"
        "self.addEventListener('install',e=>{\n"
        "  e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting()).catch(()=>self.skipWaiting()));\n"
        "});\n"
        "self.addEventListener('activate',e=>{\n"
        "  e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));\n"
        "});\n"
        "self.addEventListener('fetch',e=>{\n"
        "  const u=new URL(e.request.url);\n"
        "  if(u.origin!==location.origin) return;\n"
        "  if(u.pathname.startsWith('/api/')||u.pathname==='/sw.js'||e.request.mode==='navigate'||u.pathname==='/'){\n"
        "    e.respondWith(fetch(e.request,{cache:'no-store'}));\n"
        "    return;\n"
        "  }\n"
        "  if(u.pathname.startsWith('/static/')){\n"
        "    e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request).then(resp=>{\n"
        "      if(resp.ok && u.searchParams.get('v')===V){const c=resp.clone(); caches.open(CACHE).then(x=>x.put(e.request,c));}\n"
        "      return resp;\n"
        "    })));\n"
        "  }\n"
        "});\n"
    ) % (__version__, json.dumps(assets))
    return Response(body, media_type="text/javascript",
                    headers={**NO_STORE, "Service-Worker-Allowed": "/"})


@app.get("/")
def index():
    return _index_response()


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"):
        detail = getattr(exc, "detail", "Not found")
        return JSONResponse({"detail": detail}, status_code=404)
    return _index_response()
