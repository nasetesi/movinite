package org.movinite.app;

import android.view.View;
import android.view.ViewGroup;

/** Keeps a corner button clear of the status bar when the window draws edge-to-edge. */
final class Insets {
    private Insets() {}

    static void keepBelowStatusBar(View root, View button) {
        final ViewGroup.MarginLayoutParams lp = (ViewGroup.MarginLayoutParams) button.getLayoutParams();
        final int base = lp.topMargin;
        root.setOnApplyWindowInsetsListener((v, in) -> {
            lp.topMargin = base + in.getSystemWindowInsetTop();
            button.setLayoutParams(lp);
            return in;
        });
        root.requestApplyInsets();
    }
}
