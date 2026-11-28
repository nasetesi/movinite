package org.movinite.app;

import static org.junit.Assert.*;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

import java.util.List;

public class TvLibrariesTest {
    @Test public void kindAndCountLabels() {
        assertEquals("Movies", TvLibraries.kindLabel("movies"));
        assertEquals("TV shows", TvLibraries.kindLabel("tv"));
        assertEquals("Music", TvLibraries.kindLabel("music"));
        assertEquals("Videos", TvLibraries.kindLabel("other"));
        assertEquals("Videos", TvLibraries.kindLabel(null));
        assertEquals("1 movie", TvLibraries.countText(1, 3));
        assertEquals("12 movies", TvLibraries.countText(12, 14));
        assertEquals("4 items", TvLibraries.countText(null, 4));
        assertEquals("1 item", TvLibraries.countText(null, 1));
        assertEquals("Movies  ·  12 movies", TvLibraries.subtitle("movies", 12, 14));
    }

    @Test public void groupKeyRemoteShareLocal() {
        assertEquals("r7", TvLibraries.groupKey(true, "7", "Waimea", -3, null));
        assertEquals("rWaimea", TvLibraries.groupKey(true, "", "Waimea", -3, null));
        assertEquals("s2", TvLibraries.groupKey(false, null, null, 1, 2));
        assertEquals("local", TvLibraries.groupKey(false, null, null, 1, null));
        assertEquals("local", TvLibraries.groupKey(false, null, null, 1, 0));
    }

    @Test public void groupNamePrefersShareThenDefaults() {
        assertEquals("Sunset Server", TvLibraries.groupName(false, null, "Sunset Server", "cifs"));
        assertEquals("Waimea Server", TvLibraries.groupName(true, "Waimea Server", "", "peer"));
        assertEquals("Shared", TvLibraries.groupName(true, "", "", "peer"));
        assertEquals("This server", TvLibraries.groupName(false, null, "", ""));
        assertEquals("Network share", TvLibraries.groupName(false, null, "", "cifs"));
    }

    @Test public void groupsKeepFirstSeenOrderAndAdminOrder() throws Exception {
        JSONArray arr = new JSONArray();
        arr.put(lib(1, "4K Movies", "movies", 10, 12, 2, "Sunset Server", false));
        arr.put(lib(2, "TV", "tv", null, 40, 2, "Sunset Server", false));
        arr.put(lib(-5, "Kids", "movies", 3, 3, 0, "Waimea Server", true));
        arr.put(lib(3, "Concerts", "music", null, 8, 9, "Waimea NAS", false));

        // mark remote on Kids
        arr.getJSONObject(2).put("is_remote", true);
        arr.getJSONObject(2).put("peer_id", 11);
        arr.getJSONObject(2).put("peer_name", "Waimea Server");
        arr.getJSONObject(2).remove("share_id");
        arr.getJSONObject(2).remove("share");

        List<TvLibraries.Group> groups = TvLibraries.groups(arr);
        assertEquals(3, groups.size());
        assertEquals("Sunset Server", groups.get(0).name);
        assertEquals(2, groups.get(0).libs.size());
        assertEquals("4K Movies", groups.get(0).libs.get(0).name);
        assertEquals("TV", groups.get(0).libs.get(1).name);
        assertEquals("Movies  ·  10 movies", groups.get(0).libs.get(0).subtitle);
        assertEquals("TV shows  ·  40 items", groups.get(0).libs.get(1).subtitle);

        assertEquals("Waimea Server", groups.get(1).name);
        assertEquals("Kids", groups.get(1).libs.get(0).name);
        assertEquals("r11", groups.get(1).key);

        assertEquals("Waimea NAS", groups.get(2).name);
        assertEquals("Concerts", groups.get(2).libs.get(0).name);
        assertEquals("Music  ·  8 items", groups.get(2).libs.get(0).subtitle);
    }

    @Test public void emptyAndNullSafe() {
        assertTrue(TvLibraries.groups(null).isEmpty());
        assertTrue(TvLibraries.groups(new JSONArray()).isEmpty());
    }

    @Test public void cellsAndNeighborsMatchTwoColumnGroups() {
        // Sunset (3) + Waimea (3), the layout on the Philips TV.
        java.util.List<TvLibraries.Cell> c = TvLibraries.cells(3, 3);
        assertEquals(6, c.size());
        assertEquals(0, c.get(0).col); assertEquals(0, c.get(0).row); // Sunset Movies
        assertEquals(1, c.get(1).col); assertEquals(0, c.get(1).row); // Sunset TV
        assertEquals(0, c.get(2).col); assertEquals(1, c.get(2).row); // Music
        assertEquals(0, c.get(3).col); assertEquals(2, c.get(3).row); // Waimea Movies
        assertEquals(1, c.get(4).col); assertEquals(2, c.get(4).row); // Waimea TV
        assertEquals(0, c.get(5).col); assertEquals(3, c.get(5).row); // Waimea Other
        assertEquals(1, TvLibraries.neighbor(c, 0, 1, 0));  // right to Sunset TV
        assertEquals(0, TvLibraries.neighbor(c, 0, -1, 0)); // no left
        assertEquals(2, TvLibraries.neighbor(c, 0, 0, 1));  // down to Music
        assertEquals(3, TvLibraries.neighbor(c, 2, 0, 1));  // Music down to Waimea Movies
        assertEquals(5, TvLibraries.neighbor(c, 3, 0, 1));  // Waimea Movies down to Other
        assertEquals(4, TvLibraries.neighbor(c, 1, 0, 1));  // Sunset TV down to Waimea TV
        assertEquals(1, TvLibraries.neighbor(c, 1, 0, -1)); // Sunset TV has no up
        assertEquals(3, TvLibraries.neighbor(c, 4, -1, 0)); // Waimea TV left
        assertEquals(5, TvLibraries.neighbor(c, 5, 1, 0));  // Other has no right
    }

    @Test public void libraryListHashIsOnlyTheList() {
        assertTrue(TvLibraries.isLibraryListHash("#/library/3"));
        assertTrue(TvLibraries.isLibraryListHash("https://media.tukuia.com/#/library/-5"));
        assertTrue(TvLibraries.isLibraryListHash("#/library/12/"));
        assertFalse(TvLibraries.isLibraryListHash("#/library/3/collection/9"));
        assertFalse(TvLibraries.isLibraryListHash("#/libraries"));
        assertFalse(TvLibraries.isLibraryListHash("#/item/12"));
        assertFalse(TvLibraries.isLibraryListHash("#/home"));
        assertFalse(TvLibraries.isLibraryListHash(null));
    }

    private static JSONObject lib(int id, String name, String kind, Integer films, int items,
                                  int shareId, String shareName, boolean remote) throws Exception {
        JSONObject o = new JSONObject();
        o.put("id", id);
        o.put("name", name);
        o.put("kind", kind);
        o.put("item_count", items);
        if (films != null) o.put("film_count", films);
        o.put("is_remote", remote);
        if (shareId != 0) {
            o.put("share_id", shareId);
            JSONObject s = new JSONObject();
            s.put("name", shareName);
            s.put("kind", "cifs");
            o.put("share", s);
        }
        return o;
    }
}
