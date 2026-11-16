"""restic's repository password, a box key (PERF-010 R2, D-968).

The incremental backup's repository is encrypted by restic under a password. That password is ``restic.key`` of the
secrets folder, a protected key like the others (``tb_common.kek.PROTECTED``):

* made only under the KEK (``python -m tools.keys restic-key``), written wrapped and never in the clear: a box
  without a KEK gets no restic key, and so no incremental backup; a plain ``restic.key`` is refused;
* opened only into restic's own process environment (:func:`restic_env`, which drops every ``RESTIC_*`` setting from
  outside), never written to a file, never printed;
* listed in the key inventory and the custody report, so the key ceremony's record names its fingerprint;
* copied beside each repository on the target (:func:`escrow_copy`), in one file: the wrapped key (ciphertext under
  the KEK) and what the custodians need to rebuild that KEK from their shares (back end, KEK id, share set id and
  threshold; no salt, no names). The copy is written only when shares cover the KEK: a ``shamir`` KEK (the stewards'
  shares), or a TPM KEK (``file``) whose escrow set (D-894) is of the current KEK. Any other KEK, and a TPM KEK after
  ``rotate-kek`` until ``escrow-shares`` is run again, is refused, and an earlier copy stays as it was. The custodians
  open a dead box's repository from the target and their shares (:func:`open_from_target`); the target alone opens
  nothing.

The password is the key's 32 bytes as hex, so restic is given text it cannot misread.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tb_common import kek as K

KEY = "restic.key"
#: the one file written beside a repository on a target: the wrapped key and the KEK's public description
ESCROW = "trialbox-restic.key.json"
ESCROW_FORMAT = "tb-restic-escrow/1"


class ResticKeyError(K.KekError):
    """The restic key cannot be made, opened or copied as the rule asks."""


def make_key(secrets_dir: Path, env: Mapping[str, str]) -> bool:
    """Make ``restic.key`` wrapped under the box's KEK, unless it is there; whether one was made. Refused without a
    KEK or with the KEK locked: the key is only ever written wrapped."""
    path = secrets_dir / KEY
    if path.exists() or path.is_symlink():
        raise ResticKeyError(f"{path} is there in plain: wrap it (python -m tools.keys wrap) or remove it")
    if K.wrapped_path(path).exists():
        return False
    if K.read_meta(secrets_dir) is None:
        raise ResticKeyError(
            f"{secrets_dir} has no KEK ({K.META_FILE}): restic's key is made only under the KEK "
            "(python -m tools.keys init first); this box keeps the single encrypted backup"
        )
    K.store_key(path, os.urandom(32), K.load_kek(secrets_dir, env))  # never the plain branch of create_key_file
    return True


def password(secrets_dir: Path, env: Mapping[str, str]) -> str:
    """The repository password, opened under the unsealed KEK. A plain ``restic.key`` is refused."""
    if (secrets_dir / KEY).exists():
        raise ResticKeyError(f"{secrets_dir / KEY} is plain: restic's key is kept only wrapped under the KEK")
    if not K.wrapped_path(secrets_dir / KEY).exists():
        raise ResticKeyError(f"no {KEY} in {secrets_dir} (python -m tools.keys restic-key)")
    return K.load_key_file(secrets_dir / KEY, env).hex()


def restic_env(pw: str, base: Mapping[str, str]) -> dict[str, str]:
    """The environment of one restic process: ``base`` without any ``RESTIC_*`` setting (a password, a repository,
    the ``copy`` source's), and the password. The caller passes it to that process only."""
    env = {k: v for k, v in base.items() if not k.startswith("RESTIC_")}
    env["RESTIC_PASSWORD"] = pw
    return env


def public_kek(meta: Mapping[str, Any]) -> dict[str, Any]:
    """What the custodians need to rebuild the KEK from their shares, and nothing more; refused when no current share
    set covers the KEK."""
    backend, kid = meta.get("backend"), meta.get("kek_id")
    if backend == "shamir":
        return {"backend": backend, "kek_id": kid, "set_id": meta["set_id"], "threshold": meta["threshold"]}
    esc = meta.get("escrow")
    if backend == "file" and isinstance(esc, Mapping):
        if esc.get("kek_id") != kid:
            raise ResticKeyError(
                f"the escrow set {esc.get('set_id')} is of an older KEK ({esc.get('kek_id')}, the box's is {kid}): "
                "run `python -m tools.keys escrow-shares` with the custodians first; the copy on the target is kept"
            )
        share_set = {"set_id": esc["set_id"], "threshold": esc["threshold"], "kek_id": esc["kek_id"]}
        return {"backend": backend, "kek_id": kid, "escrow": share_set}
    raise ResticKeyError(
        f"the KEK (back end {backend}) is not covered by escrow shares: restic's key is copied to a target only for a "
        "shamir KEK or a TPM KEK with current escrow-shares (D-894)"
    )


def _read_target(path: Path) -> dict[str, Any] | None:
    if path.is_symlink() or (path.exists() and not stat.S_ISREG(path.lstat().st_mode)):
        raise ResticKeyError(f"{path} is not a plain file (a link or a folder): nothing was read or written")
    if not path.exists():
        return None
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as fh:
        try:
            doc = json.loads(fh.read())
        except ValueError:
            return {}
    return doc if isinstance(doc, dict) else {}


def _write_target(path: Path, data: bytes) -> None:
    """``data`` to ``path`` at 0600 through a new temporary file (``O_EXCL``, never through a link) and a rename."""
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def escrow_copy(secrets_dir: Path, target: Path) -> Path:
    """Write the escrow file beside the repository in ``target``. The same key re-wrapped (after ``rotate-kek`` and
    new escrow shares) replaces it; another key is refused, since the repository's snapshots open only with the key
    they were made under."""
    meta = K.read_meta(secrets_dir)
    if meta is None:
        raise ResticKeyError(f"{secrets_dir} has no KEK ({K.META_FILE})")
    kek_public = public_kek(meta)
    wrapped = K.read_wrapped(secrets_dir / KEY)
    there = target / ESCROW
    old = _read_target(there)
    if old is not None and (old.get("wrapped") or {}).get("fingerprint") != wrapped.get("fingerprint"):
        raise ResticKeyError(
            f"{there} holds another restic key (fingerprint {(old.get('wrapped') or {}).get('fingerprint')}, the box "
            f"has {wrapped.get('fingerprint')}): its repository's snapshots would no longer open; nothing was replaced"
        )
    doc = {"format": ESCROW_FORMAT, "kek": kek_public, "wrapped": wrapped}
    _write_target(there, (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode())
    return there


def open_from_target(target: Path, share_texts: list[str]) -> str:
    """The repository password from the escrow file beside the repository and the custodians' shares: the stewards'
    shares of a shamir KEK, or the escrow shares of a TPM KEK (D-894). Refused for shares of another set or KEK."""
    doc = _read_target(target / ESCROW)
    if not doc or doc.get("format") != ESCROW_FORMAT:
        raise ResticKeyError(f"{target / ESCROW} is not a restic escrow file")
    kek_meta = doc["kek"]
    kek = (K.kek_from_shares if kek_meta.get("backend") == "shamir" else K.kek_from_escrow)(kek_meta, share_texts)
    wrapped = doc["wrapped"]
    if not hmac.compare_digest(str(wrapped.get("kek_id")), K.kek_id(kek)):
        raise ResticKeyError("the wrapped key on the target is not under the KEK the shares give")
    return K.unwrap(kek, wrapped, KEY).hex()
