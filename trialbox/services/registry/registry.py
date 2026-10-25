"""Model registry v0 (spec v4 §8.4, S1-07): alias -> pinned build, statuses, served-model echo.

``models/registry.yaml`` is the source of truth. :meth:`Registry.resolve` is the only way the gateway turns an alias
into a build it may call; it fails closed:

* an unknown alias, or an alias with no build in an eligible status, is refused;
* a build whose ``sha256`` is null is *not pinned* and is refused, except the stub build in DEV/TEST;
* ``retired`` and ``suspended`` builds are never routable; production roles resolve to ``champion``, shadow roles to
  ``shadow``, evaluation roles to ``qualified`` or better (MOD-7). DEV/TEST accept any other status.

A site pins its own builds in a **site override** (``TB_REGISTRY_OVERRIDE``, written by ``tools/pin_model.py``), never
in the committed file: :func:`apply_override` may only set the pin fields of builds that already exist (``sha256``,
``served``, ``revision``, ``status``, ``quantisation``, ``context_length``, ``weights``, ``provider_pin``). It cannot
add aliases or builds, and an override that names an unknown build or field is refused (fail closed). The merged
registry's version is ``<committed version>+site.<12 hex of the override>``, so every call record shows which pins
were in force.

:func:`check_served` is the served-model echo check: the name an upstream reports in its response must equal the
build's served name for that endpoint, or the call is refused (a stub serving the wrong model is detected).

**Hosted builds** (``serving: hosted``, a model served by a third party such as OpenRouter) have no weights to hash.
They are pinned by a **provider pin** (S1-14): a descriptor of one dated provider version — endpoint, model id, the
provider's dated canonical slug and creation time, the serving provider (display name and endpoint tag) and its
quantisation, the pin date — and the build's ``sha256`` is :func:`provider_pin_sha` of that descriptor. The registry
refuses a hosted build whose sha256 does not match its descriptor, a hosted build pinned without one, and a descriptor
on a non-hosted build. At call time the gateway asks the endpoint for exactly that provider (no fallback) and
:func:`check_served` requires the response to report the pinned model id *and* the pinned provider.
``tools/pin_provider.py`` writes these pins and re-checks that the provider has not moved the model id to a new dated
version (``--verify``).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from collections.abc import Mapping
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
OVERRIDE_ENV = "TB_REGISTRY_OVERRIDE"
OVERRIDE_KIND = "registry-site-override"
OVERRIDE_FIELDS = frozenset(
    {"sha256", "served", "revision", "status", "quantisation", "context_length", "weights", "provider_pin"}
)
HOSTED = "hosted"
PROVIDER_PIN_FIELDS = (
    "endpoint",
    "model",
    "canonical_slug",
    "created",
    "provider",
    "provider_tag",
    "quantization",
    "pinned_at",
)


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
    serving: str  # stub | vllm | hosted
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
    weights: dict[str, Any] = field(default_factory=dict)  # site pin provenance (tools/pin_model.py)
    provider_pin: dict[str, Any] | None = None  # hosted builds: dated provider version (tools/pin_provider.py)
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
            _check_provider_pin(b)
            seen.add(b.build_id)
            self.builds.append(b)

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH, override: Path | None = None) -> Registry:
        """The committed registry, with the site override applied when ``override`` names an existing file."""
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if override is not None and override.is_file():
            doc = apply_override(doc, yaml.safe_load(override.read_text(encoding="utf-8")) or {})
        return cls(doc)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Registry:
        """``TB_REGISTRY_PATH`` (default: the committed file) plus ``TB_REGISTRY_OVERRIDE`` (site pins, optional).
        A missing override file means no site pins: every non-stub build stays unpinned and unroutable."""
        e = os.environ if env is None else env
        override = e.get(OVERRIDE_ENV)
        return cls.load(Path(e.get("TB_REGISTRY_PATH") or DEFAULT_PATH), Path(override) if override else None)

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
                "provider_pin": b.provider_pin,
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
        "weights",
        "provider_pin",
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
        weights=dict(raw.get("weights") or {}),
        provider_pin=dict(raw["provider_pin"]) if raw.get("provider_pin") else None,
        extra={k: v for k, v in raw.items() if k not in known},
    )


def provider_pin_sha(pin: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical provider descriptor (the :data:`PROVIDER_PIN_FIELDS`, sorted-key compact JSON).
    Raises :class:`ValueError` when a field is missing or empty, or an unknown field is present."""
    missing = [k for k in PROVIDER_PIN_FIELDS if pin.get(k) in (None, "")]
    extra = sorted(set(pin) - set(PROVIDER_PIN_FIELDS))
    if missing or extra:
        raise ValueError(f"provider pin: missing fields {missing}, unknown fields {extra}")
    if not isinstance(pin["created"], int) or isinstance(pin["created"], bool):
        raise ValueError("provider pin: created must be an integer (Unix seconds)")
    canon = {k: pin[k] if k == "created" else str(pin[k]) for k in PROVIDER_PIN_FIELDS}
    return hashlib.sha256(json.dumps(canon, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _check_provider_pin(b: Build) -> None:
    """Hosted builds are pinned only by a provider descriptor whose digest is the sha256; others never carry one."""
    where = f"registry: build {b.build_id}"
    if b.provider_pin is None:
        if b.serving == HOSTED and b.sha256 is not None:
            raise ValueError(f"{where} is hosted: it is pinned by a provider_pin descriptor, not a bare sha256")
        return
    if b.serving != HOSTED:
        raise ValueError(f"{where}: provider_pin is only for serving: {HOSTED} builds")
    if b.sha256 != provider_pin_sha(b.provider_pin):
        raise ValueError(f"{where}: sha256 is not the digest of its provider_pin descriptor")
    ep, model = str(b.provider_pin["endpoint"]), str(b.provider_pin["model"])
    if b.served.get(ep) != model:
        raise ValueError(f"{where}: served[{ep}] must be the pinned model id {model!r}")
    if any(name for e, name in b.served.items() if e != ep and name):
        raise ValueError(f"{where}: a provider pin covers its own endpoint only ({ep})")


def apply_override(doc: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """The committed registry document with a site override's pins applied (a new document; inputs unchanged).

    Raises :class:`ValueError` for an override of another kind, an unknown build, a field outside
    :data:`OVERRIDE_FIELDS`, a malformed sha256 or an unknown status."""
    if override.get("kind") != OVERRIDE_KIND:
        raise ValueError(f"registry override: kind must be {OVERRIDE_KIND!r}")
    pins = override.get("builds") or {}
    if not isinstance(pins, dict):
        raise ValueError("registry override: builds must be a mapping build_id -> fields")
    out = copy.deepcopy(doc)
    by_id = {str(b.get("build_id")): b for b in out.get("builds") or []}
    for build_id, fields in pins.items():
        if build_id not in by_id:
            raise ValueError(f"registry override: unknown build {build_id!r} (an override cannot add builds)")
        if not isinstance(fields, dict):
            raise ValueError(f"registry override: {build_id} must map to fields")
        extra = set(fields) - OVERRIDE_FIELDS
        if extra:
            raise ValueError(f"registry override: {build_id} sets fields an override may not set: {sorted(extra)}")
        sha = fields.get("sha256")
        if sha is not None and not (isinstance(sha, str) and _SHA.match(sha)):
            raise ValueError(f"registry override: {build_id} sha256 is not a lowercase hex SHA-256")
        if "status" in fields:
            Status(fields["status"])  # ValueError on an unknown status
        target = by_id[build_id]
        for key, value in fields.items():
            if key == "served":
                if not isinstance(value, dict):
                    raise ValueError(f"registry override: {build_id} served must be a mapping endpoint -> name")
                target["served"] = {**(target.get("served") or {}), **value}
            else:
                target[key] = copy.deepcopy(value)
    digest = hashlib.sha256(json.dumps(override, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    out["version"] = f"{doc.get('version')}+site.{digest[:12]}"
    return out


def check_served(resolved: Resolved, reported: object, provider: object = None) -> None:
    """Served-model echo (S1-07, MOD-6): the upstream's reported ``model`` must be the build's served name; for a
    provider-pinned hosted build the reported ``provider`` must also be the pinned provider (S1-14)."""
    if reported != resolved.served_name:
        raise RegistryError(
            "served_model_mismatch",
            f"endpoint {resolved.endpoint} served {reported!r}, registry expects {resolved.served_name!r} "
            f"for build {resolved.build.build_id}",
        )
    pin = resolved.build.provider_pin
    if pin is not None and provider != pin["provider"]:
        raise RegistryError(
            "served_provider_mismatch",
            f"endpoint {resolved.endpoint} served {reported!r} from provider {provider!r}, the pin requires "
            f"{pin['provider']!r} for build {resolved.build.build_id}",
        )


def provider_routing(pin: Mapping[str, Any]) -> dict[str, Any]:
    """The OpenRouter-style ``provider`` request object that holds a call to the pinned provider: that provider only,
    no fallback to another, only if it honours every request parameter (structured output, seed), and only if it does
    not collect prompts (the endpoint's ``training_use: none`` condition in the routing table)."""
    out: dict[str, Any] = {
        "order": [str(pin["provider_tag"])],
        "allow_fallbacks": False,
        "require_parameters": True,
        "data_collection": "deny",
    }
    q = str(pin.get("quantization") or "")
    if q and q != "unknown":
        out["quantizations"] = [q]
    return out


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
        f"| {'Provider pin' if b.serving == HOSTED else 'Weights'} SHA-256 | {pin} |",
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
