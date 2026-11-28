package org.movinite.app;

/**
 * Labels and TV-only route policy for the simplified Android TV Settings screen (2.4.6).
 * Pure Java so unit tests can run on the JVM.
 */
final class TvSettings {
    private TvSettings() {}

    /** Host (and non-default port) of a server URL, or "" if it can't be parsed. */
    static String hostOf(String serverUrl) {
        if (serverUrl == null || serverUrl.isEmpty()) return "";
        try {
            java.net.URI u = new java.net.URI(serverUrl.trim());
            String h = u.getHost();
            if (h == null || h.isEmpty()) return "";
            int p = u.getPort();
            if (p > 0 && p != 80 && p != 443) return h + ":" + p;
            return h;
        } catch (Exception e) {
            return "";
        }
    }

    /** Prefer a display name, then username. Show both when they differ. */
    static String userLabel(String name, String username) {
        String n = name == null ? "" : name.trim();
        String u = username == null ? "" : username.trim();
        if (!n.isEmpty() && !u.isEmpty() && !n.equalsIgnoreCase(u)) return n + " (" + u + ")";
        if (!u.isEmpty()) return u;
        if (!n.isEmpty()) return n;
        return "Signed in";
    }

    /** "Movinite  ·  media.example.com" — name defaults to Movinite. */
    static String serverLabel(String serverName, String host) {
        String n = serverName == null ? "" : serverName.trim();
        if (n.isEmpty()) n = "Movinite";
        String h = host == null ? "" : host.trim();
        if (h.isEmpty()) return n;
        if (n.equalsIgnoreCase(h)) return n;
        return n + "  ·  " + h;
    }

    static String versionLabel(String versionName, int versionCode) {
        String v = (versionName == null || versionName.isEmpty()) ? "?" : versionName;
        return v + "  (build " + versionCode + ")";
    }

    /**
     * TV-only: admin and extra chrome routes that should not be shown.
     * Home, Search, library/item pages, and invite/pair sign-in links stay.
     */
    static boolean hideTvHash(String hash) {
        String h = hash == null ? "" : hash.trim();
        int k = h.indexOf('#');
        if (k >= 0) h = h.substring(k + 1);
        if (h.startsWith("/")) h = h.substring(1);
        if (h.isEmpty()) return false;
        String top = h.split("/", 2)[0].toLowerCase();
        switch (top) {
            case "settings":
            case "downloads":
            case "activity":
            case "mylist":
            case "status":
            case "invites":
                return true;
            default:
                return false;
        }
    }
}
