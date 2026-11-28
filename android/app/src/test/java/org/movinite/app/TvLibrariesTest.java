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
