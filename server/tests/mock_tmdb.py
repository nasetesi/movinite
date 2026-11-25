"""A tiny fake TMDB API for tests (no internet / real key needed).

    python3 tests/mock_tmdb.py 9555            # serves http://127.0.0.1:9555/3/... and /t/p/<size>/<file>
Valid credentials: api_key=GOODKEY or 0123456789abcdef0123456789abcdef, or  "Authorization: Bearer eyJmock.token.sig".
MOCK_TMDB_429_EVERY=N makes every Nth API request answer 429 (Retry-After: 1).
"""
import base64
import hashlib
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# a small valid JPEG (gray square) so image downloads work without ffmpeg
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAAQABADASIAAhEBAxEB/8QA"
    "FQABAQAAAAAAAAAAAAAAAAAAAAP/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAM"
    "AwEAAhEDEQA/AKAA/9k=")
if os.path.exists("/tmp/mockimg.jpg"):
    JPEG = open("/tmp/mockimg.jpg", "rb").read()

MOVIES = {
    1001: {"id": 1001, "title": "The Big Test Movie", "original_title": "The Big Test Movie", "release_date": "2019-05-01",
           "overview": "A test pattern learns to love.", "tagline": "Bars. Tones. Destiny.", "runtime": 1,
           "genres": [{"id": 1, "name": "Drama"}, {"id": 2, "name": "Science Fiction"}], "vote_average": 7.8,
           "vote_count": 1234, "poster_path": "/bigposter.jpg", "backdrop_path": "/bigbackdrop.jpg", "popularity": 50,
           "belongs_to_collection": {"id": 9001, "name": "Test Pattern Collection", "poster_path": "/tpcoll.jpg",
                                     "backdrop_path": None},
           "_cert": {"US": "PG-13", "DE": "12"}, "_recs": [1003, 1002]},
    1002: {"id": 1002, "title": "Another Film", "original_title": "Another Film", "release_date": "2021-09-10",
           "overview": "The 2021 one.", "genres": [{"id": 3, "name": "Thriller"}], "vote_average": 6.1, "vote_count": 99,
           "runtime": 1, "poster_path": "/another.jpg", "backdrop_path": None, "popularity": 10},
    1099: {"id": 1099, "title": "Another Film", "original_title": "Another Film", "release_date": "1985-01-01",
           "overview": "The 1985 decoy.", "genres": [], "vote_average": 5.0, "vote_count": 5, "poster_path": "/decoy.jpg",
           "backdrop_path": None, "popularity": 80},
    1003: {"id": 1003, "title": "Remux Test", "original_title": "Remux Test", "release_date": "2022-02-02",
           "overview": "Copy that.", "genres": [{"id": 4, "name": "Documentary"}], "vote_average": 8.2, "vote_count": 10,
           "runtime": 1, "poster_path": "/remux.jpg", "backdrop_path": "/remuxbd.jpg", "popularity": 5,
           "belongs_to_collection": {"id": 9001, "name": "Test Pattern Collection", "poster_path": "/tpcoll.jpg",
                                     "backdrop_path": None},
           "_cert": {"US": "G"}},
}
SYNTH = {}   # synthetic id -> (title, year) from the search that invented it
SYNTH_GENRES = ["Action", "Adventure", "Animation", "Comedy", "Crime", "Drama", "Family", "Fantasy", "Horror",
                "Science Fiction", "Thriller", "Romance"]
FRANCHISE = re.compile(r"^(.*?)\s+(\d|II|III|IV|Reloaded|Revolutions|Resurrections)$", re.I)
FIRSTS = {"the matrix", "toy story", "alien", "back to the future", "the godfather"}


def movie_out(d, q):
    """A details response like TMDB's: release_dates only when appended."""
    cert = d.get("_cert") or d.get("_cert_synth") or {}
    d = {k: v for k, v in d.items() if not k.startswith("_")}
    if "recommendations" not in (q.get("append_to_response") or ""):
        d.pop("recommendations", None)
    elif "recommendations" not in d:
        d["recommendations"] = {"results": [{"id": k} for k in (MOVIES.get(d["id"]) or {}).get("_recs", [])]}
    info = REAL_INFO.get(_norm(d.get("title") or ""))
    if info and os.environ.get("MOCK_TMDB_SYNTH"):   # UI screenshots: real-looking details for a few titles
        d.update({k: v for k, v in info.items() if not k.startswith("_")})
        cert = {"US": info["_cert"]}
    if "credits" in (q.get("append_to_response") or ""):
        d["credits"] = credits_for(d["id"], d.get("title") or "")
    if "release_dates" in (q.get("append_to_response") or ""):
        d["release_dates"] = {"results": [{"iso_3166_1": c, "release_dates": [{"certification": v, "type": 3}]}
                                          for c, v in cert.items()]}
    return d
# 1.4.3: credits. A few real casts for the UI screenshots, otherwise a deterministic pick from a pool so that
# actors appear in several movies (actor page) and IDs stay stable between runs.
REAL_CAST = {
    "heat": ([("Al Pacino", "Lt. Vincent Hanna"), ("Robert De Niro", "Neil McCauley"), ("Val Kilmer", "Chris Shiherlis"),
              ("Jon Voight", "Nate"), ("Tom Sizemore", "Michael Cheritto"), ("Diane Venora", "Justine Hanna"),
              ("Amy Brenneman", "Eady"), ("Ashley Judd", "Charlene Shiherlis"), ("Mykelti Williamson", "Sgt. Drucker"),
              ("Wes Studi", "Det. Casals"), ("Ted Levine", "Bosko"), ("Dennis Haysbert", "Donald Breedan"),
              ("William Fichtner", "Roger Van Zant"), ("Natalie Portman", "Lauren Gustafson"), ("Tom Noonan", "Kelso"),
              ("Kevin Gage", "Waingro")], [("Michael Mann", "Director"), ("Michael Mann", "Screenplay")]),
    "the matrix": ([("Keanu Reeves", "Neo"), ("Laurence Fishburne", "Morpheus"), ("Carrie-Anne Moss", "Trinity"),
                    ("Hugo Weaving", "Agent Smith"), ("Joe Pantoliano", "Cypher"), ("Gloria Foster", "Oracle")],
                   [("Lana Wachowski", "Director"), ("Lilly Wachowski", "Director"), ("Lana Wachowski", "Writer"), ("Lilly Wachowski", "Writer")]),
    "the matrix reloaded": ([("Keanu Reeves", "Neo"), ("Laurence Fishburne", "Morpheus"), ("Carrie-Anne Moss", "Trinity"),
                             ("Hugo Weaving", "Agent Smith"), ("Jada Pinkett Smith", "Niobe")],
                            [("Lana Wachowski", "Director"), ("Lilly Wachowski", "Director")]),
    "speed": ([("Keanu Reeves", "Jack Traven"), ("Sandra Bullock", "Annie Porter"), ("Dennis Hopper", "Howard Payne")],
              [("Jan de Bont", "Director"), ("Graham Yost", "Writer")]),
    "gravity": ([("Sandra Bullock", "Dr. Ryan Stone"), ("George Clooney", "Matt Kowalski")], [("Alfonso Cuarón", "Director")]),
    "inception": ([("Leonardo DiCaprio", "Cobb"), ("Joseph Gordon-Levitt", "Arthur"), ("Elliot Page", "Ariadne"),
                   ("Tom Hardy", "Eames"), ("Ken Watanabe", "Saito"), ("Cillian Murphy", "Robert Fischer"), ("Michael Caine", "Miles")],
                  [("Christopher Nolan", "Director"), ("Christopher Nolan", "Writer")]),
    "oppenheimer": ([("Cillian Murphy", "J. Robert Oppenheimer"), ("Emily Blunt", "Kitty Oppenheimer"), ("Matt Damon", "Leslie Groves"),
                     ("Robert Downey Jr.", "Lewis Strauss"), ("Florence Pugh", "Jean Tatlock")],
                    [("Christopher Nolan", "Director"), ("Christopher Nolan", "Screenplay")]),
    "tenet": ([("John David Washington", "The Protagonist"), ("Robert Pattinson", "Neil"), ("Michael Caine", "Michael Crosby")],
              [("Christopher Nolan", "Director")]),
}
REAL_INFO = {
    "heat": {"overview": "Obsessive master thief Neil McCauley leads a top-notch crew on various daring heists throughout "
                         "Los Angeles while determined detective Vincent Hanna pursues him without rest. Each man recognizes "
                         "and respects the ability and the dedication of the other even though they are aware their "
                         "cat-and-mouse game may end in violence.",
             "tagline": "A Los Angeles crime saga.", "runtime": 170, "vote_average": 7.9, "vote_count": 7400,
             "genres": [{"id": 80, "name": "Crime"}, {"id": 18, "name": "Drama"}, {"id": 28, "name": "Action"}],
             "backdrop_path": "/heatbackdrop.jpg", "_cert": "R"},
    "the matrix": {"overview": "Set in the 22nd century, The Matrix tells the story of a computer hacker who joins a group of "
                               "underground insurgents fighting the vast and powerful computers who now rule the earth.",
                   "tagline": "Welcome to the Real World.", "runtime": 136, "vote_average": 8.2, "vote_count": 26000,
                   "genres": [{"id": 28, "name": "Action"}, {"id": 878, "name": "Science Fiction"}],
                   "backdrop_path": "/matrixbackdrop.jpg", "_cert": "R"},
}
POOL = ["Maya Lindqvist", "Daniel Okafor", "Sofia Reyes", "Liam Hartley", "Priya Natarajan", "Owen Castellano", "Hana Mori",
        "Marcus Bell", "Elena Petrova", "Jonah Whitaker", "Amara Diallo", "Felix Brandt", "Grace Holloway", "Mateo Silva",
        "Nora Fitzgerald", "Theo Vance", "Isla Chen", "Rafael Duarte", "Clara Weiss", "Samuel Achebe"]
_PIDS = {}


def _pid(name):
    return _PIDS.setdefault(name, 50000 + int(hashlib.md5(name.encode()).hexdigest()[:6], 16) % 900000)


def credits_for(mid, title):
    real = REAL_CAST.get(_norm(title))
    if real:
        cast, crew = real
    else:
        h = int(hashlib.md5(str(mid).encode()).hexdigest()[:8], 16)
        names = [POOL[(h + k * 7) % len(POOL)] for k in range(8)]
        names = list(dict.fromkeys(names))
        cast = [(n, "Character %d" % (k + 1)) for k, n in enumerate(names)]
        crew = [(POOL[(h + 3) % len(POOL)], "Director")]
    return {"cast": [{"id": _pid(n), "name": n, "character": ch, "order": k,
                      "profile_path": None if k == 5 else "/person%d.jpg" % _pid(n)} for k, (n, ch) in enumerate(cast)],
            "crew": [{"id": _pid(n), "name": n, "job": j, "department": "Directing" if j == "Director" else "Writing"}
                     for n, j in crew] + [{"id": 1, "name": "Some Grip", "job": "Key Grip", "department": "Crew"}]}


TV = {
    2001: {"id": 2001, "name": "Test Show", "original_name": "Test Show", "first_air_date": "2020-01-05",
           "overview": "A show about testing.", "genres": [{"id": 5, "name": "Comedy"}], "vote_average": 8.5,
           "vote_count": 321, "episode_run_time": [22], "poster_path": "/showposter.jpg", "backdrop_path": "/showbd.jpg",
           "popularity": 30, "seasons": [{"season_number": 1, "poster_path": "/season1.jpg"},   # 1.5.5: season posters
                                         {"season_number": 2, "poster_path": "/season2.jpg"}]},
    2002: {"id": 2002, "name": "Night Shift", "original_name": "Night Shift", "first_air_date": "2014-05-27",
           "overview": "Doctors on the night shift.", "genres": [{"id": 6, "name": "Drama"}], "vote_average": 7.1,
           "vote_count": 120, "episode_run_time": [44], "poster_path": "/nightshift.jpg", "backdrop_path": "/nightbd.jpg",
           "popularity": 12, "seasons": [{"season_number": 1, "poster_path": "/ns-season1.jpg"}]},
}
SEASONS = {
    (2001, 1): [{"episode_number": 1, "name": "The Real Pilot", "overview": "It begins.", "still_path": "/s1e1.jpg",
                 "air_date": "2020-01-05", "vote_average": 7.0},
                {"episode_number": 2, "name": "Second Wind", "overview": "It continues.", "still_path": "/s1e2.jpg",
                 "air_date": "2020-01-12", "vote_average": 7.5},
                {"episode_number": 3, "name": "Not On Disk", "overview": "", "still_path": "/s1e3.jpg"}],
    (2001, 2): [{"episode_number": 1, "name": "Homecoming", "overview": "Back again.", "still_path": "/s2e1.jpg",
                 "air_date": "2021-03-01"}],
}

stats = {"api": 0, "images": 0, "times": [], "429": 0}
LOCK = threading.Lock()


def _poster(path):
    """UI screenshots: a distinct coloured poster per image path, labelled with the title when known."""
    import io
    from PIL import Image, ImageDraw
    h = int(hashlib.md5(path.encode()).hexdigest()[:6], 16)
    col = ((h >> 16) % 160 + 40, (h >> 8) % 160 + 40, h % 160 + 40)
    im = Image.new("RGB", (300, 450), col)
    dr = ImageDraw.Draw(im)
    pm = re.search(r"/person(\d+)\.jpg$", path)
    if pm:   # portrait: soft colour + initials
        name = next((n for n, i in _PIDS.items() if i == int(pm.group(1))), "")
        if not name:
            for v in REAL_CAST.values():
                for n, _c in v[0]:
                    if _pid(n) == int(pm.group(1)):
                        name = n
            for n in POOL:
                if _pid(n) == int(pm.group(1)):
                    name = n
        im = Image.new("RGB", (185, 278), tuple(min(255, c + 40) for c in col))
        dr = ImageDraw.Draw(im)
        dr.ellipse([42, 50, 142, 150], fill=tuple(max(0, c - 30) for c in col))
        dr.rectangle([22, 170, 162, 278], fill=tuple(max(0, c - 30) for c in col))
        try:
            from PIL import ImageFont
            f = ImageFont.truetype("DejaVuSans-Bold.ttf", 34)
        except Exception:
            f = None
        ini = "".join(w[0] for w in name.split()[:2])
        dr.text((92, 100), ini, fill=(255, 255, 255), font=f, anchor="mm")
        b = io.BytesIO(); im.save(b, "JPEG", quality=80)
        return b.getvalue()
    m = re.search(r"/(synth|coll)(\d+)\.jpg$", path)
    label = ""
    if m and m.group(1) == "synth":
        label = SYNTH.get(int(m.group(2)), ("", ""))[0]
    elif m:
        label = COLLS.get(int(m.group(2)), "")
    dr.rectangle([0, 300, 300, 450], fill=tuple(max(0, c - 40) for c in col))
    words, line, lines = label.split(), "", []
    for w in words:
        if len(line + " " + w) > 16:
            lines.append(line); line = w
        else:
            line = (line + " " + w).strip()
    lines.append(line)
    try:
        from PIL import ImageFont
        f = ImageFont.truetype("DejaVuSans-Bold.ttf", 30)
    except Exception:
        f = None
    for n, ln in enumerate(lines[:4]):
        dr.text((18, 316 + n * 34), ln, fill=(255, 255, 255), font=f)
    b = io.BytesIO(); im.save(b, "JPEG", quality=80)
    return b.getvalue()


COLLS = {}
if os.environ.get("MOCK_TMDB_SYNTH_FILE") and os.path.exists(os.environ["MOCK_TMDB_SYNTH_FILE"]):
    SYNTH.update({int(k): tuple(v) for k, v in json.load(open(os.environ["MOCK_TMDB_SYNTH_FILE"])).items()})


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj, headers=None):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path.startswith("/t/p/"):
            with LOCK:
                stats["images"] += 1
            if "missing" in u.path:
                self.send_response(404); self.end_headers(); return
            if os.environ.get("MOCK_TMDB_COLORS"):
                # 1.4.6: bigger sizes (w780 posters, h632 portraits) look the same as the small ones, just more pixels
                sz = u.path.split("/")[3] if u.path.count("/") >= 4 else "w500"
                person = "/person" in u.path
                body = _poster(re.sub(r"^/t/p/[^/]+/", "/t/p/%s/" % ("w185" if person else "w500"), u.path))
                if sz in ("w780", "original", "h632"):
                    import io
                    from PIL import Image
                    im = Image.open(io.BytesIO(body)); f = (632 / im.height) if person else (780 / im.width)
                    im = im.resize((round(im.width * f), round(im.height * f)), Image.LANCZOS)
                    b = io.BytesIO(); im.save(b, "JPEG", quality=85); body = b.getvalue()
                with LOCK:
                    stats.setdefault("sizes", {}); stats["sizes"][sz] = stats["sizes"].get(sz, 0) + 1
            else:
                body = JPEG
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path == "/_stats":
            return self._json(200, stats)
        if not u.path.startswith("/3/"):
            return self._json(404, {"status_message": "nope"})
        with LOCK:
            stats["api"] += 1
            stats["times"].append(time.time())
            n = stats["api"]
        every = int(os.environ.get("MOCK_TMDB_429_EVERY") or 0)
        if every and n % every == 0:
            with LOCK:
                stats["429"] += 1
            return self._json(429, {"status_code": 25, "status_message": "rate limit"}, {"Retry-After": "1"})
        auth = self.headers.get("Authorization", "")
        if q.get("api_key") not in ("GOODKEY", "0123456789abcdef0123456789abcdef") and auth != "Bearer eyJmock.token.sig":
            return self._json(401, {"status_code": 7, "status_message": "Invalid API key"})
        p = u.path[2:]
        delay = float(os.environ.get("MOCK_TMDB_DELAY") or 0)
        if delay:
            time.sleep(delay)
        if os.environ.get("MOCK_TMDB_SYNTH"):   # UI tests: invent a match for 2 of every 3 titles
            if p == "/search/movie":
                qq = q.get("query") or ""
                h = int(hashlib.md5(qq.lower().encode()).hexdigest()[:6], 16)
                if h % 3 == 0 and not os.environ.get("MOCK_TMDB_SYNTH_ALL"):
                    return self._json(200, {"page": 1, "results": [], "total_results": 0})
                r = {"id": 100000 + h, "title": qq.title(), "original_title": qq.title(),
                     "release_date": "%s-01-01" % (q.get("year") or "2000"), "popularity": 1}
                SYNTH[r["id"]] = (qq.title(), q.get("year") or "2000")
                if os.environ.get("MOCK_TMDB_SYNTH_FILE"):   # survive a mock restart (UI upgrade tests)
                    with open(os.environ["MOCK_TMDB_SYNTH_FILE"], "w") as fh:
                        json.dump({str(k): v for k, v in SYNTH.items()}, fh)
                return self._json(200, {"page": 1, "results": [r], "total_results": 1})
            m = re.match(r"^/movie/(\d+)$", p)
            if m and int(m.group(1)) >= 100000:
                i = int(m.group(1))
                title, year = SYNTH.get(i, ("Synth %s" % i, "2000"))
                g = [SYNTH_GENRES[i % 12]] + ([SYNTH_GENRES[(i // 12) % 12]] if i % 4 else [])
                d = {"id": i, "title": title, "release_date": "%s-01-01" % year, "overview": "Synthetic.",
                     "genres": [{"id": SYNTH_GENRES.index(x), "name": x} for x in dict.fromkeys(g)],
                     "vote_average": round(5 + (i % 40) / 10, 1), "vote_count": 10 + (i % 4000),
                     "poster_path": "/synth%s.jpg" % i, "backdrop_path": None,
                     "_cert_synth": {"US": ["G", "PG", "PG-13", "R"][i % 4]}}
                fm = FRANCHISE.match(title)
                base = fm.group(1) if fm else (title if title.lower() in FIRSTS else None)
                if base:
                    cid = 500000 + int(hashlib.md5(base.lower().encode()).hexdigest()[:5], 16)
                    COLLS[cid] = base + " Collection"
                    d["belongs_to_collection"] = {"id": cid, "name": base + " Collection", "poster_path": "/coll%s.jpg" % cid,
                                                  "backdrop_path": None}
                same = sorted(k for k in SYNTH if k != i and SYNTH_GENRES[k % 12] in g)
                d["recommendations"] = {"results": [{"id": k} for k in same[:10]]}
                return self._json(200, movie_out(d, q))
        if p == "/configuration":
            return self._json(200, {"images": {"base_url": "http://x/t/p/"}})
        if p in ("/search/movie", "/search/tv"):
            src = MOVIES if p == "/search/movie" else TV
            key = "title" if p == "/search/movie" else "name"
            dkey = "release_date" if p == "/search/movie" else "first_air_date"
            yr = q.get("year") or q.get("first_air_date_year")
            qq = _norm(q.get("query"))
            res = [dict(v) for v in src.values() if qq and qq in _norm(v[key])
                   and (not yr or (v.get(dkey) or "").startswith(yr))]
            for r in res:
                r.pop("genres", None)
            return self._json(200, {"page": 1, "results": res, "total_results": len(res)})
        m = re.match(r"^/(movie|tv)/(\d+)$", p)
        if m:
            src = MOVIES if m.group(1) == "movie" else TV
            d = src.get(int(m.group(2)))
            if d and m.group(1) == "movie":
                d = movie_out(d, q)
            return self._json(200, d) if d else self._json(404, {"status_code": 34})
        m = re.match(r"^/tv/(\d+)/season/(\d+)$", p)
        if m:
            eps = SEASONS.get((int(m.group(1)), int(m.group(2))))
            return self._json(200, {"episodes": eps}) if eps is not None else self._json(404, {"status_code": 34})
        return self._json(404, {"status_code": 34})


def serve(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9555
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
