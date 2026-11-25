"""1.9: "Connect Gmail" -- invites are sent from the inviting admin's own Gmail through the Gmail API.

OAuth 2.0 authorization code flow with PKCE (S256), access_type=offline + prompt=consent so Google returns a
refresh token.  Scopes: gmail.send (send only; Movinite cannot read, list or delete mail) plus openid / email /
profile so we learn the connected address and the account's own name, which becomes the From display name.

Secrets: the OAuth client secret and every refresh token live in data/secrets/gmail.sealed (0600, AES-256-GCM
with a key derived from the server key, see keys.py).  Access tokens are kept in memory only.  Nothing here is
ever written to the database, the logs or an API response.

Each hoster uses their own Google Cloud project for now (docs/gmail-setup.md).
"""
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from . import db, keys, settings

log = logging.getLogger("media-server")

AUTH_URL = os.environ.get("MS_GOOGLE_AUTH_URL") or "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = os.environ.get("MS_GOOGLE_TOKEN_URL") or "https://oauth2.googleapis.com/token"
REVOKE_URL = os.environ.get("MS_GOOGLE_REVOKE_URL") or "https://oauth2.googleapis.com/revoke"
GMAIL_BASE = (os.environ.get("MS_GMAIL_API_BASE") or "https://gmail.googleapis.com").rstrip("/")
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
SCOPES = ["openid", "email", "profile", SEND_SCOPE]
PURPOSE = "gmail-tokens/v1"
SEALED = keys.SECRETS_DIR / "gmail.sealed"
PASTE_REDIRECT = "http://localhost/movinite-gmail-callback"
CALLBACK_PATH = "/api/gmail/callback"
HOURLY_CAP_DEFAULT = 20
DAILY_CAP_DEFAULT = 100
STATE_TTL = 600
TIMEOUT = 20

_lock = threading.RLock()
_states = {}          # sha256(state) -> {uid, sid, verifier, redirect, exp}
_access = {}          # uid -> (access_token, expires_at)


class GmailError(Exception):
    def __init__(self, code, message, reconnect=False, retry=False, status=None):
        super().__init__(message)
        self.code, self.message, self.reconnect, self.retry, self.status = code, message, reconnect, retry, status


# ---------------------------------------------------------------- secret store
def _load():
    with _lock:
        try:
            return keys.read_sealed(SEALED, PURPOSE, default={}) or {}
        except Exception as e:
            log.error("gmail: cannot read the sealed token file (%s)", type(e).__name__)
            return {}


def _save(d):
    with _lock:
        keys.write_sealed(SEALED, PURPOSE, d)


def client_id():
    return (settings.get("gmail_client_id", "") or "").strip()


def has_secret():
    return bool(_load().get("client_secret"))


def configured():
    return keys.available() and bool(client_id()) and has_secret()


def set_client(cid=None, secret=None):
    """Save the OAuth client. Changing the client disconnects every account (their tokens belong to the old one)."""
    if cid is not None:
        cid = cid.strip()
        if cid and not re.match(r"^[0-9A-Za-z._-]+\.apps\.googleusercontent\.com$", cid):
            raise GmailError("bad_client_id", "That doesn't look like a Google OAuth client ID (it ends in .apps.googleusercontent.com)")
    changed = False
    with _lock:
        d = _load()
        if cid is not None and cid != client_id():
            changed = True
            settings.put("gmail_client_id", cid)
        if secret is not None and secret.strip():
            if secret.strip() != d.get("client_secret"):
                changed = True
            d["client_secret"] = secret.strip()
        if changed:
            d["tokens"] = {}
            _access.clear()
            with db.tx() as c:
                c.execute("UPDATE gmail_accounts SET status='disconnected', last_error='OAuth client changed'")
        _save(d)
    return changed


def _refresh_token(uid):
    return (_load().get("tokens") or {}).get(str(uid))


def _store_refresh(uid, rt):
    with _lock:
        d = _load()
        d.setdefault("tokens", {})[str(uid)] = rt
        _save(d)


def _drop_refresh(uid):
    with _lock:
        d = _load()
        rt = (d.get("tokens") or {}).pop(str(uid), None)
        _save(d)
        _access.pop(uid, None)
        return rt


# ---------------------------------------------------------------- http
def _post_form(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    return _do(req)


def _do(req):
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {}
        return e.code, payload
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GmailError("network", "Can't reach Google right now (%s)" % type(e).__name__, retry=True)


def _err_reason(payload):
    """Google error payloads: {"error": "invalid_grant"} or {"error": {"errors": [{"reason": ...}], "message": ...}}"""
    e = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(e, str):
        return e, payload.get("error_description") or e
    if isinstance(e, dict):
        reasons = [x.get("reason") for x in (e.get("errors") or []) if isinstance(x, dict)]
        st = e.get("status") or ""
        return (reasons[0] if reasons and reasons[0] else st or "error"), (e.get("message") or st or "error")
    return "error", "error"


# ---------------------------------------------------------------- OAuth
def redirect_uri(base_url, paste=False):
    if paste:
        return PASTE_REDIRECT
    return base_url.rstrip("/") + CALLBACK_PATH


def start(user, base_url, paste=False):
    if not keys.available():
        raise GmailError("no_crypto", "This server is missing the Python 'cryptography' package; re-run update.sh")
    if not configured():
        raise GmailError("not_configured", "Add the Gmail app credentials (client ID and secret) first")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    redir = redirect_uri(base_url, paste)
    now = time.time()
    with _lock:
        for k in [k for k, v in _states.items() if v["exp"] < now]:
            _states.pop(k, None)
        _states[hashlib.sha256(state.encode()).hexdigest()] = {
            "uid": user["id"], "sid": user.get("sid"), "verifier": verifier, "redirect": redir, "exp": now + STATE_TTL}
    q = {"response_type": "code", "client_id": client_id(), "redirect_uri": redir, "scope": " ".join(SCOPES),
         "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
         "access_type": "offline", "prompt": "consent", "include_granted_scopes": "false"}
    if user.get("email"):
        q["login_hint"] = user["email"]
    return {"url": AUTH_URL + "?" + urllib.parse.urlencode(q), "redirect_uri": redir, "paste": paste}


def _jwt_claims(tok):
    try:
        part = tok.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def finish(user, code, state):
    """Called by the redirect (or the pasted address). Returns the gmail_accounts row (no secrets)."""
    if not code or not state:
        raise GmailError("bad_request", "The Google sign-in didn't come back with a code; try Connect Gmail again")
    with _lock:
        st = _states.pop(hashlib.sha256(state.encode()).hexdigest(), None)
    if not st or st["exp"] < time.time():
        raise GmailError("bad_state", "That Google sign-in link expired or was already used; try Connect Gmail again")
    if st["uid"] != user["id"] or (st.get("sid") and user.get("sid") and st["sid"] != user["sid"]):
        raise GmailError("bad_state", "That Google sign-in was started by a different session; try Connect Gmail again")
    secret = _load().get("client_secret")
    status, tok = _post_form(TOKEN_URL, {"grant_type": "authorization_code", "code": code, "client_id": client_id(),
                                         "client_secret": secret, "redirect_uri": st["redirect"],
                                         "code_verifier": st["verifier"]})
    if status != 200 or not tok.get("access_token"):
        reason, _msg = _err_reason(tok)
        log.warning("gmail: token exchange failed (%s %s)", status, reason)
        hint = {"redirect_uri_mismatch": "The redirect URI in Google Cloud doesn't exactly match the one shown in Settings > Email",
                "invalid_client": "Google didn't accept the client ID / secret; check them in Settings > Email",
                "invalid_grant": "The Google sign-in code expired or was already used; try Connect Gmail again"}.get(reason)
        raise GmailError(reason, hint or "Google refused the sign-in (%s)" % reason)
    granted = set((tok.get("scope") or "").split())
    if SEND_SCOPE not in granted:
        _revoke(tok.get("refresh_token") or tok.get("access_token"))
        raise GmailError("scope", "Movinite needs permission to send email. Try again and leave \"Send email on your behalf\" ticked.")
    rt = tok.get("refresh_token")
    if not rt:
        raise GmailError("no_refresh", "Google didn't return a long-lived sign-in. Remove Movinite at myaccount.google.com > Security > Third-party connections, then connect again.")
    claims = _jwt_claims(tok.get("id_token") or "")
    email = (claims.get("email") or "").strip()
    if not email or claims.get("email_verified") is False:
        _revoke(rt)
        raise GmailError("no_email", "Google didn't share a verified email address for this account")
    name = (claims.get("name") or "").strip() or None
    _store_refresh(user["id"], rt)
    with _lock:
        _access[user["id"]] = (tok["access_token"], time.time() + int(tok.get("expires_in") or 3600) - 60)
    now = int(time.time())
    with db.tx() as c:
        c.execute("INSERT INTO gmail_accounts(user_id,email,display_name,scopes,connected_at,status,last_error) "
                  "VALUES(?,?,?,?,?,'connected',NULL) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email, "
                  "display_name=excluded.display_name, scopes=excluded.scopes, connected_at=excluded.connected_at, "
                  "status='connected', last_error=NULL", (user["id"], email, name, " ".join(sorted(granted)), now))
    return status_for(user["id"])


def parse_pasted(text):
    """The user pasted the address the browser ended up on (paste mode). Returns (code, state)."""
    text = (text or "").strip()
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(text).query)
    except ValueError:
        q = {}
    if q.get("error"):
        raise GmailError(q["error"][0], "Google sign-in was cancelled" if q["error"][0] == "access_denied" else "Google returned an error: %s" % q["error"][0])
    return (q.get("code") or [None])[0], (q.get("state") or [None])[0]


def _mark(uid, status, err=None):
    with db.tx() as c:
        c.execute("UPDATE gmail_accounts SET status=?, last_error=? WHERE user_id=?", (status, err, uid))


def _access_token(uid):
    with _lock:
        hit = _access.get(uid)
    if hit and hit[1] > time.time():
        return hit[0]
    rt = _refresh_token(uid)
    if not rt:
        raise GmailError("not_connected", "Gmail isn't connected", reconnect=True)
    status, tok = _post_form(TOKEN_URL, {"grant_type": "refresh_token", "refresh_token": rt, "client_id": client_id(),
                                         "client_secret": _load().get("client_secret")})
    if status == 200 and tok.get("access_token"):
        with _lock:
            _access[uid] = (tok["access_token"], time.time() + int(tok.get("expires_in") or 3600) - 60)
        return tok["access_token"]
    reason, _msg = _err_reason(tok)
    if reason in ("invalid_grant", "unauthorized_client", "invalid_client"):
        _drop_refresh(uid)
        _mark(uid, "needs_reconnect", "Google sign-in expired or was removed (%s)" % reason)
        raise GmailError(reason, "Gmail was disconnected (the Google sign-in expired or was removed). Reconnect Gmail in Settings > Email.", reconnect=True)
    if status >= 500 or status == 429:
        raise GmailError(reason, "Google is busy; try again in a minute", retry=True, status=status)
    raise GmailError(reason, "Google refused to refresh the sign-in (%s)" % reason, status=status)


def _revoke(token):
    if not token:
        return True
    try:
        status, _ = _post_form(REVOKE_URL, {"token": token})
        return status in (200, 400)    # 400 = already invalid
    except GmailError:
        return False


def disconnect(uid):
    rt = _drop_refresh(uid)
    ok = _revoke(rt) if rt else True
    with db.tx() as c:
        c.execute("UPDATE gmail_accounts SET status='disconnected', last_error=? WHERE user_id=?",
                  (None if ok else "Couldn't reach Google to revoke; remove Movinite at myaccount.google.com > Security", uid))
    return ok


def forget_user(uid):
    """Admin deleted or demoted: revoke and delete their token."""
    try:
        disconnect(uid)
    except Exception:
        _drop_refresh(uid)
    with db.tx() as c:
        c.execute("DELETE FROM gmail_accounts WHERE user_id=?", (uid,))


def status_for(uid):
    r = db.row("SELECT email, display_name, connected_at, last_used, status, last_error FROM gmail_accounts WHERE user_id=?", (uid,))
    if r and r["status"] == "connected" and not _refresh_token(uid):
        r["status"] = "needs_reconnect"
    out = r or {"status": "disconnected"}
    out["sent_hour"], out["sent_day"] = _counts(uid)
    out["hourly_cap"], out["daily_cap"] = caps()
    return out


def connected(uid):
    r = db.row("SELECT status FROM gmail_accounts WHERE user_id=?", (uid,))
    return bool(r and r["status"] == "connected" and _refresh_token(uid) and configured())


def all_accounts():
    return db.rows("SELECT g.user_id, u.username, g.email, g.status FROM gmail_accounts g JOIN users u ON u.id=g.user_id ORDER BY u.username")


# ---------------------------------------------------------------- caps
def caps():
    def num(k, d):
        try:
            return max(1, int(settings.get(k, str(d))))
        except (TypeError, ValueError):
            return d
    return num("gmail_hourly_cap", HOURLY_CAP_DEFAULT), num("gmail_daily_cap", DAILY_CAP_DEFAULT)


def _counts(uid):
    now = int(time.time())
    h = db.row("SELECT COUNT(*) n FROM gmail_sends WHERE user_id=? AND ts>=?", (uid, now - 3600))["n"]
    d = db.row("SELECT COUNT(*) n FROM gmail_sends WHERE user_id=? AND ts>=?", (uid, now - 86400))["n"]
    return h, d


# ---------------------------------------------------------------- send
def _clean_header(v):
    return re.sub(r"[\r\n\t]+", " ", str(v or "")).strip()


def build_message(from_name, from_addr, to_addr, subject, text, html, msgid_domain=None):
    m = EmailMessage()
    from_name = _clean_header(from_name)[:120] or None
    from_addr = _clean_header(from_addr)
    to_addr = _clean_header(to_addr)
    try:
        m["From"] = Address(display_name=from_name or "", addr_spec=from_addr)
        m["To"] = Address(addr_spec=to_addr)
        m["Reply-To"] = Address(display_name=from_name or "", addr_spec=from_addr)
    except (ValueError, IndexError):
        raise GmailError("bad_address", "That email address isn't valid")
    m["Subject"] = _clean_header(subject)[:200]
    m["Date"] = formatdate(localtime=False)
    m["Message-ID"] = make_msgid(domain=(msgid_domain or "movinite.local"))
    m.set_content(text)
    m.add_alternative(html, subtype="html")
    return m


def send(uid, to_addr, subject, text, html, msgid_domain=None):
    """Send one message from this admin's Gmail. Raises GmailError. Returns Gmail's message id."""
    acct = db.row("SELECT email, display_name, status FROM gmail_accounts WHERE user_id=?", (uid,))
    if not acct or not configured() or not _refresh_token(uid):
        raise GmailError("not_connected", "Gmail isn't connected", reconnect=True)
    hcap, dcap = caps()
    sh, sd = _counts(uid)
    if sh >= hcap:
        raise GmailError("cap_hour", "Gmail limit reached: %d invites an hour. Share the link instead, or try later." % hcap)
    if sd >= dcap:
        raise GmailError("cap_day", "Gmail limit reached: %d invites a day. Share the link instead, or try tomorrow." % dcap)
    msg = build_message(acct.get("display_name"), acct["email"], to_addr, subject, text, html, msgid_domain)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    body = json.dumps({"raw": raw}).encode()
    delays = [1, 4, 16]
    refreshed = False
    attempt = 0
    while True:
        token = _access_token(uid)
        req = urllib.request.Request(GMAIL_BASE + "/gmail/v1/users/me/messages/send", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
        status, payload = _do(req)
        if status == 200:
            now = int(time.time())
            with db.tx() as c:
                c.execute("INSERT INTO gmail_sends(user_id, ts) VALUES(?,?)", (uid, now))
                c.execute("UPDATE gmail_accounts SET last_used=?, status='connected', last_error=NULL WHERE user_id=?", (now, uid))
            return payload.get("id")
        reason, gmsg = _err_reason(payload)
        if status == 401 and not refreshed:
            refreshed = True
            with _lock:
                _access.pop(uid, None)
            continue
        if status == 403 and reason in ("insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT", "PERMISSION_DENIED"):
            _drop_refresh(uid)
            _mark(uid, "needs_reconnect", "Permission to send email was removed")
            raise GmailError(reason, "Permission to send email was removed from Movinite. Reconnect Gmail in Settings > Email.", reconnect=True, status=status)
        if status == 401:
            _mark(uid, "needs_reconnect", "Google rejected the sign-in")
            raise GmailError(reason, "Google rejected the Gmail sign-in. Reconnect Gmail in Settings > Email.", reconnect=True, status=status)
        if reason in ("dailyLimitExceeded", "quotaExceeded") or "Daily" in (gmsg or "") or "sending limit" in (gmsg or "").lower():
            raise GmailError("daily_limit", "Gmail's daily sending limit was reached for this account. Share the link instead, or try tomorrow.", status=status)
        if status == 429 or reason in ("rateLimitExceeded", "userRateLimitExceeded") or status >= 500:
            if attempt < len(delays):
                time.sleep(_sleep(delays[attempt]))
                attempt += 1
                continue
            raise GmailError(reason or "busy", "Gmail is busy; try again in a few minutes, or share the link.", retry=True, status=status)
        if status == 400:
            raise GmailError(reason or "bad_request", "Gmail didn't accept the message (%s). Check the email address." % (reason or "invalid"), status=status)
        raise GmailError(reason or "error", "Gmail returned an error (%s %s)" % (status, reason), status=status)


def _sleep(s):
    return float(os.environ.get("MS_GMAIL_BACKOFF_SCALE", "1")) * s
