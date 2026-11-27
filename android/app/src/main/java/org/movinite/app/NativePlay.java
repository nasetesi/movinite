package org.movinite.app;

/**
 * 2.4.4: phones (and other non-television devices) keep the in-page web player,
 * which already has the pre-2.4 tap-to-show controls. The native ExoPlayer is
 * for TVs, where the remote / D-pad is the right fit.
 */
final class NativePlay {
    private NativePlay() {}

    /** True only when the Android UI mode is television (leanback / Android TV). */
    static boolean useNativePlayer(boolean television) {
        return television;
    }

    /** A single tap on empty video (not a button or the seek bar) toggles the chrome. */
    static boolean tapTogglesChrome(boolean hitInteractive) {
        return !hitInteractive;
    }

    /**
     * Double-tap zones: left third rewinds, right third skips ahead, middle toggles chrome.
     * x is 0..width in the same units.
     */
    static final int TAP_TOGGLE = 0;
    static final int TAP_BACK = -1;
    static final int TAP_FWD = 1;

    static int doubleTapAction(float x, int width) {
        if (width <= 0) return TAP_TOGGLE;
        if (x < width / 3f) return TAP_BACK;
        if (x > width * 2f / 3f) return TAP_FWD;
        return TAP_TOGGLE;
    }
}
