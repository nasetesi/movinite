package org.movinite.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * Server address screen.
 * First launch (no server saved yet): a welcome screen that asks for the Movinite server address, then the sign-in screen follows.
 * Later: Server settings, opened with the gear on the sign-in screen (also logo long-press, or the app icon shortcut).
 */
public class SetupActivity extends Activity {
    static final String EXTRA_FIRST_RUN = "first_run";

    static Intent firstRun(android.content.Context c) {
        Intent i = new Intent(c, SetupActivity.class);
        i.putExtra(EXTRA_FIRST_RUN, true);
        i.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK | Intent.FLAG_ACTIVITY_NEW_TASK);
        return i;
    }

    private boolean firstRun;
    private EditText url;
    private TextView status;
    private Button test, connect;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private volatile int attempt = 0;

    interface Result { void done(boolean ok, String message); }

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        setContentView(R.layout.activity_setup);
        url = findViewById(R.id.url);
        status = findViewById(R.id.status);
        test = findViewById(R.id.test);
        connect = findViewById(R.id.connect);
        String cur = Prefs.serverUrl(this);
        firstRun = cur == null || getIntent().getBooleanExtra(EXTRA_FIRST_RUN, false);
        url.setText(cur == null ? "" : cur);
        TextView current = findViewById(R.id.current);
        if (cur == null) current.setVisibility(View.GONE); else current.setText("Current server: " + cur);
        if (firstRun) {
            ((TextView) findViewById(R.id.subtitle)).setText("Welcome! Enter the address of your Movinite server to get started.");
            ((TextView) findViewById(R.id.help)).setText(getString(R.string.setup_help_first));
            findViewById(R.id.close).setVisibility(View.GONE);      // nothing to go back to yet
            url.requestFocus();
        }
        findViewById(R.id.close).setOnClickListener(v -> finish());
        Insets.keepBelowStatusBar(findViewById(R.id.setup_root), findViewById(R.id.close));
        url.setSelection(url.getText().length());
        test.setOnClickListener(v -> runTest(null));
        connect.setOnClickListener(v -> onConnect());
        url.setOnEditorActionListener((v, id, ev) -> {
            if (id == EditorInfo.IME_ACTION_GO || (ev != null && ev.getKeyCode() == KeyEvent.KEYCODE_ENTER)) { onConnect(); return true; }
            return false;
        });
    }

    private void setBusy(boolean busy) { test.setEnabled(!busy); connect.setEnabled(!busy); }

    private void say(String msg, int colorRes) { status.setText(msg); status.setTextColor(getColor(colorRes)); }

    private void runTest(Result then) {
        final String base = Prefs.normalize(url.getText().toString());
        if (base == null) { say("Please enter an address like https://movies.example.com or http://192.0.2.10:8099", R.color.bad); return; }
        setBusy(true);
        say("Testing " + base + " ...", R.color.muted);
        final int my = ++attempt;
        new Thread(() -> {
            String msg; boolean ok;
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(base + "/api/health").openConnection();
                c.setConnectTimeout(7000); c.setReadTimeout(7000);
                c.setRequestProperty("Accept", "application/json");
                int code = c.getResponseCode();
                if (code != 200) throw new Exception("HTTP " + code + " from " + Uri.parse(base).getHost());
                StringBuilder sb = new StringBuilder();
                try (BufferedReader r = new BufferedReader(new InputStreamReader(c.getInputStream(), "UTF-8"))) {
                    String line; while ((line = r.readLine()) != null && sb.length() < 4096) sb.append(line);
                }
                JSONObject j = new JSONObject(sb.toString());
                if (!"ok".equals(j.optString("status"))) throw new Exception("this doesn't look like a Movinite server");
                ok = true;
                msg = "Connected: Movinite v" + j.optString("version", "?") + (base.startsWith("http://") ? "  (not encrypted - fine at home)" : "");
            } catch (Exception e) {
                ok = false;
                String m = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
                msg = "Couldn't connect: " + m;
            }
            final boolean fok = ok; final String fmsg = msg;
            ui.post(() -> {
                if (my != attempt) return;
                setBusy(false);
                say(fmsg, fok ? R.color.ok : R.color.bad);
                if (then != null) then.done(fok, fmsg);
            });
        }).start();
    }

    private void onConnect() {
        runTest((ok, msg) -> {
            String base = Prefs.normalize(url.getText().toString());
            if (base == null) return;
            if (ok) { save(base); return; }
            new AlertDialog.Builder(this)
                .setTitle("Server not reachable")
                .setMessage(msg + "\n\nSave this address anyway? (Use this if the server is just switched off right now.)")
                .setPositiveButton("Save anyway", (d, w) -> save(base))
                .setNegativeButton("Cancel", null)
                .show();
        });
    }

    private void save(String base) {
        Prefs.setServerUrl(this, base);
        Intent i = new Intent(this, MainActivity.class);
        i.setAction(MainActivity.ACTION_OPEN);
        i.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK | Intent.FLAG_ACTIVITY_NEW_TASK);   // -> Home, or the sign-in screen for that server
        startActivity(i);
        finish();
    }

}
