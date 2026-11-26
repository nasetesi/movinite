package org.movinite.app;

import android.content.ContentValues;
import android.content.Context;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.StatFs;
import android.webkit.CookieManager;

import androidx.work.Constraints;
import androidx.work.Data;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;

import com.google.crypto.tink.Aead;
import com.google.crypto.tink.KeyTemplates;
import com.google.crypto.tink.KeysetHandle;
import com.google.crypto.tink.aead.AeadConfig;
import com.google.crypto.tink.integration.android.AndroidKeysetManager;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CopyOnWriteArraySet;
import java.util.concurrent.TimeUnit;

/**
 * 2.0 offline downloads: the device registration, the catalog of downloads (SQLite), the encrypted store, server calls
 * signed with the device key, sync (licence renewal, revocations, offline progress) and the wipe.
 * Protection is trust-based: files are AES-GCM encrypted with a key held by the Android Keystore and only the app's player
 * opens them, but a rooted phone can still get at them. The in-app help says so.
 */
final class Offline {
    static final String PREFS = "movinite_offline";
    static final String TAG_DL = "movinite-dl";
    static final String WORK_SYNC = "movinite-sync";
    private static Offline inst;

    final Context app;
    final SharedPreferences sp;
    final Db db;
    private Aead aead;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final CopyOnWriteArraySet<Runnable> listeners = new CopyOnWriteArraySet<>();
    private long lastNotify = 0;
    private boolean notifyQueued = false;
    /** offline sign-in done in this process (the unlock screen); online use doesn't need it */
    static volatile boolean unlocked = false;

    static synchronized Offline get(Context c) {
        if (inst == null) inst = new Offline(c.getApplicationContext());
        return inst;
    }

    private Offline(Context c) {
        app = c;
        sp = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        db = new Db(c);
    }

    // ------------------------------------------------------------------ profile + settings
    boolean registered() { return sp.getLong("device_id", 0) > 0 && DeviceKey.exists(); }
    long deviceId() { return sp.getLong("device_id", 0); }
    String fp() { return sp.getString("fp", null); }
    String serverId() { return sp.getString("server_id", null); }
    byte[] serverPub() { String s = sp.getString("server_pub", null); return s == null ? null : Lic.b64uDec(s); }
    String server() { String s = sp.getString("server", null); return s != null ? s : Prefs.serverUrl(app); }
    String username() { return sp.getString("username", ""); }
    int wipeDays() { return sp.getInt("wipe_days", 30); }
    int offlineDays() { return sp.getInt("offline_days", 30); }
    long lastSync() { return sp.getLong("last_sync", 0); }
    boolean wifiOnly() { return sp.getBoolean("wifi_only", true); }
    String quality() { return sp.getString("quality", "ask"); }
    String storagePref() { return sp.getString("storage", "internal"); }
    boolean hasDownloads() { return db.count() > 0; }

    long now() { return System.currentTimeMillis() / 1000; }

    /** see Lic.trustedNow: -1 when the clock went back more than an hour */
    long trustedNow() {
        long n = now(), hw = sp.getLong("high_water", 0);
        long t = Lic.trustedNow(n, hw, 3600);
        if (t > 0 && n > hw + 60) sp.edit().putLong("high_water", n).apply();
        return t;
    }

    private void sawServerTime(long st) {
        if (st <= 0) return;
        long hw = sp.getLong("high_water", 0);
        sp.edit().putLong("clock_offset", st - now()).putLong("high_water", Math.max(hw, st)).apply();
    }

    /** the offline window is over (no sync for wipe_days): remove everything */
    boolean windowExpired() {
        long ls = lastSync(), t = trustedNow();
        return registered() && ls > 0 && t > 0 && t - ls > wipeDays() * 86400L;
    }

    // ------------------------------------------------------------------ crypto
    synchronized Aead aead() throws Exception {
        if (aead == null) {
            AeadConfig.register();
            KeysetHandle h = new AndroidKeysetManager.Builder()
                .withSharedPref(app, "movinite_keyset", "movinite_keyset_prefs")
                .withKeyTemplate(KeyTemplates.get("AES256_GCM"))
                .withMasterKeyUri("android-keystore://movinite_master_v1")
                .build().getKeysetHandle();
            aead = h.getPrimitive(Aead.class);
        }
        return aead;
    }

    // ------------------------------------------------------------------ files
    File externalDir() {
        File[] d = app.getExternalFilesDirs(null);
        if (d != null && d.length > 1 && d[1] != null) return new File(d[1], "offline");
        return null;
    }

    File baseDir() {
        File ext = "external".equals(storagePref()) ? externalDir() : null;
        File d = ext != null ? ext : new File(app.getNoBackupFilesDir(), "offline");
        //noinspection ResultOfMethodCallIgnored
        d.mkdirs();
        return d;
    }

    File dirFor(long gid) {
        String p = db.str(gid, "dir");
        File d = p != null ? new File(p) : new File(baseDir(), String.valueOf(gid));
        //noinspection ResultOfMethodCallIgnored
        d.mkdirs();
        return d;
    }

    File partFile(long gid, String part) { return new File(dirFor(gid), part + ".mvc"); }

    static void rmrf(File f) {
        if (f == null || !f.exists()) return;
        File[] k = f.listFiles();
        if (k != null) for (File x : k) rmrf(x);
        //noinspection ResultOfMethodCallIgnored
        f.delete();
    }

    static long du(File f) {
        if (f == null || !f.exists()) return 0;
        if (f.isFile()) return f.length();
        long n = 0;
        File[] k = f.listFiles();
        if (k != null) for (File x : k) n += du(x);
        return n;
    }

    // ------------------------------------------------------------------ change notifications (the web page redraws)
    void addListener(Runnable r) { listeners.add(r); }
    void removeListener(Runnable r) { listeners.remove(r); }

    void changed() {
        synchronized (this) {
            if (notifyQueued) return;
            notifyQueued = true;
        }
        long wait = Math.max(0, 700 - (System.currentTimeMillis() - lastNotify));
        ui.postDelayed(() -> {
            synchronized (this) { notifyQueued = false; }
            lastNotify = System.currentTimeMillis();
            for (Runnable r : listeners) try { r.run(); } catch (Exception ignored) { }
        }, wait);
    }

    // ------------------------------------------------------------------ network
    boolean online() {
        try {
            ConnectivityManager cm = (ConnectivityManager) app.getSystemService(Context.CONNECTIVITY_SERVICE);
            Network n = cm.getActiveNetwork();
            NetworkCapabilities c = n == null ? null : cm.getNetworkCapabilities(n);
            return c != null && c.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
        } catch (Exception e) { return true; }
    }

    boolean unmetered() {
        try {
            ConnectivityManager cm = (ConnectivityManager) app.getSystemService(Context.CONNECTIVITY_SERVICE);
            Network n = cm.getActiveNetwork();
            NetworkCapabilities c = n == null ? null : cm.getNetworkCapabilities(n);
            return c != null && c.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED);
        } catch (Exception e) { return false; }
    }

    static final class ApiException extends Exception {
        final int code;
        final String error;
        final JSONObject body;
        ApiException(int code, String msg, String error, JSONObject body) { super(msg); this.code = code; this.error = error; this.body = body; }
    }

    static final class Resp {
        final int code;
        final byte[] body;
        Resp(int code, byte[] body) { this.code = code; this.body = body; }
        JSONObject json() throws JSONException { return new JSONObject(new String(body, StandardCharsets.UTF_8)); }
        JSONArray arr() throws JSONException { return new JSONArray(new String(body, StandardCharsets.UTF_8)); }
    }

    private static final SecureRandom RNG = new SecureRandom();

    static String nonce() { byte[] b = new byte[18]; RNG.nextBytes(b); return Lic.b64u(b); }

    /** adds the X-Movinite-* signature headers (device "new" = registration with the key in the body) */
    void sign(HttpURLConnection c, String method, String pathQ, byte[] body, String deviceHeader) throws Exception {
        long ts = now() + sp.getLong("clock_offset", 0);
        String n = nonce();
        byte[] sig = DeviceKey.sign(Lic.canonical(method, pathQ, ts, n, body).getBytes(StandardCharsets.UTF_8));
        c.setRequestProperty("X-Movinite-Device", deviceHeader);
        c.setRequestProperty("X-Movinite-Time", String.valueOf(ts));
        c.setRequestProperty("X-Movinite-Nonce", n);
        c.setRequestProperty("X-Movinite-Sig", Lic.b64(sig));
    }

    HttpURLConnection open(String method, String pathQ, byte[] body, boolean signed, boolean cookie, String deviceHeader) throws Exception {
        String base = server();
        HttpURLConnection c = (HttpURLConnection) new URL(base + pathQ).openConnection();
        c.setRequestMethod(method);
        c.setConnectTimeout(15000);
        c.setReadTimeout(60000);
        c.setInstanceFollowRedirects(false);
        c.setRequestProperty("User-Agent", "MediaServerAndroid/" + BuildConfigInfo.VERSION);
        c.setRequestProperty("Accept", "application/json");
        if (cookie) { String ck = CookieManager.getInstance().getCookie(base); if (ck != null) c.setRequestProperty("Cookie", ck); }
        if (signed) sign(c, method, pathQ, body == null ? new byte[0] : body, deviceHeader != null ? deviceHeader : String.valueOf(deviceId()));
        if (body != null && !"GET".equals(method) && !"DELETE".equals(method)) {
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            c.setFixedLengthStreamingMode(body.length);
            try (OutputStream o = c.getOutputStream()) { o.write(body); }
        }
        return c;
    }

    static byte[] readAll(InputStream in) throws IOException {
        if (in == null) return new byte[0];
        try (InputStream i = in) {
            ByteArrayOutputStream o = new ByteArrayOutputStream();
            byte[] b = new byte[16384];
            int n;
            while ((n = i.read(b)) > 0) o.write(b, 0, n);
            return o.toByteArray();
        }
    }

    /** a JSON call; throws ApiException with the server's message on an error */
    Resp call(String method, String pathQ, JSONObject body, boolean signed, boolean cookie) throws Exception {
        return call(method, pathQ, body, signed, cookie, null, true);
    }

    private Resp call(String method, String pathQ, JSONObject body, boolean signed, boolean cookie, String devHeader, boolean retryClock) throws Exception {
        byte[] b = body == null ? null : body.toString().getBytes(StandardCharsets.UTF_8);
        HttpURLConnection c = open(method, pathQ, b, signed, cookie, devHeader);
        try {
            int code = c.getResponseCode();
            byte[] out = readAll(code >= 400 ? c.getErrorStream() : c.getInputStream());
            if (code < 400) return new Resp(code, out);
            JSONObject j = null;
            try { j = new JSONObject(new String(out, StandardCharsets.UTF_8)); } catch (Exception ignored) { }
            Object det = j == null ? null : j.opt("detail");
            String msg = null, err = null;
            if (det instanceof JSONObject) {
                JSONObject d = (JSONObject) det;
                err = d.optString("error", null);
                msg = d.optString("detail", null);
                if ("device_signature".equals(err)) {
                    String reason = d.optString("reason");
                    if ("clock".equals(reason) && retryClock && d.optLong("server_time") > 0) {
                        sp.edit().putLong("clock_offset", d.optLong("server_time") - now()).apply();
                        return call(method, pathQ, body, signed, cookie, devHeader, false);
                    }
                    msg = "unknown_device".equals(reason) ? "This phone isn't set up for downloads any more." : "The server didn't accept this phone's signature (" + reason + ").";
                }
            } else if (det instanceof String) msg = (String) det;
            if (msg == null) msg = code == 401 ? "Sign in again to download." : "The server answered HTTP " + code;
            throw new ApiException(code, msg, err, j);
        } finally { c.disconnect(); }
    }

    // ------------------------------------------------------------------ registration
    /** first download on this phone: make the Keystore key and register it (needs the signed-in session) */
    synchronized void ensureDevice() throws Exception {
        if (registered() && Prefs.serverUrl(app).equals(server())) return;
        if (registered()) wipe("server changed");
        DeviceKey.create();
        byte[] der = DeviceKey.publicDer();
        JSONObject b = new JSONObject()
            .put("pubkey", Lic.b64(der))
            .put("name", (Build.MANUFACTURER == null ? "" : cap(Build.MANUFACTURER) + " ") + (Build.MODEL == null ? "Android" : Build.MODEL))
            .put("platform", "android")
            .put("app_version", BuildConfigInfo.VERSION)
            .put("caps", Caps.detect(app));
        sp.edit().putString("server", Prefs.serverUrl(app)).apply();
        JSONObject r;
        try { r = call("POST", "/api/devices", b, true, true, "new", true).json(); }
        catch (Exception e) { DeviceKey.delete(); sp.edit().remove("server").apply(); throw e; }
        String fp = Lic.deviceFp(der);
        if (!fp.equals(r.optString("fp"))) { DeviceKey.delete(); throw new SecurityException("The server answered with another key"); }
        JSONObject u = r.optJSONObject("user");
        sp.edit()
            .putLong("device_id", r.getLong("device_id"))
            .putString("fp", fp)
            .putString("server_pub", r.getString("server_pubkey"))
            .putString("server_id", r.getString("server_id"))
            .putString("server_fpr", r.optString("server_fingerprint"))
            .putInt("offline_days", r.optInt("offline_days", 30))
            .putInt("wipe_days", r.optInt("wipe_days", 30))
            .putString("username", u == null ? "" : u.optString("username"))
            .putLong("last_sync", r.optLong("server_time", now()))
            .apply();
        sawServerTime(r.optLong("server_time"));
        Unlock.setup(app);
        schedulePeriodicSync();
    }

    private static String cap(String s) { return s.isEmpty() ? s : Character.toUpperCase(s.charAt(0)) + s.substring(1); }

    // ------------------------------------------------------------------ the JS bridge's data
    JSONObject capsJson() {
        JSONObject o = new JSONObject();
        try {
            o.put("quality", quality()).put("wifi_only", wifiOnly()).put("storage", storagePref())
             .put("external_available", externalDir() != null)
             .put("lock", Unlock.lockKind(app)).put("device_secure", Unlock.deviceSecure(app)).put("pin", Unlock.pinSet(app))
             .put("registered", registered()).put("online", online()).put("username", username())
             .put("wipe_days", wipeDays()).put("offline_days", offlineDays()).put("last_sync", lastSync());
        } catch (JSONException ignored) { }
        return o;
    }

    JSONObject storageJson() {
        JSONObject o = new JSONObject();
        try {
            File d = baseDir();
            StatFs s = new StatFs(d.getPath());
            long used = du(new File(app.getNoBackupFilesDir(), "offline")) + du(externalDir());
            o.put("used", used).put("free", s.getAvailableBytes()).put("total", s.getTotalBytes());
        } catch (Exception ignored) { }
        return o;
    }

    JSONArray downloadsJson(boolean offlinePage) {
        JSONArray a = new JSONArray();
        long t = trustedNow();
        boolean wifiWait = wifiOnly() && !unmetered();
        try (Cursor c = db.r().rawQuery("SELECT * FROM dl ORDER BY created DESC", null)) {
            while (c.moveToNext()) {
                JSONObject o = new JSONObject();
                long gid = c.getLong(c.getColumnIndexOrThrow("gid"));
                String st = s(c, "state");
                long exp = l(c, "exp");
                if ("ready".equals(st) && Lic.unusableReason(exp, t, lastSync(), wipeDays()) != null) st = "expired";
                if ("queued".equals(st) && wifiWait) st = "waiting_wifi";
                long bytes = l(c, "bytes"), done = l(c, "done_bytes");
                o.put("gid", gid).put("item_id", l(c, "item_id")).put("title", s(c, "title")).put("subtitle", s(c, "subtitle"))
                 .put("state", st).put("quality", s(c, "quality")).put("bytes", bytes).put("done_bytes", done)
                 .put("progress", bytes > 0 ? Math.min(1.0, (double) done / bytes) : 0).put("prep", c.getDouble(c.getColumnIndexOrThrow("prep")))
                 .put("queue", l(c, "queue")).put("expires_at", exp).put("position", c.getDouble(c.getColumnIndexOrThrow("position")))
                 .put("duration", c.getDouble(c.getColumnIndexOrThrow("duration"))).put("error", s(c, "error"))
                 .put("kind", s(c, "kind"));
                String poster = s(c, "poster_url");
                if (!offlinePage && poster != null) o.put("poster_url", poster);
                o.put("has_poster", partFile(gid, "poster").exists());
                a.put(o);
            }
        } catch (JSONException ignored) { }
        return a;
    }

    static String s(Cursor c, String k) { int i = c.getColumnIndexOrThrow(k); return c.isNull(i) ? null : c.getString(i); }
    static long l(Cursor c, String k) { int i = c.getColumnIndexOrThrow(k); return c.isNull(i) ? 0 : c.getLong(i); }

    // ------------------------------------------------------------------ operations (called off the main thread)
    JSONObject options(long itemId) throws Exception {
        ensureDevice();
        JSONObject r = call("GET", "/api/offline/options/" + itemId, null, true, true).json();
        // the existing grant as this phone sees it
        JSONObject ex = r.optJSONObject("existing");
        if (ex != null && db.str(ex.optLong("id"), "state") == null) r.put("existing", JSONObject.NULL);   // not on this phone any more
        return r;
    }

    JSONObject download(long itemId, String profile, int audio, String fallbackTitle) throws Exception {
        ensureDevice();
        JSONObject b = new JSONObject().put("item_id", itemId).put("audio", audio);
        if (profile != null && !profile.isEmpty()) b.put("profile", profile);
        JSONObject g = call("POST", "/api/offline/grants", b, true, true).json();
        long gid = g.getLong("id");
        String token = g.optString("token", null);
        long exp = g.optLong("expires_at");
        if (token != null && !token.isEmpty()) exp = Lic.verify(token, serverPub(), serverId(), fp(), gid).exp;
        ContentValues v = new ContentValues();
        v.put("gid", gid);
        v.put("item_id", itemId);
        v.put("title", g.optString("title", fallbackTitle));
        v.put("profile", g.optString("profile"));
        v.put("quality", g.optString("quality"));
        v.put("audio", audio);
        v.put("bytes", g.optLong("bytes"));
        v.put("sha", g.isNull("sha256") ? null : g.optString("sha256"));
        v.put("token", token);
        v.put("exp", exp);
        v.put("state", "preparing".equals(g.optString("state")) ? "preparing" : "queued");
        v.put("created", now());
        v.put("dir", new File(baseDir(), String.valueOf(gid)).getPath());
        JSONObject job = g.optJSONObject("job");
        if (job != null) { v.put("prep", job.optDouble("progress", 0)); v.put("queue", job.optInt("position", 0)); }
        db.w().insertWithOnConflict("dl", null, v, SQLiteDatabase.CONFLICT_REPLACE);
        enqueue(gid, 0);
        changed();
        return new JSONObject().put("state", v.getAsString("state")).put("grant_id", gid);
    }

    void enqueue(long gid, long delaySeconds) {
        Constraints cons = new Constraints.Builder()
            .setRequiredNetworkType(wifiOnly() ? NetworkType.UNMETERED : NetworkType.CONNECTED)
            .setRequiresStorageNotLow(true).build();
        OneTimeWorkRequest.Builder w = new OneTimeWorkRequest.Builder(DownloadWorker.class)
            .setConstraints(cons)
            .setInputData(new Data.Builder().putLong("gid", gid).build())
            .addTag(TAG_DL)
            .setBackoffCriteria(androidx.work.BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS);
        if (delaySeconds > 0) w.setInitialDelay(delaySeconds, TimeUnit.SECONDS);
        WorkManager.getInstance(app).enqueueUniqueWork("dl-" + gid, ExistingWorkPolicy.REPLACE, w.build());
    }

    void setState(long gid, String state, String error) {
        ContentValues v = new ContentValues();
        v.put("state", state);
        v.put("error", error);
        db.w().update("dl", v, "gid=?", new String[]{String.valueOf(gid)});
        changed();
    }

    void pause(long gid) {
        WorkManager.getInstance(app).cancelUniqueWork("dl-" + gid);
        String st = db.str(gid, "state");
        if (st != null && !"ready".equals(st)) setState(gid, "paused", null);
    }

    void resume(long gid) {
        String st = db.str(gid, "state");
        if (st == null || "ready".equals(st)) return;
        setState(gid, "queued", null);
        enqueue(gid, 0);
    }

    /** delete on the phone; tell the server now, or at the next sync when offline */
    void remove(long gid) {
        WorkManager.getInstance(app).cancelUniqueWork("dl-" + gid);
        String st = db.str(gid, "state");
        rmrf(dirFor(gid));
        db.w().delete("dl", "gid=?", new String[]{String.valueOf(gid)});
        changed();
        if ("revoked".equals(st)) return;
        boolean told = false;
        try { call("DELETE", "/api/offline/grants/" + gid, null, false, true); told = true; }
        catch (ApiException e) { told = e.code == 404; }
        catch (Exception ignored) { }
        if (!told) {
            ContentValues v = new ContentValues();
            v.put("kind", "deleted"); v.put("gid", gid); v.put("ts", now());
            db.w().insert("pending", null, v);
        }
    }

    void deleteAll() {
        List<Long> all = db.gids();
        for (long g : all) remove(g);
    }

    void setSetting(String key, Object val) {
        SharedPreferences.Editor e = sp.edit();
        if ("wifi_only".equals(key)) {
            e.putBoolean("wifi_only", Boolean.TRUE.equals(val) || "true".equals(String.valueOf(val))).apply();
            for (long g : db.gids()) { String st = db.str(g, "state"); if ("queued".equals(st) || "downloading".equals(st)) enqueue(g, 0); }
        } else if ("quality".equals(key)) e.putString("quality", String.valueOf(val)).apply();
        else if ("storage".equals(key)) e.putString("storage", "external".equals(val) ? "external" : "internal").apply();
        changed();
    }

    /** the offline player's position; sent to the server at the next sync (the newest timestamp wins there) */
    void saveProgress(long gid, double pos, double dur, boolean ended) {
        long item = db.lng(gid, "item_id");
        ContentValues v = new ContentValues();
        v.put("position", ended ? 0 : pos);
        v.put("duration", dur);
        v.put("pos_ts", now());
        db.w().update("dl", v, "gid=?", new String[]{String.valueOf(gid)});
        db.w().delete("pending", "kind='progress' AND item_id=?", new String[]{String.valueOf(item)});
        ContentValues p = new ContentValues();
        p.put("kind", "progress"); p.put("gid", gid); p.put("item_id", item); p.put("position", pos); p.put("duration", dur);
        p.put("ts", now()); p.put("ended", ended ? 1 : 0);
        db.w().insert("pending", null, p);
        changed();
    }

    /** null when this download may play now, else why not (shown to the user) */
    String playBlock(long gid, boolean signedInOnline) {
        String st = db.str(gid, "state");
        if (!"ready".equals(st)) return "This download isn't finished yet.";
        if (!partFile(gid, "video").exists()) return "The file is missing. Delete the download and get it again.";
        Lic.Token t;
        try { t = Lic.verify(db.str(gid, "token"), serverPub(), serverId(), fp(), gid); }
        catch (SecurityException e) { return "This download's licence isn't valid (" + e.getMessage() + ")."; }
        String why = Lic.unusableReason(t.exp, trustedNow(), lastSync(), wipeDays());
        if (why != null) return why;
        if (!signedInOnline && !unlocked) return "Unlock your downloads first.";
        return null;
    }

    // ------------------------------------------------------------------ sync
    void schedulePeriodicSync() {
        PeriodicWorkRequest w = new PeriodicWorkRequest.Builder(SyncWorker.class, 6, TimeUnit.HOURS)
            .setConstraints(new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build();
        WorkManager.getInstance(app).enqueueUniquePeriodicWork(WORK_SYNC, ExistingPeriodicWorkPolicy.KEEP, w);
    }

    void syncSoon() {
        if (!registered()) return;
        OneTimeWorkRequest w = new OneTimeWorkRequest.Builder(SyncWorker.class)
            .setConstraints(new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build();
        WorkManager.getInstance(app).enqueueUniqueWork(WORK_SYNC + "-now", ExistingWorkPolicy.REPLACE, w);
    }

    /** renew licences, drop revoked downloads, send offline deletes and progress. Signed by the device key alone. */
    synchronized JSONObject sync() throws Exception {
        if (!registered()) return new JSONObject().put("registered", false);
        JSONArray held = new JSONArray();
        for (long g : db.gids()) held.put(g);
        JSONArray deleted = new JSONArray(), progress = new JSONArray();
        List<Long> sent = new ArrayList<>();
        try (Cursor c = db.r().rawQuery("SELECT * FROM pending ORDER BY id", null)) {
            while (c.moveToNext()) {
                sent.add(l(c, "id"));
                if ("deleted".equals(s(c, "kind"))) deleted.put(l(c, "gid"));
                else progress.put(new JSONObject().put("item_id", l(c, "item_id")).put("position", c.getDouble(c.getColumnIndexOrThrow("position")))
                    .put("duration", c.getDouble(c.getColumnIndexOrThrow("duration"))).put("ts", l(c, "ts")).put("ended", l(c, "ended") == 1));
            }
        }
        JSONObject b = new JSONObject().put("grants", held).put("deleted", deleted).put("progress", progress)
            .put("app_version", BuildConfigInfo.VERSION).put("caps", Caps.detect(app));
        JSONObject r;
        try { r = call("POST", "/api/offline/sync", b, true, false).json(); }
        catch (ApiException e) {
            if (e.code == 401 && e.body != null && e.body.optJSONObject("detail") != null && "unknown_device".equals(e.body.optJSONObject("detail").optString("reason"))) {
                wipe("this phone is no longer known to the server");
                return new JSONObject().put("wipe", true);
            }
            throw e;
        }
        sawServerTime(r.optLong("server_time"));
        if (r.optBoolean("wipe")) {
            wipe(r.optString("account", "removed"));
            return r;
        }
        for (long id : sent) db.w().delete("pending", "id=?", new String[]{String.valueOf(id)});
        SharedPreferences.Editor e = sp.edit().putLong("last_sync", r.optLong("server_time", now()))
            .putInt("wipe_days", r.optInt("wipe_days", wipeDays())).putInt("offline_days", r.optInt("offline_days", offlineDays()));
        JSONObject u = r.optJSONObject("user");
        if (u != null) e.putString("username", u.optString("username", username()));
        e.apply();
        JSONArray rev = r.optJSONArray("revoked");
        for (int i = 0; rev != null && i < rev.length(); i++) {
            JSONObject x = rev.getJSONObject(i);
            long gid = x.getLong("id");
            if (db.str(gid, "state") == null) continue;
            WorkManager.getInstance(app).cancelUniqueWork("dl-" + gid);
            rmrf(dirFor(gid));
            String why = x.optString("reason", "");
            if ("deleted".equals(why) || "unknown".equals(why)) db.w().delete("dl", "gid=?", new String[]{String.valueOf(gid)});
            else setState(gid, "revoked", "Removed by the server" + (why.isEmpty() ? "" : ": " + why));
        }
        JSONArray ren = r.optJSONArray("renewed");
        for (int i = 0; ren != null && i < ren.length(); i++) {
            JSONObject x = ren.getJSONObject(i);
            long gid = x.getLong("id");
            try {
                Lic.Token t = Lic.verify(x.getString("token"), serverPub(), serverId(), fp(), gid);
                ContentValues v = new ContentValues();
                v.put("token", x.getString("token")); v.put("exp", t.exp);
                db.w().update("dl", v, "gid=?", new String[]{String.valueOf(gid)});
            } catch (SecurityException ignored) { }
        }
        JSONArray act = r.optJSONArray("active");
        for (int i = 0; act != null && i < act.length(); i++) {
            JSONObject g = act.getJSONObject(i);
            long gid = g.getLong("id");
            String local = db.str(gid, "state");
            if (local == null) continue;
            ContentValues v = new ContentValues();
            JSONObject job = g.optJSONObject("job");
            if (job != null) { v.put("prep", job.optDouble("progress", 0)); v.put("queue", job.optInt("position", 0)); }
            if ("preparing".equals(local) && ("ready".equals(g.optString("state")) || "downloaded".equals(g.optString("state")))) {
                v.put("state", "queued");
                v.put("bytes", g.optLong("bytes"));
                db.w().update("dl", v, "gid=?", new String[]{String.valueOf(gid)});
                enqueue(gid, 0);
            } else if (v.size() > 0) db.w().update("dl", v, "gid=?", new String[]{String.valueOf(gid)});
        }
        Unlock.rearmIfNeeded(app);
        changed();
        return r;
    }

    // ------------------------------------------------------------------ wipe + sign-out
    /** forget the offline profile: every download, the keys and the catalog */
    synchronized void wipe(String why) {
        try { WorkManager.getInstance(app).cancelAllWorkByTag(TAG_DL); WorkManager.getInstance(app).cancelUniqueWork(WORK_SYNC); } catch (Exception ignored) { }
        rmrf(new File(app.getNoBackupFilesDir(), "offline"));
        rmrf(externalDir());
        db.w().delete("dl", null, null);
        db.w().delete("pending", null, null);
        boolean wifi = wifiOnly();
        String q = quality();
        sp.edit().clear().putBoolean("wifi_only", wifi).putString("quality", q).putString("wiped_reason", why).putLong("wiped_at", now()).apply();
        DeviceKey.delete();
        Unlock.reset(app);
        app.getSharedPreferences("movinite_keyset_prefs", Context.MODE_PRIVATE).edit().clear().apply();
        try { KeyStore k = KeyStore.getInstance("AndroidKeyStore"); k.load(null); if (k.containsAlias("movinite_master_v1")) k.deleteEntry("movinite_master_v1"); } catch (Exception ignored) { }
        aead = null;
        unlocked = false;
        changed();
    }

    /** the app's Sign out: tell the server to free this device (signed, no cookie needed), then wipe */
    void signOut() {
        if (registered()) {
            try { call("POST", "/api/devices/forget", new JSONObject(), true, false); } catch (Exception ignored) { }
        }
        if (registered() || hasDownloads()) wipe("signed out");
    }

    // ------------------------------------------------------------------ catalog
    static final class Db extends SQLiteOpenHelper {
        Db(Context c) { super(c, "offline.db", null, 1); }

        @Override public void onCreate(SQLiteDatabase d) {
            d.execSQL("CREATE TABLE dl(gid INTEGER PRIMARY KEY, item_id INTEGER, title TEXT, subtitle TEXT, kind TEXT, profile TEXT, quality TEXT, " +
                "audio INTEGER DEFAULT 0, state TEXT, bytes INTEGER DEFAULT 0, done_bytes INTEGER DEFAULT 0, sha TEXT, token TEXT, exp INTEGER DEFAULT 0, " +
                "poster_url TEXT, manifest TEXT, position REAL DEFAULT 0, duration REAL DEFAULT 0, pos_ts INTEGER DEFAULT 0, error TEXT, " +
                "created INTEGER, prep REAL DEFAULT 0, queue INTEGER DEFAULT 0, dir TEXT)");
            d.execSQL("CREATE TABLE pending(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, gid INTEGER, item_id INTEGER, position REAL, " +
                "duration REAL, ts INTEGER, ended INTEGER DEFAULT 0)");
        }

        @Override public void onUpgrade(SQLiteDatabase d, int a, int b) { }

        SQLiteDatabase r() { return getReadableDatabase(); }
        SQLiteDatabase w() { return getWritableDatabase(); }

        String str(long gid, String col) {
            try (Cursor c = r().rawQuery("SELECT " + col + " FROM dl WHERE gid=?", new String[]{String.valueOf(gid)})) {
                return c.moveToFirst() && !c.isNull(0) ? c.getString(0) : null;
            }
        }

        long lng(long gid, String col) {
            try (Cursor c = r().rawQuery("SELECT " + col + " FROM dl WHERE gid=?", new String[]{String.valueOf(gid)})) {
                return c.moveToFirst() && !c.isNull(0) ? c.getLong(0) : 0;
            }
        }

        int count() { try (Cursor c = r().rawQuery("SELECT COUNT(*) FROM dl", null)) { return c.moveToFirst() ? c.getInt(0) : 0; } }

        List<Long> gids() {
            List<Long> o = new ArrayList<>();
            try (Cursor c = r().rawQuery("SELECT gid FROM dl", null)) { while (c.moveToNext()) o.add(c.getLong(0)); }
            return o;
        }

        void update(long gid, ContentValues v) { w().update("dl", v, "gid=?", new String[]{String.valueOf(gid)}); }
    }
}
