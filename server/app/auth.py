"""Password hashing (stdlib scrypt), cookie sessions, roles and per-library access.

1.9:
- roles: admin | download | view (users.role; users.is_admin is kept in step for older code paths)
- per-library access: users.all_libraries=1 (default) or the rows in user_libraries
- session tokens are stored as sha256 hashes; the cookie holds the raw token
- sessions remember ip / user agent / last seen, so a user can see and sign out devices
"""
import base64
import hashlib
import hmac
import secrets
import threading
import time

from fastapi import HTTPException, Request

from . import config, db

COOKIE = "ms_session"
ROLES = ("admin", "download", "view")
ROLE_LABEL = {"admin": "Admin", "download": "Viewer + Downloads", "view": "Viewer"}


def hash_pw(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$%s$%s" % (base64.b64encode(salt).decode(), base64.b64encode(h).decode())


def check_pw(pw: str, stored: str) -> bool:
    try:
        algo, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


def token_hash(tok: str) -> str:
    return hashlib.sha256(("ms1:" + (tok or "")).encode()).hexdigest()


def norm_role(role, is_admin=False):
    role = (role or "").strip().lower()
    if role not in ROLES:
        role = "admin" if is_admin else "view"
    return role


def create_user(username, password, is_admin=False, must_change=False, role=None, email=None,
                all_libraries=True, libraries=None, invited_by=None):
    role = norm_role(role, is_admin)
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO users(username,pw_hash,is_admin,must_change_pw,created_at,role,email,all_libraries,invited_by) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (username, hash_pw(password), 1 if role == "admin" else 0, 1 if must_change else 0, int(time.time()),
             role, (email or None), 1 if (all_libraries or role == "admin") else 0, invited_by),
        )
        uid = cur.lastrowid
        if libraries and not all_libraries and role != "admin":
            c.executemany("INSERT OR IGNORE INTO user_libraries(user_id, library_id) VALUES(?,?)",
                          [(uid, int(l)) for l in libraries])
    invalidate_cache()
    return uid


def set_password(user_id, password, must_change=False):
    with db.tx() as c:
        c.execute("UPDATE users SET pw_hash=?, must_change_pw=? WHERE id=?",
                  (hash_pw(password), 1 if must_change else 0, user_id))
        c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    invalidate_cache()


def _device_name(ua):
    ua = ua or ""
    if "MoviniteAndroid" in ua or ("; wv)" in ua and "Android" in ua):
        os_ = "Movinite app (Android)"
    elif "Android" in ua:
        os_ = "Android"
    elif "iPhone" in ua or "iPad" in ua:
        os_ = "iPhone / iPad"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        os_ = "Mac"
    elif "Windows" in ua:
        os_ = "Windows"
    elif "CrOS" in ua:
        os_ = "ChromeOS"
    elif "Linux" in ua:
        os_ = "Linux"
    else:
        os_ = "Unknown device"
    br = ""
    if "MoviniteAndroid" in ua or "; wv)" in ua:
        br = ""
    elif "Edg/" in ua:
        br = "Edge"
    elif "Firefox/" in ua:
        br = "Firefox"
    elif "Chrome/" in ua:
        br = "Chrome"
    elif "Safari/" in ua:
        br = "Safari"
    return os_ + (" · " + br if br else "")


def new_session(user_id, ip=None, ua=None) -> str:
    tok = secrets.token_urlsafe(32)
    now = int(time.time())
    with db.tx() as c:
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        c.execute("INSERT INTO sessions(token,user_id,created_at,expires_at,ip,ua,last_seen,device) VALUES(?,?,?,?,?,?,?,?)",
                  (token_hash(tok), user_id, now, now + config.SESSION_DAYS * 86400, ip, (ua or "")[:400], now,
                   _device_name(ua)))
    return tok


def end_session(tok):
    with db.tx() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (token_hash(tok),))
    invalidate_cache()


# ---- user lookup (cached briefly: the library guard runs on every API request) ----
_cache = {}
_clock = threading.Lock()
_CACHE_S = 5.0
_SEEN_EVERY = 300


def invalidate_cache():
    with _clock:
        _cache.clear()


def _load(th):
    u = db.row(
        "SELECT u.id, u.username, u.is_admin, u.must_change_pw, u.role, u.all_libraries, u.email, u.disabled_at, "
        "s.last_seen, s.ip s_ip FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires_at>?",
        (th, int(time.time())))
    if not u or u.get("disabled_at"):
        return None
    u["role"] = norm_role(u.get("role"), u.get("is_admin"))
    u["is_admin"] = 1 if u["role"] == "admin" else 0
    if u["role"] == "admin" or u.get("all_libraries"):
        u["libs"] = None
    else:
        u["libs"] = frozenset(r["library_id"] for r in db.rows("SELECT library_id FROM user_libraries WHERE user_id=?", (u["id"],)))
    u["sid"] = th[:16]
    return u


def user_from_token(tok, ip=None, ua=None):
    if not tok:
        return None
    th = token_hash(tok)
    now = time.time()
    with _clock:
        hit = _cache.get(th)
    if hit and now - hit[0] < _CACHE_S:
        u = hit[1]
    else:
        u = _load(th)
        with _clock:
            if len(_cache) > 2000:
                _cache.clear()
            _cache[th] = (now, u)
    if u and (now - (u.get("last_seen") or 0) > _SEEN_EVERY or (ip and u.get("s_ip") != ip)):
        try:
            with db.tx() as c:
                c.execute("UPDATE sessions SET last_seen=?, ip=COALESCE(?, ip) WHERE token=?", (int(now), ip, th))
            u["last_seen"] = int(now)
            if ip:
                u["s_ip"] = ip
        except Exception:
            pass
    return u


def user_from_request(request: Request):
    from . import netutil
    return user_from_token(request.cookies.get(COOKIE), netutil.client_ip(request), request.headers.get("user-agent"))


def require_user(request: Request):
    u = user_from_request(request)
    if not u:
        raise HTTPException(401, "Not signed in")
    return u


def require_admin(request: Request):
    u = require_user(request)
    if not u["is_admin"]:
        raise HTTPException(403, "Admin only")
    return u


def can_see_library(u, lib_id):
    if not u:
        return False
    libs = u.get("libs")
    return libs is None or (lib_id is not None and int(lib_id) in libs)


def visible_library_ids(u):
    """None = every library."""
    return None if not u else u.get("libs")


def lib_sql(u, col="library_id"):
    """SQL fragment ' AND col IN (..)' (ints only, safe to inline) or '' for full access."""
    libs = visible_library_ids(u)
    if libs is None:
        return ""
    if not libs:
        return " AND 0"
    return " AND %s IN (%s)" % (col, ",".join(str(int(x)) for x in sorted(libs)))


# ---- devices (sessions) ----
def list_sessions(user_id, current_sid=None):
    out = []
    for r in db.rows("SELECT token, created_at, expires_at, ip, ua, last_seen, device FROM sessions WHERE user_id=? AND "
                     "expires_at>? ORDER BY COALESCE(last_seen, created_at) DESC", (user_id, int(time.time()))):
        sid = r["token"][:16]
        out.append({"id": sid, "device": r.get("device") or _device_name(r.get("ua")), "ip": r.get("ip"),
                    "created_at": r["created_at"], "last_seen": r.get("last_seen") or r["created_at"],
                    "expires_at": r["expires_at"], "current": sid == current_sid})
    return out


def end_session_by_id(user_id, sid):
    if not sid or len(sid) != 16 or not all(ch in "0123456789abcdef" for ch in sid):
        return 0
    with db.tx() as c:
        n = c.execute("DELETE FROM sessions WHERE user_id=? AND substr(token,1,16)=?", (user_id, sid)).rowcount
    invalidate_cache()
    return n


def end_all_sessions(user_id, except_sid=None):
    with db.tx() as c:
        if except_sid:
            n = c.execute("DELETE FROM sessions WHERE user_id=? AND substr(token,1,16)<>?", (user_id, except_sid)).rowcount
        else:
            n = c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,)).rowcount
    invalidate_cache()
    return n


# simple login rate limit: max 10 failures per client IP per 5 minutes (1.9: the real client IP behind the proxy)
_fails = {}


def login_allowed(ip) -> bool:
    now = time.time()
    lst = [t for t in _fails.get(ip, []) if now - t < 300]
    _fails[ip] = lst
    return len(lst) < 10


def login_failed(ip):
    _fails.setdefault(ip, []).append(time.time())
    if len(_fails) > 5000:
        now = time.time()
        for k in [k for k, v in _fails.items() if not v or now - v[-1] > 300]:
            _fails.pop(k, None)
