package org.movinite.app;

import android.webkit.CookieManager;

/** The web app's login cookie (ms_session), shared between the native sign-in screen and the WebView. No password is ever stored. */
final class Session {
    static final String COOKIE = "ms_session";

    private Session() {}

    static boolean signedIn(String server) {
        if (server == null) return false;
        String c = CookieManager.getInstance().getCookie(server);
        if (c == null) return false;
        for (String part : c.split(";")) {
            String p = part.trim();
            if (p.startsWith(COOKIE + "=") && p.length() > COOKIE.length() + 1) return true;
        }
        return false;
    }

    /** forget the session for this server (expired, signed out, or server changed) */
    static void clear(String server) {
        if (server == null) return;
        CookieManager cm = CookieManager.getInstance();
        cm.setCookie(server, COOKIE + "=; Max-Age=0; Path=/");
        cm.setCookie(server, COOKIE + "=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/");
        cm.flush();
    }
}
