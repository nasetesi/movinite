"""2.1: library sharing between Movinite servers (federation).

Pairing uses a one-time share code (or link). After that, every server-to-server
call is an Ed25519-signed HTTP request using this server's identity key
(data/secrets/server_ed25519). Tokens and share codes are stored hashed.
Public docs use 192.0.2.10; this module never logs secrets or raw codes.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional
from urllib.parse import urlparse

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse

from . import auth, config, db, keys, netutil, settings, useractivity
from .version import __version__

log = logging.getLogger("media-server")

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 12
CODE_TTL = 48 * 3600
SKEW_S = 5 * 60
NONCE_TTL = 10 * 60
TICKET_TTL = 6 * 3600
SYNC_EVERY = 6 * 3600
START_LIMIT, START_WINDOW = 8, 10 * 60
PAIR_LIMIT, PAIR_WINDOW = 20, 10 * 60

_hits: dict = {}
_nonces: dict = {}
_nonce_lock = threading.Lock()
_tickets: dict = {}
_ticket_lock = threading.Lock()
_stop = False


def _hash(kind, val) -> str:
    return hashlib.sha256(("ms-fed:%s:%s" % (kind, val or "")).encode()).hexdigest()


def normalize_code(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "").replace("-", "")


def display_code(code: str) -> str:
    c = normalize_code(code)
    if len(c) == 12:
        return "%s-%s-%s" % (c[0:4], c[4:8], c[8:12])
    return c


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))


def server_name() -> str:
    n = (settings.get("server_name") or "").strip()
    if n:
        return n[:80]
    try:
        return (os.uname().nodename or "Movinite")[:80]
    except Exception:
        return "Movinite"


def pubkey_b64() -> str:
    return base64.b64encode(keys.public_bytes()).decode()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64url(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode((s or "") + pad)


def _allowed(bucket, ip, limit, window) -> bool:
    now = time.time()
    key = "%s:%s" % (bucket, ip or "?")
    lst = [t for t in _hits.get(key, []) if now - t < window]
    if len(lst) >= limit:
        _hits[key] = lst
        return False
    lst.append(now)
    _hits[key] = lst
    if len(_hits) > 4000:
        for k in [k for k, v in list(_hits.items()) if not v or now - v[-1] > window]:
            _hits.pop(k, None)
    return True


# ---- URL policy -------------------------------------------------------------
def is_lan_host(host: str) -> bool:
    host = (host or "").split("%")[0]
    if not host or host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local)
    except ValueError:
        return False


def check_peer_url(url: str, typed_by_admin: bool = False) -> str:
    """Return a cleaned URL or raise. HTTPS is required except for LAN addresses an admin types."""
    u = (url or "").strip().rstrip("/")
    if not u:
        raise HTTPException(400, "Enter the other server's address")
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise HTTPException(400, "Enter a full URL, for example https://media.example.com")
    host = (p.hostname or "")
    if p.scheme == "http" and not is_lan_host(host):
        if not typed_by_admin:
            raise HTTPException(400, "Public server addresses must use HTTPS")
        raise HTTPException(400, "Public server addresses must use HTTPS (plain HTTP is only for a LAN address)")
    return u


# ---- signed HTTP ------------------------------------------------------------
def canonical(method, path, query, date, body, nonce) -> bytes:
    digest = hashlib.sha256(body or b"").hexdigest()
    q = query or ""
    if q.startswith("?"):
        q = q[1:]
    return ("\n".join([method.upper(), path, q, date, digest, nonce])).encode()


def sign_headers(method, path, query="", body=b"", extra=None) -> dict:
    if not keys.ensure():
        raise HTTPException(503, "This server's identity key is not available")
    date = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    nonce = secrets.token_hex(16)
    sig = base64.b64encode(keys.sign(canonical(method, path, query, date, body or b"", nonce))).decode()
    h = {
        "X-Movinite-Server": keys.server_id(),
        "X-Movinite-Key": pubkey_b64(),
        "X-Movinite-Date": date,
        "X-Movinite-Nonce": nonce,
        "X-Movinite-Signature": sig,
        "User-Agent": "Movinite/%s" % __version__,
        "Accept": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def _parse_date(s: str) -> int:
    s = (s or "").strip()
    try:
        return int(time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone)
    except Exception:
        raise HTTPException(401, "Bad date")


def _remember_nonce(nonce: str):
    now = time.time()
    with _nonce_lock:
        if nonce in _nonces and now - _nonces[nonce] < NONCE_TTL:
            raise HTTPException(401, "Replay")
        _nonces[nonce] = now
        if len(_nonces) > 8000:
            cut = now - NONCE_TTL
            for k, t in list(_nonces.items()):
                if t < cut:
                    _nonces.pop(k, None)


def verify_signed(request: Request, body: bytes, require_peer: bool = True, allow_key: Optional[str] = None):
    """Verify an incoming signed request. Returns (peer_row_or_None, server_id, pubkey_b64)."""
    hid = request.headers.get("x-movinite-server") or ""
    hkey = request.headers.get("x-movinite-key") or allow_key or ""
    date = request.headers.get("x-movinite-date") or ""
    nonce = request.headers.get("x-movinite-nonce") or ""
    sig = request.headers.get("x-movinite-signature") or ""
    if not (hid and date and nonce and sig):
        raise HTTPException(401, "Missing signature headers")
    ts = _parse_date(date)
    if abs(int(time.time()) - ts) > SKEW_S:
        raise HTTPException(401, "Clock skew too large")
    if len(nonce) < 8 or len(nonce) > 80:
        raise HTTPException(401, "Bad nonce")
    _remember_nonce(nonce)
    peer = db.row("SELECT * FROM peers WHERE server_id=?", (hid,))
    pub = None
    if peer and peer.get("pubkey"):
        pub = peer["pubkey"]
    elif hkey:
        pub = hkey
    if not pub:
        raise HTTPException(401, "Unknown peer")
    if require_peer:
        if not peer or peer["status"] != "active":
            raise HTTPException(403, "Peer is not active")
    try:
        raw_pub = base64.b64decode(pub)
        raw_sig = base64.b64decode(sig)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        path = request.url.path
        query = request.url.query or ""
        Ed25519PublicKey.from_public_bytes(raw_pub).verify(
            raw_sig, canonical(request.method, path, query, date, body or b"", nonce))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Bad signature")
    if hid != _server_id_from_pub(pub):
        # The stated server id must match the key, so a stolen id cannot ride on another key.
        if hid != (peer["server_id"] if peer else _server_id_from_pub(pub)):
            raise HTTPException(401, "Server id does not match the key")
    return peer, hid, pub


def _server_id_from_pub(pub_b64: str) -> str:
    raw = base64.b64decode(pub_b64)
    return base64.b32encode(hashlib.sha256(raw).digest()).decode().rstrip("=")[:20]


def call(url_base, method, path, query="", obj=None, timeout=20, extra_headers=None):
    """Signed HTTP call to another Movinite server. Returns (status, parsed json or bytes, headers)."""
    body = b""
    if obj is not None:
        body = json.dumps(obj).encode()
    base = (url_base or "").rstrip("/")
    q = ("?" + query) if query else ""
    url = base + path + q
    headers = sign_headers(method, path, query, body, extra_headers)
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body or None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type") or ""
            out = json.loads(data.decode()) if "json" in ctype or (data[:1] in (b"{", b"[")) else data
            return resp.status, out, dict(resp.headers)
    except urllib.error.HTTPError as e:
        data = e.read()
        try:
            msg = json.loads(data.decode()).get("detail") or data.decode()[:300]
        except Exception:
            msg = (data or b"").decode("utf-8", "replace")[:300] or e.reason
        raise HTTPException(e.code, msg)
    except urllib.error.URLError as e:
        raise HTTPException(502, "Could not reach the other server (%s)" % (getattr(e, "reason", e) or "network"))


# ---- hello / identity -------------------------------------------------------
def hello_public(code: str = "") -> dict:
    out = {
        "name": server_name(),
        "server_id": keys.server_id() if keys.ensure() else None,
        "fingerprint": keys.fingerprint() if keys.ensure() else None,
        "version": __version__,
        "pubkey": pubkey_b64() if keys.ensure() else None,
    }
    c = normalize_code(code)
    if c:
        row = _find_code(c)
        if not row:
            raise HTTPException(404, "That share code is not valid or has expired")
        out["offered"] = _offered_from_code(row)
        out["label"] = row.get("label")
        out["expires_at"] = row["expires_at"]
    return out


def _find_code(code: str):
    now = int(time.time())
    row = db.row("SELECT * FROM share_codes WHERE code_hash=? AND revoked_at IS NULL AND used_at IS NULL AND expires_at>?",
                 (_hash("code", normalize_code(code)), now))
    return row


def _offered_from_code(row) -> list:
    try:
        ids = json.loads(row["libraries"] or "[]")
    except Exception:
        ids = []
    out = []
    for i in ids:
        lib = db.row("SELECT id, name, kind FROM libraries WHERE id=?", (int(i),))
        if not lib:
            continue
        n = db.row("SELECT COUNT(*) n FROM items WHERE library_id=?", (lib["id"],))["n"]
        out.append({"id": lib["id"], "name": lib["name"], "kind": lib["kind"], "item_count": n})
    return out


# ---- admin: create / list share codes ---------------------------------------
def create_share_code(admin, body: dict, base_url: str = "") -> dict:
    if not keys.ensure():
        raise HTTPException(503, "This server's identity key is not available")
    libs = body.get("libraries") or body.get("library_ids") or []
    if not isinstance(libs, list) or not libs or not all(str(x).isdigit() or isinstance(x, int) for x in libs):
        raise HTTPException(400, "Pick one or more libraries to share")
    ids = [int(x) for x in libs]
    for i in ids:
        if not db.row("SELECT id FROM libraries WHERE id=?", (i,)):
            raise HTTPException(400, "Unknown library %s" % i)
    perms = (body.get("perms") or body.get("permission") or "stream").strip().lower()
    if perms not in ("stream", "download", "stream+download"):
        perms = "stream" if perms != "download" else "download"
    if perms == "stream+download":
        perms = "download"
    limits = {
        "max_quality": body.get("max_quality") or "1080p",
        "max_streams": int(body.get("max_streams") or 2),
        "max_mbps": int(body.get("max_mbps") or 20),
        "allow_transcode": 0 if body.get("allow_transcode") in (0, False, "0") else 1,
        "can_download": 1 if perms == "download" else 0,
    }
    ttl = int(body.get("ttl") or CODE_TTL)
    ttl = max(3600, min(ttl, 14 * 86400))
    now = int(time.time())
    raw = new_code()
    with db.tx() as c:
        c.execute("INSERT INTO share_codes(code_hash, libraries, perms, limits, label, created_by, created_at, expires_at) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  (_hash("code", raw), json.dumps(ids), perms, json.dumps(limits),
                   (body.get("label") or "").strip()[:80] or None, admin["id"], now, now + ttl))
        cid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    useractivity.record("share_code", user=admin, actor=admin, detail="created a share link")
    code = display_code(raw)
    origin = (base_url or "").rstrip("/")
    link = "%s/#/share/%s" % (origin, raw) if origin else "#/share/%s" % raw
    return {
        "id": cid, "code": code, "link": link,
        "fingerprint": keys.fingerprint(), "name": server_name(),
        "expires_at": now + ttl, "libraries": _offered_from_code({"libraries": json.dumps(ids), **{"expires_at": now + ttl}}),
        "perms": perms, "limits": limits,
    }


def list_codes():
    now = int(time.time())
    rows = db.rows("SELECT * FROM share_codes ORDER BY created_at DESC LIMIT 50")
    out = []
    for r in rows:
        st = "revoked" if r.get("revoked_at") else ("used" if r.get("used_at") else ("expired" if r["expires_at"] <= now else "pending"))
        out.append({
            "id": r["id"], "status": st, "label": r.get("label"), "perms": r["perms"],
            "libraries": _offered_from_code(r), "created_at": r["created_at"], "expires_at": r["expires_at"],
            "used_at": r.get("used_at"), "used_by_peer": r.get("used_by_peer"),
        })
    return out


def revoke_code(code_id: int, admin):
    with db.tx() as c:
        row = c.execute("SELECT * FROM share_codes WHERE id=?", (code_id,)).fetchone()
        if not row:
            raise HTTPException(404, "No such share code")
        c.execute("UPDATE share_codes SET revoked_at=? WHERE id=?", (int(time.time()), code_id))
    useractivity.record("share_code", user=admin, actor=admin, detail="revoked a share link")
    return {"ok": True}


# ---- pairing ----------------------------------------------------------------
def pair_incoming(request: Request, body: dict):
    """A: B is redeeming a share code."""
    raw = request.state._fed_body if hasattr(request.state, "_fed_body") else json.dumps(body).encode()
    ip = netutil.client_ip(request)
    if not _allowed("pair", ip, PAIR_LIMIT, PAIR_WINDOW):
        raise HTTPException(429, "Too many pairing attempts; wait a few minutes")
    peer, hid, pub = verify_signed(request, raw if isinstance(raw, (bytes, bytearray)) else json.dumps(body).encode(),
                                   require_peer=False, allow_key=body.get("pubkey"))
    code = normalize_code(body.get("code") or "")
    row = _find_code(code)
    if not row:
        raise HTTPException(404, "That share code is not valid or has expired")
    name = (body.get("name") or "").strip()[:80] or "Shared server"
    url = (body.get("url") or "").strip()
    if url:
        try:
            url = check_peer_url(url, typed_by_admin=is_lan_host(urlparse(url).hostname or ""))
        except HTTPException:
            url = url.rstrip("/")
    now = int(time.time())
    libs = json.loads(row["libraries"] or "[]")
    limits = json.loads(row["limits"] or "{}")
    can_dl = 1 if (row["perms"] == "download" or limits.get("can_download")) else 0
    with db.tx() as c:
        existing = c.execute("SELECT * FROM peers WHERE server_id=?", (hid,)).fetchone()
        if existing:
            pid = existing["id"]
            direction = "both" if existing["direction"] == "incoming" or existing["direction"] == "both" else "outgoing"
            # existing direction from our side: if we already shared to them it's outgoing; they share to us incoming
            if existing["direction"] == "incoming":
                direction = "both"
            elif existing["direction"] == "outgoing":
                direction = "both"
            else:
                direction = existing["direction"] or "outgoing"
            c.execute("UPDATE peers SET name=?, url=COALESCE(NULLIF(?,''), url), pubkey=?, direction=?, status='active', "
                      "last_seen=?, last_error=NULL WHERE id=?",
                      (name, url, pub, direction, now, pid))
        else:
            c.execute("INSERT INTO peers(server_id, name, url, pubkey, direction, status, created_at, last_seen) "
                      "VALUES(?,?,?,?, 'outgoing','active',?,?)",
                      (hid, name, url or None, pub, now, now))
            pid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("DELETE FROM peer_grants WHERE peer_id=?", (pid,))
        for lid in libs:
            c.execute("INSERT INTO peer_grants(peer_id, library_id, can_stream, can_download, max_quality, max_streams, "
                      "max_mbps, allow_transcode) VALUES(?,?,1,?,?,?,?,?)",
                      (pid, int(lid), can_dl, limits.get("max_quality") or "1080p",
                       int(limits.get("max_streams") or 2), int(limits.get("max_mbps") or 20),
                       int(limits.get("allow_transcode") if limits.get("allow_transcode") is not None else 1)))
        c.execute("UPDATE share_codes SET used_at=?, used_by_peer=? WHERE id=?", (now, pid, row["id"]))
    useractivity.record("share_pair", detail="accepted a share from %s" % name)
    offered = _offered_from_code(row)
    return {
        "ok": True,
        "name": server_name(),
        "server_id": keys.server_id(),
        "fingerprint": keys.fingerprint(),
        "pubkey": pubkey_b64(),
        "libraries": offered,
        "peer_id": pid,
    }


def accept_share(admin, body: dict):
    """B: paste a link or URL + code, then accept. Creates an incoming peer and syncs the catalog."""
    if not keys.ensure():
        raise HTTPException(503, "This server's identity key is not available")
    url = (body.get("url") or "").strip()
    code = normalize_code(body.get("code") or "")
    link = (body.get("link") or "").strip()
    if link and not url:
        # https://host/#/share/CODE or ?c=
        p = urlparse(link)
        url = "%s://%s" % (p.scheme, p.netloc) if p.scheme and p.netloc else ""
        frag = (p.fragment or "")
        if "/share/" in frag:
            code = normalize_code(frag.split("/share/")[-1].split("?")[0].split("&")[0])
        qs = urllib.parse.parse_qs(p.query)
        if qs.get("c"):
            code = normalize_code(qs["c"][0])
        if "/share/" in (p.path or ""):
            code = normalize_code((p.path or "").split("/share/")[-1])
    if not url or not code:
        raise HTTPException(400, "Paste the share link, or the other server's address and the code")
    url = check_peer_url(url, typed_by_admin=True)
    # hello (public) to show name + offered libs — if this is the confirm step we go on to pair
    if not body.get("confirm"):
        try:
            req = urllib.request.Request(url.rstrip("/") + "/api/fed/hello?c=" + urllib.parse.quote(code),
                                         headers={"Accept": "application/json", "User-Agent": "Movinite/%s" % __version__})
            with urllib.request.urlopen(req, timeout=15) as resp:
                info = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise HTTPException(e.code, (e.read() or b"").decode("utf-8", "replace")[:300] or "The other server refused the code")
        except Exception as e:
            raise HTTPException(502, "Could not reach the other server")
        return {"preview": True, "hello": info, "url": url, "code": display_code(code)}
    my_url = (body.get("my_url") or "").strip()
    payload = {"code": code, "name": server_name(), "url": my_url, "pubkey": pubkey_b64()}
    log.info("accept: pairing with %s", url)
    status, data, _h = call(url, "POST", "/api/fed/pair", obj=payload, timeout=20)
    log.info("accept: pair returned %s", status)
    if not isinstance(data, dict) or not data.get("ok"):
        raise HTTPException(status, "Pairing failed")
    pub = data.get("pubkey")
    sid = data.get("server_id") or (_server_id_from_pub(pub) if pub else None)
    if not sid or not pub:
        raise HTTPException(502, "The other server did not return its identity")
    now = int(time.time())
    name = (data.get("name") or "Shared server")[:80]
    with db.tx() as c:
        existing = c.execute("SELECT * FROM peers WHERE server_id=?", (sid,)).fetchone()
        if existing:
            pid = existing["id"]
            direction = "both" if existing["direction"] in ("outgoing", "both") else "incoming"
            c.execute("UPDATE peers SET name=?, url=?, pubkey=?, direction=?, status='active', last_seen=?, last_error=NULL WHERE id=?",
                      (name, url, pub, direction, now, pid))
        else:
            c.execute("INSERT INTO peers(server_id, name, url, pubkey, direction, status, created_at, last_seen, proxy) "
                      "VALUES(?,?,?,?,'incoming','active',?,?,?)",
                      (sid, name, url, pub, now, now, 0 if urlparse(url).scheme == "https" else 1))
            pid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        for lib in data.get("libraries") or []:
            row = c.execute("SELECT id FROM remote_libraries WHERE peer_id=? AND remote_library_id=?",
                            (pid, int(lib["id"]))).fetchone()
            if row:
                c.execute("UPDATE remote_libraries SET name=?, kind=?, item_count=?, hidden_at=NULL WHERE id=?",
                          (lib.get("name"), lib.get("kind"), lib.get("item_count"), row[0]))
                rlid = row[0]
            else:
                c.execute("INSERT INTO remote_libraries(peer_id, remote_library_id, name, kind, item_count) "
                          "VALUES(?,?,?,?,?)",
                          (pid, int(lib["id"]), lib.get("name"), lib.get("kind"), lib.get("item_count") or 0))
                rlid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    useractivity.record("share_accept", user=admin, actor=admin, detail="accepted libraries from %s" % name)
    try:
        log.info("accept: syncing catalog for peer %s", pid)
        sync_peer(pid)
        log.info("accept: sync done")
    except Exception:
        log.exception("catalog sync after pair")
    return {"ok": True, "peer_id": pid, "name": name, "fingerprint": data.get("fingerprint"),
            "libraries": list_remote_libraries(pid)}


# ---- catalog (A side + B sync) ----------------------------------------------
def _grant(peer_id, library_id):
    return db.row("SELECT * FROM peer_grants WHERE peer_id=? AND library_id=?", (peer_id, library_id))


def fed_libraries(peer) -> list:
    out = []
    for g in db.rows("SELECT g.*, l.name, l.kind FROM peer_grants g JOIN libraries l ON l.id=g.library_id WHERE g.peer_id=?",
                     (peer["id"],)):
        n = db.row("SELECT COUNT(*) n FROM items WHERE library_id=?", (g["library_id"],))["n"]
        out.append({"id": g["library_id"], "name": g["name"], "kind": g["kind"], "item_count": n,
                    "can_stream": bool(g["can_stream"]), "can_download": bool(g["can_download"]),
                    "max_quality": g["max_quality"]})
    return out


def _item_summary(it) -> dict:
    # keep this small: titles, year, artwork names, tmdb, overview for the hero
    poster = it.get("poster")
    backdrop = it.get("backdrop")
    return {
        "id": it["id"],
        "kind": it.get("kind") or "movie",
        "title": it.get("title"),
        "year": it.get("year"),
        "tmdb_id": it.get("tmdb_id"),
        "sort_title": it.get("sort_title") or it.get("title"),
        "duration": it.get("duration"),
        "poster": poster,
        "backdrop": backdrop,
        "overview": it.get("overview"),
        "runtime": it.get("runtime"),
        "certification": it.get("certification"),
        "rating": it.get("rating"),
        "genres": it.get("genres") if isinstance(it.get("genres"), str) else json.dumps(it.get("genres") or []),
        "added_at": it.get("added_at"),
        "updated_at": it.get("added_at"),
    }


def fed_library_items(peer, library_id: int, since: int = 0, offset: int = 0, limit: int = 200) -> dict:
    if not _grant(peer["id"], library_id):
        raise HTTPException(403, "This library is not shared with you")
    lib = db.row("SELECT id, name, kind FROM libraries WHERE id=?", (library_id,))
    if not lib:
        raise HTTPException(404, "No such library")
    limit = max(1, min(int(limit or 200), 500))
    offset = max(0, int(offset or 0))
    since = int(since or 0)
    rows = db.rows(
        "SELECT * FROM items WHERE library_id=? AND COALESCE(added_at, 0) >= ? "
        "ORDER BY id LIMIT ? OFFSET ?", (library_id, since, limit, offset))
    total = db.row("SELECT COUNT(*) n FROM items WHERE library_id=? AND COALESCE(added_at, 0) >= ?",
                   (library_id, since))["n"]
    # enrich from metadata so the other server can show a hero
    try:
        from . import tmdb
        items = [dict(r) for r in rows]
        tmdb.enrich(items)
    except Exception:
        items = [dict(r) for r in rows]
    return {"library": {"id": lib["id"], "name": lib["name"], "kind": lib["kind"]},
            "total": total, "offset": offset, "items": [_item_summary(i) for i in items]}


def fed_item(peer, item_id: int) -> dict:
    it = db.row("SELECT * FROM items WHERE id=?", (item_id,))
    if not it:
        raise HTTPException(404, "No such item")
    if not _grant(peer["id"], it["library_id"]):
        raise HTTPException(403, "This library is not shared with you")
    item = dict(it)
    try:
        from . import tmdb
        tmdb.enrich([item])
    except Exception:
        pass
    # never leak file paths
    for k in ("path", "audio_streams", "subtitle_streams", "external_subs"):
        item.pop(k, None)
    return _item_summary(item)


def sync_peer(peer_id: int):
    peer = db.row("SELECT * FROM peers WHERE id=?", (peer_id,))
    if not peer or peer["status"] != "active" or not peer.get("url"):
        return
    try:
        _st, data, _h = call(peer["url"], "GET", "/api/fed/libraries", timeout=20)
    except HTTPException as e:
        with db.tx() as c:
            c.execute("UPDATE peers SET last_error=?, last_seen=? WHERE id=?",
                      (str(e.detail)[:200], int(time.time()), peer_id))
        raise
    libs = data if isinstance(data, list) else (data.get("libraries") or [])
    now = int(time.time())
    seen = set()
    with db.tx() as c:
        c.execute("UPDATE peers SET last_seen=?, last_error=NULL WHERE id=?", (now, peer_id))
        for lib in libs:
            rid = int(lib["id"])
            seen.add(rid)
            row = c.execute("SELECT id, last_sync FROM remote_libraries WHERE peer_id=? AND remote_library_id=?",
                            (peer_id, rid)).fetchone()
            if row:
                c.execute("UPDATE remote_libraries SET name=?, kind=?, item_count=?, hidden_at=NULL WHERE id=?",
                          (lib.get("name"), lib.get("kind"), lib.get("item_count") or 0, row[0]))
                rlid = row[0]
                since = row[1] or 0
            else:
                c.execute("INSERT INTO remote_libraries(peer_id, remote_library_id, name, kind, item_count) "
                          "VALUES(?,?,?,?,?)",
                          (peer_id, rid, lib.get("name"), lib.get("kind"), lib.get("item_count") or 0))
                rlid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
                since = 0
            _sync_items(c, peer, rlid, rid, since)
            c.execute("UPDATE remote_libraries SET last_sync=?, item_count=("
                      "SELECT COUNT(*) FROM remote_items WHERE remote_library_id=?) WHERE id=?",
                      (now, rlid, rlid))
        # libraries no longer offered
        for old in c.execute("SELECT id, remote_library_id FROM remote_libraries WHERE peer_id=? AND hidden_at IS NULL",
                             (peer_id,)).fetchall():
            if old[1] not in seen:
                c.execute("UPDATE remote_libraries SET hidden_at=? WHERE id=?", (now, old[0]))


def _sync_items(c, peer, rlid, remote_lib_id, since):
    offset = 0
    while True:
        _st, data, _h = call(peer["url"], "GET", "/api/fed/libraries/%d/items" % remote_lib_id,
                             query="since=%d&offset=%d&limit=200" % (int(since or 0), offset), timeout=30)
        items = (data or {}).get("items") or []
        for it in items:
            c.execute(
                "INSERT INTO remote_items(remote_library_id, remote_item_id, kind, title, year, tmdb_id, sort_title, "
                "duration, poster, backdrop, overview, runtime, certification, rating, genres, added_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(remote_library_id, remote_item_id) DO UPDATE SET "
                "kind=excluded.kind, title=excluded.title, year=excluded.year, tmdb_id=excluded.tmdb_id, "
                "sort_title=excluded.sort_title, duration=excluded.duration, poster=excluded.poster, "
                "backdrop=excluded.backdrop, overview=excluded.overview, runtime=excluded.runtime, "
                "certification=excluded.certification, rating=excluded.rating, genres=excluded.genres, "
                "added_at=excluded.added_at, updated_at=excluded.updated_at",
                (rlid, int(it["id"]), it.get("kind") or "movie", it.get("title"), it.get("year"), it.get("tmdb_id"),
                 it.get("sort_title") or it.get("title"), it.get("duration"), it.get("poster"), it.get("backdrop"),
                 it.get("overview"), it.get("runtime"), it.get("certification"), it.get("rating"),
                 it.get("genres") if isinstance(it.get("genres"), str) else json.dumps(it.get("genres") or []),
                 it.get("added_at"), it.get("added_at")))
            _cache_art(peer, it.get("poster"))
            _cache_art(peer, it.get("backdrop"))
        total = int((data or {}).get("total") or 0)
        offset += len(items)
        if not items or offset >= total:
            break


def fed_thumb(peer, name: str):
    """A: serve a cached thumb/poster to a signed-in peer."""
    import re
    if not re.match(r"^[0-9a-f]{40}\.(jpg|jpeg|png|webp)$", name or ""):
        raise HTTPException(404)
    for folder in ("thumbs", "logos"):
        pth = config.DATA_DIR / folder / name
        if pth.is_file():
            from fastapi.responses import FileResponse
            return FileResponse(str(pth), media_type="image/jpeg" if name.endswith((".jpg", ".jpeg")) else "image/png")
    raise HTTPException(404)


def _cache_art(peer, name):
    import re
    if not name or not re.match(r"^[0-9a-f]{40}\.(jpg|jpeg|png|webp)$", str(name)):
        return
    dest = config.DATA_DIR / "thumbs"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / name
    if path.is_file():
        return
    try:
        _st, data, _h = call(peer["url"], "GET", "/api/fed/thumb/%s" % name, timeout=20)
        if isinstance(data, (bytes, bytearray)) and len(data) > 32:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
    except Exception:
        log.debug("thumb fetch failed for %s", name, exc_info=True)


def sync_loop(stop_flag):
    """Background catalog refresh every 6 hours (plus a first pass a minute after start)."""
    time.sleep(8)
    while not stop_flag():
        try:
            for p in db.rows("SELECT id FROM peers WHERE status='active' AND url IS NOT NULL AND "
                             "(direction='incoming' OR direction='both')"):
                try:
                    sync_peer(p["id"])
                except Exception:
                    log.exception("sync peer %s", p["id"])
        except Exception:
            log.exception("fed sync loop")
        # wake often so stop_flag is noticed; only sync when last_sync is stale
        for _ in range(60):
            if stop_flag():
                return
            time.sleep(30)


def list_remote_libraries(peer_id=None, user=None) -> list:
    q = "SELECT rl.*, p.name AS peer_name, p.url AS peer_url, p.status AS peer_status, p.last_seen, p.proxy, p.id AS peer_id_join " \
        "FROM remote_libraries rl JOIN peers p ON p.id=rl.peer_id WHERE rl.hidden_at IS NULL"
    args = []
    if peer_id:
        q += " AND rl.peer_id=?"
        args.append(peer_id)
    q += " ORDER BY p.name COLLATE NOCASE, rl.name COLLATE NOCASE"
    out = []
    for r in db.rows(q, args):
        if user and not can_see_remote(user, r):
            continue
        out.append(_remote_lib_out(r))
    return out


def can_see_remote(u, rl) -> bool:
    if not u:
        return False
    if u.get("is_admin"):
        return True
    vis = rl.get("visible_to")
    if not vis:
        return True
    try:
        ids = json.loads(vis)
    except Exception:
        return True
    return int(u["id"]) in [int(x) for x in ids]


def _remote_lib_out(r) -> dict:
    name = r.get("local_name") or r.get("name") or "Library"
    peer_name = r.get("peer_name") or "Shared"
    return {
        "id": -int(r["id"]),
        "name": name,
        "kind": r.get("kind") or "movies",
        "is_remote": True,
        "remote_library_id": r.get("remote_library_id"),
        "peer_id": r.get("peer_id") or r.get("peer_id_join"),
        "peer_name": peer_name,
        "source_name": peer_name,
        "item_count": r.get("item_count") or 0,
        "last_sync": r.get("last_sync"),
        "online": r.get("peer_status") == "active",
        "share": {"name": peer_name, "kind": "peer", "remote": r.get("peer_url")},
        "health": {"state": "ok" if r.get("peer_status") == "active" else "offline"},
        "path": None,
        "share_id": None,
    }


def get_remote_lib(lib_id_neg: int, user=None):
    """lib_id_neg is the negative API id, or pass positive local remote_libraries.id via abs."""
    rid = abs(int(lib_id_neg))
    r = db.row("SELECT rl.*, p.name AS peer_name, p.url AS peer_url, p.status AS peer_status, p.last_seen, p.proxy "
               "FROM remote_libraries rl JOIN peers p ON p.id=rl.peer_id WHERE rl.id=?", (rid,))
    if not r or r.get("hidden_at"):
        return None
    if user and not can_see_remote(user, r):
        raise HTTPException(403, "You do not have access to this shared library")
    return r


def library_items(lib_id_neg: int, q: str = "", offset: int = 0, limit: int = 200, user=None) -> dict:
    rl = get_remote_lib(lib_id_neg, user)
    if not rl:
        raise HTTPException(404, "No such library")
    limit = max(1, min(int(limit or 200), 10000))
    offset = max(0, int(offset or 0))
    like = "%" + (q or "").strip() + "%"
    rows = db.rows("SELECT * FROM remote_items WHERE remote_library_id=? AND title LIKE ? "
                   "ORDER BY sort_title COLLATE NOCASE LIMIT ? OFFSET ?",
                   (rl["id"], like, limit, offset))
    total = db.row("SELECT COUNT(*) n FROM remote_items WHERE remote_library_id=? AND title LIKE ?",
                   (rl["id"], like))["n"]
    items = [item_as_local(r, rl) for r in rows]
    return {"library": _remote_lib_out(rl), "view": "items", "items": items, "total": total}


def item_as_local(ri, rl=None) -> dict:
    if rl is None:
        rl = get_remote_lib(ri["remote_library_id"])
    genres = ri.get("genres")
    try:
        genres_l = json.loads(genres) if isinstance(genres, str) else (genres or [])
    except Exception:
        genres_l = []
    poster = ri.get("poster")
    backdrop = ri.get("backdrop")
    return {
        "id": -int(ri["id"]),
        "library_id": -int(ri["remote_library_id"]),
        "kind": ri.get("kind") or "movie",
        "media_type": "video",
        "title": ri.get("title"),
        "sort_title": ri.get("sort_title") or ri.get("title"),
        "year": ri.get("year"),
        "tmdb_id": ri.get("tmdb_id"),
        "duration": ri.get("duration"),
        "poster": poster,
        "backdrop": backdrop,
        "overview": ri.get("overview"),
        "runtime": ri.get("runtime"),
        "certification": ri.get("certification"),
        "rating": ri.get("rating"),
        "genres": genres_l,
        "added_at": ri.get("added_at"),
        "is_remote": True,
        "peer_name": (rl or {}).get("peer_name"),
        "source_name": (rl or {}).get("peer_name"),
        "remote_item_id": ri.get("remote_item_id"),
        "path": None,
        "has_art": bool(poster),
    }


def local_item(local_remote_item_id: int, user=None):
    ri = db.row("SELECT * FROM remote_items WHERE id=?", (int(local_remote_item_id),))
    if not ri:
        return None
    rl = get_remote_lib(ri["remote_library_id"], user)
    if not rl:
        return None
    return item_as_local(ri, rl)


def home_sections(user) -> list:
    out = []
    for rl in list_remote_libraries(user=user):
        if (rl.get("kind") or "movies") not in ("movies", "tv"):
            continue
        rows = db.rows("SELECT * FROM remote_items WHERE remote_library_id=? ORDER BY COALESCE(added_at,0) DESC, "
                       "sort_title COLLATE NOCASE LIMIT 20", (abs(rl["id"]),))
        items = [item_as_local(r, get_remote_lib(rl["id"])) for r in rows]
        lib = dict(rl)
        out.append({"library": lib, "items": items, "smart_rows": [
            {"key": "added", "title": "Recently added", "items": items, "note": ""}
        ], "genre_rows": []})
    return out


def search_items(q: str, user, limit=40) -> list:
    like = "%" + q + "%"
    rows = db.rows("SELECT ri.* FROM remote_items ri JOIN remote_libraries rl ON rl.id=ri.remote_library_id "
                   "JOIN peers p ON p.id=rl.peer_id WHERE rl.hidden_at IS NULL AND p.status='active' "
                   "AND ri.title LIKE ? ORDER BY ri.sort_title COLLATE NOCASE LIMIT ?", (like, limit))
    out = []
    for r in rows:
        rl = get_remote_lib(r["remote_library_id"], user=None)
        if not rl or (user and not can_see_remote(user, rl)):
            continue
        out.append(item_as_local(r, rl))
    return out


# ---- tickets + play ---------------------------------------------------------
QUALITY_RANK = {"original": 4, "4k": 4, "2160p": 4, "1080p": 3, "720p": 2, "480p": 1, "audio": 0}


def _cap_profile(grant, profile: str) -> str:
    want = (profile or "1080p").lower()
    cap = (grant.get("max_quality") or "1080p").lower()
    if QUALITY_RANK.get(want, 3) <= QUALITY_RANK.get(cap, 3):
        return want if want != "4k" else "original"
    return cap


def _active_peer_streams(peer_id: int) -> int:
    now = time.time()
    with _ticket_lock:
        return sum(1 for t in _tickets.values() if t.get("peer_id") == peer_id and t.get("exp", 0) > now)


def issue_ticket(peer, body: dict) -> dict:
    item_id = int(body.get("item") or body.get("item_id") or 0)
    it = db.row("SELECT * FROM items WHERE id=?", (item_id,))
    if not it:
        raise HTTPException(404, "No such item")
    grant = _grant(peer["id"], it["library_id"])
    if not grant or not grant["can_stream"]:
        raise HTTPException(403, "This title is not shared for streaming")
    max_streams = int(grant["max_streams"] or 2)
    if _active_peer_streams(peer["id"]) >= max_streams:
        raise HTTPException(429, "%s's server is busy" % server_name())
    # local users win: if we're at MAX transcodes, refuse peer streams
    try:
        from . import transcode as tc
        if hasattr(tc, "too_busy") and tc.too_busy():
            raise HTTPException(429, "%s's server is busy" % server_name())
    except HTTPException:
        raise
    except Exception:
        pass
    profile = _cap_profile(grant, body.get("profile") or "1080p")
    if profile not in ("original",) and not grant["allow_transcode"] and profile != "original":
        # remux / original only
        profile = "original"
    now = int(time.time())
    tok = secrets.token_urlsafe(24)
    ticket = {
        "tok": tok, "peer_id": peer["id"], "item_id": item_id, "profile": profile,
        "remote_user": str(body.get("remote_user") or "")[:40],
        "display": str(body.get("display") or "")[:80],
        "exp": now + TICKET_TTL, "grant_id": "%s:%s" % (peer["id"], it["library_id"]),
    }
    with _ticket_lock:
        _tickets[tok] = ticket
    useractivity.record("share_play", detail="peer stream of %s" % (it.get("title") or item_id),
                        item=it, user=None)
    return {"ticket": tok, "profile": profile, "expires_at": ticket["exp"],
            "path": "/api/fed/play/%s/index.m3u8" % tok}


def get_ticket(tok: str):
    with _ticket_lock:
        t = _tickets.get(tok)
    if not t or t["exp"] < time.time():
        raise HTTPException(403, "This playback ticket has expired")
    peer = db.row("SELECT * FROM peers WHERE id=?", (t["peer_id"],))
    if not peer or peer["status"] != "active":
        raise HTTPException(403, "Sharing has been stopped")
    grant = _grant(peer["id"], db.row("SELECT library_id FROM items WHERE id=?", (t["item_id"],))["library_id"])
    if not grant:
        raise HTTPException(403, "This library is no longer shared")
    return t


def _peer_session(t):
    from . import transcode
    it = db.row("SELECT * FROM items WHERE id=?", (t["item_id"],))
    if not it:
        raise HTTPException(404, "No such item")
    player = "peer-%d" % t["peer_id"]
    try:
        sess = transcode.get_session(it, t["profile"], 0, 0, player)
        transcode.kickoff(sess, 0)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return it, sess, transcode


def play_index(tok: str, request: Request):
    t = get_ticket(tok)
    it, sess, transcode = _peer_session(t)
    need_init = transcode.split_profile(t["profile"])[1] == "hevc" or (
        t["profile"] == "remux" and transcode.remux_codec(it) == "hevc")
    init = ("init.mp4?audio=0") if need_init else None
    text = transcode.playlist(it, "?audio=0", None, init)
    text = _rewrite_playlist(text, "/api/fed/play/%s/" % tok)
    return PlainTextResponse(text, media_type="application/vnd.apple.mpegurl",
                             headers=_play_cors(request, no_store=True))


def _rewrite_playlist(text: str, prefix: str) -> str:
    out = []
    for line in text.splitlines():
        if line and not line.startswith("#") and "://" not in line:
            # relative segment or init
            name = line.split("?")[0].lstrip("./")
            qs = ""
            if "?" in line:
                qs = "?" + line.split("?", 1)[1]
            out.append(prefix + name + qs)
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def play_part(tok: str, name: str, request: Request):
    t = get_ticket(tok)
    it, sess, transcode = _peer_session(t)
    headers = _play_cors(request, no_store=True)
    name = (name or "").split("?")[0]
    if name.startswith("init"):
        pth = sess.get_init(0)
        if not pth:
            raise HTTPException(500, "Transcode failed")
        return Response(pth.read_bytes(), media_type="video/mp4", headers=headers)
    if name.startswith("seg"):
        num = int("".join(ch for ch in name if ch.isdigit()) or 0)
        if num < 0 or num >= getattr(sess, "nseg", 10**9):
            raise HTTPException(404, "No such segment")
        pth = sess.get_segment(num)
        if not pth:
            raise HTTPException(500, "Transcode failed")
        try:
            data = pth.read_bytes()
        except FileNotFoundError:
            raise HTTPException(503, "Segment expired, retry")
        ctype = "video/iso.segment" if name.endswith(".m4s") else "video/mp2t"
        return Response(data, media_type=ctype, headers=headers)
    raise HTTPException(404, "No such segment")


def _play_cors(request: Request, no_store=False) -> dict:
    origin = request.headers.get("origin") or ""
    allowed = _allowed_origins()
    h = {"Cache-Control": "private, no-store"} if no_store else {}
    if origin and (origin in allowed or _origin_ok(origin)):
        h["Access-Control-Allow-Origin"] = origin
        h["Access-Control-Allow-Credentials"] = "true"
        h["Vary"] = "Origin"
    elif not origin:
        pass
    return h


def _allowed_origins() -> set:
    out = set()
    for p in db.rows("SELECT url FROM peers WHERE status='active' AND url IS NOT NULL"):
        try:
            u = urlparse(p["url"])
            if u.scheme and u.netloc:
                out.add("%s://%s" % (u.scheme, u.netloc))
        except Exception:
            pass
    return out


def _origin_ok(origin: str) -> bool:
    try:
        u = urlparse(origin)
        return is_lan_host(u.hostname or "")
    except Exception:
        return False


def cors_preflight(request: Request):
    origin = request.headers.get("origin") or ""
    h = {"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
         "Access-Control-Allow-Headers": "Content-Type, X-Movinite-Server, X-Movinite-Key, X-Movinite-Date, "
                                          "X-Movinite-Nonce, X-Movinite-Signature"}
    if origin and (origin in _allowed_origins() or _origin_ok(origin)):
        h["Access-Control-Allow-Origin"] = origin
        h["Access-Control-Allow-Credentials"] = "true"
        h["Access-Control-Max-Age"] = "600"
    return Response(status_code=204, headers=h)


# ---- B: start play for a local user -----------------------------------------
def start_remote_play(user, local_item_id: int, profile: str, request: Request, my_base: str = "") -> dict:
    it = local_item(-int(local_item_id) if local_item_id < 0 else local_item_id, user)
    # local_item expects the positive remote_items.id
    if local_item_id < 0:
        it = local_item(-local_item_id, user)
    if not it:
        raise HTTPException(404, "No such item")
    rl = get_remote_lib(it["library_id"], user)
    peer = db.row("SELECT * FROM peers WHERE id=?", (rl["peer_id"],))
    if not peer or not peer.get("url") or peer["status"] != "active":
        raise HTTPException(503, "That server is not reachable right now")
    payload = {"item": it["remote_item_id"], "profile": profile or "1080p",
               "remote_user": str(user["id"]), "display": user.get("username") or "user"}
    _st, data, _h = call(peer["url"], "POST", "/api/fed/tickets", obj=payload, timeout=20)
    ticket = data.get("ticket")
    if not ticket:
        raise HTTPException(502, "The other server did not start playback")
    use_proxy = bool(peer.get("proxy"))
    if (peer.get("proxy") in (None, 0)) and urlparse(peer["url"]).scheme == "https":
        use_proxy = False
    if urlparse(peer["url"]).scheme == "http" and not is_lan_host(urlparse(peer["url"]).hostname or ""):
        use_proxy = True
    a_path = data.get("path") or ("/api/fed/play/%s/index.m3u8" % ticket)
    if use_proxy:
        src = "/api/sharing/proxy/%s/index.m3u8" % ticket
        # remember how to reach A
        with _ticket_lock:
            _tickets["proxy:" + ticket] = {"url": peer["url"].rstrip("/") + a_path.rsplit("/", 1)[0],
                                           "peer_id": peer["id"], "exp": int(time.time()) + TICKET_TTL}
    else:
        src = peer["url"].rstrip("/") + a_path
    return {"src": src, "ticket": ticket, "proxy": use_proxy, "profile": data.get("profile") or profile,
            "peer_name": peer.get("name")}


def proxy_part(ticket: str, name: str, request: Request):
    with _ticket_lock:
        meta = _tickets.get("proxy:" + ticket)
    if not meta or meta["exp"] < time.time():
        raise HTTPException(403, "This playback ticket has expired")
    url = meta["url"].rstrip("/") + "/" + name
    req = urllib.request.Request(url, headers={"User-Agent": "Movinite/%s" % __version__})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = resp.read()
        ctype = resp.headers.get("Content-Type") or "application/octet-stream"
        if name.endswith("m3u8") or "mpegurl" in ctype:
            text = data.decode()
            prefix = "/api/sharing/proxy/%s/" % ticket
            # rewrite A-absolute and relative URIs onto our proxy
            lines = []
            base = meta["url"].rstrip("/") + "/"
            for line in text.splitlines():
                if line and not line.startswith("#"):
                    if line.startswith(base):
                        line = prefix + line[len(base):]
                    elif "://" not in line:
                        line = prefix + line.lstrip("./")
                    elif "/api/fed/play/" in line:
                        line = prefix + line.rsplit("/", 1)[-1]
                lines.append(line)
            return PlainTextResponse("\n".join(lines) + "\n", media_type="application/vnd.apple.mpegurl",
                                     headers={"Cache-Control": "private, no-store"})
        return Response(data, media_type=ctype, headers={"Cache-Control": "private, no-store"})
    except urllib.error.HTTPError as e:
        raise HTTPException(e.code, "The other server closed this stream")
    except Exception:
        raise HTTPException(502, "Could not reach the other server")


# ---- revoke / admin lists ---------------------------------------------------
def list_peers():
    out = []
    for p in db.rows("SELECT * FROM peers ORDER BY name COLLATE NOCASE"):
        grants, live = [], _active_peer_streams(p["id"])
        for g in db.rows("SELECT g.*, l.name, l.kind FROM peer_grants g JOIN libraries l ON l.id=g.library_id WHERE g.peer_id=?",
                         (p["id"],)):
            grants.append({"library_id": g["library_id"], "name": g["name"], "kind": g["kind"],
                           "can_stream": bool(g["can_stream"]), "can_download": bool(g["can_download"]),
                           "max_quality": g["max_quality"], "max_streams": g["max_streams"],
                           "max_mbps": g["max_mbps"], "allow_transcode": bool(g["allow_transcode"])})
        remotes = list_remote_libraries(p["id"])
        out.append({
            "id": p["id"], "server_id": p["server_id"], "name": p["name"], "url": p["url"],
            "fingerprint": _fp(p["server_id"]), "direction": p["direction"], "status": p["status"],
            "created_at": p["created_at"], "last_seen": p["last_seen"], "last_error": p["last_error"],
            "proxy": bool(p.get("proxy")), "grants": grants, "live_streams": live, "remote": remotes,
        })
    return out


def _fp(server_id: str) -> str:
    s = server_id or ""
    return "MOVI-%s-%s-%s" % (s[0:4], s[4:8], s[8:12]) if len(s) >= 12 else s


def stop_sharing(admin, peer_id: int, library_id: int = None):
    peer = db.row("SELECT * FROM peers WHERE id=?", (peer_id,))
    if not peer:
        raise HTTPException(404, "No such peer")
    now = int(time.time())
    with db.tx() as c:
        if library_id:
            c.execute("DELETE FROM peer_grants WHERE peer_id=? AND library_id=?", (peer_id, library_id))
            left = c.execute("SELECT COUNT(*) n FROM peer_grants WHERE peer_id=?", (peer_id,)).fetchone()[0]
            if not left and peer["direction"] == "outgoing":
                c.execute("UPDATE peers SET status='revoked' WHERE id=?", (peer_id,))
        else:
            c.execute("DELETE FROM peer_grants WHERE peer_id=?", (peer_id,))
            if peer["direction"] == "both":
                c.execute("UPDATE peers SET direction='incoming' WHERE id=?", (peer_id,))
            else:
                c.execute("UPDATE peers SET status='revoked' WHERE id=?", (peer_id,))
        # drop live tickets for this peer
    with _ticket_lock:
        for k, t in list(_tickets.items()):
            if t.get("peer_id") == peer_id and (not library_id or True):
                t["exp"] = 0
    useractivity.record("share_stop", user=admin, actor=admin, detail="stopped sharing with %s" % peer.get("name"))
    return {"ok": True}


def remove_remote(admin, remote_lib_id: int, tell=True):
    rl = db.row("SELECT rl.*, p.url, p.name AS peer_name, p.server_id FROM remote_libraries rl "
                "JOIN peers p ON p.id=rl.peer_id WHERE rl.id=?", (abs(int(remote_lib_id)),))
    if not rl:
        raise HTTPException(404, "No such shared library")
    with db.tx() as c:
        c.execute("DELETE FROM remote_items WHERE remote_library_id=?", (rl["id"],))
        c.execute("DELETE FROM remote_libraries WHERE id=?", (rl["id"],))
        left = c.execute("SELECT COUNT(*) n FROM remote_libraries WHERE peer_id=?", (rl["peer_id"],)).fetchone()[0]
        if not left:
            # keep the peer row if we still share to them
            grants = c.execute("SELECT COUNT(*) n FROM peer_grants WHERE peer_id=?", (rl["peer_id"],)).fetchone()[0]
            if grants:
                c.execute("UPDATE peers SET direction='outgoing' WHERE id=? AND direction='both'", (rl["peer_id"],))
            else:
                c.execute("UPDATE peers SET status='revoked' WHERE id=?", (rl["peer_id"],))
    if tell and rl.get("url"):
        try:
            call(rl["url"], "POST", "/api/fed/leave", obj={"reason": "removed"}, timeout=10)
        except Exception:
            log.exception("leave notice")
    useractivity.record("share_remove", user=admin, actor=admin, detail="removed libraries from %s" % rl.get("peer_name"))
    return {"ok": True}


def set_visible(admin, remote_lib_id: int, user_ids):
    rl = db.row("SELECT * FROM remote_libraries WHERE id=?", (abs(int(remote_lib_id)),))
    if not rl:
        raise HTTPException(404, "No such shared library")
    vis = None if not user_ids else json.dumps([int(x) for x in user_ids])
    with db.tx() as c:
        c.execute("UPDATE remote_libraries SET visible_to=? WHERE id=?", (vis, rl["id"]))
    return {"ok": True}


def set_proxy(admin, peer_id: int, proxy: bool):
    with db.tx() as c:
        if not c.execute("SELECT id FROM peers WHERE id=?", (peer_id,)).fetchone():
            raise HTTPException(404, "No such peer")
        c.execute("UPDATE peers SET proxy=? WHERE id=?", (1 if proxy else 0, peer_id))
    return {"ok": True}


def set_grants(admin, peer_id: int, grants: list):
    peer = db.row("SELECT * FROM peers WHERE id=?", (peer_id,))
    if not peer:
        raise HTTPException(404, "No such peer")
    with db.tx() as c:
        c.execute("DELETE FROM peer_grants WHERE peer_id=?", (peer_id,))
        for g in grants or []:
            c.execute("INSERT INTO peer_grants(peer_id, library_id, can_stream, can_download, max_quality, max_streams, "
                      "max_mbps, allow_transcode) VALUES(?,?,?,?,?,?,?,?)",
                      (peer_id, int(g["library_id"]), 0 if g.get("can_stream") in (0, False, "0") else 1,
                       1 if g.get("can_download") else 0, g.get("max_quality") or "1080p",
                       int(g.get("max_streams") or 2), int(g.get("max_mbps") or 20),
                       0 if g.get("allow_transcode") in (0, False, "0") else 1))
    return {"ok": True, "peers": list_peers()}


def leave_incoming(peer):
    """A is told B is leaving (or vice versa). Drop grants for that peer."""
    now = int(time.time())
    with db.tx() as c:
        c.execute("DELETE FROM peer_grants WHERE peer_id=?", (peer["id"],))
        c.execute("UPDATE peers SET status='revoked', last_seen=? WHERE id=?", (now, peer["id"]))
    with _ticket_lock:
        for t in _tickets.values():
            if t.get("peer_id") == peer["id"]:
                t["exp"] = 0
    return {"ok": True}


def identity_payload() -> dict:
    return {
        "name": server_name(),
        "server_id": keys.server_id() if keys.ensure() else None,
        "fingerprint": keys.fingerprint() if keys.ensure() else None,
        "version": __version__,
    }


def set_server_name(admin, name: str):
    name = (name or "").strip()[:80]
    settings.put("server_name", name)
    return {"ok": True, "name": server_name(), "fingerprint": keys.fingerprint() if keys.ensure() else None}
