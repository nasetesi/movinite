package org.movinite.app;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.os.Build;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;

import org.json.JSONObject;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * The window.MSAndroid methods for downloads (2.0), shared by the online app (MainActivity) and the offline screen.
 * call(id, name, args) runs off the main thread and answers through window.__msResolve(id, ok, json);
 * window.__msDownloadsChanged() is fired whenever the list changes.
 */
public class OfflineBridge {
    final Activity act;
    final Offline off;
    private WebView web;
    private final boolean offlinePage;
    private static final ExecutorService POOL = Executors.newFixedThreadPool(2);
    private final Runnable listener = () -> js("window.__msDownloadsChanged&&window.__msDownloadsChanged()");

    OfflineBridge(Activity a, boolean offlinePage) {
        act = a;
        off = Offline.get(a);
        this.offlinePage = offlinePage;
    }

    void attach(WebView w) { web = w; off.addListener(listener); }
    void detach() { off.removeListener(listener); web = null; }

    void js(String code) {
        WebView w = web;
        if (w == null) return;
        act.runOnUiThread(() -> { if (web != null) web.evaluateJavascript(code, null); });
    }

    private void resolve(int id, boolean ok, Object data) {
        String json = data == null ? "null" : data.toString();
        js("window.__msResolve&&window.__msResolve(" + id + "," + ok + "," + JSONObject.quote(json) + ")");
    }

    private static JSONObject err(Exception e) {
        JSONObject o = new JSONObject();
        try {
            o.put("detail", e.getMessage() == null ? "Something went wrong" : e.getMessage());
            if (e instanceof Offline.ApiException) { o.put("error", ((Offline.ApiException) e).error); o.put("code", ((Offline.ApiException) e).code); }
        } catch (Exception ignored) { }
        return o;
    }

    @JavascriptInterface public String offlineCaps() { return off.capsJson().toString(); }
    @JavascriptInterface public String downloads() { return off.downloadsJson(offlinePage).toString(); }
    @JavascriptInterface public String storageInfo() { return off.storageJson().toString(); }
    @JavascriptInterface public boolean isOfflinePage() { return offlinePage; }

    @JavascriptInterface
    public void playOffline(long gid) { act.runOnUiThread(() -> OfflinePlayerActivity.start(act, gid, !offlinePage)); }

    /** a poster for the offline page, as a data: URL (the file is encrypted like the film) */
    @JavascriptInterface
    public String posterData(long gid) {
        try {
            java.io.File f = off.partFile(gid, "poster");
            if (!f.exists()) return "";
            try (ChunkStore.Reader r = new ChunkStore.Reader(f, off.aead(), gid, "poster")) { return "data:image/jpeg;base64," + Lic.b64(r.readAll()); }
        } catch (Exception e) { return ""; }
    }

    @JavascriptInterface
    public void call(int id, String name, String argsJson) {
        JSONObject a;
        try { a = new JSONObject(argsJson == null || argsJson.isEmpty() ? "{}" : argsJson); } catch (Exception e) { a = new JSONObject(); }
        final JSONObject args = a;
        switch (name) {     // the ones that need the screen
            case "setupPin": act.runOnUiThread(() -> Unlock.setupPinDialog(act, (ok, why) -> resolve(id, ok, ok ? "{}" : jsonErr(why)))); return;
            case "clearPin": act.runOnUiThread(() -> { Unlock.clearPin(act); resolve(id, true, "{}"); off.changed(); }); return;
            case "download":
                if (!Unlock.deviceSecure(act) && !Unlock.pinSet(act)) {   // no screen lock: protect offline sign-in with a PIN first
                    act.runOnUiThread(() -> Unlock.setupPinDialog(act, (ok, why) -> { if (ok) POOL.execute(() -> run(id, name, args)); else resolve(id, false, jsonErr("A PIN is needed to keep downloads on a phone without a screen lock.")); }));
                    return;
                }
                askNotifications();
                break;
            default: break;
        }
        POOL.execute(() -> run(id, name, args));
    }

    private static String jsonErr(String why) { return "{\"detail\":" + JSONObject.quote(why == null ? "cancelled" : why) + "}"; }

    private void run(int id, String name, JSONObject a) {
        try {
            Object out;
            switch (name) {
                case "options": out = off.options(a.getLong("item_id")); break;
                case "download": out = off.download(a.getLong("item_id"), a.optString("profile", ""), a.optInt("audio", 0), a.optString("title", "")); break;
                case "remove": off.remove(a.getLong("grant_id")); out = new JSONObject().put("ok", true); break;
                case "pause": off.pause(a.getLong("grant_id")); out = new JSONObject().put("ok", true); break;
                case "resume": case "retry":
                    if ("retry".equals(name)) { long g = a.getLong("grant_id"); Offline.rmrf(off.partFile(g, "video")); Offline.rmrf(new java.io.File(off.dirFor(g), "video.mvc.part")); }
                    off.resume(a.getLong("grant_id")); out = new JSONObject().put("ok", true); break;
                case "sync": out = off.sync(); break;
                case "setting": off.setSetting(a.getString("key"), a.opt("value")); out = new JSONObject().put("ok", true); break;
                case "deleteAll": off.deleteAll(); out = new JSONObject().put("ok", true); break;
                case "caps": out = off.capsJson(); break;
                default: throw new IllegalArgumentException("Unknown request " + name);
            }
            resolve(id, true, out);
        } catch (Exception e) {
            resolve(id, false, err(e));
        }
    }

    private void askNotifications() {
        if (Build.VERSION.SDK_INT >= 33 && act.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            act.runOnUiThread(() -> act.requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 9));
    }
}
