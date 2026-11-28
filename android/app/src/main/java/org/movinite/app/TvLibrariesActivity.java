package org.movinite.app;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;

import java.util.ArrayList;
import java.util.List;

/**
 * Android TV Libraries (2.4.8): same page scaffold as Settings, with
 * share/server group labels and a 2-column grid of large focusable rows.
 * Phones do not open this screen.
 */
public class TvLibrariesActivity extends Activity {
    private final Handler ui = new Handler(Looper.getMainLooper());
    private LinearLayout content;
    private final List<View> rows = new ArrayList<>();

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        setContentView(R.layout.activity_tv_libraries);
        content = findViewById(R.id.lib_content);
        showMessage("Loading…");
        refresh();
    }

    @Override
    public void onBackPressed() {
        finish();
    }

    private void refresh() {
        new Thread(() -> {
            try {
                ServerApi api = new ServerApi(this);
                JSONArray libs = api.getJsonArray("/api/libraries");
                List<TvLibraries.Group> groups = TvLibraries.groups(libs);
                ui.post(() -> {
                    if (isFinishing()) return;
                    bind(groups);
                });
            } catch (Exception e) {
                String msg = e.getMessage();
                if (msg == null || msg.trim().isEmpty()) msg = "Could not load libraries.";
                final String shown = msg;
                ui.post(() -> {
                    if (isFinishing()) return;
                    showMessage(shown);
                });
            }
        }).start();
    }

    private void bind(List<TvLibraries.Group> groups) {
        content.removeAllViews();
        rows.clear();
        if (groups == null || groups.isEmpty()) {
            showMessage(getString(R.string.tv_libraries_empty));
            return;
        }
        LayoutInflater inf = getLayoutInflater();
        int gap = dp(12);
        for (TvLibraries.Group g : groups) {
            TextView head = new TextView(this);
            head.setText(g.name);
            head.setAllCaps(true);
            head.setTextColor(getColor(R.color.muted));
            head.setTextSize(TypedValue.COMPLEX_UNIT_PX, getResources().getDimension(R.dimen.tv_label_size));
            head.setLetterSpacing(0.08f);
            LinearLayout.LayoutParams hp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            // First heading flush with the title gap; later ones get a little air.
            hp.topMargin = content.getChildCount() == 0 ? 0 : dp(20);
            hp.bottomMargin = dp(10);
            content.addView(head, hp);

            LinearLayout pair = null;
            for (int i = 0; i < g.libs.size(); i++) {
                if (i % 2 == 0) {
                    pair = new LinearLayout(this);
                    pair.setOrientation(LinearLayout.HORIZONTAL);
                    pair.setLayoutParams(new LinearLayout.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
                    ((LinearLayout.LayoutParams) pair.getLayoutParams()).bottomMargin = gap;
                    content.addView(pair);
                }
                View row = inflateRow(inf, pair, g.libs.get(i));
                LinearLayout.LayoutParams rp = new LinearLayout.LayoutParams(0, dp(68), 1f);
                if (i % 2 == 1) rp.leftMargin = gap;
                pair.addView(row, rp);
                rows.add(row);
            }
            // Keep a single last cell at half width so row sizes stay consistent.
            if (pair != null && pair.getChildCount() == 1) {
                View spacer = new View(this);
                spacer.setFocusable(false);
                LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(0, dp(68), 1f);
                sp.leftMargin = gap;
                pair.addView(spacer, sp);
            }
        }
        wireFocus();
        if (!rows.isEmpty()) rows.get(0).requestFocus();
    }

    private View inflateRow(LayoutInflater inf, ViewGroup parent, TvLibraries.Lib lib) {
        View row = inf.inflate(R.layout.item_tv_library, parent, false);
        ((TextView) row.findViewById(R.id.lib_name)).setText(lib.name);
        ((TextView) row.findViewById(R.id.lib_sub)).setText(lib.subtitle);
        final int id = lib.id;
        row.setOnClickListener(v -> openLibrary(id));
        return row;
    }

    private void wireFocus() {
        int n = rows.size();
        for (int i = 0; i < n; i++) {
            View v = rows.get(i);
            int left = (i % 2 == 1) ? i - 1 : i;
            int right = (i % 2 == 0 && i + 1 < n) ? i + 1 : i;
            int up = i - 2;
            if (up < 0) up = (i % 2 == 1 && i - 1 >= 0) ? i - 1 : i;
            int down = i + 2;
            if (down >= n) down = (i + 1 < n) ? i + 1 : i;
            v.setNextFocusLeftId(rows.get(left).getId());
            v.setNextFocusRightId(rows.get(right).getId());
            v.setNextFocusUpId(rows.get(up).getId());
            v.setNextFocusDownId(rows.get(down).getId());
        }
        // Assign ids so nextFocus* works (views inflated without ids share NONE).
        for (int i = 0; i < n; i++) {
            if (rows.get(i).getId() == View.NO_ID) rows.get(i).setId(View.generateViewId());
        }
        for (int i = 0; i < n; i++) {
            View v = rows.get(i);
            int left = (i % 2 == 1) ? i - 1 : i;
            int right = (i % 2 == 0 && i + 1 < n) ? i + 1 : i;
            int up = i - 2;
            if (up < 0) up = (i % 2 == 1 && i - 1 >= 0) ? i - 1 : i;
            int down = i + 2;
            if (down >= n) down = (i + 1 < n) ? i + 1 : i;
            v.setNextFocusLeftId(rows.get(left).getId());
            v.setNextFocusRightId(rows.get(right).getId());
            v.setNextFocusUpId(rows.get(up).getId());
            v.setNextFocusDownId(rows.get(down).getId());
        }
    }

    private void openLibrary(int id) {
        Intent i = new Intent(this, MainActivity.class);
        i.setAction(MainActivity.ACTION_OPEN_LIBRARY);
        i.putExtra(MainActivity.EXTRA_LIBRARY_ID, id);
        i.addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        startActivity(i);
        finish();
    }

    private void showMessage(String msg) {
        content.removeAllViews();
        rows.clear();
        TextView t = new TextView(this);
        t.setText(msg);
        t.setTextColor(getColor(R.color.muted));
        t.setTextSize(TypedValue.COMPLEX_UNIT_PX, getResources().getDimension(R.dimen.tv_row_sub));
        t.setGravity(Gravity.START);
        content.addView(t);
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
