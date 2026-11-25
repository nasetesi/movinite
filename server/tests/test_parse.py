"""Run: .venv/bin/python -m pytest tests  (or python3 tests/test_parse.py)"""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("MS_DATA_DIR", "/tmp/ms-test-data")
from app import media  # noqa: E402


def test_movies():
    m = media.parse_movie(Path("/m/The.Matrix.1999.1080p.BluRay.x264.mkv"))
    assert (m["kind"], m["title"], m["year"], m["edition"]) == ("movie", "The Matrix", 1999, None)
    assert media.parse_movie(Path("/m/Inception (2010)/Inception (2010).mp4"))["title"] == "Inception"
    assert media.parse_movie(Path("/m/Alien (1979) [1080p].mkv"))["year"] == 1979


def test_editions():
    cases = {"Salt DIRECTORS CUT (2010) [1080p]/Salt DIRECTORS CUT (2010) [1080p].mp4": ("Salt", "Director's Cut"),
             "Sin City EXTENDED and UNRATED (2005).mp4": ("Sin City", "Extended, Unrated"),
             "Terminator 2 Judgment Day DC (1991).mp4": ("Terminator 2 Judgment Day", "Director's Cut"),
             "The Last of the Mohicans DDC (1992).mp4": ("The Last of the Mohicans", "Director's Cut"),
             "Blade Runner (1982) {edition-Final Cut}.mkv": ("Blade Runner", "Final Cut"),
             "Dune.2021.IMAX.2160p.WEB-DL.mkv": ("Dune", "IMAX"),
             "The Final Cut (2004).mkv": ("The Final Cut", None),
             "Uncut Gems (2019).mkv": ("Uncut Gems", None),
             "Washington DC (2010).mkv": ("Washington DC", None),
             "Charlotte's Web (2006).mkv": ("Charlotte's Web", None)}
    for f, want in cases.items():
        m = media.parse_movie(Path("/m/" + f))
        assert (m["title"], m["edition"]) == want, (f, m)


def test_episodes():
    r = Path("/tv")
    e = media.parse_episode(r / "Breaking Bad/Season 01/Breaking.Bad.S01E02.Cats.in.the.Bag.720p.mkv", r)
    assert (e["show"], e["season"], e["episode"], e["title"]) == ("Breaking Bad", 1, 2, "Cats in the Bag")
    e = media.parse_episode(r / "The Office (US)/Season 2/The Office - 2x05 - Halloween.mp4", r)
    assert (e["show"], e["season"], e["episode"]) == ("The Office (US)", 2, 5)


def test_tracks():
    r = Path("/mu")
    t = media.parse_track(r / "Artist/Album/01 - Song.mp3", r)
    assert (t["artist"], t["album"], t["track"], t["title"]) == ("Artist", "Album", 1, "Song")


if __name__ == "__main__":
    test_movies(); test_editions(); test_episodes(); test_tracks(); print("ok")


def test_years_v11():
    p = media.parse_movie
    m = p(Path("/m/1917.2019.mkv"))
    assert (m["title"], m["year"]) == ("1917", 2019)
    assert p(Path("/m/Blade Runner 2049 (2017).mkv"))["title"] == "Blade Runner 2049"
    assert p(Path("/m/Charlotte's Web (2006).mkv"))["title"] == "Charlotte's Web"
    assert p(Path("/m/Remux Test (2022).mkv"))["title"] == "Remux Test"
    assert p(Path("/m/Heat.1080p.BluRay.mkv"))["title"] == "Heat"


if __name__ == "__main__":
    test_years_v11(); print("ok v1.1")
