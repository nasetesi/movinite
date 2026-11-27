package org.movinite.app;

import org.json.JSONObject;
import org.junit.Test;

import java.util.HashSet;
import java.util.Set;

import static org.junit.Assert.assertEquals;

public class PlayFallbackTest {
    @Test public void hevcFallsBackToH264ThenWeb() throws Exception {
        JSONObject pb = new JSONObject("{\"hires\":[\"1440p\",\"1080p\"],\"profiles\":[\"1080p\",\"720p\"],\"remux\":false}");
        JSONObject caps = new JSONObject("{\"hevc\":true}");
        Set<String> tried = new HashSet<>();
        tried.add("1440p.hevc");
        assertEquals("1440p", PlayFallback.nextMode("1440p.hevc", pb, caps, tried));
        tried.add("1440p");
        assertEquals(PlayFallback.WEB, PlayFallback.nextMode("1440p", pb, caps, tried));
    }

    @Test public void directPrefersRemuxThenTranscode() throws Exception {
        JSONObject pb = new JSONObject("{\"remux\":true,\"hires\":[\"1440p\"]}");
        JSONObject caps = new JSONObject("{\"hevc\":true}");
        Set<String> tried = new HashSet<>();
        tried.add("direct");
        assertEquals("remux", PlayFallback.nextMode("direct", pb, caps, tried));
        tried.add("remux");
        assertEquals("1440p.hevc", PlayFallback.nextMode("remux", pb, caps, tried));
    }

    @Test public void errorDetailPrefersHttpStatus() {
        assertEquals("ERROR_CODE_IO_BAD_HTTP_STATUS · HTTP 500",
            PlayFallback.errorDetail("ERROR_CODE_IO_BAD_HTTP_STATUS", 500, "Source error", null));
    }
}
