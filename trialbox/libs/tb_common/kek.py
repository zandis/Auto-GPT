"""The site keys under a key-encryption key (KEK), and the unseal (T-210b; CR-041 second third, OPS-058; D-347).

The keys of the secrets folder (``site_hmac.key``, ``pid_map.key``, ``objects.key`` once the object store is
sealed, T-210c, and the two signing keys, ``audit_sign.key`` of the signed audit heads and ``edc_sign.key`` of the EDC
signature binding, T-210d) are kept wrapped: ``<name>.wrapped`` is a small JSON document (format
``tb-wrapped-key/1``) with the key sealed by AES-256-GCM under the KEK. The associated data binds the format, the
key's file name and the KEK's id, so a wrapped file renamed to another key, or opened with another KEK, is refused.
The document also carries the key's fingerprint (``tb_common.crypto.key_fingerprint``), so ``tools/keys.py status``
and ``doctor`` can name the key without opening it.

``kek.json`` in the same folder describes the KEK without holding it: its id (a domain-separated SHA-256), its back
end and the back end's public parameters. Back ends:

* ``passphrase``: the KEK is scrypt(passphrase, salt). The passphrase is typed at boot (``tools.keys unseal``, which
  writes the KEK file) or read by ``tools.keys`` from a root-only file or stdin and handed here in the mapping it
  builds; never from the process environment (H-96, H-97: refused), never a file in the secrets folder;
* ``shamir``: a random KEK split into ``n`` shares of which any ``k`` give it back (GF(256), one share per steward).
  ``tools/keys.py unseal`` takes ``k`` shares, checks them against ``kek.json`` and writes the KEK to a runtime file;
* ``file``: a random KEK written once to a place outside the data volume that the host protects: a TPM-sealed
  systemd credential (``systemd-creds encrypt --with-key=tpm2``; the service then reads
  ``$CREDENTIALS_DIRECTORY/trialbox-kek``), Windows DPAPI on the WSL2 host, or removable media. Its recovery copy
  (D-894) is an escrow set: the KEK split into custodians' shares, recorded in ``kek.json``'s ``escrow`` (set id,
  threshold, count, the KEK id it opens, each share's custodian and fingerprint; never a share);
* ``kms``: the platform variant (T-319, D-432; IT pack §A.6 "KEK in KMS"). A random KEK sealed by the hospital's key
  management service, which keeps the key that seals it; ``kek.json`` holds the KMS address, the key's name and the
  KMS ciphertext (useless without the KMS). The client speaks the transit protocol of Vault and OpenBao
  (``POST <url>/encrypt/<key>`` and ``<url>/decrypt/<key>``, the token in ``X-Vault-Token``). The token comes from
  ``TB_KMS_TOKEN`` (an environment variable; on a platform the Secret ``trialbox-kms``, which holds a revocable
  credential for the KMS, never the KEK); ``TB_KMS_URL`` replaces the recorded address when it moves. Only https, or
  plain http to the loopback for a test KMS. No proxy is used: the KMS is inside the hospital.

Where a running service finds the KEK (:func:`load_kek`), in order: ``TB_KEK_FILE`` (default ``/run/trialbox/kek``,
a tmpfs the unseal writes), ``$CREDENTIALS_DIRECTORY/trialbox-kek``, then ``TB_KEK_PASSPHRASE`` of a mapping a tool
built from a root-only file or stdin for the passphrase back end (the process environment's is refused), or the KMS
for the ``kms`` back end when ``TB_KMS_TOKEN`` is set. A KEK file inside the secrets folder is refused: a KEK beside
the keys it wraps protects nothing. A KEK whose id is not ``kek.json``'s is refused.
With none of them the key load fails closed (:class:`KekLockedError`); the night, the pid map and the console say
why and no key is made in its place.

A plain key file still loads (boxes from before T-210b); ``doctor`` (check ``key_custody``) FAILs it in VALIDATION
and PRODUCTION and ``tools/keys.py wrap`` wraps it. A plain copy beside a wrapped one is refused: it is a left-over
or a key made by mistake, and either could be the wrong one.

Standard library only at import (the host python3 of ``tools/apply_update.sh`` may lack ``cryptography``): AES-GCM
is imported where a key is wrapped or opened.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

META_FILE = "kek.json"
META_FORMAT = "tb-kek/1"
WRAP_FORMAT = "tb-wrapped-key/1"
WRAPPED_SUFFIX = ".wrapped"
KEK_LEN = 32
#: the keys of the secrets folder that are kept under the KEK; ``objects.key`` seals the object store (T-210c);
#: ``audit_sign.key`` signs the audit heads (T-211a) and ``edc_sign.key`` binds the EDC signatures (D-281; T-210d);
#: ``restic.key`` is the incremental backup's repository password (D-968), made only under a KEK
PROTECTED = ("site_hmac.key", "pid_map.key", "objects.key", "audit_sign.key", "edc_sign.key", "restic.key")
#: protected keys a box may not have yet (a store never sealed, no audit key made, no EDC signature yet): not listed
#: by :func:`custody` while absent
OPTIONAL = ("objects.key", "audit_sign.key", "edc_sign.key", "restic.key")
BACKENDS = ("passphrase", "shamir", "file", "kms")
KMS_TIMEOUT = 10.0
KMS_KEY_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
DEFAULT_KEK_FILE = "/run/trialbox/kek"
CREDENTIAL = "trialbox-kek"  # systemd LoadCredentialEncrypted= name
#: scrypt cost of the passphrase back end (stored in kek.json, so a later box can raise it)
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1
SHARE_PREFIX = "tbks1"
STRICT_ENVS = ("VALIDATION", "PRODUCTION")


class KekError(RuntimeError):
    """A wrapped key cannot be opened safely: wrong KEK, a damaged or renamed file, a KEK beside the keys."""


class KekLockedError(KekError):
    """The KEK is not available here (not unsealed, no passphrase, no credential): nothing is opened or made."""


def kek_id(kek: bytes) -> str:
    """A one-way, domain-separated id of a KEK (32 hex), stored in ``kek.json`` and every wrapped file."""
    return hashlib.sha256(b"trialbox kek id\x00" + kek).hexdigest()[:32]


def fingerprint(key: bytes) -> str:
    """``tb_common.crypto.key_fingerprint`` without importing ``cryptography`` (the same formula; a test holds it)."""
    return hashlib.sha256(b"trialbox key fingerprint\x00" + key).hexdigest()[:32]


def wrapped_path(path: Path) -> Path:
    """``secrets/site_hmac.key`` -> ``secrets/site_hmac.key.wrapped``."""
    return path.with_name(path.name + WRAPPED_SUFFIX)


def key_present(path: Path) -> bool:
    """Whether the key of ``path`` exists in either form (plain or wrapped)."""
    return path.exists() or wrapped_path(path).exists()


def _write_private(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` (mode 0600) through a temporary file and a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# ------------------------------------------------------------------------------------------------ kek.json


def read_meta(secrets_dir: Path) -> dict[str, Any] | None:
    """``kek.json`` of the folder, or None when the folder has no KEK; :class:`KekError` when it is not one."""
    path = secrets_dir / META_FILE
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise KekError(f"{path} cannot be read ({type(exc).__name__})") from None
    if not isinstance(doc, dict) or doc.get("format") != META_FORMAT or doc.get("backend") not in BACKENDS:
        raise KekError(f"{path} is not a {META_FORMAT} file")
    if not isinstance(doc.get("kek_id"), str):
        raise KekError(f"{path} has no kek_id")
    return doc


def write_meta(secrets_dir: Path, meta: Mapping[str, Any], *, suffix: str = "") -> Path:
    path = secrets_dir / (META_FILE + suffix)
    _write_private(path, (json.dumps(dict(meta), indent=1, sort_keys=True) + "\n").encode())
    return path


def new_meta(backend: str, kek: bytes, **params: Any) -> dict[str, Any]:
    if backend not in BACKENDS:
        raise KekError(f"unknown KEK back end {backend!r} (one of {', '.join(BACKENDS)})")
    return {"format": META_FORMAT, "backend": backend, "kek_id": kek_id(kek), **params}


# ------------------------------------------------------------------------------------------------ kms (platform)


def _kms_endpoint(base: str, op: str, key: str) -> str:
    u = urllib.parse.urlsplit(base)
    loopback = u.hostname in ("127.0.0.1", "::1", "localhost")
    if u.scheme != "https" and not (u.scheme == "http" and loopback):
        raise KekError(f"the KMS address {base} is not https (only a loopback test KMS may be plain http)")
    if not KMS_KEY_NAME.match(key):
        raise KekError(f"{key!r} is not a KMS key name")
    return f"{base.rstrip('/')}/{op}/{key}"


def _kms_call(base: str, op: str, key: str, token: str, body: Mapping[str, str]) -> dict[str, Any]:
    """One transit call. The token never appears in an error; the KMS's own answer is not echoed either."""
    req = urllib.request.Request(  # noqa: S310 - https or loopback http only (_kms_endpoint)
        _kms_endpoint(base, op, key),
        data=json.dumps(body).encode(),
        method="POST",
        headers={"X-Vault-Token": token, "Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=KMS_TIMEOUT) as r:  # nosec B310: https or loopback only, checked above
            doc = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise KekError(f"the KMS refused {op} with key {key}: HTTP {e.code}") from None
    except (OSError, ValueError) as e:
        raise KekError(f"the KMS at {base} did not answer {op}: {type(e).__name__}") from None
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, dict):
        raise KekError(f"the KMS at {base} gave no data for {op}")
    return data


def kms_seal(kek: bytes, url: str, key: str, token: str) -> dict[str, Any]:
    """The ``kms`` back end's public parameters for ``kek`` (sealed by the KMS now)."""
    if not token:
        raise KekError("TB_KMS_TOKEN is not set: the KMS needs a token")
    ct = _kms_call(url, "encrypt", key, token, {"plaintext": base64.b64encode(kek).decode()}).get("ciphertext")
    if not isinstance(ct, str) or not ct:
        raise KekError(f"the KMS at {url} returned no ciphertext")
    return {"kms_url": url, "kms_key": key, "kms_ciphertext": ct}


def kms_open(meta: Mapping[str, Any], env: Mapping[str, str]) -> bytes:
    """The KEK from the KMS, checked against ``kek.json``'s id."""
    token = env.get("TB_KMS_TOKEN") or ""
    if not token:
        raise KekLockedError("TB_KMS_TOKEN is not set: the KEK stays sealed in the KMS")
    url = env.get("TB_KMS_URL") or str(meta.get("kms_url") or "")
    data = _kms_call(url, "decrypt", str(meta.get("kms_key") or ""), token, {"ciphertext": str(meta["kms_ciphertext"])})
    try:
        kek = base64.b64decode(str(data.get("plaintext") or ""), validate=True)
    except ValueError:
        raise KekError(f"the KMS at {url} returned no key") from None
    if len(kek) != KEK_LEN or not hmac.compare_digest(kek_id(kek), str(meta["kek_id"])):
        raise KekError(f"the KMS at {url} returned a key that is not this box's KEK (kek.json names {meta['kek_id']})")
    return kek


# ------------------------------------------------------------------------------------------------ passphrase


def passphrase_params() -> dict[str, Any]:
    return {"salt": secrets.token_hex(16), "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P}


def derive_from_passphrase(passphrase: str, meta: Mapping[str, Any]) -> bytes:
    """The KEK of the passphrase back end: scrypt with the salt and cost of ``meta``."""
    if not passphrase:
        raise KekError("an empty passphrase is refused")
    n, r, p = int(meta["n"]), int(meta["r"]), int(meta["p"])
    return hashlib.scrypt(
        passphrase.encode("utf-8"), salt=bytes.fromhex(str(meta["salt"])), n=n, r=r, p=p, dklen=KEK_LEN,
        maxmem=256 * n * r * p + (1 << 20),
    )  # fmt: skip


# ------------------------------------------------------------------------------------------------ Shamir, GF(256)

_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x ^= (x << 1) ^ (0x11B if x & 0x80 else 0)  # multiply by the generator 3
        x &= 0xFF
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _div(a: int, b: int) -> int:
    if b == 0:
        raise ZeroDivisionError("division by zero in GF(256)")
    return 0 if a == 0 else _EXP[_LOG[a] - _LOG[b] + 255]


def split_secret(secret: bytes, threshold: int, count: int) -> list[tuple[int, bytes]]:
    """``count`` shares ``(x, y)`` of ``secret``, any ``threshold`` of which give it back (Shamir over GF(256))."""
    if not 2 <= threshold <= count <= 255:
        raise KekError(f"{threshold} of {count} shares: need 2 <= threshold <= count <= 255")
    coeffs = [[b, *secrets.token_bytes(threshold - 1)] for b in secret]
    shares: list[tuple[int, bytes]] = []
    for x in range(1, count + 1):
        out = bytearray()
        for poly in coeffs:
            y = 0
            for c in reversed(poly):  # Horner
                y = _mul(y, x) ^ c
            out.append(y)
        shares.append((x, bytes(out)))
    return shares


def combine_shares(shares: list[tuple[int, bytes]]) -> bytes:
    """The secret at x = 0 by Lagrange interpolation; the shares must have distinct x and one length."""
    xs = [x for x, _ in shares]
    if len(set(xs)) != len(xs) or 0 in xs:
        raise KekError("shares must have distinct, non-zero indexes")
    if len({len(y) for _, y in shares}) != 1:
        raise KekError("shares of different lengths")
    out = bytearray()
    for i in range(len(shares[0][1])):
        acc = 0
        for j, (xj, yj) in enumerate(shares):
            num, den = 1, 1
            for m, (xm, _) in enumerate(shares):
                if m != j:
                    num = _mul(num, xm)
                    den = _mul(den, xm ^ xj)
            acc ^= _mul(yj[i], _div(num, den))
        out.append(acc)
    return bytes(out)


@dataclass(frozen=True)
class Share:
    set_id: str
    threshold: int
    count: int
    index: int
    data: bytes

    def text(self) -> str:
        body = f"{SHARE_PREFIX}-{self.set_id}-{self.threshold}of{self.count}-{self.index}-{self.data.hex()}"
        return f"{body}-{_share_check(body)}"


def _share_check(body: str) -> str:
    return hashlib.sha256(b"trialbox share\x00" + body.encode()).hexdigest()[:8]


def parse_share(text: str) -> Share:
    """A share as written by :func:`make_shares`; :class:`KekError` on a typo (the check) or another format."""
    t = text.strip()
    parts = t.split("-")
    if len(parts) != 6 or parts[0] != SHARE_PREFIX or "of" not in parts[2]:
        raise KekError("not a TrialBox key share (tbks1-...)")
    body, check = t.rsplit("-", 1)
    if not hmac.compare_digest(_share_check(body), check):
        raise KekError("a share does not pass its check: mistyped or damaged")
    k, n = parts[2].split("of", 1)
    try:
        return Share(parts[1], int(k), int(n), int(parts[3]), bytes.fromhex(parts[4]))
    except ValueError:
        raise KekError("not a TrialBox key share (bad number or hex)") from None


def make_shares(kek: bytes, threshold: int, count: int) -> tuple[str, list[Share]]:
    """``(set_id, shares)``: the shares of one split carry its set id, so a share of another split is refused."""
    set_id = secrets.token_hex(4)
    return set_id, [Share(set_id, threshold, count, x, y) for x, y in split_secret(kek, threshold, count)]


def kek_from_shares(meta: Mapping[str, Any], texts: list[str]) -> bytes:
    """The KEK from ``threshold`` or more share texts, checked against ``kek.json``. Refused: a share of another
    split, a share given twice, too few shares, or shares that do not give this box's KEK."""
    if meta.get("backend") != "shamir":
        raise KekError(f"this box's KEK is not split into shares (back end {meta.get('backend')})")
    return _combine_checked(str(meta["set_id"]), int(meta["threshold"]), str(meta["kek_id"]), texts)


def kek_from_escrow(meta: Mapping[str, Any], texts: list[str]) -> bytes:
    """D-894: the KEK of a TPM box (back end ``file``) from its escrow shares (``kek.json``'s ``escrow``), for a new
    board. Refused as :func:`kek_from_shares`, and when the box has no escrow set or its set is of an older KEK."""
    esc = meta.get("escrow")
    if meta.get("backend") != "file" or not isinstance(esc, Mapping):
        raise KekError(f"this box's KEK has no escrow shares (back end {meta.get('backend')}, no escrow set)")
    if esc.get("kek_id") != meta["kek_id"]:
        raise KekError(f"the escrow set {esc.get('set_id')} is of an older KEK ({esc.get('kek_id')}); "
                       f"kek.json names {meta['kek_id']}: its shares do not open this box")  # fmt: skip
    return _combine_checked(str(esc["set_id"]), int(esc["threshold"]), str(meta["kek_id"]), texts)


def _combine_checked(set_id: str, need: int, want_id: str, texts: list[str]) -> bytes:
    shares = [parse_share(t) for t in texts if t.strip()]
    seen: set[int] = set()
    for s in shares:
        if s.set_id != set_id:
            raise KekError(f"share {s.index} is of another set ({s.set_id}, this box's is {set_id})")
        if s.index in seen:
            raise KekError(f"share {s.index} was given twice: each steward gives their own share once")
        seen.add(s.index)
    if len(shares) < need:
        raise KekError(f"{len(shares)} share(s) given; {need} are needed")
    kek = combine_shares([(s.index, s.data) for s in shares])
    if not hmac.compare_digest(kek_id(kek), want_id):
        raise KekError("the shares do not give this box's KEK (a wrong or damaged share)")
    return kek


# ------------------------------------------------------------------------------------------------ the KEK at run time


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
    except ValueError:
        return False
    return True


def kek_file_problem(path: Path, secrets_dir: Path) -> str | None:
    """Why ``path`` may not hold the KEK, or None: inside the secrets folder, or readable by group or others."""
    if _inside(path, secrets_dir):
        return f"the KEK file {path} is inside the secrets folder {secrets_dir}: a KEK beside the keys protects nothing"
    try:
        mode = path.stat().st_mode & 0o077
    except OSError:
        return None
    if mode:
        return f"the KEK file {path} is readable by group or others (mode {oct(path.stat().st_mode & 0o777)})"
    return None


def kek_sources(secrets_dir: Path, env: Mapping[str, str]) -> list[Path]:
    """The KEK files a service looks at, in order."""
    out = [Path(env.get("TB_KEK_FILE") or DEFAULT_KEK_FILE)]
    if env.get("CREDENTIALS_DIRECTORY"):
        out.append(Path(env["CREDENTIALS_DIRECTORY"]) / CREDENTIAL)
    return out


def load_kek(secrets_dir: Path, env: Mapping[str, str] | None = None) -> bytes:
    """This box's KEK (see the module text), checked against ``kek.json``. Never made here."""
    env = os.environ if env is None else env
    meta = read_meta(secrets_dir)
    if meta is None:
        raise KekError(f"{secrets_dir} has wrapped keys but no {META_FILE}: the KEK cannot be checked")
    for src in kek_sources(secrets_dir, env):
        if not src.is_file():
            continue
        why = kek_file_problem(src, secrets_dir)
        if why:
            raise KekError(why)
        kek = src.read_bytes()
        if len(kek) != KEK_LEN or not hmac.compare_digest(kek_id(kek), str(meta["kek_id"])):
            raise KekError(f"{src} is not this box's KEK (kek.json names {meta['kek_id']})")
        return kek
    if meta["backend"] == "passphrase" and os.environ.get("TB_KEK_PASSPHRASE"):
        # H-97 (the review's L-2, 7102655419; H-94 (5)): a caller's environment may be in a log (sudo keeps it with
        # its value) or a container's configuration; the value is never printed
        raise KekError("TB_KEK_PASSPHRASE is set in the environment: refused. Unseal with `python -m tools.keys "
                       "unseal` (the passphrase typed, or --passphrase-file FILE, root only, or --passphrase-stdin); "
                       "treat the passphrase given in the environment as exposed and rotate it (RUNBOOK §23)")
    if meta["backend"] == "passphrase" and env.get("TB_KEK_PASSPHRASE"):  # a mapping tools.keys built
        kek = derive_from_passphrase(env["TB_KEK_PASSPHRASE"], meta)
        if not hmac.compare_digest(kek_id(kek), str(meta["kek_id"])):
            raise KekError("TB_KEK_PASSPHRASE is not this box's passphrase")
        return kek
    if meta["backend"] == "kms" and env.get("TB_KMS_TOKEN"):
        return kms_open(meta, env)
    raise KekLockedError(
        f"the site keys in {secrets_dir} are wrapped and the KEK is not unsealed here (back end {meta['backend']}): "
        f"run `python -m tools.keys unseal` on the host (it writes {DEFAULT_KEK_FILE}); no key is made in their place"
    )


# ------------------------------------------------------------------------------------------------ wrap and unwrap


def _aad(name: str, kid: str) -> bytes:
    return f"{WRAP_FORMAT}\x00{name}\x00{kid}".encode()


def wrap(kek: bytes, key: bytes, name: str) -> dict[str, Any]:
    """The wrapped document of ``key`` (file name ``name``) under ``kek``."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    kid = kek_id(kek)
    nonce = os.urandom(12)
    blob = nonce + AESGCM(kek).encrypt(nonce, key, _aad(name, kid))
    return {"format": WRAP_FORMAT, "name": name, "kek_id": kid, "fingerprint": fingerprint(key),
            "blob": base64.b64encode(blob).decode("ascii")}  # fmt: skip


def unwrap(kek: bytes, doc: Mapping[str, Any], name: str) -> bytes:
    """The key of a wrapped document; :class:`KekError` when it is another key's, another KEK's, or damaged."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if doc.get("format") != WRAP_FORMAT:
        raise KekError(f"{name}{WRAPPED_SUFFIX} is not a {WRAP_FORMAT} document")
    if doc.get("name") != name:
        raise KekError(f"{name}{WRAPPED_SUFFIX} holds the key {doc.get('name')!r}, not {name!r}")
    kid = kek_id(kek)
    if doc.get("kek_id") != kid:
        raise KekError(f"{name}{WRAPPED_SUFFIX} is wrapped under KEK {doc.get('kek_id')}, not {kid}")
    try:
        blob = base64.b64decode(str(doc["blob"]), validate=True)
        key = AESGCM(kek).decrypt(blob[:12], blob[12:], _aad(name, kid))
    except (KeyError, ValueError, InvalidTag):
        raise KekError(f"{name}{WRAPPED_SUFFIX} does not open under this KEK: damaged or changed") from None
    if fingerprint(key) != doc.get("fingerprint"):
        raise KekError(f"{name}{WRAPPED_SUFFIX}: the opened key is not the one its fingerprint names")
    return key


def read_wrapped(path: Path) -> dict[str, Any]:
    w = wrapped_path(path)
    try:
        doc = json.loads(w.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KekError(f"{w} cannot be read ({type(exc).__name__})") from None
    if not isinstance(doc, dict):
        raise KekError(f"{w} is not a {WRAP_FORMAT} document")
    return doc


def store_key(path: Path, key: bytes, kek: bytes | None) -> Path:
    """Write ``key`` for ``path``: wrapped under ``kek`` (``<path>.wrapped``), or plain when ``kek`` is None."""
    if kek is None:
        _write_private(path, key)
        return path
    w = wrapped_path(path)
    _write_private(w, (json.dumps(wrap(kek, key, path.name), indent=1, sort_keys=True) + "\n").encode())
    return w


def load_key_file(path: Path, env: Mapping[str, str] | None = None) -> bytes:
    """The key of ``path``: opened from ``<path>.wrapped`` under the KEK, or read plain. ``KeyMissingError``
    (``tb_common.crypto``) when neither exists or the plain file is empty; :class:`KekError` when both exist."""
    from tb_common.crypto import KeyMissingError

    w = wrapped_path(path)
    if w.exists():
        if path.exists():
            raise KekError(
                f"{path} is there in plain beside {w.name}: one of them may be the wrong key. Compare fingerprints "
                f"(`python -m tools.keys status`) and remove the plain copy"
            )
        return unwrap(load_kek(path.parent, env), read_wrapped(path), path.name)
    try:
        key = path.read_bytes()
    except FileNotFoundError:
        raise KeyMissingError(f"key file {path} is missing") from None
    if not key:
        raise KeyMissingError(f"key file {path} is empty")
    return key


def create_key_file(path: Path, size: int = 32, env: Mapping[str, str] | None = None) -> bool:
    """Make a key for ``path`` when it has none in either form: wrapped when the folder has a KEK (which must then be
    unsealed), else plain. Returns whether a key was made; a key is never replaced."""
    if key_present(path):
        return False
    kek = load_kek(path.parent, env) if read_meta(path.parent) is not None else None
    if kek is None:
        from tb_common.crypto import create_key

        return create_key(path, size)
    store_key(path, os.urandom(size), kek)
    return True


# ------------------------------------------------------------------------------------------------ custody report


@dataclass
class Custody:
    """What ``doctor`` and ``tools/keys.py`` know of a secrets folder, without opening a key."""

    secrets_dir: Path
    backend: str | None = None
    kek_id: str | None = None
    keys: dict[str, str] = field(default_factory=dict)  # name -> wrapped | plain | both | missing
    fingerprints: dict[str, str] = field(default_factory=dict)
    kek: str = "none"  # none (no kek.json) | ok | locked | refused
    kek_detail: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def plain(self) -> list[str]:
        return [n for n, s in self.keys.items() if s == "plain"]

    @property
    def wrapped(self) -> list[str]:
        return [n for n, s in self.keys.items() if s == "wrapped"]

    def as_dict(self) -> dict[str, Any]:
        return {"secrets_dir": str(self.secrets_dir), "backend": self.backend, "kek_id": self.kek_id,
                "kek": self.kek, "kek_detail": self.kek_detail, "keys": self.keys,
                "fingerprints": self.fingerprints, "problems": self.problems}  # fmt: skip


def custody(secrets_dir: Path, env: Mapping[str, str] | None = None) -> Custody:
    """The state of the protected keys of ``secrets_dir`` and of the KEK. ``problems`` lists what is wrong whatever
    the environment: a key both plain and wrapped, a wrapped key without ``kek.json`` or under another KEK, a KEK
    file beside the keys, a KEK that is not this box's."""
    env = os.environ if env is None else env
    c = Custody(secrets_dir)
    try:
        meta = read_meta(secrets_dir)
    except KekError as exc:
        c.problems.append(str(exc))
        meta = None
    if meta is not None:
        c.backend, c.kek_id = str(meta["backend"]), str(meta["kek_id"])
    for name in PROTECTED:
        p = secrets_dir / name
        plain, wrapped = p.exists(), wrapped_path(p).exists()
        if name in OPTIONAL and not plain and not wrapped:
            continue
        c.keys[name] = "both" if plain and wrapped else "wrapped" if wrapped else "plain" if plain else "missing"
        if plain and wrapped:
            c.problems.append(f"{name} is there in plain beside its wrapped form")
        if wrapped:
            try:
                doc = read_wrapped(p)
            except KekError as exc:
                c.problems.append(str(exc))
                continue
            c.fingerprints[name] = str(doc.get("fingerprint"))
            if doc.get("name") != name:
                c.problems.append(f"{name}{WRAPPED_SUFFIX} holds the key {doc.get('name')!r}")
            if meta is None:
                c.problems.append(f"{name} is wrapped but the folder has no {META_FILE}")
            elif doc.get("kek_id") != meta["kek_id"]:
                c.problems.append(f"{name} is wrapped under KEK {doc.get('kek_id')}, kek.json names {meta['kek_id']}")
        elif plain:
            with contextlib.suppress(OSError):
                c.fingerprints[name] = fingerprint(p.read_bytes())
    stray = sorted(f.name for f in secrets_dir.glob("*") if f.name.lower() in {"kek", "kek.bin", "kek.key", CREDENTIAL})
    if stray:
        c.problems.append(f"a KEK file is in the secrets folder ({', '.join(stray)}): a KEK beside the keys")
    if meta is not None:
        try:
            load_kek(secrets_dir, env)
            c.kek = "ok"
        except KekLockedError as exc:
            c.kek, c.kek_detail = "locked", str(exc)
        except KekError as exc:
            c.kek, c.kek_detail = "refused", str(exc)
            c.problems.append(str(exc))
    return c
