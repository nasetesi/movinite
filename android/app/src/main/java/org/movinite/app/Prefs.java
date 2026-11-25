package org.movinite.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;

/** The server address, kept in the app's private preferences. */
final class Prefs {
    private static final String FILE = "media_server";
    private static final String KEY_URL = "server_url";

    private Prefs() {}

    static SharedPreferences sp(Context c) { return c.getSharedPreferences(FILE, Context.MODE_PRIVATE); }

    /** the saved server address, or null before the first-run setup screen has saved one */
    static String serverUrl(Context c) { return sp(c).getString(KEY_URL, null); }

    static boolean hasServer(Context c) { return serverUrl(c) != null; }

    static void setServerUrl(Context c, String url) { sp(c).edit().putString(KEY_URL, url).apply(); }

    /** "movies.example.com/" -> "https://movies.example.com"; keeps an explicit http:// (LAN); drops a trailing slash. */
    static String normalize(String in) {
        if (in == null) return null;
        String s = in.trim();
        if (s.isEmpty()) return null;
        if (!s.matches("(?i)^https?://.*")) s = "https://" + s;
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        Uri u = Uri.parse(s);
        if (u.getHost() == null || u.getHost().isEmpty()) return null;
        String scheme = u.getScheme().toLowerCase();
        return scheme + "://" + u.getHost().toLowerCase() + (u.getPort() > 0 ? ":" + u.getPort() : "") + (u.getPath() == null ? "" : u.getPath());
    }

    /** same scheme, host and port as the server the user entered */
    static boolean sameOrigin(String serverUrl, Uri u) {
        if (serverUrl == null || u == null || u.getHost() == null) return false;
        Uri s = Uri.parse(serverUrl);
        return u.getHost().equalsIgnoreCase(s.getHost()) && port(u) == port(s);
    }

    static int port(Uri u) {
        if (u.getPort() > 0) return u.getPort();
        return "http".equalsIgnoreCase(u.getScheme()) ? 80 : 443;
    }
}
