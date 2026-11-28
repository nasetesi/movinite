package org.movinite.app;

import static org.junit.Assert.*;

import org.junit.Test;

public class TvSettingsTest {
    @Test public void hostOfHttpsDefaultPort() {
        assertEquals("media.tukuia.com", TvSettings.hostOf("https://media.tukuia.com"));
        assertEquals("media.tukuia.com", TvSettings.hostOf("https://media.tukuia.com/"));
        assertEquals("movies.tukuia.com", TvSettings.hostOf("https://movies.tukuia.com/foo"));
    }

    @Test public void hostOfLanPort() {
        assertEquals("192.0.2.10:8099", TvSettings.hostOf("http://192.0.2.10:8099"));
        assertEquals("192.168.111.137", TvSettings.hostOf("http://192.168.111.137:80"));
    }

    @Test public void hostOfEmpty() {
        assertEquals("", TvSettings.hostOf(null));
        assertEquals("", TvSettings.hostOf(""));
        assertEquals("", TvSettings.hostOf("not a url"));
    }

    @Test public void userLabelPrefersUsernameThenBoth() {
        assertEquals("manase", TvSettings.userLabel(null, "manase"));
        assertEquals("manase", TvSettings.userLabel("manase", "manase"));
        assertEquals("Nase (manase)", TvSettings.userLabel("Nase", "manase"));
        assertEquals("Signed in", TvSettings.userLabel("  ", null));
    }

    @Test public void serverLabelJoinsNameAndHost() {
        assertEquals("Movinite  ·  media.tukuia.com", TvSettings.serverLabel(null, "media.tukuia.com"));
        assertEquals("Home  ·  media.tukuia.com", TvSettings.serverLabel("Home", "media.tukuia.com"));
        assertEquals("Movinite", TvSettings.serverLabel("", ""));
        assertEquals("media.tukuia.com", TvSettings.serverLabel("media.tukuia.com", "media.tukuia.com"));
    }

    @Test public void versionLabelIncludesBuild() {
        assertEquals("2.4.9  (build 17)", TvSettings.versionLabel("2.4.9", 17));
        assertEquals("?  (build 0)", TvSettings.versionLabel(null, 0));
    }

    @Test public void hideTvHashDropsAdminAndExtraChrome() {
        assertTrue(TvSettings.hideTvHash("#/settings"));
        assertTrue(TvSettings.hideTvHash("#/settings/sounds"));
        assertTrue(TvSettings.hideTvHash("#/settings/system"));
        assertTrue(TvSettings.hideTvHash("#/downloads"));
        assertTrue(TvSettings.hideTvHash("#/activity"));
        assertTrue(TvSettings.hideTvHash("#/mylist"));
        assertTrue(TvSettings.hideTvHash("#/invites"));
        assertTrue(TvSettings.hideTvHash("https://media.tukuia.com/#/status"));
        assertFalse(TvSettings.hideTvHash("#/home"));
        assertFalse(TvSettings.hideTvHash("#/search"));
        assertFalse(TvSettings.hideTvHash("#/search/fix"));
        assertFalse(TvSettings.hideTvHash("#/libraries"));
        assertFalse(TvSettings.hideTvHash("#/library/3"));
        assertFalse(TvSettings.hideTvHash("#/item/12"));
        assertFalse(TvSettings.hideTvHash("#/pair/ABCD"));
        assertFalse(TvSettings.hideTvHash("#/invite/token"));
        assertFalse(TvSettings.hideTvHash("#/"));
        assertFalse(TvSettings.hideTvHash(null));
    }
}
