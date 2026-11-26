package org.movinite.app;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.webkit.CookieManager;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Talks to the Movinite server with the WebView's login cookie. The cookie is never logged.
 */
final class ServerApi {
    final String base;
    private final String cookie;

    ServerApi(Context c) {
        String b = Prefs.serverUrl(c);
        this.base = b == null ? "" : b;
        this.cookie = (b == null) ? null : CookieManager.getInstance().getCookie(b);
    }

    boolean signedIn() { return cookie != null && !cookie.isEmpty(); }

    HttpURLConnection open(String pathAndQuery) throws Exception {
        String url = pathAndQuery.startsWith("http") ? pathAndQuery : base + pathAndQuery;
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(15000);
        conn.setReadTimeout(30000);
        conn.setInstanceFollowRedirects(true);
        if (cookie != null) conn.setRequestProperty("Cookie", cookie);
        conn.setRequestProperty("Accept", "*/*");
        conn.setRequestProperty("User-Agent", "Movinite-Android/" + BuildConfigInfo.VERSION);
        return conn;
    }

    JSONObject getJson(String pathAndQuery) throws Exception {
        HttpURLConnection conn = open(pathAndQuery);
        try {
            int code = conn.getResponseCode();
            InputStream in = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
            String body = read(in);
            if (code >= 400) throw new ApiException(code, body);
            return new JSONObject(body.isEmpty() ? "{}" : body);
        } finally { conn.disconnect(); }
    }

    JSONObject postJson(String path, JSONObject body) throws Exception {
        HttpURLConnection conn = open(path);
        conn.setRequestMethod("POST");
        conn.setDoOutput(true);
        conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        byte[] raw = (body == null ? "{}" : body.toString()).getBytes(StandardCharsets.UTF_8);
        try (OutputStream os = conn.getOutputStream()) { os.write(raw); }
        try {
            int code = conn.getResponseCode();
            InputStream in = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
            String resp = read(in);
            if (code >= 400) throw new ApiException(code, resp);
            return new JSONObject(resp.isEmpty() ? "{\"ok\":true}" : resp);
        } finally { conn.disconnect(); }
    }

    Bitmap getBitmap(String pathAndQuery) throws Exception {
        HttpURLConnection conn = open(pathAndQuery);
        try (InputStream in = conn.getInputStream()) {
            return BitmapFactory.decodeStream(in);
        } finally { conn.disconnect(); }
    }

    /** Cookie header for ExoPlayer — same session as the WebView, not passed through JavaScript. */
    String cookieHeader() { return cookie; }

    private static String read(InputStream in) throws Exception {
        if (in == null) return "";
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
        return bo.toString("UTF-8");
    }

    static final class ApiException extends Exception {
        final int code;
        ApiException(int code, String body) {
            super(message(code, body));
            this.code = code;
        }
        private static String message(int code, String body) {
            if (code == 401 || code == 403) return "Your session has ended. Please sign in again.";
            try {
                JSONObject o = new JSONObject(body == null ? "{}" : body);
                if (o.has("detail")) return o.optString("detail");
            } catch (Exception ignored) { }
            return "The server answered HTTP " + code;
        }
    }
}
