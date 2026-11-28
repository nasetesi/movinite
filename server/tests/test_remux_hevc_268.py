"""2.6.8: an HEVC remux must be advertised as fMP4, not MPEG-TS.

Run: .venv/bin/python -m pytest tests  (or python3 tests/test_remux_hevc_268.py)
"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("MS_DATA_DIR", "/tmp/ms-test-data")
from app import transcode, config  # noqa: E402

SEG = transcode.SEG
ITEM = {"id": 1, "duration": 30.0, "media_type": "video", "container": "matroska,webm",
        "vcodec": "hevc", "width": 3840, "height": 2160, "mtime": 1,
        "audio_streams": '[{"index": 0, "codec": "eac3", "channels": 6}]'}
# Real keyframe plans are SPARSER than ceil(duration / SEG): probe_bounds() only keeps
# a split point when it is >= 3.0 s past the last one, while SEG is 2.0 s. So a 30 s
# title has 15 muxer segments but only ~10 probed bounds -- which is exactly why the
# HEVC remux (cut by the hls muxer at -hls_time SEG) must not take its nseg from them.
BOUNDS = [0.0, 3.2, 6.4, 9.5, 12.7, 16.0, 19.2, 22.4, 25.6, 28.8]


def test_fmp4_playlist_has_map_and_m4s():
    """The generic branch -- what an HEVC remux must now use."""
    pl = transcode.playlist(ITEM, "?session=x", None, "init.mp4?session=x")
    assert '#EXT-X-MAP:URI="init.mp4?session=x"' in pl, pl
    assert "#EXT-X-VERSION:7" in pl
    assert "seg0.m4s?session=x" in pl
    assert ".ts" not in pl


def test_bounded_playlist_is_ts_only():
    """Regression guard: the bounded branch cannot serve fMP4 -- it ignores fmp4_init.

    This is the 2.6.7 bug. hls_playlist() must therefore pass bounds=None whenever the
    stream needs an init segment, which is what the fix does; this test pins down WHY.
    """
    pl = transcode.playlist(ITEM, "?session=x", BOUNDS, "init.mp4?session=x")
    assert "#EXT-X-MAP" not in pl
    assert "seg0.ts?session=x" in pl
    assert ".m4s" not in pl


def test_hevc_remux_nseg_is_duration_based():
    """An HEVC remux is cut by the hls muxer at -hls_time SEG, not at `bounds`."""
    with tempfile.TemporaryDirectory() as td:
        config.TRANSCODE_DIR = Path(td)
        s = transcode.Session("sid1", ITEM, "remux", 0, BOUNDS)
        assert s.hevc is True
        assert s.ext == "m4s"
        expected = max(1, int(-(-ITEM["duration"] // SEG)))
        assert s.nseg == expected, (s.nseg, expected, len(BOUNDS))


def test_h264_remux_still_uses_bounds():
    """The H.264 path is genuinely segment-cut at the probed keyframes -- unchanged."""
    with tempfile.TemporaryDirectory() as td:
        config.TRANSCODE_DIR = Path(td)
        it = dict(ITEM, vcodec="h264", pix_fmt="yuv420p")
        s = transcode.Session("sid2", it, "remux", 0, BOUNDS)
        assert s.hevc is False
        assert s.ext == "ts"
        assert s.nseg == len(BOUNDS)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("  ok", name)
    print("all remux/HEVC tests pass")
