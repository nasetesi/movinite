package org.movinite.app;

import org.json.JSONObject;
import org.junit.Test;

import static org.junit.Assert.*;

public class CapsTest {
    @Test
    public void queryIncludesNativeAndFlags() throws Exception {
        JSONObject o = new JSONObject();
        o.put("hevc", true);
        o.put("hevc10", true);
        o.put("ac3", true);
        o.put("eac3", true);
        o.put("dts", true);
        o.put("truehd", false);
        o.put("hdr10", true);
        o.put("hlg", true);
        o.put("dv", false);
        o.put("av1", true);
        o.put("maxh", 2160);
        o.put("maxHevc", 2160);
        String q = Caps.asQuery(o);
        assertTrue(q.startsWith("native=1"));
        assertTrue(q.contains("hevc=1"));
        assertTrue(q.contains("hevc10=1"));
        assertTrue(q.contains("ac3=1"));
        assertTrue(q.contains("eac3=1"));
        assertTrue(q.contains("dts=1"));
        assertFalse(q.contains("truehd=1"));
        assertTrue(q.contains("hdr10=1"));
        assertTrue(q.contains("hlg=1"));
        assertFalse(q.contains("dv=1"));
        assertTrue(q.contains("av1=1"));
        assertTrue(q.contains("acopy=1"));
        assertTrue(q.contains("surr=6"));
        assertTrue(q.contains("maxh=2160"));
        assertTrue(q.contains("dec=3840"));
    }

    @Test
    public void emptyCapsStillNative() throws Exception {
        String q = Caps.asQuery(new JSONObject());
        assertEquals("native=1", q);
        assertFalse(q.contains("hevc=1"));
    }

    @Test
    public void versionMatchesRelease() {
        assertEquals("2.4.8", BuildConfigInfo.VERSION);
    }
}
