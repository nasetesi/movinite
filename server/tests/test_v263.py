"""2.6.3: Roku session auth, honor mkv=0, device name, sideload channel files."""
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]       # server/
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="ms-v263-"))
(TMP / "data").mkdir()
os.environ["MS_DATA_DIR"] = str(TMP / "data")
os.environ["MS_SESSION_DAYS"] = "30"
os.environ.pop("MS_TMDB_KEY", None)

failed = 0


def check(cond, msg):
    global failed
    if cond:
        print("  ok  ", msg)
    else:
        failed += 1
        print("  FAIL", msg)


from app.version import __version__
from app import transcode, auth
from app.server import playback_info, _player_query, _embed_session

ch = (ROOT / "CHANGELOG.md").read_text()
rd = (ROOT / "README.md").read_text()
trp = (ROOT / "app/transcode.py").read_text()
au = (ROOT / "app/auth.py").read_text()
srv = (ROOT / "app/server.py").read_text()

print("version and docs")
check(__version__ == "2.6.3", "version is 2.6.3")
check("## 2.6.3" in ch and ch.find("## 2.6.3") < ch.find("## 2.6.2"), "CHANGELOG has 2.6.3 above 2.6.2")
sec = ch.split("## 2.6.3", 1)[1].split("## 2.6.2", 1)[0]
check("Roku" in sec and "mkv=0" in sec, "CHANGELOG 2.6.3 describes the Roku app and mkv=0")
check("ms_session" in sec or "Bearer" in sec, "CHANGELOG 2.6.3 describes session header/query")
check("**2.6.3:**" in rd, "install README mentions 2.6.3")
rd263 = rd.split("**2.6.3:**", 1)[1].split("**2.6.2:**", 1)[0] if "**2.6.3:**" in rd else ""
for bad in ("192.168.", "tukuia.com password", "ms_session=secret"):
    check(bad not in sec, "2.6.3 changelog does not contain %r" % bad)

print("mkv cap is honored")
# default (missing) stays True for Android
nat = transcode.client_caps_from_params({"native": "1", "hevc": "1"})
check(nat["mkv"] is True, "missing mkv still defaults to True")
# explicit 1
yes = transcode.client_caps_from_params({"native": "1", "hevc": "1", "mkv": "1"})
check(yes["mkv"] is True, "mkv=1 is True")
# the bug: mkv=0 used to become True because of `or True`
no = transcode.client_caps_from_params({"native": "1", "hevc": "1", "hevc10": "1", "mkv": "0"})
check(no["mkv"] is False, "mkv=0 is False")
check(no["native"] is True and no["hevc"] is True, "other caps still parse with mkv=0")

# playback_info should refuse Matroska Direct Play when mkv=0
film = {
    "path": "/tmp/movie.mkv", "media_type": "video", "vcodec": "h264", "acodec": "aac",
    "pix_fmt": "yuv420p", "width": 1920, "height": 1080, "color_transfer": "",
    "audio_streams": "[]", "subtitle_streams": "[]", "external_subs": "[]",
    "hdr_type": "", "hdr_primaries": "",
}
try:
    pb_yes = playback_info(film, client=yes)
    pb_no = playback_info(film, client=no)
    check(pb_yes.get("direct") is True, "H.264/AAC MKV is Direct Play when mkv=1")
    check(pb_no.get("direct") is False, "H.264/AAC MKV is not Direct Play when mkv=0")
except Exception as e:
    check(False, "playback_info mkv check raised: %s" % e)

print("device name and session token")
check(auth._device_name("Movinite-Roku/0.1 (Roku 3500X; 14.1)") == "Movinite app (Roku)",
      "Movinite-Roku UA is labeled Movinite app (Roku)")
check(auth._device_name("Roku/DVP-14.1") == "Roku", "plain Roku UA is labeled Roku")
check("Android" not in auth._device_name("Movinite-Roku/0.1"), "Roku is not labeled Android")

class Dummy:
    def __init__(self, cookies=None, headers=None, query=None):
        self.cookies = cookies or {}
        self.headers = headers or {}
        self.query_params = query or {}

tok = "test-session-token-not-real"
check(auth.session_token_from_request(Dummy(cookies={"ms_session": tok})) == tok,
      "token from cookie")
check(auth.session_token_from_request(Dummy(headers={"authorization": "Bearer " + tok})) == tok,
      "token from Authorization Bearer")
check(auth.session_token_from_request(Dummy(headers={"Authorization": "Bearer " + tok})) == tok,
      "token from Authorization (capital A)")
check(auth.session_token_from_request(Dummy(headers={"x-movinite-session": tok})) == tok,
      "token from X-Movinite-Session")
check(auth.session_token_from_request(Dummy(query={"ms_session": tok})) == tok,
      "token from ms_session query")
check(auth.session_token_from_request(Dummy(headers={"authorization": "Bearer " + tok},
                                            query={"ms_session": "other"})) == tok,
      "Bearer wins over query when no cookie")
check(auth.session_token_from_request(Dummy()) is None, "no token returns None")
# cookie wins
check(auth.session_token_from_request(Dummy(cookies={"ms_session": "cookie-tok"},
                                            headers={"authorization": "Bearer other"})) == "cookie-tok",
      "cookie wins over Bearer")

print("HLS playlist embeds session only when asked")
q = _player_query(0, "", session=tok)
check("ms_session=" in q and tok in unquote(q), " _player_query can append ms_session")
q0 = _player_query(0, "")
check("ms_session=" not in q0, "_player_query omits session when not passed")

class Req:
    def __init__(self, query=None, ua=""):
        self.query_params = query or {}
        self.headers = {"user-agent": ua}
        self.cookies = {}

check(_embed_session(Req()) is None, "web request does not embed session")
r = Req(query={"embed_session": "1", "ms_session": tok})
check(_embed_session(r) == tok, "embed_session=1 with ms_session embeds the token")
r2 = Req(ua="Movinite-Roku/0.1", query={"ms_session": tok})
check(_embed_session(r2) == tok, "Movinite-Roku UA embeds ms_session")

print("Roku channel files")
roku = REPO / "roku"
check((roku / "manifest").is_file(), "roku/manifest exists")
man = (roku / "manifest").read_text()
check("title=Movinite" in man, "manifest title is Movinite")
check("mm_icon_focus_hd=" in man and "splash_screen" in man, "manifest has icon and splash")
check((roku / "source/main.brs").is_file(), "source/main.brs exists")
check((roku / "components/MainScene.xml").is_file(), "MainScene exists")
for name in ("SetupScreen", "LoginScreen", "HomeScreen", "LibraryScreen",
             "SearchScreen", "DetailsScreen", "PlayerScreen"):
    check((roku / "components/screens" / (name + ".xml")).is_file(), name + " exists")
readme = (roku / "README.md").read_text() if (roku / "README.md").is_file() else ""
check("Developer Mode" in readme and "Home" in readme, "sideload guide mentions Developer Mode")
check("192.0.2.10" in readme or "<roku-ip>" in readme or "roku-ip" in readme.lower()
      or "http://" in readme, "sideload guide mentions the dev installer URL")
# no secrets
blob = "\n".join([man, readme])
check(".creds" not in blob and "BEGIN " not in blob, "roku docs have no keystore or creds")

if failed:
    print("\n%d check(s) failed" % failed)
    sys.exit(1)
print("\nall checks passed")
