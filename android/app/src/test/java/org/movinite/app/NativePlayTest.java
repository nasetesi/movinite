package org.movinite.app;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class NativePlayTest {
    @Test public void phonesStayOnTheWebPlayer() {
        assertFalse(NativePlay.useNativePlayer(false));
        assertTrue(NativePlay.useNativePlayer(true));
    }

    @Test public void tapOnEmptyVideoTogglesChrome() {
        assertTrue(NativePlay.tapTogglesChrome(false));
        assertFalse(NativePlay.tapTogglesChrome(true));
    }

    @Test public void doubleTapSeeksOnTheSides() {
        assertEquals(NativePlay.TAP_BACK, NativePlay.doubleTapAction(10, 900));
        assertEquals(NativePlay.TAP_TOGGLE, NativePlay.doubleTapAction(450, 900));
        assertEquals(NativePlay.TAP_FWD, NativePlay.doubleTapAction(890, 900));
    }
}
