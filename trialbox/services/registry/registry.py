"""Model registry v0 (spec v4 §8.4, S1-07): alias -> pinned build, statuses, served-model echo.

``models/registry.yaml`` is the source of truth. :meth:`Registry.resolve` is the only way the gateway turns an alias
into a build it may call; it fails closed:

* an unknown alias, or an alias with no build in an eligible status, is refused;
* a build whose ``sha256`` is null is *not pinned* and is refused, except the stub build in DEV/TEST;
* ``retired`` and ``suspended`` builds are never routable; production roles resolve to ``champion``, shadow roles to
  ``shadow``, evaluation roles to ``qualified`` or better (MOD-7). DEV/TEST accept any other status.

:func:`check_served` is the served-model echo check: the name an upstream reports in its response must equal the
build's served name for that endpoint, or the call is refused (a stub serving the wrong model is detected).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from tb_common.policy.classes import Environment

REPO = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO / "models" / "registry.yaml"
CARDS_DIR = REPO / "models" / "cards"
_SHA = re.compile(r"^[0-9a-f]{64}$")
EVALUATION_ROLES = frozenset({"bakeoff", "optimise_prompt"})


class Status(StrEnum):
    CANDIDATE = "candidate"
    QUALIFIED = "qualified"
    SHADOW = "shadow"
    CHAMPION = "champion"
    RETIRED = "retired"
    SUSPENDED = "suspended"


class RegistryError(PermissionError):
    """Resolution refused; ``reason`` is a stable code for the audit record and the HTTP body."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Build:
    build_id: str
    alias: str
    status: Status
    serving: str  # stub | vllm | external
    served: dict[str, str | None]
    sha256: str | None
    revision: str | None
    quantisation: str | None
    licence: dict[str, Any]
    origin: dict[str, Any]
    family: str = ""
    model_name: str = ""
    repository: str | None = None
    context_length: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def pinned(self) -> bool:
        return self.sha256 is not None

    @property
    def model_sha(self) -> str:
        """Identity used in call records and cache keys; ``unpinned:<build_id>`` for the DEV/TEST stub."""
        return self.sha256 or f"unpinned:{self.build_id}"


@dataclass(frozen=True)
class Resolved:
    build: Build
    served_name: str
    endpoint: str


def _status_ok(status: Status, role: str, env: Environment) -> bool:
    if status in (Status.RETIRED, Status.SUSPENDED):
        return False
    if env in (Environment.DEV, Environment.TEST):
        return True
    if role.startswith("shadow:"):
        return status == Status.SHADOW
    if role in EVALUATION_ROLES:
        return status in (Status.QUALIFIED, Status.SHADOW, Status.CHAMPION)
    return status == Status.CHAMPION


class Registry:
    def __init__(self, doc: dict[str, Any]) -> None:
        self.version = str(doc.get("version") or "")
        if not self.version:
            raise ValueError("registry: missing version")
        self.aliases: dict[str, dict[str, Any]] = dict(doc.get("aliases") or {})
        self.builds: list[Build] = []
        seen: set[str] = set()
        for raw in doc.get("builds") or []:
            b = _build(raw)
            if b.build_id in seen:
                raise ValueError(f"registry: duplicate build_id {b.build_id}")
            if b.alias not in self.aliases:
                raise ValueError(f"registry: build {b.build_id} names unknown alias {b.alias}")
            if b.sha256 is not None and not _SHA.match(b.sha256):
                raise ValueError(f"registry: build {b.build_id} sha256 is not a lowercase hex SHA-256")
            seen.add(b.build_id)
            self.builds.append(b)

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> Registry:
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    def build(self, build_id: str) -> Build:
        for b in self.builds:
            if b.build_id == build_id:
                return b
        raise RegistryError("build_unknown", f"unknown build {build_id!r}")

    def resolve(self, alias: str, endpoint: str, *, role: str, env: Environment) -> Resolved:
        if alias not in self.aliases:
            raise RegistryError("alias_unknown", f"alias {alias!r} is not in the registry")
        reasons: list[str] = []
        for b in self.builds:
            if b.alias != alias:
                continue
            if not _status_ok(b.status, role, env):
                reasons.append(f"{b.build_id}: status {b.status.value}")
                continue
            if not b.pinned and not (b.serving == "stub" and env in (Environment.DEV, Environment.TEST)):
                reasons.append(f"{b.build_id}: sha256 not pinned")
                continue
            served = b.served.get(endpoint)
            if not served:
                reasons.append(f"{b.build_id}: not served on {endpoint}")
                continue
            return Resolved(b, served, endpoint)
        code = "build_unpinned" if any("not pinned" in r for r in reasons) else "no_eligible_build"
        raise RegistryError(code, f"alias {alias!r} on {endpoint}: no routable build ({'; '.join(reasons) or 'none'})")

    def table(self) -> list[dict[str, Any]]:
        """Alias -> builds view for the registry API and the control plane (no endpoint addresses)."""
        return [
            {
                "build_id": b.build_id,
                "alias": b.alias,
                "status": b.status.value,
                "sha256": b.sha256,
                "pinned": b.pinned,
                "revision": b.revision,
                "quantisation": b.quantisation,
                "licence": b.licence,
                "origin": b.origin,
                "model_name": b.model_name,
            }
            for b in self.builds
        ]


def _build(raw: dict[str, Any]) -> Build:
    known = {
        "build_id",
        "alias",
        "status",
        "serving",
        "served",
        "sha256",
        "revision",
        "quantisation",
        "licence",
        "origin",
        "family",
        "model_name",
        "repository",
        "context_length",
    }
    for key in ("build_id", "alias", "status", "serving", "licence", "origin"):
        if key not in raw:
            raise ValueError(f"registry: build {raw.get('build_id')!r} lacks {key}")
    return Build(
        build_id=str(raw["build_id"]),
        alias=str(raw["alias"]),
        status=Status(raw["status"]),
        serving=str(raw["serving"]),
        served={str(k): (str(v) if v else None) for k, v in (raw.get("served") or {}).items()},
        sha256=raw.get("sha256"),
        revision=raw.get("revision"),
        quantisation=raw.get("quantisation"),
        licence=dict(raw["licence"]),
        origin=dict(raw["origin"]),
        family=str(raw.get("family") or ""),
        model_name=str(raw.get("model_name") or ""),
        repository=raw.get("repository"),
        context_length=raw.get("context_length"),
        extra={k: v for k, v in raw.items() if k not in known},
    )


def check_served(resolved: Resolved, reported: object) -> None:
    """Served-model echo (S1-07, MOD-6): the upstream's reported ``model`` must be the build's served name."""
    if reported != resolved.served_name:
        raise RegistryError(
            "served_model_mismatch",
            f"endpoint {resolved.endpoint} served {reported!r}, registry expects {resolved.served_name!r} "
            f"for build {resolved.build.build_id}",
        )


def card_markdown(b: Build) -> str:
    """Model card v0 generated from the build record (§8.4; CHAI-style sections filled at qualification)."""
    lic = b.licence
    org = b.origin
    verified = "yes" if lic.get("verified") else "no"
    non_prc = "yes" if org.get("non_prc") else "no"
    pin = b.sha256 or "not yet pinned (null)"
    lines = [
        f"# Model card: {b.build_id}",
        "",
        "Generated from `models/registry.yaml` by `python -m registry.cards --write`. Do not edit by hand.",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Alias | `{b.alias}` |",
        f"| Model | {b.model_name or b.family or b.build_id} |",
        f"| Status | {b.status.value} |",
        f"| Serving | {b.serving} |",
        f"| Weights SHA-256 | {pin} |",
        f"| Revision | {b.revision or 'not yet pinned'} |",
        f"| Quantisation | {b.quantisation or 'to record at qualification'} |",
        f"| Context length | {b.context_length or 'to record at qualification'} |",
        f"| Licence | {lic.get('name')} (SPDX: {lic.get('spdx') or 'n/a'}; verified: {verified}) |",
        f"| Origin | {org.get('developer')} ({org.get('country')}); non-PRC: {non_prc} |",
        "",
        "## Contexts of use",
        "",
        "None approved. A build is used only through a route in `models/routing.yaml` after G5 (§8.16).",
        "",
        "## Evaluation",
        "",
        "No evaluation report is recorded. Per-language results (en, zh-TW, ja, mixed) come from the suites (§8.9).",
        "",
    ]
    return "\n".join(lines)
