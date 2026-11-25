"""1.7: one title, several files -- versions inside a library and copies on other libraries (mirrored shares).

* A *title key* says which files are the same film / episode:
    movies    matched: TMDB id + edition;  unmatched: title + year + edition (Director's Cut etc. stay separate)
    episodes  the show's folder name + season + episode
    anything else is its own title.
* *Versions* = files with the same key in one library (e.g. a 4K and a 1080p file of the same film).  They are
  always ordered by resolution, highest first (4K > 2K/1440p > 1080p > 720p > SD), then bitrate, then file size;
  the first one is what a poster opens and plays.
* *Copies* = files with the same key in other libraries (the same film on a second, redundant share).  Views that
  span libraries (home page, Continue watching, My List, search) show a title once, from a library whose share is
  online; watch progress is kept for every copy and version at the same time.
"""
from . import db, sharehealth

# resolution rank (also used for the poster badge): 4 = 4K, 3 = 2K (1440p), 2 = 1080p, 1 = 720p, 0 = SD / unknown
RES_LABEL = {4: "4K", 3: "2K", 2: "1080p", 1: "720p", 0: "SD"}


def res_rank(w, h):
    w, h = w or 0, h or 0
    if w >= 3200 or h >= 2000:
        return 4
    if w >= 2400 or h >= 1300:
        return 3
    if w >= 1800 or h >= 1000:
        return 2
    if w >= 1200 or h >= 700:
        return 1
    return 0


def rank_sql(a=""):
    p = a + "." if a else ""
    w, h = "COALESCE(%swidth,0)" % p, "COALESCE(%sheight,0)" % p
    return ("(CASE WHEN {w}>=3200 OR {h}>=2000 THEN 4 WHEN {w}>=2400 OR {h}>=1300 THEN 3 WHEN {w}>=1800 OR {h}>=1000 "
            "THEN 2 WHEN {w}>=1200 OR {h}>=700 THEN 1 ELSE 0 END)").format(w=w, h=h)


def key_sql(a="items"):
    """SQL expression for the title key of the row `a` (a table name or alias)."""
    return ("(CASE WHEN {a}.kind='movie' AND {a}.tmdb_id IS NOT NULL THEN 'm'||{a}.tmdb_id||'|'||lower(COALESCE({a}.edition,'')) "
            "WHEN {a}.kind='movie' THEN 'n'||lower(COALESCE({a}.title,''))||'|'||COALESCE({a}.year,'')||'|'||lower(COALESCE({a}.edition,'')) "
            "WHEN {a}.kind='episode' AND {a}.show IS NOT NULL AND {a}.episode IS NOT NULL THEN "
            "'e'||lower({a}.show)||'|'||COALESCE({a}.season,'')||'|'||{a}.episode "
            "ELSE 'i'||{a}.id END)").format(a=a)


def order_sql(a=""):
    """Best version first: resolution, then bitrate, then size (then the oldest id, so the order is stable)."""
    p = a + "." if a else ""
    return "%s DESC, COALESCE(%sbitrate,0) DESC, COALESCE(%ssize,0) DESC, %sid" % (rank_sql(a), p, p, p)


def best_in_lib_cond(col="id"):
    """SQL condition (one ? = library id): `col` is the best version of its title in that library."""
    return ("%s IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY %s ORDER BY %s) rn FROM items "
            "WHERE library_id=?) WHERE rn=1)" % (col, key_sql("items"), order_sql()))


def version_counts(lib_id):
    """{title key: [resolution ranks, best first]} for titles with more than one file in the library."""
    out = {}
    for r in db.rows("SELECT %s k, %s r FROM items WHERE library_id=? ORDER BY %s" % (key_sql(), rank_sql(), order_sql()),
                     (lib_id,)):
        out.setdefault(r["k"], []).append(r["r"])
    return {k: v for k, v in out.items() if len(v) > 1}


def key_of(item_id):
    r = db.row("SELECT %s k FROM items WHERE id=?" % key_sql(), (item_id,))
    return r["k"] if r else None


def same_title_ids(item_id):
    """Every file of this title in every library (versions and copies), this one included."""
    k = key_of(item_id)
    if not k:
        return []
    if k.startswith("i"):
        return [item_id]
    return ids_for_key(k)


def ids_for_key(k):
    """Every file with this title key (narrowed by an indexed column first)."""
    if k[0] == "m":
        return [r["id"] for r in db.rows("SELECT id FROM items WHERE kind='movie' AND tmdb_id=? AND %s=?" % key_sql(),
                                         (int(k[1:].split("|", 1)[0]), k))]
    if k[0] == "n":
        return [r["id"] for r in db.rows("SELECT id FROM items WHERE kind='movie' AND tmdb_id IS NULL AND %s=?" % key_sql(), (k,))]
    if k[0] == "e":
        return [r["id"] for r in db.rows("SELECT id FROM items WHERE kind='episode' AND episode=? AND %s=?" % key_sql(),
                                         (int(k.rsplit("|", 1)[1]), k))]
    return [int(k[1:])]


def file_title_ids(item_id):
    """Every movie file with the same file-name title, year and edition, in every library."""
    it = db.row("SELECT kind, title, year, edition FROM items WHERE id=?", (item_id,))
    if not it or it["kind"] != "movie":
        return [item_id] if it else []
    return [r["id"] for r in db.rows(
        "SELECT id FROM items WHERE kind='movie' AND lower(title)=lower(?) AND year IS ? "
        "AND lower(COALESCE(edition,''))=lower(?)",
        (it["title"], it["year"], it["edition"] or ""))]


def movie_match_ids(item_id):
    """1.7.1: every version and copy that should follow a Fix match / Accept / unmatch.
    Unions the current title key (TMDB id when already matched, otherwise file name) with
    other files of the same file-name title + year + edition, so a 4K that is already
    (wrongly) matched and a still-unmatched 1080p, or the copy on the other share, all
    pick up the new match."""
    ids = set(same_title_ids(item_id) or [item_id])
    ids.update(file_title_ids(item_id))
    return sorted(ids)


def lib_down():
    """{library id: True} for libraries on a share that is offline or not answering right now."""
    out = {}
    for l in db.rows("SELECT id, share_id FROM libraries WHERE share_id IS NOT NULL"):
        h = sharehealth.get(l) or {}
        if h.get("state") in ("offline", "stuck"):
            out[l["id"]] = True
    return out


def lib_rank():
    from . import liborder
    return {r["id"]: n for n, r in enumerate(db.rows("SELECT id FROM libraries " + liborder.ORDER_SQL))}


def version_sort_key(it):
    return (-res_rank(it.get("width"), it.get("height")), -(it.get("bitrate") or 0), -(it.get("size") or 0), it.get("id") or 0)


def collapse(items, key="title_key", down=None, order=None):
    """Keep one entry per title key, in the order of first appearance.  The entry kept for a title is the best
    version from the first library (admin order) whose share is up; `items` need library_id, width, height,
    bitrate/size optional and the key field."""
    down = lib_down() if down is None else down
    order = lib_rank() if order is None else order
    groups, first = {}, []
    for it in items:
        k = it.get(key) or ("i%s" % it.get("id"))
        if k not in groups:
            groups[k] = []
            first.append(k)
        groups[k].append(it)
    out = []
    for k in first:
        g = groups[k]
        g.sort(key=lambda it: (1 if down.get(it.get("library_id")) else 0, order.get(it.get("library_id"), 999))
               + version_sort_key(it))
        best = dict(g[0])
        best["copies"] = len({x.get("library_id") for x in g})
        out.append(best)
    return out


def online_twin(item_id, prefer_same_res=True):
    """The best file of the same title on a library that is up (None when this one is fine or there is none)."""
    down = lib_down()
    it = db.row("SELECT id, library_id, width, height FROM items WHERE id=?", (item_id,))
    if not it or not down.get(it["library_id"]):
        return None
    ids = [i for i in same_title_ids(item_id) if i != item_id]
    if not ids:
        return None
    rows = db.rows("SELECT id, library_id, width, height, bitrate, size FROM items WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
    rows = [r for r in rows if not down.get(r["library_id"])]
    if not rows:
        return None
    want = res_rank(it["width"], it["height"])
    order = lib_rank()
    rows.sort(key=lambda r: ((0 if res_rank(r["width"], r["height"]) == want else 1) if prefer_same_res else 0,
                             order.get(r["library_id"], 999)) + version_sort_key(r))
    return rows[0]["id"]


def mirror_groups(kind):
    """Libraries of one type that hold (mostly) the same titles -- e.g. the same movies on two redundant shares.
    Returns [[library ids in admin order], ...]; a library that mirrors nothing is a group of its own.
    Two libraries are mirrors when at least half of the smaller one's titles are also in the other."""
    from . import liborder
    libs = [r["id"] for r in db.rows("SELECT id FROM libraries WHERE kind=? " + liborder.ORDER_SQL, (kind,))]
    if len(libs) < 2:
        return [[l] for l in libs]
    keys = {}
    for l in libs:
        if kind == "tv":
            ks = {r["k"] for r in db.rows("SELECT DISTINCT lower(show) k FROM items WHERE library_id=? AND kind='episode' "
                                          "AND show IS NOT NULL", (l,))}
        else:
            ks = {r["k"] for r in db.rows("SELECT DISTINCT %s k FROM items WHERE library_id=?" % key_sql(), (l,))}
        keys[l] = ks
    parent = {l: l for l in libs}

    def find(x):
        while parent[x] != x:
            x = parent[x]
        return x
    for i, a in enumerate(libs):
        for b in libs[i + 1:]:
            ka, kb = keys[a], keys[b]
            small = min(len(ka), len(kb))
            if small and len(ka & kb) * 2 >= small:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra
    groups = {}
    for l in libs:
        groups.setdefault(find(l), []).append(l)
    return sorted(groups.values(), key=lambda g: libs.index(g[0]))


def backfill_progress(c):
    """1.7 migration: copy existing watch progress to the other files of the same title that have none yet
    (inserts only -- no existing row is changed)."""
    rows = c.execute("SELECT p.user_id, p.item_id, p.position, p.duration, p.watched, p.updated_at, %s k, i.kind "
                     "FROM progress p JOIN items i ON i.id=p.item_id ORDER BY p.updated_at" % key_sql("i")).fetchall()
    n = 0
    for uid, iid, pos, dur, watched, upd, k, kind in rows:
        if not k or k.startswith("i"):
            continue
        for (oid,) in c.execute("SELECT id FROM items WHERE kind=? AND %s=? AND id<>?" % key_sql(), (kind, k, iid)).fetchall():  # noqa
            cur = c.execute("INSERT OR IGNORE INTO progress(user_id, item_id, position, duration, watched, updated_at) "
                            "VALUES(?,?,?,?,?,?)", (uid, oid, pos, dur, watched, upd))
            n += cur.rowcount
    return n
