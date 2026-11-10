"""``trialbox doctor --platform``: the install checks on a hospital platform (WS-14.8, WS-11.8, WS-13.9; D-211).

The same signed images run on a platform TrialBox does not own (CGMH's shared B200, an interim private cloud) from
the Kubernetes manifests of ``deploy/platform`` or the compose variant ``deploy/platform/docker-compose.platform.yml``.
There is no ``install.sh`` there, so the install checks run as a job in the namespace and write the IQ evidence
(``iq-evidence.json``) the IQ protocol (TST-IQ-03) attaches. Each check is PASS, WARN, FAIL or SKIP (``--no-gpu``
makes the GPU checks ``skipped: no device``; it is refused in VALIDATION and PRODUCTION, where a GPU check can never be
skipped); any FAIL makes the command exit 1, and a check that raises is a FAIL.

What the checks read is a list of Kubernetes objects (``PlatformState``): from the API server inside the namespace
(the doctor Job's service account, read-only), from rendered manifests (``--manifests``: ``kustomize build`` output,
before anything is applied) or from ``docker compose config --format json`` (``--compose-config``). Checks:

* ``image_digests``: every container image is pinned by digest and the digest is ``release.json``'s; a ``latest``
  tag or an image that is not in the release is refused; a tag without a digest is a FAIL in VALIDATION and
  PRODUCTION (an unreleased build) and a WARN elsewhere; a running container whose image id differs is a FAIL;
* ``quota``: the namespace's ResourceQuotas cover the profile's minimum: ``requests.*`` (and the bare names) against
  the sum of the workloads' requests, ``limits.*`` against the sum of their limits, the lowest figure where several
  quotas bound one resource; a quota that bounds a limit fails when a container has no such limit (the pod would be
  refused); GPU devices are one resource whatever the MIG name; the GPU part is skipped with ``--no-gpu``;
* ``storage_encryption``: evidenced by the platform, not tested (PR-19): ``TB_PLATFORM_STORAGE_ENCRYPTED=yes`` with
  ``TB_PLATFORM_STORAGE_EVIDENCE`` (the storage class specification's reference); every claim uses
  ``TB_PLATFORM_STORAGE_CLASS``, which VALIDATION and PRODUCTION require;
* ``network_policy``: the default deny exists and denies everything, ``trialbox-model-isolation`` is the shipped one,
  no rule of any policy is open (an ingress rule without ``from``, an egress rule without ``to``, an ipBlock of
  ``0.0.0.0/0`` or ``::/0``), the egress allowlist policies name exactly the hosts ``deploy/egress.py`` allows and
  carry exactly the ipBlocks ``platform-egress`` renders for them now, and the doctor's own egress policy, when
  present, is exactly the rendered one (``render_doctor_policy``);
* ``kek_custody``: no Secret holds the key-encryption key or a key it protects (``pid_map.key``,
  ``site_hmac.key``): WS-13.11 (T-210 adds the unseal);
* ``ntp``: an SNTP query to ``TB_NTP_SERVER`` answers and the offset is under ``TB_NTP_MAX_OFFSET_S`` (default 1 s);
* ``directory``: the hospital directory (``TB_DIRECTORY_URL``: ``ldap(s)://`` or an ``https://`` OIDC issuer)
  accepts a TCP connection; none configured is a WARN (local accounts);
* ``mail_relay``: ``SMTP_HOST:SMTP_PORT`` accepts a TCP connection;
* ``backup_target``: ``TB_BACKUP_TARGETS`` is set and off-box (a network share, or the platform's declaration
  ``TB_PLATFORM_BACKUP_EVIDENCE``); a FAIL in PRODUCTION, a WARN elsewhere (D-187's rule);
* ``serving_record``: the ``shared-quota`` serving record (``TB_SERVING_RECORD``) exists, validates and names the
  MIG profile the namespace was given (``TB_MIG_PROFILE``). The profile is measured, never assumed: until T-114's
  record exists this is a FAIL that says so;
* ``gpu_serving``: exactly one judge and one verifier workload (``trialbox.io/role``), each with exactly one GPU
  device, no other workload with a GPU, a GPU quota of at least two; in a cluster their pods are ready;
* ``canary``: the last canary result (``TB_CANARY_RESULT``, ``tools/canary.py --out``) passed.
  The three GPU checks are skipped with ``--no-gpu`` (outside VALIDATION and PRODUCTION only).

``release.json`` is provisional here (``deploy/platform/release.json``, schema ``tb-release-images/0-provisional``)
until T-110 lands the real one; only its ``images`` map is read.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import ssl
import struct
import time
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from tools.trialbox.doctor import ROOT, Check, Status, _egress

RELEASE = ROOT / "deploy" / "platform" / "release.json"
COMPONENT = ROOT / "deploy" / "platform" / "components" / "release-images" / "kustomization.yaml"
NO_DEVICE = "skipped: no device"
EVIDENCE_SCHEMA = "tb-iq-evidence/1"
# a data key, name or annotation that marks a Secret as holding the KEK or a key it wraps (WS-13.11)
KEK_KEYS = re.compile(r"(^|[^a-z])(kek|pid_?map\.key|site_hmac\.key|key[-_]?encryption[-_]?key)([^a-z]|$)", re.I)
GPU_RESOURCE = re.compile(r"^(nvidia\.com/gpu|nvidia\.com/mig-[0-9a-z.+-]+)$")
REQUIRED_POLICIES = ("trialbox-default-deny", "trialbox-model-isolation")
WORKLOADS = ("Deployment", "StatefulSet", "Job", "Pod", "DaemonSet", "CronJob")


class PlatformError(Exception):
    """A release file or manifest that cannot be used at all (refused before any check)."""


# ------------------------------------------------------------------------------------------------ release.json
@dataclass(frozen=True)
class ReleaseImage:
    name: str
    image: str  # repository:tag
    digest: str | None

    @property
    def repository(self) -> str:
        return split_ref(self.image)[0]

    @property
    def tag(self) -> str | None:
        return split_ref(self.image)[1]


@dataclass(frozen=True)
class Release:
    release_id: str
    images: dict[str, ReleaseImage]
    sha256: str = ""

    def by_repository(self, repo: str) -> ReleaseImage | None:
        for img in self.images.values():
            if _norm(img.repository) == _norm(repo):
                return img
        return None


def _norm(repo: str) -> str:
    """``docker.io/library/postgres`` and ``postgres`` are one repository (the kubelet reports the long form)."""
    for prefix in ("docker.io/", "index.docker.io/", "library/"):
        repo = repo.removeprefix(prefix)
    return repo


def load_release(path: Path = RELEASE) -> Release:
    raw = path.read_bytes()
    doc = json.loads(raw)
    images: dict[str, ReleaseImage] = {}
    for name, ent in sorted((doc.get("images") or {}).items()):
        image, digest = str(ent.get("image") or ""), ent.get("digest")
        repo, tag, dig = split_ref(image)
        if not repo or dig:
            raise PlatformError(f"release image {name}: {image!r} must be repository:tag (the digest goes apart)")
        if tag in (None, "latest"):
            raise PlatformError(f"release image {name}: {image!r} has no tag or the tag latest; pin a version")
        if digest is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", str(digest)):
            raise PlatformError(f"release image {name}: digest {digest!r} is not sha256:<64 hex>")
        images[name] = ReleaseImage(name, image, digest)
    if not images:
        raise PlatformError(f"{path}: no images")
    return Release(str(doc.get("release_id") or "?"), images, hashlib.sha256(raw).hexdigest())


def split_ref(ref: str) -> tuple[str, str | None, str | None]:
    """``repo[:tag][@digest]`` -> (repo, tag, digest); a registry port is not a tag."""
    ref = ref.strip()
    digest = None
    if "@" in ref:
        ref, digest = ref.split("@", 1)
    last = ref.rsplit("/", 1)[-1]
    if ":" in last:
        repo, tag = ref.rsplit(":", 1)
        return repo, tag, digest
    return ref, None, digest


def component_yaml(rel: Release) -> str:
    """The kustomize Component that pins every image of the platform manifests to the release (acceptance 5).
    Generated: ``python -m tools.trialbox platform-images --write``; a test checks it equals ``release.json``."""
    lines = [
        "# GENERATED from deploy/platform/release.json by `python -m tools.trialbox platform-images` (D-211).",
        "# Do not edit: change release.json (T-110's release identity once it lands) and regenerate.",
        f"# release_id: {rel.release_id}",
        "apiVersion: kustomize.config.k8s.io/v1alpha1",
        "kind: Component",
        "images:",
    ]
    for name, img in sorted(rel.images.items()):
        lines += [f"  - name: {name}", f"    newName: {img.repository}"]
        if img.digest:
            lines.append(f"    digest: {img.digest}")
        else:
            lines.append(
                f'    newTag: "{img.tag}"  # unreleased, no digest: doctor --platform fails in VALIDATION/PRODUCTION'
            )
    lines += [
        "configMapGenerator:",
        "  - name: trialbox-release  # what doctor --platform compares the running images with",
        "    files:",
        "      - release.json",
    ]
    return "\n".join(lines) + "\n"


# the compose variables that name each image (deploy/docker-compose*.yml, deploy/platform/docker-compose.platform.yml)
COMPOSE_VARS = {
    "TB_IMAGE": "trialbox-py",
    "TB_EMBED_IMAGE": "trialbox-py",
    "TB_DOCPARSER_IMAGE": "trialbox-py",
    "TB_JVM_IMAGE": "trialbox-jvm",
    "POSTGRES_IMAGE": "trialbox-postgres",
    "HAPI_IMAGE": "hapi",
    "VLLM_IMAGE": "vllm",
}


def compose_env(rel: Release) -> list[str]:
    """``VAR=repository:tag@sha256:...`` for the compose platform form (tag only for an unreleased image)."""
    out = []
    for var, name in COMPOSE_VARS.items():
        img = rel.images[name]
        out.append(f"{var}={img.image}" + (f"@{img.digest}" if img.digest else ""))
    return out


def write_component(rel_path: Path = RELEASE, out: Path = COMPONENT) -> list[Path]:
    """Write the component and its copy of ``release.json`` (kustomize reads files only under the component)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(component_yaml(load_release(rel_path)), encoding="utf-8")
    copy = out.parent / "release.json"
    copy.write_bytes(rel_path.read_bytes())
    return [out, copy]


def component_matches(rel_path: Path = RELEASE, out: Path = COMPONENT) -> bool:
    copy = out.parent / "release.json"
    return (
        out.is_file()
        and copy.is_file()
        and out.read_text(encoding="utf-8") == component_yaml(load_release(rel_path))
        and copy.read_bytes() == rel_path.read_bytes()
    )


# ------------------------------------------------------------------------------------------------ state
@dataclass
class PlatformState:
    """The Kubernetes objects the checks read, and where they came from."""

    objects: list[dict[str, Any]] = field(default_factory=list)
    source: str = "manifests"  # manifests | cluster | compose
    namespace: str = ""

    def of(self, *kinds: str) -> list[dict[str, Any]]:
        return [o for o in self.objects if o.get("kind") in kinds]

    def named(self, kind: str, name: str) -> dict[str, Any] | None:
        for o in self.of(kind):
            if (o.get("metadata") or {}).get("name") == name:
                return o
        return None


def state_from_manifests(text: str) -> PlatformState:
    objs = [d for d in yaml.safe_load_all(text) if isinstance(d, dict)]
    flat: list[dict[str, Any]] = []
    for o in objs:
        flat.extend(o.get("items") or [] if o.get("kind", "").endswith("List") else [o])
    ns = next(
        (str((o.get("metadata") or {}).get("namespace")) for o in flat if (o.get("metadata") or {}).get("namespace")),
        "",
    )
    return PlatformState(flat, "manifests", ns)


COMPOSE_ROLES = {"llm-service": "judge", "llm-verifier": "verifier"}  # the pair's compose services (D-142)


def state_from_compose(config: Mapping[str, Any]) -> PlatformState:
    """``docker compose config --format json`` as pseudo workloads: one Deployment per service (its image, its GPU
    reservation). A compose platform has no NetworkPolicy or ResourceQuota objects: those checks then read the
    platform's evidence references (``TB_PLATFORM_NETWORK_POLICY_EVIDENCE``, ``TB_PLATFORM_QUOTA``)."""
    objs: list[dict[str, Any]] = []
    for name, svc in sorted((config.get("services") or {}).items()):
        gpus = 0
        for dev in (
            (((svc.get("deploy") or {}).get("resources") or {}).get("reservations") or {}).get("devices")
        ) or []:
            if "gpu" in (dev.get("capabilities") or []):
                gpus += len(dev.get("device_ids") or []) or int(dev.get("count") or 1)
        res = {"requests": {"nvidia.com/gpu": str(gpus)}} if gpus else {}
        container = {"name": name, "image": svc.get("image", ""), "resources": res}
        labels = {"app.kubernetes.io/component": name}
        role = (svc.get("labels") or {}).get("trialbox.io/role") or COMPOSE_ROLES.get(name)
        if role:
            labels["trialbox.io/role"] = role
        objs.append(
            {
                "kind": "Deployment",
                "metadata": {"name": name, "labels": labels},
                "spec": {"replicas": 1, "template": {"spec": {"containers": [container]}}},
            }
        )
    return PlatformState(objs, "compose", str(config.get("name") or ""))


class KubeApi:
    """The namespace's objects through the API server, with the pod's service account (standard library only)."""

    SA = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    PATHS = (
        ("Pod", "/api/v1/namespaces/{ns}/pods"),
        ("Secret", "/api/v1/namespaces/{ns}/secrets"),
        ("ConfigMap", "/api/v1/namespaces/{ns}/configmaps"),
        ("ResourceQuota", "/api/v1/namespaces/{ns}/resourcequotas"),
        ("PersistentVolumeClaim", "/api/v1/namespaces/{ns}/persistentvolumeclaims"),
        ("Deployment", "/apis/apps/v1/namespaces/{ns}/deployments"),
        ("StatefulSet", "/apis/apps/v1/namespaces/{ns}/statefulsets"),
        ("Job", "/apis/batch/v1/namespaces/{ns}/jobs"),
        ("NetworkPolicy", "/apis/networking.k8s.io/v1/namespaces/{ns}/networkpolicies"),
    )

    def __init__(self, base: str | None = None, sa: Path | None = None) -> None:
        sa = sa or self.SA
        host, port = os.environ.get("KUBERNETES_SERVICE_HOST", ""), os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        self.base = base or f"https://{host}:{port}"
        self.token = (sa / "token").read_text(encoding="utf-8").strip()
        self.namespace = (sa / "namespace").read_text(encoding="utf-8").strip()
        self.ctx = ssl.create_default_context(cafile=str(sa / "ca.crt"))

    def state(self) -> PlatformState:
        objs: list[dict[str, Any]] = []
        for kind, path in self.PATHS:
            req = urllib.request.Request(
                self.base + path.format(ns=self.namespace), headers={"Authorization": f"Bearer {self.token}"}
            )
            with urllib.request.urlopen(req, context=self.ctx, timeout=10) as r:
                doc = json.loads(r.read())
            for item in doc.get("items") or []:
                if kind == "Secret":  # never keep a value: names, labels, annotations and data keys only
                    item = {**item, "data": dict.fromkeys(item.get("data") or {}, ""), "stringData": {}}
                item.setdefault("kind", kind)
                objs.append(item)
        return PlatformState(objs, "cluster", self.namespace)


# ------------------------------------------------------------------------------------------------ helpers
def pod_specs(state: PlatformState) -> list[tuple[dict[str, Any], dict[str, Any], int]]:
    """``(owner object, pod spec, replicas)`` for every workload (and bare pods not owned by one)."""
    out: list[tuple[dict[str, Any], dict[str, Any], int]] = []
    for o in state.of(*WORKLOADS):
        kind, spec = o.get("kind"), o.get("spec") or {}
        if kind == "Pod":
            if (o.get("metadata") or {}).get("ownerReferences"):
                continue  # counted through its workload
            out.append((o, spec, 1))
        elif kind == "CronJob":
            out.append(
                (o, ((spec.get("jobTemplate") or {}).get("spec") or {}).get("template", {}).get("spec") or {}, 1)
            )
        elif kind == "Job":
            if (o.get("metadata") or {}).get("ownerReferences"):
                continue
            out.append((o, (spec.get("template") or {}).get("spec") or {}, 1))
        else:
            reps = spec.get("replicas")
            out.append((o, (spec.get("template") or {}).get("spec") or {}, 1 if reps is None else int(reps)))
    return out


def containers(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [*(spec.get("initContainers") or []), *(spec.get("containers") or [])]


def _name(o: Mapping[str, Any]) -> str:
    return f"{o.get('kind')}/{(o.get('metadata') or {}).get('name')}"


_UNITS = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40, "k": 10**3, "M": 10**6, "G": 10**9, "T": 10**12}


def quantity(v: object) -> float:
    """A Kubernetes quantity as a number (CPU in cores, memory in bytes)."""
    s = str(v).strip()
    if s.endswith("m") and s[:-1].replace(".", "", 1).isdigit():
        return float(s[:-1]) / 1000
    for suf in sorted(_UNITS, key=len, reverse=True):
        if s.endswith(suf):
            return float(s[: -len(suf)]) * _UNITS[suf]
    return float(s)


def _res_key(name: str) -> str:
    return "gpu" if GPU_RESOURCE.match(name) else name


def minimum(state: PlatformState, kind: str = "requests") -> dict[str, float]:
    """The profile's minimum quota: the sum of the workloads' requests (limits where a request is missing, as
    Kubernetes defaults it), per resource; with ``kind="limits"`` the sum of their limits. GPU devices are summed over
    every ``nvidia.com/gpu`` or ``nvidia.com/mig-*`` resource. Jobs count."""
    need: dict[str, float] = {}
    for _, spec, reps in pod_specs(state):
        for c in spec.get("containers") or []:
            res = c.get("resources") or {}
            if kind == "limits":
                req = dict(res.get("limits") or {})
            else:
                req = {**(res.get("limits") or {}), **(res.get("requests") or {})}
            for k, v in req.items():
                key = _res_key(k)
                need[key] = need.get(key, 0.0) + quantity(v) * reps
    return need


COMPUTE = ("cpu", "memory", "ephemeral-storage", "gpu")


def quota_hard(inp: PlatformInputs) -> dict[tuple[str, str], float] | None:
    """The platform's fixed quota as ``{("requests"|"limits", resource): figure}``; a bare name (``cpu``) bounds
    requests, as in Kubernetes. Where several ResourceQuotas bound one resource every one applies, so the lowest
    figure is kept; inside one quota the GPU names (``nvidia.com/gpu``, ``nvidia.com/mig-*``) are alternatives (the
    largest is kept) and a bare name with its ``requests.`` form both bound (the lowest). None: no quota at all."""
    if inp.state.source == "compose":
        raw = inp.env.get("TB_PLATFORM_QUOTA", "")
        hards = [{k.strip(): v.strip() for k, _, v in (p.partition("=") for p in raw.split(",") if p.strip())}]
        if not hards[0]:
            return None
    else:
        quotas = inp.state.of("ResourceQuota")
        if not quotas:
            return None
        hards = [dict((q.get("spec") or {}).get("hard") or {}) for q in quotas]
    out: dict[tuple[str, str], float] = {}
    for hard in hards:
        mine: dict[tuple[str, str], float] = {}
        for k, v in hard.items():
            kind = "limits" if k.startswith("limits.") else "requests"
            res = _res_key(k.removeprefix("requests.").removeprefix("limits."))
            if res not in COMPUTE:
                continue
            n, old = quantity(v), mine.get((kind, res))
            # GPU names are alternatives (one strategy is in use); ``cpu`` and ``requests.cpu`` both bound
            mine[(kind, res)] = n if old is None else (max(old, n) if res == "gpu" else min(old, n))
        for key, n in mine.items():
            out[key] = min(out.get(key, n), n)
    return out


# ------------------------------------------------------------------------------------------------ checks
@dataclass
class PlatformInputs:
    state: PlatformState
    release: Release
    env: Mapping[str, str] = field(default_factory=dict)
    no_gpu: bool = False
    routing_path: Path = ROOT / "models" / "routing.yaml"
    connect: Callable[[str, int], None] | None = None  # raises OSError when the host does not answer
    sntp: Callable[[str], float] | None = None  # returns the offset in seconds
    resolve: Callable[[str], list[str]] | None = None  # host -> addresses (the egress policies' ipBlocks)


def _strict(inp: PlatformInputs) -> bool:
    return inp.env.get("TB_ENV", "PRODUCTION") in ("VALIDATION", "PRODUCTION")


def check_image_digests(inp: PlatformInputs) -> Check:
    rel, bad, unreleased, seen = inp.release, [], [], 0
    for owner, spec, _ in pod_specs(inp.state):
        for c in containers(spec):
            seen += 1
            ref = str(c.get("image") or "")
            repo, tag, digest = split_ref(ref)
            where = f"{_name(owner)} {c.get('name')}"
            want = rel.by_repository(repo)
            if tag == "latest" or (tag is None and digest is None):
                bad.append(f"{where}: {ref or '(no image)'} is not pinned (a latest or missing tag is refused)")
            elif want is None:
                bad.append(f"{where}: {ref} is not an image of release {rel.release_id}")
            elif tag is not None and tag != want.tag:
                bad.append(f"{where}: {ref} is not the release's tag {want.tag}")
            elif digest is None:
                if want.digest:
                    bad.append(f"{where}: {ref} has no digest (release {rel.release_id}: {want.digest[:19]}...)")
                else:
                    unreleased.append(f"{where}: {ref}")
            elif digest != want.digest:
                bad.append(f"{where}: {ref} is not the release's digest {want.digest or '(unreleased)'}")
    for pod in inp.state.of("Pod"):  # what actually runs, from the kubelet
        for cs in (pod.get("status") or {}).get("containerStatuses") or []:
            iid, ref = str(cs.get("imageID") or ""), str(cs.get("image") or "")
            want = inp.release.by_repository(split_ref(ref)[0])
            if want and want.digest and "@sha256:" in iid and not iid.endswith(want.digest):
                bad.append(f"{_name(pod)} {cs.get('name')}: running {iid.rsplit('@', 1)[-1]}, release {want.digest}")
    if not seen:
        return Check("image_digests", "FAIL", "no workload found")  # nothing deployed is not a pass
    if bad:
        return Check("image_digests", "FAIL", "; ".join(bad[:6]) + (f" (+{len(bad) - 6})" if len(bad) > 6 else ""))
    if unreleased:
        status: Status = "FAIL" if _strict(inp) else "WARN"
        return Check(
            "image_digests",
            status,
            f"unreleased images, tag only (release {rel.release_id}): " + "; ".join(unreleased[:4]),
        )
    return Check("image_digests", "PASS", f"{seen} containers on the digests of release {rel.release_id}")


def check_quota(inp: PlatformInputs) -> Check:
    need = {"requests": minimum(inp.state), "limits": minimum(inp.state, "limits")}
    hard = quota_hard(inp)
    if hard is None:
        if inp.state.source == "compose":
            return Check(
                "quota", "FAIL", "no TB_PLATFORM_QUOTA (the platform's fixed quota, e.g. gpu=2,cpu=16,memory=96Gi)"
            )
        floor = ", ".join(f"{r} {_fmt(r, n)}" for r, n in sorted(need["requests"].items()))
        return Check(
            "quota",
            "FAIL",
            f"no ResourceQuota in the namespace: the platform's fixed quota is the contract (profile minimum: {floor})",
        )
    skip_gpu = inp.no_gpu and not _strict(inp)
    short, notes, shown = [], [], []
    for res, n in sorted(need["requests"].items()):
        if res == "gpu" and skip_gpu:
            notes.append(f"gpu {NO_DEVICE}")
            continue
        have = hard.get(("requests", res))
        if have is None:
            if inp.state.source == "compose" and res != "gpu":
                notes.append(f"{res}: no figure in TB_PLATFORM_QUOTA")
                continue
            short.append(f"{res}: no quota figure (need {_fmt(res, n)})")
        elif have < n:
            short.append(f"{res}: quota {_fmt(res, have)} < profile minimum {_fmt(res, n)}")
        else:
            shown.append(f"{res} {_fmt(res, have)} >= {_fmt(res, n)}")
    for (kind, res), have in sorted(hard.items()):
        if kind != "limits" or (res == "gpu" and skip_gpu):
            continue
        lacking = [
            f"{_name(owner)} {c.get('name')}"
            for owner, spec, _ in pod_specs(inp.state)
            for c in containers(spec)
            if not any(_res_key(k) == res for k in ((c.get("resources") or {}).get("limits") or {}))
        ]
        if lacking:
            short.append(
                f"limits.{res} is bounded but {len(lacking)} containers set no {res} limit (refused by the quota): "
                + ", ".join(lacking[:4])
            )
        n = need["limits"].get(res, 0.0)
        if have < n:
            short.append(f"limits.{res}: quota {_fmt(res, have)} < the workloads' limits {_fmt(res, n)}")
        else:
            shown.append(f"limits.{res} {_fmt(res, have)} >= {_fmt(res, n)}")
    if short:
        return Check("quota", "FAIL", "; ".join(short))
    return Check("quota", "PASS", ", ".join(shown) + (f"; {'; '.join(notes)}" if notes else ""))


def _fmt(res: str, n: float) -> str:
    if res == "memory":
        return f"{n / 2**30:.1f}Gi"
    return f"{n:g}"


def check_storage_encryption(inp: PlatformInputs) -> Check:
    flag = inp.env.get("TB_PLATFORM_STORAGE_ENCRYPTED", "").strip().lower()
    ref = inp.env.get("TB_PLATFORM_STORAGE_EVIDENCE", "").strip()
    cls = inp.env.get("TB_PLATFORM_STORAGE_CLASS", "").strip()
    off = []
    if cls:
        for pvc in inp.state.of("PersistentVolumeClaim"):
            got = (pvc.get("spec") or {}).get("storageClassName")
            if got != cls:
                off.append(f"{_name(pvc)} uses {got or 'the default class'}")
        for sts in inp.state.of("StatefulSet"):
            for t in (sts.get("spec") or {}).get("volumeClaimTemplates") or []:
                if (t.get("spec") or {}).get("storageClassName") != cls:
                    off.append(f"{_name(sts)} claim {(t.get('metadata') or {}).get('name')} not on {cls}")
    if off:
        return Check("storage_encryption", "FAIL", f"claims outside the encrypted class {cls}: " + "; ".join(off[:5]))
    if not cls and _strict(inp):
        return Check(
            "storage_encryption",
            "FAIL",
            "no TB_PLATFORM_STORAGE_CLASS: in VALIDATION and PRODUCTION every claim must be on the encrypted class "
            "the platform evidences, so the class is named and checked",
        )
    if flag == "yes" and ref:
        return Check(
            "storage_encryption", "PASS", f"evidenced by the platform: {ref}" + (f" (class {cls})" if cls else "")
        )
    why = "TB_PLATFORM_STORAGE_ENCRYPTED is not yes" if flag != "yes" else "no TB_PLATFORM_STORAGE_EVIDENCE reference"
    return Check(
        "storage_encryption",
        "FAIL" if _strict(inp) else "WARN",
        f"{why}: the encryption of the volume is evidenced by the platform (IT pack §A.6)",
    )


# ------------------------------------------------------------------------------------------------ network policy
SHIPPED_POLICIES = ROOT / "deploy" / "platform" / "base" / "networkpolicy.yaml"
DOCTOR_POLICY = "trialbox-egress-doctor"


@dataclass(frozen=True)
class DoctorDst:
    """One destination the install-check job probes (its egress policy holds exactly these)."""

    what: str  # api-server | ntp | directory | mail-relay | backup
    host: str
    port: int
    protocol: str = "TCP"


def _hostport(value: str, default: int) -> tuple[str, int] | None:
    """``host``, ``host:port``, ``[v6]:port`` or a URL -> (host, port)."""
    v = value.strip()
    if not v:
        return None
    if "://" in v:
        u = urlparse(v)
        return (u.hostname, u.port or default) if u.hostname else None
    if v.startswith("["):
        host, _, rest = v[1:].partition("]")
        return host, int(rest.removeprefix(":") or default)
    if v.count(":") == 1:
        host, _, port = v.partition(":")
        return host, int(port)
    return v, default


def doctor_destinations(env: Mapping[str, str]) -> tuple[list[DoctorDst], list[str]]:
    """What the doctor job may reach, from the site's declarations only: the API server
    (``TB_PLATFORM_API_SERVER``: the kubernetes endpoint addresses, ``host:port`` list), ``TB_NTP_SERVER`` (UDP 123),
    the directory (``TB_DIRECTORY_URL``), the mail relay (``SMTP_HOST:SMTP_PORT``) and the backup share
    (``TB_PLATFORM_BACKUP_HOST``, ``host:port`` list, 445 by default). A destination not declared gets no rule and a
    warning (fail closed: the doctor then reports that probe as failing)."""
    out: list[DoctorDst] = []
    warn: list[str] = []

    def many(var: str, what: str, default: int) -> None:
        vals = [v for v in env.get(var, "").split(",") if v.strip()]
        if not vals:
            warn.append(f"{var} not declared: the doctor gets no {what} rule")
        for v in vals:
            hp = _hostport(v, default)
            if hp:
                out.append(DoctorDst(what, hp[0], hp[1]))

    many("TB_PLATFORM_API_SERVER", "api-server", 443)
    ntp = env.get("TB_NTP_SERVER", "").strip()
    if ntp:
        out.append(DoctorDst("ntp", ntp, 123, "UDP"))
    else:
        warn.append("TB_NTP_SERVER not declared: the doctor gets no ntp rule")
    url = env.get("TB_DIRECTORY_URL", "").strip()
    if url:
        u = urlparse(url)
        port = u.port or {"ldap": 389, "ldaps": 636, "https": 443}.get(u.scheme, 0)
        if u.hostname and port:
            out.append(DoctorDst("directory", u.hostname, port))
        else:
            warn.append(f"TB_DIRECTORY_URL={url!r} is not ldap://, ldaps:// or https://: no directory rule")
    smtp = env.get("SMTP_HOST", "").strip()
    if smtp:
        out.append(DoctorDst("mail-relay", smtp, int(env.get("SMTP_PORT") or 587)))
    else:
        warn.append("SMTP_HOST not declared: the doctor gets no mail-relay rule")
    many("TB_PLATFORM_BACKUP_HOST", "backup", 445)
    return out, warn


def _resolve(host: str) -> list[str]:
    return list(_egress().resolve(host))


def render_doctor_policy(
    env: Mapping[str, str], resolver: Callable[[str], list[str]] | None = None
) -> tuple[dict[str, Any] | None, list[str]]:
    """The doctor job's egress policy, rendered as ``platform-egress`` renders the allowlist (one rule per declared
    destination, its addresses as /32 or /128 ipBlocks, resolved now). None when nothing is declared or resolves."""
    res = resolver or _resolve
    dsts, warn = doctor_destinations(env)
    rules: list[dict[str, Any]] = []
    kept: list[DoctorDst] = []
    for d in dsts:
        addrs = sorted(res(d.host))
        if not addrs:
            warn.append(f"{d.host}: does not resolve; doctor {d.what} rule skipped")
            continue
        blocks = [{"ipBlock": {"cidr": f"{a}/{128 if ':' in a else 32}"}} for a in addrs]
        rules.append({"to": blocks, "ports": [{"protocol": d.protocol, "port": d.port}]})
        kept.append(d)
    if not rules:
        return None, warn
    pol = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": DOCTOR_POLICY,
            "labels": {"app.kubernetes.io/part-of": "trialbox", "trialbox.io/policy": "doctor-egress"},
            "annotations": {
                "trialbox.io/egress-hosts": ",".join(f"{d.what}={d.host}:{d.port}/{d.protocol}" for d in kept)
            },
        },
        "spec": {
            "podSelector": {"matchLabels": {"app.kubernetes.io/component": "doctor"}},
            "policyTypes": ["Egress"],
            "egress": rules,
        },
    }
    return pol, warn


def _canon(x: Any) -> Any:
    """A policy spec without empty fields and with the defaults the API server fills (protocol TCP)."""
    if isinstance(x, dict):
        d = {k: _canon(v) for k, v in x.items()}
        if "port" in d and "protocol" not in d:
            d["protocol"] = "TCP"
        return {k: v for k, v in d.items() if v not in (None, [], {})}
    if isinstance(x, list):
        return [_canon(i) for i in x]
    return str(x)


def _blocks(p: Mapping[str, Any]) -> set[tuple[str, str, str]]:
    """``(destination, protocol, port)`` for every egress rule of a policy."""
    out: set[tuple[str, str, str]] = set()
    for r in (p.get("spec") or {}).get("egress") or []:
        for peer in r.get("to") or []:
            ib = peer.get("ipBlock") or {}
            dst = (
                ib["cidr"] + "".join(f" except {e}" for e in sorted(ib.get("except") or []))
                if ib.get("cidr")
                else json.dumps(peer, sort_keys=True)
            )
            for pt in r.get("ports") or [{}]:
                out.add((dst, str(pt.get("protocol") or "TCP"), str(pt.get("port", "*"))))
    return out


def open_rules(pols: Iterable[Mapping[str, Any]]) -> list[str]:
    """The rules that let anything through: an ingress rule without ``from``, an egress rule without ``to`` (both
    mean every peer), or an ipBlock of a whole address space (``0.0.0.0/0``, ``::/0``)."""
    bad = []
    for p in pols:
        name, spec = (p.get("metadata") or {}).get("name"), p.get("spec") or {}
        for direction, peers in (("ingress", "from"), ("egress", "to")):
            for i, r in enumerate(spec.get(direction) or []):
                if not (r or {}).get(peers):
                    bad.append(f"{name} {direction}[{i}] has no {peers} (every peer)")
                    continue
                for peer in r[peers]:
                    cidr = str((peer.get("ipBlock") or {}).get("cidr") or "")
                    if cidr.endswith("/0"):
                        bad.append(f"{name} {direction}[{i}] allows {cidr}")
    return bad


def check_network_policy(inp: PlatformInputs) -> Check:
    eg = _egress()
    try:
        allows = eg.allowlist(dict(inp.env), inp.routing_path)
    except SystemExit as e:
        return Check("network_policy", "FAIL", str(e))
    want = sorted({f"{a.service}->{a.host}:{a.port}" for a in allows})
    if inp.state.source == "compose":
        ref = inp.env.get("TB_PLATFORM_NETWORK_POLICY_EVIDENCE", "").strip()
        if not ref:
            return Check(
                "network_policy",
                "FAIL",
                "compose platform: no TB_PLATFORM_NETWORK_POLICY_EVIDENCE (the platform's egress rule for the hosts "
                "of deploy/egress.py)",
            )
        return Check(
            "network_policy", "PASS", f"evidenced by the platform: {ref}; allowlist {', '.join(want) or 'empty'}"
        )
    pols = inp.state.of("NetworkPolicy")
    names = {(p.get("metadata") or {}).get("name") for p in pols}
    missing = [n for n in REQUIRED_POLICIES if n not in names]
    if missing:
        return Check("network_policy", "FAIL", "missing NetworkPolicy: " + ", ".join(missing))
    deny = inp.state.named("NetworkPolicy", "trialbox-default-deny") or {}
    dspec = deny.get("spec") or {}
    if (
        dspec.get("podSelector") not in ({}, None)
        or set(dspec.get("policyTypes") or []) != {"Ingress", "Egress"}
        or dspec.get("ingress")
        or dspec.get("egress")
    ):
        return Check(
            "network_policy", "FAIL", "trialbox-default-deny does not deny all ingress and egress of every pod"
        )
    wide = open_rules(pols)
    if wide:
        return Check("network_policy", "FAIL", "open rules: " + "; ".join(wide[:6]))
    shipped = {
        (d.get("metadata") or {}).get("name"): d
        for d in yaml.safe_load_all(SHIPPED_POLICIES.read_text(encoding="utf-8"))
        if isinstance(d, dict)
    }
    for name in ("trialbox-model-isolation",):
        got_spec = (inp.state.named("NetworkPolicy", name) or {}).get("spec") or {}
        if _canon(got_spec) != _canon(shipped[name].get("spec") or {}):
            return Check("network_policy", "FAIL", f"{name} differs from the shipped one (deploy/platform/base)")
    egress_pols = {
        (p.get("metadata") or {}).get("name"): p
        for p in pols
        if ((p.get("metadata") or {}).get("labels") or {}).get("trialbox.io/policy") == "egress-allowlist"
    }
    got = sorted(
        {
            f"{_selects(p)}->{hp}"
            for p in egress_pols.values()
            for hp in filter(
                None,
                ((p.get("metadata") or {}).get("annotations") or {}).get("trialbox.io/egress-hosts", "").split(","),
            )
        }
    )
    if got != want:
        extra, lack = sorted(set(got) - set(want)), sorted(set(want) - set(got))
        return Check(
            "network_policy",
            "FAIL",
            f"egress policies differ from deploy/egress.py: missing {lack or '-'}, extra {extra or '-'}",
        )
    res = inp.resolve or _resolve
    rendered, _ = eg.render_networkpolicy(allows, res)
    differ = []
    for exp in rendered:
        name = exp["metadata"]["name"]
        act = egress_pols.get(name) or {}
        if _canon((act.get("spec") or {}).get("podSelector")) != _canon(exp["spec"]["podSelector"]):
            differ.append(f"{name}: selects other pods")
        elif _blocks(act) != _blocks(exp):
            differ.append(
                f"{name}: ipBlocks {sorted(_blocks(act) - _blocks(exp)) or '-'} not rendered, "
                f"{sorted(_blocks(exp) - _blocks(act)) or '-'} missing"
            )
    differ += [
        f"{n}: not rendered from deploy/egress.py"
        for n in egress_pols
        if n not in {r["metadata"]["name"] for r in rendered}
    ]
    doc_pols = [
        p
        for p in pols
        if (p.get("metadata") or {}).get("name") == DOCTOR_POLICY
        or ((p.get("metadata") or {}).get("labels") or {}).get("trialbox.io/policy") == "doctor-egress"
    ]
    doc_note = "doctor egress: none (the doctor reaches nothing outside)"
    if doc_pols:
        exp_doc, _ = render_doctor_policy(inp.env, res)
        for act in doc_pols:
            name = (act.get("metadata") or {}).get("name")
            if exp_doc is None:
                differ.append(f"{name}: the site declares no doctor destination")
            elif _canon((act.get("spec") or {}).get("podSelector")) != _canon(exp_doc["spec"]["podSelector"]):
                differ.append(f"{name}: selects other pods than the doctor")
            elif _blocks(act) != _blocks(exp_doc):
                differ.append(
                    f"{name}: ipBlocks {sorted(_blocks(act) - _blocks(exp_doc)) or '-'} not declared, "
                    f"{sorted(_blocks(exp_doc) - _blocks(act)) or '-'} missing"
                )
        doc_note = "doctor egress as declared"
    if differ:
        return Check(
            "network_policy",
            "FAIL",
            "egress policies differ from what platform-egress renders now (re-render if an address changed): "
            + "; ".join(differ[:5]),
        )
    return Check(
        "network_policy",
        "PASS",
        f"default deny, model isolation as shipped, no open rule; egress allowlist {', '.join(want) or 'empty'}; "
        + doc_note,
    )


def _selects(p: Mapping[str, Any]) -> str:
    return str(
        ((p.get("spec") or {}).get("podSelector") or {}).get("matchLabels", {}).get("app.kubernetes.io/component")
    )


def check_kek_custody(inp: PlatformInputs) -> Check:
    hits = []
    for s in inp.state.of("Secret"):
        meta = s.get("metadata") or {}
        marks = [
            meta.get("name") or "",
            *((meta.get("labels") or {}).keys()),
            *((meta.get("annotations") or {}).keys()),
        ]
        keys = [*(s.get("data") or {}).keys(), *(s.get("stringData") or {}).keys()]
        found = [k for k in [*keys, *marks] if KEK_KEYS.search(str(k))]
        if found:
            hits.append(f"Secret/{meta.get('name')} ({', '.join(sorted(set(map(str, found))))})")
    if hits:
        return Check(
            "kek_custody",
            "FAIL",
            "a plain platform Secret holds the KEK or a key it protects (WS-13.11: a hospital KMS or the steward's "
            "unseal, never a Secret): " + "; ".join(hits),
        )
    return Check(
        "kek_custody",
        "PASS",
        f"no Secret holds the KEK ({len(inp.state.of('Secret'))} Secrets read, names and keys only)",
    )


def _connect(host: str, port: int) -> None:
    with socket.create_connection((host, port), timeout=5):
        pass


def sntp_offset(server: str, timeout: float = 3.0) -> float:
    """Clock offset to ``server`` in seconds (one SNTP v4 query, RFC 4330)."""
    packet = b"\x23" + 47 * b"\0"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        t0 = time.time()
        s.sendto(packet, (server, 123))
        data, _ = s.recvfrom(512)
        t3 = time.time()
    secs, frac = struct.unpack("!II", data[40:48])
    t2 = secs - 2208988800 + frac / 2**32
    return float(t2 - (t0 + t3) / 2)


def check_ntp(inp: PlatformInputs) -> Check:
    server = inp.env.get("TB_NTP_SERVER", "").strip()
    if not server:
        return Check(
            "ntp", "FAIL" if _strict(inp) else "WARN", "no TB_NTP_SERVER: the hospital's time source is not named"
        )
    limit = float(inp.env.get("TB_NTP_MAX_OFFSET_S") or 1.0)
    try:
        off = (inp.sntp or sntp_offset)(server)
    except OSError as e:
        return Check("ntp", "FAIL", f"{server} does not answer SNTP: {e}")
    if abs(off) > limit:
        return Check("ntp", "FAIL", f"clock off by {off:+.3f} s from {server} (limit {limit} s)")
    return Check("ntp", "PASS", f"clock within {off:+.3f} s of {server}")


def _probe(inp: PlatformInputs, name: str, host: str, port: int, what: str) -> Check:
    try:
        (inp.connect or _connect)(host, port)
    except OSError as e:
        return Check(name, "FAIL", f"{what} {host}:{port} does not answer from the namespace: {e}")
    return Check(name, "PASS", f"{what} {host}:{port} answers")


def check_directory(inp: PlatformInputs) -> Check:
    url = inp.env.get("TB_DIRECTORY_URL", "").strip()
    if not url:
        return Check("directory", "WARN", "no hospital directory (TB_DIRECTORY_URL): local accounts")
    u = urlparse(url)
    port = u.port or {"ldap": 389, "ldaps": 636, "https": 443}.get(u.scheme, 0)
    if not u.hostname or not port:
        return Check("directory", "FAIL", f"TB_DIRECTORY_URL={url!r} is not ldap://, ldaps:// or https://")
    return _probe(inp, "directory", u.hostname, port, "directory")


def check_mail_relay(inp: PlatformInputs) -> Check:
    host = inp.env.get("SMTP_HOST", "").strip()
    if not host:
        return Check("mail_relay", "FAIL" if _strict(inp) else "WARN", "no SMTP_HOST: the morning mail has no relay")
    return _probe(inp, "mail_relay", host, int(inp.env.get("SMTP_PORT") or 587), "mail relay")


def check_backup_target(inp: PlatformInputs) -> Check:
    from tools.trialbox import backup_schedule as bsch

    targets = [t for t in (inp.env.get("TB_BACKUP_TARGETS") or "").replace(";", ",").split(",") if t.strip()]
    ref = inp.env.get("TB_PLATFORM_BACKUP_EVIDENCE", "").strip()
    prod = inp.env.get("TB_ENV", "PRODUCTION") == "PRODUCTION"
    if not targets:
        return Check("backup_target", "FAIL" if prod else "WARN", "no TB_BACKUP_TARGETS")
    kinds = []
    for t in targets:
        p = Path(t.strip())
        kinds.append(bsch.target_kind(p) if p.exists() else None)
    if all(k is not None and k.offbox for k in kinds):
        return Check("backup_target", "PASS", "; ".join(f"{k.path}: {k.kind}" for k in kinds if k))
    if ref:
        return Check("backup_target", "PASS", f"{', '.join(targets)}: off-box by the platform's declaration {ref}")
    return Check(
        "backup_target",
        "FAIL" if prod else "WARN",
        f"{', '.join(targets)}: not shown off-box (no network share mounted, no TB_PLATFORM_BACKUP_EVIDENCE)",
    )


NO_GPU_REFUSED = (
    "--no-gpu (TB_PLATFORM_NO_GPU) is refused in VALIDATION and PRODUCTION: the GPU checks never skip there"
)


def _gpu_skipped(inp: PlatformInputs, name: str) -> Check | None:
    """SKIP for a GPU check under ``--no-gpu``, except in VALIDATION and PRODUCTION, where it is a FAIL: there the
    evidence can never say ``passed`` without the GPU checks."""
    if not inp.no_gpu:
        return None
    if _strict(inp):
        return Check(name, "FAIL", NO_GPU_REFUSED)
    return Check(name, "SKIP", NO_DEVICE)


def check_serving_record(inp: PlatformInputs) -> Check:
    if (skipped := _gpu_skipped(inp, "serving_record")) is not None:
        return skipped
    from tools import serving_config as sc

    path = inp.env.get("TB_SERVING_RECORD", "").strip()
    mig = inp.env.get("TB_MIG_PROFILE", "").strip()
    if not path or not Path(path).is_file():
        return Check(
            "serving_record",
            "FAIL",
            f"absent ({path or 'TB_SERVING_RECORD unset'}): the shared-quota profile is measured on the partition, "
            "never assumed (WS-02.7, T-114)",
        )
    rec = json.loads(Path(path).read_text(encoding="utf-8"))
    why = sc.validate(rec)
    card = rec.get("card") or {}
    if not mig or mig == "unmeasured":
        why.append("TB_MIG_PROFILE is not set to the partition the namespace was given")
    elif card.get("mig_profile") != mig:
        why.append(f"the record's MIG profile {card.get('mig_profile')!r} is not this namespace's {mig!r}")
    if card.get("capped_to"):
        why.append(f"measured on a capped card ({card['capped_to']})")
    roles = {s.get("role") for s in rec.get("servers") or []}
    why += [f"no {r} server in the record" for r in sc.ROLES if r not in roles]
    if why:
        return Check("serving_record", "FAIL", f"{path}: " + "; ".join(why))
    return Check(
        "serving_record",
        "PASS",
        f"{path}: {card.get('name')} {mig}, driver {card.get('driver')}, CUDA {card.get('cuda')}",
    )


GPU_ROLES = ("judge", "verifier")


def _devices(spec: Mapping[str, Any]) -> int:
    """GPU devices one pod of this spec takes (an extended resource's request equals its limit)."""
    n = 0.0
    for c in containers(spec):
        res = c.get("resources") or {}
        per = {**(res.get("requests") or {}), **(res.get("limits") or {})}
        n += sum(quantity(v) for k, v in per.items() if GPU_RESOURCE.match(k))
    return int(n)


def _role(owner: Mapping[str, Any]) -> str:
    tmpl = (((owner.get("spec") or {}).get("template") or {}).get("metadata") or {}).get("labels") or {}
    return str(
        tmpl.get("trialbox.io/role")
        or ((owner.get("metadata") or {}).get("labels") or {}).get("trialbox.io/role")
        or ""
    )


def check_gpu_serving(inp: PlatformInputs) -> Check:
    """Two devices, enforced: exactly one judge and one verifier workload (``trialbox.io/role``), each taking exactly
    one GPU device (one replica, one device), no other workload with a GPU, and a GPU quota of at least two."""
    if (skipped := _gpu_skipped(inp, "gpu_serving")) is not None:
        return skipped
    bad: list[str] = []
    by_role: dict[str, list[tuple[dict[str, Any], int]]] = {}
    for owner, spec, reps in pod_specs(inp.state):
        role, dev = _role(owner), _devices(spec) * reps
        if role in GPU_ROLES:
            by_role.setdefault(role, []).append((owner, dev))
        elif dev:
            bad.append(f"{_name(owner)} takes {dev} GPU devices and is neither the judge nor the verifier")
    for role in GPU_ROLES:
        got = by_role.get(role, [])
        if len(got) != 1:
            bad.append(f"{len(got)} {role} workloads (trialbox.io/role={role}), need exactly one")
        for owner, dev in got:
            if dev != 1:
                bad.append(f"{role} {_name(owner)} takes {dev} GPU devices, need exactly one")
    hard = quota_hard(inp) or {}
    gpu_quota = hard.get(("requests", "gpu"))
    if gpu_quota is None or gpu_quota < len(GPU_ROLES):
        bad.append(
            f"GPU quota {_fmt('gpu', gpu_quota) if gpu_quota is not None else 'not set'} < 2 (the judge and the "
            "verifier, one device each)"
        )
    if bad:
        return Check("gpu_serving", "FAIL", "; ".join(bad))
    pair = [o for role in GPU_ROLES for o, _ in by_role[role]]
    if inp.state.source != "cluster":
        return Check(
            "gpu_serving",
            "PASS",
            f"judge and verifier declared, one device each, GPU quota {_fmt('gpu', gpu_quota or 0)} "
            f"({inp.state.source}; running state not read)",
        )
    down = []
    for o in pair:
        comp = ((o.get("metadata") or {}).get("labels") or {}).get("app.kubernetes.io/component")
        pods = [
            p
            for p in inp.state.of("Pod")
            if ((p.get("metadata") or {}).get("labels") or {}).get("app.kubernetes.io/component") == comp
        ]
        ready = [
            p
            for p in pods
            if any(
                c.get("type") == "Ready" and c.get("status") == "True"
                for c in (p.get("status") or {}).get("conditions") or []
            )
        ]
        if not ready:
            down.append(f"{comp}: no ready pod")
    if down:
        return Check("gpu_serving", "FAIL", "; ".join(down))
    return Check("gpu_serving", "PASS", "judge and verifier ready, one device each")


def check_canary(inp: PlatformInputs) -> Check:
    if (skipped := _gpu_skipped(inp, "canary")) is not None:
        return skipped
    path = inp.env.get("TB_CANARY_RESULT", "").strip()
    if not path or not Path(path).is_file():
        return Check(
            "canary",
            "FAIL",
            f"no canary result ({path or 'TB_CANARY_RESULT unset'}): run the trialbox-canary job on the partition",
        )
    rep = json.loads(Path(path).read_text(encoding="utf-8"))
    if rep.get("ok") is not True:
        return Check("canary", "FAIL", f"{path}: the pair canary did not pass (at {rep.get('at', '?')})")
    return Check("canary", "PASS", f"{path}: the pair canary passed at {rep.get('at', '?')}")


PLATFORM_CHECKS: tuple[Callable[[PlatformInputs], Check], ...] = (
    check_image_digests,
    check_quota,
    check_storage_encryption,
    check_network_policy,
    check_kek_custody,
    check_ntp,
    check_directory,
    check_mail_relay,
    check_backup_target,
    check_serving_record,
    check_gpu_serving,
    check_canary,
)


def run(inp: PlatformInputs) -> list[Check]:
    out: list[Check] = []
    for fn in PLATFORM_CHECKS:
        name = fn.__name__.removeprefix("check_")
        try:
            out.append(fn(inp))
        except Exception as e:  # fail closed
            out.append(Check(name, "FAIL", f"check error: {type(e).__name__}: {e}"))
    return out


def evidence(checks: Iterable[Check], inp: PlatformInputs, *, now: datetime | None = None) -> dict[str, Any]:
    """The IQ evidence document (``iq-evidence.json``; TST-IQ-03 attaches it)."""
    rows = [asdict(c) for c in checks]
    return {
        "schema": EVIDENCE_SCHEMA,
        "generated_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "source": inp.state.source,
        "namespace": inp.state.namespace,
        "environment": inp.env.get("TB_ENV", "PRODUCTION"),
        "gpu_profile": inp.env.get("TB_GPU_PROFILE", ""),
        "mig_profile": inp.env.get("TB_MIG_PROFILE", ""),
        "no_gpu": inp.no_gpu,
        "release": {"release_id": inp.release.release_id, "sha256": inp.release.sha256},
        "checks": rows,
        "passed": all(r["status"] != "FAIL" for r in rows),
    }


def lint_manifests(text: str) -> list[str]:
    """Image refusals for a rendered manifest stream (before it is applied): a ``latest`` or missing tag."""
    st = state_from_manifests(text)
    bad = []
    for owner, spec, _ in pod_specs(st):
        for c in containers(spec):
            ref = str(c.get("image") or "")
            _, tag, digest = split_ref(ref)
            if tag == "latest" or (tag is None and digest is None):
                bad.append(f"{_name(owner)} {c.get('name')}: {ref or '(no image)'}")
    return bad


def manifest_env(state: PlatformState) -> dict[str, str]:
    """The environment the rendered ConfigMaps give the doctor job (trialbox-env, -platform, -serving)."""
    env: dict[str, str] = {}
    for prefix in ("trialbox-env", "trialbox-platform", "trialbox-serving"):
        for cm in state.of("ConfigMap"):
            name = str((cm.get("metadata") or {}).get("name") or "")
            if name == prefix or re.fullmatch(re.escape(prefix) + r"-[a-z0-9]{10}", name):
                env.update({str(k): str(v) for k, v in (cm.get("data") or {}).items()})
    return env


def platform_env(env: Mapping[str, str]) -> dict[str, str]:
    """doctor's environment plus what the egress allowlist and the probes read (SMTP_*, IMAP_*, NHI_*, TB_EP_*)."""
    keys = set(_egress()._KEYS)
    return {**env, **{k: v for k, v in os.environ.items() if k in keys or k.startswith("TB_EP_")}}


def inputs_from(a: Any, env: Mapping[str, str], routing: Path) -> PlatformInputs:
    """The platform inputs from ``doctor``'s arguments: rendered manifests, a compose config, or the cluster."""
    if a.manifests is not None and a.compose_config is not None:
        raise PlatformError("give --manifests or --compose-config, not both")
    if a.manifests is not None:
        state = state_from_manifests(a.manifests.read_text(encoding="utf-8"))
        env = {**manifest_env(state), **env}  # what the pods will read, unless this shell says otherwise
    elif a.compose_config is not None:
        state = state_from_compose(json.loads(a.compose_config.read_text(encoding="utf-8")))
    elif os.environ.get("KUBERNETES_SERVICE_HOST"):
        state = KubeApi().state()
    else:
        raise PlatformError("not in a cluster: give --manifests (kustomize build output) or --compose-config")
    in_pod = Path(env.get("TB_RELEASE_FILE") or RELEASE)
    release = load_release(a.release or (in_pod if in_pod.is_file() else RELEASE))
    penv = platform_env(env)
    no_gpu = a.no_gpu or penv.get("TB_PLATFORM_NO_GPU", "") in ("1", "true", "yes")  # a test cluster's overlay
    inp = PlatformInputs(state, release, penv, no_gpu=no_gpu, routing_path=routing)
    if no_gpu and _strict(inp):
        raise PlatformError(f"{NO_GPU_REFUSED} (TB_ENV={penv.get('TB_ENV', 'PRODUCTION')})")
    return inp
