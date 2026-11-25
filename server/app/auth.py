"""Password hashing (stdlib scrypt) and cookie sessions."""
import base64
import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request

from . import config, db

COOKIE = "ms_session"


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


def create_user(username, password, is_admin=False, must_change=False):
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO users(username,pw_hash,is_admin,must_change_pw,created_at) VALUES(?,?,?,?,?)",
            (username, hash_pw(password), 1 if is_admin else 0, 1 if must_change else 0, int(time.time())),
        )
        return cur.lastrowid


def set_password(user_id, password, must_change=False):
    with db.tx() as c:
        c.execute("UPDATE users SET pw_hash=?, must_change_pw=? WHERE id=?",
                  (hash_pw(password), 1 if must_change else 0, user_id))
        c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


def new_session(user_id) -> str:
    tok = secrets.token_urlsafe(32)
    now = int(time.time())
    with db.tx() as c:
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        c.execute("INSERT INTO sessions(token,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                  (tok, user_id, now, now + config.SESSION_DAYS * 86400))
    return tok


def end_session(tok):
    with db.tx() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (tok,))


def user_from_request(request: Request):
    tok = request.cookies.get(COOKIE)
    if not tok:
        return None
    return db.row(
        "SELECT u.id, u.username, u.is_admin, u.must_change_pw FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token=? AND s.expires_at>?", (tok, int(time.time())))


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


# simple login rate limit: max 10 failures per IP per 5 minutes
_fails = {}


def login_allowed(ip) -> bool:
    now = time.time()
    lst = [t for t in _fails.get(ip, []) if now - t < 300]
    _fails[ip] = lst
    return len(lst) < 10


def login_failed(ip):
    _fails.setdefault(ip, []).append(time.time())
