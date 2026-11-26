"""2.0: offline downloads for the Movinite Android app (schema 11).

Pieces (see PLAN-invites-offline-sharing.md section 4):
- devices: each phone/tablet registers an EC P-256 public key that lives in its Android Keystore (never exportable).
  Requests that matter (register, grant, file, done, sync) carry a signature made with that key, so a leaked cookie
  alone can't download anything or renew a licence.
- grants: a signed, expiring licence per title per device.  Token = base64url(payload) "." base64url(Ed25519 signature
  by the server key over the first part).  30 days by default, renewed on every sync; revoked titles are listed in the
  sync answer and the app deletes them.
- jobs: device-profile transcodes (1080p / 720p / 480p, H.264 or HEVC, AAC stereo, MP4) made by one background
  ffmpeg on the GPU (VAAPI / QSV / NVENC through hwaccel.stage_args, CPU as the last fallback).  A running job is
  paused (SIGSTOP) the moment someone starts watching, and carries on once streaming has been idle for a while.
  Results are cached in data/offline and shared by every user and device that asks for the same title, quality and
  audio track; least recently used files are removed above the cache cap.
- quotas: 20 titles or 100 GB per user and 3 devices by default (Settings > Downloads); admins are unlimited.  Only
  the "Viewer + Downloads" role and admins can download.

This is trust-based protection for a self-hosted server, not studio DRM: it stops casual copying and lets you revoke,
but a rooted device and a determined person can still get at a downloaded file.
"""
import base64
import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import auth, config, db, hwaccel, keys, netutil, settings, transcode, useractivity

log = logging.getLogger("media-server.offline")
router = APIRouter()

OFFLINE_DIR = config.DATA_DIR / "offline"
SIG_VERSION = "MOVINITE-DEVICE-1"
SKEW_S = 300                      # allowed clock difference for a signed request
NONCE_KEEP_S = 2 * SKEW_S + 60
ACTIVE = ("preparing", "ready", "downloaded")

DEFAULTS = {"offline_enabled": "1", "offline_days": "30", "offline_wipe_days": "30", "offline_titles": "20",
            "offline_gb": "100", "offline_devices": "3", "offline_cache_gb": "200"}
LIMITS = {"offline_days": (7, 90), "offline_wipe_days": (7, 90), "offline_titles": (0, 1000), "offline_gb": (0, 10000),
          "offline_devices": (0, 50), "offline_cache_gb": (5, 10000)}

# name: (max height, video kbps (H.264), audio kbps).  720p is about 1.8 GB for a 2-hour film, 1080p about 3.2 GB.
PROFILES = {"1080p": (1080, 3500, 160), "720p": (720, 2000, 160), "480p": (480, 1000, 128)}
HEVC_FACTOR = 0.65                # HEVC needs about a third less for the same picture
DEFAULT_PROFILE = "720p"
ORIGINAL_EXT = {".mp4", ".m4v", ".mov", ".mkv", ".webm"}
BASE_AUDIO = {"aac", "mp3", "opus", "vorbis", "flac"}
RESUME_IDLE_S = 10                # streaming must be idle this long before a paused job carries on


# ----------------------------------------------------------------------------------------------- settings
def cfg(key):
    raw = settings.get(key, DEFAULTS[key])
    if key == "offline_enabled":
        return raw != "0"
    try:
        v = float(raw)
    except (TypeError, ValueError):
        v = float(DEFAULTS[key])
    lo, hi = LIMITS[key]
    v = max(lo, min(hi, v))
    return v if key == "offline_gb" else int(v)


def all_settings():
    return {"enabled": cfg("offline_enabled"), "days": cfg("offline_days"), "wipe_days": cfg("offline_wipe_days"),
            "titles": cfg("offline_titles"), "gb": cfg("offline_gb"), "devices": cfg("offline_devices"),
            "cache_gb": cfg("offline_cache_gb")}


SETTING_NAMES = {"enabled": "offline_enabled", "days": "offline_days", "wipe_days": "offline_wipe_days",
                 "titles": "offline_titles", "gb": "offline_gb", "devices": "offline_devices", "cache_gb": "offline_cache_gb"}


def save_settings(body):
    changed = []
    for k, key in SETTING_NAMES.items():
        if k not in body:
            continue
        v = body[k]
        if k == "enabled":
            settings.put(key, "1" if v else "0")
        else:
            try:
                n = float(v)
            except (TypeError, ValueError):
                raise ValueError("%s must be a number" % k)
            lo, hi = LIMITS[key]
            if n < lo or n > hi:
                raise ValueError("%s must be between %g and %g" % (k, lo, hi))
            settings.put(key, str(n if k == "gb" else int(n)))
        changed.append(k)
    if "cache_gb" in changed:
        evict_lru()
    return changed


def can_download(u):
    return bool(u) and auth.norm_role(u.get("role"), u.get("is_admin")) in ("admin", "download")


def user_limits(uid):
    """{"titles", "gb", "devices"} with None = unlimited.  Admins are unlimited."""
    r = db.row("SELECT role, is_admin, dl_titles, dl_gb, dl_devices FROM users WHERE id=?", (uid,))
    if not r:
        return {"titles": 0, "gb": 0, "devices": 0}
    if auth.norm_role(r.get("role"), r.get("is_admin")) == "admin":
        return {"titles": None, "gb": None, "devices": None}

    def pick(own, key):
        v = cfg(key) if own is None else own
        return None if not v else v       # 0 = unlimited
    return {"titles": pick(r.get("dl_titles"), "offline_titles"), "gb": pick(r.get("dl_gb"), "offline_gb"),
            "devices": pick(r.get("dl_devices"), "offline_devices")}


def usage(uid):
    r = db.row("SELECT COUNT(*) n, COALESCE(SUM(bytes),0) b FROM offline_grants WHERE user_id=? AND state IN "
               "('preparing','ready','downloaded')", (uid,))
    lim = user_limits(uid)
    return {"titles": int(r["n"]), "bytes": int(r["b"]), "titles_max": lim["titles"],
            "bytes_max": int(lim["gb"] * 1024 ** 3) if lim["gb"] else None, "devices_max": lim["devices"],
            "devices": db.row("SELECT COUNT(*) n FROM devices WHERE user_id=? AND revoked_at IS NULL", (uid,))["n"]}


# ----------------------------------------------------------------------------------------------- crypto
def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def device_fp(der: bytes) -> str:
    return b64u(hashlib.sha256(der).digest())


def load_pubkey(b64der):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import load_der_public_key
    try:
        der = base64.b64decode(b64der, validate=True)
        k = load_der_public_key(der)
    except Exception:
        raise HTTPException(400, "Bad device key")
    if not isinstance(k, ec.EllipticCurvePublicKey) or k.curve.name != "secp256r1":
        raise HTTPException(400, "The device key must be EC P-256")
    return k, der


def canonical(method, path, ts, nonce, body: bytes) -> bytes:
    return ("%s\n%s\n%s\n%s\n%s\n%s" % (SIG_VERSION, method.upper(), path, ts, nonce,
                                        hashlib.sha256(body or b"").hexdigest())).encode()


def _req_path(request):
    q = request.url.query
    return request.url.path + ("?" + q if q else "")


_nonces = {}
_nlock = threading.Lock()


def _fresh_nonce(nonce, now):
    with _nlock:
        for k in [k for k, t in _nonces.items() if now - t > NONCE_KEEP_S]:
            _nonces.pop(k, None)
        if nonce in _nonces:
            return False
        _nonces[nonce] = now
        return True


def _sig_error(why):
    return HTTPException(401, {"error": "device_signature", "reason": why, "server_time": int(time.time())})


def verify_request(request, body: bytes, pubkey=None):
    """Check the X-Movinite-* headers.  Returns the device row (None when pubkey is given: registration)."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    h = request.headers
    did, ts, nonce, sig = h.get("x-movinite-device"), h.get("x-movinite-time"), h.get("x-movinite-nonce"), h.get("x-movinite-sig")
    if not (did and ts and nonce and sig):
        raise _sig_error("missing")
    if not re.match(r"^[A-Za-z0-9_-]{16,64}$", nonce):
        raise _sig_error("nonce")
    try:
        tsi = int(ts)
    except ValueError:
        raise _sig_error("time")
    now = int(time.time())
    if abs(now - tsi) > SKEW_S:
        raise _sig_error("clock")
    dev = None
    if pubkey is None:
        if not did.isdigit():
            raise _sig_error("device")
        dev = db.row("SELECT * FROM devices WHERE id=?", (int(did),))
        if not dev:
            raise _sig_error("unknown_device")
        pubkey, _ = load_pubkey(dev["pubkey"])
    try:
        pubkey.verify(base64.b64decode(sig), canonical(request.method, _req_path(request), ts, nonce, body),
                      ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError):
        raise _sig_error("bad_signature")
    if not _fresh_nonce(nonce, now):
        raise _sig_error("replay")
    return dev


def issue_token(g, dev_fp, role):
    payload = {"v": 1, "srv": keys.server_id(), "uid": g["user_id"], "role": role, "dev": dev_fp, "item": g["item_id"],
               "prof": g["profile"], "sha": g.get("sha256"), "bytes": g.get("bytes"), "iat": int(time.time()),
               "exp": int(g["expires_at"]), "gid": g["id"]}
    p = b64u(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return p + "." + b64u(keys.sign(p.encode("ascii")))


def check_token(tok):
    """Server-side check (tests, admin): returns the payload or raises."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    p, _, s = tok.partition(".")
    Ed25519PublicKey.from_public_bytes(keys.public_bytes()).verify(b64u_dec(s), p.encode("ascii"))
    return json.loads(b64u_dec(p))


# ----------------------------------------------------------------------------------------------- caps + profiles
def parse_caps(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            raw = {}
    raw = raw if isinstance(raw, dict) else {}
    out = {k: bool(raw.get(k)) for k in ("hevc", "av1", "vp9", "ac3", "eac3", "dts", "truehd", "hdr")}
    out["h264"] = True
    try:
        out["maxh"] = max(240, min(4320, int(raw.get("maxh") or 1080)))
    except (TypeError, ValueError):
        out["maxh"] = 1080
    return out


def _audio_codec(item, audio):
    try:
        auds = json.loads(item.get("audio_streams") or "[]")
    except ValueError:
        auds = []
    if auds:
        a = auds[audio] if 0 <= audio < len(auds) else auds[0]
        return (a.get("codec") or "").lower()
    return (item.get("acodec") or "").lower()


def original_ok(item, caps, audio=0):
    """(True, "") when the device can play the file itself, else (False, why)."""
    ext = Path(item.get("path") or "").suffix.lower()
    if ext not in ORIGINAL_EXT:
        return False, "%s files need converting" % (ext.lstrip(".").upper() or "These")
    v = (item.get("vcodec") or "").lower()
    if v == "h265":
        v = "hevc"
    okv = {"h264"} | {c for c in ("hevc", "av1", "vp9") if caps.get(c)}
    if v not in okv:
        return False, "This device can't decode %s video" % (v.upper() or "this")
    if v == "h264" and (item.get("pix_fmt") or "yuv420p") not in ("yuv420p", "yuvj420p"):
        return False, "10-bit H.264 isn't supported on phones"
    a = _audio_codec(item, audio)
    oka = BASE_AUDIO | {c for c in ("ac3", "eac3", "dts", "truehd") if caps.get(c)}
    if a and a not in oka:
        return False, "This device can't play %s audio" % a.upper()
    h = int(item.get("height") or 0)
    if h and h > caps["maxh"] * 1.05:
        return False, "Larger than this device can play (%dp)" % h
    if (item.get("color_transfer") or "") in ("smpte2084", "arib-std-b67") and not caps.get("hdr"):
        return False, "HDR isn't supported on this device"
    return True, ""


def use_hevc(caps):
    return bool(caps.get("hevc")) and hwaccel.active()[0] is not None


def _kbps(item, profile):
    base, _, vc = profile.partition(".")
    maxh, vk, ak = PROFILES[base]
    if vc == "hevc":
        vk = int(vk * HEVC_FACTOR)
    src_h = int(item.get("height") or 0)
    if src_h and src_h < maxh:
        vk = max(500, int(vk * (src_h / maxh) ** 1.5))
    return vk, ak


def estimate(item, profile):
    if profile == "original":
        return int(item.get("size") or 0)
    vk, ak = _kbps(item, profile)
    src_k = int((item.get("bitrate") or 0) / 1000)
    if src_k:
        vk = min(vk, max(500, src_k))
    return int(float(item.get("duration") or 0) * (vk + ak) * 125 * 1.02)


def profile_list(item, caps, audio=0):
    src_h = int(item.get("height") or 0)
    hevc = use_hevc(caps)
    ok, why = original_ok(item, caps, audio)
    out = [{"id": "original", "label": "Original", "bytes": estimate(item, "original"), "available": ok,
            "note": why or "%s%s" % ((item.get("vcodec") or "").upper(), (" · %dp" % src_h) if src_h else "")}]
    for base, (h, _, _) in PROFILES.items():
        if src_h and h > max(src_h, 480):
            continue
        pid = base + (".hevc" if hevc else "")
        out.append({"id": pid, "label": base, "bytes": estimate(item, pid), "available": True,
                    "note": "HEVC" if hevc else "H.264"})
    bases = [p["id"].split(".")[0] for p in out if p["id"] != "original"]
    want = DEFAULT_PROFILE if DEFAULT_PROFILE in bases else (bases[0] if bases else "original")
    default = next((p["id"] for p in out if p["id"].split(".")[0] == want), "original")
    return out, default


# ----------------------------------------------------------------------------------------------- helpers
def _item(item_id):
    return db.row("SELECT * FROM items WHERE id=?", (item_id,))


def _user_row(uid):
    return db.row("SELECT id, username, role, is_admin, disabled_at, all_libraries FROM users WHERE id=?", (uid,))


def _libs(uid):
    r = _user_row(uid)
    if not r:
        return frozenset()
    if auth.norm_role(r.get("role"), r.get("is_admin")) == "admin" or r.get("all_libraries"):
        return None
    return frozenset(x["library_id"] for x in db.rows("SELECT library_id FROM user_libraries WHERE user_id=?", (uid,)))


def _visible(uid, item):
    libs = _libs(uid)
    return libs is None or item.get("library_id") in libs


def _device_for(u, dev):
    if not dev or dev["user_id"] != u["id"]:
        raise HTTPException(403, "This device belongs to another account")
    if dev.get("revoked_at"):
        raise HTTPException(403, {"error": "device_revoked", "detail": "This device was removed from your account"})
    return dev


def _ip(request):
    return netutil.client_ip(request)


def _brief(item):
    return {k: item.get(k) for k in ("id", "library_id", "title", "show", "season", "episode", "episode_title",
                                     "artist", "media_type")} if item else None


def _queue_position(job_id):
    r = db.row("SELECT COUNT(*) n FROM offline_jobs WHERE status IN ('queued','running','paused') AND id<?", (job_id,))
    return int(r["n"]) + 1


def grant_out(g, with_token=False, dev=None):
    o = {k: g.get(k) for k in ("id", "item_id", "device_id", "profile", "audio", "bytes", "sha256", "title", "state",
                               "issued_at", "expires_at", "renewed_at", "revoked_at", "revoke_reason", "done_at")}
    o["quality"] = "Original" if g["profile"] == "original" else g["profile"].replace(".hevc", " HEVC")
    if g.get("job_id") and g["state"] == "preparing":
        j = db.row("SELECT status, progress, error FROM offline_jobs WHERE id=?", (g["job_id"],))
        if j:
            o["job"] = {"status": j["status"], "progress": round(float(j["progress"] or 0), 3),
                        "position": _queue_position(g["job_id"]) if j["status"] == "queued" else 0}
    if with_token and dev and g["state"] in ("ready", "downloaded"):
        u = _user_row(g["user_id"])
        o["token"] = issue_token(g, dev["fp"], auth.norm_role(u.get("role"), u.get("is_admin")) if u else "view")
    return o


def _json(body):
    if not body:
        return {}
    try:
        d = json.loads(body)
    except ValueError:
        raise HTTPException(400, "Bad JSON")
    if not isinstance(d, dict):
        raise HTTPException(400, "Bad JSON")
    return d


async def _raw(request):
    return await request.body()


# ----------------------------------------------------------------------------------------------- devices
def _register(request, body):
    u = auth.require_user(request)
    if not cfg("offline_enabled"):
        raise HTTPException(403, "Downloads are turned off on this server")
    if not can_download(u):
        raise HTTPException(403, "Downloads need the Viewer + Downloads role. Ask the server's admin.")
    if not keys.available() or not keys.ensure():
        raise HTTPException(503, "The server key isn't available (update.sh installs the cryptography package)")
    d = _json(body)
    pk, der = load_pubkey(d.get("pubkey") or "")
    verify_request(request, body, pubkey=pk)          # proof that the caller holds the private key
    fp = device_fp(der)
    b64 = base64.b64encode(der).decode()
    now = int(time.time())
    existing = db.row("SELECT * FROM devices WHERE pubkey=?", (b64,))
    name = str(d.get("name") or "Android device")[:80]
    caps = json.dumps(parse_caps(d.get("caps")))
    meta = (name, str(d.get("platform") or "android")[:40], str(d.get("app_version") or "")[:20], caps)
    if existing:
        if existing["user_id"] != u["id"] or existing.get("revoked_at"):
            raise HTTPException(409, {"error": "device_key_used",
                                      "detail": "This device key can't be used again. Sign out of the app and sign in once more."})
        with db.tx() as c:
            c.execute("UPDATE devices SET name=?, platform=?, app_version=?, caps=?, last_ip=? WHERE id=?",
                      meta + (_ip(request), existing["id"]))
        dev = db.row("SELECT * FROM devices WHERE id=?", (existing["id"],))
    else:
        lim = user_limits(u["id"])["devices"]
        n = db.row("SELECT COUNT(*) n FROM devices WHERE user_id=? AND revoked_at IS NULL", (u["id"],))["n"]
        if lim is not None and n >= lim:
            raise HTTPException(409, {"error": "device_limit", "limit": lim,
                                      "detail": "You already have %d devices set up for downloads (the limit is %d). "
                                                "Remove one in Settings > My account > Devices & downloads." % (n, lim)})
        with db.tx() as c:
            cur = c.execute("INSERT INTO devices(user_id,name,platform,app_version,pubkey,fp,caps,created_at,last_sync,last_ip) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?)", (u["id"],) + meta[:3] + (b64, fp, caps, now, now, _ip(request)))
            did = cur.lastrowid
        dev = db.row("SELECT * FROM devices WHERE id=?", (did,))
        useractivity.record("device_registered", user=u, ip=_ip(request), device=name, detail={"device_id": did})
    return {"device_id": dev["id"], "fp": dev["fp"], "server_pubkey": b64u(keys.public_bytes()),
            "server_id": keys.server_id(), "server_fingerprint": keys.fingerprint(),
            "offline_days": cfg("offline_days"), "wipe_days": cfg("offline_wipe_days"),
            "user": {"id": u["id"], "username": u["username"], "role": u["role"]}, "server_time": now}


@router.post("/api/devices")
async def register_device(request: Request):
    body = await _raw(request)
    return await run_in_threadpool(_register, request, body)


def device_out(d, with_grants=False):
    o = {k: d.get(k) for k in ("id", "user_id", "name", "platform", "app_version", "created_at", "last_sync",
                               "revoked_at", "revoke_reason")}
    o["fp_short"] = (d.get("fp") or "")[:8]
    if with_grants:
        o["grants"] = [grant_out(g) for g in db.rows(
            "SELECT * FROM offline_grants WHERE device_id=? AND state IN ('preparing','ready','downloaded','failed') "
            "ORDER BY issued_at DESC", (d["id"],))]
        o["bytes"] = sum(int(g.get("bytes") or 0) for g in o["grants"] if g["state"] != "failed")
    return o


@router.get("/api/devices")
def list_devices(u=Depends(auth.require_user)):
    devs = db.rows("SELECT * FROM devices WHERE user_id=? AND revoked_at IS NULL ORDER BY created_at", (u["id"],))
    return {"devices": [device_out(d, True) for d in devs], "usage": usage(u["id"]),
            "can_download": can_download(u), "enabled": cfg("offline_enabled"), "days": cfg("offline_days")}


def revoke_device(did, by, reason):
    d = db.row("SELECT * FROM devices WHERE id=?", (did,))
    if not d or d.get("revoked_at"):
        return d
    now = int(time.time())
    with db.tx() as c:
        c.execute("UPDATE devices SET revoked_at=?, revoke_reason=? WHERE id=?", (now, reason, did))
        c.execute("UPDATE offline_grants SET state='revoked', revoked_at=?, revoke_reason=? WHERE device_id=? AND "
                  "state IN ('preparing','ready','downloaded')", (now, reason, did))
    useractivity.record("device_revoked", user=by, actor=None if by else "server", device=d.get("name"),
                        detail={"device_id": did, "reason": reason, "owner_id": d["user_id"]})
    _cancel_orphan_jobs()
    return d


def _forget_self(request, body):
    dev = verify_request(request, body)          # signed by the device key alone: works after the cookie is gone
    if not dev.get("revoked_at"):
        revoke_device(dev["id"], None, "signed out on the device")
    return {"ok": True}


@router.post("/api/devices/forget")
async def forget_self(request: Request):
    """The app's Sign out: the phone deletes its downloads and keys, and tells the server to free the device slot."""
    body = await _raw(request)
    return await run_in_threadpool(_forget_self, request, body)


@router.delete("/api/devices/{did}")
def delete_device(did: int, u=Depends(auth.require_user)):
    d = db.row("SELECT * FROM devices WHERE id=?", (did,))
    if not d or (d["user_id"] != u["id"] and not u["is_admin"]):
        raise HTTPException(404, "No such device")
    revoke_device(did, u, "removed by you" if d["user_id"] == u["id"] else "removed by an admin")
    return {"ok": True}


def forget_user(uid, reason="account deleted"):
    """A user was deleted or disabled: tombstone their devices so the phones wipe on their next sync."""
    for d in db.rows("SELECT id FROM devices WHERE user_id=? AND revoked_at IS NULL", (uid,)):
        revoke_device(d["id"], None, reason)


def revoke_user_grants(uid, reason):
    now = int(time.time())
    with db.tx() as c:
        c.execute("UPDATE offline_grants SET state='revoked', revoked_at=?, revoke_reason=? WHERE user_id=? AND "
                  "state IN ('preparing','ready','downloaded')", (now, reason, uid))
    _cancel_orphan_jobs()


# ----------------------------------------------------------------------------------------------- options + grants
def _options(request, body, item_id):
    u = auth.require_user(request)
    dev = verify_request(request, body) if request.headers.get("x-movinite-device") else None
    if dev:
        _device_for(u, dev)
    it = _item(item_id)
    if not it or not _visible(u["id"], it):
        raise HTTPException(404, "No such item")
    if it.get("media_type") != "video":
        raise HTTPException(400, "Only videos can be downloaded")
    caps = parse_caps(dev["caps"] if dev else request.query_params.get("caps"))
    try:
        audio = int(request.query_params.get("audio") or 0)
    except ValueError:
        audio = 0
    profs, default = profile_list(it, caps, audio)
    try:
        auds = json.loads(it.get("audio_streams") or "[]")
    except ValueError:
        auds = []
    have = None
    if dev:
        g = db.row("SELECT * FROM offline_grants WHERE device_id=? AND item_id=? AND state IN ('preparing','ready','downloaded')",
                   (dev["id"], item_id))
        have = grant_out(g) if g else None
    return {"item_id": item_id, "title": useractivity._title(it), "duration": it.get("duration"),
            "profiles": profs, "default": default, "can_download": can_download(u) and cfg("offline_enabled"),
            "audio": [{"index": i, "label": (a.get("title") or a.get("lang") or "Track %d" % (i + 1)),
                       "codec": a.get("codec"), "channels": a.get("channels")} for i, a in enumerate(auds)],
            "usage": usage(u["id"]), "existing": have, "days": cfg("offline_days")}


@router.get("/api/offline/options/{item_id}")
async def offline_options(item_id: int, request: Request):
    body = await _raw(request)
    return await run_in_threadpool(_options, request, body, item_id)


def _create_grant(request, body):
    u = auth.require_user(request)
    dev = _device_for(u, verify_request(request, body))
    if not cfg("offline_enabled"):
        raise HTTPException(403, "Downloads are turned off on this server")
    if not can_download(u):
        raise HTTPException(403, "Downloads need the Viewer + Downloads role")
    d = _json(body)
    try:
        item_id, audio = int(d.get("item_id")), int(d.get("audio") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "item_id is required")
    it = _item(item_id)
    if not it or not _visible(u["id"], it):
        raise HTTPException(404, "No such item")
    if it.get("media_type") != "video":
        raise HTTPException(400, "Only videos can be downloaded")
    caps = parse_caps(dev.get("caps"))
    profs, default = profile_list(it, caps, audio)
    profile = str(d.get("profile") or default)
    p = next((x for x in profs if x["id"] == profile), None)
    if not p:
        raise HTTPException(400, "That quality isn't offered for this title")
    if not p["available"]:
        raise HTTPException(400, p["note"] or "That quality isn't available on this device")
    old = db.row("SELECT * FROM offline_grants WHERE device_id=? AND item_id=? AND state IN ('preparing','ready','downloaded')",
                 (dev["id"], item_id))
    if old:
        if old["profile"] == profile and old["audio"] == audio:
            return JSONResponse(grant_out(old, True, dev))
        raise HTTPException(409, {"error": "already_downloaded", "grant_id": old["id"],
                                  "detail": "Already on this device in %s. Delete that download first." % grant_out(old)["quality"]})
    est = p["bytes"]
    us = usage(u["id"])
    if us["titles_max"] is not None and us["titles"] >= us["titles_max"]:
        raise HTTPException(409, {"error": "quota_titles", "usage": us,
                                  "detail": "You've reached your limit of %d downloaded titles. Delete one to make room." % us["titles_max"]})
    if us["bytes_max"] is not None and us["bytes"] + est > us["bytes_max"]:
        raise HTTPException(409, {"error": "quota_bytes", "usage": us,
                                  "detail": "This would go over your %d GB download limit (%.1f GB used). Pick a smaller "
                                            "quality or delete a download." % (round(us["bytes_max"] / 1024 ** 3), us["bytes"] / 1024 ** 3)})
    now = int(time.time())
    exp = now + cfg("offline_days") * 86400
    job = None
    state, size, sha = "ready", int(it.get("size") or 0), None
    if profile != "original":
        job = ensure_job(it, profile, audio)
        if job["status"] == "ready":
            size, sha = int(job["bytes"] or 0), job["sha256"]
        else:
            state, size = "preparing", est
    with db.tx() as c:
        cur = c.execute("INSERT INTO offline_grants(user_id,device_id,item_id,profile,audio,job_id,bytes,sha256,title,"
                        "issued_at,expires_at,state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (u["id"], dev["id"], item_id, profile, audio, job["id"] if job else None, size, sha,
                         useractivity._title(it), now, exp, state))
        gid = cur.lastrowid
    g = db.row("SELECT * FROM offline_grants WHERE id=?", (gid,))
    useractivity.record("download_requested", user=u, item=_brief(it), ip=_ip(request), device=dev.get("name"),
                        detail={"grant_id": gid, "quality": grant_out(g)["quality"], "bytes": size})
    if state == "ready":
        useractivity.record("download_ready", user=u, item=_brief(it), device=dev.get("name"), detail={"grant_id": gid})
    kick()
    return JSONResponse(grant_out(g, True, dev), status_code=201)


@router.post("/api/offline/grants")
async def create_grant(request: Request):
    body = await _raw(request)
    return await run_in_threadpool(_create_grant, request, body)


def _grant_for(u, gid, dev=None):
    g = db.row("SELECT * FROM offline_grants WHERE id=?", (gid,))
    if not g or g["user_id"] != u["id"] or (dev and g["device_id"] != dev["id"]):
        raise HTTPException(404, "No such download")
    return g


def _grant_status(request, body, gid):
    u = auth.require_user(request)
    dev = _device_for(u, verify_request(request, body))
    return grant_out(_grant_for(u, gid, dev), True, dev)


@router.get("/api/offline/grants/{gid}")
async def grant_status(gid: int, request: Request):
    body = await _raw(request)
    return await run_in_threadpool(_grant_status, request, body, gid)


def _grant_file_path(g):
    it = _item(g["item_id"])
    if not it:
        raise HTTPException(410, {"error": "gone", "detail": "This title is no longer on the server"})
    if g["profile"] == "original":
        return it, Path(it["path"])
    j = db.row("SELECT * FROM offline_jobs WHERE id=?", (g["job_id"],)) if g.get("job_id") else None
    if not j or j["status"] != "ready" or not j.get("path"):
        raise HTTPException(409, {"error": "not_ready", "detail": "Still being prepared"})
    p = OFFLINE_DIR / j["path"]
    if not p.is_file():
        with db.tx() as c:          # removed from the cache: make it again (the grant goes back to preparing)
            c.execute("UPDATE offline_jobs SET status='queued', progress=0, path=NULL WHERE id=?", (j["id"],))
            c.execute("UPDATE offline_grants SET state='preparing' WHERE job_id=? AND state='ready'", (j["id"],))
        kick()
        raise HTTPException(409, {"error": "not_ready", "detail": "Being prepared again"})
    with db.tx() as c:
        c.execute("UPDATE offline_jobs SET last_access=? WHERE id=?", (int(time.time()), j["id"]))
    return it, p


def _file(request, body, gid):
    u = auth.require_user(request)
    dev = _device_for(u, verify_request(request, body))
    g = _grant_for(u, gid, dev)
    if g["state"] not in ("ready", "downloaded"):
        raise HTTPException(409 if g["state"] == "preparing" else 410, {"error": g["state"], "detail": "Not available (%s)" % g["state"]})
    if g["expires_at"] < time.time():
        raise HTTPException(410, {"error": "expired", "detail": "This download's licence expired; sync first"})
    it, path = _grant_file_path(g)
    if not _visible(u["id"], it):
        raise HTTPException(404, "No such item")
    try:
        size = os.path.getsize(path)
    except OSError:
        raise HTTPException(404, "File is not reachable (share offline?)")
    start, end, status = 0, size - 1, 200
    rng = request.headers.get("range")
    if rng:
        m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
        if not m or (not m.group(1) and not m.group(2)):
            raise HTTPException(416)
        if m.group(1):
            start = int(m.group(1))
            if m.group(2):
                end = min(int(m.group(2)), size - 1)
        else:
            start = max(0, size - int(m.group(2)))
        if start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": "bytes */%d" % size, "Cache-Control": "private, no-store"})
        status = 206
    if start == 0:
        useractivity.record("download_started", user=u, item=_brief(it), ip=_ip(request), device=dev.get("name"),
                            detail={"grant_id": gid, "bytes": size})
    length = end - start + 1

    def gen():
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(1024 * 1024, left))
                if not chunk:
                    break
                left -= len(chunk)
                yield chunk

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(length), "Cache-Control": "private, no-store",
               "X-Movinite-Bytes": str(size), "X-Content-Type-Options": "nosniff"}
    if status == 206:
        headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)
    return StreamingResponse(gen(), status_code=status, media_type="application/octet-stream", headers=headers)


@router.get("/api/offline/{gid}/file")
async def grant_file(gid: int, request: Request):
    body = await _raw(request)
    return await run_in_threadpool(_file, request, body, gid)


def _manifest(request, body, gid):
    u = auth.require_user(request)
    dev = _device_for(u, verify_request(request, body))
    g = _grant_for(u, gid, dev)
    it = _item(g["item_id"])
    if not it or not _visible(u["id"], it):
        raise HTTPException(410, "This title is no longer on the server")
    m = None
    if it.get("tmdb_id") and it.get("kind") == "movie":
        m = db.row("SELECT title, overview, genres, rating, poster, year FROM metadata WHERE kind='movie' AND tmdb_id=?",
                   (it["tmdb_id"],))
    m = m or {}
    poster = m.get("poster") or it.get("poster") or it.get("thumb")
    subs = []
    try:
        for i, s in enumerate(json.loads(it.get("external_subs") or "[]")):
            subs.append({"key": "e%d" % i, "label": s.get("label") or "External", "lang": s.get("lang")})
        for s in json.loads(it.get("subtitle_streams") or "[]"):
            if s.get("text"):
                subs.append({"key": "s%d" % s["index"], "label": s.get("title") or s.get("lang") or "Track %d" % s["index"],
                             "lang": s.get("lang")})
    except (TypeError, ValueError):
        pass
    for s in subs:
        s["url"] = "/api/items/%d/subs/%s.vtt" % (it["id"], s["key"])
    try:
        genres = json.loads(m.get("genres") or "[]")
    except ValueError:
        genres = []
    return {"grant_id": gid, "item_id": it["id"], "title": m.get("title") or it.get("title"),
            "display_title": useractivity._title(it), "year": m.get("year") or it.get("year"),
            "overview": m.get("overview"), "kind": it.get("kind"), "show": it.get("show"),
            "season": it.get("season"), "episode": it.get("episode"), "episode_title": it.get("episode_title"),
            "duration": it.get("duration"), "genres": genres, "rating": m.get("rating"),
            "poster_url": ("/api/thumb/%s" % poster) if poster and re.match(r"^[0-9a-f]{40}\.jpg$", poster) else None,
            "subtitles": subs[:8], "quality": grant_out(g)["quality"]}


@router.get("/api/offline/{gid}/manifest")
async def grant_manifest(gid: int, request: Request):
    body = await _raw(request)
    return await run_in_threadpool(_manifest, request, body, gid)


def _done(request, body, gid):
    u = auth.require_user(request)
    dev = _device_for(u, verify_request(request, body))
    g = _grant_for(u, gid, dev)
    d = _json(body)
    if g["state"] not in ("ready", "downloaded"):
        raise HTTPException(409, "Not available (%s)" % g["state"])
    if g.get("sha256") and (d.get("sha256") or "").lower() != g["sha256"]:
        raise HTTPException(400, {"error": "checksum", "detail": "The download doesn't match the server's copy. Try again."})
    if g["state"] == "ready":
        with db.tx() as c:
            c.execute("UPDATE offline_grants SET state='downloaded', done_at=? WHERE id=?", (int(time.time()), gid))
        it = _item(g["item_id"]) or {"id": g["item_id"], "title": g["title"]}
        useractivity.record("download_complete", user=u, item=_brief(it), ip=_ip(request), device=dev.get("name"),
                            detail={"grant_id": gid, "bytes": g.get("bytes"), "quality": grant_out(g)["quality"]})
    return grant_out(db.row("SELECT * FROM offline_grants WHERE id=?", (gid,)), True, dev)


@router.post("/api/offline/grants/{gid}/done")
async def grant_done(gid: int, request: Request):
    body = await _raw(request)
    return await run_in_threadpool(_done, request, body, gid)


@router.delete("/api/offline/grants/{gid}")
def delete_grant(gid: int, request: Request, u=Depends(auth.require_user)):
    """The owner removed the download (frees quota), or an admin revoked it (the device deletes it on next sync)."""
    g = db.row("SELECT * FROM offline_grants WHERE id=?", (gid,))
    if not g or (g["user_id"] != u["id"] and not u["is_admin"]):
        raise HTTPException(404, "No such download")
    if g["state"] not in ACTIVE + ("failed",):
        return {"ok": True, "state": g["state"]}
    now = int(time.time())
    mine = g["user_id"] == u["id"]
    with db.tx() as c:
        if mine:
            c.execute("UPDATE offline_grants SET state='deleted', revoked_at=?, revoke_reason='deleted' WHERE id=?", (now, gid))
        else:
            c.execute("UPDATE offline_grants SET state='revoked', revoked_at=?, revoke_reason='removed by an admin' WHERE id=?", (now, gid))
    it = _item(g["item_id"]) or {"id": g["item_id"], "title": g["title"]}
    useractivity.record("download_deleted" if mine else "download_revoked", user=u, item=_brief(it), ip=_ip(request),
                        detail={"grant_id": gid, "owner_id": g["user_id"]})
    _cancel_orphan_jobs()
    return {"ok": True, "state": "deleted" if mine else "revoked"}


# ----------------------------------------------------------------------------------------------- sync
def _sync(request, body):
    dev = verify_request(request, body)          # the device key alone: still works after the cookie expired
    d = _json(body)
    now = int(time.time())
    u = _user_row(dev["user_id"])
    account = "active"
    if not u:
        account = "deleted"
    elif u.get("disabled_at"):
        account = "disabled"
    elif auth.norm_role(u.get("role"), u.get("is_admin")) not in ("admin", "download"):
        account = "no_downloads"
    elif not cfg("offline_enabled"):
        account = "downloads_off"
    if account != "active" and not dev.get("revoked_at"):
        if account in ("deleted", "disabled"):
            revoke_device(dev["id"], None, "account %s" % account)
        else:
            revoke_user_grants(dev["user_id"], "downloads turned off" if account == "downloads_off" else "role changed")
        dev = db.row("SELECT * FROM devices WHERE id=?", (dev["id"],))
    out = {"server_time": now, "account": account, "device": "revoked" if dev.get("revoked_at") else "active",
           "offline_days": cfg("offline_days"), "wipe_days": cfg("offline_wipe_days"), "renewed": [], "revoked": [],
           "active": [], "progress_saved": 0}
    # wipe = forget the offline profile and every download (device removed, account gone, or no download role)
    out["wipe"] = out["device"] == "revoked" or account in ("deleted", "disabled", "no_downloads")
    held = []
    for x in (d.get("grants") or [])[:2000]:
        try:
            held.append(int(x))
        except (TypeError, ValueError):
            pass
    if out["wipe"]:
        out["revoked"] = [{"id": i, "reason": dev.get("revoke_reason") or account} for i in held]
        return out
    with db.tx() as c:
        c.execute("UPDATE devices SET last_sync=?, last_ip=?, app_version=COALESCE(?, app_version) WHERE id=?",
                  (now, _ip(request), (str(d["app_version"])[:20] if d.get("app_version") else None), dev["id"]))
        if d.get("caps"):
            c.execute("UPDATE devices SET caps=? WHERE id=?", (json.dumps(parse_caps(d.get("caps"))), dev["id"]))
    # downloads the user deleted while offline
    for x in (d.get("deleted") or [])[:2000]:
        try:
            gid = int(x)
        except (TypeError, ValueError):
            continue
        with db.tx() as c:
            n = c.execute("UPDATE offline_grants SET state='deleted', revoked_at=?, revoke_reason='deleted' WHERE id=? AND "
                          "device_id=? AND state IN ('preparing','ready','downloaded','failed')", (now, gid, dev["id"])).rowcount
        if n:
            g = db.row("SELECT * FROM offline_grants WHERE id=?", (gid,))
            useractivity.record("download_deleted", user_id=u["id"], actor=u["username"], device=dev.get("name"),
                                item={"id": g["item_id"], "title": g["title"]}, detail={"grant_id": gid, "offline": True})
    role = auth.norm_role(u.get("role"), u.get("is_admin"))
    libs = _libs(u["id"])
    exp = now + cfg("offline_days") * 86400
    grants = {g["id"]: g for g in db.rows("SELECT * FROM offline_grants WHERE device_id=?", (dev["id"],))}
    for gid in held:
        g = grants.get(gid)
        if not g:
            out["revoked"].append({"id": gid, "reason": "unknown"})
        elif g["state"] not in ACTIVE:
            out["revoked"].append({"id": gid, "reason": g.get("revoke_reason") or g["state"]})
    for g in grants.values():
        if g["state"] not in ACTIVE:
            continue
        it = _item(g["item_id"])
        why = None
        if not it:
            why = "no longer on the server"
        elif libs is not None and it["library_id"] not in libs:
            why = "no longer shared with you"
        if why:
            with db.tx() as c:
                c.execute("UPDATE offline_grants SET state='revoked', revoked_at=?, revoke_reason=? WHERE id=?", (now, why, g["id"]))
            useractivity.record("download_revoked", user_id=u["id"], actor="server",
                                item={"id": g["item_id"], "title": g["title"]}, detail={"grant_id": g["id"], "reason": why})
            if g["id"] in held:
                out["revoked"].append({"id": g["id"], "reason": why})
            continue
        if g["state"] in ("ready", "downloaded"):
            with db.tx() as c:
                c.execute("UPDATE offline_grants SET expires_at=?, renewed_at=? WHERE id=?", (exp, now, g["id"]))
            g = dict(g, expires_at=exp, renewed_at=now)
            if g["id"] in held:
                out["renewed"].append({"id": g["id"], "token": issue_token(g, dev["fp"], role), "exp": exp})
        out["active"].append(grant_out(g))
    # watch progress made offline: the newest timestamp wins
    from . import titles
    saved = 0
    for p in (d.get("progress") or [])[:500]:
        try:
            iid, pos, ts = int(p.get("item_id")), float(p.get("position") or 0), int(p.get("ts") or 0)
            dur = float(p.get("duration") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
        it = _item(iid)
        if not it or (libs is not None and it["library_id"] not in libs):
            continue
        ts = min(ts, now)
        dur = dur or float(it.get("duration") or 0)
        watched = 1 if (dur and pos / dur > 0.92) or p.get("ended") else 0
        with db.tx() as c:
            for x in (titles.same_title_ids(iid) or [iid]):
                cur = c.execute("SELECT updated_at FROM progress WHERE user_id=? AND item_id=?", (u["id"], x)).fetchone()
                if cur and cur[0] and cur[0] >= ts:
                    continue
                c.execute("INSERT INTO progress(user_id,item_id,position,duration,watched,updated_at) VALUES(?,?,?,?,?,?) "
                          "ON CONFLICT(user_id,item_id) DO UPDATE SET position=excluded.position, duration=excluded.duration, "
                          "watched=MAX(watched, excluded.watched), updated_at=excluded.updated_at",
                          (u["id"], x, 0 if watched else pos, dur, watched, ts))
                saved += 1
    out["progress_saved"] = saved
    out["usage"] = usage(u["id"])
    out["user"] = {"id": u["id"], "username": u["username"], "role": role}
    return out


@router.post("/api/offline/sync")
async def offline_sync(request: Request):
    body = await _raw(request)
    return await run_in_threadpool(_sync, request, body)


# ----------------------------------------------------------------------------------------------- admin
def _encoder_label():
    m, _d = hwaccel.active()
    return {"vaapi": "GPU (VAAPI)", "qsv": "GPU (Quick Sync)", "nvenc": "GPU (NVENC)"}.get(m, "CPU")


def _job_out(j):
    return {"id": j["id"], "item_id": j["item_id"], "title": j.get("title"), "profile": j["profile"],
            "status": j["status"], "progress": round(float(j.get("progress") or 0), 3), "error": j.get("error"),
            "encoder": j.get("encoder"), "waiting": sum(1 for _ in db.rows(
                "SELECT 1 FROM offline_grants WHERE job_id=? AND state='preparing'", (j["id"],)))}


@router.get("/api/admin/offline")
def admin_offline(u=Depends(auth.require_admin)):
    out = []
    for r in db.rows("SELECT id, username, role, is_admin, dl_titles, dl_gb, dl_devices FROM users ORDER BY username COLLATE NOCASE"):
        role = auth.norm_role(r.get("role"), r.get("is_admin"))
        devs = db.rows("SELECT * FROM devices WHERE user_id=? AND revoked_at IS NULL ORDER BY created_at", (r["id"],))
        if not devs and role == "view":
            continue
        out.append({"id": r["id"], "username": r["username"], "role": role, "limits": user_limits(r["id"]),
                    "own_limits": {"titles": r.get("dl_titles"), "gb": r.get("dl_gb"), "devices": r.get("dl_devices")},
                    "usage": usage(r["id"]), "devices": [device_out(d, True) for d in devs]})
    jobs = db.rows("SELECT j.*, i.title FROM offline_jobs j LEFT JOIN items i ON i.id=j.item_id "
                   "WHERE j.status IN ('queued','running','paused','failed') ORDER BY j.id")
    return {"settings": all_settings(), "users": out, "jobs": [_job_out(j) for j in jobs], "cache": cache_stats(),
            "encoder": _encoder_label()}


@router.get("/api/settings/offline")
def get_offline_settings(u=Depends(auth.require_admin)):
    return dict(all_settings(), cache=cache_stats(), encoder=_encoder_label())


@router.put("/api/settings/offline")
def put_offline_settings(request: Request, body: dict = Body(...), u=Depends(auth.require_admin)):
    try:
        changed = save_settings(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if changed:
        useractivity.record("settings_changed", user=u, ip=_ip(request), detail={"section": "downloads", "fields": changed})
    return dict(all_settings(), cache=cache_stats(), encoder=_encoder_label())


@router.put("/api/users/{uid}/download-limits")
def put_user_limits(uid: int, request: Request, body: dict = Body(...), u=Depends(auth.require_admin)):
    t = db.row("SELECT id, username FROM users WHERE id=?", (uid,))
    if not t:
        raise HTTPException(404, "No such user")
    vals = {}
    for k, col, typ in (("titles", "dl_titles", int), ("gb", "dl_gb", float), ("devices", "dl_devices", int)):
        if k not in body:
            continue
        v = body[k]
        if v is None or v == "":
            vals[col] = None
            continue
        try:
            v = typ(v)
        except (TypeError, ValueError):
            raise HTTPException(400, "%s must be a number (0 = unlimited, empty = server default)" % k)
        if v < 0 or v > 10000:
            raise HTTPException(400, "%s is out of range" % k)
        vals[col] = v
    if vals:
        with db.tx() as c:
            for col, v in vals.items():
                c.execute("UPDATE users SET %s=? WHERE id=?" % col, (v, uid))
        useractivity.record("settings_changed", user=u, ip=_ip(request), detail={"section": "download_limits", "username": t["username"]})
    return {"ok": True, "limits": user_limits(uid)}


# ----------------------------------------------------------------------------------------------- transcode jobs
_wake = threading.Event()
_jlock = threading.Lock()
_cur = {"proc": None, "job": None, "paused": False, "idle_since": 0}
_stop_flag = [False]


def kick():
    _wake.set()


def job_name(item_id, profile, audio):
    return "%d-%s-a%d.mp4" % (item_id, profile.replace(".", "-"), audio)


def ensure_job(item, profile, audio):
    now = int(time.time())
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO offline_jobs(item_id,profile,audio,status,progress,created_at,mtime,last_access) "
                  "VALUES(?,?,?,?,0,?,?,?)", (item["id"], profile, audio, "queued", now, item.get("mtime"), now))
    j = db.row("SELECT * FROM offline_jobs WHERE item_id=? AND profile=? AND audio=?", (item["id"], profile, audio))
    stale = j["status"] == "ready" and (not j.get("path") or not (OFFLINE_DIR / j["path"]).is_file()
                                         or (j.get("mtime") is not None and item.get("mtime") is not None
                                             and j["mtime"] != item["mtime"]))
    if j["status"] in ("failed", "evicted") or stale:
        with db.tx() as c:
            c.execute("UPDATE offline_jobs SET status='queued', progress=0, error=NULL, path=NULL, mtime=?, created_at=? "
                      "WHERE id=?", (item.get("mtime"), now, j["id"]))
        j = db.row("SELECT * FROM offline_jobs WHERE id=?", (j["id"],))
    return j


def build_cmd(item, profile, audio, out_path, stage, hw):
    """ffmpeg command for one offline transcode.  stage: full | enc (GPU, hw = (method, device)) | cpu."""
    base, _, vc = profile.partition(".")
    maxh, _vk, ak = PROFILES[base]
    vk, ak = _kbps(item, profile)
    hevc = vc == "hevc"
    src_h = int(item.get("height") or 0)
    h = min(maxh, src_h) if src_h else maxh
    cmd = [config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y"]
    vmap = ["-map", "0:v:0", "-map", "0:a:%d?" % audio, "-sn", "-dn"]
    if stage != "cpu":
        pre, vf, venc = hwaccel.stage_args(hw[0], hw[1], stage, h, vk, hwaccel.rotation(item),
                                           codec="hevc" if hevc else "h264", hdr=transcode.hdr_info(item))
        cmd += pre + ["-i", item["path"]] + vmap + ["-vf", vf] + venc
    else:
        if hevc:
            raise ValueError("HEVC downloads need the GPU")
        cmd += ["-i", item["path"]] + vmap + [
            "-vf", "scale=-2:'min(%d,ih)',format=yuv420p" % h, "-c:v", "libx264", "-preset", config.X264_PRESET,
            "-profile:v", "high", "-level:v", "4.1", "-crf", "23", "-maxrate", "%dk" % vk, "-bufsize", "%dk" % (vk * 2)]
    cmd += ["-c:a", "aac", "-ac", "2", "-b:a", "%dk" % ak, "-ar", "48000", "-max_muxing_queue_size", "4096",
            "-movflags", "+faststart", "-f", "mp4", str(out_path)]
    return cmd


def stages_for(profile):
    """[(stage, (method, device))...]: full GPU, CPU decode + GPU encode, then the CPU (H.264 only)."""
    m, d = hwaccel.active()
    hevc = profile.endswith(".hevc")
    if not m:
        return [] if hevc else [("cpu", (None, None))]
    st = ["full", "enc"]
    return [(s, (m, d)) for s in st] + ([] if hevc else [("cpu", (None, None))])


def _signal(p, sig):
    try:
        os.killpg(p.pid, sig)
    except Exception:
        try:
            p.send_signal(sig)
        except Exception:
            pass


def _set_status(jid, st):
    try:
        with db.tx() as c:
            c.execute("UPDATE offline_jobs SET status=? WHERE id=? AND status IN ('running','paused')", (st, jid))
    except Exception:
        pass


def yield_now():
    """preload.yield_to_playback calls this when a stream starts: pause the running offline job at once."""
    with _jlock:
        p, jid = _cur.get("proc"), _cur.get("job")
        if p is None or p.poll() is not None or _cur["paused"]:
            return
        _signal(p, signal.SIGSTOP)
        _cur["paused"], _cur["idle_since"] = True, 0
    log.info("offline job %s paused for playback", jid)
    _set_status(jid, "paused")


def _busy():
    """Someone is watching: a transcode/remux session, or a direct-play film read in the last 30 s."""
    from . import preload
    if preload.busy():
        return True
    now = time.time()
    try:
        with useractivity._nplock:
            entries = list(useractivity._now_playing.values())
    except Exception:
        return False
    return any(now - e.get("last", 0) < 30 and e.get("mode") != "music" for e in entries)


def _wanted(job_id):
    return db.row("SELECT COUNT(*) n FROM offline_grants WHERE job_id=? AND state='preparing'", (job_id,))["n"] > 0


def _run_stage(j, item, stage, hw, tmp):
    cmd = build_cmd(item, j["profile"], j["audio"], tmp, stage, hw)
    dur = float(item.get("duration") or 0) or 1.0

    def _low():
        try:
            os.nice(10)
        except OSError:
            pass
        os.setsid()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=_low, text=True, bufsize=1)
    with _jlock:
        _cur.update(proc=p, job=j["id"], paused=False, idle_since=0)
    err_lines, prog = [], [0.0]

    def _err():
        for line in p.stderr:
            err_lines.append(line.strip())
            del err_lines[:-20]

    def _out():
        for line in p.stdout:
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    prog[0] = max(0.0, min(0.999, int(line.split("=", 1)[1]) / 1e6 / dur))
                except ValueError:
                    pass
    readers = [threading.Thread(target=f, daemon=True) for f in (_err, _out)]
    for t in readers:
        t.start()
    cancelled, last_db = False, 0
    try:
        while p.poll() is None:
            time.sleep(0.5)
            now = time.time()
            busy = _busy()
            change = None
            with _jlock:
                if busy and not _cur["paused"]:
                    _signal(p, signal.SIGSTOP)
                    _cur["paused"], _cur["idle_since"] = True, 0
                    change = "paused"
                elif _cur["paused"]:
                    if busy:
                        _cur["idle_since"] = 0
                    elif not _cur["idle_since"]:
                        _cur["idle_since"] = now
                    elif now - _cur["idle_since"] >= RESUME_IDLE_S:
                        _signal(p, signal.SIGCONT)
                        _cur["paused"] = False
                        change = "running"
            if change:
                log.info("offline job %s %s", j["id"], "paused for playback" if change == "paused" else "resumed")
                _set_status(j["id"], change)
            if now - last_db > 2:
                last_db = now
                with db.tx() as c:
                    c.execute("UPDATE offline_jobs SET progress=? WHERE id=?", (prog[0], j["id"]))
                if _stop_flag[0] or not _wanted(j["id"]):
                    cancelled = True
                    _signal(p, signal.SIGCONT)
                    _signal(p, signal.SIGTERM)
                    break
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _signal(p, signal.SIGKILL)
            p.wait()
    finally:
        with _jlock:
            _cur.update(proc=None, job=None, paused=False, idle_since=0)
    for t in readers:
        t.join(timeout=2)
    if cancelled:
        return "cancelled", ""
    ok = p.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 1000
    return ("ok" if ok else "fail"), " | ".join(err_lines[-3:])


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rm(p):
    try:
        p.unlink()
    except OSError:
        pass


def run_job(j):
    item = _item(j["item_id"])
    if not item or not os.path.exists(item.get("path") or ""):
        _fail(j, "The source file isn't reachable")
        return
    OFFLINE_DIR.mkdir(parents=True, exist_ok=True)
    name = job_name(j["item_id"], j["profile"], j["audio"])
    tmp = OFFLINE_DIR / (name + ".part")
    plan = stages_for(j["profile"])
    if not plan:
        _fail(j, "HEVC downloads need hardware transcoding")
        return
    with db.tx() as c:
        c.execute("UPDATE offline_jobs SET status='running', started_at=?, progress=0, error=NULL WHERE id=?",
                  (int(time.time()), j["id"]))
    err = ""
    for st, hw in plan:
        _rm(tmp)
        enc = "cpu" if st == "cpu" else hw[0]
        with db.tx() as c:
            c.execute("UPDATE offline_jobs SET encoder=? WHERE id=?", (enc, j["id"]))
        log.info("offline job %s: item %s %s audio %s on %s (%s)", j["id"], j["item_id"], j["profile"], j["audio"], enc, st)
        try:
            res, err = _run_stage(j, item, st, hw, tmp)
        except (OSError, ValueError) as e:
            res, err = "fail", str(e)
        if res == "cancelled":
            _rm(tmp)
            with db.tx() as c:
                c.execute("UPDATE offline_jobs SET status='queued', progress=0 WHERE id=?", (j["id"],))
            if not _wanted(j["id"]):
                with db.tx() as c:
                    c.execute("DELETE FROM offline_jobs WHERE id=? AND status!='ready'", (j["id"],))
            log.info("offline job %s stopped (nobody is waiting for it, or the server is stopping)", j["id"])
            return
        if res == "ok":
            final = OFFLINE_DIR / name
            tmp.replace(final)
            size, sha = final.stat().st_size, _sha256(final)
            now = int(time.time())
            with db.tx() as c:
                c.execute("UPDATE offline_jobs SET status='ready', progress=1, path=?, bytes=?, sha256=?, finished_at=?, "
                          "last_access=?, error=NULL WHERE id=?", (name, size, sha, now, now, j["id"]))
                grants = c.execute("SELECT id, user_id FROM offline_grants WHERE job_id=? AND state='preparing'",
                                   (j["id"],)).fetchall()
                c.execute("UPDATE offline_grants SET state='ready', bytes=?, sha256=? WHERE job_id=? AND state='preparing'",
                          (size, sha, j["id"]))
            for g in grants:
                useractivity.record("download_ready", user_id=g[1], actor=(_user_row(g[1]) or {}).get("username"),
                                    item=_brief(item), detail={"grant_id": g[0], "bytes": size, "encoder": enc})
            log.info("offline job %s ready (%d bytes, %s)", j["id"], size, enc)
            evict_lru()
            return
        log.warning("offline job %s stage %s failed: %s", j["id"], st, err)
        if st != "cpu" and hw[0]:
            try:
                hwaccel.note_failure(hw[0], hw[1], st, "offline download: " + (err or "ffmpeg failed")[:200])
            except Exception:
                pass
    _rm(tmp)
    _fail(j, err or "ffmpeg failed")


def _fail(j, why):
    now = int(time.time())
    with db.tx() as c:
        c.execute("UPDATE offline_jobs SET status='failed', error=?, finished_at=? WHERE id=?", (why[:300], now, j["id"]))
        grants = c.execute("SELECT id, user_id, item_id, title FROM offline_grants WHERE job_id=? AND state='preparing'",
                           (j["id"],)).fetchall()
        c.execute("UPDATE offline_grants SET state='failed', revoke_reason=? WHERE job_id=? AND state='preparing'",
                  ("couldn't be prepared", j["id"]))
    for g in grants:
        useractivity.record("download_failed", user_id=g[1], actor=(_user_row(g[1]) or {}).get("username"),
                            item={"id": g[2], "title": g[3]}, detail={"grant_id": g[0], "reason": why[:200]})


def _cancel_orphan_jobs():
    with db.tx() as c:
        c.execute("DELETE FROM offline_jobs WHERE status IN ('queued','failed') AND NOT EXISTS (SELECT 1 FROM offline_grants g "
                  "WHERE g.job_id=offline_jobs.id AND g.state='preparing')")
    kick()       # a running job notices within ~2 s and stops


def loop(stop_flag):
    """One offline transcode at a time; a job never starts while someone is streaming."""
    try:
        with db.tx() as c:
            c.execute("UPDATE offline_jobs SET status='queued' WHERE status IN ('running','paused')")
    except Exception:
        log.exception("offline jobs reset")
    for _ in range(int(os.environ.get("MS_OFFLINE_START_DELAY", "10"))):
        if stop_flag():
            return
        time.sleep(1)
    while not stop_flag():
        try:
            j = db.row("SELECT * FROM offline_jobs WHERE status='queued' ORDER BY created_at, id LIMIT 1")
            if j and not _wanted(j["id"]):
                _cancel_orphan_jobs()
                continue
            if j and not _busy():
                run_job(j)
                continue
        except Exception:
            log.exception("offline job loop")
        _wake.wait(3)
        _wake.clear()


def stop():
    _stop_flag[0] = True
    with _jlock:
        p = _cur.get("proc")
    if p is not None:
        _signal(p, signal.SIGCONT)
        _signal(p, signal.SIGTERM)


def evict_lru():
    cap = int(cfg("offline_cache_gb") * 1024 ** 3)
    rows = db.rows("SELECT * FROM offline_jobs WHERE status='ready' ORDER BY COALESCE(last_access, finished_at, 0)")
    total = sum(int(r.get("bytes") or 0) for r in rows)
    for r in rows:
        if total <= cap:
            break
        if db.row("SELECT 1 x FROM offline_grants WHERE job_id=? AND state='ready'", (r["id"],)):
            continue          # someone still has to download it
        _rm(OFFLINE_DIR / (r.get("path") or "-"))
        with db.tx() as c:
            c.execute("UPDATE offline_jobs SET status='evicted', path=NULL WHERE id=?", (r["id"],))
        total -= int(r.get("bytes") or 0)
        log.info("offline cache: removed %s (%s bytes)", r.get("path"), r.get("bytes"))


def cache_stats():
    r = db.row("SELECT COUNT(*) n, COALESCE(SUM(bytes),0) b FROM offline_jobs WHERE status='ready'")
    q = db.row("SELECT COUNT(*) n FROM offline_jobs WHERE status IN ('queued','running','paused')")
    return {"files": int(r["n"]), "bytes": int(r["b"]), "cap_gb": cfg("offline_cache_gb"), "queued": int(q["n"])}


def status_brief():
    with _jlock:
        return {"job": _cur.get("job"), "paused": bool(_cur.get("paused"))}
