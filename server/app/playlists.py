"""Per-user music playlists (schema 8 / 1.7.6)."""
import sqlite3
import time

from fastapi import HTTPException

from . import db

NAME_MAX = 80


def _now():
    return int(time.time())


def _clean_name(name):
    n = (name or "").strip()
    if not n:
        raise HTTPException(400, "Name is required")
    if len(n) > NAME_MAX:
        raise HTTPException(400, "Name is too long")
    return n


def owned(pid, uid):
    r = db.row("SELECT * FROM playlists WHERE id=? AND user_id=?", (pid, uid))
    if not r:
        raise HTTPException(404, "Playlist not found")
    return r


def _count(pid):
    r = db.row("SELECT COUNT(*) n FROM playlist_tracks WHERE playlist_id=?", (pid,))
    return int(r["n"] if r else 0)


def _poster(pid):
    r = db.row(
        "SELECT i.poster FROM playlist_tracks t JOIN items i ON i.id=t.item_id "
        "WHERE t.playlist_id=? AND i.poster IS NOT NULL AND i.poster<>'' "
        "ORDER BY t.position LIMIT 1",
        (pid,),
    )
    return r["poster"] if r else None


def _summary(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "track_count": row["track_count"] if "track_count" in row.keys() and row["track_count"] is not None else _count(row["id"]),
        "poster": row["poster"] if "poster" in row.keys() else _poster(row["id"]),
        "duration": row["duration"] if "duration" in row.keys() else None,
    }


def list_for(uid):
    rows = db.rows(
        "SELECT p.*, "
        "(SELECT COUNT(*) FROM playlist_tracks t WHERE t.playlist_id=p.id) AS track_count, "
        "(SELECT SUM(i.duration) FROM playlist_tracks t JOIN items i ON i.id=t.item_id "
        " WHERE t.playlist_id=p.id) AS duration "
        "FROM playlists p WHERE p.user_id=? ORDER BY p.updated_at DESC, p.id DESC",
        (uid,),
    )
    out = []
    for r in rows:
        s = _summary(r)
        s["poster"] = _poster(r["id"])
        out.append(s)
    return out


def get(pid, uid, item_cols):
    p = owned(pid, uid)
    tracks = db.rows(
        "SELECT t.id AS entry_id, t.position, t.added_at, " + item_cols +
        " FROM playlist_tracks t JOIN items i ON i.id=t.item_id "
        "WHERE t.playlist_id=? ORDER BY t.position, t.id",
        (pid,),
    )
    # qualify item columns with i. already in item_cols if passed as "i.id, ..."
    return {
        "id": p["id"],
        "name": p["name"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "track_count": len(tracks),
        "duration": sum((t.get("duration") or 0) for t in tracks),
        "poster": next((t.get("poster") for t in tracks if t.get("poster")), None),
        "tracks": tracks,
    }


def create(uid, name, item_ids=None):
    name = _clean_name(name)
    now = _now()
    try:
        with db.tx() as c:
            cur = c.execute(
                "INSERT INTO playlists(user_id, name, created_at, updated_at) VALUES(?,?,?,?)",
                (uid, name, now, now),
            )
            pid = cur.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A playlist with that name already exists")
    if item_ids:
        add_tracks(pid, uid, item_ids)
    return get_lite(pid, uid)


def get_lite(pid, uid):
    p = owned(pid, uid)
    s = _summary(p)
    s["poster"] = _poster(pid)
    s["duration"] = (db.row(
        "SELECT SUM(i.duration) d FROM playlist_tracks t JOIN items i ON i.id=t.item_id WHERE t.playlist_id=?",
        (pid,),
    ) or {}).get("d")
    return s


def rename(pid, uid, name):
    owned(pid, uid)
    name = _clean_name(name)
    try:
        with db.tx() as c:
            c.execute("UPDATE playlists SET name=?, updated_at=? WHERE id=? AND user_id=?",
                      (name, _now(), pid, uid))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A playlist with that name already exists")
    return get_lite(pid, uid)


def delete(pid, uid):
    owned(pid, uid)
    with db.tx() as c:
        c.execute("DELETE FROM playlist_tracks WHERE playlist_id=?", (pid,))
        c.execute("DELETE FROM playlists WHERE id=? AND user_id=?", (pid, uid))
    return {"ok": True}


def _valid_items(ids):
    ids = [int(i) for i in ids if i is not None]
    if not ids:
        return []
    have = {r["id"]: r for r in db.rows(
        "SELECT id, media_type FROM items WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)}
    missing = [i for i in ids if i not in have]
    if missing:
        raise HTTPException(400, "Unknown track")
    return ids


def add_tracks(pid, uid, item_ids):
    owned(pid, uid)
    if isinstance(item_ids, (int, str)):
        item_ids = [item_ids]
    ids = _valid_items(item_ids)
    if not ids:
        raise HTTPException(400, "No tracks to add")
    added = 0
    with db.tx() as c:
        already = {r[0] for r in c.execute(
            "SELECT item_id FROM playlist_tracks WHERE playlist_id=?", (pid,)).fetchall()}
        pos_row = c.execute(
            "SELECT COALESCE(MAX(position), -1) FROM playlist_tracks WHERE playlist_id=?", (pid,)).fetchone()
        pos = int(pos_row[0]) + 1
        now = _now()
        for iid in ids:
            if iid in already:
                continue
            c.execute(
                "INSERT INTO playlist_tracks(playlist_id, item_id, position, added_at) VALUES(?,?,?,?)",
                (pid, iid, pos, now),
            )
            already.add(iid)
            pos += 1
            added += 1
        c.execute("UPDATE playlists SET updated_at=? WHERE id=?", (now, pid))
    out = get_lite(pid, uid)
    out["added"] = added
    return out


def remove_entry(pid, uid, entry_id):
    owned(pid, uid)
    row = db.row("SELECT id, position FROM playlist_tracks WHERE id=? AND playlist_id=?", (entry_id, pid))
    if not row:
        raise HTTPException(404, "Track not in this playlist")
    with db.tx() as c:
        c.execute("DELETE FROM playlist_tracks WHERE id=? AND playlist_id=?", (entry_id, pid))
        c.execute(
            "UPDATE playlist_tracks SET position=position-1 WHERE playlist_id=? AND position>?",
            (pid, row["position"]),
        )
        c.execute("UPDATE playlists SET updated_at=? WHERE id=?", (_now(), pid))
    return get_lite(pid, uid)


def reorder(pid, uid, entry_ids):
    owned(pid, uid)
    ids = [int(i) for i in (entry_ids or [])]
    have = [r["id"] for r in db.rows(
        "SELECT id FROM playlist_tracks WHERE playlist_id=? ORDER BY position, id", (pid,))]
    if sorted(ids) != sorted(have):
        raise HTTPException(400, "Order must include every track in the playlist once")
    now = _now()
    with db.tx() as c:
        # two-step so UNIQUE(position) is never assumed; positions stay unique after commit
        for i, eid in enumerate(ids):
            c.execute("UPDATE playlist_tracks SET position=? WHERE id=? AND playlist_id=?",
                      (100000 + i, eid, pid))
        for i, eid in enumerate(ids):
            c.execute("UPDATE playlist_tracks SET position=? WHERE id=? AND playlist_id=?",
                      (i, eid, pid))
        c.execute("UPDATE playlists SET updated_at=? WHERE id=?", (now, pid))
    return get_lite(pid, uid)
