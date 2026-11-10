"""``trialbox doctor --platform``: the install checks on a hospital platform (WS-14.8, WS-11.8, WS-13.9; D-211).

The same signed images run on a platform TrialBox does not own (CGMH's shared B200, an interim private cloud) from
the Kubernetes manifests of ``deploy/platform`` or the compose variant ``deploy/platform/docker-compose.platform.yml``.
There is no ``install.sh`` there, so the install checks run as a job in the namespace and write the IQ evidence
(``iq-evidence.json``) the IQ protocol (TST-IQ-03) attaches. Each check is PASS, WARN, FAIL or SKIP (``--no-gpu``
makes the GPU checks ``skipped: no device``); any FAIL makes the command exit 1, and a check that raises is a FAIL.

What the checks read is a list of Kubernetes objects (``PlatformState``): from the API server inside the namespace
(the doctor Job's service account, read-only), from rendered manifests (``--manifests``: ``kustomize build`` output,
before anything is applied) or from ``docker compose config --format json`` (``--compose-config``). Checks:

* ``image_digests``: every container image is pinned by digest and the digest is ``release.json``'s; a ``latest``
  tag or an image that is not in the release is refused; a tag without a digest is a FAIL in VALIDATION and
  PRODUCTION (an unreleased build) and a WARN elsewhere; a running container whose image id differs is a FAIL;
* ``quota``: the namespace's ResourceQuota covers the profile's minimum, which is the sum of the requests of the
  workloads (CPU, memory, GPU devices); the GPU part is skipped with ``--no-gpu``;
* ``storage_encryption``: evidenced by the platform, not tested (PR-19): ``TB_PLATFORM_STORAGE_ENCRYPTED=yes`` with
  ``TB_PLATFORM_STORAGE_EVIDENCE`` (the storage class specification's reference); every claim uses
  ``TB_PLATFORM_STORAGE_CLASS`` when it is set;
* ``network_policy``: the default deny and the model isolation policies exist, and the egress allowlist policies
  name exactly the hosts ``deploy/egress.py`` allows (one source, two renderings);
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
* ``gpu_serving``: the judge and the verifier pods run; ``canary``: the last canary result (``TB_CANARY_RESULT``,
  ``tools/canary.py --out``) passed. Both are skipped with ``--no-gpu``.

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
    "POSTGRES_IMAGE": "postgres",
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
        objs.append(
            {
                "kind": "Deployment",
                "metadata": {"name": name, "labels": {"app.kubernetes.io/component": name}},
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


def minimum(state: PlatformState) -> dict[str, float]:
    """The profile's minimum quota: the sum of the workloads' requests (limits where a request is missing), per
    resource; GPU devices summed over every ``nvidia.com/gpu`` or ``nvidia.com/mig-*`` resource. Jobs count."""
    need: dict[str, float] = {}
    for _, spec, reps in pod_specs(state):
        for c in spec.get("containers") or []:
            res = c.get("resources") or {}
            req = {**(res.get("limits") or {}), **(res.get("requests") or {})}
            for k, v in req.items():
                key = "gpu" if GPU_RESOURCE.match(k) else k
                need[key] = need.get(key, 0.0) + quantity(v) * reps
    return need


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
    need = minimum(inp.state)
    if inp.state.source == "compose":
        have_s = inp.env.get("TB_PLATFORM_QUOTA", "")
        hard = {k.strip(): v.strip() for k, _, v in (p.partition("=") for p in have_s.split(",") if p.strip())}
        if not hard:
            return Check(
                "quota", "FAIL", "no TB_PLATFORM_QUOTA (the platform's fixed quota, e.g. gpu=2,cpu=16,memory=96Gi)"
            )
    else:
        quotas = inp.state.of("ResourceQuota")
        if not quotas:
            floor = ", ".join(f"{r} {_fmt(r, n)}" for r, n in sorted(need.items()))
            return Check(
                "quota",
                "FAIL",
                f"no ResourceQuota in the namespace: the platform's fixed quota is the contract "
                f"(profile minimum: {floor})",
            )
        hard = {}
        for q in quotas:
            for k, v in ((q.get("spec") or {}).get("hard") or {}).items():
                hard[k] = v
    have: dict[str, float] = {}
    for k, v in hard.items():
        key = k.removeprefix("requests.").removeprefix("limits.")
        key = "gpu" if GPU_RESOURCE.match(key) else key
        have[key] = max(have.get(key, 0.0), quantity(v))  # requests.* and limits.* both bound: keep one figure
    short, notes = [], []
    for res, n in sorted(need.items()):
        if res == "gpu" and inp.no_gpu:
            notes.append(f"gpu {NO_DEVICE}")
            continue
        if res not in have:
            if inp.state.source == "compose" and res != "gpu":
                notes.append(f"{res}: no figure in TB_PLATFORM_QUOTA")
                continue
            short.append(f"{res}: no quota figure (need {_fmt(res, n)})")
        elif have[res] < n:
            short.append(f"{res}: quota {_fmt(res, have[res])} < profile minimum {_fmt(res, n)}")
    if short:
        return Check("quota", "FAIL", "; ".join(short))
    shown = ", ".join(f"{r} {_fmt(r, have[r])} >= {_fmt(r, n)}" for r, n in sorted(need.items()) if r in have)
    return Check("quota", "PASS", shown + (f"; {'; '.join(notes)}" if notes else ""))


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
    got = sorted(
        {
            f"{_selects(p)}->{hp}"
            for p in pols
            if ((p.get("metadata") or {}).get("labels") or {}).get("trialbox.io/policy") == "egress-allowlist"
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
    return Check(
        "network_policy", "PASS", f"default deny, model isolation; egress allowlist {', '.join(want) or 'empty'}"
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


def check_serving_record(inp: PlatformInputs) -> Check:
    if inp.no_gpu:
        return Check("serving_record", "SKIP", NO_DEVICE)
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


def check_gpu_serving(inp: PlatformInputs) -> Check:
    if inp.no_gpu:
        return Check("gpu_serving", "SKIP", NO_DEVICE)
    gpu_wl = [
        (o, c)
        for o, spec, _ in pod_specs(inp.state)
        for c in spec.get("containers") or []
        if any(
            GPU_RESOURCE.match(k)
            for k in {
                **((c.get("resources") or {}).get("limits") or {}),
                **((c.get("resources") or {}).get("requests") or {}),
            }
        )
    ]
    if not gpu_wl:
        return Check("gpu_serving", "FAIL", "no workload requests a GPU device (the judge and the verifier)")
    if inp.state.source != "cluster":
        return Check(
            "gpu_serving", "PASS", f"{len(gpu_wl)} GPU containers declared ({inp.state.source}; running state not read)"
        )
    down = []
    for o, _ in gpu_wl:
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
    return Check("gpu_serving", "PASS", f"{len(gpu_wl)} GPU containers ready")


def check_canary(inp: PlatformInputs) -> Check:
    if inp.no_gpu:
        return Check("canary", "SKIP", NO_DEVICE)
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
    return PlatformInputs(state, release, penv, no_gpu=no_gpu, routing_path=routing)
