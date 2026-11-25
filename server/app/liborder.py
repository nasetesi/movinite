"""1.6: the order libraries are listed in (sidebar, phone Libraries tab, home page, Settings, the Android app).

One server-wide order, set by admins (Settings -> Libraries: drag and drop, or the up / down buttons).
Default order by type, top to bottom:  Movies (movies) < TV Shows (tv) < Other videos (other) < Music (music);
a type this version doesn't know goes last.  A new library goes right after the last library of its type;
with none of its type yet, right before the first library of a later type; otherwise at the end -- the rest of
an admin's custom order is never changed.
"""

KIND_RANK = {"movies": 1, "tv": 2, "other": 3, "music": 4}
ORDER_SQL = "ORDER BY COALESCE(sort_order, 1000000000), name COLLATE NOCASE, id"


def rank(kind):
    return KIND_RANK.get(kind, 9)


def place(ordered, new):
    """ordered: [(id, kind)] in the current order; new: (id, kind).  Returns the list with `new` inserted."""
    r = rank(new[1])
    same = [i for i, (_, k) in enumerate(ordered) if rank(k) == r]
    if same:
        pos = same[-1] + 1
    else:
        later = [i for i, (_, k) in enumerate(ordered) if rank(k) > r]
        pos = later[0] if later else len(ordered)
    return ordered[:pos] + [new] + ordered[pos:]


def _write(c, ordered):
    for n, (lid, _) in enumerate(ordered, 1):
        c.execute("UPDATE libraries SET sort_order=? WHERE id=?", (n, lid))


def assign_missing(c):
    """Give every library without a position one (migration: all of them, by type then name; later: new ones)."""
    rows = c.execute("SELECT id, kind, sort_order, name FROM libraries").fetchall()
    have = sorted([r for r in rows if r[2] is not None], key=lambda r: (r[2], r[0]))
    todo = [r for r in rows if r[2] is None]
    if not todo:
        return False
    todo.sort(key=lambda r: (rank(r[1]), (r[3] or "").lower(), r[0]))
    ordered = [(r[0], r[1]) for r in have]
    for r in todo:
        ordered = place(ordered, (r[0], r[1]))
    _write(c, ordered)
    return True


def set_order(c, ids):
    """Admin order: `ids` must list every library exactly once."""
    rows = c.execute("SELECT id, kind FROM libraries").fetchall()
    kinds = dict(rows)
    if sorted(ids) != sorted(kinds):
        raise ValueError("The new order must list every library exactly once")
    _write(c, [(i, kinds[i]) for i in ids])
