package org.movinite.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.TextView;

import org.json.JSONObject;

/**
 * Android TV Settings (2.4.7): signed-in user, server name + host, app version,
 * plus Change server and Sign out. Phones do not open this screen.
 */
public class TvSettingsActivity extends Activity {
    private final Handler ui = new Handler(Looper.getMainLooper());
    private TextView userValue, serverValue, versionValue;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        setContentView(R.layout.activity_tv_settings);
        userValue = findViewById(R.id.user_value);
        serverValue = findViewById(R.id.server_value);
        versionValue = findViewById(R.id.version_value);

        String host = TvSettings.hostOf(Prefs.serverUrl(this));
        serverValue.setText(TvSettings.serverLabel(null, host));
        userValue.setText(getIntent().getStringExtra(MainActivity.EXTRA_TV_USER) != null
                ? getIntent().getStringExtra(MainActivity.EXTRA_TV_USER)
                : "Signed in");
        versionValue.setText(TvSettings.versionLabel(versionName(), versionCode()));

        View change = findViewById(R.id.change_server);
        change.setOnClickListener(v -> startActivity(new Intent(this, SetupActivity.class)));
        findViewById(R.id.sign_out).setOnClickListener(v -> confirmSignOut());
        change.requestFocus();
        refreshFromServer();
    }

    @Override
    protected void onResume() {
        super.onResume();
        // If the server address changed in Setup, MainActivity will reload; finish so Back isn't stuck here.
        String now = Prefs.serverUrl(this);
        String started = getIntent().getStringExtra(MainActivity.EXTRA_TV_SERVER);
        if (started != null && now != null && !started.equals(now)) {
            finish();
            return;
        }
        refreshFromServer();
    }

    @Override
    public void onBackPressed() {
        // Back returns to Home (MainActivity already moved the WebView to #/home).
        finish();
    }

    private void confirmSignOut() {
        AlertDialog d = new AlertDialog.Builder(this)
                .setTitle(R.string.tv_sign_out_confirm_title)
                .setMessage(R.string.tv_sign_out_confirm)
                .setNegativeButton(R.string.tv_sign_out_cancel, null)
                .setPositiveButton(R.string.tv_sign_out, (dlg, w) -> doSignOut())
                .create();
        d.setOnShowListener(x -> {
            // Default focus on Cancel so a stray OK doesn't sign them out.
            View cancel = d.getButton(AlertDialog.BUTTON_NEGATIVE);
            if (cancel != null) cancel.requestFocus();
        });
        d.show();
    }

    private void doSignOut() {
        Intent i = new Intent(this, MainActivity.class);
        i.setAction(MainActivity.ACTION_SIGN_OUT);
        i.addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        startActivity(i);
        finish();
    }

    private void refreshFromServer() {
        final String host = TvSettings.hostOf(Prefs.serverUrl(this));
        new Thread(() -> {
            String user = "Signed in";
            String serverName = null;
            try {
                ServerApi api = new ServerApi(this);
                JSONObject me = api.getJson("/api/me");
                user = TvSettings.userLabel(me.optString("name", null), me.optString("username", null));
            } catch (Exception ignored) { }
            try {
                ServerApi api = new ServerApi(this);
                JSONObject em = api.getJson("/api/settings/email");
                String n = em.optString("server_name", "");
                if (n != null && !n.trim().isEmpty()) serverName = n.trim();
            } catch (Exception ignored) { }
            final String fu = user, fn = serverName;
            ui.post(() -> {
                if (isFinishing()) return;
                userValue.setText(fu);
                serverValue.setText(TvSettings.serverLabel(fn, host));
            });
        }).start();
    }

    private String versionName() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception e) {
            return BuildConfigInfo.VERSION;
        }
    }

    private int versionCode() {
        try {
            PackageInfo p = getPackageManager().getPackageInfo(getPackageName(), 0);
            if (Build.VERSION.SDK_INT >= 28) return (int) p.getLongVersionCode();
            return p.versionCode;
        } catch (Exception e) {
            return 15;
        }
    }
}
