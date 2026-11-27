package org.movinite.app;

import android.app.Activity;
import android.app.PictureInPictureParams;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Rational;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.GestureDetector;
import android.view.ScaleGestureDetector;
import android.view.ViewGroup;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.SeekBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.media3.common.AudioAttributes;
import androidx.media3.common.C;
import androidx.media3.common.MediaItem;
import androidx.media3.common.MimeTypes;
import androidx.media3.common.PlaybackException;
import androidx.media3.common.Player;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.datasource.DefaultHttpDataSource;
import androidx.media3.datasource.HttpDataSource;
import androidx.media3.exoplayer.DefaultRenderersFactory;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory;
import androidx.media3.exoplayer.trackselection.DefaultTrackSelector;
import androidx.media3.ui.PlayerView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 2.4: native online player (Media3 / ExoPlayer). Browse stays in the WebView;
 * Play hands off here with the WebView login cookie applied to media requests.
 */
@UnstableApi
public class PlayerActivity extends Activity {
    static final String EXTRA_ITEM = "item_id";
    static final String EXTRA_START = "start";
    static final String EXTRA_AUDIO = "audio";
    static final String EXTRA_SUB = "sub";
    static final String EXTRA_ERROR = "error";
    static final String EXTRA_FALLBACK = "fallback";

    private static final ExecutorService IO = Executors.newCachedThreadPool();
    private final Handler main = new Handler(Looper.getMainLooper());

    private ServerApi api;
    private ExoPlayer player;
    private DefaultTrackSelector tracks;
    private JSONObject caps;
    private JSONObject item;
    private JSONObject markers;
    private JSONObject me;
    private JSONObject trick;
    private final Map<Integer, Bitmap> sheets = new HashMap<>();

    private long itemId;
    private double startAt;
    private int audioIdx;
    private String subKey = "";
    private String mode = "";
    private final Set<String> triedModes = new HashSet<>();
    private boolean triedDirect;
    private boolean autoSkipIntro, autoSkipCredits;
    private boolean skippedIntro, shownUpNext, cancelledUpNext;
    private int upNextLeft;
    private boolean chromeOn = true;
    private boolean seeking;
    private boolean ended;

    private PlayerView surface;
    private View chrome, wait, skipRow, upNext, menu;
    private TextView title, modeLab, waitText, debugLine, tCur, tEnd, upTitle, upCount, menuTitle;
    private SeekBar seek;
    private ImageView trickView;
    private Button btnPlay, btnBack10, btnFwd10, btnAudio, btnSubs, btnQuality;
    private Button btnIntro, btnCredits, btnPlayNow, btnCancel;
    private LinearLayout menuList;

    private final Runnable hideChrome = () -> { if (chromeOn && !seeking && !menuOpen()) setChrome(false); };
    private GestureDetector gestures;
    private ScaleGestureDetector pincher;
    private boolean pinchHandled;
    private boolean fillCrop;

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            syncChrome();
            main.postDelayed(this, 250);
        }
    };
    private final Runnable save = new Runnable() {
        @Override public void run() {
            saveProgress(false);
            main.postDelayed(this, 10000);
        }
    };
    private final Runnable upTick = new Runnable() {
        @Override public void run() {
            if (upNext.getVisibility() != View.VISIBLE) return;
            upNextLeft--;
            if (upNextLeft <= 0) { playNext(); return; }
            upCount.setText("Playing in " + upNextLeft + "s");
            main.postDelayed(this, 1000);
        }
    };

    /** Called from the JS bridge on the UI thread. Returns a JSON status string. */
    static String startFromJs(Context c, String json) {
        try {
            JSONObject o = new JSONObject(json == null ? "{}" : json);
            long id = o.getLong("item_id");
            if (id == 0) return "{\"ok\":false,\"detail\":\"no item\"}";
            if (Prefs.serverUrl(c) == null) return "{\"ok\":false,\"detail\":\"no server\"}";
            Intent i = new Intent(c, PlayerActivity.class)
                .putExtra(EXTRA_ITEM, id)
                .putExtra(EXTRA_START, o.optDouble("start", 0))
                .putExtra(EXTRA_AUDIO, o.optInt("audio", 0))
                .putExtra(EXTRA_SUB, o.optString("sub", ""));
            if (c instanceof MainActivity) {
                ((MainActivity) c).startActivityForResult(i, MainActivity.REQ_NATIVE_PLAY);
            } else if (c instanceof Activity) {
                ((Activity) c).startActivityForResult(i, MainActivity.REQ_NATIVE_PLAY);
            } else {
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                c.startActivity(i);
            }
            return "{\"ok\":true}";
        } catch (Exception e) {
            return "{\"ok\":false}";
        }
    }

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        api = new ServerApi(this);
        caps = Caps.detect(this);
        itemId = getIntent().getLongExtra(EXTRA_ITEM, 0);
        startAt = getIntent().getDoubleExtra(EXTRA_START, 0);
        audioIdx = getIntent().getIntExtra(EXTRA_AUDIO, 0);
        subKey = getIntent().getStringExtra(EXTRA_SUB);
        if (subKey == null) subKey = "";
        if (itemId == 0 || !api.signedIn()) {
            Toast.makeText(this, itemId == 0 ? "Nothing to play" : "Your session has ended. Please sign in again.", Toast.LENGTH_LONG).show();
            finish();
            return;
        }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (Build.VERSION.SDK_INT >= 26) {
            try { getWindow().setColorMode(ActivityInfo.COLOR_MODE_HDR); } catch (Exception ignored) { }
        }
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
        setContentView(R.layout.activity_player);
        bind();
        immersive();
        buildPlayer();
        IO.execute(this::loadAndPlay);
    }

    private void bind() {
        surface = findViewById(R.id.surface);
        chrome = findViewById(R.id.chrome);
        wait = findViewById(R.id.wait);
        waitText = findViewById(R.id.wait_text);
        debugLine = findViewById(R.id.debug);
        skipRow = findViewById(R.id.skip_row);
        upNext = findViewById(R.id.upnext);
        menu = findViewById(R.id.menu);
        title = findViewById(R.id.title);
        modeLab = findViewById(R.id.mode);
        tCur = findViewById(R.id.t_cur);
        tEnd = findViewById(R.id.t_end);
        seek = findViewById(R.id.seek);
        trickView = findViewById(R.id.trick);
        btnPlay = findViewById(R.id.btn_play);
        btnBack10 = findViewById(R.id.btn_back10);
        btnFwd10 = findViewById(R.id.btn_fwd10);
        btnAudio = findViewById(R.id.btn_audio);
        btnSubs = findViewById(R.id.btn_subs);
        btnQuality = findViewById(R.id.btn_quality);
        btnIntro = findViewById(R.id.btn_intro);
        btnCredits = findViewById(R.id.btn_credits);
        btnPlayNow = findViewById(R.id.btn_playnow);
        btnCancel = findViewById(R.id.btn_cancel);
        upTitle = findViewById(R.id.upnext_title);
        upCount = findViewById(R.id.upnext_count);
        menuTitle = findViewById(R.id.menu_title);
        menuList = findViewById(R.id.menu_list);

        btnPlay.setOnClickListener(v -> togglePlay());
        btnBack10.setOnClickListener(v -> seekBy(-10_000));
        btnFwd10.setOnClickListener(v -> seekBy(10_000));
        btnAudio.setOnClickListener(v -> openAudioMenu());
        btnSubs.setOnClickListener(v -> openSubMenu());
        btnQuality.setOnClickListener(v -> openQualityMenu());
        btnIntro.setOnClickListener(v -> skipIntro());
        btnCredits.setOnClickListener(v -> skipCredits());
        btnPlayNow.setOnClickListener(v -> playNext());
        btnCancel.setOnClickListener(v -> cancelUpNext());
        seek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar s, int p, boolean fromUser) {
                if (!fromUser || player == null) return;
                long dur = Math.max(player.getDuration(), 0);
                long pos = dur <= 0 ? 0 : dur * p / 1000;
                tCur.setText(fmt(pos));
                showTrick(pos / 1000.0);
            }
            @Override public void onStartTrackingTouch(SeekBar s) { seeking = true; showChrome(); }
            @Override public void onStopTrackingTouch(SeekBar s) {
                seeking = false;
                if (player != null) {
                    long dur = Math.max(player.getDuration(), 0);
                    player.seekTo(dur <= 0 ? 0 : dur * s.getProgress() / 1000);
                }
                trickView.setVisibility(View.GONE);
                bumpChrome();
            }
        });
        seek.setOnFocusChangeListener((v, has) -> { if (has) showChrome(); });
        setChrome(true);
        bindTouch();
        View close = findViewById(R.id.btn_close);
        if (close != null) close.setOnClickListener(v -> finish());
        View fit = findViewById(R.id.btn_fit);
        if (fit != null) fit.setOnClickListener(v -> toggleFitFill());
    }

    /** 2.4.4: tap empty video to show/hide controls; double-tap sides seek ±10s; pinch toggles fit/fill. */
    private void bindTouch() {
        View root = findViewById(R.id.root);
        gestures = new GestureDetector(this, new GestureDetector.SimpleOnGestureListener() {
            @Override public boolean onDown(MotionEvent e) { return true; }
            @Override public boolean onSingleTapConfirmed(MotionEvent e) {
                if (hitInteractive(e)) return false;
                if (menuOpen()) { hideMenu(); return true; }
                if (chromeOn) setChrome(false);
                else showChrome();
                return true;
            }
            @Override public boolean onDoubleTap(MotionEvent e) {
                if (hitInteractive(e)) return false;
                int w = surface != null ? surface.getWidth() : 0;
                int a = NativePlay.doubleTapAction(e.getX(), w);
                if (a == NativePlay.TAP_BACK) seekBy(-10_000);
                else if (a == NativePlay.TAP_FWD) seekBy(10_000);
                else {
                    if (chromeOn) setChrome(false); else showChrome();
                }
                return true;
            }
        });
        pincher = new ScaleGestureDetector(this, new ScaleGestureDetector.SimpleOnScaleGestureListener() {
            @Override public void onScaleEnd(ScaleGestureDetector d) {
                if (d.getScaleFactor() > 1.08f && !fillCrop) toggleFitFill();
                else if (d.getScaleFactor() < 0.92f && fillCrop) toggleFitFill();
                pinchHandled = true;
            }
        });
        if (root != null) {
            root.setClickable(true);
        }
    }

    private boolean hitInteractive(MotionEvent e) {
        View root = findViewById(R.id.root);
        if (root == null) return false;
        View v = hit(root, e.getRawX(), e.getRawY());
        while (v != null) {
            int id = v.getId();
            if (v instanceof Button || v instanceof SeekBar) return true;
            if (id == R.id.menu || id == R.id.upnext || id == R.id.skip_row) return true;
            if (!(v.getParent() instanceof View)) break;
            v = (View) v.getParent();
        }
        return false;
    }

    private static View hit(View v, float rawX, float rawY) {
        int[] loc = new int[2];
        v.getLocationOnScreen(loc);
        if (rawX < loc[0] || rawY < loc[1] || rawX >= loc[0] + v.getWidth() || rawY >= loc[1] + v.getHeight())
            return null;
        if (v instanceof ViewGroup) {
            ViewGroup g = (ViewGroup) v;
            for (int i = g.getChildCount() - 1; i >= 0; i--) {
                View child = g.getChildAt(i);
                if (child.getVisibility() != View.VISIBLE) continue;
                View found = hit(child, rawX, rawY);
                if (found != null) return found;
            }
        }
        return v;
    }

    private void toggleFitFill() {
        fillCrop = !fillCrop;
        if (surface != null)
            surface.setResizeMode(fillCrop ? androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_ZOOM
                : androidx.media3.ui.AspectRatioFrameLayout.RESIZE_MODE_FIT);
        View fit = findViewById(R.id.btn_fit);
        if (fit instanceof Button) ((Button) fit).setText(fillCrop ? "Fit" : "Fill");
        showChrome();
    }

    private void buildPlayer() {
        Map<String, String> headers = new HashMap<>();
        String cookie = api.cookieHeader();
        if (cookie != null) headers.put("Cookie", cookie);
        headers.put("User-Agent", "Movinite-Android/" + BuildConfigInfo.VERSION);
        DefaultHttpDataSource.Factory http = new DefaultHttpDataSource.Factory()
            .setAllowCrossProtocolRedirects(true)
            .setConnectTimeoutMs(15_000)
            .setReadTimeoutMs(30_000)
            .setDefaultRequestProperties(headers);
        DefaultRenderersFactory rf = new DefaultRenderersFactory(this).setEnableDecoderFallback(true);
        tracks = new DefaultTrackSelector(this);
        player = new ExoPlayer.Builder(this)
            .setRenderersFactory(rf)
            .setTrackSelector(tracks)
            .setMediaSourceFactory(new DefaultMediaSourceFactory(http))
            .setSeekBackIncrementMs(10_000)
            .setSeekForwardIncrementMs(10_000)
            .build();
        player.setAudioAttributes(new AudioAttributes.Builder()
            .setUsage(C.USAGE_MEDIA)
            .setContentType(C.AUDIO_CONTENT_TYPE_MOVIE)
            .build(), true);
        player.setHandleAudioBecomingNoisy(true);
        surface.setPlayer(player);
        player.addListener(new Player.Listener() {
            @Override public void onPlaybackStateChanged(int st) {
                if (st == Player.STATE_READY) {
                    wait.setVisibility(View.GONE);
                    if (startAt > 1 && Math.abs(player.getCurrentPosition() / 1000.0 - startAt) > 2)
                        player.seekTo((long) (startAt * 1000));
                    startAt = 0;
                }
                if (st == Player.STATE_ENDED) { ended = true; saveProgress(true); showUpNext(true); }
                syncChrome();
            }
            @Override public void onIsPlayingChanged(boolean n) { syncChrome(); bumpChrome(); }
            @Override public void onPlayerError(PlaybackException e) {
                main.post(() -> onPlayError(e));
            }
        });
    }

    private void loadAndPlay() {
        try {
            String q = Caps.asQuery(caps);
            item = api.getJson("/api/items/" + itemId + "?" + q);
            try { markers = api.getJson("/api/items/" + itemId + "/markers"); } catch (Exception e) { markers = new JSONObject(); }
            try { me = api.getJson("/api/me"); } catch (Exception e) { me = new JSONObject(); }
            autoSkipIntro = me.optBoolean("auto_skip_intro", false);
            autoSkipCredits = me.optBoolean("auto_skip_credits", false);
            if (startAt <= 0) {
                double pos = item.optDouble("position", 0);
                if (pos > 30) startAt = pos;
            }
            try {
                trick = api.getJson("/api/items/" + itemId + "/trickplay");
                if (trick != null && "ready".equals(trick.optString("status")) || "partial".equals(trick.optString("status")))
                    prefetchSheets();
            } catch (Exception ignored) { }
            final String first = pickMode(false);
            main.post(() -> {
                applyTitle();
                startStream(first, startAt);
            });
        } catch (Exception e) {
            main.post(() -> {
                Toast.makeText(this, e.getMessage() == null ? "Couldn't start playback" : e.getMessage(), Toast.LENGTH_LONG).show();
                finish();
            });
        }
    }

    private void applyTitle() {
        if (item == null) return;
        String t;
        if ("episode".equals(item.optString("kind"))) {
            t = item.optString("show") + " · S" + item.optInt("season") + "E" + item.optInt("episode") + " · " + item.optString("title");
        } else {
            t = item.optString("title");
            if (item.optInt("year") > 0) t += " (" + item.optInt("year") + ")";
        }
        title.setText(t);
    }

    private JSONObject pb() { return item == null ? new JSONObject() : item.optJSONObject("playback"); }

    private boolean subBurns() {
        JSONObject p = pb();
        if (p == null || subKey.isEmpty()) return false;
        JSONArray subs = p.optJSONArray("subtitles");
        for (int i = 0; subs != null && i < subs.length(); i++) {
            JSONObject s = subs.optJSONObject(i);
            if (s != null && subKey.equals(s.optString("key")) && (s.optBoolean("burn") || "image".equals(s.optString("kind"))))
                return true;
        }
        return false;
    }

    private String pickMode(boolean afterFail) {
        JSONObject p = pb();
        if (p == null) return "1080p";
        if (subBurns()) return firstTranscode(p);
        if (!afterFail && (p.optBoolean("direct") || p.optBoolean("direct_maybe"))) return "direct";
        if (p.optBoolean("remux")) return "remux";
        return firstTranscode(p);
    }

    private String firstTranscode(JSONObject p) {
        JSONArray hi = p.optJSONArray("hires");
        if (hi != null && hi.length() > 0) {
            String h = hi.optString(0);
            return caps.optBoolean("hevc") ? h + ".hevc" : h;
        }
        JSONArray pr = p.optJSONArray("profiles");
        if (pr != null && pr.length() > 0) return pr.optString(0);
        return "1080p";
    }

    private void startStream(String m, double at) {
        if (player == null || item == null) return;
        mode = m;
        if (m != null) triedModes.add(m);
        ended = false;
        shownUpNext = false;
        long seekMs = (long) Math.max(0, at * 1000);
        wait.setVisibility(View.VISIBLE);
        waitText.setText(label(m));
        modeLab.setText(label(m));
        List<MediaItem.SubtitleConfiguration> subs = textSubs();
        MediaItem.Builder b = new MediaItem.Builder();
        if ("direct".equals(m)) {
            triedDirect = true;
            b.setUri(api.base + "/api/items/" + itemId + "/file");
        } else {
            int seg = pb() != null ? pb().optInt("seg", 2) : 2;
            int startSeg = seg > 0 ? (int) Math.floor(at / seg) : 0;
            String burn = "";
            if (subBurns()) {
                try { burn = "&burn=" + Integer.parseInt(subKey.replaceAll("[^0-9]", "")); } catch (Exception ignored) { }
            }
            String url = api.base + "/api/items/" + itemId + "/hls/" + m + "/index.m3u8?audio=" + audioIdx
                + "&" + Caps.asQuery(caps) + "&player=" + Uri.encode("native-" + BuildConfigInfo.VERSION)
                + "&start=" + startSeg + burn;
            b.setUri(url).setMimeType(MimeTypes.APPLICATION_M3U8);
        }
        if (!subs.isEmpty()) b.setSubtitleConfigurations(subs);
        player.setMediaItem(b.build());
        player.prepare();
        if (seekMs > 1000 && "direct".equals(m)) player.seekTo(seekMs);
        player.play();
        bumpChrome();
    }

    private List<MediaItem.SubtitleConfiguration> textSubs() {
        List<MediaItem.SubtitleConfiguration> out = new ArrayList<>();
        JSONObject p = pb();
        if (p == null) return out;
        JSONArray subs = p.optJSONArray("subtitles");
        for (int i = 0; subs != null && i < subs.length(); i++) {
            JSONObject s = subs.optJSONObject(i);
            if (s == null) continue;
            if (s.optBoolean("burn") || "image".equals(s.optString("kind"))) continue;
            String key = s.optString("key");
            MediaItem.SubtitleConfiguration.Builder sb = new MediaItem.SubtitleConfiguration.Builder(
                Uri.parse(api.base + "/api/items/" + itemId + "/subs/" + key + ".vtt"))
                .setMimeType(MimeTypes.TEXT_VTT)
                .setLanguage(s.isNull("lang") ? null : s.optString("lang"))
                .setLabel(s.optString("label", key));
            if (key.equals(subKey)) sb.setSelectionFlags(C.SELECTION_FLAG_DEFAULT);
            out.add(sb.build());
        }
        return out;
    }

    private String describeError(PlaybackException e) {
        Integer http = null;
        String cause = null;
        Throwable c = e == null ? null : e.getCause();
        while (c != null) {
            if (c instanceof HttpDataSource.InvalidResponseCodeException)
                http = ((HttpDataSource.InvalidResponseCodeException) c).responseCode;
            if (cause == null && c.getMessage() != null) cause = c.getMessage();
            c = c.getCause();
        }
        return PlayFallback.errorDetail(e == null ? null : e.getErrorCodeName(),
            http, e == null ? null : e.getMessage(), cause);
    }

    private void showDebug(String s) {
        if (debugLine == null) return;
        debugLine.setText(s == null ? "" : s);
        debugLine.setVisibility(s == null || s.isEmpty() ? View.GONE : View.VISIBLE);
    }

    private void onPlayError(PlaybackException e) {
        String detail = describeError(e);
        showDebug(detail);
        if (waitText != null) waitText.setText(detail);
        if (mode != null) triedModes.add(mode);
        String next = PlayFallback.nextMode(mode, pb(), caps, triedModes);
        if (next != null && !PlayFallback.WEB.equals(next)) {
            Toast.makeText(this, "Switching to " + label(next) + " \u00b7 " + detail, Toast.LENGTH_SHORT).show();
            startAt = player != null ? Math.max(startAt, player.getCurrentPosition() / 1000.0) : startAt;
            startStream(next, startAt);
            return;
        }
        // 2.4.3: after HEVC and H.264 fail, hand the title back to the in-page player.
        Intent data = new Intent()
            .putExtra(EXTRA_ITEM, itemId)
            .putExtra(EXTRA_START, player != null ? Math.max(startAt, player.getCurrentPosition() / 1000.0) : startAt)
            .putExtra(EXTRA_AUDIO, audioIdx)
            .putExtra(EXTRA_SUB, subKey == null ? "" : subKey)
            .putExtra(EXTRA_ERROR, detail)
            .putExtra(EXTRA_FALLBACK, PlayFallback.WEB);
        setResult(RESULT_OK, data);
        Toast.makeText(this, "Opening the in-page player \u00b7 " + detail, Toast.LENGTH_LONG).show();
        finish();
    }

    private String label(String m) {
        if ("direct".equals(m)) return "Direct play";
        if ("remux".equals(m)) return "Remux (original video)";
        if (m != null && m.contains("2160")) return "Transcode 4K" + (m.contains("hevc") ? " HEVC" : "");
        if (m != null && m.contains("1440")) return "Transcode 2K" + (m.contains("hevc") ? " HEVC" : "");
        return "Transcode " + (m == null ? "" : m.replace(".hevc", " HEVC"));
    }

    // ---- chrome / remote ----
    private boolean menuOpen() { return menu.getVisibility() == View.VISIBLE; }

    private void setChrome(boolean on) {
        chromeOn = on;
        chrome.setVisibility(on ? View.VISIBLE : View.INVISIBLE);
        if (on) {
            if (!btnPlay.isFocused() && !seek.isFocused() && !menuOpen()
                && btnIntro.getVisibility() != View.VISIBLE && btnCredits.getVisibility() != View.VISIBLE
                && upNext.getVisibility() != View.VISIBLE)
                btnPlay.requestFocus();
            bumpChrome();
        } else {
            main.removeCallbacks(hideChrome);
            trickView.setVisibility(View.GONE);
        }
    }

    private void showChrome() { setChrome(true); }
    private void bumpChrome() {
        main.removeCallbacks(hideChrome);
        if (chromeOn && player != null && player.isPlaying() && !menuOpen() && upNext.getVisibility() != View.VISIBLE)
            main.postDelayed(hideChrome, 4000);
    }

    private void togglePlay() {
        if (player == null) return;
        if (player.isPlaying()) player.pause(); else player.play();
        showChrome();
        syncChrome();
    }

    private void seekBy(long ms) {
        if (player == null) return;
        long pos = Math.max(0, player.getCurrentPosition() + ms);
        long dur = player.getDuration();
        if (dur > 0) pos = Math.min(pos, dur);
        player.seekTo(pos);
        showTrick(pos / 1000.0);
        showChrome();
        main.postDelayed(() -> trickView.setVisibility(View.GONE), 800);
    }

    private void syncChrome() {
        if (player == null) return;
        long pos = Math.max(0, player.getCurrentPosition());
        long dur = player.getDuration();
        if (!seeking && dur > 0) {
            seek.setProgress((int) (pos * 1000 / dur));
            tEnd.setText(fmt(dur));
        }
        tCur.setText(fmt(pos));
        btnPlay.setText(player.isPlaying() ? "Pause" : "Play");
        updateSkip(pos / 1000.0, dur > 0 ? dur / 1000.0 : item != null ? item.optDouble("duration", 0) : 0);
    }

    private void updateSkip(double pos, double dur) {
        double i0 = markers == null ? -1 : markers.optDouble("intro_start", Double.NaN);
        double i1 = markers == null ? -1 : markers.optDouble("intro_end", Double.NaN);
        double c0 = markers == null ? -1 : markers.optDouble("credits_start", Double.NaN);
        boolean inIntro = !Double.isNaN(i0) && !Double.isNaN(i1) && pos >= i0 && pos < i1 - 0.4 && !skippedIntro;
        boolean inCredits = !Double.isNaN(c0) && pos >= c0;
        if (inIntro && autoSkipIntro && !skippedIntro) { skipIntro(); return; }
        if (inCredits && autoSkipCredits && !shownUpNext) { skipCredits(); return; }
        btnIntro.setVisibility(inIntro ? View.VISIBLE : View.GONE);
        btnCredits.setVisibility(inCredits && itemHasNext() ? View.VISIBLE : View.GONE);
        if (inIntro && btnIntro.getVisibility() == View.VISIBLE && !menuOpen() && !btnIntro.isFocused())
            btnIntro.requestFocus();
        if (!cancelledUpNext && itemHasNext() && dur > 0 && pos >= Math.max(dur - 15, Double.isNaN(c0) ? dur - 15 : c0))
            showUpNext(false);
    }

    private void skipIntro() {
        skippedIntro = true;
        btnIntro.setVisibility(View.GONE);
        double i1 = markers == null ? 0 : markers.optDouble("intro_end", 0);
        if (player != null && i1 > 0) player.seekTo((long) (i1 * 1000));
    }

    private void skipCredits() {
        btnCredits.setVisibility(View.GONE);
        showUpNext(true);
    }

    private boolean itemHasNext() {
        return item != null && item.optJSONObject("next") != null && item.optJSONObject("next").optLong("id", 0) > 0;
    }

    private void showUpNext(boolean force) {
        if (shownUpNext && upNext.getVisibility() == View.VISIBLE) return;
        if (!itemHasNext()) {
            if (force && ended) finish();
            return;
        }
        shownUpNext = true;
        JSONObject n = item.optJSONObject("next");
        String t = n.optString("title", "Next episode");
        if (n.optInt("season") > 0)
            t = "S" + n.optInt("season") + "E" + n.optInt("episode") + " · " + t;
        upTitle.setText(t);
        upNextLeft = 15;
        upCount.setText("Playing in 15s");
        upNext.setVisibility(View.VISIBLE);
        btnPlayNow.requestFocus();
        main.removeCallbacks(upTick);
        main.postDelayed(upTick, 1000);
    }

    private void cancelUpNext() {
        cancelledUpNext = true;
        shownUpNext = true;
        main.removeCallbacks(upTick);
        upNext.setVisibility(View.GONE);
        if (ended) finish();
    }

    private void playNext() {
        main.removeCallbacks(upTick);
        JSONObject n = item == null ? null : item.optJSONObject("next");
        if (n == null) { finish(); return; }
        saveProgress(true);
        itemId = n.optLong("id");
        startAt = 0; audioIdx = 0; subKey = ""; skippedIntro = false; shownUpNext = false; cancelledUpNext = false;
        upNext.setVisibility(View.GONE);
        wait.setVisibility(View.VISIBLE);
        waitText.setText("Starting next episode…");
        IO.execute(this::loadAndPlay);
    }

    // ---- menus ----
    private void openAudioMenu() {
        JSONObject p = pb();
        JSONArray a = p == null ? null : p.optJSONArray("audio_streams");
        List<Row> rows = new ArrayList<>();
        if (a == null || a.length() == 0) rows.add(new Row("Default", 0, audioIdx == 0));
        for (int i = 0; a != null && i < a.length(); i++) {
            JSONObject s = a.optJSONObject(i);
            String lab = (s.optString("title").isEmpty() ? s.optString("lang", "Audio " + (i + 1)) : s.optString("title"))
                + " · " + s.optString("codec") + (s.optInt("channels") > 0 ? " " + s.optInt("channels") + "ch" : "");
            final int idx = i;
            rows.add(new Row(lab, idx, idx == audioIdx));
        }
        showMenu("Audio", rows, r -> {
            audioIdx = r.value;
            hideMenu();
            startAt = player == null ? startAt : player.getCurrentPosition() / 1000.0;
            // Direct play of a file uses the first audio unless we restart as remux/HLS to pick a track.
            String m = "direct".equals(mode) && audioIdx != 0 && pb() != null && (pb().optBoolean("remux") || true)
                ? (pb().optBoolean("remux") ? "remux" : firstTranscode(pb())) : mode;
            startStream(m, startAt);
        });
    }

    private void openSubMenu() {
        JSONObject p = pb();
        JSONArray s = p == null ? null : p.optJSONArray("subtitles");
        List<Row> rows = new ArrayList<>();
        rows.add(new Row("Off", -1, subKey.isEmpty()));
        for (int i = 0; s != null && i < s.length(); i++) {
            JSONObject t = s.optJSONObject(i);
            String lab = t.optString("label");
            if (t.optBoolean("burn") || "image".equals(t.optString("kind"))) lab += " · burned in";
            final String key = t.optString("key");
            rows.add(new Row(lab, i, key.equals(subKey)) { { this.key = key; } });
        }
        showMenu("Subtitles", rows, r -> {
            subKey = r.key == null ? "" : r.key;
            hideMenu();
            startAt = player == null ? startAt : player.getCurrentPosition() / 1000.0;
            boolean burn = subBurns();
            String m = burn ? firstTranscode(pb()) : mode;
            if (!burn && "direct".equals(mode)) { startStream(mode, startAt); return; }
            startStream(m, startAt);
        });
    }

    private void openQualityMenu() {
        JSONObject p = pb();
        List<Row> rows = new ArrayList<>();
        int i = 0;
        if (p != null && (p.optBoolean("direct") || p.optBoolean("direct_maybe")))
            rows.add(new Row("Original (direct play)", i++, "direct".equals(mode)) { { this.key = "direct"; } });
        if (p != null && p.optBoolean("remux"))
            rows.add(new Row("Original (remux)", i++, "remux".equals(mode)) { { this.key = "remux"; } });
        JSONArray hi = p == null ? null : p.optJSONArray("hires");
        for (int n = 0; hi != null && n < hi.length(); n++) {
            String h = hi.optString(n);
            String key = caps.optBoolean("hevc") ? h + ".hevc" : h;
            rows.add(new Row(label(key), i++, key.equals(mode)) { { this.key = key; } });
        }
        JSONArray pr = p == null ? null : p.optJSONArray("profiles");
        for (int n = 0; pr != null && n < pr.length(); n++) {
            String key = pr.optString(n);
            rows.add(new Row(label(key), i++, key.equals(mode)) { { this.key = key; } });
        }
        showMenu("Quality", rows, r -> {
            hideMenu();
            startAt = player == null ? startAt : player.getCurrentPosition() / 1000.0;
            startStream(r.key, startAt);
        });
    }

    private static class Row {
        final String label; final int value; final boolean selected; String key;
        Row(String l, int v, boolean s) { label = l; value = v; selected = s; }
    }
    private interface Pick { void onPick(Row r); }

    private void showMenu(String heading, List<Row> rows, Pick pick) {
        menuTitle.setText(heading);
        menuList.removeAllViews();
        menu.setVisibility(View.VISIBLE);
        showChrome();
        Button first = null, sel = null;
        for (Row r : rows) {
            Button b = new Button(this);
            b.setText((r.selected ? "●  " : "    ") + r.label);
            b.setAllCaps(false);
            b.setTextColor(Color.WHITE);
            b.setBackgroundResource(R.drawable.player_chip);
            b.setFocusable(true);
            b.setPadding(24, 18, 24, 18);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            lp.topMargin = 8;
            b.setLayoutParams(lp);
            final Row rr = r;
            b.setOnClickListener(v -> pick.onPick(rr));
            menuList.addView(b);
            if (first == null) first = b;
            if (r.selected) sel = b;
        }
        Button focus = sel != null ? sel : first;
        if (focus != null) focus.requestFocus();
    }

    private void hideMenu() { menu.setVisibility(View.GONE); bumpChrome(); }

    // ---- trickplay ----
    private void prefetchSheets() {
        if (trick == null) return;
        JSONArray arr = trick.optJSONArray("sheets");
        int n = arr == null ? 0 : Math.min(arr.length(), 4);
        for (int i = 0; i < n; i++) {
            try {
                Bitmap bm = api.getBitmap(arr.getString(i));
                if (bm != null) sheets.put(i, bm);
            } catch (Exception ignored) { }
        }
    }

    private void showTrick(double seconds) {
        if (trick == null || sheets.isEmpty()) { trickView.setVisibility(View.GONE); return; }
        double interval = trick.optDouble("interval", 10);
        int cols = trick.optInt("columns", 10);
        int rows = trick.optInt("rows", 10);
        int per = cols * rows;
        int idx = (int) Math.max(0, Math.floor(seconds / Math.max(interval, 0.1)));
        int count = trick.optInt("count", 0);
        if (count > 0) idx = Math.min(idx, count - 1);
        int sheet = idx / Math.max(per, 1);
        int cell = idx % Math.max(per, 1);
        Bitmap src = sheets.get(sheet);
        if (src == null) {
            final int fs = sheet;
            IO.execute(() -> {
                try {
                    JSONArray arr = trick.optJSONArray("sheets");
                    if (arr == null || fs >= arr.length()) return;
                    Bitmap bm = api.getBitmap(arr.getString(fs));
                    if (bm != null) { sheets.put(fs, bm); main.post(() -> showTrick(seconds)); }
                } catch (Exception ignored) { }
            });
            return;
        }
        int cw = src.getWidth() / cols, ch = src.getHeight() / rows;
        int cx = (cell % cols) * cw, cy = (cell / cols) * ch;
        if (cw <= 0 || ch <= 0 || cx + cw > src.getWidth() || cy + ch > src.getHeight()) return;
        try {
            trickView.setImageBitmap(Bitmap.createBitmap(src, cx, cy, cw, ch));
            trickView.setVisibility(View.VISIBLE);
        } catch (Exception ignored) { }
    }

    // ---- progress / keys / lifecycle ----
    private void saveProgress(boolean forceEnded) {
        if (player == null || itemId == 0) return;
        long d = player.getDuration();
        long p = player.getCurrentPosition();
        if (d <= 0 && !forceEnded) return;
        final boolean endedNow = forceEnded || ended;
        final double pos = p / 1000.0, dur = d > 0 ? d / 1000.0 : item != null ? item.optDouble("duration", 0) : 0;
        IO.execute(() -> {
            try {
                JSONObject b = new JSONObject();
                b.put("position", endedNow ? dur : pos);
                b.put("duration", dur);
                if (endedNow) b.put("ended", true);
                api.postJson("/api/items/" + itemId + "/progress", b);
            } catch (Exception ignored) { }
        });
    }

    @Override
    public boolean dispatchTouchEvent(MotionEvent ev) {
        if (pincher != null) pincher.onTouchEvent(ev);
        if (ev.getActionMasked() == MotionEvent.ACTION_DOWN) pinchHandled = false;
        if (gestures != null && !pinchHandled) gestures.onTouchEvent(ev);
        return super.dispatchTouchEvent(ev);
    }

    @Override
    public boolean onKeyDown(int key, KeyEvent e) {

        if (key == KeyEvent.KEYCODE_BACK) {
            if (menuOpen()) { hideMenu(); return true; }
            if (upNext.getVisibility() == View.VISIBLE) { cancelUpNext(); return true; }
            if (chromeOn) { setChrome(false); return true; }
            finish();
            return true;
        }
        if (key == KeyEvent.KEYCODE_DPAD_CENTER || key == KeyEvent.KEYCODE_ENTER || key == KeyEvent.KEYCODE_NUMPAD_ENTER
            || key == KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE) {
            if (!chromeOn && upNext.getVisibility() != View.VISIBLE && btnIntro.getVisibility() != View.VISIBLE
                && btnCredits.getVisibility() != View.VISIBLE) {
                showChrome();
                btnPlay.requestFocus();
                return true;
            }
        }
        if (key == KeyEvent.KEYCODE_MEDIA_PLAY) { if (player != null) player.play(); showChrome(); return true; }
        if (key == KeyEvent.KEYCODE_MEDIA_PAUSE) { if (player != null) player.pause(); showChrome(); return true; }
        if (key == KeyEvent.KEYCODE_MEDIA_FAST_FORWARD || key == KeyEvent.KEYCODE_MEDIA_SKIP_FORWARD) { seekBy(10_000); return true; }
        if (key == KeyEvent.KEYCODE_MEDIA_REWIND || key == KeyEvent.KEYCODE_MEDIA_SKIP_BACKWARD) { seekBy(-10_000); return true; }
        if (key == KeyEvent.KEYCODE_DPAD_LEFT && seek.hasFocus()) { seekBy(-10_000); return true; }
        if (key == KeyEvent.KEYCODE_DPAD_RIGHT && seek.hasFocus()) { seekBy(10_000); return true; }
        if (!chromeOn && (key == KeyEvent.KEYCODE_DPAD_UP || key == KeyEvent.KEYCODE_DPAD_DOWN
            || key == KeyEvent.KEYCODE_DPAD_LEFT || key == KeyEvent.KEYCODE_DPAD_RIGHT)) {
            showChrome();
            return true;
        }
        return super.onKeyDown(key, e);
    }

    @SuppressWarnings("deprecation")
    private void immersive() {
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController c = getWindow().getInsetsController();
            if (c != null) { c.hide(WindowInsets.Type.systemBars()); c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE); }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
        }
    }

    @Override public void onUserLeaveHint() {
        super.onUserLeaveHint();
        if (Build.VERSION.SDK_INT >= 26 && player != null && player.isPlaying()
            && getPackageManager().hasSystemFeature(PackageManager.FEATURE_PICTURE_IN_PICTURE)) {
            try {
                enterPictureInPictureMode(new PictureInPictureParams.Builder()
                    .setAspectRatio(new Rational(16, 9)).build());
            } catch (Exception ignored) { }
        }
    }

    @Override public void onPictureInPictureModeChanged(boolean in, android.content.res.Configuration cfg) {
        super.onPictureInPictureModeChanged(in, cfg);
        if (in) setChrome(false);
        else { immersive(); showChrome(); }
    }

    @Override protected void onResume() { super.onResume(); immersive(); main.post(tick); main.postDelayed(save, 10000); }
    @Override protected void onPause() {
        super.onPause();
        main.removeCallbacks(tick);
        main.removeCallbacks(save);
        saveProgress(false);
        if (Build.VERSION.SDK_INT < 24 || !isInPictureInPictureMode()) {
            if (player != null) player.pause();
        }
    }

    @Override
    protected void onDestroy() {
        main.removeCallbacksAndMessages(null);
        saveProgress(ended);
        if (player != null) { player.release(); player = null; }
        for (Bitmap bm : sheets.values()) { if (bm != null && !bm.isRecycled()) bm.recycle(); }
        sheets.clear();
        super.onDestroy();
    }

    private static String fmt(long ms) {
        long s = Math.max(0, ms / 1000);
        long h = s / 3600, m = (s % 3600) / 60, sec = s % 60;
        return h > 0 ? String.format(Locale.US, "%d:%02d:%02d", h, m, sec)
                     : String.format(Locale.US, "%d:%02d", m, sec);
    }
}
