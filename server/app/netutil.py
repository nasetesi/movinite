"""1.9: the real client address behind a reverse proxy.

Before 1.9 the server only saw the proxy's address (e.g. OpenResty at 192.0.2.10) for every request from
the internet, so all failed sign-ins shared one rate-limit bucket.  Forwarded headers are trusted only when
the request comes from an address listed in Settings > System > Trusted proxies (or MS_TRUSTED_PROXIES),
plus 127.0.0.1 / ::1.  CF-Connecting-IP (Cloudflare) wins, then X-Real-IP, then the right-most untrusted
address in X-Forwarded-For.
"""
import ipaddress
import os
import time

from . import settings

_cache = {"at": 0, "nets": []}
last_proxy_hint = {}     # {"ip": "...", "at": ts} a private peer that sent forwarded headers but is not trusted


def _parse(spec):
    nets = []
    for part in (spec or "").replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    return nets


def valid_spec(spec):
    bad = []
    for part in (spec or "").replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if part:
            try:
                ipaddress.ip_network(part, strict=False)
            except ValueError:
                bad.append(part)
    return bad


def trusted_nets():
    now = time.time()
    if now - _cache["at"] > 5:
        spec = ",".join(["127.0.0.1", "::1", os.environ.get("MS_TRUSTED_PROXIES", ""),
                         settings.get("trusted_proxies", "") or ""])
        _cache["nets"] = _parse(spec)
        _cache["at"] = now
    return _cache["nets"]


def invalidate():
    _cache["at"] = 0


def _is_trusted(ip, nets):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in n for n in nets)


def _clean(v):
    v = (v or "").strip().strip('"')
    if v.startswith("[") and "]" in v:
        v = v[1:v.index("]")]
    elif v.count(":") == 1 and "." in v:      # 1.2.3.4:5678
        v = v.split(":")[0]
    try:
        return str(ipaddress.ip_address(v))
    except ValueError:
        return None


def client_ip_from(peer, headers):
    """peer: the TCP peer address. headers: a mapping with lower-case keys."""
    nets = trusted_nets()
    if not peer or not _is_trusted(peer, nets):
        if peer and (headers.get("x-forwarded-for") or headers.get("cf-connecting-ip")):
            try:
                if ipaddress.ip_address(peer).is_private:
                    last_proxy_hint.update({"ip": peer, "at": time.time()})
            except ValueError:
                pass
        return peer or "?"
    for h in ("cf-connecting-ip", "x-real-ip"):
        v = _clean(headers.get(h))
        if v:
            return v
    xff = headers.get("x-forwarded-for") or ""
    hops = [_clean(x) for x in xff.split(",")]
    hops = [h for h in hops if h]
    for h in reversed(hops):
        if not _is_trusted(h, nets):
            return h
    return hops[0] if hops else peer


def client_ip(request):
    peer = request.client.host if request.client else None
    return client_ip_from(peer, {k.lower(): v for k, v in request.headers.items()})
