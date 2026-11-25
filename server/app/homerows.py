"""1.4.1: Home rows / smart views for movie libraries -- Recommended, Recently released, Recently added, Top movies.

Each function returns a list of (item_id, reason) in display order. Everything is computed locally from data
that is already cached (TMDB details incl. their "recommendations" list, genres, collections, watch progress),
so building a row never calls TMDB.
"""
import hashlib
import json
import math
import time
from datetime import date, timedelta

from . import db, titles

ROWS = {
    "recommended": "Recommended for you",
    "released": "Recently released",
    "added": "Recently added",
    "top": "Top movies",
}
PIN_ROWS = ("recommended", "top")
TOP_M = 500            # weighted rating: votes needed to count as much as the library average (IMDb formula)
TOP_MIN_VOTES = 50     # never list a film with fewer TMDB votes than this under Top movies
RELEASED_DAYS = 730    # "recently released" window (about 2 years)
SEED_MIN_S = 300       # a movie counts as "watched some of it" after 5 minutes


def _movies(lib_id):
    """One row per TMDB movie in the library, with its cached metadata.  1.7: the row's id is the film's best
    version (highest resolution, then bitrate, then size) -- it used to be the first file found."""
    best = {r["tmdb_id"]: r["id"] for r in db.rows(
        "SELECT id, tmdb_id FROM (SELECT id, tmdb_id, ROW_NUMBER() OVER (PARTITION BY tmdb_id ORDER BY " + titles.order_sql() +
        ") rn FROM items WHERE library_id=? AND kind='movie' AND tmdb_id IS NOT NULL AND meta_status IN ('matched','manual')) "
        "WHERE rn=1", (lib_id,))}
    rows = db.rows(
        "SELECT MIN(i.id) id, i.tmdb_id, MAX(i.added_at) added_at, md.title, md.year, md.release_date, md.rating, "
        "md.vote_count, md.collection_id, md.collection_name FROM items i JOIN metadata md ON md.kind='movie' "
        "AND md.tmdb_id=i.tmdb_id WHERE i.library_id=? AND i.kind='movie' AND i.meta_status IN ('matched','manual') "
        "GROUP BY i.tmdb_id", (lib_id,))
    for r in rows:
        r["id"] = best.get(r["tmdb_id"], r["id"])
    return rows


def _pins(row):
    return {r["item_id"]: r["mode"] for r in db.rows("SELECT item_id, mode FROM home_pins WHERE row=?", (row,))}


def _wr_fn(movies):
    rated = [m for m in movies if m["vote_count"] and m["rating"] is not None]
    c = (sum(m["rating"] for m in rated) / len(rated)) if rated else 6.5

    def wr(m):
        v, r = m["vote_count"] or 0, m["rating"] or 0
        return (v / (v + TOP_M)) * r + (TOP_M / (v + TOP_M)) * c
    return wr, c


def _apply_pins(row, ranked):
    """ranked: [(item_id, reason)].  Admin pins go first, hidden ones are dropped.
    1.7: a pin counts for the film, whichever of its files (versions) it was set on."""
    pins = _pins(row)
    if not pins:
        return ranked
    ids = list({i for i, _ in ranked} | set(pins))
    keys = {}
    for chunk in range(0, len(ids), 500):
        part = ids[chunk:chunk + 500]
        for r in db.rows("SELECT id, " + titles.key_sql() + " k FROM items WHERE id IN (%s)" % ",".join("?" * len(part)), part):
            keys[r["id"]] = r["k"]
    by_key = {keys[i]: i for i, _ in ranked if i in keys}
    pk = {}
    for i, m in pins.items():
        k = keys.get(i)
        if k is not None:
            pk[k] = m
    pins = {}
    for k, m in pk.items():
        pins[by_key.get(k) or next((i for i, kk in keys.items() if kk == k), None)] = m
    for i, _ in ranked:
        if keys.get(i) in pk:
            pins[i] = pk[keys[i]]
    pins.pop(None, None)
    have = {i for i, _ in ranked}
    first = [(i, "Picked by an admin") for i, m in pins.items() if m == 1]
    first = [(i, r) for i, r in first if i in have or db.row("SELECT 1 x FROM items WHERE id=?", (i,))]
    pinned = {i for i, _ in first}
    return first + [(i, r) for i, r in ranked if pins.get(i, 0) != -1 and i not in pinned]


def recently_released(lib_id, today=None):
    today = today or date.today()
    lo = (today - timedelta(days=RELEASED_DAYS)).isoformat()
    ms = [m for m in _movies(lib_id) if m["release_date"] and m["release_date"] <= today.isoformat()]
    ms.sort(key=lambda m: (m["release_date"], m["id"]), reverse=True)
    out = [(m["id"], "recent") for m in ms if m["release_date"] >= lo]
    if len(out) < 12:            # few new films in this library: top the row up with the next-newest ones
        out += [(m["id"], "older") for m in ms[len(out):12]]
    return out


def recently_added(lib_id):
    """1.7: one entry per film (its best version), newest addition first."""
    return [(r["id"], None) for r in db.rows(
        "SELECT id FROM items WHERE library_id=? AND kind='movie' AND " + titles.best_in_lib_cond("id") + " "
        "ORDER BY (SELECT MAX(i2.added_at) FROM items i2 WHERE i2.library_id=items.library_id AND " + titles.key_sql("i2") +
        "=" + titles.key_sql("items") + ") DESC, id DESC", (lib_id, lib_id))]


def top_movies(lib_id):
    ms = _movies(lib_id)
    wr, _c = _wr_fn(ms)
    today = date.today().isoformat()
    ms = [m for m in ms if (m["vote_count"] or 0) >= TOP_MIN_VOTES and (m["release_date"] or "") <= today]
    ms.sort(key=lambda m: (-wr(m), -(m["vote_count"] or 0), m["id"]))
    return _apply_pins("top", [(m["id"], "%.1f" % wr(m)) for m in ms])


def _history(user_id, lib_id):
    return db.rows(
        "SELECT p.item_id, p.position, p.duration, p.watched, p.updated_at, i.tmdb_id FROM progress p "
        "JOIN items i ON i.id=p.item_id WHERE p.user_id=? AND i.library_id=? AND i.kind='movie' "
        "ORDER BY p.updated_at DESC", (user_id, lib_id))


def _jitter(user_id, day, tid):
    return int(hashlib.md5(("%s|%s|%s" % (user_id, day, tid)).encode()).hexdigest()[:6], 16) / 0xFFFFFF


def _compute_recommended(user_id, lib_id, day):
    ms = _movies(lib_id)
    if not ms:
        return [], "none"
    by_tid = {m["tmdb_id"]: m for m in ms}
    wr, c = _wr_fn(ms)
    genres = {}
    for r in db.rows("SELECT g.tmdb_id, g.genre FROM movie_genres g JOIN items i ON i.tmdb_id=g.tmdb_id AND "
                     "i.library_id=? AND i.kind='movie' GROUP BY g.tmdb_id, g.genre", (lib_id,)):
        genres.setdefault(r["tmdb_id"], set()).add(r["genre"])
    hist = _history(user_id, lib_id)
    seen = set()          # finished or started: never recommended (started ones are in Continue watching)
    seeds = []
    finished = set()
    for h in hist:
        if not h["tmdb_id"]:
            continue
        if h["watched"] or (h["position"] or 0) > 30:
            seen.add(h["tmdb_id"])
        if (h["watched"] or (h["position"] or 0) >= SEED_MIN_S) and h["tmdb_id"] in by_tid and \
                h["tmdb_id"] not in [s for s, _ in seeds]:
            seeds.append((h["tmdb_id"], h["updated_at"]))
            if h["watched"]:
                finished.add(h["tmdb_id"])
    seeds = seeds[:25]
    cands = [m for m in ms if m["tmdb_id"] not in seen]

    def fallback(exclude):
        """No history (or not enough): best-rated, well-known unwatched films, mixed across the top genres."""
        tops = [g for g, _n in sorted(((g, sum(1 for t in genres if g in genres[t])) for g in
                                       {x for s in genres.values() for x in s}), key=lambda x: -x[1])][:6]
        score = lambda m: wr(m) + 0.35 * math.log10(1 + (m["vote_count"] or 0)) + 0.05 * _jitter(user_id, day, m["tmdb_id"])  # noqa: E731
        pool = sorted([m for m in cands if m["tmdb_id"] not in exclude], key=lambda m: -score(m))
        lanes = [[m for m in pool if g in genres.get(m["tmdb_id"], ())] for g in tops] or [pool]
        out, used = [], set()
        while any(lanes):
            for lane in lanes:
                while lane and lane[0]["tmdb_id"] in used:
                    lane.pop(0)
                if lane:
                    m = lane.pop(0)
                    used.add(m["tmdb_id"])
                    out.append((m["id"], "Highly rated"))
        out += [(m["id"], "Highly rated") for m in pool if m["tmdb_id"] not in used]
        return out

    if not seeds:
        return fallback(set()), "fallback"
    recs = {}
    ids = [s for s, _ in seeds]
    for r in db.rows("SELECT tmdb_id, rec_id, rank FROM movie_recs WHERE tmdb_id IN (%s)" % ",".join("?" * len(ids)), ids):
        recs.setdefault(r["tmdb_id"], {})[r["rec_id"]] = r["rank"]
    rev = {}
    cand_ids = [m["tmdb_id"] for m in cands]
    for k in range(0, len(cand_ids), 500):
        part = cand_ids[k:k + 500]
        for r in db.rows("SELECT tmdb_id, rec_id FROM movie_recs WHERE tmdb_id IN (%s) AND rec_id IN (%s)"
                         % (",".join("?" * len(part)), ",".join("?" * len(ids))), part + ids):
            rev.setdefault(r["tmdb_id"], set()).add(r["rec_id"])
    # continue the franchise: the first unwatched film after the latest one watched, per collection
    nxt = {}
    for sid, _t in seeds:
        s = by_tid[sid]
        if not s["collection_id"] or sid not in finished:   # only after you finished one
            continue
        later = sorted([m for m in ms if m["collection_id"] == s["collection_id"] and m["tmdb_id"] not in finished and
                        (m["release_date"] or "") > (s["release_date"] or "")], key=lambda m: m["release_date"] or "")
        # the very next film -- if you already started it, it is in Continue watching instead
        if later and later[0]["tmdb_id"] not in seen and later[0]["tmdb_id"] not in nxt:
            nxt[later[0]["tmdb_id"]] = s["collection_name"] or "the collection"
    scored = []
    for m in cands:
        t = m["tmdb_id"]
        g = genres.get(t, set())
        best, why, total = 0.0, None, 0.0
        for k, (sid, _ts) in enumerate(seeds):
            w = 0.9 ** k
            part = 0.0
            if t in recs.get(sid, {}):
                part += 3.0 * (1 - recs[sid][t] / 25.0)
            if sid in rev.get(t, ()):
                part += 1.0
            sg = genres.get(sid, set())
            if g and sg:
                part += 1.5 * len(g & sg) / len(g | sg)
            if m["collection_id"] and m["collection_id"] == by_tid[sid]["collection_id"]:
                part += 1.0
            part *= w
            total += part
            if part > best:
                best, why = part, "Because you watched " + (by_tid[sid]["title"] or "a movie you liked")
        if t in nxt:
            total += 6.0
            why = "Next in " + nxt[t]
        total += 0.3 * (wr(m) - c) + 0.05 * _jitter(user_id, day, t)
        if total > 0.4:
            scored.append((total, m["id"], why or "Popular pick"))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out = [(i, r) for _s, i, r in scored]
    if len(out) < 40:
        have = {i for i, _ in out}
        out += [x for x in fallback(set()) if x[0] not in have]
    return out, "history"


def recommended(user_id, lib_id):
    """Per user; cached until the day changes or the user's watch history / the library / admin pins change."""
    day = date.today().isoformat()
    h = db.row("SELECT COUNT(*) n, COALESCE(SUM(watched),0) w, GROUP_CONCAT(item_id) ids FROM (SELECT p.item_id, p.watched "
               "FROM progress p JOIN items i ON i.id=p.item_id WHERE p.user_id=? AND i.library_id=? AND i.kind='movie' "
               "AND (p.watched=1 OR p.position>30) ORDER BY p.item_id)", (user_id, lib_id))
    lib = db.row("SELECT COUNT(*) n, COALESCE(MAX(id),0) mx FROM items WHERE library_id=? AND kind='movie'", (lib_id,))
    cat = db.row("SELECT COUNT(*) n FROM movie_recs")["n"]
    pins = db.row("SELECT COUNT(*) n, COALESCE(SUM(mode),0) s, COALESCE(MAX(created_at),0) t FROM home_pins "
                  "WHERE row='recommended'")
    sig = "|".join(str(x) for x in ("v17", day, h["n"], h["w"], hashlib.md5((h["ids"] or "").encode()).hexdigest()[:10],
                                    lib["n"], lib["mx"], cat // 50, pins["n"], pins["s"], pins["t"]))
    row = db.row("SELECT sig, data FROM rec_cache WHERE user_id=? AND library_id=?", (user_id, lib_id))
    if row and row["sig"] == sig:
        d = json.loads(row["data"])
        return [tuple(x) for x in d["items"]], d["basis"]
    ranked, basis = _compute_recommended(user_id, lib_id, day)
    ranked = _apply_pins("recommended", ranked)
    done = {r["item_id"] for r in db.rows("SELECT p.item_id FROM progress p JOIN items i ON i.id=p.item_id WHERE "
                                          "p.user_id=? AND i.library_id=? AND (p.watched=1 OR p.position>30)",
                                          (user_id, lib_id))}
    ranked = [x for x in ranked if x[0] not in done][:200]
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO rec_cache(user_id, library_id, sig, computed_at, data) VALUES(?,?,?,?,?)",
                  (user_id, lib_id, sig, int(time.time()), json.dumps({"items": ranked, "basis": basis})))
    return ranked, basis


def row(user_id, lib_id, key):
    """-> (ranked [(item_id, reason)], note)"""
    if key == "recommended":
        ranked, basis = recommended(user_id, lib_id)
        note = {"history": "Based on what you have watched, with the next film in franchises you started",
                "fallback": "Highly rated films you haven't watched yet -- this gets personal once you watch something"
                }.get(basis, "")
        return ranked, note
    if key == "released":
        rr = recently_released(lib_id)
        n = sum(1 for _i, r in rr if r == "recent")
        return rr, ("Newest releases first (TMDB release date, last 2 years)" if n >= 12 else
                    "Newest releases first: %d from the last 2 years, then the next-newest" % n)
    if key == "added":
        return recently_added(lib_id), "Newest additions to the library first"
    if key == "top":
        return top_movies(lib_id), ("Best TMDB scores, weighted by number of votes (at least %d) so a few perfect "
                                    "votes don't win" % TOP_MIN_VOTES)
    raise KeyError(key)
