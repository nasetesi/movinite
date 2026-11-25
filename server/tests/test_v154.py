"""1.5.4: H.264 bitrate for HEVC / AV1 / VP9 sources, MPEG-TS start offset, dropped-frames readout."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MS_DATA_DIR", "/tmp/ms-test154")
from app import transcode as t  # noqa: E402

HEVC4K = {"vcodec": "hevc", "bitrate": 6671000}


class Bitrate(unittest.TestCase):
    def test_hevc_source_h264_4k_is_1_8x(self):
        self.assertEqual(t.video_kbps(HEVC4K, "2160p"), int(int(6671 * 1.8) * 1.25))   # avg 12.0 Mbps, maxrate 15.0

    def test_floors_and_ceilings(self):
        self.assertEqual(t.video_kbps({"vcodec": "av1", "bitrate": 3000000}, "2160p"), 15000)    # floor 12 Mbps avg
        self.assertEqual(t.video_kbps({"vcodec": "vp9", "bitrate": 3000000}, "1440p"), 10000)    # floor 8 Mbps avg
        self.assertEqual(t.video_kbps({"vcodec": "hevc", "bitrate": 40000000}, "2160p"), 25000)  # profile ceiling
        self.assertEqual(t.video_kbps(HEVC4K, "1440p"), 12000)

    def test_h264_source_and_hevc_output_unchanged(self):
        self.assertEqual(t.video_kbps({"vcodec": "h264", "bitrate": 6671000}, "2160p"), 8005)
        self.assertEqual(t.video_kbps(HEVC4K, "2160p", hevc_out=True), 8005)
        self.assertEqual(t.video_kbps({"vcodec": "h264", "bitrate": 0}, "2160p"), 25000)

    def test_cpu_fallback_and_small_profiles(self):
        self.assertEqual(t.video_kbps(HEVC4K, "2160p", cpu=True), 8000)
        self.assertEqual(t.video_kbps(HEVC4K, "1080p"), 8000)
        self.assertEqual(t.video_kbps(HEVC4K, "720p"), 4000)


def _session(item, profile, hw=("vaapi", "/dev/dri/renderD128"), stage="full"):
    s = t.Session.__new__(t.Session)
    s.item, s.profile, s.audio_idx, s.hw, s.rot = item, profile, 0, hw, 0
    s.base, s.vc = t.split_profile(profile); s.hevc = s.vc == "hevc"; s.ext = "m4s" if s.hevc else "ts"
    s.stages, s.stage_i = [stage], 0
    s.dir = t.config.TRANSCODE_DIR / "x"
    return s


ITEM = dict(HEVC4K, id=1, path="/m/f.mkv", width=3840, height=1610, duration=600, media_type="video")


class Command(unittest.TestCase):
    def test_gpu_4k_command(self):
        c = _session(ITEM, "2160p")._cmd(88)
        self.assertEqual(c[c.index("-maxrate") + 1], "15008k")
        self.assertEqual(c[c.index("-b:v") + 1], "12006k")
        self.assertIn("scale_vaapi=w=3840:h=1610:format=nv12", c)
        self.assertEqual(c[c.index("-muxdelay") + 1], "0")
        self.assertEqual(c[c.index("-muxpreload") + 1], "0")
        self.assertEqual(c[c.index("-output_ts_offset") + 1], "%.3f" % (88 * t.SEG))

    def test_cpu_fallback_keeps_rate_unscaled(self):
        c = _session(ITEM, "2160p", stage="cpu")._cmd(0)
        self.assertEqual(c[c.index("-maxrate") + 1], "8000k")     # 1.5.3 scaled this down to ~5.1 Mbps for scope films
        self.assertIn("scale=1920:804,format=yuv420p", c)

    def test_hevc_fmp4_has_no_muxdelay(self):
        c = _session(ITEM, "2160p.hevc")._cmd(0)
        self.assertNotIn("-muxdelay", c)


class Player(unittest.TestCase):
    def test_dropped_frames_in_pill(self):
        js = open(os.path.join(os.path.dirname(t.__file__), "static", "app.js")).read()
        self.assertIn("getVideoPlaybackQuality", js)
        self.assertIn("droppedVideoFrames", js)
        self.assertIn("function frameStat()", js)


if __name__ == "__main__":
    unittest.main()
