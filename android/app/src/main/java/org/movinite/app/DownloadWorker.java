package org.movinite.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;

import androidx.annotation.NonNull;
import androidx.work.ForegroundInfo;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * One download in the background (WorkManager): waits while the server prepares the file, then fetches it with HTTP
 * ranges into the encrypted store (resuming at the last whole chunk), checks the SHA-256 against the server's, saves the
 * poster and subtitles, and confirms with the server, which answers with the signed licence.
 */
public class DownloadWorker extends Worker {
    static final String CHANNEL = "downloads";
    private final Offline off;
    private final long gid;
    private long lastUi = 0;

    public DownloadWorker(@NonNull Context c, @NonNull WorkerParameters p) {
        super(c, p);
        off = Offline.get(c);
        gid = p.getInputData().getLong("gid", 0);
    }

    static void channel(Context c) {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = c.getSystemService(NotificationManager.class);
            if (nm.getNotificationChannel(CHANNEL) == null)
                nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Downloads", NotificationManager.IMPORTANCE_LOW));
        }
    }

    private ForegroundInfo info(String title, int pct) {
        Context c = getApplicationContext();
        channel(c);
        Intent open = new Intent(c, MainActivity.class).setAction(MainActivity.ACTION_DOWNLOADS);
        PendingIntent pi = PendingIntent.getActivity(c, 1, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(c, CHANNEL) : new Notification.Builder(c);
        b.setSmallIcon(android.R.drawable.stat_sys_download).setContentTitle(title == null ? "Downloading" : title)
         .setContentText(pct >= 0 ? pct + "%" : "Starting ...").setProgress(100, Math.max(0, pct), pct < 0)
         .setOngoing(true).setOnlyAlertOnce(true).setContentIntent(pi);
        int id = (int) (1000 + gid % 100000);
        if (Build.VERSION.SDK_INT >= 29) return new ForegroundInfo(id, b.build(), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        return new ForegroundInfo(id, b.build());
    }

    @NonNull
    @Override
    public Result doWork() {
        String st = off.db.str(gid, "state");
        if (st == null || "ready".equals(st) || "paused".equals(st) || "revoked".equals(st)) return Result.success();
        if (!off.registered()) return Result.failure();
        String title = off.db.str(gid, "title");
        try {
            JSONObject g = off.call("GET", "/api/offline/grants/" + gid, null, true, true).json();
            String gs = g.optString("state");
            if ("preparing".equals(gs)) {
                ContentValues v = new ContentValues();
                v.put("state", "preparing");
                JSONObject job = g.optJSONObject("job");
                if (job != null) {
                    v.put("prep", job.optDouble("progress", 0)); v.put("queue", job.optInt("position", 0));
                    if ("failed".equals(job.optString("status"))) { off.setState(gid, "failed", "The server couldn't prepare this download"); return Result.success(); }
                }
                off.db.update(gid, v);
                off.changed();
                off.enqueue(gid, 20);       // check again shortly (the server pauses preparing while someone watches)
                return Result.success();
            }
            if (!"ready".equals(gs) && !"downloaded".equals(gs)) {
                off.setState(gid, "revoked".equals(gs) || "deleted".equals(gs) ? "revoked" : "failed", "Not available on the server (" + gs + ")");
                return Result.success();
            }
            try { setForegroundAsync(info(title, -1)); } catch (Exception ignored) { }
            long bytes = g.optLong("bytes");
            String sha = g.isNull("sha256") ? null : g.optString("sha256");
            ContentValues v = new ContentValues();
            v.put("state", "downloading"); v.put("bytes", bytes); v.put("sha", sha); v.put("error", (String) null);
            off.db.update(gid, v);
            off.changed();
            extras();
            if (isStopped()) return Result.retry();
            String got = fetch(bytes, title);
            if (got == null) return isStopped() ? Result.retry() : Result.retry();
            if (sha != null && !sha.equalsIgnoreCase(got)) {
                Offline.rmrf(off.partFile(gid, "video"));
                off.setState(gid, "failed", "The download was damaged. Try again.");
                return Result.success();
            }
            JSONObject done = off.call("POST", "/api/offline/grants/" + gid + "/done", new JSONObject().put("sha256", got), true, true).json();
            String tok = done.optString("token", null);
            Lic.Token t = Lic.verify(tok, off.serverPub(), off.serverId(), off.fp(), gid);
            ContentValues f = new ContentValues();
            f.put("state", "ready"); f.put("token", tok); f.put("exp", t.exp); f.put("done_bytes", bytes); f.put("sha", got);
            off.db.update(gid, f);
            off.changed();
            return Result.success();
        } catch (Offline.ApiException e) {
            if (e.code == 401 || e.code >= 500) { off.setState(gid, "queued", e.code == 401 ? "Open the app while online to continue" : null); return Result.retry(); }
            if (e.code == 404 || e.code == 410) { off.setState(gid, "failed", e.getMessage()); return Result.success(); }
            if (e.code == 409) { off.enqueue(gid, 30); return Result.success(); }    // not ready (cache refilled): wait
            off.setState(gid, "failed", e.getMessage());
            return Result.success();
        } catch (SecurityException e) {
            off.setState(gid, "failed", "The licence didn't check out (" + e.getMessage() + ")");
            return Result.success();
        } catch (java.io.IOException e) {
            if (getRunAttemptCount() > 8) { off.setState(gid, "failed", "Couldn't download: " + e.getMessage()); return Result.success(); }
            off.setState(gid, "queued", null);
            return Result.retry();
        } catch (Exception e) {
            off.setState(gid, "failed", String.valueOf(e.getMessage()));
            return Result.success();
        }
    }

    private static final Pattern CR = Pattern.compile("bytes (\\d+)-(\\d+)/(\\d+)");

    /** the file into the encrypted store; returns the plaintext sha256 when complete, null when stopped */
    private String fetch(long bytes, String title) throws Exception {
        File part = new File(off.dirFor(gid), "video.mvc.part"), fin = off.partFile(gid, "video");
        if (fin.exists() && bytes > 0) {   // finished earlier but not confirmed: re-hash it
            try (ChunkStore.Reader r = new ChunkStore.Reader(fin, off.aead(), gid, "video")) {
                java.security.MessageDigest md = java.security.MessageDigest.getInstance("SHA-256");
                for (long i = 0; i < Lic.chunks(r.plainLen); i++) md.update(r.chunk(i));
                return Lic.hex(md.digest());
            } catch (java.io.IOException e) { Offline.rmrf(fin); }
        }
        long start = part.exists() ? Lic.completeChunks(part.length(), bytes) : 0;
        try (ChunkStore.Writer w = new ChunkStore.Writer(part, off.aead(), gid, "video", bytes, start)) {
            long from = w.position();
            HttpURLConnection c = null;
            if (from < bytes) {
                c = off.open("GET", "/api/offline/" + gid + "/file", null, true, true, null);
                c.setRequestProperty("Accept", "application/octet-stream");
                c.setRequestProperty("Range", "bytes=" + from + "-");
                c.setReadTimeout(90000);
                int code = c.getResponseCode();
                if (code >= 400) {
                    byte[] err = Offline.readAll(c.getErrorStream());
                    String msg = "HTTP " + code;
                    try { Object d = new JSONObject(new String(err, "UTF-8")).opt("detail"); msg = d instanceof JSONObject ? ((JSONObject) d).optString("detail", msg) : String.valueOf(d); } catch (Exception ignored) { }
                    c.disconnect();
                    throw new Offline.ApiException(code, msg, null, null);
                }
                if (code == 200 && from > 0) throw new java.io.IOException("the server ignored the resume point");
                if (code == 206) {
                    Matcher m = CR.matcher(String.valueOf(c.getHeaderField("Content-Range")));
                    if (!m.find() || Long.parseLong(m.group(1)) != from || Long.parseLong(m.group(3)) != bytes)
                        throw new java.io.IOException("unexpected range from the server");
                }
                byte[] buf = new byte[256 * 1024];
                long done = from;
                try (InputStream in = c.getInputStream()) {
                    int n;
                    while ((n = in.read(buf)) > 0) {
                        w.write(buf, 0, n);
                        done += n;
                        if (isStopped()) { w.sync(); return null; }
                        long now = System.currentTimeMillis();
                        if (now - lastUi > 1000) {
                            lastUi = now;
                            ContentValues v = new ContentValues();
                            v.put("done_bytes", done);
                            off.db.update(gid, v);
                            off.changed();
                            int pct = bytes > 0 ? (int) (100 * done / bytes) : 0;
                            try { setForegroundAsync(info(title, pct)); } catch (Exception ignored) { }
                        }
                    }
                } finally { c.disconnect(); }
            }
            if (!w.complete()) throw new java.io.IOException("connection closed early");
            w.sync();
            String sha = w.sha256();
            w.close();
            if (!part.renameTo(fin)) throw new java.io.IOException("couldn't save the download");
            return sha;
        }
    }

    /** poster and subtitles (small; failures don't stop the download) */
    private void extras() {
        if (off.db.str(gid, "manifest") != null) return;
        try {
            JSONObject m = off.call("GET", "/api/offline/" + gid + "/manifest", null, true, true).json();
            ContentValues v = new ContentValues();
            v.put("manifest", m.toString());
            String sub = null;
            if ("episode".equals(m.optString("kind"))) sub = m.optString("show", "") + (m.optInt("season") > 0 ? String.format(java.util.Locale.ROOT, " · S%02dE%02d", m.optInt("season"), m.optInt("episode")) : "");
            else if (m.optInt("year") > 0) sub = String.valueOf(m.optInt("year"));
            v.put("subtitle", sub);
            v.put("kind", m.optString("kind"));
            if (m.optDouble("duration", 0) > 0) v.put("duration", m.optDouble("duration"));
            String poster = m.isNull("poster_url") ? null : m.optString("poster_url", null);
            if (poster != null) v.put("poster_url", poster);
            off.db.update(gid, v);
            off.changed();
            if (poster != null) saveSmall(poster, "poster");
            JSONArray subs = m.optJSONArray("subtitles");
            for (int i = 0; subs != null && i < subs.length(); i++) {
                JSONObject s = subs.getJSONObject(i);
                saveSmall(s.getString("url"), "sub-" + s.getString("key"));
            }
        } catch (Exception ignored) { }
    }

    private void saveSmall(String path, String part) {
        try {
            HttpURLConnection c = off.open("GET", path, null, false, true, null);
            try {
                if (c.getResponseCode() != 200) return;
                byte[] b = Offline.readAll(c.getInputStream());
                if (b.length > 0 && b.length < 8 * 1024 * 1024) ChunkStore.writeSmall(off.partFile(gid, part), off.aead(), gid, part, b);
            } finally { c.disconnect(); }
        } catch (Exception ignored) { }
    }
}
