"""restic's repository password, a box key (PERF-010 R2, D-968).

The incremental backup's repository is encrypted by restic under a password. That password is ``restic.key`` of the
secrets folder, a protected key like the others (``tb_common.kek.PROTECTED``):

* made only under the KEK (``python -m tools.keys restic-key``): a box without a KEK gets no restic key, and so no
  incremental backup, rather than a key in the clear; a plain ``restic.key`` is refused;
* opened only into restic's own process environment (:func:`restic_env`), never written to a file, never printed;
* listed in the key inventory and the custody report, so the key ceremony's record names its fingerprint;
* copied, in its wrapped form only (ciphertext under the KEK) with the KEK's description, beside each repository on
  the target (:func:`escrow_copy`). The escrow shares cover the KEK (D-894), so the custodians open a dead box's
  repository from the target alone (:func:`open_from_target`); the target alone opens nothing.

The password is the key's 32 bytes as hex, so restic is given text it cannot misread.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from tb_common import kek as K

KEY = "restic.key"
#: the files written beside a repository on a target: the wrapped key and the KEK's description (no secret in either)
ESCROW_KEY = "trialbox-restic.key.wrapped"
ESCROW_META = "trialbox-restic.kek.json"
#: settings that would let something outside choose restic's password or repository: never passed on
RESTIC_FROM_OUTSIDE = ("RESTIC_PASSWORD", "RESTIC_PASSWORD_FILE", "RESTIC_PASSWORD_COMMAND", "RESTIC_REPOSITORY",
                       "RESTIC_REPOSITORY_FILE", "RESTIC_KEY_HINT")  # fmt: skip


class ResticKeyError(K.KekError):
    """The restic key cannot be made, opened or copied as the rule asks."""


def make_key(secrets_dir: Path, env: Mapping[str, str]) -> bool:
    """Make ``restic.key`` wrapped under the box's KEK, unless it is there; whether one was made. Refused without a
    KEK: the key is never made in the clear."""
    if K.read_meta(secrets_dir) is None:
        raise ResticKeyError(
            f"{secrets_dir} has no KEK ({K.META_FILE}): restic's key is made only under the KEK "
            "(python -m tools.keys init first); this box keeps the single encrypted backup"
        )
    if (secrets_dir / KEY).exists():
        raise ResticKeyError(f"{secrets_dir / KEY} is there in plain: wrap it (python -m tools.keys wrap) or remove it")
    return K.create_key_file(secrets_dir / KEY, 32, env)


def password(secrets_dir: Path, env: Mapping[str, str]) -> str:
    """The repository password, opened under the unsealed KEK. A plain ``restic.key`` is refused."""
    if (secrets_dir / KEY).exists():
        raise ResticKeyError(f"{secrets_dir / KEY} is plain: restic's key is kept only wrapped under the KEK")
    if not K.wrapped_path(secrets_dir / KEY).exists():
        raise ResticKeyError(f"no {KEY} in {secrets_dir} (python -m tools.keys restic-key)")
    return K.load_key_file(secrets_dir / KEY, env).hex()


def restic_env(pw: str, base: Mapping[str, str]) -> dict[str, str]:
    """The environment of one restic process: ``base`` without any restic password or repository setting, and the
    password. The caller passes it to that process only."""
    env = {k: v for k, v in base.items() if k not in RESTIC_FROM_OUTSIDE}
    env["RESTIC_PASSWORD"] = pw
    return env


def _write(path: Path, data: bytes) -> None:
    part = path.with_name(path.name + ".part")
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(part, path)


def escrow_copy(secrets_dir: Path, target: Path) -> list[Path]:
    """Write the wrapped key and the KEK's description beside the repository in ``target``. The same key re-wrapped
    (after ``rotate-kek``) replaces the copy; another key is refused, since the repository's snapshots open only
    with the key they were made under."""
    wrapped = K.read_wrapped(secrets_dir / KEY)
    meta = K.read_meta(secrets_dir)
    if meta is None:
        raise ResticKeyError(f"{secrets_dir} has no KEK ({K.META_FILE})")
    there = target / ESCROW_KEY
    if there.exists():
        try:
            old = json.loads(there.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = {}
        if old.get("fingerprint") != wrapped.get("fingerprint"):
            raise ResticKeyError(
                f"{there} holds another restic key (fingerprint {old.get('fingerprint')}, the box has "
                f"{wrapped.get('fingerprint')}): its repository's snapshots would no longer open; nothing was replaced"
            )
    out = []
    for name, doc in ((ESCROW_KEY, wrapped), (ESCROW_META, meta)):
        _write(target / name, (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode())
        out.append(target / name)
    return out


def open_from_target(target: Path, kek: bytes) -> str:
    """The repository password from the copy beside the repository, under a KEK the custodians rebuilt from their
    escrow shares (D-894). Refused under any other KEK."""
    meta = json.loads((target / ESCROW_META).read_text(encoding="utf-8"))
    if K.kek_id(kek) != meta.get("kek_id"):
        raise ResticKeyError(f"this KEK is not the one {ESCROW_KEY} was wrapped under ({meta.get('kek_id')})")
    doc = json.loads((target / ESCROW_KEY).read_text(encoding="utf-8"))
    return K.unwrap(kek, doc, KEY).hex()
