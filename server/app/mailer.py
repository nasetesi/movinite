"""1.9: send invite email over SMTP -- a Gmail app password (the default) or any SMTP server.

Settings (non-secret, in the settings table):
    mail_method      smtp (default) | gmail_oauth  (Advanced: Connect Gmail with Google sign-in, see gmail.py)
    smtp_provider    gmail | custom
    smtp_host / smtp_port / smtp_security (starttls | ssl | none) / smtp_user / smtp_from_addr / smtp_from_name
    smtp_status      ok | error | auth_failed  + smtp_last_error, smtp_last_used
Secret: the password lives only in data/secrets/smtp.sealed (AES-256-GCM with a key derived from the server key).
It is never returned by the API, never written to the database, and never logged.

Gmail: smtp.gmail.com:587 with STARTTLS; the From address must be the Gmail address (Gmail rewrites any
other From), Reply-To is the same address. 2-Step Verification + an app password are required.
Caps (Settings > Email, default 20 an hour / 100 a day) count every message sent through this account.
"""
import logging
import os
import re
import smtplib
import socket
import ssl
import threading
import time

from . import db, gmail, keys, settings

log = logging.getLogger("media-server")
PURPOSE = "smtp/v1"
SEALED = keys.SECRETS_DIR / "smtp.sealed"
ACCOUNT_ID = 0                    # gmail_sends.user_id used for the server's SMTP account
TIMEOUT = 20
SECURITY = ("starttls", "ssl", "none")
APP_PASSWORD_URL = "https://myaccount.google.com/apppasswords"
_lock = threading.RLock()
EMAIL_RE = re.compile(r"^[^@\s<>\"',;]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class MailError(Exception):
    def __init__(self, code, message, fix=False, retry=False):
        super().__init__(message)
        self.code, self.message, self.fix, self.retry = code, message, fix, retry
        self.reconnect = fix          # same meaning for the UI as gmail.GmailError.reconnect


def gmail_host():
    return os.environ.get("MS_GMAIL_SMTP_HOST") or "smtp.gmail.com", int(os.environ.get("MS_GMAIL_SMTP_PORT") or 587)


def _get(k, d=""):
    return (settings.get(k, d) or d)


def method():
    return "gmail_oauth" if _get("mail_method", "smtp") == "gmail_oauth" else "smtp"


def _password():
    try:
        return (keys.read_sealed(SEALED, PURPOSE, default={}) or {}).get("password")
    except Exception as e:
        log.error("mail: cannot read the sealed SMTP password (%s)", type(e).__name__)
        return None


def config():
    prov = _get("smtp_provider", "gmail")
    if prov == "gmail":
        host, port = gmail_host()
        sec = "starttls" if port != 465 else "ssl"
        user = _get("smtp_user").strip()
        from_addr = user
    else:
        host, sec = _get("smtp_host").strip(), _get("smtp_security", "starttls")
        try:
            port = int(_get("smtp_port", "587"))
        except ValueError:
            port = 587
        user = _get("smtp_user").strip()
        from_addr = _get("smtp_from_addr").strip() or user
    return {"provider": prov, "host": host, "port": port, "security": sec if sec in SECURITY else "starttls",
            "user": user, "from_addr": from_addr, "from_name": _get("smtp_from_name").strip()}


def configured():
    c = config()
    return keys.available() and bool(c["host"] and c["from_addr"] and (c["user"] == "" or _password()))


def counts():
    now = int(time.time())
    h = db.row("SELECT COUNT(*) n FROM gmail_sends WHERE user_id=? AND ts>=?", (ACCOUNT_ID, now - 3600))["n"]
    d = db.row("SELECT COUNT(*) n FROM gmail_sends WHERE user_id=? AND ts>=?", (ACCOUNT_ID, now - 86400))["n"]
    return h, d


def suggested_name(user):
    """The From name to prefill: the Google account's name if Connect Gmail ever told us, else the user's name."""
    if user:
        r = db.row("SELECT display_name FROM gmail_accounts WHERE user_id=? AND display_name IS NOT NULL", (user["id"],))
        if r and r["display_name"]:
            return r["display_name"]
        return user.get("username") or ""
    return ""


def status(user=None):
    c = config()
    h, d = counts()
    hc, dc = gmail.caps()
    st = _get("smtp_status", "")
    ready = configured()
    return dict(c, password_saved=bool(_password()), configured=ready, method=method(),
                status=("not_set_up" if not ready else (st or "untested")), last_error=_get("smtp_last_error") or None,
                last_used=int(_get("smtp_last_used", "0") or 0) or None, sent_hour=h, sent_day=d, hourly_cap=hc,
                daily_cap=dc, suggested_from_name=suggested_name(user), app_password_url=APP_PASSWORD_URL,
                crypto=keys.available())


def _mark(st, err=None):
    settings.put("smtp_status", st)
    settings.put("smtp_last_error", err or "")


def save(body):
    """Validate and store. Returns the list of changed setting names (never values)."""
    if not keys.available():
        raise MailError("no_crypto", "This server is missing the Python 'cryptography' package; re-run update.sh")
    prov = body.get("provider") or _get("smtp_provider", "gmail")
    if prov not in ("gmail", "custom"):
        raise MailError("bad", "Pick Gmail or Other email")
    user = (body.get("user") if "user" in body else _get("smtp_user")) or ""
    user = re.sub(r"\s+", "", user)
    name = re.sub(r"[\r\n\t]+", " ", (body.get("from_name") if "from_name" in body else _get("smtp_from_name")) or "").strip()[:80]
    pw = body.get("password")
    changed = []
    if prov == "gmail":
        if not EMAIL_RE.match(user):
            raise MailError("bad_address", "Enter your Gmail address, for example you@gmail.com")
        if pw:
            pw = re.sub(r"\s+", "", pw)            # Google shows app passwords as four groups of four
            if not re.match(r"^[A-Za-z]{16}$", pw):
                raise MailError("bad_password", "A Google app password is 16 letters (shown as four groups of four). Your normal Gmail password won't work.")
        host_fields = {}
    else:
        host = (body.get("host") if "host" in body else _get("smtp_host")) or ""
        host = host.strip()
        if not re.match(r"^[A-Za-z0-9.-]{1,253}$", host):
            raise MailError("bad_host", "Enter the SMTP server name, for example smtp.example.com")
        try:
            port = int(body.get("port") if "port" in body else _get("smtp_port", "587"))
        except (TypeError, ValueError):
            port = 0
        if not 1 <= port <= 65535:
            raise MailError("bad_port", "Port is a number like 587 (STARTTLS) or 465 (SSL)")
        sec = body.get("security") if "security" in body else _get("smtp_security", "starttls")
        if sec not in SECURITY:
            raise MailError("bad_security", "Pick STARTTLS, SSL/TLS or None")
        from_addr = re.sub(r"\s+", "", (body.get("from_addr") if "from_addr" in body else _get("smtp_from_addr")) or "") or user
        if not EMAIL_RE.match(from_addr):
            raise MailError("bad_address", "Enter the From address (the email address invites come from)")
        if pw:
            pw = pw.strip()
        host_fields = {"smtp_host": host, "smtp_port": str(port), "smtp_security": sec, "smtp_from_addr": from_addr}
    if pw is not None and len(pw) > 512:
        raise MailError("bad_password", "That password is too long")
    new = dict(host_fields, smtp_provider=prov, smtp_user=user, smtp_from_name=name)
    account_changed = False
    for k, v in new.items():
        if (_get(k) or "") != v:
            settings.put(k, v)
            changed.append(k)
            if k not in ("smtp_from_name",):
                account_changed = True
    with _lock:
        if pw:
            keys.write_sealed(SEALED, PURPOSE, {"password": pw})
            changed.append("smtp_password")
            account_changed = True
        elif account_changed and "smtp_user" in changed and _password():
            # a different account: the old password belongs to someone else
            keys.write_sealed(SEALED, PURPOSE, {})
            changed.append("smtp_password_cleared")
    if account_changed:
        _mark("", None)
    return changed


def forget():
    with _lock:
        if SEALED.exists():
            keys.write_sealed(SEALED, PURPOSE, {})
            try:
                SEALED.unlink()
            except OSError:
                pass
    for k in ("smtp_user", "smtp_from_addr", "smtp_host", "smtp_status", "smtp_last_error"):
        settings.put(k, "")


def _ctx():
    return ssl.create_default_context(cafile=os.environ.get("MS_SMTP_CAFILE") or None)


def _gmail_hint(c):
    return c["provider"] == "gmail"


def _explain(e, c):
    """Map an smtplib / socket error to a MailError with a plain message."""
    where = "%s:%s" % (c["host"], c["port"])
    g = _gmail_hint(c)
    if isinstance(e, smtplib.SMTPAuthenticationError):
        txt = (e.smtp_error or b"").decode("utf-8", "replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        if e.smtp_code == 534 or "Application-specific password required" in txt or "5.7.9" in txt:
            return MailError("app_password_required", "Gmail needs an app password, not your normal password. Turn on 2-Step Verification, "
                             "create one at myaccount.google.com/apppasswords and save it here." if g else
                             "The mail server wants a different kind of password (an app password).", fix=True)
        if e.smtp_code == 454 or "4.7.0" in txt:
            return MailError("auth_busy", "The mail server is temporarily refusing sign-ins (too many attempts). Try again in a few minutes.", retry=True)
        return MailError("auth", ("Gmail didn't accept the address and app password (535). Check the Gmail address, create a new app password "
                                  "at myaccount.google.com/apppasswords (2-Step Verification must be on) and save it again.") if g else
                         "The mail server didn't accept the username and password (%s)." % e.smtp_code, fix=True)
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        codes = [v[0] for v in (e.recipients or {}).values()]
        txt = " ".join((v[1].decode("utf-8", "replace") if isinstance(v[1], bytes) else str(v[1])) for v in (e.recipients or {}).values())
        if any(400 <= cd < 500 for cd in codes):
            return MailError("busy", "The mail server asked to try later (%s)." % (codes[0] if codes else "4xx"), retry=True)
        if "5.4.5" in txt or "sending limit" in txt.lower():
            return MailError("daily_limit", "Gmail's daily sending limit was reached for this account. Share the link instead, or try tomorrow.")
        return MailError("bad_address", "The mail server refused that email address. Check it and try again.")
    if isinstance(e, (smtplib.SMTPSenderRefused, smtplib.SMTPDataError, smtplib.SMTPResponseException)):
        code = getattr(e, "smtp_code", 0) or 0
        txt = getattr(e, "smtp_error", b"")
        txt = txt.decode("utf-8", "replace") if isinstance(txt, bytes) else str(txt)
        if "5.4.5" in txt or "sending limit" in txt.lower() or "quota" in txt.lower():
            return MailError("daily_limit", "Gmail's daily sending limit was reached for this account. Share the link instead, or try tomorrow." if g
                             else "The mail server's sending limit was reached. Share the link instead, or try later.")
        if 400 <= code < 500:
            return MailError("busy", "The mail server asked to try later (%s)." % code, retry=True)
        if code == 530:
            return MailError("auth_required", "The mail server requires signing in; add the username and password.", fix=True)
        if code in (550, 553, 554) and ("From" in txt or "sender" in txt.lower()):
            return MailError("bad_sender", "The mail server refused the From address. For Gmail it must be the Gmail address itself.", fix=True)
        return MailError("rejected", "The mail server refused the message (%s)." % code)
    if isinstance(e, smtplib.SMTPNotSupportedError):
        return MailError("tls", "The mail server doesn't offer STARTTLS on %s. Try SSL/TLS on port 465." % where, fix=True)
    if isinstance(e, ssl.SSLCertVerificationError):
        return MailError("tls", "The mail server's certificate couldn't be verified (%s)." % where, fix=True)
    if isinstance(e, ssl.SSLError):
        return MailError("tls", "Secure connection to %s failed. Check the port and security setting (587 = STARTTLS, 465 = SSL/TLS)." % where, fix=True)
    if isinstance(e, smtplib.SMTPServerDisconnected):
        return MailError("busy", "The mail server closed the connection; try again in a minute.", retry=True)
    if isinstance(e, (socket.timeout, TimeoutError)):
        return MailError("timeout", "Timed out talking to %s. Check this server's internet access." % where, retry=True)
    if isinstance(e, socket.gaierror):
        return MailError("connect", "Couldn't find the mail server %s. Check the name." % c["host"], fix=True)
    if isinstance(e, OSError):
        return MailError("connect", "Couldn't connect to %s (%s). Check the port and this server's internet access (some networks block outgoing mail ports)." % (where, type(e).__name__), retry=True)
    return MailError("error", "Sending failed (%s)." % type(e).__name__)


def _deliver_once(c, pw, msg, to_addr):
    if c["security"] == "ssl":
        s = smtplib.SMTP_SSL(c["host"], c["port"], timeout=TIMEOUT, context=_ctx())
    else:
        s = smtplib.SMTP(c["host"], c["port"], timeout=TIMEOUT)
    try:
        s.ehlo()
        if c["security"] == "starttls":
            s.starttls(context=_ctx())
            s.ehlo()
        if c["user"]:
            s.login(c["user"], pw or "")
        s.send_message(msg, from_addr=c["from_addr"], to_addrs=[to_addr])
    finally:
        try:
            s.quit()
        except Exception:
            try:
                s.close()
            except Exception:
                pass


def _sleep(sec):
    scale = os.environ.get("MS_MAIL_BACKOFF_SCALE") or os.environ.get("MS_GMAIL_BACKOFF_SCALE") or "1"
    time.sleep(float(scale) * sec)


def send(to_addr, subject, text, html, from_name=None, msgid_domain=None):
    """Send one message. Raises MailError. Counts toward the hourly / daily caps."""
    if not configured():
        raise MailError("not_configured", "Email sending isn't set up (Settings > Email)", fix=True)
    c = config()
    hcap, dcap = gmail.caps()
    sh, sd = counts()
    if sh >= hcap:
        raise MailError("cap_hour", "Email limit reached: %d invites an hour. Share the link instead, or try later." % hcap)
    if sd >= dcap:
        raise MailError("cap_day", "Email limit reached: %d invites a day. Share the link instead, or try tomorrow." % dcap)
    try:
        msg = gmail.build_message(from_name or c["from_name"] or None, c["from_addr"], to_addr, subject, text, html, msgid_domain)
    except gmail.GmailError as e:
        raise MailError(e.code, e.message)
    pw = _password()
    delays = [1, 4, 16]
    attempt = 0
    while True:
        try:
            _deliver_once(c, pw, msg, to_addr)
            break
        except Exception as e:   # noqa: BLE001 -- mapped below, password never included
            err = _explain(e, c)
            log.warning("mail: send via %s:%s failed (%s)", c["host"], c["port"], err.code)
            if err.retry and err.code not in ("auth_busy",) and attempt < len(delays):
                _sleep(delays[attempt])
                attempt += 1
                continue
            if err.fix:
                _mark("auth_failed" if err.code in ("auth", "app_password_required") else "error", err.message)
            elif err.code not in ("cap_hour", "cap_day", "bad_address"):
                _mark("error", err.message)
            raise err
    now = int(time.time())
    with db.tx() as cx:
        cx.execute("INSERT INTO gmail_sends(user_id, ts) VALUES(?,?)", (ACCOUNT_ID, now))
    settings.put("smtp_last_used", str(now))
    _mark("ok", None)
    return True


# ---------------------------------------------------------------- one view for the UI / invites
def active(user):
    """How invites from this admin go out right now: 'smtp', 'gmail_oauth' or None (copy link / QR)."""
    if method() == "gmail_oauth":
        return "gmail_oauth" if gmail.connected(user["id"]) else None
    return "smtp" if configured() else None


def sender(user):
    """{method, ready, from_name, from_addr, status, last_error, sent_hour, sent_day, hourly_cap, daily_cap}"""
    m = method()
    if m == "gmail_oauth":
        g = gmail.status_for(user["id"])
        return {"method": m, "ready": g.get("status") == "connected", "from_name": g.get("display_name"),
                "from_addr": g.get("email"), "status": g.get("status"), "last_error": g.get("last_error"),
                "sent_hour": g.get("sent_hour"), "sent_day": g.get("sent_day"), "hourly_cap": g.get("hourly_cap"),
                "daily_cap": g.get("daily_cap")}
    s = status(user)
    return {"method": m, "ready": s["configured"], "from_name": s["from_name"] or suggested_name(user), "from_addr": s["from_addr"],
            "status": s["status"], "last_error": s["last_error"], "sent_hour": s["sent_hour"], "sent_day": s["sent_day"],
            "hourly_cap": s["hourly_cap"], "daily_cap": s["daily_cap"], "provider": s["provider"]}
