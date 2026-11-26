package org.movinite.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/**
 * 2.0 offline mode: no connection to the server. Unlock (fingerprint / face / screen lock, then the Movinite PIN if set),
 * then a bundled page lists the downloads through the same bridge as the online Downloads tab and plays them.
 */
public class OfflineActivity extends Activity {
    private WebView web;
    private Bridge bridge;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        Offline off = Offline.get(this);
        if (off.windowExpired()) off.wipe("offline for too long");
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        web = new WebView(this);
        web.setBackgroundColor(getColor(R.color.bg));
        setContentView(web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(false);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setBlockNetworkLoads(true);           // the offline page never touches the network
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) { return true; }
        });
        bridge = new Bridge();
        bridge.attach(web);
        web.addJavascriptInterface(bridge, "MSAndroid");
        String html;
        try (InputStream in = getAssets().open("offline.html")) { html = new String(Offline.readAll(in), StandardCharsets.UTF_8); }
        catch (Exception e) { html = "<p>Offline page missing</p>"; }
        web.loadDataWithBaseURL("https://offline.movinite.invalid/", html, "text/html", "utf-8", null);
    }

    private void signIn() {
        if (!Offline.get(this).registered()) { bridge.js("window.__offState&&window.__offState('none')"); return; }
        if (Offline.unlocked) { bridge.js("window.__offState&&window.__offState('unlocked')"); return; }
        Unlock.offlineSignIn(this, (ok, why) -> {
            if (ok) Offline.unlocked = true;
            bridge.js("window.__offState&&window.__offState(" + org.json.JSONObject.quote(ok ? "unlocked" : (why == null ? "locked" : why)) + ")");
        });
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        if (!Unlock.onResult(this, req, res)) super.onActivityResult(req, res, data);
    }

    @Override
    protected void onDestroy() {
        if (bridge != null) bridge.detach();
        if (web != null) { web.destroy(); web = null; }
        super.onDestroy();
    }

    private class Bridge extends OfflineBridge {
        Bridge() { super(OfflineActivity.this, true); }
        @JavascriptInterface public void unlock() { runOnUiThread(OfflineActivity.this::signIn); }
        @JavascriptInterface public boolean unlocked() { return Offline.unlocked; }
        @Override @JavascriptInterface public String downloads() { return Offline.unlocked ? super.downloads() : "[]"; }
        @JavascriptInterface public boolean online() { return Offline.get(OfflineActivity.this).online(); }
        /** "Try again": back to the normal app when the connection is back */
        @JavascriptInterface public void reconnect() {
            runOnUiThread(() -> {
                startActivity(new Intent(OfflineActivity.this, MainActivity.class).setAction(MainActivity.ACTION_OPEN)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
                finish();
            });
        }
        @JavascriptInterface public void signOutAll() { new Thread(() -> { Offline.get(OfflineActivity.this).wipe("signed out offline"); bridge.js("window.__offState&&window.__offState('none')"); }).start(); }
        @Override @JavascriptInterface public void playOffline(long gid) {
            runOnUiThread(() -> { if (Offline.unlocked) OfflinePlayerActivity.start(OfflineActivity.this, gid, false); else signIn(); });
        }
    }
}
