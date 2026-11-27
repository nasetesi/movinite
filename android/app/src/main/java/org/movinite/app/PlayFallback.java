package org.movinite.app;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * 2.4.3: next playback mode after a native player source error.
 * Chain: direct → remux (if available) or transcode; remux → transcode;
 * an HEVC transcode → the same height as H.264; any other transcode → the
 * in-page web player ("web").
 */
final class PlayFallback {
    private PlayFallback() {}

    static final String WEB = "web";

    static String firstTranscode(JSONObject playback, JSONObject caps) {
        if (playback == null) return "1080p";
        JSONArray hi = playback.optJSONArray("hires");
        boolean hevc = caps != null && caps.optBoolean("hevc");
        if (hi != null && hi.length() > 0) {
            String h = hi.optString(0);
            return hevc ? h + ".hevc" : h;
        }
        JSONArray pr = playback.optJSONArray("profiles");
        if (pr != null && pr.length() > 0) return pr.optString(0);
        return "1080p";
    }

    /** Return the next mode to try, or {@link #WEB}, or null if {@code alreadyTried}. */
    static String nextMode(String mode, JSONObject playback, JSONObject caps, java.util.Set<String> alreadyTried) {
        String next;
        if ("direct".equals(mode)) {
            if (playback != null && playback.optBoolean("remux")) next = "remux";
            else next = firstTranscode(playback, caps);
        } else if ("remux".equals(mode)) {
            next = firstTranscode(playback, caps);
        } else if (mode != null && mode.endsWith(".hevc")) {
            next = mode.substring(0, mode.length() - 5);
            if (next.isEmpty()) next = "1080p";
        } else {
            next = WEB;
        }
        if (next == null || next.equals(mode)) return WEB;
        if (alreadyTried != null && alreadyTried.contains(next)) return WEB;
        return next;
    }

    static String errorDetail(String codeName, Integer httpStatus, String message, String cause) {
        StringBuilder b = new StringBuilder();
        if (codeName != null && !codeName.isEmpty() && !"ERROR_CODE_UNSPECIFIED".equals(codeName))
            b.append(codeName);
        if (httpStatus != null && httpStatus > 0) {
            if (b.length() > 0) b.append(" · ");
            b.append("HTTP ").append(httpStatus);
        }
        String extra = (message != null && !message.isEmpty() && !"Source error".equals(message))
            ? message : (cause != null && !cause.isEmpty() ? cause : null);
        if (extra != null) {
            if (b.length() > 0) b.append(" · ");
            b.append(extra);
        }
        if (b.length() == 0) {
            if (message != null && !message.isEmpty()) return message;
            return "unknown error";
        }
        return b.toString();
    }
}
