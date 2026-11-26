package org.movinite.app;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.webkit.CookieManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ProgressBar;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

import javax.net.ssl.SSLException;

/**
 * Native sign-in screen. Posts the username and password to the server's /api/login (the same call the web page makes),
 * puts the returned ms_session cookie into the WebView's cookie store and opens Home. The password is never saved.
 * The gear at the top right (or a long-press on the logo) opens Server settings (advanced: a LAN address instead of https://movies.example.com).
 */
public class LoginActivity extends Activity {
    static final String EXTRA_MESSAGE = "message";

    private EditText user, pass;
    private TextView error, show, serverLine;
    private Button signIn;
    private ProgressBar busy;
    private String server;
    private boolean shown = false;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private volatile int attempt = 0;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        setContentView(R.layout.activity_login);
        user = findViewById(R.id.username);
        pass = findViewById(R.id.password);
        error = findViewById(R.id.error);
        show = findViewById(R.id.show);
        signIn = findViewById(R.id.signin);
        busy = findViewById(R.id.busy);
        serverLine = findViewById(R.id.server_line);
        findViewById(R.id.gear).setOnClickListener(v -> openSettings());                                  // top-right gear
        findViewById(R.id.logo).setOnLongClickListener(v -> { openSettings(); return true; });            // older shortcut, kept
        Insets.keepBelowStatusBar(findViewById(R.id.login_root), findViewById(R.id.gear));
        fitCard();
        show.setOnClickListener(v -> togglePassword());
        signIn.setOnClickListener(v -> submit());
        user.setOnEditorActionListener((v, id, ev) -> {
            if (id == EditorInfo.IME_ACTION_NEXT) { pass.requestFocus(); return true; }
            return false;
        });
        pass.setOnEditorActionListener((v, id, ev) -> {
            if (id == EditorInfo.IME_ACTION_DONE || (ev != null && ev.getKeyCode() == KeyEvent.KEYCODE_ENTER)) { submit(); return true; }
            return false;
        });
        String msg = getIntent().getStringExtra(EXTRA_MESSAGE);
        if (msg != null) { error.setText(msg); error.setTextColor(getColor(R.color.muted)); }
    }

    @Override
    protected void onResume() {
        super.onResume();
        server = Prefs.serverUrl(this);           // may have changed in Server settings
        if (server == null) { startActivity(SetupActivity.firstRun(this)); finish(); return; }
        if (Session.signedIn(server)) { openHome(); return; }
        boolean custom = server != null;
        serverLine.setText(custom ? "Server: " + server : "");
        serverLine.setVisibility(custom ? View.VISIBLE : View.GONE);
    }

    /** 1.5: like the web page's .auth-box -- full width on a phone, at most 380 dp wide on tablets / in landscape. */
    private void fitCard() {
        final View card = findViewById(R.id.card);
        final float dp = getResources().getDisplayMetrics().density;
        card.addOnLayoutChangeListener((v, l, t, r, bt, ol, ot, or, ob) -> {
            View parent = (View) v.getParent();
            int avail = parent.getWidth() - parent.getPaddingLeft() - parent.getPaddingRight();
            int want = Math.min(avail, Math.round(380 * dp));
            android.view.ViewGroup.LayoutParams lp = v.getLayoutParams();
            if (want > 0 && lp.width != want) { lp.width = want; v.post(() -> v.setLayoutParams(lp)); }
        });
    }

    @Override
    public void onConfigurationChanged(android.content.res.Configuration c) {
        super.onConfigurationChanged(c);
        View card = findViewById(R.id.card);
        if (card != null) { card.getLayoutParams().width = android.view.ViewGroup.LayoutParams.MATCH_PARENT; card.requestLayout(); }
    }

    private void openSettings() { startActivity(new Intent(this, SetupActivity.class)); }

    private void togglePassword() {
        shown = !shown;
        int sel = pass.getSelectionEnd();
        pass.setInputType(InputType.TYPE_CLASS_TEXT | (shown ? InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD : InputType.TYPE_TEXT_VARIATION_PASSWORD));
        pass.setSelection(Math.max(0, Math.min(sel, pass.getText().length())));
        show.setText(shown ? "Hide" : "Show");
        show.setContentDescription(shown ? "Hide password" : "Show password");
    }

    private void setBusy(boolean on) {
        signIn.setEnabled(!on); user.setEnabled(!on); pass.setEnabled(!on);
        signIn.setText(on ? "Signing in..." : "Sign in");
        busy.setVisibility(on ? View.VISIBLE : View.GONE);
    }

    private void submit() {
        final String u = user.getText().toString().trim();
        final String p = pass.getText().toString();
        error.setTextColor(getColor(R.color.bad));
        if (u.isEmpty()) { error.setText("Enter your username"); user.requestFocus(); return; }
        if (p.isEmpty()) { error.setText("Enter your password"); pass.requestFocus(); return; }
        error.setText("");
        error.setTextColor(getColor(R.color.bad));
        InputMethodManager imm = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (imm != null) imm.hideSoftInputFromWindow(pass.getWindowToken(), 0);
        setBusy(true);
        final String base = server;
        final int my = ++attempt;
        new Thread(() -> {
            String err = null;
            final List<String> cookies = new java.util.ArrayList<>();
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(base + "/api/login").openConnection();
                c.setConnectTimeout(10000); c.setReadTimeout(15000);
                c.setRequestMethod("POST");
                c.setDoOutput(true);
                c.setInstanceFollowRedirects(false);
                c.setUseCaches(false);
                c.setRequestProperty("Content-Type", "application/json");
                c.setRequestProperty("Accept", "application/json");
                c.setRequestProperty("User-Agent", "MediaServerAndroid/" + BuildConfigInfo.VERSION);
                JSONObject body = new JSONObject();
                body.put("username", u);
                body.put("password", p);
                try (OutputStream os = c.getOutputStream()) { os.write(body.toString().getBytes(StandardCharsets.UTF_8)); }
                int code = c.getResponseCode();
                if (code == 200) {
                    for (Map.Entry<String, List<String>> h : c.getHeaderFields().entrySet()) {
                        if (h.getKey() == null || !h.getKey().equalsIgnoreCase("Set-Cookie")) continue;
                        cookies.addAll(h.getValue());
                    }
                    boolean got = false;
                    for (String v : cookies) if (v.trim().startsWith(Session.COOKIE + "=")) got = true;
                    if (!got) err = "The server didn't start a session. Is this a Movinite server?";
                } else if (code == 401) {
                    err = "Wrong username or password";
                } else {
                    String detail = readDetail(c);
                    err = detail != null ? detail : "The server answered HTTP " + code;
                }
                c.disconnect();
            } catch (SSLException e) {
                err = "Can't connect securely to " + Uri.parse(base).getHost() + " (certificate problem)";
            } catch (java.io.IOException e) {
                err = "Can't reach " + Uri.parse(base).getHost() + ". Check your internet connection, or that the server is on.";
            } catch (Exception e) {
                err = "Sign-in failed: " + e.getClass().getSimpleName();
            }
            final String fe = err;
            ui.post(() -> {
                if (my != attempt || isFinishing()) return;
                setBusy(false);
                if (fe == null) {
                    CookieManager cm = CookieManager.getInstance();      // hand the session to the WebView
                    cm.setAcceptCookie(true);
                    for (String v : cookies) cm.setCookie(base, v);
                    cm.flush();
                    pass.setText("");
                    openHome();
                }
                else { error.setText(fe); if (fe.startsWith("Wrong")) { pass.selectAll(); pass.requestFocus(); } }
            });
        }).start();
    }

    /** FastAPI errors look like {"detail": "..."} */
    private static String readDetail(HttpURLConnection c) {
        try {
            InputStream in = c.getErrorStream();
            if (in == null) return null;
            StringBuilder sb = new StringBuilder();
            try (BufferedReader r = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8))) {
                String line; while ((line = r.readLine()) != null && sb.length() < 4096) sb.append(line);
            }
            String d = new JSONObject(sb.toString()).optString("detail", null);
            return d == null || d.isEmpty() ? null : d;
        } catch (Exception e) { return null; }
    }

    private void openHome() {
        Intent i = new Intent(this, MainActivity.class);
        i.setAction(MainActivity.ACTION_OPEN);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        startActivity(i);
        finish();
    }
}
