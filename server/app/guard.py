"""1.9: request guard (pure ASGI, so file and HLS streaming pass through untouched).

For every /api/ request with a session cookie it:
1. enforces per-library access for users who don't have "All libraries":
   - /api/libraries/{id}/..., ?library_id=..., /api/items/{id}/... -> 404 when the library isn't theirs
   - JSON GET responses: any object carrying a library_id they can't see is dropped from lists
     (home rows, search, continue watching, person pages, playlists, versions, the scan indicator ...)
   - /api/libraries and /api/libraries/health only list their libraries
2. feeds Activity > Now playing (HLS playlist / segments, direct file reads, progress heartbeats).
Admins and "All libraries" users are not buffered or rewritten at all.
"""
import json
import re
import threading
import time
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

from . import auth, db, netutil, useractivity

RE_LIB = re.compile(r"^/api/libraries/(\d+)(?:/|$)")
RE_ITEM = re.compile(r"^/api/items/(\d+)(?:/|$)")
RE_HLS = re.compile(r"^/api/items/(\d+)/hls/([A-Za-z0-9_-]+)/(index\.m3u8|seg\d+\.(?:ts|m4s)|init\.mp4)$")
RE_FILE = re.compile(r"^/api/items/(\d+)/file$")
RE_PROGRESS = re.compile(r"^/api/items/(\d+)/progress$")
RE_STOP = re.compile(r"^/api/items/(\d+)/stop$")

_item_cache = {}
_ic_lock = threading.Lock()


def item_brief(item_id):
    now = time.time()
    with _ic_lock:
        hit = _item_cache.get(item_id)
    if hit and now - hit[0] < 60:
        return hit[1]
    it = db.row("SELECT id, library_id, title, show, season, episode, episode_title, artist, media_type, kind, duration, "
                "poster, thumb, year FROM items WHERE id=?", (item_id,))
    with _ic_lock:
        if len(_item_cache) > 5000:
            _item_cache.clear()
        _item_cache[item_id] = (now, it)
    return it


def scrub(obj, allowed):
    """Drop dicts whose library_id isn't allowed from every list (recursively)."""
    if isinstance(obj, list):
        out = []
        for x in obj:
            if isinstance(x, dict) and "library_id" in x and x["library_id"] is not None:
                try:
                    if int(x["library_id"]) not in allowed:
                        continue
                except (TypeError, ValueError):
                    pass
            out.append(scrub(x, allowed))
        return out
    if isinstance(obj, dict):
        return {k: scrub(v, allowed) for k, v in obj.items()}
    return obj


def _cookie_token(headers):
    raw = headers.get(b"cookie")
    if not raw:
        return None
    try:
        c = SimpleCookie()
        c.load(raw.decode("latin-1"))
        m = c.get(auth.COOKIE)
        return m.value if m else None
    except Exception:
        return None


class Guard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        path = scope["path"]
        headers = {}
        for k, v in scope.get("headers") or []:
            headers[k] = v
        tok = _cookie_token(headers)
        if not tok:
            return await self.app(scope, receive, send)
        hdr = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in headers.items()}
        peer = (scope.get("client") or (None, None))[0]
        ip = netutil.client_ip_from(peer, hdr)
        ua = hdr.get("user-agent")
        try:
            u = auth.user_from_token(tok, ip, ua)
        except Exception:
            u = None
        if not u:
            return await self.app(scope, receive, send)
        qs = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
        method = scope.get("method", "GET")
        allowed = u.get("libs")

        # ---- direct access checks for restricted users
        item = None
        m = RE_ITEM.match(path)
        if m:
            item = item_brief(int(m.group(1)))
        if allowed is not None:
            deny = False
            m2 = RE_LIB.match(path)
            if m2 and int(m2.group(1)) not in allowed:
                deny = True
            for key in ("library_id", "lib"):
                for v in qs.get(key, []):
                    try:
                        if int(v) and int(v) not in allowed:
                            deny = True
                    except ValueError:
                        pass
            if item is not None and item["library_id"] not in allowed:
                deny = True
            if deny:
                body = b'{"detail":"Not found"}'
                await send({"type": "http.response.start", "status": 404,
                            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                        (b"cache-control", b"no-store")]})
                await send({"type": "http.response.body", "body": body})
                return

        # ---- now playing
        if item is not None:
            try:
                player = (qs.get("player") or [""])[0]
                device = auth._device_name(ua)
                mh = RE_HLS.match(path)
                if mh:
                    prof = mh.group(2)
                    mode = "remux" if prof == "remux" else ("music" if prof == "audio" else "transcode")
                    useractivity.touch(u, item, mode, prof, player, ip, device)
                elif RE_FILE.match(path) and not qs.get("download"):
                    useractivity.touch(u, item, "music" if item.get("media_type") == "audio" else "direct", None, player, ip, device)
                elif RE_PROGRESS.match(path) and method == "POST":
                    useractivity.touch(u, item, "progress", None, player, ip, device)
                elif RE_STOP.match(path) and method == "POST":
                    useractivity.end_player(u["id"], item["id"], player)
            except Exception:
                pass

        if allowed is None or method != "GET":
            return await self.app(scope, receive, send)
        if RE_HLS.match(path) or RE_FILE.match(path) or path.startswith("/api/thumb/") or path.endswith(".vtt") \
                or path.endswith("/poster-large") or path.endswith("/photo") or path.endswith(".csv"):
            return await self.app(scope, receive, send)

        # ---- buffer and scrub JSON for restricted users
        start = {}
        chunks = []

        async def _send(msg):
            if msg["type"] == "http.response.start":
                start.update(msg)
                return
            if msg["type"] == "http.response.body":
                chunks.append(msg.get("body", b""))
                if msg.get("more_body"):
                    return
                body = b"".join(chunks)
                hdrs = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
                ctype = dict((k.lower(), v) for k, v in start.get("headers", [])).get(b"content-type", b"")
                if b"json" in ctype and start.get("status") == 200:
                    try:
                        data = json.loads(body)
                        if path == "/api/libraries" and isinstance(data, list):
                            data = [l for l in data if isinstance(l, dict) and l.get("id") in allowed]
                        elif path == "/api/libraries/health" and isinstance(data, dict):
                            data = {k: v for k, v in data.items() if k.isdigit() and int(k) in allowed}
                        else:
                            data = scrub(data, allowed)
                        body = json.dumps(data, separators=(",", ":")).encode()
                    except Exception:
                        pass
                hdrs.append((b"content-length", str(len(body)).encode()))
                await send({"type": "http.response.start", "status": start.get("status", 200), "headers": hdrs})
                await send({"type": "http.response.body", "body": body})
                return
            await send(msg)

        return await self.app(scope, receive, _send)
