"""Hashing, pseudonymisation, symmetric encryption and Ed25519 signatures."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import string
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PID_HEX_LEN = 32  # DECISIONS D-09


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def pid_for_mrn(site_key: bytes, mrn: str) -> str:
    """Stable pseudonymous patient id: ``hex(HMAC-SHA256(site_key, MRN))[:32]`` (SPEC §4.6, D-09)."""
    if len(site_key) < 16:
        raise ValueError("site HMAC key must be at least 16 bytes")
    return hmac.new(site_key, mrn.strip().encode("utf-8"), hashlib.sha256).hexdigest()[:PID_HEX_LEN]


def load_or_create_key(path: Path, size: int = 32) -> bytes:
    """Read a binary key file, creating it (mode 0600) with random bytes when absent."""
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(size)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    return key


def aes_encrypt(key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def aes_decrypt(key: bytes, blob: bytes, aad: bytes = b"") -> bytes:
    return AESGCM(key).decrypt(blob[:12], blob[12:], aad)


def random_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def ed25519_generate() -> tuple[bytes, bytes]:
    """Return (private_pem, public_pem)."""
    key = Ed25519PrivateKey.generate()
    priv = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return priv, pub


def ed25519_sign(private_pem: bytes, data: bytes) -> bytes:
    key = serialization.load_pem_private_key(private_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("not an Ed25519 private key")
    return key.sign(data)


def ed25519_verify(public_pem: bytes, data: bytes, signature: bytes) -> bool:
    key = serialization.load_pem_public_key(public_pem)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("not an Ed25519 public key")
    try:
        key.verify(signature, data)
    except InvalidSignature:
        return False
    return True
