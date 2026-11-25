# Security policy

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Instead, use GitHub's private reporting:
the **Security** tab of this repository → **Report a vulnerability**.

Include the version (`/api/health` shows it), the steps to reproduce and the impact. You should get a reply within
a week. Please give us reasonable time to fix the problem before you disclose it.

## Supported versions

Only the latest release gets security fixes. Update with `update.sh`.

## How Movinite is meant to be deployed

- The web app runs as an unprivileged `media-server` user. The only thing it can run as root is the
  `helpers/media-server-mount` helper (through a single sudoers rule), which only manages read-only mounts under
  `/srv/media-server/shares/<id>`.
- Share passwords are stored in root-only credential files (`0600`) and are never sent back to the browser.
- User passwords are stored hashed. Sessions use an HTTP-only cookie.
- Plain HTTP is fine on a home network. For access from the internet, put Movinite behind a reverse proxy with HTTPS
  (see `server/README.md`), and keep the server's port closed to the outside.
- Delete `/opt/media-server/ADMIN_PASSWORD` after your first sign-in.
