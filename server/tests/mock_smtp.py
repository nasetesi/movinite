"""1.9: a fake SMTP server for tests (no internet, no real mailbox).

    from tests import mock_smtp; srv = mock_smtp.start(mode="starttls")   # or "ssl" / "plain"
    srv.port, srv.received -> [{"from", "to", "data", "user", "tls"}]

Accepts only the fake login below (AUTH PLAIN or LOGIN). TLS uses a throwaway self-signed certificate for
"localhost" made at start-up; point the app at it with MS_SMTP_CAFILE=mock_smtp.CAFILE.
srv.fail = {"auth": "535 5.7.8 ...", "mail": ["421 4.7.0 Try again later"], "rcpt": [...], "data": [...]}
injects replies (lists are consumed one per message).
"""
import base64
import datetime
import os
import socket
import ssl
import tempfile
import threading

USER = "test.host@gmail.com"
PASSWORD = "abcdefghijklmnop"          # fake 16-letter "app password"
_DIR = tempfile.mkdtemp(prefix="mock-smtp-")
CAFILE = os.path.join(_DIR, "cert.pem")
KEYFILE = os.path.join(_DIR, "key.pem")


def _make_cert():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    import ipaddress
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    with open(CAFILE, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(KEYFILE, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


_make_cert()


def _server_ctx():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CAFILE, KEYFILE)
    return ctx


class Server:
    def __init__(self, mode):
        self.mode = mode
        self.received = []
        self.fail = {}
        self.logins = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(c,), daemon=True).start()

    def _pop(self, k):
        v = self.fail.get(k)
        if isinstance(v, list):
            return v.pop(0) if v else None
        return v

    def _handle(self, conn):
        tls = False
        try:
            if self.mode == "ssl":
                conn = _server_ctx().wrap_socket(conn, server_side=True)
                tls = True
            f = conn.makefile("rb")

            def out(line):
                conn.sendall((line + "\r\n").encode())

            out("220 mock.smtp ESMTP ready")
            user = None
            mail_from, rcpts = None, []
            while True:
                raw = f.readline()
                if not raw:
                    return
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                cmd = line[:4].upper()
                if cmd in ("EHLO", "HELO"):
                    caps = ["250-mock.smtp", "250-SIZE 35882577", "250-8BITMIME"]
                    if self.mode == "starttls" and not tls:
                        caps.append("250-STARTTLS")
                    if tls or self.mode == "plain":
                        caps.append("250-AUTH LOGIN PLAIN")
                    caps.append("250 SMTPUTF8")
                    out("\r\n".join(caps))
                elif line.upper() == "STARTTLS":
                    out("220 2.0.0 Ready to start TLS")
                    conn = _server_ctx().wrap_socket(conn, server_side=True)
                    f = conn.makefile("rb")
                    tls = True
                elif cmd == "AUTH":
                    parts = line.split()
                    mech = parts[1].upper() if len(parts) > 1 else ""
                    if mech == "PLAIN":
                        blob = parts[2] if len(parts) > 2 else None
                        if not blob:
                            out("334 ")
                            blob = f.readline().decode().strip()
                        dec = base64.b64decode(blob).split(b"\0")
                        u, p = dec[1].decode(), dec[2].decode()
                    elif mech == "LOGIN":
                        if len(parts) > 2:
                            u = base64.b64decode(parts[2]).decode()
                        else:
                            out("334 VXNlcm5hbWU6")
                            u = base64.b64decode(f.readline().strip()).decode()
                        out("334 UGFzc3dvcmQ6")
                        p = base64.b64decode(f.readline().strip()).decode()
                    else:
                        out("504 5.5.4 Unrecognized authentication type")
                        continue
                    self.logins.append(u)
                    forced = self._pop("auth")
                    if forced:
                        out(forced)
                    elif u == USER and p == PASSWORD:
                        user = u
                        out("235 2.7.0 Accepted")
                    else:
                        out("535-5.7.8 Username and Password not accepted. For more information, go to\r\n535 5.7.8  https://support.google.com/mail/?p=BadCredentials mock")
                elif cmd == "MAIL":
                    if self.mode != "plain" and not user:
                        out("530-5.7.0 Authentication Required\r\n530 5.7.0 mock")
                        continue
                    forced = self._pop("mail")
                    if forced:
                        out(forced)
                        if forced.startswith("421"):
                            return
                        continue
                    mail_from, rcpts = line.split(":", 1)[1].strip().split()[0].strip("<>"), []
                    out("250 2.1.0 OK")
                elif cmd == "RCPT":
                    forced = self._pop("rcpt")
                    if forced:
                        out(forced)
                        continue
                    rcpts.append(line.split(":", 1)[1].strip().split()[0].strip("<>"))
                    out("250 2.1.5 OK")
                elif cmd == "DATA":
                    out("354 Go ahead")
                    buf = []
                    while True:
                        d = f.readline()
                        if d in (b".\r\n", b".\n", b""):
                            break
                        if d.startswith(b".."):
                            d = d[1:]
                        buf.append(d)
                    forced = self._pop("data")
                    if forced:
                        out(forced)
                        continue
                    self.received.append({"from": mail_from, "to": rcpts, "data": b"".join(buf), "user": user, "tls": tls})
                    out("250 2.0.0 OK mock-queued")
                elif cmd == "RSET":
                    mail_from, rcpts = None, []
                    out("250 2.1.5 Flushed")
                elif cmd == "NOOP":
                    out("250 2.0.0 OK")
                elif cmd == "QUIT":
                    out("221 2.0.0 closing connection")
                    return
                else:
                    out("502 5.5.1 Unrecognized command")
        except (OSError, ssl.SSLError, ValueError, IndexError):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass


def start(mode="starttls"):
    return Server(mode)
