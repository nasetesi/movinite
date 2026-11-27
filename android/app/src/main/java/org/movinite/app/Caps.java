package org.movinite.app;

import android.content.Context;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.os.Build;
import android.util.DisplayMetrics;
import android.view.Display;
import android.view.WindowManager;

import androidx.media3.common.C;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.exoplayer.audio.AudioCapabilities;

import org.json.JSONObject;

/**
 * Real decoder, display and audio-passthrough capabilities, so the server can prefer
 * Direct Play of HEVC / HDR / surround instead of guessing from a WebView.
 */
@UnstableApi
final class Caps {
    private Caps() {}

    private static boolean decoder(String mime) {
        try {
            for (MediaCodecInfo i : new MediaCodecList(MediaCodecList.REGULAR_CODECS).getCodecInfos()) {
                if (i.isEncoder()) continue;
                for (String t : i.getSupportedTypes()) if (t.equalsIgnoreCase(mime)) return true;
            }
        } catch (Exception ignored) { }
        return false;
    }

    /** Highest height this mime can decode at 30 fps, else 0. */
    private static int maxHeight(String mime) {
        int best = 0;
        try {
            for (MediaCodecInfo i : new MediaCodecList(MediaCodecList.REGULAR_CODECS).getCodecInfos()) {
                if (i.isEncoder()) continue;
                try {
                    MediaCodecInfo.CodecCapabilities caps = i.getCapabilitiesForType(mime);
                    if (caps == null || caps.getVideoCapabilities() == null) continue;
                    MediaCodecInfo.VideoCapabilities v = caps.getVideoCapabilities();
                    for (int h : new int[]{2160, 1440, 1080, 720}) {
                        int w = h == 2160 ? 3840 : h == 1440 ? 2560 : h == 1080 ? 1920 : 1280;
                        if (h <= best) continue;
                        try {
                            if (v.areSizeAndRateSupported(w, h, 30)) best = Math.max(best, h);
                        } catch (Exception ignored) { }
                    }
                } catch (IllegalArgumentException ignored) { }
            }
        } catch (Exception ignored) { }
        return best;
    }

    private static boolean hevcMain10() {
        try {
            for (MediaCodecInfo i : new MediaCodecList(MediaCodecList.REGULAR_CODECS).getCodecInfos()) {
                if (i.isEncoder()) continue;
                try {
                    MediaCodecInfo.CodecCapabilities caps = i.getCapabilitiesForType("video/hevc");
                    if (caps == null || caps.profileLevels == null) continue;
                    for (MediaCodecInfo.CodecProfileLevel p : caps.profileLevels) {
                        if (p.profile == MediaCodecInfo.CodecProfileLevel.HEVCProfileMain10
                            || p.profile == MediaCodecInfo.CodecProfileLevel.HEVCProfileMain10HDR10
                            || (Build.VERSION.SDK_INT >= 29 && p.profile == MediaCodecInfo.CodecProfileLevel.HEVCProfileMain10HDR10Plus))
                            return true;
                    }
                } catch (IllegalArgumentException ignored) { }
            }
        } catch (Exception ignored) { }
        return false;
    }

    static JSONObject detect(Context c) {
        JSONObject o = new JSONObject();
        try {
            boolean hevc = decoder("video/hevc");
            o.put("h264", true);
            o.put("hevc", hevc);
            o.put("hevc10", hevc && hevcMain10());
            o.put("av1", decoder("video/av01"));
            o.put("vp9", decoder("video/x-vnd.on2.vp9"));
            o.put("aac", true);
            boolean ac3 = false, eac3 = false, dts = false, truehd = false;
            try {
                AudioCapabilities ac = AudioCapabilities.getCapabilities(c);
                ac3 = ac.supportsEncoding(C.ENCODING_AC3);
                eac3 = ac.supportsEncoding(C.ENCODING_E_AC3)
                    || (Build.VERSION.SDK_INT >= 29 && ac.supportsEncoding(C.ENCODING_E_AC3_JOC));
                dts = ac.supportsEncoding(C.ENCODING_DTS)
                    || ac.supportsEncoding(C.ENCODING_DTS_HD);
                truehd = ac.supportsEncoding(C.ENCODING_DOLBY_TRUEHD);
            } catch (Exception ignored) { }
            // Also count a software decoder as playable (decoded, not passthrough).
            if (decoder("audio/ac3")) ac3 = true;
            if (decoder("audio/eac3")) eac3 = true;
            if (decoder("audio/vnd.dts")) dts = true;
            if (decoder("audio/true-hd")) truehd = true;
            o.put("ac3", ac3);
            o.put("eac3", eac3);
            o.put("dts", dts);
            o.put("truehd", truehd);
            o.put("surr", (ac3 || eac3 || dts || truehd) ? 6 : 6); // ExoPlayer decodes 5.1 AAC too
            int maxh = 1080, maxw = 1920;
            boolean hdr = false, hdr10 = false, hlg = false, dv = false;
            try {
                WindowManager wm = (WindowManager) c.getSystemService(Context.WINDOW_SERVICE);
                Display d = wm.getDefaultDisplay();
                DisplayMetrics m = new DisplayMetrics();
                d.getRealMetrics(m);
                maxw = Math.max(m.widthPixels, m.heightPixels);
                maxh = Math.min(m.widthPixels, m.heightPixels);
                if (Build.VERSION.SDK_INT >= 23) {
                    Display.Mode mode = d.getMode();
                    if (mode != null) {
                        maxw = Math.max(mode.getPhysicalWidth(), mode.getPhysicalHeight());
                        maxh = Math.min(mode.getPhysicalWidth(), mode.getPhysicalHeight());
                    }
                    if (Build.VERSION.SDK_INT >= 23) {
                        Display.Mode[] modes = d.getSupportedModes();
                        if (modes != null) {
                            for (Display.Mode md : modes) {
                                int w = Math.max(md.getPhysicalWidth(), md.getPhysicalHeight());
                                int h = Math.min(md.getPhysicalWidth(), md.getPhysicalHeight());
                                if (w * h > maxw * maxh) { maxw = w; maxh = h; }
                            }
                        }
                    }
                }
                if (Build.VERSION.SDK_INT >= 24 && d.getHdrCapabilities() != null) {
                    int[] types = d.getHdrCapabilities().getSupportedHdrTypes();
                    if (types != null) {
                        for (int t : types) {
                            hdr = true;
                            if (t == Display.HdrCapabilities.HDR_TYPE_HDR10
                                || (Build.VERSION.SDK_INT >= 29 && t == Display.HdrCapabilities.HDR_TYPE_HDR10_PLUS))
                                hdr10 = true;
                            if (t == Display.HdrCapabilities.HDR_TYPE_HLG) hlg = true;
                            if (t == Display.HdrCapabilities.HDR_TYPE_DOLBY_VISION) dv = true;
                        }
                    }
                }
            } catch (Exception ignored) { }
            int decHevc = maxHeight("video/hevc");
            int decH264 = maxHeight("video/avc");
            // A 4K television's reported mode may already be 2160; keep the greater of display and decoder.
            if (maxh < 720) maxh = 1080;
            o.put("maxw", maxw);
            o.put("maxh", maxh >= 2000 ? 2160 : maxh >= 1400 ? 1440 : maxh >= 1000 ? 1080 : maxh);
            o.put("maxHevc", decHevc);
            o.put("maxH264", decH264);
            o.put("hdr", hdr);
            o.put("hdr10", hdr10);
            o.put("hlg", hlg);
            o.put("dv", dv);
            o.put("mkv", true);
            o.put("native", true);
        } catch (Exception ignored) { }
        return o;
    }

    /** Query string the item-detail and HLS endpoints understand (no leading ?). */
    static String asQuery(JSONObject o) {
        if (o == null) o = new JSONObject();
        StringBuilder sb = new StringBuilder("native=1");
        String[] flags = {"hevc", "hevc10", "av1", "vp9", "ac3", "eac3", "dts", "truehd",
            "hdr10", "hlg", "dv", "mkv", "hdr"};
        for (String k : flags) {
            if (o.optBoolean(k, false)) sb.append("&").append(k).append("=1");
        }
        if (o.optBoolean("ac3", false) || o.optBoolean("eac3", false)) sb.append("&acopy=1");
        int surr = o.optInt("surr", 0);
        if (surr >= 6 || o.optBoolean("ac3") || o.optBoolean("eac3") || o.optBoolean("dts") || o.optBoolean("truehd"))
            sb.append("&surr=6");
        int maxh = o.optInt("maxh", 0);
        if (maxh > 0) sb.append("&maxh=").append(maxh).append("&disp=").append(Math.max(maxh == 2160 ? 3840 : maxh * 16 / 9, maxh));
        int dec = Math.max(o.optInt("maxHevc", 0), o.optInt("maxH264", 0));
        if (dec >= 2160) sb.append("&dec=3840");
        else if (dec >= 1440) sb.append("&dec=2560");
        else if (dec >= 1080) sb.append("&dec=1920");
        return sb.toString();
    }
}
