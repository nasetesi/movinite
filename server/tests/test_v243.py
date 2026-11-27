"""2.4.3: HEVC fMP4 (.m4s) segment route no longer crashes; acopy is accepted."""
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL: " + msg)
    print("  ok", msg)


def test_version():
    from app.version import __version__
    check(__version__ == "2.4.3", "version is 2.4.3, got " + __version__)


def test_hls_segment_accepts_acopy():
    from app import server
    check(hasattr(server, "_hls_segment_response"), "shared segment helper exists")
    sig = inspect.signature(server._hls_segment_response)
    check("acopy" in sig.parameters, "helper takes acopy")
    check(sig.parameters["acopy"].default == 0, "acopy defaults to 0")
    for name in ("hls_segment", "hls_segment_m4s"):
        fn = getattr(server, name)
        ps = inspect.signature(fn).parameters
        check("acopy" in ps, name + " takes acopy")
        keys = list(ps)
        check(keys.index("acopy") < keys.index("u"), name + " has acopy before u")


def test_m4s_does_not_call_ts_handler_positionally():
    """The 2.4.2 bug: hls_segment_m4s called hls_segment(..., acopy) with 12
    positional args, but hls_segment only accepted 11, so every native HEVC
    segment request raised TypeError."""
    from app import server
    src = inspect.getsource(server.hls_segment_m4s)
    check("hls_segment(" not in src.replace("hls_segment_m4s", ""),
          "m4s route does not call hls_segment() directly")
    check("_hls_segment_response(" in src, "m4s route uses the shared helper")
    ts = inspect.getsource(server.hls_segment)
    check("acopy" in inspect.signature(server.hls_segment).parameters,
          ".ts route accepts acopy")
    check("_hls_segment_response(" in ts, ".ts route uses the shared helper")


def test_web_fallback_hooks():
    js = (ROOT / "app" / "static" / "app.js").read_text()
    check("function playInWebPlayer(" in js, "playInWebPlayer hook exists")
    check("forceWeb" in js, "playItem honors forceWeb")
    check("!opts.forceWeb && nativePlaySupported()" in js,
          "native handoff is skipped when forceWeb is set")


if __name__ == "__main__":
    print("2.4.3 HLS m4s / acopy")
    test_version()
    test_hls_segment_accepts_acopy()
    test_m4s_does_not_call_ts_handler_positionally()
    test_web_fallback_hooks()
    print("all ok")
