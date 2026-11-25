"""Command line: python -m app.cli init | reset-admin [username] | scan <library_id|all> | run | hw-setup [--if-unset] [--by NAME] | hw-get"""
import os
import secrets
import sys

from . import auth, config, db


def cmd_init():
    db.migrate()
    print("database: %s" % config.DB_PATH)
    if db.row("SELECT COUNT(*) n FROM users WHERE is_admin=1")["n"]:
        print("ADMIN_STATUS=exists")
        return
    pw = os.environ.get("MS_ADMIN_PASSWORD") or secrets.token_urlsafe(14)
    auth.create_user("admin", pw, is_admin=True, must_change=True)
    print("ADMIN_STATUS=created")
    if not os.environ.get("MS_ADMIN_PASSWORD"):
        print("admin password: %s" % pw)


def cmd_reset_admin(username="admin"):
    db.migrate()
    pw = os.environ.get("MS_ADMIN_PASSWORD") or secrets.token_urlsafe(14)
    u = db.row("SELECT id FROM users WHERE username=?", (username,))
    if u:
        auth.set_password(u["id"], pw, must_change=True)
        with db.tx() as c:
            c.execute("UPDATE users SET is_admin=1 WHERE id=?", (u["id"],))
    else:
        auth.create_user(username, pw, is_admin=True, must_change=True)
    print("username: %s" % username)
    print("password: %s" % pw)


def cmd_scan(which):
    from . import scanner
    db.migrate()
    ids = [r["id"] for r in db.rows("SELECT id FROM libraries")] if which == "all" else [int(which)]
    for i in ids:
        scanner.scan_library(i)
        print("library %s: %s" % (i, scanner.status.get(i)))


def cmd_hw_setup(args):
    """1.5.2: scan for video cards, test-encode, save hw_transcode.  --if-unset keeps a value already chosen."""
    from . import hwaccel
    db.migrate()
    by = args[args.index("--by") + 1] if "--by" in args and args.index("--by") + 1 < len(args) else "install"
    r = hwaccel.setup(if_unset="--if-unset" in args, by=by)
    for c in r["det"]["cards"]:
        extra = ("methods: " + ", ".join(hwaccel.LABEL[m] for m in c["methods"])) if c.get("methods") else c.get("note", "")
        print("HW_CARD=%s | %s | driver %s | %s" % (c["name"], c["render"] or "no render node", c["driver"] or "-", extra))
    if not r["det"]["cards"]:
        print("HW_CARD=none")
    for t in r["tests"]:
        print("HW_TEST=%s %s %s" % (hwaccel.LABEL[t["method"]], t["device"],
                                   ("OK (%s fps)" % t.get("fps")) if t["ok"] else "FAILED: %s" % t.get("error", "")))
        if t.get("hint"):
            print("HW_HINT=%s" % t["hint"])
    print("HW_MODE=%s" % r["mode"])
    print("HW_DEVICE=%s" % (r["device"] or ""))
    print("HW_KEPT=%s" % ("yes" if r["kept"] else "no"))


def cmd_hw_get():
    from . import hwaccel, settings
    db.migrate()
    print(settings.get("hw_transcode") or "")


def cmd_run():
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=config.PORT)


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    c = argv[0]
    if c == "init":
        cmd_init()
    elif c == "reset-admin":
        cmd_reset_admin(*(argv[1:2] or ["admin"]))
    elif c == "scan":
        cmd_scan(argv[1] if len(argv) > 1 else "all")
    elif c == "run":
        cmd_run()
    elif c == "hw-setup":
        cmd_hw_setup(argv[1:])
    elif c == "hw-get":
        cmd_hw_get()
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
