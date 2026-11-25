"""1.9: the server's own Ed25519 identity and the secrets folder.

data/secrets/            0700, owned by the service user
data/secrets/server_ed25519   raw 32-byte private seed, 0600 (never printed, never sent anywhere)

The public key / fingerprint identify this server (2.0 offline grants, 2.1 server-to-server sharing).
1.9 uses the key to derive an AES-256-GCM key (HKDF) that encrypts other secrets at rest, for example the
Gmail OAuth refresh tokens.  This protects a copied database or a stray log/screenshot -- it does not
protect against root on this server, because the key lives on the same disk.
"""
import base64
import hashlib
import json
import logging
import os
import secrets as _secrets
import threading

from . import config

log = logging.getLogger("media-server")
SECRETS_DIR = config.DATA_DIR / "secrets"
KEY_FILE = SECRETS_DIR / "server_ed25519"
_lock = threading.RLock()
_seed = None


def available():
    try:
        import cryptography  # noqa: F401
        return True
    except Exception:
        return False


def _ensure_dir():
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(SECRETS_DIR, 0o700)
    except OSError:
        pass


def _write_private(path, data: bytes):
    """Atomic write with mode 0600 from the first byte."""
    _ensure_dir()
    tmp = path.with_name(path.name + ".tmp%d" % os.getpid())
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(path))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def ensure():
    """Create the server key on first start. Returns True when a key is available."""
    global _seed
    with _lock:
        if _seed is not None:
            return True
        try:
            if KEY_FILE.is_file():
                raw = KEY_FILE.read_bytes()
                if len(raw) != 32:
                    log.error("server key %s has the wrong size; not using it", KEY_FILE)
                    return False
                _seed = raw
                try:
                    os.chmod(KEY_FILE, 0o600)
                except OSError:
                    pass
            else:
                _seed = _secrets.token_bytes(32)
                _write_private(KEY_FILE, _seed)
                log.info("created this server's identity key (%s)", fingerprint())
            return True
        except OSError as e:
            log.error("cannot create the server key: %s", e)
            return False


def _private():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if not ensure():
        raise RuntimeError("server key is not available")
    return Ed25519PrivateKey.from_private_bytes(_seed)


def public_bytes():
    from cryptography.hazmat.primitives import serialization
    return _private().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def server_id():
    return base64.b32encode(hashlib.sha256(public_bytes()).digest()).decode().rstrip("=")[:20]


def fingerprint():
    """Human-friendly: MOVI-XXXX-XXXX-XXXX (first 12 chars of the server id)."""
    try:
        s = server_id()
    except Exception:
        return None
    return "MOVI-%s-%s-%s" % (s[0:4], s[4:8], s[8:12])


def sign(data: bytes) -> bytes:
    return _private().sign(data)


def derive_key(purpose: str) -> bytes:
    """32-byte symmetric key for one purpose, derived from the server key (HKDF-SHA256). Never stored."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    if not ensure():
        raise RuntimeError("server key is not available")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"movinite-" + server_id().encode(),
                info=("movinite/%s" % purpose).encode()).derive(_seed)


def seal(purpose: str, obj) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = _secrets.token_bytes(12)
    ct = AESGCM(derive_key(purpose)).encrypt(nonce, json.dumps(obj).encode(), purpose.encode())
    return b"MVS1" + nonce + ct


def unseal(purpose: str, blob: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not blob.startswith(b"MVS1") or len(blob) < 4 + 12 + 16:
        raise ValueError("not a sealed Movinite secret")
    return json.loads(AESGCM(derive_key(purpose)).decrypt(blob[4:16], blob[16:], purpose.encode()))


def write_sealed(path, purpose, obj):
    _write_private(path, seal(purpose, obj))


def read_sealed(path, purpose, default=None):
    if not path.is_file():
        return default
    return unseal(purpose, path.read_bytes())


def _reset_for_tests():
    global _seed
    _seed = None
