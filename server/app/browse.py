"""1.4.14: browse a share's folders while adding a library, without mounting it for good.

SMB  -> smbclient (runs as the service user; no root, no mount).  Host only ("//nas") lists the shares.
        Without smbclient the root mount helper does a short read-only temporary mount instead.
NFS  -> host only: showmount -e;  otherwise a short read-only temporary mount through the mount helper.
local-> plain directory listing.

Credentials come in the request body only. They go to smbclient through a 0600 file in a private 0700 temp
dir (deleted right after) or to the helper on stdin -- never on a command line, in a log or in a reply.
"""
import os
import re
import shutil
import socket
import subprocess
import tempfile

from . import config, media, shares

MAX_DIRS = 500
SMB_TIMEOUT = 25
VIDEO_EXT = media.VIDEO_EXT


class BrowseError(Exception):
    """A clear, user-facing reason: code = auth | denied | unreachable | notfound | bad | unavailable."""
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


# ------------------------------------------------------------------ helpers
def clean_rel(rel):
    """A path *inside* the share: no '..', no leading '/', no control characters. Returns 'a/b' or ''."""
    rel = rel or ""
    if any(ord(ch) < 32 or ch == "\x7f" for ch in rel):
        raise BrowseError("bad", "Bad folder name")
    rel = rel.replace("\\", "/").strip()
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise BrowseError("bad", "Folder paths may not contain '..'")
    if any('"' in p for p in parts):
        raise BrowseError("bad", "Bad folder name")
    return "/".join(parts)


def suggest_kind(name):
    n = (name or "").lower()
    if re.search(r"\b(tv|series|shows?|episodes?)\b|tv[ ._-]?shows", n):
        return "tv"
    if re.search(r"\b(movies?|films?|cinema)\b", n):
        return "movies"
    if re.search(r"\b(music|audio|albums?|songs?)\b", n):
        return "music"
    return None


def _is_video(name):
    return os.path.splitext(name)[1].lower() in VIDEO_EXT


def parse_smb(remote):
    """'//host', '//host/share', '//host/share/sub/dir', 'smb://..', '\\\\host\\share' -> (host, share, sub)."""
    r = (remote or "").strip().replace("\\", "/")
    if r.lower().startswith("smb:"):
        r = r[4:]
    r = r.lstrip("/")
    host, _, rest = r.partition("/")
    if not re.match(r"^[A-Za-z0-9._:-]+$", host or ""):
        raise BrowseError("bad", "Enter the share address like //192.0.2.10 or //192.0.2.10/Media")
    share, _, sub = rest.partition("/")
    if share and (re.search(r"[\"'$`\\]", share) or any(ord(c) < 32 for c in share)):
        raise BrowseError("bad", "Bad share name")
    return host, share, clean_rel(sub)


def parse_nfs(remote):
    r = (remote or "").strip()
    if r.lower().startswith("nfs://"):
        rest = r[6:]
        h, _, p = rest.partition("/")
        r = "%s:/%s" % (h, p) if p else h
    host, sep, export = r.partition(":")
    if not re.match(r"^[A-Za-z0-9._\[\]-]+$", host or ""):
        raise BrowseError("bad", "Enter the export like 192.0.2.10:/volume1/media (or just the server to list exports)")
    export = export.strip()
    if export and (not export.startswith("/") or re.search(r"[\"'$`\\]", export)):
        raise BrowseError("bad", "NFS exports look like server:/export/path")
    return host, export.rstrip("/") or ("" if not export else "/")


# ------------------------------------------------------------------ local folders (and an existing share mount)
def list_local(path, root=None):
    """List sub-folders of `path`. With `root`, `path` is relative to root and may not leave it."""
    if root:
        root = os.path.realpath(root)
        rel = clean_rel(path)
        p = os.path.realpath(os.path.join(root, rel))
        if p != root and not p.startswith(root + os.sep):
            raise BrowseError("bad", "That folder is outside the share")
    else:
        p = os.path.realpath(path or "/")
    if not os.path.isdir(p):
        raise BrowseError("notfound", "Folder not found: %s" % (path or "/"))
    try:
        ents = list(os.scandir(p))
    except PermissionError:
        raise BrowseError("denied", "The media-server service user may not read %s" % p)
    dirs, videos = [], 0
    for e in ents:
        try:
            if e.name.startswith("."):
                continue
            if e.is_dir(follow_symlinks=True):
                dirs.append(e)
            elif _is_video(e.name):
                videos += 1
        except OSError:
            continue
    dirs.sort(key=lambda e: e.name.lower())
    out = []
    for e in dirs[:MAX_DIRS]:
        d = {"name": e.name}
        if len(dirs) <= 300:          # cheap: one level down
            try:
                d["videos"] = sum(1 for x in os.scandir(e.path) if not x.name.startswith(".") and _is_video(x.name))
            except OSError:
                pass
        out.append(d)
    if root:
        rel = os.path.relpath(p, root)
        rel = "" if rel == "." else rel
        return {"path": rel, "parent": (os.path.dirname(rel) if rel else None), "dirs": out, "videos": videos,
                "truncated": len(dirs) > MAX_DIRS}
    return {"path": p, "parent": os.path.dirname(p) if p != "/" else None, "dirs": out, "videos": videos,
            "truncated": len(dirs) > MAX_DIRS}


# ------------------------------------------------------------------ SMB via smbclient
SMB_ERRORS = [
    ("tree connect failed: NT_STATUS_OBJECT", "notfound", "No share with that name on the server."),
    ("tree connect failed: NT_STATUS_ACCESS_DENIED", "denied", "Access denied: this account may not open that share."),
    ("NT_STATUS_LOGON_FAILURE", "auth", "Wrong username or password for this share."),
    ("NT_STATUS_WRONG_PASSWORD", "auth", "Wrong username or password for this share."),
    ("NT_STATUS_ACCOUNT_DISABLED", "auth", "This account is disabled on the server."),
    ("NT_STATUS_ACCOUNT_LOCKED_OUT", "auth", "This account is locked on the server."),
    ("NT_STATUS_ACCESS_DENIED", "denied", "Access denied: this account may not open that folder."),
    ("NT_STATUS_BAD_NETWORK_NAME", "notfound", "No share with that name on the server."),
    ("NT_STATUS_OBJECT_NAME_NOT_FOUND", "notfound", "That folder doesn't exist on the share."),
    ("NT_STATUS_OBJECT_PATH_NOT_FOUND", "notfound", "That folder doesn't exist on the share."),
    ("NT_STATUS_NOT_A_DIRECTORY", "notfound", "That is a file, not a folder."),
    ("NT_STATUS_NO_SUCH_FILE", "notfound", "That folder doesn't exist on the share."),
    ("NT_STATUS_OBJECT_PATH_SYNTAX_BAD", "notfound", "That folder can't be opened on the share."),
    ("NT_STATUS_OBJECT_PATH_INVALID", "notfound", "That folder can't be opened on the share."),
    ("NT_STATUS_HOST_UNREACHABLE", "unreachable", "The server can't be reached (host unreachable)."),
    ("NT_STATUS_NETWORK_UNREACHABLE", "unreachable", "The server can't be reached (network unreachable)."),
    ("NT_STATUS_CONNECTION_REFUSED", "unreachable", "The server refused the connection (is file sharing on?)."),
    ("NT_STATUS_IO_TIMEOUT", "unreachable", "The server didn't answer in time."),
    ("NT_STATUS_UNSUCCESSFUL", "unreachable", "Could not connect to the server."),
    ("NT_STATUS_CONNECTION_RESET", "unreachable", "The server dropped the connection (try another SMB version)."),
    ("NT_STATUS_CONNECTION_DISCONNECTED", "unreachable", "The server dropped the connection (try another SMB version)."),
    ("NT_STATUS_INVALID_NETWORK_RESPONSE", "unreachable", "The server answered in a way this SMB version doesn't understand."),
    ("NT_STATUS_NOT_SUPPORTED", "unreachable", "The server doesn't support this SMB version."),
    ("Name or service not known", "unreachable", "Unknown server name."),
]


def _smb_err(out):
    for key, code, msg in SMB_ERRORS:
        if key in out:
            return BrowseError(code, msg)
    if "failed" in out.lower() and "connect" in out.lower():
        return BrowseError("unreachable", "Could not connect to the server.")
    return None


def smbclient_path():
    return shutil.which("smbclient") or ("/usr/bin/smbclient" if os.path.exists("/usr/bin/smbclient") else None)


def _smb_proto(options):
    o = options or ""
    if "vers=1.0" in o:
        return ["--option=client min protocol=NT1", "--option=client max protocol=NT1"]
    m = re.search(r"vers=(2\.0|2\.1|3\.0|3\.1\.1)", o)
    if m:
        p = {"2.0": "SMB2_02", "2.1": "SMB2_10", "3.0": "SMB3_00", "3.1.1": "SMB3_11"}[m.group(1)]
        return ["--option=client max protocol=%s" % p]
    return []


def _port(options):
    m = re.search(r"(?:^|,)port=(\d{1,5})(?:,|$)", options or "")
    return ["-p", m.group(1)] if m else []


def _run_smbclient(args, username, password, domain, options):
    exe = smbclient_path()
    for v in (username, password, domain):
        if v and ("\n" in v or "\r" in v):
            raise BrowseError("bad", "Credentials can't contain line breaks")
    tmpd = tempfile.mkdtemp(prefix="ms-browse-")      # 0700, only the service user
    try:
        cmd = [exe] + args + _smb_proto(options) + _port(options) + ["-t", "15"]
        if username:
            auth = os.path.join(tmpd, "auth")
            fd = os.open(auth, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write("username = %s\npassword = %s\n" % (username, password or ""))
                if domain:
                    f.write("domain = %s\n" % domain)
            cmd += ["-A", auth]
        else:
            cmd += ["-N"]
        env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": tmpd, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=SMB_TIMEOUT, env=env, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise BrowseError("unreachable", "The server didn't answer in time.")
        out = (p.stdout + p.stderr).decode("utf-8", errors="replace")
        err = _smb_err(out)
        if err:
            raise err
        if p.returncode != 0:
            raise BrowseError("unreachable", "Could not list the share (smbclient exit %d)." % p.returncode)
        return p.stdout.decode("utf-8", errors="replace")
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


LS_RE = re.compile(r"^  (.+?)\s+([DAHSRNVIX]*)\s+(\d+)\s+\w{3} \w{3}\s+\d+ \d\d:\d\d:\d\d \d{4}$")


def reach(host, port, timeout=5.0):
    """Fast, clear errors before smbclient / mount: unknown name, or nothing listening."""
    h = host.strip("[]")
    try:
        infos = socket.getaddrinfo(h, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise BrowseError("unreachable", "Unknown server name: %s" % host)
    last = None
    for fam, typ, proto, _, addr in infos[:4]:
        try:
            with socket.socket(fam, typ, proto) as so:
                so.settimeout(timeout)
                so.connect(addr)
                return
        except socket.timeout:
            last = "timeout"
        except OSError as e:
            last = e
    if last == "timeout":
        raise BrowseError("unreachable", "The server %s didn't answer (is it on, and is the address right?)." % host)
    raise BrowseError("unreachable", "The server %s refused the connection on port %d (is file sharing on?)." % (host, port))


def smb_port(options):
    m = re.search(r"(?:^|,)port=(\d{1,5})(?:,|$)", options or "")
    return int(m.group(1)) if m else 445


def smb_shares(host, username, password, domain, options):
    out = _run_smbclient(["-L", "//" + host, "-g"], username, password, domain, options)
    names = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) >= 2 and parts[0] == "Disk" and parts[1] and not parts[1].endswith("$"):
            names.append({"name": parts[1], "comment": parts[2] if len(parts) > 2 else ""})
    names.sort(key=lambda x: x["name"].lower())
    return names


def smb_list(host, share, rel, username, password, domain, options):
    args = ["//%s/%s" % (host, share)]
    if rel:
        args += ["-D", rel.replace("/", "\\")]
    out = _run_smbclient(args + ["-c", "ls"], username, password, domain, options)
    dirs, videos = [], 0
    for line in out.splitlines():
        m = LS_RE.match(line)
        if not m:
            continue
        name, attrs = m.group(1), m.group(2)
        if name in (".", "..") or name.startswith("."):
            continue
        if "D" in attrs:
            if "H" not in attrs and "S" not in attrs:
                dirs.append({"name": name})
        elif _is_video(name):
            videos += 1
    dirs.sort(key=lambda d: d["name"].lower())
    return dirs[:MAX_DIRS], videos, len(dirs) > MAX_DIRS


# ------------------------------------------------------------------ NFS / SMB via a temporary read-only mount
def helper_list(kind, remote, rel, options, username="", password="", domain="", as_share=None):
    if not shares.helper_available():
        raise BrowseError("unavailable", "Browsing needs the mount helper. Re-run install.sh, or type the sub-folder.")
    stdin = ""
    if as_share:      # 1.5.3: the helper reads the login of that share itself
        args = ["browse-as", str(int(as_share)), kind, remote, options or "", rel or ""]
    else:
        args = ["browse", kind, remote, options or "", rel or ""]
    if kind == "smb" and not as_share:
        for v in (username, password, domain):
            if v and ("\n" in v or "\r" in v):
                raise BrowseError("bad", "Credentials can't contain line breaks")
        stdin = "username=%s\npassword=%s\ndomain=%s\n" % (username or "", password or "", domain or "")
    try:
        p = subprocess.run(shares._helper_cmd(args), input=stdin.encode(), capture_output=True, timeout=45)
    except subprocess.TimeoutExpired:
        raise BrowseError("unreachable", "The server didn't answer in time.")
    except OSError as e:
        raise BrowseError("unavailable", str(e))
    err = p.stderr.decode("utf-8", errors="replace")
    if p.returncode != 0:
        if "a password is required" in err or "sudo:" in err or "usage:" in err:
            raise BrowseError("unavailable", "The mount helper can't browse yet (update the server), or type the sub-folder.")
        if "BROWSE-AUTH" in err:
            raise BrowseError("auth", "Wrong username or password for this share.")
        if "BROWSE-DENIED" in err:
            raise BrowseError("denied", "Access denied: the server doesn't let this account (or this server's IP) in.")
        if "BROWSE-NOTFOUND" in err:
            raise BrowseError("notfound", "That share or folder doesn't exist.")
        if "BROWSE-UNREACHABLE" in err:
            raise BrowseError("unreachable", "The server can't be reached.")
        if "BROWSE-BAD" in err:
            raise BrowseError("bad", "Bad folder name.")
        raise BrowseError("unreachable", "Could not open the share: %s" % (err.strip().splitlines() or ["?"])[-1][:200])
    dirs, videos, trunc = [], 0, False
    for rec in p.stdout.decode("utf-8", errors="replace").split("\0"):
        if rec.startswith("V\t"):
            try:
                videos = int(rec[2:])
            except ValueError:
                pass
        elif rec.startswith("T"):
            trunc = True
        elif rec.startswith("D\t"):
            _, cnt, name = (rec.split("\t", 2) + ["", ""])[:3]
            if name and not name.startswith("."):
                d = {"name": name}
                if cnt.isdigit():
                    d["videos"] = int(cnt)
                dirs.append(d)
    dirs.sort(key=lambda d: d["name"].lower())
    return dirs[:MAX_DIRS], videos, trunc


def helper_shares(as_share, host, options):
    """1.5.3: the shares on `host`, listed by the root helper with the login of existing share `as_share`."""
    if not shares.helper_available():
        raise BrowseError("unavailable", "Listing shares with a saved login needs the mount helper (update the server).")
    try:
        p = subprocess.run(shares._helper_cmd(["shares-as", str(int(as_share)), host, options or ""]),
                           input=b"", capture_output=True, timeout=45)
    except subprocess.TimeoutExpired:
        raise BrowseError("unreachable", "The server didn't answer in time.")
    except OSError as e:
        raise BrowseError("unavailable", str(e))
    out = (p.stdout + p.stderr).decode("utf-8", errors="replace")
    if p.returncode != 0:
        if "a password is required" in out or "sudo:" in out or "usage:" in out:
            raise BrowseError("unavailable", "The mount helper can't do this yet (update the server).")
        if "BROWSE-" in out:
            raise BrowseError("unavailable" if "not installed" in out else "bad", out.split("BROWSE-", 1)[1].split(" ", 1)[-1].strip()[:200])
        raise _smb_err(out) or BrowseError("unreachable", "Could not list the shares (exit %d)." % p.returncode)
    err = _smb_err(out)
    if err:
        raise err
    names = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) >= 2 and parts[0] == "Disk" and parts[1] and not parts[1].endswith("$"):
            names.append({"name": parts[1], "comment": parts[2] if len(parts) > 2 else ""})
    names.sort(key=lambda x: x["name"].lower())
    return names


def nfs_exports(host):
    exe = shutil.which("showmount") or "/usr/sbin/showmount"
    if not os.path.exists(exe):
        raise BrowseError("unavailable", "showmount (nfs-common) isn't installed; enter the export, e.g. %s:/volume1/media" % host)
    try:
        p = subprocess.run([exe, "-e", "--no-headers", host], capture_output=True, timeout=20, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise BrowseError("unreachable", "The NFS server didn't answer in time.")
    if p.returncode != 0:
        e = p.stderr.decode(errors="replace")
        if "not known" in e or "resolve" in e:
            raise BrowseError("unreachable", "Unknown server name.")
        raise BrowseError("unreachable", "Couldn't list the NFS exports (%s)." % (e.strip().splitlines() or ["no answer"])[-1][:160])
    ex = []
    for line in p.stdout.decode(errors="replace").splitlines():
        path = line.split()[0] if line.split() else ""
        if path.startswith("/"):
            ex.append({"name": path})
    return ex


# ------------------------------------------------------------------ entry point
def browse(src, rel=""):
    """src = {type, remote|path, username, password, domain, options}; rel = folder inside the share.
    Returns {mode: 'shares'|'dirs', remote, path, parent, dirs, videos, suggest, via}."""
    stype = (src.get("type") or "local").strip()
    opts = (src.get("options") or "").strip()
    if opts and not re.match(r"^[A-Za-z0-9_.=:,-]+$", opts):
        raise BrowseError("bad", "Bad options")
    if stype == "local":
        d = list_local(src.get("path") or rel or "/")
        d.update(mode="dirs", via="local", suggest=suggest_kind(os.path.basename(d["path"])))
        return d
    if stype == "smb":
        host, share, sub = parse_smb(src.get("remote"))
        user, pw, dom = (src.get("username") or "").strip(), src.get("password") or "", (src.get("domain") or "").strip()
        reach(host, smb_port(opts))
        if not share:
            if not smbclient_path():
                raise BrowseError("unavailable", "Listing the shares needs smbclient (apt install smbclient). "
                                  "Enter the share as //%s/ShareName and browse its folders." % host)
            return {"mode": "shares", "remote": "//" + host, "path": "", "parent": None, "via": "smbclient",
                    "dirs": smb_shares(host, user, pw, dom, opts), "videos": 0, "suggest": None}
        rel = clean_rel(rel if rel else sub)
        if smbclient_path():
            dirs, videos, trunc = smb_list(host, share, rel, user, pw, dom, opts)
            via = "smbclient"
        else:
            dirs, videos, trunc = helper_list("smb", "//%s/%s" % (host, share), rel, opts, user, pw, dom)
            via = "mount"
        name = rel.rsplit("/", 1)[-1] if rel else share
        return {"mode": "dirs", "remote": "//%s/%s" % (host, share), "path": rel,
                "parent": (rel.rsplit("/", 1)[0] if "/" in rel else "") if rel else None,
                "dirs": dirs, "videos": videos, "truncated": trunc, "via": via, "suggest": suggest_kind(name)}
    if stype == "nfs":
        host, export = parse_nfs(src.get("remote"))
        reach(host, 2049 if export else 111)
        if not export:
            return {"mode": "shares", "remote": host, "path": "", "parent": None, "via": "showmount",
                    "dirs": nfs_exports(host), "videos": 0, "suggest": None}
        rel = clean_rel(rel)
        dirs, videos, trunc = helper_list("nfs", "%s:%s" % (host, export), rel, opts)
        name = rel.rsplit("/", 1)[-1] if rel else export.rsplit("/", 1)[-1]
        return {"mode": "dirs", "remote": "%s:%s" % (host, export), "path": rel,
                "parent": (rel.rsplit("/", 1)[0] if "/" in rel else "") if rel else None,
                "dirs": dirs, "videos": videos, "truncated": trunc, "via": "mount", "suggest": suggest_kind(name)}
    raise BrowseError("bad", "Unknown source type")
