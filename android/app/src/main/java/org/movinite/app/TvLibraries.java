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

    /** One cell in the 2-column TV grid, used to wire D-pad neighbors. */
    static final class Cell {
        final int index;
        final int row;
        final int col;
        Cell(int index, int row, int col) {
            this.index = index;
            this.row = row;
            this.col = col;
        }
    }

    /**
     * Place libraries into a 2-column grid, starting a new row at each group
     * and after every two items. Group sizes are the number of libraries in
     * each group, in display order.
     */
    static List<Cell> cells(int... groupSizes) {
        List<Cell> out = new ArrayList<>();
        int index = 0, gridRow = 0;
        for (int n : groupSizes) {
            if (n < 0) continue;
            for (int i = 0; i < n; i++) {
                if (i > 0 && i % 2 == 0) gridRow++;
                out.add(new Cell(index, gridRow, i % 2));
                index++;
            }
            if (n > 0) gridRow++;
        }
        return out;
    }

    /** Neighbor in one direction; returns the same index if there isn't one. */
    static int neighbor(List<Cell> cells, int index, int dx, int dy) {
        if (cells == null || index < 0 || index >= cells.size()) return index;
        Cell c = cells.get(index);
        if (dx != 0 && dy == 0) {
            int wantCol = c.col + dx;
            for (Cell o : cells) {
                if (o.row == c.row && o.col == wantCol) return o.index;
            }
            return index;
        }
        if (dy != 0 && dx == 0) {
            int best = -1, bestRow = dy > 0 ? Integer.MAX_VALUE : Integer.MIN_VALUE;
            for (Cell o : cells) {
                if (o.col != c.col) continue;
                if (dy > 0 && o.row > c.row && o.row < bestRow) { best = o.index; bestRow = o.row; }
                if (dy < 0 && o.row < c.row && o.row > bestRow) { best = o.index; bestRow = o.row; }
            }
            return best >= 0 ? best : index;
        }
        return index;
    }

    /** True for the library list itself (#/library/3), not a deeper collection path. */
    static boolean isLibraryListHash(String urlOrHash) {
        if (urlOrHash == null) return false;
        String h = urlOrHash.trim();
        int hash = h.indexOf('#');
        if (hash >= 0) h = h.substring(hash + 1);
        if (h.startsWith("/")) h = h.substring(1);
        int q = h.indexOf('?');
        if (q >= 0) h = h.substring(0, q);
        if (h.endsWith("/")) h = h.substring(0, h.length() - 1);
        if (!h.startsWith("library/")) return false;
        String rest = h.substring("library/".length());
        if (rest.isEmpty()) return false;
        if (rest.charAt(0) == '-') {
            if (rest.length() == 1) return false;
            rest = rest.substring(1);
        }
        for (int i = 0; i < rest.length(); i++) {
            if (!Character.isDigit(rest.charAt(i))) return false;
        }
        return true;
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
