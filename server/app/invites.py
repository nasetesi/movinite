"""1.9: invite people by email.

- one-time token (32 random bytes); only its sha256 is stored; 7 days by default (24 h / 3 / 7 / 30 days)
- the invite carries the role (view | download) and the libraries (all, or a list)
- sent from the inviting admin's own Gmail when it is connected (gmail.py); otherwise the admin gets a
  Copy link / QR code to share it themselves
- accepting creates the account and signs the person in; wrong / used / expired links all get the same message
"""
import hashlib
import html as _html
import json
import re
import secrets
import time
from datetime import datetime
from urllib.parse import urlparse

from . import auth, db, gmail, settings, useractivity

EXPIRY_CHOICES = {1: "24 hours", 3: "3 days", 7: "7 days", 30: "30 days"}
INVALID = "This invite isn't valid any more. Ask the person who invited you for a new one."
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


class InviteError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.msg, self.status = msg, status


def thash(tok):
    return hashlib.sha256(("inv1:" + (tok or "")).encode()).hexdigest()


def valid_email(e):
    e = (e or "").strip()
    return bool(len(e) <= 254 and EMAIL_RE.match(e))


def server_name():
    return (settings.get("server_name", "") or "").strip() or "Movinite"


def link_for(base_url, tok):
    return base_url.rstrip("/") + "/#/invite/" + tok


def _libs_for(ids):
    if ids is None:
        return None
    ok = {r["id"] for r in db.rows("SELECT id FROM libraries")}
    return sorted({int(x) for x in ids if int(x) in ok})


def create(admin, email, role="view", libraries=None, note="", days=7):
    email = (email or "").strip()
    if not valid_email(email):
        raise InviteError("Enter a valid email address")
    role = role if role in ("view", "download") else "view"
    if db.row("SELECT id FROM users WHERE email=?", (email,)):
        raise InviteError("Someone with that email already has an account", 409)
    days = int(days) if int(days or 7) in EXPIRY_CHOICES else 7
    libs = _libs_for(libraries)
    if libs is not None and not libs:
        raise InviteError("Pick at least one library, or choose All libraries")
    note = (note or "").strip()[:500]
    tok = secrets.token_urlsafe(32)
    now = int(time.time())
    with db.tx() as c:
        # a fresh invite to the same address replaces any pending one
        c.execute("UPDATE invites SET revoked_at=? WHERE email=? AND accepted_at IS NULL AND revoked_at IS NULL", (now, email))
        cur = c.execute("INSERT INTO invites(token_hash,email,role,libraries,note,created_by,created_at,expires_at) "
                        "VALUES(?,?,?,?,?,?,?,?)", (thash(tok), email, role, json.dumps(libs) if libs is not None else None,
                                                     note or None, admin["id"], now, now + days * 86400))
        iid = cur.lastrowid
    useractivity.record("invite_created", user=admin, detail={"email": email, "role": role, "days": days})
    return iid, tok


def renew(admin, iid):
    inv = db.row("SELECT * FROM invites WHERE id=?", (iid,))
    if not inv or inv["accepted_at"]:
        raise InviteError("That invite can't be resent", 404)
    tok = secrets.token_urlsafe(32)
    now = int(time.time())
    days = max(1, round((inv["expires_at"] - inv["created_at"]) / 86400))
    with db.tx() as c:
        c.execute("UPDATE invites SET token_hash=?, created_at=?, expires_at=?, revoked_at=NULL, send_error=NULL WHERE id=?",
                  (thash(tok), now, now + days * 86400, iid))
    return tok


def revoke(admin, iid):
    with db.tx() as c:
        n = c.execute("UPDATE invites SET revoked_at=? WHERE id=? AND accepted_at IS NULL AND revoked_at IS NULL",
                      (int(time.time()), iid)).rowcount
    if n:
        inv = db.row("SELECT email FROM invites WHERE id=?", (iid,))
        useractivity.record("invite_revoked", user=admin, detail={"email": inv and inv["email"]})
    return n


def state(inv, now=None):
    now = now or time.time()
    if inv.get("accepted_at"):
        return "accepted"
    if inv.get("revoked_at"):
        return "revoked"
    if inv["expires_at"] < now:
        return "expired"
    return "pending"


def list_all():
    names = {r["id"]: r["name"] for r in db.rows("SELECT id, name FROM libraries")}
    users = {r["id"]: r["username"] for r in db.rows("SELECT id, username FROM users")}
    out = []
    for r in db.rows("SELECT * FROM invites ORDER BY created_at DESC LIMIT 500"):
        r.pop("token_hash", None)
        libs = json.loads(r["libraries"]) if r.get("libraries") else None
        r["libraries"] = libs
        r["library_names"] = None if libs is None else [names.get(i, "?") for i in libs]
        r["state"] = state(r)
        r["created_by_name"] = users.get(r.get("created_by"))
        r["accepted_username"] = users.get(r.get("accepted_user_id"))
        out.append(r)
    return out


def lookup(tok):
    if not tok or len(tok) > 200:
        return None
    inv = db.row("SELECT * FROM invites WHERE token_hash=?", (thash(tok),))
    if not inv or state(inv) != "pending":
        return None
    return inv


def preview(tok):
    inv = lookup(tok)
    if not inv:
        raise InviteError(INVALID, 404)
    by = db.row("SELECT username FROM users WHERE id=?", (inv["created_by"],))
    g = db.row("SELECT display_name FROM gmail_accounts WHERE user_id=?", (inv["created_by"],))
    libs = json.loads(inv["libraries"]) if inv.get("libraries") else None
    names = [r["name"] for r in db.rows("SELECT name FROM libraries " + ("WHERE id IN (%s)" % ",".join(str(int(i)) for i in libs) if libs else "") + " ORDER BY name")] if libs != [] else []
    return {"server": server_name(), "inviter": (g and g["display_name"]) or (by and by["username"]) or "An admin",
            "email": inv["email"], "role": inv["role"], "role_label": auth.ROLE_LABEL.get(inv["role"], inv["role"]),
            "libraries": names, "all_libraries": libs is None, "note": inv.get("note"), "expires_at": inv["expires_at"]}


def accept(tok, username, password):
    username = (username or "").strip()
    inv = lookup(tok)
    if not inv:
        raise InviteError(INVALID, 404)
    if not re.match(r"^[A-Za-z0-9._@-]{2,64}$", username):
        raise InviteError("Usernames are 2-64 characters: letters, numbers, . _ - @")
    if len(password or "") < 8:
        raise InviteError("Password must be at least 8 characters")
    if db.row("SELECT id FROM users WHERE username=?", (username,)):
        raise InviteError("That username is taken; pick another", 409)
    if db.row("SELECT id FROM users WHERE email=?", (inv["email"],)):
        raise InviteError("Someone with that email already has an account", 409)
    libs = json.loads(inv["libraries"]) if inv.get("libraries") else None
    now = int(time.time())
    with db.tx() as c:   # claim the invite first so a double submit can't create two accounts
        n = c.execute("UPDATE invites SET accepted_at=? WHERE id=? AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at>?",
                      (now, inv["id"], now)).rowcount
    if not n:
        raise InviteError(INVALID, 404)
    try:
        uid = auth.create_user(username, password, role=inv["role"], email=inv["email"], all_libraries=libs is None,
                               libraries=libs, invited_by=inv["created_by"])
    except Exception:
        with db.tx() as c:
            c.execute("UPDATE invites SET accepted_at=NULL WHERE id=?", (inv["id"],))
        raise
    with db.tx() as c:
        c.execute("UPDATE invites SET accepted_user_id=? WHERE id=?", (uid, inv["id"]))
    useractivity.record("invite_accepted", user={"id": uid, "username": username}, detail={"email": inv["email"], "role": inv["role"]})
    return uid


# ---------------------------------------------------------------- the email
def _fmt_expiry(ts):
    try:
        d = datetime.fromtimestamp(ts).astimezone()
        return d.strftime("%a, %b %-d at %-I:%M %p ") + (d.tzname() or "")
    except Exception:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def compose(inv, link, sender_name, base_url):
    """Returns (subject, text, html) for one invite."""
    p = urlparse(base_url)
    host = p.netloc or base_url
    who = (sender_name or "").strip() or "Someone you know"
    first = who.split()[0] if who != "Someone you know" else who
    libs = json.loads(inv["libraries"]) if inv.get("libraries") else None
    names = [r["name"] for r in db.rows("SELECT name FROM libraries WHERE id IN (%s) ORDER BY name" % ",".join(str(int(i)) for i in libs))] if libs else []
    role_txt = "watch, and download for offline viewing" if inv["role"] == "download" else "watch"
    lib_txt = ", ".join(names) if names else "all of the libraries"
    exp = _fmt_expiry(inv["expires_at"])
    note = (inv.get("note") or "").strip()
    subject = "%s invited you to their Movinite" % first
    text = ["Hi,", "",
            "%s invited you to watch movies and shows on %s (%s)." % (who, server_name(), host), ""]
    if note:
        text += ["Their note:", ""] + ["  > " + ln for ln in note.splitlines()] + [""]
    text += ["You'll be able to %s: %s." % (role_txt, lib_txt), "",
             "Accept the invite:", link, "",
             "This link works once and expires on %s." % exp, "",
             "--",
             "You got this because %s entered your address. If you weren't expecting it, you can ignore this email; "
             "nothing happens unless you open the link." % who]
    e = _html.escape
    note_html = ""
    if note:
        note_html = ('<tr><td style="padding:0 32px 18px"><div style="border-left:3px solid #8424EA;background:#1d1530;'
                     'padding:12px 16px;border-radius:8px;color:#e9e3f5;font-size:15px;line-height:1.5;white-space:pre-wrap">'
                     '%s</div></td></tr>' % e(note))
    logo = base_url.rstrip("/") + "/static/logo-full.png"
    html = """<!doctype html><html><body style="margin:0;padding:0;background:#0d0a14">
<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="background:#0d0a14;padding:24px 0"><tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%%;background:#151020;border:1px solid #2a2140;border-radius:16px;font-family:Segoe UI,Helvetica,Arial,sans-serif">
<tr><td align="center" style="padding:28px 32px 8px"><img src="%(logo)s" width="180" alt="Movinite" style="display:block;border:0;max-width:180px;height:auto;color:#B07CFF;font-size:24px;font-weight:700"></td></tr>
<tr><td style="padding:8px 32px 6px;color:#f3eefc;font-size:20px;font-weight:600">%(who)s invited you to %(server)s</td></tr>
<tr><td style="padding:0 32px 18px;color:#bfb4d6;font-size:15px;line-height:1.5">Watch movies and shows on <span style="color:#B07CFF">%(host)s</span>.</td></tr>
%(note)s
<tr><td style="padding:0 32px 22px;color:#bfb4d6;font-size:14px;line-height:1.5">You'll be able to %(role)s: <b style="color:#e9e3f5">%(libs)s</b>.</td></tr>
<tr><td align="center" style="padding:0 32px 18px"><a href="%(link)s" style="display:inline-block;background:#8424EA;color:#ffffff;text-decoration:none;font-weight:600;font-size:16px;padding:13px 28px;border-radius:10px">Accept invite</a></td></tr>
<tr><td style="padding:0 32px 8px;color:#8f84a8;font-size:12px;line-height:1.5;word-break:break-all">Or open this link: <a href="%(link)s" style="color:#B07CFF">%(link)s</a></td></tr>
<tr><td style="padding:0 32px 22px;color:#8f84a8;font-size:12px">This link works once and expires on %(exp)s.</td></tr>
<tr><td style="padding:16px 32px 26px;border-top:1px solid #2a2140;color:#6f6688;font-size:11px;line-height:1.5">You got this because %(who)s entered your address. If you weren't expecting it, you can ignore this email; nothing happens unless you open the link.</td></tr>
</table></td></tr></table></body></html>""" % {"logo": e(logo), "who": e(who), "server": e(server_name()), "host": e(host),
                                                 "note": note_html, "role": e(role_txt), "libs": e(lib_txt), "link": e(link), "exp": e(exp)}
    return subject, "\n".join(text) + "\n", html


def deliver(admin, iid, tok, base_url):
    """Email the invite (SMTP / Gmail app password by default, or Connect Gmail when chosen under Advanced).
    Returns {"sent": bool, "via", "error", "link"}; without email set up, or on any failure, the link is returned
    so the admin can share it (copy / QR)."""
    from . import mailer
    inv = db.row("SELECT * FROM invites WHERE id=?", (iid,))
    link = link_for(base_url, tok)
    how = mailer.active(admin)
    snd = mailer.sender(admin)
    if not how:
        with db.tx() as c:
            c.execute("UPDATE invites SET sent_via='link' WHERE id=?", (iid,))
        return {"sent": False, "via": "link", "error": None, "link": link, "mail": snd["status"], "method": snd["method"]}
    name = snd.get("from_name") or admin.get("username")
    subject, text, html = compose(inv, link, name, base_url)
    try:
        if how == "gmail_oauth":
            gmail.send(admin["id"], inv["email"], subject, text, html, msgid_domain=urlparse(base_url).hostname)
        else:
            mailer.send(inv["email"], subject, text, html, from_name=name, msgid_domain=urlparse(base_url).hostname)
    except (gmail.GmailError, mailer.MailError) as e:
        with db.tx() as c:
            c.execute("UPDATE invites SET send_error=?, sent_via='link' WHERE id=?", (e.message[:300], iid))
        useractivity.record("invite_send_failed", user=admin, detail={"email": inv["email"], "reason": e.code, "via": how})
        if e.reconnect:
            useractivity.record("gmail_error" if how == "gmail_oauth" else "email_error", user=admin, detail={"reason": e.code})
        return {"sent": False, "via": "link", "error": e.message, "reconnect": e.reconnect, "link": link, "method": how}
    with db.tx() as c:
        c.execute("UPDATE invites SET sent_at=?, sent_via=?, send_error=NULL, send_count=send_count+1 WHERE id=?",
                  (int(time.time()), "gmail" if how == "gmail_oauth" else "email", iid))
    useractivity.record("invite_sent", user=admin, detail={"email": inv["email"], "via": how, "from": snd.get("from_addr")})
    return {"sent": True, "via": how, "from": snd.get("from_addr"), "from_name": name, "link": link}
