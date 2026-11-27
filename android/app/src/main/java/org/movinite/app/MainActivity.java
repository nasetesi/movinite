package org.movinite.app;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.app.PictureInPictureParams;
import android.content.res.Configuration;
import android.util.Rational;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.view.OrientationEventListener;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.SslErrorHandler;
import android.webkit.URLUtil;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import java.io.ByteArrayInputStream;

/**
 * Movinite for Android (package org.movinite.app): a full-screen WebView around the Movinite web app.
 * - Signed out (no ms_session cookie, web sign-out, or an expired session): the native LoginActivity; the web sign-in page is never shown.
 * - Back: closes the video player / side menu, then goes back in the web history; on Home it offers Exit / Reload / Sign out.
 * - Long-press the app icon for "Server settings" and "Reload" shortcuts.
 * - Links to other sites open in the browser; downloads go through Android's Download manager (with the login cookie).
 * - 1.3: picture-in-picture (Android 8+): the player's PiP button, or Home while a film plays, shrinks the film into a
 *   small window; the web app shows only the picture there. Closing the PiP window pauses the film.
 * - 1.4: while the player is open the app follows the phone's rotation; sideways = immersive full screen (status and
 *   navigation bars hidden, the web player goes full screen), upright = bars back. The full-screen button while upright
 *   turns the picture sideways until the phone is actually turned, then rotation is free again.
 */
public class MainActivity extends Activity {
    static final String ACTION_OPEN = "org.movinite.app.OPEN";
    static final String ACTION_SETTINGS = "org.movinite.app.SERVER_SETTINGS";
    static final String ACTION_RELOAD = "org.movinite.app.RELOAD";
    static final String ACTION_DOWNLOADS = "org.movinite.app.DOWNLOADS";
    private static final int REQ_STORAGE = 7;
    static final int REQ_NATIVE_PLAY = 243;

    private WebView web;
    private View loading, error, fullscreenBox;
    private TextView errorText, loadingText;
    private ProgressBar progress;
    private String server;            // e.g. https://movies.example.com
    private boolean firstLoadDone = false;
    private boolean mainFrameFailed = false;
    private View customView;
    private WebChromeClient.CustomViewCallback customCallback;
    private Runnable pendingDownload;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        server = Prefs.serverUrl(this);
        if (server == null) {                     // first launch: ask for the server address, then sign in
            startActivity(SetupActivity.firstRun(this));
            finish();
            return;
        }

        // 2.0: offline downloads -- the offline window is over: remove them; no connection: the offline screen
        Offline off = Offline.get(this);
        if (off.windowExpired()) off.wipe("offline for too long");
        if (off.registered() && !off.online()) { startActivity(new Intent(this, OfflineActivity.class)); finish(); return; }
        if (!Session.signedIn(server)) {
            // 2.0.2: on a television, load the web sign-in (short code + QR). Phones still use the native form.
            // The gear / Server settings action still opens Setup, then the native form.
            if (ACTION_SETTINGS.equals(getIntent().getAction())) {
                Intent login = new Intent(this, LoginActivity.class);
                startActivities(new Intent[]{login, new Intent(this, SetupActivity.class)});
                finish();
                return;
            }
            if (!isTelevision()) {
                startActivity(new Intent(this, LoginActivity.class));
                finish();
                return;
            }
        }
        setContentView(R.layout.activity_main);
        web = findViewById(R.id.web);
        loading = findViewById(R.id.loading);
        loadingText = findViewById(R.id.loading_text);
        error = findViewById(R.id.error);
        errorText = findViewById(R.id.error_text);
        progress = findViewById(R.id.progress);
        fullscreenBox = findViewById(R.id.fullscreen);
        findViewById(R.id.retry).setOnClickListener(v -> retry());
        findViewById(R.id.change_server).setOnClickListener(v -> openSettings());
        findViewById(R.id.offline_btn).setOnClickListener(v -> { startActivity(new Intent(this, OfflineActivity.class)); finish(); });

        if ((getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0) WebView.setWebContentsDebuggingEnabled(true);   // debug builds only
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);          // localStorage: sound settings, quality choice ...
        s.setDatabaseEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setSupportMultipleWindows(false);    // target=_blank -> handled in shouldOverrideUrlLoading
        s.setJavaScriptCanOpenWindowsAutomatically(false);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        if (isTelevision()) s.setTextZoom(100); // 1.9.2 / 2.0: TVs (4K) ignore the system font scale so the 1920-wide layout isn't zoomed in; phones keep the user's font size
        s.setSupportZoom(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        String agent = s.getUserAgentString() + " MediaServerAndroid/" + BuildConfigInfo.VERSION;
        if (isTelevision()) agent += " AndroidTV";      // 1.9.1 web app: TV / D-pad navigation
        s.setUserAgentString(agent);
        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);               // the login cookie survives app restarts
        cm.setAcceptThirdPartyCookies(web, false);
        web.setBackgroundColor(getColor(R.color.bg));
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new Chrome());
        bridge = new Bridge();
        bridge.attach(web);
        web.addJavascriptInterface(bridge, "MSAndroid");
        web.setFocusable(true);
        web.setFocusableInTouchMode(true);
        web.requestFocus();
        web.setDownloadListener((url, ua, disposition, mime, length) -> download(url, ua, disposition, mime));

        if (b != null && web.restoreState(b) != null) { firstLoadDone = true; loading.setVisibility(View.GONE); }
        else load(server);
        handleIntent(getIntent());
        if (off.registered()) { off.syncSoon(); off.schedulePeriodicSync(); healthCheck(); }
    }

    private Bridge bridge;

    boolean isTelevision() {
        return (getResources().getConfiguration().uiMode & Configuration.UI_MODE_TYPE_MASK) == Configuration.UI_MODE_TYPE_TELEVISION;
    }

    /** 2.0: the server doesn't answer within 3 s and this phone has downloads: offer them straight away */
    private void healthCheck() {
        final String base = server;
        new Thread(() -> {
            boolean ok;
            try {
                java.net.HttpURLConnection c = (java.net.HttpURLConnection) new java.net.URL(base + "/api/health").openConnection();
                c.setConnectTimeout(3000); c.setReadTimeout(3000);
                ok = c.getResponseCode() < 500; c.disconnect();
            } catch (Exception e) { ok = false; }
            if (!ok) runOnUiThread(() -> {
                if (web == null || leaving || firstLoadDone) return;
                if (Offline.get(this).hasDownloads()) { startActivity(new Intent(this, OfflineActivity.class)); finish(); }
            });
        }).start();
    }

    private void load(String url) {
        mainFrameFailed = false;
        error.setVisibility(View.GONE);
        if (!firstLoadDone) { loadingText.setText("Connecting to " + Uri.parse(server).getHost() + " ..."); loading.setVisibility(View.VISIBLE); }
        web.loadUrl(url);
    }

    private void retry() {
        firstLoadDone = false;
        String cur = web.getUrl();
        load(cur != null && Prefs.sameOrigin(server, Uri.parse(cur)) ? cur : server);
    }

    private void openSettings() { startActivity(new Intent(this, SetupActivity.class)); }

    @Override
    protected void onNewIntent(Intent i) { super.onNewIntent(i); setIntent(i); handleIntent(i); }

    private void handleIntent(Intent i) {
        if (i == null || web == null) return;
        String a = i.getAction();
        if (ACTION_SETTINGS.equals(a)) { i.setAction(Intent.ACTION_MAIN); openSettings(); }
        else if (ACTION_RELOAD.equals(a)) { i.setAction(Intent.ACTION_MAIN); retry(); }
        else if (ACTION_OPEN.equals(a)) { i.setAction(Intent.ACTION_MAIN); }
        else if (ACTION_DOWNLOADS.equals(a)) { i.setAction(Intent.ACTION_MAIN); web.evaluateJavascript("location.hash='#/downloads'", null); }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (web == null) return;
        String now = Prefs.serverUrl(this);
        if (now != null && !now.equals(server)) {   // server changed in Server settings
            server = now;
            if (!Session.signedIn(server) && !isTelevision()) { toLogin(null); return; }
            firstLoadDone = false; web.clearHistory(); load(server);
        }
    }

    @Override
    protected void onPause() { super.onPause(); CookieManager.getInstance().flush(); }

    // ---------------------------------------------------------------- 1.3: picture in picture
    private volatile boolean filmPlaying = false;
    private Rational aspect = new Rational(16, 9);

    private boolean pipSupported() {
        return Build.VERSION.SDK_INT >= 26 && getPackageManager().hasSystemFeature(PackageManager.FEATURE_PICTURE_IN_PICTURE);
    }

    private PictureInPictureParams pipParams() {
        PictureInPictureParams.Builder p = new PictureInPictureParams.Builder().setAspectRatio(aspect);
        if (Build.VERSION.SDK_INT >= 31) p.setAutoEnterEnabled(filmPlaying).setSeamlessResizeEnabled(true);   // Android 12+: Home goes straight to PiP
        return p.build();
    }

    private void updatePip() {
        if (!pipSupported()) return;
        try { setPictureInPictureParams(pipParams()); } catch (Exception ignored) { }
    }

    private void enterPip() {
        if (!pipSupported() || web == null) return;
        if (Build.VERSION.SDK_INT >= 26 && isInPictureInPictureMode()) return;
        try { enterPictureInPictureMode(pipParams()); }
        catch (Exception e) { Toast.makeText(this, "Picture-in-picture is turned off for this app in Android settings", Toast.LENGTH_LONG).show(); }
    }

    /** keeps the PiP window the shape of the film (Android allows 1:2.39 to 2.39:1) */
    private void setAspect(int w, int h) {
        if (w <= 0 || h <= 0) return;
        double r = (double) w / h;
        if (r > 2.39) { w = 239; h = 100; } else if (r < 1 / 2.39) { w = 100; h = 239; }
        aspect = new Rational(w, h);
    }

    @Override
    protected void onUserLeaveHint() {           // Home / Recents while a film plays (Android 8-11; 12+ uses auto-enter)
        super.onUserLeaveHint();
        if (filmPlaying && Build.VERSION.SDK_INT >= 26 && Build.VERSION.SDK_INT < 31) enterPip();
    }

    @Override
    public void onPictureInPictureModeChanged(boolean inPip, Configuration cfg) {
        super.onPictureInPictureModeChanged(inPip, cfg);
        if (web != null) web.evaluateJavascript("window.__msAndroidPip&&window.__msAndroidPip(" + inPip + ")", null);
        if (!inPip) applyRotation();
    }

    @Override
    protected void onStop() {
        super.onStop();
        // the PiP window was closed (or the app left without PiP): don't keep playing a film nobody can see
        boolean inPip = Build.VERSION.SDK_INT >= 26 && isInPictureInPictureMode();
        if (!inPip && web != null) web.evaluateJavascript("(function(){var v=document.getElementById('video');if(v&&!v.paused)v.pause();})()", null);
    }

    @Override
    protected void onSaveInstanceState(Bundle out) { super.onSaveInstanceState(out); if (web != null) web.saveState(out); }

    @Override
    protected void onDestroy() {
        stopTilt();
        if (bridge != null) bridge.detach();
        if (web != null) { web.stopLoading(); web.setWebChromeClient(null); web.destroy(); web = null; }
        super.onDestroy();
    }

    // ---------------------------------------------------------------- back button
    @Override
    public void onBackPressed() {
        if (customView != null) { exitFullscreen(); return; }
        if (error.getVisibility() == View.VISIBLE || web == null) { appMenu(); return; }
        // let the web app close its video player / side menu first
        web.evaluateJavascript("(function(){try{var d=document;"
            + "if(window.__msTvBack&&window.__msTvBack())return 'closed';"
            + "var p=d.getElementById('player');"
            + "if(p&&!p.classList.contains('hidden')){var c=d.getElementById('pl-close');if(c){c.click();return 'closed';}}"
            + "var m=d.getElementById('modal');"
            + "if(m&&!m.classList.contains('hidden')&&!m.dataset.locked){m.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));"
            + "if(m.classList.contains('hidden'))return 'closed';}"
            + "var sd=d.querySelector('.side.open');if(sd){sd.classList.remove('open');return 'closed';}"
            + "var mm=d.getElementById('more-menu');if(mm&&!mm.hidden){mm.hidden=true;return 'closed';}"
            + "var am=d.getElementById('acct-menu');if(am&&!am.classList.contains('hidden')){var av=d.getElementById('m-avatar');if(av)av.click();else am.classList.add('hidden');return 'closed';}"   // 1.5: phone account menu
            + "}catch(e){}return 'no';})()", r -> {
                if (r != null && r.contains("closed")) return;
                if (web == null) return;
                String cur = web.getUrl();
                if (isHomeUrl(cur)) { appMenu(); return; }
                // never step back into the sign-in page / first load: go to Home instead
                android.webkit.WebBackForwardList h = web.copyBackForwardList();
                int i = h.getCurrentIndex();
                String prev = i > 0 ? h.getItemAtIndex(i - 1).getUrl() : null;
                if (prev != null && prev.contains("#/") && Prefs.sameOrigin(server, Uri.parse(prev))) { web.goBack(); return; }
                web.evaluateJavascript("location.hash='#/home'", null);
            });
    }

    /** Home = the start page: no "#/" route, or "#/home". */
    private static boolean isHomeUrl(String u) {
        if (u == null) return true;
        int k = u.indexOf('#');
        if (k < 0) return true;
        String f = u.substring(k + 1);
        return f.isEmpty() || f.equals("/") || f.equals("/home");
    }

    private void appMenu() {
        String host = Uri.parse(server).getHost();
        new AlertDialog.Builder(this)
            .setTitle(getString(R.string.app_name))
            .setMessage((signedInAs != null ? "Signed in as " + signedInAs + "\n" : "") + "Connected to " + host)
            .setPositiveButton("Exit", (d, w) -> finish())
            .setNeutralButton("Reload", (d, w) -> retry())
            .setNegativeButton("Sign out", (d, w) -> signOut())
            .show();
    }

    // ---------------------------------------------------------------- sign-in state (native login screen instead of the web one)
    private String signedInAs = null;
    private boolean webReady = false;
    private boolean leaving = false;

    /** Watches the web app: "ready" (Home shown), "login" (its sign-in form: signed out or session expired), "other" (e.g. first-run setup).
     *  The web sign-in form is hidden with CSS so it is never seen; the native screen replaces it. */
    private static final String WATCH_JS = "(function(){try{if(window.__msWatch)return;window.__msWatch=1;var d=document;"
        + "var st=d.createElement('style');st.textContent='#auth #loginf{visibility:hidden!important}';(d.head||d.documentElement).appendChild(st);"
        + "var last='';function chk(){var a=d.getElementById('auth'),s=d.getElementById('shell'),v='';"
        + "if(d.getElementById('loginf'))v='login';else if(s&&!s.classList.contains('hidden'))v='ready';"
        + "else if(a&&!a.classList.contains('hidden')&&a.innerHTML.trim())v='other';"
        + "if(v&&v!==last){last=v;var w=d.getElementById('whoami');MSAndroid.state(v,w?w.textContent:'');}}"
        + "var mo=new MutationObserver(chk);var a=d.getElementById('auth'),s=d.getElementById('shell');"
        + "if(a)mo.observe(a,{childList:true,attributes:true,attributeFilter:['class']});"
        + "if(s)mo.observe(s,{attributes:true,attributeFilter:['class']});chk();"
        + "d.addEventListener('click',function(e){var t=e.target&&e.target.closest&&e.target.closest('#logout');if(t&&MSAndroid.signingOut)MSAndroid.signingOut();},true);"
        + "}catch(e){}})()";

    private class Bridge extends OfflineBridge {
        Bridge() { super(MainActivity.this, false); }
        /** 1.9.1: the web app's TV mode */
        @android.webkit.JavascriptInterface
        public boolean isTv() { return isTelevision(); }
        /** 2.0: the web Sign out link was pressed: this phone's downloads and keys go too */
        @android.webkit.JavascriptInterface
        public void signingOut() { new Thread(() -> Offline.get(MainActivity.this).signOut()).start(); }
        @android.webkit.JavascriptInterface
        public void state(String v, String who) {
            runOnUiThread(() -> onWebState(v, who));
        }
        /** 1.3: is picture-in-picture possible on this phone (Android 8+, not turned off)? */
        @android.webkit.JavascriptInterface
        public boolean pipAvailable() { return pipSupported(); }
        /** 1.3: the player's PiP button */
        @android.webkit.JavascriptInterface
        public void pip(int w, int h) { runOnUiThread(() -> { setAspect(w, h); enterPip(); }); }
        /** 1.3: the web player reports play / pause (and the film's size) so Home can go to PiP */
        @android.webkit.JavascriptInterface
        public void playing(boolean on, int w, int h) { runOnUiThread(() -> { filmPlaying = on; setAspect(w, h); updatePip(); }); }
        /** 1.4: the web player opened / closed: follow the phone's rotation only while it is open */
        @android.webkit.JavascriptInterface
        public void player(boolean open) { runOnUiThread(() -> setPlayerOpen(open)); }
        /** 2.4: real MediaCodec / AudioCapabilities / display HDR modes, for Direct Play decisions. */
        @android.webkit.JavascriptInterface
        public String decoderCaps() { return Caps.detect(MainActivity.this).toString(); }
        /** 2.4: hand Play over to the native ExoPlayer. Session cookie stays in the WebView cookie store. */
        @android.webkit.JavascriptInterface
        public String playNative(String json) {
            try {
                final String payload = json == null ? "{}" : json;
                runOnUiThread(() -> PlayerActivity.startFromJs(MainActivity.this, payload));
                return "{\"ok\":true}";
            } catch (Exception e) {
                return "{\"ok\":false}";
            }
        }
    }

    @Override
    protected void onActivityResult(int req, int result, Intent data) {
        super.onActivityResult(req, result, data);
        if (req != REQ_NATIVE_PLAY || data == null) return;
        if (!PlayFallback.WEB.equals(data.getStringExtra(PlayerActivity.EXTRA_FALLBACK))) return;
        long id = data.getLongExtra(PlayerActivity.EXTRA_ITEM, 0);
        double start = data.getDoubleExtra(PlayerActivity.EXTRA_START, 0);
        if (id == 0 || web == null) return;
        web.evaluateJavascript("playInWebPlayer(" + id + "," + start + ")", null);
    }

    // ---------------------------------------------------------------- 1.4: rotate = full screen
    private boolean playerOpen = false, landLock = false;
    private OrientationEventListener tilt;

    private boolean isLandscape() { return getResources().getConfiguration().orientation == Configuration.ORIENTATION_LANDSCAPE; }

    private void setPlayerOpen(boolean open) {
        if (playerOpen == open) return;
        playerOpen = open;
        if (open) {
            if (!landLock) setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_FULL_SENSOR);
            applyRotation();
        } else {
            landLock = false; stopTilt();
            if (customView == null) {
                setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
                setSystemBars(true);
                getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            }
        }
    }

    /** sideways with the player open (or a full-screen video): hide the bars; upright: show them again */
    private void applyRotation() {
        boolean inPip = Build.VERSION.SDK_INT >= 26 && isInPictureInPictureMode();
        if (inPip) return;
        boolean immersive = customView != null || (playerOpen && isLandscape());
        setSystemBars(!immersive);
        if (playerOpen || customView != null) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    @Override
    public void onConfigurationChanged(Configuration cfg) {
        super.onConfigurationChanged(cfg);
        applyRotation();
    }

    /** the full-screen button while upright locks sideways; once the phone is really turned, rotation is free again */
    private void startTilt() {
        if (tilt == null) tilt = new OrientationEventListener(this) {
            @Override public void onOrientationChanged(int deg) {
                if (!landLock || deg == ORIENTATION_UNKNOWN) return;
                if ((deg > 60 && deg < 120) || (deg > 240 && deg < 300)) {
                    landLock = false; stopTilt();
                    setRequestedOrientation(playerOpen || customView != null ? ActivityInfo.SCREEN_ORIENTATION_FULL_SENSOR : ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
                }
            }
        };
        if (tilt.canDetectOrientation()) tilt.enable(); else { landLock = false; }
    }
    private void stopTilt() { if (tilt != null) tilt.disable(); }

    private void onWebState(String v, String who) {
        if (web == null || leaving) return;
        String cur = web.getUrl();
        if (cur == null || !Prefs.sameOrigin(server, Uri.parse(cur))) return;   // only our own server's page
        if ("ready".equals(v) || "other".equals(v)) {
            if ("ready".equals(v)) { webReady = true; if (who != null && !who.isEmpty()) signedInAs = who; }
            firstLoadDone = true; loading.setVisibility(View.GONE);
            if (web != null) web.requestFocus();
            return;
        }
        if ("login".equals(v)) {
            loading.setVisibility(View.VISIBLE);       // cover the (hidden) web form
            loadingText.setText("Signing out ...");
            final boolean wasReady = webReady;
            final String cookie = CookieManager.getInstance().getCookie(server);
            new Thread(() -> {                      // make sure it's really a sign-out, not a server hiccup
                int code;
                try {
                    java.net.HttpURLConnection c = (java.net.HttpURLConnection) new java.net.URL(server + "/api/me").openConnection();
                    c.setConnectTimeout(8000); c.setReadTimeout(8000);
                    if (cookie != null) c.setRequestProperty("Cookie", cookie);
                    code = c.getResponseCode(); c.disconnect();
                } catch (Exception e) { code = -1; }
                final int fc = code;
                runOnUiThread(() -> {
                    if (web == null || leaving) return;
                    if (fc == 401 || fc == 403) toLogin(wasReady ? "You've been signed out." : "Your session has ended. Please sign in again.");
                    else if (fc == 200) { loading.setVisibility(View.GONE); retry(); }
                    else showError(fc < 0 ? "No connection to the server" : "The server answered HTTP " + fc);
                });
            }).start();
        }
    }

    private void toLogin(String message) {
        if (leaving) return;
        // 2.0.2: a television stays in the WebView and reloads the code-and-QR sign-in.
        if (isTelevision() && web != null && server != null) {
            Session.clear(server);
            leaving = false;
            firstLoadDone = false;
            load(server);
            return;
        }
        leaving = true;
        Session.clear(server);
        Intent i = new Intent(this, LoginActivity.class);
        if (message != null) i.putExtra(LoginActivity.EXTRA_MESSAGE, message);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        startActivity(i);
        finish();
    }

    /** same as the web app's Sign out link: ends the session on the server, then the watcher brings up the native screen */
    private void signOut() {
        if (web == null) return;
        new Thread(() -> Offline.get(this).signOut()).start();     // 2.0: downloads and keys go with the account
        web.evaluateJavascript("(function(){var l=document.getElementById('logout');if(l){l.click();return 'ok';}return 'no';})()", r -> {
            if (r == null || !r.contains("ok")) toLogin(null);
            else ui.postDelayed(() -> { if (!leaving) toLogin("You've been signed out."); }, 4000);   // fallback
        });
    }
    private final android.os.Handler ui = new android.os.Handler(android.os.Looper.getMainLooper());

    // ---------------------------------------------------------------- downloads (admin "Download file")
    private void download(String url, String ua, String disposition, String mime) {
        Runnable go = () -> {
            try {
                DownloadManager.Request r = new DownloadManager.Request(Uri.parse(url));
                String name = URLUtil.guessFileName(url, disposition, mime);
                String cookie = CookieManager.getInstance().getCookie(url);
                if (cookie != null) r.addRequestHeader("Cookie", cookie);
                r.addRequestHeader("User-Agent", ua);
                r.setTitle(name);
                r.setDescription("Movinite download");
                r.setMimeType(mime);
                r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                r.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
                ((DownloadManager) getSystemService(DOWNLOAD_SERVICE)).enqueue(r);
                Toast.makeText(this, "Downloading " + name, Toast.LENGTH_SHORT).show();
            } catch (Exception e) {
                Toast.makeText(this, "Download failed: " + e.getMessage(), Toast.LENGTH_LONG).show();
            }
        };
        if (Build.VERSION.SDK_INT < 29 && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            pendingDownload = go;
            requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, REQ_STORAGE);
        } else go.run();
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        super.onRequestPermissionsResult(code, perms, res);
        if (code == REQ_STORAGE && pendingDownload != null) {
            if (res.length > 0 && res[0] == PackageManager.PERMISSION_GRANTED) pendingDownload.run();
            else Toast.makeText(this, "Storage permission is needed to save downloads", Toast.LENGTH_LONG).show();
            pendingDownload = null;
        }
    }

    // ---------------------------------------------------------------- full-screen video
    private void enterFullscreen(View v, WebChromeClient.CustomViewCallback cb) {
        if (customView != null) { cb.onCustomViewHidden(); return; }
        customView = v; customCallback = cb;
        ((FrameLayout) fullscreenBox).addView(v, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        fullscreenBox.setVisibility(View.VISIBLE);
        web.setVisibility(View.INVISIBLE);
        setSystemBars(false);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (isLandscape()) setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_FULL_SENSOR);   // turned sideways: keep following the phone
        else { landLock = true; setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE); startTilt(); }   // button while upright
    }

    private void exitFullscreen() {
        if (customView == null) return;
        ((FrameLayout) fullscreenBox).removeView(customView);
        fullscreenBox.setVisibility(View.GONE);
        web.setVisibility(View.VISIBLE);
        customView = null;
        if (customCallback != null) customCallback.onCustomViewHidden();
        customCallback = null;
        landLock = false; stopTilt();
        if (playerOpen) { setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_FULL_SENSOR); applyRotation(); }
        else {
            setSystemBars(true);
            getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
        }
    }

    @SuppressWarnings("deprecation")
    private void setSystemBars(boolean show) {
        Window w = getWindow();
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController c = w.getInsetsController();
            if (c == null) return;
            if (show) c.show(WindowInsets.Type.systemBars());
            else { c.hide(WindowInsets.Type.systemBars()); c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE); }
        } else {
            w.getDecorView().setSystemUiVisibility(show ? View.SYSTEM_UI_FLAG_VISIBLE
                : View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                  | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
        }
    }

    private void showError(String why) {
        mainFrameFailed = true;
        loading.setVisibility(View.GONE);
        progress.setVisibility(View.GONE);
        errorText.setText(Uri.parse(server).getHost() + "\n" + why + "\n\nCheck your connection, or that the server is on.");
        findViewById(R.id.offline_btn).setVisibility(Offline.get(this).hasDownloads() ? View.VISIBLE : View.GONE);
        error.setVisibility(View.VISIBLE);
    }

    // ---------------------------------------------------------------- WebView clients
    private class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest req) {
            Uri u = req.getUrl();
            String sc = u.getScheme() == null ? "" : u.getScheme().toLowerCase();
            if ((sc.equals("http") || sc.equals("https")) && Prefs.sameOrigin(server, u)) return false;   // our server
            try {   // TMDB and any other site -> the phone's browser; mailto:, intent: ... -> their apps
                Intent i = sc.equals("intent") ? Intent.parseUri(u.toString(), Intent.URI_INTENT_SCHEME) : new Intent(Intent.ACTION_VIEW, u);
                i.addCategory(Intent.CATEGORY_BROWSABLE);
                startActivity(i);
            } catch (ActivityNotFoundException | java.net.URISyntaxException e) {
                Toast.makeText(MainActivity.this, "No app can open this link", Toast.LENGTH_SHORT).show();
            }
            return true;
        }

        @Override
        public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest req) {
            // plain http only for the server the user entered (the LAN address); block it for anything else
            Uri u = req.getUrl();
            if ("http".equalsIgnoreCase(u.getScheme()) && !Prefs.sameOrigin(server, u))
                return new WebResourceResponse("text/plain", "utf-8", 403, "Blocked", null, new ByteArrayInputStream(new byte[0]));
            return null;
        }

        @Override
        public void onPageStarted(WebView v, String url, Bitmap fav) { progress.setVisibility(View.VISIBLE); }

        @Override
        public void onPageFinished(WebView v, String url) {
            progress.setVisibility(View.GONE);
            CookieManager.getInstance().flush();
            if (mainFrameFailed) return;
            error.setVisibility(View.GONE);
            v.evaluateJavascript(WATCH_JS, null);
            // the watcher reveals the page; fall back after a few seconds in case this isn't the usual web app
            if (!firstLoadDone) ui.postDelayed(() -> { if (!mainFrameFailed && !leaving && web != null) { firstLoadDone = true; loading.setVisibility(View.GONE); } }, 8000);
        }

        @Override
        public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
            if (req.isForMainFrame()) showError(String.valueOf(err.getDescription()));
        }

        @Override
        public void onReceivedHttpError(WebView v, WebResourceRequest req, WebResourceResponse resp) {
            if (req.isForMainFrame() && resp.getStatusCode() >= 500) showError("The server answered HTTP " + resp.getStatusCode());
        }

        @Override
        public void onReceivedSslError(WebView v, SslErrorHandler h, SslError e) {
            h.cancel();     // never accept a bad certificate
            showError("The server's security certificate isn't valid");
        }
    }

    private class Chrome extends WebChromeClient {
        @Override public void onShowCustomView(View view, CustomViewCallback cb) { enterFullscreen(view, cb); }
        @Override public void onHideCustomView() { exitFullscreen(); }
        @Override public void onProgressChanged(WebView v, int p) { progress.setProgress(p); }
        @Override public Bitmap getDefaultVideoPoster() { return Bitmap.createBitmap(1, 1, Bitmap.Config.ARGB_8888); }  // no grey play icon
    }
}
