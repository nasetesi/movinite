package org.movinite.app;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Grouping and labels for the native Android TV Libraries screen (2.4.8).
 * Mirrors the web app's libGroups() so Sunset / Waimea (and remote peers)
 * stay together. Pure Java so unit tests can run on the JVM.
 */
final class TvLibraries {
    private TvLibraries() {}

    static final class Lib {
        final int id;
        final String name;
        final String kind;
        final String subtitle;
        final String groupKey;
        final String groupName;

        Lib(int id, String name, String kind, String subtitle, String groupKey, String groupName) {
            this.id = id;
            this.name = name;
            this.kind = kind;
            this.subtitle = subtitle;
            this.groupKey = groupKey;
            this.groupName = groupName;
        }
    }

    static final class Group {
        final String key;
        final String name;
        final List<Lib> libs = new ArrayList<>();

        Group(String key, String name) {
            this.key = key;
            this.name = name;
        }
    }

    static String kindLabel(String kind) {
        String k = kind == null ? "" : kind.trim().toLowerCase();
        switch (k) {
            case "movies": return "Movies";
            case "tv": return "TV shows";
            case "music": return "Music";
            default: return "Videos";
        }
    }

    /** Same wording as the web libCountText(). */
    static String countText(Integer filmCount, int itemCount) {
        if (filmCount != null) {
            return filmCount + " movie" + (filmCount == 1 ? "" : "s");
        }
        return itemCount + " item" + (itemCount == 1 ? "" : "s");
    }

    static String subtitle(String kind, Integer filmCount, int itemCount) {
        return kindLabel(kind) + "  ·  " + countText(filmCount, itemCount);
    }

    static String groupKey(boolean isRemote, String peerId, String peerName, int id, Integer shareId) {
        if (isRemote) {
            if (peerId != null && !peerId.isEmpty()) return "r" + peerId;
            if (peerName != null && !peerName.isEmpty()) return "r" + peerName;
            return "r" + id;
        }
        if (shareId != null && shareId != 0) return "s" + shareId;
        return "local";
    }

    static String groupName(boolean isRemote, String peerName, String shareName, String shareKind) {
        if (isRemote) {
            if (peerName != null && !peerName.trim().isEmpty()) return peerName.trim();
            return "Shared";
        }
        if (shareName != null && !shareName.trim().isEmpty()) return shareName.trim();
        if (shareKind != null && shareKind.equalsIgnoreCase("peer")) return "Shared";
        if (shareKind != null && !shareKind.trim().isEmpty()) return "Network share";
        return "This server";
    }

    /**
     * Groups come in the order of their first library; inside a group the
     * incoming (admin) order is kept.
     */
    static List<Group> groups(JSONArray libs) {
        Map<String, Group> by = new LinkedHashMap<>();
        List<Group> out = new ArrayList<>();
        if (libs == null) return out;
        for (int i = 0; i < libs.length(); i++) {
            JSONObject o = libs.optJSONObject(i);
            if (o == null) continue;
            Lib lib = fromJson(o);
            Group g = by.get(lib.groupKey);
            if (g == null) {
                g = new Group(lib.groupKey, lib.groupName);
                by.put(lib.groupKey, g);
                out.add(g);
            }
            g.libs.add(lib);
        }
        return out;
    }

    static Lib fromJson(JSONObject o) {
        int id = o.optInt("id", 0);
        String name = optStr(o, "name");
        if (name.isEmpty()) name = "Library";
        String kind = optStr(o, "kind");
        boolean remote = o.optBoolean("is_remote", false);
        String peerId = optAsString(o, "peer_id");
        String peerName = optStr(o, "peer_name");
        if (peerName.isEmpty()) peerName = optStr(o, "source_name");
        Integer shareId = optIntObj(o, "share_id");
        JSONObject share = o.optJSONObject("share");
        String shareName = share == null ? "" : optStr(share, "name");
        String shareKind = share == null ? "" : optStr(share, "kind");
        Integer film = o.has("film_count") && !o.isNull("film_count") ? o.optInt("film_count") : null;
        int items = o.optInt("item_count", 0);
        String key = groupKey(remote, peerId, peerName, id, shareId);
        String gname = groupName(remote, peerName, shareName, shareKind);
        return new Lib(id, name, kind, subtitle(kind, film, items), key, gname);
    }

    private static String optStr(JSONObject o, String k) {
        if (o == null || !o.has(k) || o.isNull(k)) return "";
        String s = o.optString(k, "");
        return s == null ? "" : s.trim();
    }

    private static String optAsString(JSONObject o, String k) {
        if (o == null || !o.has(k) || o.isNull(k)) return "";
        Object v = o.opt(k);
        return v == null ? "" : String.valueOf(v).trim();
    }

    private static Integer optIntObj(JSONObject o, String k) {
        if (o == null || !o.has(k) || o.isNull(k)) return null;
        return o.optInt(k);
    }
}
