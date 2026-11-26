"""2.0.2: advertise this server on the LAN (mDNS / Zeroconf) so TVs and the Android app can list it.

Browsers cannot browse mDNS themselves, so the web UI also probes recently used addresses.
The advertisement is best-effort: if the 'zeroconf' package is missing, we just log and continue.
"""
from __future__ import annotations

import logging
import socket
import threading

import sys
from . import config
from .version import __version__

log = logging.getLogger("media-server.discover")

SERVICE_TYPE = "_movinite._tcp.local."

def listen_port() -> int:
    """Prefer the port uvicorn was started with (--port), then MS_PORT."""
    argv = sys.argv or []
    if "--port" in argv:
        i = argv.index("--port")
        if i + 1 < len(argv) and str(argv[i + 1]).isdigit():
            return int(argv[i + 1])
    return int(config.PORT or 8099)

_state = {"zc": None, "info": None}


def info_payload(request=None) -> dict:
    """Public JSON at /.well-known/movinite.json — used by the app and by JS probes."""
    name = "Movinite"
    try:
        from . import settings
        name = (settings.get("server_name") or "").strip() or name
    except Exception:
        pass
    port = listen_port()
    return {
        "ok": True,
        "service": "movinite",
        "name": name,
        "version": __version__,
        "port": port,
    }


def _addresses():
    out = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in out:
                out.append(ip)
    except Exception:
        pass
    if not out:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("192.0.2.1", 1))  # documentation net; no packets needed
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127."):
                out.append(ip)
        except Exception:
            pass
    return out


def start(stop_fn=None):
    """Register _movinite._tcp on the LAN. Safe to call once at startup."""
    try:
        from zeroconf import ServiceInfo, Zeroconf
    except ImportError:
        log.info("Python package 'zeroconf' is not installed: LAN server discovery is off until it is")
        return
    addrs = _addresses()
    if not addrs:
        log.info("No LAN address to advertise for Movinite discovery")
        return
    try:
        host = (socket.gethostname() or "movinite").split(".")[0] or "movinite"
        inst = "Movinite (%s)" % host
        name = "%s.%s" % (inst, SERVICE_TYPE)
        packed = [socket.inet_aton(a) for a in addrs]
        info = ServiceInfo(
            SERVICE_TYPE,
            name,
            addresses=packed,
            port=int(listen_port()),
            properties={
                "path": "/",
                "version": __version__,
                "https": "0",
            },
            server=host + ".local.",
        )
        zc = Zeroconf()
        zc.register_service(info)
        _state["zc"] = zc
        _state["info"] = info
        log.info("Advertising Movinite on the LAN as %s at %s:%s", inst, ", ".join(addrs), listen_port())
    except Exception:
        log.exception("LAN discovery advertisement failed")
        return
    if stop_fn:
        def _watch():
            try:
                while not stop_fn():
                    threading.Event().wait(2)
            finally:
                stop()
        threading.Thread(target=_watch, daemon=True, name="mdns-watch").start()


def stop():
    zc, info = _state.get("zc"), _state.get("info")
    _state["zc"] = _state["info"] = None
    if not zc:
        return
    try:
        if info:
            zc.unregister_service(info)
    except Exception:
        pass
    try:
        zc.close()
    except Exception:
        pass
