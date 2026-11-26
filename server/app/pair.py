"""2.0.2: TV / living-room sign-in with a short code (and QR) that a signed-in phone approves.

Codes are 6 characters from a no-ambiguity alphabet, last 10 minutes, and are single-use.
The TV keeps a secret poll token; after approval the next poll creates a normal session
cookie for that user (same hashed-token sessions as password sign-in). Rate limits use
the real client address (trusted_proxies / CF-Connecting-IP).
"""
from __future__ import annotations

import hashlib
import secrets
import time

from fastapi import HTTPException

from . import auth, db, netutil, useractivity

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
CODE_LEN = 6
TTL_S = 10 * 60
START_LIMIT = 10         # new codes per IP per window (2.1.1)
START_WINDOW = 10 * 60
APPROVE_LIMIT = 20
APPROVE_WINDOW = 10 * 60
POLL_LIMIT = 90
POLL_WINDOW = 10 * 60

_hits: dict = {}
_live: dict = {}  # ip|ua -> last pending code (in memory only)


def _hash(kind, val) -> str:
    return hashlib.sha256(("ms-pair:%s:%s" % (kind, val or "")).encode()).hexdigest()


def normalize(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "").replace("-", "")


def display(code: str) -> str:
    c = normalize(code)
    if len(c) == 6:
        return c[:3] + "-" + c[3:]
    return c


def _allowed(bucket, ip, limit, window) -> bool:
    now = time.time()
    key = "%s:%s" % (bucket, ip or "?")
    lst = [t for t in _hits.get(key, []) if now - t < window]
    _hits[key] = lst
    if len(_hits) > 4000:
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > window]:
            _hits.pop(k, None)
    if len(lst) >= limit:
        return False
    lst.append(now)
    _hits[key] = lst
    return True


def _cleanup(c=None, now=None):
    now = int(now or time.time())
    close = c is None
    if c is None:
        c = db.get()
    c.execute("UPDATE pair_codes SET status='expired' WHERE status IN ('pending','approved') AND expires_at < ?", (now,))
    c.execute("DELETE FROM pair_codes WHERE expires_at < ? OR (status IN ('consumed','expired','denied') AND created_at < ?)",
              (now - 3600, now - 86400))
    if close:
        c.commit()


def start(request, base_url: str = "", force: bool = False) -> dict:
    """Create a pending code for the TV. Returns the short code, the poll token, and a QR URL.

    2.1.1: rate-limit buckets use netutil.client_ip (trusted_proxies / CF-Connecting-IP).
    A new code is minted only when force=True or there is no in-memory live code for this
    (IP, UA) still pending. The password sign-in path is not rate-limited here.
    """
    ip = netutil.client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:400]
    now = int(time.time())
    live_key = "%s|%s" % (ip or "?", ua)
    if not force:
        live = _live.get(live_key)
        if live and live["expires_at"] > now:
            out = dict(live)
            out["expires_in"] = max(0, int(live["expires_at"]) - now)
            return out
    if not _allowed("start", ip, START_LIMIT, START_WINDOW):
        raise HTTPException(429, "Too many sign-in codes from this address; wait a few minutes")
    device = auth._device_name(ua) or "Television"
    if "AndroidTV" in ua or "Android TV" in ua or "BRAVIA" in ua or "AFT" in ua:
        if "TV" not in device and "Television" not in device:
            device = "Android TV"
    code = poll = None
    with db.tx() as c:
        _cleanup(c, now)
        for _ in range(8):
            cand = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
            exists = c.execute("SELECT 1 FROM pair_codes WHERE code_hash=?", (_hash("code", cand),)).fetchone()
            if not exists:
                code = cand
                break
        if not code:
            raise HTTPException(503, "Couldn't make a sign-in code; try again")
        poll = secrets.token_urlsafe(32)
        c.execute(
            "INSERT INTO pair_codes(code_hash, poll_hash, created_at, expires_at, status, device, ua, ip) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (_hash("code", code), _hash("poll", poll), now, now + TTL_S, "pending", device, ua, ip),
        )
    base = (base_url or "").rstrip("/")
    url = (base + "/pair?code=" + code) if base else ("/pair?code=" + code)
    out = {
        "code": code,
        "display": display(code),
        "poll_token": poll,
        "expires_at": now + TTL_S,
        "expires_in": TTL_S,
        "url": url,
        "device": device,
    }
    _live[live_key] = dict(out)
    return out


def poll(request, token: str) -> dict:
    """TV: wait for approval. When approved, a session cookie is set (caller should pass the Response)."""
    ip = netutil.client_ip(request)
    if not _allowed("poll", ip, POLL_LIMIT, POLL_WINDOW):
        raise HTTPException(429, "Too many checks; wait a moment")
    if not token or len(token) < 16:
        raise HTTPException(400, "Missing sign-in token")
    now = int(time.time())
    ph = _hash("poll", token)
    with db.tx() as c:
        _cleanup(c, now)
        row = c.execute("SELECT * FROM pair_codes WHERE poll_hash=?", (ph,)).fetchone()
        if not row:
            return {"status": "unknown"}
        row = dict(row)
        if row["status"] == "pending":
            if row["expires_at"] <= now:
                c.execute("UPDATE pair_codes SET status='expired' WHERE id=?", (row["id"],))
                return {"status": "expired"}
            return {"status": "pending", "expires_in": max(0, row["expires_at"] - now), "device": row.get("device")}
        if row["status"] in ("expired", "denied", "consumed"):
            return {"status": row["status"]}
        if row["status"] != "approved" or not row.get("user_id"):
            return {"status": "pending", "expires_in": max(0, row["expires_at"] - now)}
        # Claim the code and create a normal session in the same commit (no nested tx).
        cur = c.execute("UPDATE pair_codes SET status='consumed' WHERE id=? AND status='approved'", (row["id"],))
        if cur.rowcount != 1:
            return {"status": "consumed"}
        import secrets
        from . import config
        ua = row.get("ua") or request.headers.get("user-agent")
        tok = secrets.token_urlsafe(32)
        now_i = int(time.time())
        c.execute(
            "INSERT INTO sessions(token,user_id,created_at,expires_at,ip,ua,last_seen,device) VALUES(?,?,?,?,?,?,?,?)",
            (auth.token_hash(tok), row["user_id"], now_i, now_i + config.SESSION_DAYS * 86400,
             ip, (ua or "")[:400], now_i, auth._device_name(ua)),
        )
        urow = c.execute("SELECT id, username FROM users WHERE id=?", (row["user_id"],)).fetchone()
        u = dict(urow) if urow else {"id": row["user_id"], "username": ""}
    useractivity.record(
        "login", user=u, ip=ip,
        device=auth._device_name(ua),
        detail={"method": "pair", "device": row.get("device")},
    )
    return {"status": "approved", "token": tok, "username": (u or {}).get("username") or ""}


def info(request, code: str, user) -> dict:
    """Signed-in phone: who would this code sign in, and which device is waiting."""
    code = normalize(code)
    if len(code) != CODE_LEN or any(ch not in ALPHABET for ch in code):
        raise HTTPException(400, "That code isn't valid")
    now = int(time.time())
    with db.tx() as c:
        _cleanup(c, now)
        row = c.execute("SELECT * FROM pair_codes WHERE code_hash=?", (_hash("code", code),)).fetchone()
    if not row:
        raise HTTPException(404, "That code is not valid or has expired")
    row = dict(row)
    if row["status"] == "expired" or row["expires_at"] <= now:
        raise HTTPException(404, "That code has expired. Start again on the TV.")
    if row["status"] != "pending":
        raise HTTPException(409, "That code was already used")
    return {
        "code": display(code),
        "device": row.get("device") or "A television",
        "expires_in": max(0, row["expires_at"] - now),
        "username": user.get("username"),
    }


def approve(request, code: str, user) -> dict:
    """Signed-in phone: approve the waiting TV as this user."""
    ip = netutil.client_ip(request)
    if not _allowed("approve", ip, APPROVE_LIMIT, APPROVE_WINDOW):
        raise HTTPException(429, "Too many approvals from this address; wait a few minutes")
    if user.get("disabled_at"):
        raise HTTPException(403, "This account is turned off. Ask the server admin.")
    code = normalize(code)
    if len(code) != CODE_LEN or any(ch not in ALPHABET for ch in code):
        raise HTTPException(400, "That code isn't valid")
    now = int(time.time())
    with db.tx() as c:
        _cleanup(c, now)
        row = c.execute("SELECT * FROM pair_codes WHERE code_hash=?", (_hash("code", code),)).fetchone()
        if not row:
            raise HTTPException(404, "That code is not valid or has expired")
        row = dict(row)
        if row["status"] == "expired" or row["expires_at"] <= now:
            c.execute("UPDATE pair_codes SET status='expired' WHERE id=?", (row["id"],))
            raise HTTPException(404, "That code has expired. Start again on the TV.")
        if row["status"] != "pending":
            raise HTTPException(409, "That code was already used")
        c.execute(
            "UPDATE pair_codes SET status='approved', user_id=?, approved_at=?, approver_ip=? WHERE id=?",
            (user["id"], now, ip, row["id"]),
        )
    return {"ok": True, "device": row.get("device") or "A television"}


def deny(request, code: str, user) -> dict:
    code = normalize(code)
    now = int(time.time())
    with db.tx() as c:
        row = c.execute("SELECT * FROM pair_codes WHERE code_hash=?", (_hash("code", code),)).fetchone()
        if not row:
            raise HTTPException(404, "That code is not valid or has expired")
        row = dict(row)
        if row["status"] != "pending":
            raise HTTPException(409, "That code was already used")
        c.execute("UPDATE pair_codes SET status='denied' WHERE id=?", (row["id"],))
    return {"ok": True}
