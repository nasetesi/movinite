"""1.9: a fake Google OAuth + Gmail API for tests (no internet, no real Google account).

    from tests import mock_google; port = mock_google.start()
    MS_GOOGLE_AUTH_URL=http://127.0.0.1:<port>/o/oauth2/v2/auth  (and _TOKEN_URL, _REVOKE_URL, MS_GMAIL_API_BASE)

Only the fake client below is accepted. STATE holds what was received so tests can assert on it, and FAIL
lets a test inject errors (e.g. FAIL["send"] = [(429, {...}), ...] or FAIL["refresh"] = "invalid_grant").
"""
import base64
import hashlib
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

CLIENT_ID = "123456789012-faketestclient.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-FAKE-test-secret-not-real"
TEST_EMAIL = "test.host@example.com"
TEST_NAME = "Test Host"

STATE = {"codes": {}, "refresh": {}, "access": {}, "sent": [], "revoked": [], "token_calls": [], "granted_scope": None}
FAIL = {}
_lock = threading.Lock()


def _b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")


def id_token(email=TEST_EMAIL, name=TEST_NAME):
    return "%s.%s.%s" % (_b64({"alg": "none"}), _b64({"email": email, "email_verified": True, "name": name, "iss": "mock"}), "sig")


def authorize(query):
    """What Google would do after the user signs in and approves: returns the redirect URL."""
    q = {k: v[0] for k, v in parse_qs(query).items()}
    assert q["client_id"] == CLIENT_ID, "wrong client"
    assert q["code_challenge_method"] == "S256" and q["access_type"] == "offline"
    code = "mockcode-" + secrets.token_urlsafe(12)
    with _lock:
        STATE["codes"][code] = {"redirect": q["redirect_uri"], "challenge": q["code_challenge"],
                                "scope": STATE.get("granted_scope") or q["scope"]}
    return "%s?state=%s&code=%s&scope=%s" % (q["redirect_uri"], q["state"], code, q["scope"].replace(" ", "+"))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode()
        path = urlparse(self.path).path
        if path == "/token":
            f = {k: v[0] for k, v in parse_qs(body).items()}
            with _lock:
                STATE["token_calls"].append({k: ("<redacted>" if k in ("client_secret", "refresh_token", "code", "code_verifier") else v) for k, v in f.items()})
            if f.get("client_id") != CLIENT_ID or f.get("client_secret") != CLIENT_SECRET:
                return self._json(401, {"error": "invalid_client"})
            if f.get("grant_type") == "authorization_code":
                with _lock:
                    c = STATE["codes"].pop(f.get("code"), None)
                if not c:
                    return self._json(400, {"error": "invalid_grant"})
                if c["redirect"] != f.get("redirect_uri"):
                    return self._json(400, {"error": "redirect_uri_mismatch"})
                ch = base64.urlsafe_b64encode(hashlib.sha256(f.get("code_verifier", "").encode()).digest()).decode().rstrip("=")
                if ch != c["challenge"]:
                    return self._json(400, {"error": "invalid_grant", "error_description": "PKCE mismatch"})
                rt, at = "1//mock-refresh-" + secrets.token_urlsafe(16), "ya29.mock-access-" + secrets.token_urlsafe(16)
                with _lock:
                    STATE["refresh"][rt] = True
                    STATE["access"][at] = True
                return self._json(200, {"access_token": at, "expires_in": 3599, "refresh_token": rt, "scope": c["scope"],
                                        "token_type": "Bearer", "id_token": id_token()})
            if f.get("grant_type") == "refresh_token":
                if FAIL.get("refresh"):
                    return self._json(400, {"error": FAIL["refresh"]})
                if not STATE["refresh"].get(f.get("refresh_token")):
                    return self._json(400, {"error": "invalid_grant"})
                at = "ya29.mock-access-" + secrets.token_urlsafe(16)
                with _lock:
                    STATE["access"][at] = True
                return self._json(200, {"access_token": at, "expires_in": 3599, "token_type": "Bearer"})
            return self._json(400, {"error": "unsupported_grant_type"})
        if path == "/revoke":
            tok = parse_qs(body).get("token", [""])[0]
            with _lock:
                STATE["revoked"].append(tok)
                STATE["refresh"].pop(tok, None)
            return self._json(200, {})
        if path == "/gmail/v1/users/me/messages/send":
            auth = self.headers.get("Authorization") or ""
            with _lock:
                queue = FAIL.get("send") or []
                inj = queue.pop(0) if queue else None
            if inj:
                return self._json(inj[0], inj[1])
            if not auth.startswith("Bearer ") or not STATE["access"].get(auth[7:]):
                return self._json(401, {"error": {"code": 401, "status": "UNAUTHENTICATED", "message": "Invalid Credentials"}})
            raw = json.loads(body)["raw"]
            mime = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
            with _lock:
                STATE["sent"].append(mime)
            return self._json(200, {"id": "mockmsg%d" % len(STATE["sent"]), "threadId": "t1", "labelIds": ["SENT"]})
        self._json(404, {"error": "not found"})


_srv = None


def start(port=0):
    global _srv
    _srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=_srv.serve_forever, daemon=True).start()
    return _srv.server_address[1]


def reset():
    with _lock:
        for k in ("codes", "refresh", "access"):
            STATE[k].clear()
        for k in ("sent", "revoked", "token_calls"):
            STATE[k].clear()
        STATE["granted_scope"] = None
        FAIL.clear()
