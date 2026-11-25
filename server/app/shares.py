"""Network shares: thin wrapper around the root-only mount helper (run through sudo)."""
import os
import re
import subprocess
from pathlib import Path

from . import config


def _helper_cmd(args):
    if os.geteuid() == 0 or os.environ.get("MS_MOUNT_HELPER_NOSUDO") == "1":   # the latter: tests with a stand-in helper
        return [config.MOUNT_HELPER] + args
    return ["sudo", "-n", config.MOUNT_HELPER] + args


def helper_available():
    return Path(config.MOUNT_HELPER).exists()


def validate(kind, remote):
    remote = (remote or "").strip()
    if kind == "smb":
        remote = remote.replace("\\", "/")
        if remote.lower().startswith("smb:"):
            remote = remote[4:]
        if not remote.startswith("//"):
            remote = "//" + remote.lstrip("/")
        if not re.match(r"^//[A-Za-z0-9._:-]+/[^/\"'$`][^\"'$`]*$", remote):
            raise ValueError("SMB path must look like //server/share or //server/share/folder")
        return remote.rstrip("/")
    if kind == "nfs":
        if remote.lower().startswith("nfs://"):
            rest = remote[6:]
            host, _, path = rest.partition("/")
            remote = "%s:/%s" % (host, path)
        if not re.match(r"^[A-Za-z0-9._:\[\]-]+:/[^\"'$`]*$", remote):
            raise ValueError("NFS path must look like server:/export/path")
        return remote
    raise ValueError("Share type must be smb or nfs")


def mount_point(share_id):
    return str(config.SHARES_DIR / str(int(share_id)))


def mount(share_id, kind, remote, options="", username="", password="", domain="", allow_write=False):
    stdin = ""
    if kind == "smb":
        stdin = "username=%s\npassword=%s\ndomain=%s\n" % (username or "", password or "", domain or "")
        if "\n" in (username or "") + (password or "") + (domain or ""):
            raise ValueError("credentials cannot contain line breaks")
    return _run(["add", str(int(share_id)), kind, remote, options or "", "rw" if allow_write else "ro"], stdin, timeout=60)


def mount_as(share_id, src_id, kind, remote, options="", allow_write=False):
    """1.5.3: mount a new share with the login of existing share `src_id` (copied by the root helper; the
    app never reads the password).  Each share keeps its own copy, so removing one never breaks another."""
    return _run(["add-as", str(int(share_id)), str(int(src_id)), kind, remote, options or "", "rw" if allow_write else "ro"], "", timeout=60)


def set_access(share_id, allow_write):
    """1.3: remount a share read-write (artwork saving only) or back to read-only."""
    return _run(["access", str(int(share_id)), "rw" if allow_write else "ro"], "", timeout=90)


def mount_mode(share_id):
    """'rw' / 'ro' as currently mounted, or None."""
    mp = os.path.realpath(mount_point(share_id))
    try:
        with open("/proc/self/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) > 3 and parts[1].replace("\\040", " ") == mp:
                    return parts[3].split(",")[0]
    except OSError:
        pass
    return None


def remount(share_id):
    return _run(["remount", str(int(share_id))], "", timeout=60)


def unmount(share_id):
    return _run(["remove", str(int(share_id))], "", timeout=60)


def is_mounted(share_id):
    mp = os.path.realpath(mount_point(share_id))
    try:
        with open("/proc/self/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) > 1 and parts[1].replace("\\040", " ") == mp:
                    return True
    except OSError:
        pass
    return False


def _run(args, stdin, timeout):
    if not helper_available():
        return False, "Mount helper not installed (%s). Re-run install.sh." % config.MOUNT_HELPER
    try:
        p = subprocess.run(_helper_cmd(args), input=stdin.encode(), capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "Timed out talking to the server (is it reachable?)"
    except OSError as e:
        return False, str(e)
    out = (p.stdout + p.stderr).decode(errors="replace").strip()
    if p.returncode != 0:
        if "a password is required" in out or "sudo:" in out:
            out = "Not allowed to mount (sudoers rule missing). Re-run install.sh. " + out
        return False, out or "mount helper failed (exit %d)" % p.returncode
    return True, out
