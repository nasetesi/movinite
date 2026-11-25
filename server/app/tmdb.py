"""TMDB (themoviedb.org) metadata: matching, local cache, images.

* Works with a v3 API key (sent as ?api_key=) or a v4 "API Read Access Token" (sent as Bearer).
* Rate limited client side (MS_TMDB_MAX_RPS, default 20 req/s, well under TMDB's limit) and honours
  HTTP 429 Retry-After. Network errors never break scanning or browsing -- items simply keep their
  filename/tag metadata and are retried on the next scan.
* Everything is cached: details in the `metadata` / `tmdb_episodes` tables, images in data/thumbs.

This product uses the TMDB API but is not endorsed or certified by TMDB.
"""
import difflib
import hashlib
import json
import logging
import math
import os
import queue
from concurrent.futures import ThreadPoolExecutor
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from . import config, db, media, settings

log = logging.getLogger("media-server.tmdb")

USER_AGENT = "MediaServer/1.3 (self-hosted)"
RETRY_NOMATCH_S = 7 * 86400
REFRESH_S = 30 * 86400
MATCH_THRESHOLD = 0.72


class TMDBError(Exception):
    pass


class TMDBAuthError(TMDBError):
    pass


class TMDBNetworkError(TMDBError):
    """TMDB unreachable: stop the current run instead of trying every item."""


# ---------------------------------------------------------------------------
# HTTP client with rate limiting
# ---------------------------------------------------------------------------
class _Limiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self):
        rps = max(1.0, config.TMDB_MAX_RPS)
        with self.lock:
            now = time.monotonic()
            if self.next_at > now:
                time.sleep(self.next_at - now)
                now = time.monotonic()
            self.next_at = now + 1.0 / rps

    def pause(self, seconds):
        with self.lock:
            self.next_at = max(self.next_at, time.monotonic() + seconds)


_limiter = _Limiter()
stats = {"requests": 0, "rate_limited": 0, "errors": 0, "last_error": None}


def _is_v4_token(key):
    return key.startswith("eyJ") and key.count(".") == 2


def request(path, params=None, key=None, retries=4):
    key = (key if key is not None else settings.tmdb_key()).strip()
    if not key:
        raise TMDBAuthError("No TMDB API key set")
    params = dict(params or {})
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if _is_v4_token(key):
        headers["Authorization"] = "Bearer " + key
    else:
        params["api_key"] = key
    url = config.TMDB_API_BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    attempt = 0
    while True:
        attempt += 1
        _limiter.wait()
        stats["requests"] += 1
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise TMDBAuthError("TMDB rejected the API key (401)")
            if e.code == 404:
                raise TMDBError("not found")
            if e.code == 429 and attempt <= retries + 2:
                stats["rate_limited"] += 1
                try:
                    wait = float(e.headers.get("Retry-After") or 2)
                except ValueError:
                    wait = 2
                wait = min(max(wait, 1), 30)
                log.info("TMDB rate limit hit, waiting %.0fs", wait)
                _limiter.pause(wait)
                continue
            if 500 <= e.code < 600 and attempt <= retries:
                time.sleep(min(2 ** attempt, 15))
                continue
            stats["errors"] += 1
            stats["last_error"] = "HTTP %s" % e.code
            raise TMDBError("TMDB HTTP %s" % e.code)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            if attempt <= min(retries, 2):
                time.sleep(attempt)
                continue
            stats["errors"] += 1
            stats["last_error"] = str(e)
            raise TMDBNetworkError("Cannot reach TMDB: %s" % e)


def test_key(key):
    """Return (ok, message)."""
    try:
        request("/configuration", key=key, retries=1)
        return True, "TMDB key works"
    except TMDBAuthError as e:
        return False, str(e)
    except TMDBError as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# images
# ---------------------------------------------------------------------------
def image_url(path, size):
    return "%s/%s%s" % (config.TMDB_IMAGE_BASE, size, path) if path else None


PROFILE_SIZE = "h632"      # 1.4.6 (was w185): cast photos are shown up to ~190 px wide, sharp on hi-dpi screens
POSTER_LARGE = "w780"      # 1.4.6: the details page poster is up to 550 px wide


def _thumb_name(path, size):
    return hashlib.sha1(("tmdb|%s|%s" % (size, path)).encode()).hexdigest() + ".jpg"


def large_poster(kind, tmdb_id):
    """1.4.6: a high-resolution poster (w780) for the details page, downloaded the first time it is shown, then cached.
    Returns the file name in data/thumbs, or None (no poster on TMDB / TMDB unreachable -> the page keeps the w500 one)."""
    m = cached(kind, tmdb_id)
    if not m or not m["poster_path"]:
        return None
    name = _thumb_name(m["poster_path"], POSTER_LARGE)
    if (config.THUMB_DIR / name).exists():
        return name
    if time.time() - _LARGE_FAILED.get(m["poster_path"], 0) < 600:   # TMDB unreachable a moment ago: don't wait again
        return None
    name = download_image(m["poster_path"], POSTER_LARGE)
    if not name:
        _LARGE_FAILED[m["poster_path"]] = time.time()
    return name


_LARGE_FAILED = {}


def download_image(path, size):
    """Download a TMDB image into data/thumbs; returns the file name (cached) or None."""
    if not path or not re.match(r"^/[A-Za-z0-9_.-]+\.(jpg|jpeg|png|webp)$", path):
        return None
    name = _thumb_name(path, size)
    out = config.THUMB_DIR / name
    if out.exists() and out.stat().st_size > 0:
        return name
    url = image_url(path, size)
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read(15 * 1024 * 1024)
            if not data:
                return None
            tmp = out.with_name("%s.%d.part" % (name, threading.get_ident()))
            tmp.write_bytes(data)
            os.replace(tmp, out)
            return name
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1 + attempt)
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(1 + attempt)
    return None


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------
def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"^(the|a|an) ", "", s.strip())
    return s.strip()


def _year_of(d):
    m = re.match(r"^(\d{4})", d or "")
    return int(m.group(1)) if m else None


def score(result, title, year, kind):
    names = [result.get("title"), result.get("original_title")] if kind == "movie" else \
        [result.get("name"), result.get("original_name")]
    t = norm(title)
    sim = max((difflib.SequenceMatcher(None, t, norm(n)).ratio() for n in names if n), default=0)
    ry = _year_of(result.get("release_date") if kind == "movie" else result.get("first_air_date"))
    sc = sim
    if year and ry:
        if ry == year:
            sc += 0.25
        elif abs(ry - year) == 1:
            sc += 0.1
        else:
            sc -= 0.25
    sc += min(0.05, math.log10(1 + float(result.get("popularity") or 0)) / 100)
    return sc, sim


def best_match(results, title, year, kind):
    best, best_sc = None, 0
    for r in results[:20]:
        sc, sim = score(r, title, year, kind)
        if sim < 0.6:
            continue
        if sc > best_sc:
            best, best_sc = r, sc
    return best if best is not None and best_sc >= MATCH_THRESHOLD else None


def search(kind, query, year=None, page=1):
    kind = "movie" if kind == "movie" else "tv"
    params = {"query": query, "include_adult": "false", "language": settings.tmdb_language(), "page": page}
    if year:
        params["year" if kind == "movie" else "first_air_date_year"] = int(year)
    return request("/search/%s" % kind, params).get("results") or []


def find_match(kind, title, year):
    if not title:
        return None
    results = search(kind, title, year) if year else []
    m = best_match(results, title, year, kind)
    if m is None:
        results = search(kind, title)
        m = best_match(results, title, year, kind)
    return m


# ---------------------------------------------------------------------------
# 1.3 movie matcher: year-aware, shorter-title / sequel / typo retries, confidence + review flags
# ---------------------------------------------------------------------------
REVIEW_BELOW = 0.75        # automatic matches under this confidence show up in "Needs review"
_ROMAN = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10",
          "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
          "nine": "9", "ten": "10"}
_STOP = {"the", "a", "an", "of", "and", "to", "in", "on", "for", "at", "with", "de", "la", "le", "el"}


def _toks(s):
    t = norm(s)
    t = re.sub(r"\b(?:[a-z0-9] ){2,}[a-z0-9]\b", lambda m: m.group(0).replace(" ", ""), t)   # "s w a t" -> "swat"
    return [_ROMAN.get(w, w) for w in t.split()]


def similarity(a, b):
    """max of character similarity and word-set overlap (handles re-ordered titles)."""
    ta, tb = _toks(a), _toks(b)
    if not ta or not tb:
        return 0.0
    seq = difflib.SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    sa, sb = set(ta), set(tb)
    jac = len(sa & sb) / len(sa | sb)
    return max(seq, jac)


def _sig(s):
    t = _toks(s)
    return {w for w in t if w not in _STOP and len(w) > 1} or set(t)


def _contained(query, result):
    """How well the two titles nest. -> (n_shared_words, direction) direction 'r_in_q' = file name has extra words
    ("F1 The Movie" / "F1"), 'q_in_r' = TMDB title has extra words ("Anchorman 2" / "Anchorman 2: The Legend ...")."""
    q, r = _sig(query), _sig(result)
    if not q or not r:
        return 0, None
    if r <= q:
        return len(r), "r_in_q"
    if q <= r:
        return len(q), ("q_in_r" if len(r) - len(q) <= 2 or len(q) >= 2 else None)
    return 0, None


def title_variants(title):
    """Search strings to try, best first: the title itself, then shorter forms. -> [(query, how)]"""
    t = re.sub(r"\s+", " ", (title or "").strip())
    out = []

    def add(q, how):
        q = re.sub(r"\s+", " ", (q or "").strip(" -:._,"))
        if q and len(q) >= 2 and q.lower() not in [x[0].lower() for x in out]:
            out.append((q, how))
    add(t, "title")
    add(re.sub(r"\s+the\s+movie$", "", t, flags=re.I), "without 'The Movie'")
    ep = re.search(r"\bepisode\s+([ivx]+|\d+)\b\s*[-:]?\s*", t, re.I)
    if ep:
        add(t[:ep.start()], "series name")
        add(t[ep.end():], "episode title")
        add(t[:ep.start()] + " " + t[ep.end():], "without episode number")
    for sep in (" - ", ": ", " -", "- "):
        if sep in t:
            left, right = t.split(sep, 1)
            add(left, "before the dash")
            add(right, "after the dash")
            break
    m = re.match(r"^(.*?\S)\s+(\d{1,2}|ii|iii|iv|v|vi|vii|viii)$", t, re.I)
    if m:
        add(m.group(1), "sequel")
    words = t.split()
    if words and len(words) <= 4 and len(words[-1]) >= 5 and words[-1].isalpha():
        # TMDB matches the last word as a prefix: "Dinos" finds "Dinosaur" when the file says "Dinosour"
        add(" ".join(words[:-1] + [words[-1][:max(3, round(len(words[-1]) * 0.6))]]), "prefix")
    if len(words) >= 4:
        add(" ".join(words[-3:]), "last words")
        add(" ".join(words[-2:]), "last words")
        add(" ".join(words[:3]), "first words")
    if 2 <= len(words) <= 4:
        for i in range(len(words)):
            if words[i].lower() in _STOP:
                continue
            add(" ".join(words[:i] + words[i + 1:]), "typo")
    return out[:10]


def _latin(name):
    """False for titles that are mostly non-Latin script -- they normalise to a stray word or two."""
    alnum = [c for c in name if c.isalnum()]
    latin = [c for c in unicodedata.normalize("NFKD", name) if c.isascii() and c.isalnum()]
    return bool(alnum) and len(latin) >= 0.8 * len(alnum)


def _evaluate(r, title, year, how, n_results, query=None):
    """-> (confidence, note) for one TMDB result, or (0, None)."""
    names = [n for n in (r.get("title"), r.get("original_title")) if n and _latin(n)]
    if not names:
        return 0, None
    sim = max(similarity(title, n) for n in names)
    if sim >= 0.95 and similarity(title, names[0]) < 0.95 and names[0] == r.get("title"):
        sim = 0.9           # only the original-language title matches ("Money or Love" / "Lóve")
    if query and query != title and how in ("without 'The Movie'", "series name", "before the dash",
                                            "after the dash", "without episode number"):
        sim = max(sim, max(similarity(query, n) for n in names) - 0.03)
    ry = _year_of(r.get("release_date"))
    dy = abs(ry - year) if (ry and year) else None
    if dy is not None and dy > 1:
        return 0, None
    conf, note = 0, None
    if sim >= 0.95:
        conf = {0: 1.0, 1: 0.8}.get(dy, 0.85 if not year else 0.75)
        note = None if dy in (0, None) else "year off by one"
    elif sim >= 0.85:
        conf = sim if dy == 0 else (sim - 0.2 if dy == 1 else sim - 0.15)
        note = None if dy == 0 else "similar title, year %s" % ("off by one" if dy == 1 else "unknown")
    if conf < 0.82:
        if how == "sequel":
            n, d = _contained(query or title, names[0])
            if n and dy == 0:
                conf, note = 0.78, "sequel picked by year"
        else:
            n, d = max((_contained(title, nm) for nm in names), key=lambda x: x[0])
            c2 = 0
            if n >= 2 and d and dy == 0:
                c2 = 0.82
            elif n >= 2 and d and dy == 1:
                c2 = 0.62
            elif n == 1 and dy == 0 and (d == "r_in_q" or (d == "q_in_r" and len(_sig(names[0])) <= 3)):
                c2 = 0.7
            if c2 > conf:
                conf, note = c2, "title contained" + ("" if dy == 0 else ", year off by one")
        if not conf and 0.7 <= sim < 0.85 and dy == 0:
            conf, note = sim - 0.1, "close spelling"
        if not conf and how == "title" and n_results == 1 and dy in (0, 1):
            conf, note = 0.55, "only result for this title and year (alternate title?)"
    if not conf:
        return 0, None
    if how not in ("title", "sequel") and sim < 0.85:
        conf -= 0.03
    conf = round(max(0, min(1, conf + min(0.03, math.log10(1 + float(r.get("popularity") or 0)) / 100))), 3)
    return conf, note


def _is_exact(r, title):
    return any(similarity(title, n) >= 0.95 for n in (r.get("title"), r.get("original_title")) if n and _latin(n))


def _pop(r):
    return float(r.get("popularity") or 0)


def match_movie(title, year, searcher=None):
    """Find the TMDB movie for a parsed file title.

    Returns {"status": "matched"|"review"|"nomatch", "result": dict|None, "confidence": float,
             "note": str|None, "candidate": int|None, "queries": int}
    "review" = nothing safe to apply automatically, but a same-title movie from another year exists (candidate).
    A "matched" result below REVIEW_BELOW confidence is applied but shows up under "Needs review"; it can also
    carry a candidate (the same-title movie) the user can switch to with one click."""
    searcher = searcher or (lambda q, y: search("movie", q, y))
    scored = {}            # tmdb id -> [conf, note, result, how]
    year_listed = set()    # ids TMDB returned for a year-filtered search (it knows a release in that year)
    queries = 0
    best_conf = lambda: max((v[0] for v in scored.values()), default=0)  # noqa: E731

    def consider(res, how, q, with_year):
        for r in res[:20]:
            if with_year:
                year_listed.add(r.get("id"))
            c, note = _evaluate(r, title, year, how, len(res), q)
            if c and c > scored.get(r.get("id"), [0])[0]:
                scored[r.get("id")] = [c, note, r, how]
    seen = []
    for q, how in title_variants(title):
        if queries >= 10 or best_conf() >= 0.95:
            break
        if how in ("typo", "prefix") and best_conf() >= 0.6:
            continue
        res = searcher(q, year) if year else searcher(q, None)
        queries += 1
        if q == title:
            seen = res
        consider(res, how, q, bool(year))
        if how == "title" and best_conf() >= 0.85:
            break
    alt = []               # same title, more than a year off
    if year and best_conf() < 0.85:
        # TMDB's year filter only finds films with a release in that year: look at every year for the same title
        res = searcher(title, None)
        queries += 1
        consider(res, "title", title, False)
        seen = list(seen) + list(res)
    if year:
        for r in seen[:40]:
            ry = _year_of(r.get("release_date"))
            if _is_exact(r, title) and ry and abs(ry - year) > 1 and r not in alt:
                alt.append(r)
    alt.sort(key=lambda r: (r.get("id") in year_listed, _pop(r)), reverse=True)
    wrong_year = alt[0] if alt else None

    best = max(scored.values(), key=lambda v: v[0]) if scored else None
    if best:
        b_conf, b_note, b, b_how = best
        b_exact = _is_exact(b, title)
        # popularity breaks near-ties between a same-title film and a longer/shorter title, and between
        # several films that share the exact title ("Eden" 2024: the obscure one vs. the one people own)
        for c, note, r, how in sorted(scored.values(), key=lambda v: -v[0]):
            if r is b or c < 0.75 or not _is_exact(r, title):
                continue
            if (not b_exact and _pop(r) >= _pop(b)) or (b_exact and _pop(r) >= 1 and _pop(r) >= 10 * _pop(b)):
                b_conf, b_note, b = c, "same title, more popular" + (", " + note if note else ""), r
                b_exact = True
                break
        candidate = None
        if wrong_year and not b_exact:
            n, d = _contained(title, b.get("title") or "")
            weak = b_conf < 0.65 or (b_conf < REVIEW_BELOW and (wrong_year.get("id") in year_listed or _pop(wrong_year) >= _pop(b)))
            if weak:
                b = None        # don't apply a guess when a same-title film exists: let the user pick
            elif b_conf < REVIEW_BELOW or d == "r_in_q" or (b_note or "").startswith("only result"):
                b_conf, candidate = min(b_conf, 0.7), wrong_year["id"]
                b_note = "%s; '%s' (%s) has the exact title" % (b_note or "partial match", wrong_year.get("title"),
                                                                  _year_of(wrong_year.get("release_date")) or "no year")
        if b is not None and b_conf >= 0.5:
            return {"status": "matched", "result": b, "confidence": round(b_conf, 3), "candidate": candidate,
                    "note": b_note, "queries": queries}
    if wrong_year:
        return {"status": "review", "result": None, "confidence": 0, "candidate": wrong_year["id"],
                "note": "Same title on TMDB, but %s instead of %s" % (
                    _year_of(wrong_year.get("release_date")) or "no year", year), "queries": queries}
    return {"status": "nomatch", "result": None, "confidence": 0, "candidate": None, "note": None, "queries": queries}


# ---------------------------------------------------------------------------
# fetching + caching
# ---------------------------------------------------------------------------
def cached(kind, tmdb_id):
    return db.row("SELECT * FROM metadata WHERE kind=? AND tmdb_id=?", (kind, tmdb_id))


def fetch_details(kind, tmdb_id, force=False):
    """Fetch and cache movie/tv details + poster/backdrop. Returns the metadata row."""
    row = cached(kind, tmdb_id)
    if row and not force and time.time() - row["fetched_at"] < REFRESH_S:
        return row
    params = {"language": settings.tmdb_language()}
    if kind == "movie":
        params["append_to_response"] = "release_dates,recommendations,credits"   # 1.4 age rating, 1.4.1 recs, 1.4.3 cast: one request
    d = request("/%s/%d" % (kind, int(tmdb_id)), params)
    title = d.get("title") if kind == "movie" else d.get("name")
    orig = d.get("original_title") if kind == "movie" else d.get("original_name")
    year = _year_of(d.get("release_date") if kind == "movie" else d.get("first_air_date"))
    runtime = d.get("runtime") if kind == "movie" else ((d.get("episode_run_time") or [None])[0])
    poster = download_image(d.get("poster_path"), "w500")
    backdrop = download_image(d.get("backdrop_path"), "w1280")
    genres = json.dumps([g.get("name") for g in d.get("genres") or [] if g.get("name")])
    extra = json.dumps({
        "studios": [x.get("name") for x in d.get("production_companies") or [] if x.get("name")][:5],
        "countries": [x.get("iso_3166_1") for x in d.get("production_countries") or [] if x.get("iso_3166_1")],
        "collection": (d.get("belongs_to_collection") or {}).get("name"),
        "original_language": d.get("original_language"),
    })
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO metadata(kind,tmdb_id,title,original_title,year,overview,tagline,genres,rating,"
                  "vote_count,runtime,poster,backdrop,fetched_at,release_date,imdb_id,poster_path,backdrop_path,extra) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (kind, int(tmdb_id), title, orig, year, d.get("overview"), d.get("tagline"), genres,
                   d.get("vote_average"), d.get("vote_count"), runtime, poster, backdrop, int(time.time()),
                   d.get("release_date") if kind == "movie" else d.get("first_air_date"),
                   d.get("imdb_id") or (d.get("external_ids") or {}).get("imdb_id"),
                   d.get("poster_path"), d.get("backdrop_path"), extra))
    if kind == "movie":
        store_categories(int(tmdb_id), d)
    return cached(kind, tmdb_id)


CAT_VERSION = 3   # 1.4.1: + TMDB recommendations, 1.4.3: + cast & crew. Bump when more category fields are read from the details response


def _certification(d):
    """Age rating from release_dates: the UI language's country first, then US (none if neither has one)."""
    lang = settings.tmdb_language()
    want = [lang.split("-")[1].upper()] if "-" in lang else []
    want += ["US"]
    by = {}
    for r in (d.get("release_dates") or {}).get("results") or []:
        certs = [x.get("certification") for x in r.get("release_dates") or [] if (x.get("certification") or "").strip()]
        if certs:
            by[r.get("iso_3166_1")] = certs[0].strip()
    for cc in want:
        if cc in by:
            return by[cc]
    return None


def store_categories(tmdb_id, d):
    """1.4: genres index, collection / franchise and age rating for one movie (from a details response)."""
    names = [g.get("name").strip() for g in d.get("genres") or [] if (g.get("name") or "").strip()]
    col = d.get("belongs_to_collection") or None
    now = int(time.time())
    poster = None
    if col and col.get("id"):
        have = db.row("SELECT poster, poster_path FROM collections WHERE id=?", (int(col["id"]),))
        if have and have["poster"] and have["poster_path"] == col.get("poster_path"):
            poster = have["poster"]
        else:
            try:
                poster = download_image(col.get("poster_path"), "w500")
            except Exception:   # the poster is a nice-to-have; the grid falls back to the first movie's
                poster = None
    recs = [r.get("id") for r in ((d.get("recommendations") or {}).get("results") or []) if r.get("id")][:20]
    credits = d.get("credits") if isinstance(d.get("credits"), dict) else None
    with db.tx() as c:
        if credits is not None:
            store_credits(c, tmdb_id, credits, now)
        if "recommendations" in d:
            c.execute("DELETE FROM movie_recs WHERE tmdb_id=?", (tmdb_id,))
            c.executemany("INSERT OR IGNORE INTO movie_recs(tmdb_id, rec_id, rank) VALUES(?,?,?)",
                          [(tmdb_id, int(r), n) for n, r in enumerate(recs)])
        c.execute("DELETE FROM movie_genres WHERE tmdb_id=?", (tmdb_id,))
        for n in names:
            c.execute("INSERT OR IGNORE INTO movie_genres(tmdb_id, genre) VALUES(?,?)", (tmdb_id, n))
        if col and col.get("id"):
            c.execute("INSERT INTO collections(id,name,poster_path,backdrop_path,poster,updated_at) VALUES(?,?,?,?,?,?) "
                      "ON CONFLICT(id) DO UPDATE SET name=excluded.name, poster_path=excluded.poster_path, "
                      "backdrop_path=excluded.backdrop_path, poster=COALESCE(excluded.poster, collections.poster), "
                      "updated_at=excluded.updated_at",
                      (int(col["id"]), col.get("name") or "Collection", col.get("poster_path"), col.get("backdrop_path"),
                       poster, now))
        c.execute("UPDATE metadata SET collection_id=?, collection_name=?, certification=?, cat_v=? "
                  "WHERE kind='movie' AND tmdb_id=?",
                  (int(col["id"]) if col and col.get("id") else None, (col or {}).get("name"), _certification(d),
                   CAT_VERSION, tmdb_id))


CAST_MAX = 20
CREW_JOBS = {"Director": "director", "Screenplay": "writer", "Writer": "writer", "Story": "writer", "Novel": "writer",
             "Author": "writer", "Characters": "writer"}


def store_credits(c, tmdb_id, credits, now=None):
    """1.4.3: top-billed cast (ordered) plus directors / writers, inside the caller's transaction."""
    now = now or int(time.time())
    cast = sorted((x for x in credits.get("cast") or [] if x.get("id") and x.get("name")),
                  key=lambda x: x.get("order") if x.get("order") is not None else 999)[:CAST_MAX]
    crew = [x for x in credits.get("crew") or [] if x.get("id") and x.get("name") and x.get("job") in CREW_JOBS]
    c.execute("DELETE FROM movie_cast WHERE tmdb_id=?", (tmdb_id,))
    c.execute("DELETE FROM movie_crew WHERE tmdb_id=?", (tmdb_id,))
    for x in cast + crew:
        c.execute("INSERT INTO people(id,name,profile_path,updated_at) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                  "name=excluded.name, photo=CASE WHEN people.profile_path IS excluded.profile_path THEN people.photo END, "
                  "profile_path=excluded.profile_path, updated_at=excluded.updated_at",
                  (int(x["id"]), x["name"], x.get("profile_path"), now))
    for n, x in enumerate(cast):
        c.execute("INSERT OR IGNORE INTO movie_cast(tmdb_id,person_id,character,ord) VALUES(?,?,?,?)",
                  (tmdb_id, int(x["id"]), (x.get("character") or "").strip() or None, n))
    for x in crew:
        c.execute("INSERT OR IGNORE INTO movie_crew(tmdb_id,person_id,job) VALUES(?,?,?)",
                  (tmdb_id, int(x["id"]), CREW_JOBS[x["job"]]))


def person_photo(person_id):
    """1.4.3: a cast member's photo, downloaded from TMDB the first time someone views it, then cached."""
    p = db.row("SELECT profile_path, photo FROM people WHERE id=?", (int(person_id),))
    if not p or not p["profile_path"]:
        return None
    want = _thumb_name(p["profile_path"], PROFILE_SIZE)
    if p["photo"] == want and (config.THUMB_DIR / p["photo"]).exists():
        return p["photo"]
    # 1.4.6: bigger cast photos need the h632 image; a w185 photo cached by 1.4.3-1.4.5 is upgraded on first view
    # (and still used if TMDB can't be reached)
    have_old = bool(p["photo"] and (config.THUMB_DIR / p["photo"]).exists())
    if have_old and time.time() - _LARGE_FAILED.get(p["profile_path"], 0) < 600:   # TMDB unreachable a moment ago
        return p["photo"]
    name = download_image(p["profile_path"], PROFILE_SIZE)
    if not name:
        _LARGE_FAILED[p["profile_path"]] = time.time()
    if not name and have_old:
        return p["photo"]
    if name:
        with db.tx() as c:
            c.execute("UPDATE people SET photo=? WHERE id=?", (name, int(person_id)))
    return name


# matched movies whose category fields were never fetched (matched before 1.4)
CAT_PENDING = ("meta_status IN ('matched','manual') AND tmdb_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM metadata md "
               "WHERE md.kind='movie' AND md.tmdb_id=items.tmdb_id AND COALESCE(md.cat_v,0) >= %d)" % CAT_VERSION)


def fetch_season(tv_id, season, wanted_episodes=None, force=False):
    have = db.row("SELECT COUNT(*) n FROM tmdb_episodes WHERE tv_id=? AND season=?", (tv_id, season))["n"]
    if have and not force:
        # season cached: just fetch stills for episodes that got a file since
        if wanted_episodes:
            for e in db.rows("SELECT episode, still_path FROM tmdb_episodes WHERE tv_id=? AND season=? AND still IS NULL "
                             "AND still_path IS NOT NULL", (tv_id, season)):
                if e["episode"] in wanted_episodes:
                    name = download_image(e["still_path"], "w300")
                    if name:
                        with db.tx() as c:
                            c.execute("UPDATE tmdb_episodes SET still=? WHERE tv_id=? AND season=? AND episode=?",
                                      (name, tv_id, season, e["episode"]))
        return
    try:
        d = request("/tv/%d/season/%d" % (int(tv_id), int(season)), {"language": settings.tmdb_language()})
    except TMDBError as e:
        if str(e) == "not found":
            return
        raise
    rows = []
    for e in d.get("episodes") or []:
        n = e.get("episode_number")
        if n is None:
            continue
        still = None
        if wanted_episodes is None or n in wanted_episodes:
            still = download_image(e.get("still_path"), "w300")
        rows.append((int(tv_id), int(season), int(n), e.get("name"), e.get("overview"), still, e.get("still_path"),
                     e.get("air_date"), e.get("runtime"), e.get("vote_average")))
    with db.tx() as c:
        c.execute("DELETE FROM tmdb_episodes WHERE tv_id=? AND season=?", (tv_id, season))
        c.executemany("INSERT INTO tmdb_episodes(tv_id,season,episode,name,overview,still,still_path,air_date,runtime,rating) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?)", rows)


def apply_movie_match(item_ids, tmdb_id, status, confidence=None, note=None, candidate=None):
    """status: matched | manual | nomatch | unmatched | review. Manual matches are always confidence 1."""
    now = int(time.time())
    if status == "manual":
        confidence, note, candidate = 1.0, None, None
    with db.tx() as c:
        for iid in item_ids:
            c.execute("UPDATE items SET tmdb_id=?, meta_status=?, meta_checked_at=?, meta_confidence=?, meta_note=?, "
                      "meta_candidate=? WHERE id=?", (tmdb_id, status, now, confidence, note, candidate, iid))
        m = cached("movie", tmdb_id) if tmdb_id else None
        for iid in item_ids:
            if m and m["title"]:
                c.execute("UPDATE items SET sort_title=? WHERE id=?", (media.sort_key(m["title"]), iid))
            else:   # back to the file-name title
                t = c.execute("SELECT title FROM items WHERE id=?", (iid,)).fetchone()
                if t:
                    c.execute("UPDATE items SET sort_title=? WHERE id=?", (media.sort_key(t[0] or ""), iid))


def apply_match_result(item_ids, r, force=False):
    """Store the outcome of match_movie() (downloads details for a match). Returns True when matched."""
    if r["status"] == "matched":
        fetch_details("movie", r["result"]["id"], force=force)
        if r.get("candidate"):
            try:
                fetch_details("movie", r["candidate"])
            except TMDBError:
                pass
        apply_movie_match(item_ids, r["result"]["id"], "matched", r["confidence"], r["note"], r.get("candidate"))
        return True
    if r["status"] == "review":
        try:
            fetch_details("movie", r["candidate"])     # so the review dialog can show the suggestion
        except TMDBError:
            pass
        apply_movie_match(item_ids, None, "review", 0, r["note"], r["candidate"])
        return False
    apply_movie_match(item_ids, None, "nomatch")
    return False


def apply_show_match(library_id, show, tmdb_id, status):
    with db.tx() as c:
        c.execute("INSERT INTO show_matches(library_id,show,tmdb_id,status,checked_at) VALUES(?,?,?,?,?) "
                  "ON CONFLICT(library_id,show) DO UPDATE SET tmdb_id=excluded.tmdb_id, status=excluded.status, "
                  "checked_at=excluded.checked_at", (library_id, show, tmdb_id, status, int(time.time())))


def match_show_seasons(library_id, show, tv_id, force=False):
    eps = db.rows("SELECT DISTINCT season, episode FROM items WHERE library_id=? AND show=? AND season IS NOT NULL",
                  (library_id, show))
    seasons = {}
    for e in eps:
        seasons.setdefault(e["season"], set()).add(e["episode"])
    for s, wanted in sorted(seasons.items()):
        fetch_season(tv_id, s, wanted, force=force)


# ---------------------------------------------------------------------------
# background worker
# ---------------------------------------------------------------------------
status = {}          # library_id -> {state, done, total, matched, error}
_q = queue.Queue()
_worker = None
_wlock = threading.Lock()
_stop_flags = {}
_last_resume = {}


def pending_count(library_id, kind=None):
    """How many movies / shows of a library have never been looked up (or are due a no-match retry)."""
    now = int(time.time())
    if kind is None:
        r = db.row("SELECT kind FROM libraries WHERE id=?", (library_id,))
        kind = r["kind"] if r else None
    if kind == "movies":
        return db.row("SELECT COUNT(*) n FROM items WHERE library_id=? AND kind='movie' AND (meta_status IS NULL "
                      "OR (meta_status='nomatch' AND COALESCE(meta_checked_at,0) < ?) OR (" + CAT_PENDING + "))",
                      (library_id, now - RETRY_NOMATCH_S))["n"]
    if kind == "tv":
        return db.row("SELECT COUNT(DISTINCT show) n FROM items i WHERE library_id=? AND kind='episode' AND show IS NOT NULL "
                      "AND NOT EXISTS (SELECT 1 FROM show_matches m WHERE m.library_id=i.library_id AND m.show=i.show "
                      "AND (m.status<>'nomatch' OR m.checked_at >= ?))", (library_id, now - RETRY_NOMATCH_S))["n"]
    return 0


def _after_match(library_id, item_ids):
    """hook for artwork saving (set by app.artwork when it is loaded)"""
    if on_matched:
        try:
            on_matched(library_id, item_ids)
        except Exception:
            log.exception("on_matched hook")


on_matched = None


def resume_pending(min_gap_s=600):
    """1.2.1: pick up metadata work that never ran or was cut short (service restart / update mid-match,
    key saved while the scan was idle, network down). Called at startup and every few minutes; does
    nothing when TMDB is off, a run is already going, or the last run failed less than min_gap_s ago."""
    if not settings.tmdb_enabled():
        return []
    queued = []
    now = time.time()
    for lib in db.rows("SELECT id, kind FROM libraries WHERE kind IN ('movies','tv')"):
        st = status.get(lib["id"]) or {}
        if st.get("state") in ("queued", "running"):
            continue
        if st.get("state") == "error" and now - (st.get("finished_at") or 0) < min_gap_s:
            continue
        if now - _last_resume.get(lib["id"], 0) < 60:
            continue
        try:
            n = pending_count(lib["id"], lib["kind"])
        except Exception:
            log.exception("TMDB pending count")
            continue
        if n and queue_library(lib["id"]):
            _last_resume[lib["id"]] = now
            log.info("TMDB: resuming metadata for library %s (%d waiting)", lib["id"], n)
            queued.append(lib["id"])
    return queued


def resume_loop(stop=lambda: False, first_delay=10, every=300):
    time.sleep(first_delay)
    while not stop():
        try:
            resume_pending()
        except Exception:
            log.exception("TMDB resume")
        for _ in range(every):
            if stop():
                return
            time.sleep(1)


def queue_library(library_id, force=False):
    global _worker
    if not settings.tmdb_enabled():
        return False
    st = status.get(library_id)
    if st and st.get("state") in ("queued", "running") and not force:
        return False
    status[library_id] = {"state": "queued", "done": 0, "total": 0, "matched": 0}
    _q.put((library_id, force))
    with _wlock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, daemon=True, name="tmdb")
            _worker.start()
    return True


def _run():
    while True:
        lib_id, force = _q.get()
        try:
            process_library(lib_id, force)
        except (TMDBAuthError, TMDBNetworkError) as e:
            status[lib_id] = {"state": "error", "error": str(e), "finished_at": time.time()}
            log.warning("TMDB: %s", e)
        except Exception as e:  # never die
            log.exception("TMDB metadata for library %s failed", lib_id)
            status[lib_id] = {"state": "error", "error": str(e), "finished_at": time.time()}


def process_library(library_id, force=False):
    lib = db.row("SELECT * FROM libraries WHERE id=?", (library_id,))
    if not lib or not settings.tmdb_enabled():
        status.pop(library_id, None)
        return
    st = {"state": "running", "done": 0, "total": 0, "matched": 0, "errors": 0, "started_at": time.time()}
    status[library_id] = st
    now = int(time.time())
    if lib["kind"] == "movies":
        rows = db.rows("SELECT id, title, year, tmdb_id, meta_status, meta_checked_at FROM items "
                       "WHERE library_id=? AND kind='movie' ORDER BY sort_title COLLATE NOCASE, year", (library_id,))
        groups = {}
        need_cat = {r["tmdb_id"] for r in db.rows("SELECT DISTINCT tmdb_id FROM items WHERE library_id=? AND kind='movie' "
                                                    "AND " + CAT_PENDING, (library_id,))}
        n_cat = 0
        for r in rows:
            ms = r["meta_status"]
            if ms in ("matched", "manual") and not force and r["tmdb_id"] in need_cat:
                # 1.4: matched before categories existed -> re-read the details once (keeps the match)
                key = (r["title"], r["year"], r["tmdb_id"])
                n_cat += key not in groups
                groups.setdefault(key, []).append(r["id"])
                continue
            if ms in ("manual", "unmatched") and not force:
                continue
            if ms == "unmatched":
                continue
            if not force and ms == "matched":
                continue
            if not force and ms in ("nomatch", "review") and now - (r["meta_checked_at"] or 0) < RETRY_NOMATCH_S:
                continue
            groups.setdefault((r["title"], r["year"], r["tmdb_id"] if ms in ("matched", "manual") else None), []).append(r["id"])
        st["total"] = len(groups)
        st["phase"] = "categories" if groups and n_cat == len(groups) else "matching"
        # 1.2.1: a few lookups in flight at once (the shared limiter still caps requests/s). One movie needs
        # ~4 round trips (search, details, poster, backdrop), so a single thread managed only ~1.3 movies/s.
        lock = threading.Lock()
        fatal = []

        def one(key):
            title, year, known_id = key
            ids = groups[key]
            if fatal or _stop_flags.get(library_id):
                return
            try:
                if known_id:
                    try:
                        fetch_details("movie", known_id, force=True)
                    except TMDBError as e:
                        if str(e) != "not found":
                            raise
                        with db.tx() as c:   # removed from TMDB: keep what we have, stop asking
                            c.execute("UPDATE metadata SET cat_v=? WHERE kind='movie' AND tmdb_id=?", (CAT_VERSION, known_id))
                    ok = True
                else:
                    ok = apply_match_result(ids, match_movie(title, year), force=force)
                    if ok:
                        _after_match(library_id, ids)
                with lock:
                    st["matched"] += 1 if ok else 0
            except (TMDBAuthError, TMDBNetworkError) as e:
                fatal.append(e)
                return
            except TMDBError as e:
                with lock:
                    st["errors"] += 1
                    st["error"] = str(e)
            except Exception as e:  # one odd title must not stop the library
                log.exception("TMDB movie %r", title)
                with lock:
                    st["errors"] += 1
                    st["error"] = str(e)
            with lock:
                st["done"] += 1
                st["rate_per_min"] = round(st["done"] / max(1e-6, time.time() - st["started_at"]) * 60, 1)
                left = st["total"] - st["done"]
                st["eta_s"] = int(left / (st["rate_per_min"] / 60)) if st["rate_per_min"] else None

        workers = max(1, min(config.TMDB_WORKERS, len(groups) or 1))
        if workers == 1:
            for k in groups:
                one(k)
        else:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tmdb-w") as ex:
                list(ex.map(one, list(groups)))
        if fatal:
            raise fatal[0]
    elif lib["kind"] == "tv":
        shows = [r["show"] for r in db.rows("SELECT DISTINCT show FROM items WHERE library_id=? AND kind='episode' "
                                            "AND show IS NOT NULL", (library_id,))]
        matches = {r["show"]: r for r in db.rows("SELECT * FROM show_matches WHERE library_id=?", (library_id,))}
        st["total"] = len(shows)
        for show in shows:
            m0 = matches.get(show)
            try:
                if m0 and m0["status"] == "unmatched":
                    pass
                elif m0 and m0["status"] in ("matched", "manual") and m0["tmdb_id"]:
                    fetch_details("tv", m0["tmdb_id"], force=force)
                    match_show_seasons(library_id, show, m0["tmdb_id"], force=force)
                    st["matched"] += 1
                elif m0 and m0["status"] == "nomatch" and not force and now - m0["checked_at"] < RETRY_NOMATCH_S:
                    pass
                else:
                    year = db.row("SELECT MIN(year) y FROM items WHERE library_id=? AND show=?", (library_id, show))["y"]
                    ym = re.search(r"\((\d{4})\)\s*$", show)
                    name = re.sub(r"\s*\(\d{4}\)\s*$", "", show)
                    m = find_match("tv", name, year or (int(ym.group(1)) if ym else None))
                    if m:
                        fetch_details("tv", m["id"], force=force)
                        apply_show_match(library_id, show, m["id"], "matched")
                        match_show_seasons(library_id, show, m["id"], force=force)
                        st["matched"] += 1
                    else:
                        apply_show_match(library_id, show, None, "nomatch")
            except (TMDBAuthError, TMDBNetworkError):
                raise
            except TMDBError as e:
                st["errors"] += 1
                st["error"] = str(e)
            st["done"] += 1
    st["state"] = "done"
    st["finished_at"] = time.time()
    log.info("TMDB library %s: %s", library_id, st)


# ---------------------------------------------------------------------------
# enrichment for API output
# ---------------------------------------------------------------------------
def _local_poster(it):
    return it.get("poster") and it.get("poster") != it.get("thumb")


def enrich(items):
    """Overlay cached TMDB data onto item dicts (in place). Cheap: a few indexed lookups."""
    if not items:
        return items
    movie_ids = {i["tmdb_id"] for i in items if i.get("tmdb_id") and i.get("kind") == "movie"}
    movies = {}
    if movie_ids:
        ids = list(movie_ids)
        for r in db.rows("SELECT * FROM metadata WHERE kind='movie' AND tmdb_id IN (%s)" % ",".join("?" * len(ids)), ids):
            movies[r["tmdb_id"]] = r
    show_keys = {(i["library_id"], i["show"]) for i in items if i.get("kind") == "episode" and i.get("show")}
    shows = {}
    for lib_id, show in show_keys:
        sm = db.row("SELECT tmdb_id FROM show_matches WHERE library_id=? AND show=? AND tmdb_id IS NOT NULL "
                    "AND status IN ('matched','manual')", (lib_id, show))
        if sm:
            shows[(lib_id, show)] = (sm["tmdb_id"], cached("tv", sm["tmdb_id"]))
    for it in items:
        it["has_art"] = bool(_local_poster(it))
        if it.get("kind") == "movie" and it.get("tmdb_id") in movies:
            m = movies[it["tmdb_id"]]
            _overlay_common(it, m)
            if m.get("collection_id"):
                it["collection"] = {"id": m["collection_id"], "name": m.get("collection_name")}
            it["certification"] = m.get("certification")
            if m["title"]:
                it["file_title"] = it.get("title")
                it["title"] = m["title"]
            if m["year"]:
                it["year"] = m["year"]
            if m["poster"] and not _local_poster(it):
                it["poster"] = m["poster"]
                it["has_art"] = True
        elif it.get("kind") == "episode" and (it.get("library_id"), it.get("show")) in shows:
            tv_id, sm = shows[(it["library_id"], it["show"])]
            it["show_tmdb_id"] = tv_id
            if sm:
                it["show_title"] = sm["title"]
                if sm["poster"] and not _local_poster(it):
                    it["poster"] = sm["poster"]
                    it["has_art"] = True
                it["backdrop"] = sm["backdrop"]
                it["genres"] = json.loads(sm["genres"] or "[]")
                it["show_overview"] = sm["overview"]
            if it.get("season") is not None and it.get("episode") is not None:
                e = db.row("SELECT * FROM tmdb_episodes WHERE tv_id=? AND season=? AND episode=?",
                           (tv_id, it["season"], it["episode"]))
                if e:
                    if e["name"]:
                        it["title"] = e["name"]
                        it["episode_title"] = e["name"]
                    it["overview"] = e["overview"]
                    it["air_date"] = e["air_date"]
                    it["rating"] = e["rating"]
                    if e["still"]:
                        it["thumb"] = e["still"]
            it["tmdb"] = True
    return items


def _overlay_common(it, m):
    it["overview"] = m["overview"]
    it["tagline"] = m["tagline"]
    it["genres"] = json.loads(m["genres"] or "[]")
    it["rating"] = m["rating"]
    it["vote_count"] = m["vote_count"]
    it["backdrop"] = m["backdrop"]
    it["tmdb"] = True


def show_meta(library_id, show):
    sm = db.row("SELECT * FROM show_matches WHERE library_id=? AND show=?", (library_id, show))
    if not sm or not sm["tmdb_id"] or sm["status"] not in ("matched", "manual"):
        return None, (sm["status"] if sm else None)
    return cached("tv", sm["tmdb_id"]), sm["status"]
