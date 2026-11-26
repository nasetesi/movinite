package org.movinite.app;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.Toast;

import androidx.media3.common.MediaItem;
import androidx.media3.common.MimeTypes;
import androidx.media3.common.Player;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory;
import androidx.media3.ui.PlayerView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** The built-in offline player (Media3 / ExoPlayer): plays the encrypted download with its subtitles and resumes where you stopped. */
@UnstableApi
public class OfflinePlayerActivity extends Activity {
    static final String EXTRA_GID = "gid", EXTRA_ONLINE = "online";
    private ExoPlayer player;
    private PlayerView view;
    private long gid;
    private Offline off;
    private final Handler h = new Handler(Looper.getMainLooper());
    private final Runnable saver = new Runnable() { @Override public void run() { save(false); h.postDelayed(this, 10000); } };

    static void start(Context c, long gid, boolean online) {
        Offline o = Offline.get(c);
        String why = o.playBlock(gid, online);
        if (why != null) { Toast.makeText(c, why, Toast.LENGTH_LONG).show(); return; }
        Intent i = new Intent(c, OfflinePlayerActivity.class).putExtra(EXTRA_GID, gid).putExtra(EXTRA_ONLINE, online);
        if (!(c instanceof Activity)) i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        c.startActivity(i);
    }

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        off = Offline.get(this);
        gid = getIntent().getLongExtra(EXTRA_GID, 0);
        String why = off.playBlock(gid, getIntent().getBooleanExtra(EXTRA_ONLINE, false));
        if (why != null) { Toast.makeText(this, why, Toast.LENGTH_LONG).show(); finish(); return; }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON | WindowManager.LayoutParams.FLAG_SECURE);   // no screenshots / screen recording of films
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        view = new PlayerView(this);
        view.setKeepScreenOn(true);
        view.setShowSubtitleButton(true);
        view.setControllerShowTimeoutMs(3500);
        root.addView(view, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(root);
        immersive();

        List<MediaItem.SubtitleConfiguration> subs = new ArrayList<>();
        try {
            String m = off.db.str(gid, "manifest");
            JSONArray arr = m == null ? null : new JSONObject(m).optJSONArray("subtitles");
            for (int i = 0; arr != null && i < arr.length(); i++) {
                JSONObject s = arr.getJSONObject(i);
                String part = "sub-" + s.getString("key");
                if (!off.partFile(gid, part).exists()) continue;
                subs.add(new MediaItem.SubtitleConfiguration.Builder(EncryptedDataSource.uri(gid, part))
                    .setMimeType(MimeTypes.TEXT_VTT).setLanguage(s.isNull("lang") ? null : s.optString("lang")).setLabel(s.optString("label")).build());
            }
        } catch (Exception ignored) { }
        MediaItem item = new MediaItem.Builder().setUri(EncryptedDataSource.uri(gid, "video")).setSubtitleConfigurations(subs).build();
        player = new ExoPlayer.Builder(this).setMediaSourceFactory(new DefaultMediaSourceFactory(new EncryptedDataSource.Factory(off))).build();
        view.setPlayer(player);
        player.setMediaItem(item);
        double pos = 0, dur = 0;
        try (android.database.Cursor c = off.db.r().rawQuery("SELECT position, duration FROM dl WHERE gid=?", new String[]{String.valueOf(gid)})) {
            if (c.moveToFirst()) { pos = c.getDouble(0); dur = c.getDouble(1); }
        }
        if (pos > 30 && (dur <= 0 || pos < dur * 0.95)) player.seekTo((long) (pos * 1000));
        player.addListener(new Player.Listener() {
            @Override public void onPlaybackStateChanged(int st) { if (st == Player.STATE_ENDED) { save(true); finish(); } }
            @Override public void onPlayerError(androidx.media3.common.PlaybackException e) {
                Toast.makeText(OfflinePlayerActivity.this, "Can't play this download: " + e.getMessage(), Toast.LENGTH_LONG).show();
            }
        });
        player.prepare();
        player.play();
    }

    private void save(boolean ended) {
        if (player == null) return;
        long d = player.getDuration();
        if (d <= 0) return;
        off.saveProgress(gid, player.getCurrentPosition() / 1000.0, d / 1000.0, ended);
    }

    @SuppressWarnings("deprecation")
    private void immersive() {
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController c = getWindow().getInsetsController();
            if (c != null) { c.hide(WindowInsets.Type.systemBars()); c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE); }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
        }
    }

    @Override protected void onResume() { super.onResume(); immersive(); h.postDelayed(saver, 10000); }
    @Override protected void onPause() { super.onPause(); h.removeCallbacks(saver); save(false); if (player != null) player.pause(); }

    @Override
    protected void onDestroy() {
        h.removeCallbacks(saver);
        if (player != null) { player.release(); player = null; }
        if (off != null && off.online()) off.syncSoon();
        super.onDestroy();
    }
}
