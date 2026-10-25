"""``hermes.lock`` reader and pin check (spec v4 §9.5, HER-18, ENG-08; S1-11, S1-16).

:func:`pin_problems` lists every reason the lock does not describe a verified, digest-pinned release at or above the
floor for the given environment. An empty list is the only state in which ``trialbox doctor`` lets Hermes start.

Mirror rule (ENG-08): VALIDATION and PRODUCTION run only the internal mirror, whose digest must equal the upstream
digest. DEV and TEST may run the upstream image by digest while ``mirror_image`` holds the documented placeholder
:data:`MIRROR_PENDING`; :func:`pin_notes` reports that so doctor can WARN. Any other non-digest mirror value, or a
mismatching mirror digest, is a problem in every environment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

LOCK_PATH = Path(__file__).resolve().parent / "hermes.lock"
FLOOR = (0, 21, 6)
MIRROR_PENDING = "PENDING-INTERNAL-MIRROR"
UPSTREAM_OK_ENVS = frozenset({"DEV", "TEST"})
_SEMVER = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class HermesLock:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path = LOCK_PATH) -> HermesLock:
        if not path.exists():
            return cls({})
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(doc, dict):
            return cls({})
        return cls(doc)

    def get(self, key: str) -> str:
        v = self.raw.get(key)
        return "" if v is None else str(v)

    @property
    def mirror_pending(self) -> bool:
        return self.get("mirror_image") == MIRROR_PENDING and self.get("mirror_digest") == MIRROR_PENDING


def _version(v: str) -> tuple[int, int, int] | None:
    m = _SEMVER.match(v)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _ref_problems(lock: HermesLock, key: str, digest_key: str) -> list[str]:
    p: list[str] = []
    if not _DIGEST.match(lock.get(digest_key)):
        p.append(f"{digest_key} is not a sha256 digest")
    ref = lock.get(key)
    if not ref or "@sha256:" not in ref:
        p.append(f"{key} is not pinned by digest (a mutable tag is never allowed, ENG-08)")
    elif lock.get(digest_key) and not ref.endswith("@" + lock.get(digest_key)):
        p.append(f"{key} digest differs from {digest_key}")
    return p


def expected_digest(lock: HermesLock, environment: str = "DEV") -> str:
    """The digest the running Hermes image must have in ``environment`` (mirror if set, else upstream in DEV/TEST)."""
    if lock.mirror_pending and environment in UPSTREAM_OK_ENVS:
        return lock.get("upstream_digest")
    return lock.get("mirror_digest")


def run_image(lock: HermesLock, environment: str = "DEV") -> str:
    """The image reference to run in ``environment`` (always by digest)."""
    if lock.mirror_pending and environment in UPSTREAM_OK_ENVS:
        return lock.get("upstream_image")
    return lock.get("mirror_image")


def pin_problems(lock: HermesLock, *, running_digest: str | None = None, environment: str = "DEV") -> list[str]:
    """Every reason Hermes must not start on this lock in ``environment`` (fail closed: missing field = problem)."""
    p: list[str] = []
    if not lock.raw:
        return ["hermes.lock missing or empty"]
    ver = _version(lock.get("version"))
    if ver is None:
        p.append(f"version {lock.get('version')!r} is not a vX.Y.Z release tag")
    elif ver < FLOOR:
        p.append(f"version {lock.get('version')} is below the floor v{'.'.join(map(str, FLOOR))}")
    if lock.get("tag") != lock.get("version"):
        p.append("tag does not match version")
    if not _SHA1.match(lock.get("commit_sha")):
        p.append("commit_sha is not a verified 40-hex commit")
    p += _ref_problems(lock, "upstream_image", "upstream_digest")
    if lock.mirror_pending:
        if environment not in UPSTREAM_OK_ENVS:
            p.append(f"internal mirror pending: {environment} runs only the mirrored digest (ENG-08)")
    else:
        p += _ref_problems(lock, "mirror_image", "mirror_digest")
        if lock.get("upstream_digest") and lock.get("upstream_digest") != lock.get("mirror_digest"):
            p.append("mirror_digest differs from upstream_digest")
    if lock.raw.get("verified") is not True:
        p.append("release not verified")
    if running_digest is not None and running_digest != expected_digest(lock, environment):
        p.append("running image digest differs from hermes.lock")
    return p


def pin_notes(lock: HermesLock, environment: str = "DEV") -> list[str]:
    """Non-blocking remarks for a lock without problems (doctor WARNs on them)."""
    if lock.mirror_pending and environment in UPSTREAM_OK_ENVS:
        return [f"{environment} runs the upstream digest; push the internal mirror before VALIDATION/PRODUCTION"]
    return []
