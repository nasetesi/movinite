"""1.4.14 static + unit checks: Add library -> Browse (share / folder picker)."""
import os, re, sys, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
from app import browse as b
A = os.path.join(ROOT, "app")
js = open(os.path.join(A, "static", "app.js")).read(); css = open(os.path.join(A, "static", "style.css")).read()
srv = open(os.path.join(A, "server.py")).read(); helper = open(os.path.join(ROOT, "helpers", "media-server-mount")).read()
inst = open(os.path.join(ROOT, "install.sh")).read(); upd = open(os.path.join(ROOT, "update.sh")).read()
ver = open(os.path.join(A, "version.py")).read()
fails = 0
def check(c, m):
    global fails
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails += 1
def err(f, *a):
    try: f(*a); return None
    except b.BrowseError as e: return e.code
check(tuple(int(x) for x in re.search(r'"([0-9.]+)"', ver).group(1).split(".")) >= (1, 5), "version (1, 5) or later (numeric; 1.6 > 1.5.5)")
# paths inside a share
check(b.clean_rel("/Movies//HD/") == "Movies/HD" and b.clean_rel("a\\b") == "a/b" and b.clean_rel("") == "", "clean_rel normalises slashes")
check(all(err(b.clean_rel, x) == "bad" for x in ["..", "a/../..", "a\\..\\b", "x\n", 'a"b', "./.."]), "clean_rel refuses '..', control characters and quotes")
check(b.parse_smb("//nas") == ("nas", "", "") and b.parse_smb("smb://nas/Media/Movies HD") == ("nas", "Media", "Movies HD") and b.parse_smb("\\\\nas\\Media") == ("nas", "Media", ""), "parse_smb: host only, smb://, Windows style")
check(err(b.parse_smb, "//na s/x") == "bad" and err(b.parse_smb, "//nas/a$b`") == "bad" and err(b.parse_smb, "//nas/M/../..") == "bad", "parse_smb refuses odd hosts, shell characters and '..'")
check(b.parse_nfs("nas") == ("nas", "") and b.parse_nfs("nas:/volume1/media/") == ("nas", "/volume1/media") and b.parse_nfs("nfs://nas/v1") == ("nas", "/v1"), "parse_nfs: host only / export / nfs://")
check(b.suggest_kind("Movies") == "movies" and b.suggest_kind("TV Shows") == "tv" and b.suggest_kind("Series") == "tv" and b.suggest_kind("Music") == "music" and b.suggest_kind("Photos") is None, "type suggestion from the folder name")
# local listing, root jail
t = tempfile.mkdtemp()
try:
    os.makedirs(os.path.join(t, "share", "Movies", "A (2000)")); os.makedirs(os.path.join(t, "share", ".hidden")); os.makedirs(os.path.join(t, "outside"))
    open(os.path.join(t, "share", "Movies", "A (2000)", "a.mkv"), "w").close(); open(os.path.join(t, "share", "x.mp4"), "w").close()
    os.symlink(os.path.join(t, "outside"), os.path.join(t, "share", "jump"))
    d = b.list_local("", root=os.path.join(t, "share"))
    check([x["name"] for x in d["dirs"]] == ["jump", "Movies"] and d["videos"] == 1 and d["path"] == "" and d["parent"] is None, "list_local: folders only, hidden skipped, video count here")
    d = b.list_local("Movies", root=os.path.join(t, "share"))
    check(d["dirs"] == [{"name": "A (2000)", "videos": 1}] and d["parent"] == "", "list_local: per-folder video counts")
    check(err(b.list_local, "jump", os.path.join(t, "share")) == "bad", "list_local: a symlink out of the share is refused")
    check(err(b.list_local, "../outside", os.path.join(t, "share")) == "bad", "list_local: '..' refused")
    check(err(b.list_local, "nope", os.path.join(t, "share")) == "notfound", "list_local: missing folder -> notfound")
finally:
    shutil.rmtree(t)
# smbclient output parsing + error mapping
sample = "  .                                   D        0  Tue Nov 24 13:24:21 2026\n  ..                                  D        0  Tue Nov 24 13:24:21 2026\n  Movies HD                           D        0  Tue Nov 24 13:24:21 2026\n  $RECYCLE.BIN                      DHS        0  Mon Jan  1 10:00:00 2024\n  film.mkv                            A  1234567  Tue Nov 24 13:24:21 2026\n"
names = [(m.group(1), m.group(2)) for m in (b.LS_RE.match(l) for l in sample.splitlines()) if m]
check(("Movies HD", "D") in names and ("film.mkv", "A") in names and ("$RECYCLE.BIN", "DHS") in names, "smbclient ls lines parse (names with spaces, attributes)")
check(b._smb_err("session setup failed: NT_STATUS_LOGON_FAILURE").code == "auth" and b._smb_err("tree connect failed: NT_STATUS_BAD_NETWORK_NAME").code == "notfound"
      and b._smb_err("NT_STATUS_ACCESS_DENIED listing").code == "denied" and b._smb_err("NT_STATUS_IO_TIMEOUT").code == "unreachable", "smbclient errors -> wrong password / not found / denied / unreachable")
check(b._smb_proto("vers=1.0")[0].endswith("NT1") and b._smb_proto("vers=3.0") == ["--option=client max protocol=SMB3_00"] and b._smb_proto("") == [], "SMB version choice passed to smbclient")
bsrc = open(os.path.join(A, "browse.py")).read()
check('"-A", auth' in bsrc and "0o600" in bsrc and "mkdtemp" in bsrc and "rmtree" in bsrc and "password" not in re.sub(r"#.*", "", bsrc.split("def _run_smbclient")[1].split("def ")[0]).split("cmd = ")[1].split("\n")[0], "smbclient login via a 0600 file in a private temp dir, removed after; never on the command line")
check("timeout=SMB_TIMEOUT" in bsrc and '"-t", "15"' in bsrc and "def reach(" in bsrc, "timeouts + a quick reachability check")
# server
check('@app.post("/api/browse")' in srv and "def browse_source(body: dict = Body(...), u=Depends(auth.require_admin))" in srv, "POST /api/browse, admin only (login in the body, not the URL)")
check('@app.get("/api/libraries/{lib_id}/browse")' in srv and "root=shares.mount_point" in srv, "Edit library browse stays inside the existing share mount")
check("status_code=400" in srv.split("def _browse_fail")[1][:300], "browse errors are 400 (a 401 would sign the admin out)")
check('"subpath" in body' in srv and "scanner.request_scan(lib_id, full=True)" in srv, "Edit library can change the folder (full rescan)")
check("shares.mount(share_id, stype, remote, opts" in srv, "adding a library still mounts the same way")
# helper
check("cmd_browse()" in helper and "browse)  [ $# -ge 2 ]" in helper, "mount helper: new browse command")
check("*/../*" in helper and 'realpath -e' in helper and '"$mnt"/*' in helper, "mount helper: '..' and symlink escapes refused")
check("/run/media-server-browse" in helper and "mktemp -d" in helper and "trap" in helper and "umount -l" in helper and "ro," in helper.split("cmd_browse()")[1], "mount helper: read-only temporary mount in a private dir, always unmounted")
check("timeout 30 mount" in helper, "mount helper: mount timeout")
check('rm -f "$cred"' in helper.split("cmd_browse()")[1], "mount helper: temporary credentials file removed right after mounting")
# install / update
check("nfs-common smbclient" in inst, "install.sh installs smbclient")
check("command -v smbclient" in upd and "timeout 300 apt-get install -y -q smbclient" in upd and "MS_SKIP_APT" in upd, "update.sh adds smbclient if missing (best effort)")
# UI
check("function folderPicker(" in js and '"/api/browse"' in js and "upToShares" in js, "folder picker component + Add library wiring")
check('id="al-browse"' in js and 'id="el-browse"' in js, "Browse buttons in Add library and Edit library")
check("Select this folder" in js and "fp-crumbs" in js and "fp-up" in js and "fp-spin" in js and 'role="alert"' in js, "picker: breadcrumb, Up, Select, loading and error states")
check("applyKind(d.suggest)" in js, "picker suggests the library type")
check("err.code = data.code" in js, "api() keeps the error code")
check("rgba(23,26,33,.78)" in css and "blur(18px)" in css and ".fp-row{" in css and "min-height:44px" in css.split(".fp-row{")[1][:200], "picker: frosted see-through style, 44 px rows")
m = css.split("1.4.14: folder picker")[1]
check("(max-width:640px),(pointer:coarse) and (max-width:900px)" in m and "height:100%" in m and ".fp-row{min-height:48px}" in m, "phone: full-screen sheet, 48 px rows")
print("%d failure(s)" % fails)
raise SystemExit(1 if fails else 0)
