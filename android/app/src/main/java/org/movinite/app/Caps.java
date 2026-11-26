package org.movinite.app;

import android.content.Context;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.os.Build;
import android.util.DisplayMetrics;
import android.view.Display;
import android.view.WindowManager;

import org.json.JSONObject;

/** What this phone can play itself, so the server only offers "Original" when it will actually work. */
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

    static JSONObject detect(Context c) {
        JSONObject o = new JSONObject();
        try {
            o.put("h264", true);
            o.put("hevc", decoder("video/hevc"));
            o.put("av1", decoder("video/av01"));
            o.put("vp9", decoder("video/x-vnd.on2.vp9"));
            o.put("ac3", decoder("audio/ac3"));
            o.put("eac3", decoder("audio/eac3"));
            o.put("dts", decoder("audio/vnd.dts"));
            o.put("truehd", decoder("audio/true-hd"));
            int maxh = 1080;
            boolean hdr = false;
            try {
                WindowManager wm = (WindowManager) c.getSystemService(Context.WINDOW_SERVICE);
                Display d = wm.getDefaultDisplay();
                DisplayMetrics m = new DisplayMetrics();
                d.getRealMetrics(m);
                int shortSide = Math.min(m.widthPixels, m.heightPixels);
                maxh = shortSide >= 2000 ? 2160 : shortSide >= 1400 ? 1440 : 1080;   // phones play 1080p fine even on 720p screens
                if (Build.VERSION.SDK_INT >= 24 && d.getHdrCapabilities() != null) hdr = d.getHdrCapabilities().getSupportedHdrTypes().length > 0;
            } catch (Exception ignored) { }
            o.put("maxh", maxh);
            o.put("hdr", hdr);
        } catch (Exception ignored) { }
        return o;
    }
}
