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
* ``backup_job`` (T-633, D-416, OPS-068): the CronJob ``trialbox-backup`` exists (a FAIL in every environment when
  it does not), is not suspended, runs the backup to the backup share claim (labelled
  ``trialbox.io/storage=backup-share``), takes the FHIR store too (``TB_HAPI_DB_URL``), runs in the site's zone
  (``spec.timeZone`` = ``TB_TZ``) and, in a cluster, last succeeded within ``TB_BACKUP_MAX_AGE_HOURS`` (36); the
  restore key Secret is not left in the namespace (D-126). On the compose form: ``TB_PLATFORM_BACKUP_JOB_EVIDENCE``;
* ``log_job`` (T-633): the CronJob ``trialbox-logs`` (pod logs of the site's day, the audit archive) exists, runs
  in the site's zone and, in a cluster, succeeded within two days;
* ``db_storage`` (T-633, OPS-069): the database's claim is ReadWriteOnce on ``TB_PLATFORM_DB_STORAGE_CLASS``, a
  block class that is not the shared ReadWriteMany one, evidenced by ``TB_PLATFORM_DB_STORAGE_EVIDENCE``;
* ``pod_limits`` (T-633, OPS-070): every container states CPU and memory requests and a memory limit (MIG isolates
  the GPU, not the CPU, memory or storage of a shared host);
* ``serving_record``: the ``shared-quota`` serving record (``TB_SERVING_RECORD``) exists, validates and names the
  MIG profile the namespace was given (``TB_MIG_PROFILE``). The profile is measured, never assumed: until T-114's
  record exists this is a FAIL that says so;
* ``host_match`` (T-114, D-428; RSK-52, OPS-071): the host the serving record was taken on (its
  ``host_fingerprint``: GPU, driver, CUDA, VBIOS, MIG layout, kernel, OS, toolkit, vLLM image digest, written by
  ``tools/b200_qualify.py``) against this host: ``TB_PLATFORM_HOST_FINGERPRINT`` (a fingerprint taken on the host),
  else the GPU node's labels and the vLLM images running. A difference is a WARN, never a FAIL: the record was taken
  on the owner's B200, and the site re-measures at IQ; no fingerprint on either side is a WARN that says so;
* ``gpu_serving``: exactly one judge and one verifier workload (``trialbox.io/role``), each with exactly one GPU
  device, no other workload with a GPU, a GPU quota of at least two; in a cluster their pods are ready;
* ``mig_instances`` (D-409, LLM-027): the pair's devices are MIG instances, not a time-slice or an MPS share, and
  there are two. Refused: a shared resource name (``nvidia.com/gpu.shared``, MPS), a node labelled
  ``nvidia.com/gpu.sharing-strategy=time-slicing|mps`` or ``nvidia.com/gpu.replicas`` above 1, a declaration
  ``TB_PLATFORM_GPU_SHARING=time-slicing|mps``; one instance (the nodes offer fewer than the pair needs, or a pair pod
  cannot be scheduled for ``Insufficient nvidia.com/...``) fails with that reason. In ``shared-quota`` MIG must be
  shown: a ``nvidia.com/mig-<profile>`` resource, a node's ``nvidia.com/mig.strategy`` label (the optional
  ``components/node-read`` lets the job read Nodes) or ``TB_PLATFORM_GPU_SHARING=mig`` with
  ``TB_PLATFORM_GPU_EVIDENCE``; and the profiles seen must be the ones ``TB_MIG_PROFILE`` names (one profile, or
  ``judge=<profile>,verifier=<profile>``);
* ``canary``: the last canary result (``TB_CANARY_RESULT``, ``tools/canary.py --out``) passed.
  The four GPU checks are skipped with ``--no-gpu`` (outside VALIDATION and PRODUCTION only). On a test cluster whose
  GPU devices are stand-ins (extended resources advertised by hand, ``TB_PLATFORM_GPU_STANDIN=1``, refused in
  VALIDATION and PRODUCTION like ``--no-gpu``) ``gpu_serving`` and ``mig_instances`` run and ``serving_record`` and
  ``canary`` are ``skipped: stand-in device`` (no model was measured there).

And one check that needs no GPU:

* ``model_key`` (D-177, D-409, LLM-028): both model servers get ``VLLM_API_KEY`` from a Secret, model-guard stands
  in front of them with the same key, the Services the gateway calls (``llm-service``, ``llm-verifier``) select
  model-guard, the gateway holds the key and no other workload does; in a cluster, model-guard answers its health
  check and refuses a call without the key and with another key (401) and an unkeyed vLLM route (404). On the
  compose form: the guard service, the servers' key and their network (the refusal is ``doctor --serving``'s).

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
import urllib.error
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
GPU_RESOURCE = re.compile(r"^(nvidia\.com/gpu|nvidia\.com/mig-[0-9a-z.+-]+)$")
# every GPU resource a device plugin may advertise, the shared ones too (time-slicing renamed, MPS)
GPU_ANY = re.compile(r"^nvidia\.com/(gpu(\.shared)?|mig-[0-9a-z.+-]+|mps[0-9a-z./-]*)$")
SHARED_GPU = re.compile(r"(\.shared$|/mps)")
REQUIRED_POLICIES = ("trialbox-default-deny", "trialbox-model-isolation", "trialbox-model-guard")
STANDIN = "skipped: stand-in device"
WORKLOADS = ("Deployment", "StatefulSet", "Job", "Pod", "DaemonSet", "CronJob")


def _protected_keys() -> tuple[str, ...]:
    """``tb_common.kek.PROTECTED`` (T-210e): the keys the KEK wraps, from the one list that wraps them. The keys of
    ``OPTIONAL`` are in it too: a box may not have made them yet, but where one exists it is never a plain Secret.
    The list is read from this install's ``libs/tb_common/kek.py`` (its literal, not by import), so the host python3
    with no ``PYTHONPATH`` and a stale ``tb_common`` installed elsewhere both get this release's list."""
    import ast

    path = ROOT / "libs" / "tb_common" / "kek.py"
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PROTECTED" for t in node.targets):
            return tuple(str(n) for n in ast.literal_eval(node.value))
    raise ImportError(f"{path} has no PROTECTED list")


def kek_keys_pattern(names: Iterable[str]) -> re.Pattern[str]:
    """A data key, name or annotation that marks a Secret as holding the KEK or one of ``names`` (WS-13.11). An
    underscore of a name may be a dash or left out (``pid-map.key``, ``pidmap.key``)."""
    alts = ["kek", "key[-_]?encryption[-_]?key"]
    alts += [re.escape(n.removesuffix(".key")).replace("_", "[-_]?") + r"\.key" for n in names]
    return re.compile(rf"(^|[^a-z])({'|'.join(alts)})([^a-z]|$)", re.I)


#: the keys the KEK wraps, and the pattern that finds them or the KEK in a platform Secret (built from kek.PROTECTED)
KEK_KEY_NAMES = _protected_keys()
KEK_KEYS = kek_keys_pattern(KEK_KEY_NAMES)


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
MODEL_KEY_VARS = ("VLLM_API_KEY", "TB_LLM_API_KEY")  # D-177: the servers' key and the guard's and gateway's


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
        # D-409: whether the model key is set (never its value) and the networks, for model_key
        env = [
            {"name": k, "value": "<set>" if v else ""}
            for k, v in sorted((svc.get("environment") or {}).items())
            if k in MODEL_KEY_VARS
        ]
        container = {"name": name, "image": svc.get("image", ""), "resources": res, "env": env}
        labels = {"app.kubernetes.io/component": name}
        role = (svc.get("labels") or {}).get("trialbox.io/role") or COMPOSE_ROLES.get(name)
        if role:
            labels["trialbox.io/role"] = role
        nets = ",".join(sorted(svc.get("networks") or {}))
        objs.append(
            {
                "kind": "Deployment",
                "metadata": {"name": name, "labels": labels, "annotations": {"trialbox.io/networks": nets}},
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
        ("Service", "/api/v1/namespaces/{ns}/services"),
        ("PersistentVolumeClaim", "/api/v1/namespaces/{ns}/persistentvolumeclaims"),
        ("Deployment", "/apis/apps/v1/namespaces/{ns}/deployments"),
        ("StatefulSet", "/apis/apps/v1/namespaces/{ns}/statefulsets"),
        ("Job", "/apis/batch/v1/namespaces/{ns}/jobs"),
        ("CronJob", "/apis/batch/v1/namespaces/{ns}/cronjobs"),  # the day-2 jobs (T-633)
        ("NetworkPolicy", "/apis/networking.k8s.io/v1/namespaces/{ns}/networkpolicies"),
    )

    def __init__(self, base: str | None = None, sa: Path | None = None) -> None:
        sa = sa or self.SA
        host, port = os.environ.get("KUBERNETES_SERVICE_HOST", ""), os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        self.base = base or f"https://{host}:{port}"
        self.token = (sa / "token").read_text(encoding="utf-8").strip()
        self.namespace = (sa / "namespace").read_text(encoding="utf-8").strip()
        self.ctx = ssl.create_default_context(cafile=str(sa / "ca.crt"))

    def _get(self, path: str) -> dict[str, Any]:
        req = urllib.request.Request(self.base + path, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, context=self.ctx, timeout=10) as r:
            doc: dict[str, Any] = json.loads(r.read())
        return doc

    def state(self) -> PlatformState:
        objs: list[dict[str, Any]] = []
        for kind, path in self.PATHS:
            doc = self._get(path.format(ns=self.namespace))
            for item in doc.get("items") or []:
                if kind == "Secret":  # never keep a value: names, labels, annotations and data keys only
                    item = {**item, "data": dict.fromkeys(item.get("data") or {}, ""), "stringData": {}}
                item.setdefault("kind", kind)
                objs.append(item)
        try:  # cluster-scoped: only with the optional components/node-read (D-409)
            for item in self._get("/api/v1/nodes").get("items") or []:
                item.setdefault("kind", "Node")
                objs.append(item)
        except urllib.error.HTTPError as e:
            if e.code not in (401, 403, 404):
                raise
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
    gpu_standin: bool = False  # TB_PLATFORM_GPU_STANDIN: the devices are stand-ins (a test cluster, D-409)
    # model_key's live probe: service name -> base URL of model-guard, and the HTTP call (method, url, key, host)
    guard_urls: Mapping[str, str] = field(
        default_factory=lambda: {"llm-service": "http://llm-service:8000", "llm-verifier": "http://llm-verifier:8000"}
    )
    http: Callable[[str, str, str | None, str], int | None] | None = None
    now: datetime | None = None  # the clock of the day-2 checks (the jobs' last success); None: now


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


def _is_backup_share(pvc: Mapping[str, Any]) -> bool:
    """The claim of the hospital's backup share (T-633): what is on it is encrypted to the hospital's key (D-126), so
    it is not held to the encrypted storage class."""
    return ((pvc.get("metadata") or {}).get("labels") or {}).get(STORAGE_LABEL) == BACKUP_SHARE


def _is_db_claim(name: str) -> bool:
    """The database's claim: the template ``db-pg`` and the claims the StatefulSet makes from it (``db-pg-db-0``)."""
    return name == DB_CLAIM or name.startswith(f"{DB_CLAIM}-{DB}-")


def check_storage_encryption(inp: PlatformInputs) -> Check:
    flag = inp.env.get("TB_PLATFORM_STORAGE_ENCRYPTED", "").strip().lower()
    ref = inp.env.get("TB_PLATFORM_STORAGE_EVIDENCE", "").strip()
    cls = inp.env.get("TB_PLATFORM_STORAGE_CLASS", "").strip()
    db_cls = inp.env.get("TB_PLATFORM_DB_STORAGE_CLASS", "").strip() or cls  # OPS-069: block storage for the db
    off = []
    if cls:
        for pvc in inp.state.of("PersistentVolumeClaim"):
            if _is_backup_share(pvc):
                continue
            want = db_cls if _is_db_claim(str((pvc.get("metadata") or {}).get("name") or "")) else cls
            got = (pvc.get("spec") or {}).get("storageClassName")
            if got != want:
                off.append(f"{_name(pvc)} uses {got or 'the default class'}")
        for sts in inp.state.of("StatefulSet"):
            for t in (sts.get("spec") or {}).get("volumeClaimTemplates") or []:
                tname = str((t.get("metadata") or {}).get("name") or "")
                want = db_cls if _is_db_claim(tname) else cls
                if (t.get("spec") or {}).get("storageClassName") != want:
                    off.append(f"{_name(sts)} claim {tname} not on {want}")
    if off:
        return Check("storage_encryption", "FAIL", "claims outside the encrypted classes: " + "; ".join(off[:5]))
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


OPS_POLICY = "trialbox-egress-ops"
OPS_COMPONENT = "logs"


def render_ops_policy(
    env: Mapping[str, str], resolver: Callable[[str], list[str]] | None = None
) -> tuple[dict[str, Any] | None, list[str]]:
    """The log job's egress (T-633): the API server only (``TB_PLATFORM_API_SERVER``), where it lists the pods and
    reads their logs; rendered as the doctor's is. None when the API server is not declared (the job then reaches
    nothing and fails, closed)."""
    res = resolver or _resolve
    rules: list[dict[str, Any]] = []
    hosts: list[str] = []
    warn: list[str] = []
    for v in [v for v in env.get("TB_PLATFORM_API_SERVER", "").split(",") if v.strip()]:
        hp = _hostport(v, 443)
        if not hp:
            continue
        addrs = sorted(res(hp[0]))
        if not addrs:
            warn.append(f"{hp[0]}: does not resolve; log job api-server rule skipped")
            continue
        blocks = [{"ipBlock": {"cidr": f"{a}/{128 if ':' in a else 32}"}} for a in addrs]
        rules.append({"to": blocks, "ports": [{"protocol": "TCP", "port": hp[1]}]})
        hosts.append(f"api-server={hp[0]}:{hp[1]}/TCP")
    if not rules:
        return None, [*warn, "TB_PLATFORM_API_SERVER not declared: the log job gets no api-server rule"]
    pol = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": OPS_POLICY,
            "labels": {"app.kubernetes.io/part-of": "trialbox", "trialbox.io/policy": "ops-egress"},
            "annotations": {"trialbox.io/egress-hosts": ",".join(hosts)},
        },
        "spec": {
            "podSelector": {"matchLabels": {"app.kubernetes.io/component": OPS_COMPONENT}},
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
    for name in ("trialbox-model-isolation", "trialbox-model-guard"):
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
            pol_name = (act.get("metadata") or {}).get("name")
            if exp_doc is None:
                differ.append(f"{pol_name}: the site declares no doctor destination")
            elif _canon((act.get("spec") or {}).get("podSelector")) != _canon(exp_doc["spec"]["podSelector"]):
                differ.append(f"{pol_name}: selects other pods than the doctor")
            elif _blocks(act) != _blocks(exp_doc):
                differ.append(
                    f"{pol_name}: ipBlocks {sorted(_blocks(act) - _blocks(exp_doc)) or '-'} not declared, "
                    f"{sorted(_blocks(exp_doc) - _blocks(act)) or '-'} missing"
                )
        doc_note = "doctor egress as declared"
    ops_pols = [
        p
        for p in pols
        if (p.get("metadata") or {}).get("name") == OPS_POLICY
        or ((p.get("metadata") or {}).get("labels") or {}).get("trialbox.io/policy") == "ops-egress"
    ]
    if ops_pols:  # the log job's egress (T-633): exactly the declared API server
        exp_ops, _ = render_ops_policy(inp.env, res)
        for act in ops_pols:
            pol_name = (act.get("metadata") or {}).get("name")
            if exp_ops is None:
                differ.append(f"{pol_name}: the site declares no API server")
            elif _canon((act.get("spec") or {}).get("podSelector")) != _canon(exp_ops["spec"]["podSelector"]):
                differ.append(f"{pol_name}: selects other pods than the log job")
            elif _blocks(act) != _blocks(exp_ops):
                differ.append(
                    f"{pol_name}: ipBlocks {sorted(_blocks(act) - _blocks(exp_ops)) or '-'} not declared, "
                    f"{sorted(_blocks(exp_ops) - _blocks(act)) or '-'} missing"
                )
        doc_note += "; log job egress as declared"
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
        "default deny, model isolation and model-guard as shipped, no open rule; "
        f"egress allowlist {', '.join(want) or 'empty'}; " + doc_note,
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


# ------------------------------------------------------------------------------------------------ day 2 (T-633)
BACKUP_JOB = "trialbox-backup"
LOG_JOB = "trialbox-logs"
RESTORE_JOB = "trialbox-restore"
RESTORE_KEY_SECRET = "trialbox-backup-restore-key"  # only for a restore, then deleted (D-126: the box never keeps it)
STORAGE_LABEL = "trialbox.io/storage"
BACKUP_SHARE = "backup-share"
DB = "db"
DB_CLAIM = "db-pg"
DEFAULT_BACKUP_MAX_AGE_H = 36.0  # backup_schedule.MAX_AGE_HOURS: the appliance's age alert
LOG_JOB_MAX_AGE_H = 48.0  # a daily job, with a day's slack


def _when(inp: PlatformInputs) -> datetime:
    return inp.now or datetime.now(UTC)


def _parse_time(v: object) -> datetime | None:
    if not v:
        return None
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _commands(spec: Mapping[str, Any]) -> list[str]:
    return [" ".join(map(str, [*(c.get("command") or []), *(c.get("args") or [])])) for c in containers(spec)]


def _cron_problems(cj: Mapping[str, Any], inp: PlatformInputs, max_age_h: float) -> tuple[list[str], list[str]]:
    """What is wrong with a scheduled day-2 job: (failures, warnings). Suspended or without a schedule fails; a
    ``timeZone`` that is not the site's (``TB_TZ``) fails in VALIDATION and PRODUCTION (the job would run at another
    hour, D-315); in a cluster, the last success older than ``max_age_h``, or none since the job was made that long
    ago, likewise."""
    fails: list[str] = []
    warns: list[str] = []
    strict = fails if _strict(inp) else warns
    spec = cj.get("spec") or {}
    name = (cj.get("metadata") or {}).get("name")
    if spec.get("suspend"):
        fails.append(f"{name} is suspended: it never runs")
    if not str(spec.get("schedule") or "").strip():
        fails.append(f"{name} has no schedule")
    site_tz = inp.env.get("TB_TZ", "").strip()
    tz = str(spec.get("timeZone") or "").strip()
    if site_tz and tz != site_tz:
        strict.append(
            f"{name} timeZone is {tz or 'unset (the cluster zone, often UTC)'}, not the site's {site_tz}: the site "
            "overlay sets spec.timeZone (D-315)"
        )
    if inp.state.source == "cluster":
        now = _when(inp)
        last = _parse_time((cj.get("status") or {}).get("lastSuccessfulTime"))
        made = _parse_time((cj.get("metadata") or {}).get("creationTimestamp"))
        if last is not None:
            age = (now - last).total_seconds() / 3600
            if age > max_age_h:
                strict.append(f"{name} last succeeded {age:.0f} h ago (limit {max_age_h:.0f} h)")
        elif made is not None and (now - made).total_seconds() / 3600 > max_age_h:
            strict.append(f"{name} has not succeeded since it was made {(now - made).days} days ago")
        else:
            warns.append(f"{name} has not run yet")
    return fails, warns


def _verdict(name: str, fails: list[str], warns: list[str], ok: str) -> Check:
    if fails:
        return Check(name, "FAIL", "; ".join(fails + warns))
    if warns:
        return Check(name, "WARN", "; ".join(warns))
    return Check(name, "PASS", ok)


def check_backup_job(inp: PlatformInputs) -> Check:
    """The nightly backup on the platform (T-633, OPS-068): the CronJob ``trialbox-backup`` exists, runs, writes to
    the backup share claim, takes the FHIR store too, and has succeeded within ``TB_BACKUP_MAX_AGE_HOURS``; the
    restore key is not left in the namespace. A FAIL in every environment when there is no backup job at all."""
    if inp.state.source == "compose":
        ref = inp.env.get("TB_PLATFORM_BACKUP_JOB_EVIDENCE", "").strip()
        if ref:
            return Check(
                "backup_job", "PASS", f"compose platform: the nightly backup by the platform's declaration {ref}"
            )
        return Check(
            "backup_job",
            "FAIL",
            "compose platform: no backup job declared (TB_PLATFORM_BACKUP_JOB_EVIDENCE: the host's schedule that runs "
            "`trialbox backup-nightly`, RUNBOOK §5)",
        )
    cj = inp.state.named("CronJob", BACKUP_JOB)
    if cj is None:
        return Check(
            "backup_job",
            "FAIL",
            f"no backup job (CronJob {BACKUP_JOB}): nothing backs this namespace up (OPS-068); it is in "
            "deploy/platform/base/day2.yaml (RUNBOOK §26)",
        )
    try:
        max_age = float(inp.env.get("TB_BACKUP_MAX_AGE_HOURS") or DEFAULT_BACKUP_MAX_AGE_H)
    except ValueError:
        max_age = DEFAULT_BACKUP_MAX_AGE_H
    fails, warns = _cron_problems(cj, inp, max_age)
    strict = fails if _strict(inp) else warns
    spec = ((cj.get("spec") or {}).get("jobTemplate") or {}).get("spec", {}).get("template", {}).get("spec") or {}
    if not any("platform-day2 backup" in c or " backup " in f"{c} " for c in _commands(spec)):
        fails.append(f"{BACKUP_JOB} runs no backup command")
    claims = {
        str((v.get("persistentVolumeClaim") or {}).get("claimName"))
        for v in spec.get("volumes") or []
        if v.get("persistentVolumeClaim")
    }
    shares = [p for p in inp.state.of("PersistentVolumeClaim") if _is_backup_share(p)]
    share_names = {str((p.get("metadata") or {}).get("name")) for p in shares}
    if not shares:
        fails.append(f"no backup share claim (a claim labelled {STORAGE_LABEL}={BACKUP_SHARE})")
    elif not claims & share_names:
        fails.append(f"{BACKUP_JOB} does not mount the backup share claim {', '.join(sorted(share_names))}")
    env_names = {str(e.get("name")) for c in containers(spec) for e in c.get("env") or []}
    if "TB_HAPI_DB_URL" not in env_names:
        strict.append("the FHIR store (database hapi) is not in the backup: the job has no TB_HAPI_DB_URL")
    db_secret = inp.state.named("Secret", "trialbox-db")
    if (
        inp.state.source == "cluster"
        and db_secret is not None
        and "TB_HAPI_DB_URL" not in (db_secret.get("data") or {})
    ):
        strict.append("Secret trialbox-db has no TB_HAPI_DB_URL: the FHIR store (database hapi) is not backed up")
    if inp.state.named("Secret", RESTORE_KEY_SECRET) is not None:
        strict.append(
            f"Secret {RESTORE_KEY_SECRET} is in the namespace: the backup private key is there only during a "
            "restore; delete it (D-126: the box never holds the key to its own backups)"
        )
    sched = (cj.get("spec") or {}).get("schedule")
    return _verdict(
        "backup_job",
        fails,
        warns,
        f"{BACKUP_JOB} at {sched!r} ({(cj.get('spec') or {}).get('timeZone')}) to {', '.join(sorted(share_names))}",
    )


def check_log_job(inp: PlatformInputs) -> Check:
    """The daily log collection and audit archive on the platform (T-633, OPS-068): the CronJob ``trialbox-logs``
    exists, runs ``platform-day2 logs`` and has succeeded within two days. Missing is a FAIL in VALIDATION and
    PRODUCTION (the audit's second copy, D-138) and a WARN elsewhere."""
    if inp.state.source == "compose":
        return Check(
            "log_job", "PASS", "compose platform: `trialbox logs daily` runs from the host's cron (RUNBOOK §2)"
        )
    cj = inp.state.named("CronJob", LOG_JOB)
    if cj is None:
        return Check(
            "log_job",
            "FAIL" if _strict(inp) else "WARN",
            f"no log job (CronJob {LOG_JOB}): no pod logs are kept past the platform's rotation and the audit chain "
            "has no archive (D-138; deploy/platform/base/day2.yaml)",
        )
    fails, warns = _cron_problems(cj, inp, LOG_JOB_MAX_AGE_H)
    spec = ((cj.get("spec") or {}).get("jobTemplate") or {}).get("spec", {}).get("template", {}).get("spec") or {}
    if not any("platform-day2 logs" in c for c in _commands(spec)):
        fails.append(f"{LOG_JOB} runs no `platform-day2 logs`")
    return _verdict("log_job", fails, warns, f"{LOG_JOB} at {(cj.get('spec') or {}).get('schedule')!r}")


def check_db_storage(inp: PlatformInputs) -> Check:
    """The database on block storage (OPS-069): the claim template ``db-pg`` is ReadWriteOnce and on
    ``TB_PLATFORM_DB_STORAGE_CLASS``, which is not the shared ReadWriteMany class (a database on a network file
    system is an integrity and speed risk) and is evidenced (``TB_PLATFORM_DB_STORAGE_EVIDENCE``: block, encrypted).
    In a cluster the claim the StatefulSet made is checked too: a claim never moves class by itself."""
    if inp.state.source == "compose":
        return Check("db_storage", "PASS", "compose platform: the db volume is the host's disk (RUNBOOK §17)")
    sts = inp.state.named("StatefulSet", DB)
    tmpl = next(
        (
            t
            for t in ((sts or {}).get("spec") or {}).get("volumeClaimTemplates") or []
            if (t.get("metadata") or {}).get("name") == DB_CLAIM
        ),
        None,
    )
    if tmpl is None:
        return Check("db_storage", "FAIL", f"no StatefulSet {DB} with the claim template {DB_CLAIM}")
    fails: list[str] = []
    warns: list[str] = []
    strict = fails if _strict(inp) else warns
    modes = list((tmpl.get("spec") or {}).get("accessModes") or [])
    if not modes or any(m not in ("ReadWriteOnce", "ReadWriteOncePod") for m in modes):
        fails.append(
            f"the database claim is {', '.join(modes) or 'without an access mode'}: block storage is ReadWriteOnce; "
            "a database on a shared file system is an integrity and speed risk (OPS-069)"
        )
    db_cls = inp.env.get("TB_PLATFORM_DB_STORAGE_CLASS", "").strip()
    shared = inp.env.get("TB_PLATFORM_STORAGE_CLASS", "").strip()
    got = (tmpl.get("spec") or {}).get("storageClassName")
    if not db_cls:
        strict.append("no TB_PLATFORM_DB_STORAGE_CLASS: the block storage class for the database is not named")
    else:
        if got != db_cls:
            fails.append(f"the claim template {DB_CLAIM} uses {got or 'the default class'}, not {db_cls}")
        if db_cls == shared:
            fails.append(f"{db_cls} is also the class of the shared ReadWriteMany claims: a file system, not block")
        if not inp.env.get("TB_PLATFORM_DB_STORAGE_EVIDENCE", "").strip():
            strict.append("no TB_PLATFORM_DB_STORAGE_EVIDENCE (the class's specification: block, encrypted)")
        for pvc in inp.state.of("PersistentVolumeClaim"):
            pname = str((pvc.get("metadata") or {}).get("name") or "")
            if _is_db_claim(pname) and pname != DB_CLAIM:
                pcls = (pvc.get("spec") or {}).get("storageClassName")
                if pcls != db_cls:
                    fails.append(
                        f"the database's claim {pname} was made on {pcls or 'the default class'}: a claim never moves "
                        "class; move the database by backup and restore (RUNBOOK §26)"
                    )
    return _verdict("db_storage", fails, warns, f"{DB_CLAIM}: {', '.join(modes)} on {db_cls}")


def check_pod_limits(inp: PlatformInputs) -> Check:
    """Noisy neighbours (OPS-070): MIG isolates the GPU only, so every container states its CPU and memory requests
    and a memory limit; the platform's scheduler and quota then keep TrialBox's share and keep it from taking more."""
    lack = []
    n = 0
    for owner, spec, _ in pod_specs(inp.state):
        for c in containers(spec):
            n += 1
            res = c.get("resources") or {}
            gaps = [
                f"{kind}.{what}"
                for kind, what in (("requests", "cpu"), ("requests", "memory"), ("limits", "memory"))
                if not (res.get(kind) or {}).get(what)
            ]
            if gaps:
                lack.append(f"{_name(owner)} {c.get('name')}: no {', '.join(gaps)}")
    if lack:
        return Check(
            "pod_limits",
            "FAIL" if _strict(inp) else "WARN",
            "on a shared host every container states requests and a memory limit (OPS-070): " + "; ".join(lack[:6]),
        )
    return Check("pod_limits", "PASS", f"{n} containers state CPU and memory requests and a memory limit")


NO_GPU_REFUSED = (
    "--no-gpu (TB_PLATFORM_NO_GPU) is refused in VALIDATION and PRODUCTION: the GPU checks never skip there"
)
STANDIN_REFUSED = (
    "TB_PLATFORM_GPU_STANDIN is refused in VALIDATION and PRODUCTION: stand-in devices are for a test cluster only"
)


def _gpu_skipped(inp: PlatformInputs, name: str) -> Check | None:
    """SKIP for a GPU check under ``--no-gpu``, except in VALIDATION and PRODUCTION, where it is a FAIL: there the
    evidence can never say ``passed`` without the GPU checks."""
    if not inp.no_gpu:
        return None
    if _strict(inp):
        return Check(name, "FAIL", NO_GPU_REFUSED)
    return Check(name, "SKIP", NO_DEVICE)


def _measured_skipped(inp: PlatformInputs, name: str) -> Check | None:
    """A check that needs a model measured on the device: skipped on stand-in devices (refused where strict)."""
    if (skipped := _gpu_skipped(inp, name)) is not None:
        return skipped
    if inp.gpu_standin:
        return Check(name, "FAIL", STANDIN_REFUSED) if _strict(inp) else Check(name, "SKIP", STANDIN)
    return None


def check_serving_record(inp: PlatformInputs) -> Check:
    if (skipped := _measured_skipped(inp, "serving_record")) is not None:
        return skipped
    from tools import serving_config as sc

    path = inp.env.get("TB_SERVING_RECORD", "").strip()
    mig = inp.env.get("TB_MIG_PROFILE", "").strip()
    if inp.env.get("TB_GPU_PROFILE", "").strip() == "shared-quota" and path and Path(path).is_file():
        return _shared_quota_record(path, mig)
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


def _shared_quota_record(path: str, mig: str) -> Check:
    """D-409: the shared-quota record is a measurement on two MIG instances (``serving_config.measured_for``, the rule
    keyed on each instance's MIG profile) of the layout this namespace was given (``TB_MIG_PROFILE``)."""
    from tools import serving_config as sc

    rec = json.loads(Path(path).read_text(encoding="utf-8"))
    why = sc.measured_for(rec, "shared-quota")
    try:
        want = sc.mig_layout(mig)
    except ValueError as e:
        want, why = {}, [*why, f"TB_MIG_PROFILE: {e}"]
    got = sc.record_layout(rec)
    if not want:
        why.append("TB_MIG_PROFILE is not set to the MIG instances the namespace was given")
    for role, prof in sorted(want.items()):
        if role in got and sc.mig_base(got[role]) != sc.mig_base(prof):
            why.append(f"the record's {role} ran on MIG profile {got[role]}, this namespace's is {prof}")
    if why:
        return Check("serving_record", "FAIL", f"{path}: " + "; ".join(why))
    card = rec.get("card") or {}
    lay = ", ".join(f"{r} {p}" for r, p in sorted(got.items()))
    what = f"{card.get('name')} {lay}, driver {card.get('driver')}, CUDA {card.get('cuda')}"
    return Check("serving_record", "PASS", f"{path}: {what}")


def _host_here(inp: PlatformInputs) -> tuple[dict[str, Any], str]:
    """This host's fingerprint for ``host_match``, and where it came from."""
    from tools import b200_qualify as bq

    path = inp.env.get("TB_PLATFORM_HOST_FINGERPRINT", "").strip()
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8")), f"TB_PLATFORM_HOST_FINGERPRINT {path}"
    images = sorted(
        {
            str(c.get("image"))
            for _, spec, _ in pod_specs(inp.state)
            for c in containers(spec)
            if "vllm" in str(c.get("image"))
        }
    )
    node = next(
        (
            n
            for n in inp.state.of("Node")
            if ((n.get("metadata") or {}).get("labels") or {}).get("nvidia.com/gpu.product")
        ),
        None,
    )
    if node is not None:
        return bq.fingerprint_from_node(node, images), f"node {(node.get('metadata') or {}).get('name')} labels"
    if any("@sha256:" in i for i in images):
        return {"vllm_image_digests": images}, "the running vLLM images only (no GPU node labels)"
    return {}, ""


def check_host_match(inp: PlatformInputs) -> Check:
    if (skipped := _measured_skipped(inp, "host_match")) is not None:
        return skipped
    from tools import b200_qualify as bq

    path = inp.env.get("TB_SERVING_RECORD", "").strip()
    rec = json.loads(Path(path).read_text(encoding="utf-8")) if path and Path(path).is_file() else {}
    recorded = rec.get("host_fingerprint") or {}
    if not recorded:
        return Check(
            "host_match",
            "WARN",
            f"{path or 'TB_SERVING_RECORD unset'}: no host fingerprint in the serving record, so whether this host is "
            "the one measured is unknown (T-114: tools/b200_qualify.sh stamps it)",
        )
    here, source = _host_here(inp)
    if not here:
        return Check(
            "host_match",
            "WARN",
            "this host's fingerprint is unknown: set TB_PLATFORM_HOST_FINGERPRINT (`python3 -m tools.b200_qualify "
            "fingerprint` on the host) or let the doctor read Nodes (components/node-read)",
        )
    diffs, seen = bq.compare(recorded, here)
    if not seen:
        return Check("host_match", "WARN", f"nothing to compare between the record and this host ({source})")
    if diffs:
        return Check(
            "host_match",
            "WARN",
            f"this host differs from the one the serving record was measured on ({source}): "
            + "; ".join(diffs)
            + ". The record does not predict this host: re-measure here (RSK-52)",
        )
    return Check("host_match", "PASS", f"matches the measured host on {', '.join(seen)} ({source})")


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


# ------------------------------------------------------------------------------------------------ MIG (D-409)
MIG_STRATEGY_LABEL = "nvidia.com/mig.strategy"
SHARING_LABEL = "nvidia.com/gpu.sharing-strategy"
REPLICAS_LABEL = "nvidia.com/gpu.replicas"
PRODUCT_LABEL = "nvidia.com/gpu.product"
TWO_INSTANCES = "the judge and the verifier each need their own MIG instance: ask for two (LLM-027, D-409)"


def _gpu_names(spec: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for c in containers(spec):
        res = c.get("resources") or {}
        for part in ("requests", "limits"):
            out |= {k for k, v in (res.get(part) or {}).items() if GPU_ANY.match(k) and quantity(v) > 0}
    return out


def _pair_specs(state: PlatformState) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    pair: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for owner, spec, _ in pod_specs(state):
        role = _role(owner)
        if role in GPU_ROLES:
            pair.setdefault(role, (owner, spec))
    return pair


def _component(owner: Mapping[str, Any]) -> str:
    tmpl = (((owner.get("spec") or {}).get("template") or {}).get("metadata") or {}).get("labels") or {}
    return str(
        tmpl.get("app.kubernetes.io/component")
        or ((owner.get("metadata") or {}).get("labels") or {}).get("app.kubernetes.io/component")
        or ""
    )


def _pods_of(state: PlatformState, component: str) -> list[dict[str, Any]]:
    return [
        p
        for p in state.of("Pod")
        if ((p.get("metadata") or {}).get("labels") or {}).get("app.kubernetes.io/component") == component
    ]


def check_mig_instances(inp: PlatformInputs) -> Check:
    """MIG instance, not time-sliced, and two of them (D-409; LLM-027, OPS-067)."""
    if (skipped := _gpu_skipped(inp, "mig_instances")) is not None:
        return skipped
    from tools import serving_config as sc

    need_mig = inp.env.get("TB_GPU_PROFILE", "").strip() == "shared-quota"
    pair = _pair_specs(inp.state)
    if set(pair) != set(GPU_ROLES):
        return Check("mig_instances", "FAIL", f"no judge and verifier pair declared (found {sorted(pair) or 'none'})")
    bad: list[str] = []
    evidence: list[str] = []
    names = {role: sorted(_gpu_names(spec)) for role, (_, spec) in pair.items()}
    seen: dict[str, str] = {}  # role -> MIG profile seen on the platform
    for role, ns in sorted(names.items()):
        if not ns:
            bad.append(f"the {role} asks for no GPU device")
        for n in ns:
            if SHARED_GPU.search(n):
                bad.append(f"the {role} asks for {n}: a time-sliced or MPS share, no memory isolation (refused)")
            elif n.startswith("nvidia.com/mig-"):
                seen[role] = n.removeprefix("nvidia.com/mig-")
                evidence.append(f"{role} on {n}")
    sharing = inp.env.get("TB_PLATFORM_GPU_SHARING", "").strip().lower()
    ref = inp.env.get("TB_PLATFORM_GPU_EVIDENCE", "").strip()
    if sharing in ("time-slicing", "time-sliced", "timeslicing", "mps"):
        bad.append(f"the platform declares TB_PLATFORM_GPU_SHARING={sharing}: no memory isolation (refused)")
    declared_mig = sharing == "mig" and bool(ref)
    if declared_mig:
        evidence.append(f"declared mig ({ref})")
    elif sharing == "mig":
        bad.append("TB_PLATFORM_GPU_SHARING=mig without TB_PLATFORM_GPU_EVIDENCE (the MIG configuration dump)")
    # the nodes (with components/node-read, or given with --manifests): the ones the pair's pods run on, else all
    on = {
        str((p.get("spec") or {}).get("nodeName"))
        for owner, _ in pair.values()
        for p in _pods_of(inp.state, _component(owner))
        if (p.get("spec") or {}).get("nodeName")
    }
    nodes = [nd for nd in inp.state.of("Node") if not on or (nd.get("metadata") or {}).get("name") in on]
    gpu_nodes = [nd for nd in nodes if any(GPU_ANY.match(k) for k in ((nd.get("status") or {}).get("capacity") or {}))]
    node_mig = False
    avail: dict[str, float] = {}
    for node in gpu_nodes:
        nm = (node.get("metadata") or {}).get("name")
        lab = (node.get("metadata") or {}).get("labels") or {}
        strategy, how = lab.get(MIG_STRATEGY_LABEL, ""), lab.get(SHARING_LABEL, "")
        if how in ("time-slicing", "mps"):
            bad.append(f"node {nm}: {SHARING_LABEL}={how} (a shared device, no memory isolation)")
        reps = str(lab.get(REPLICAS_LABEL, ""))
        if reps.isdigit() and int(reps) > 1:
            bad.append(f"node {nm}: {REPLICAS_LABEL}={reps} (each device is handed out {reps} times: time-sliced)")
        if strategy in ("single", "mixed"):
            node_mig = True
            evidence.append(f"node {nm} {MIG_STRATEGY_LABEL}={strategy}")
            m = re.search(r"MIG-(\d+g\.\d+gb(\+me)?)$", str(lab.get(PRODUCT_LABEL, "")))
            if strategy == "single" and m:
                for role, ns in names.items():
                    if "nvidia.com/gpu" in ns:
                        seen.setdefault(role, m.group(1))
        elif need_mig:
            bad.append(f"node {nm}: no {MIG_STRATEGY_LABEL} label: MIG is off there (a whole card or a time-slice)")
        for k, v in ((node.get("status") or {}).get("allocatable") or {}).items():
            if GPU_ANY.match(k):
                avail[k] = avail.get(k, 0.0) + quantity(v)
    if gpu_nodes:  # enough instances of each resource the pair asks for
        want: dict[str, int] = {}
        for ns in names.values():
            for k in ns:
                want[k] = want.get(k, 0) + 1
        for k, need in sorted(want.items()):
            have = int(avail.get(k, 0))
            if have < need:
                bad.append(f"the nodes offer {have} {k} for the pair's {need}: {TWO_INSTANCES}")
    elif inp.state.source == "cluster":
        evidence.append("nodes not readable (components/node-read not granted)")
    for role, (owner, _) in sorted(pair.items()):
        for p in _pods_of(inp.state, _component(owner)):
            for c in (p.get("status") or {}).get("conditions") or []:
                msg = str(c.get("message") or "")
                if c.get("type") == "PodScheduled" and c.get("status") == "False" and "Insufficient nvidia.com/" in msg:
                    pod = (p.get("metadata") or {}).get("name")
                    bad.append(f"the {role} pod {pod} cannot be scheduled ({msg.strip()}): {TWO_INSTANCES}")
    is_mig = bool(seen) or node_mig or declared_mig
    if need_mig and not is_mig:
        bad.append(
            "not shown to be MIG instances: no nvidia.com/mig-<profile> resource, no node with "
            f"{MIG_STRATEGY_LABEL} (components/node-read) and no TB_PLATFORM_GPU_SHARING=mig with "
            "TB_PLATFORM_GPU_EVIDENCE"
        )
    try:
        layout = sc.mig_layout(inp.env.get("TB_MIG_PROFILE", ""))
    except ValueError as e:
        layout = {}
        bad.append(f"TB_MIG_PROFILE: {e}")
    if need_mig and not layout:
        bad.append("TB_MIG_PROFILE does not name the instances the namespace was given")
    for role, prof in sorted(seen.items()):
        if layout.get(role) and sc.mig_base(layout[role]) != sc.mig_base(prof):
            bad.append(f"the {role} is on MIG profile {prof}, TB_MIG_PROFILE says {layout[role]}")
    if bad:
        return Check("mig_instances", "FAIL", "; ".join(bad))
    if not is_mig:
        how = "not declared (TB_PLATFORM_GPU_SHARING)" if not sharing else f"declared {sharing}"
        return Check(
            "mig_instances",
            "WARN" if not sharing else "PASS",
            f"whole devices, not MIG; no time-slice seen; sharing {how}",
        )
    lay = ", ".join(f"{r} {p}" for r, p in sorted((layout or seen).items()))
    return Check("mig_instances", "PASS", f"two MIG instances ({lay}), not time-sliced: " + "; ".join(evidence))


# ------------------------------------------------------------------------------------------------ model key (D-409)
MODEL_KEY_SECRET = "trialbox-model-key"
GUARD = "model-guard"
WRONG_KEY = "doctor-probe-not-the-key"


def _key_refs(c: Mapping[str, Any]) -> dict[str, str]:
    """``{env var: "secret/key" | "<literal>" | "<set>"}`` for the model key variables of one container."""
    out: dict[str, str] = {}
    for e in c.get("env") or []:
        if e.get("name") in MODEL_KEY_VARS:
            sk = (e.get("valueFrom") or {}).get("secretKeyRef")
            if sk:
                out[e["name"]] = f"{sk.get('name')}/{sk.get('key')}"
            elif e.get("value") == "<set>":
                out[e["name"]] = "<set>"
            elif e.get("value"):
                out[e["name"]] = "<literal>"
    return out


def _uses_secret(spec: Mapping[str, Any], secret: str) -> bool:
    for v in spec.get("volumes") or []:
        if (v.get("secret") or {}).get("secretName") == secret:
            return True
    for c in containers(spec):
        for e in c.get("env") or []:
            if ((e.get("valueFrom") or {}).get("secretKeyRef") or {}).get("name") == secret:
                return True
        for ef in c.get("envFrom") or []:
            if (ef.get("secretRef") or {}).get("name") == secret:
                return True
    return False


def _http_status(method: str, url: str, key: str | None, host: str) -> int | None:
    """HTTP status of one call (never following a redirect), None when nothing answers."""
    from tools.trialbox.doctor import _NoRedirect

    headers = {"Host": host}
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    data = b"{}" if method == "POST" else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=10) as r:
            return int(r.status)
    except urllib.error.HTTPError as e:
        return int(e.code)
    except (OSError, ValueError):
        return None


def _probe_guard(inp: PlatformInputs) -> tuple[list[str], list[str]]:
    """In the cluster: model-guard is up and refuses a call without the key, with another key, and on vLLM's
    unkeyed routes. The doctor holds no key, so a call with the right key is the gateway's to make (canary)."""
    call = inp.http or _http_status
    bad, good = [], []
    for name, base in sorted(inp.guard_urls.items()):
        base = base.rstrip("/")
        up = call("GET", base + "/healthz", None, name)
        if up != 200:
            bad.append(f"{name}: model-guard not reachable ({'no answer' if up is None else f'HTTP {up}'})")
            continue
        no_key = call("GET", base + "/v1/models", None, name)
        wrong = call("GET", base + "/v1/models", WRONG_KEY, name)
        unkeyed = call("POST", base + "/invocations", None, name)
        if no_key not in (401, 403):
            bad.append(f"{name}: a call without the key answered {no_key} (must be refused 401)")
        if wrong not in (401, 403):
            bad.append(f"{name}: a call with another key answered {wrong} (must be refused 401)")
        if unkeyed not in (401, 403, 404, 405):
            bad.append(f"{name}: POST /invocations without the key answered {unkeyed} (vLLM's unkeyed route is open)")
        if no_key in (401, 403) and wrong in (401, 403) and unkeyed in (401, 403, 404, 405):
            good.append(f"{name} refuses without the key ({no_key})")
    return bad, good


def check_model_key(inp: PlatformInputs) -> Check:
    """The model servers refuse a call without the key, and only the gateway holds it (D-177, D-409; LLM-028)."""
    bad: list[str] = []
    refs: set[str] = set()
    pair = _pair_specs(inp.state)
    if not pair:
        return Check("model_key", "WARN", "no model server declared: nothing to check")
    for role, (owner, spec) in sorted(pair.items()):
        for c in spec.get("containers") or []:
            got = _key_refs(c).get("VLLM_API_KEY")
            if not got:
                bad.append(f"the {role} {_name(owner)} runs without VLLM_API_KEY (vLLM answers /v1 without a key)")
            elif got == "<literal>":
                bad.append(f"the {role} {_name(owner)}: VLLM_API_KEY is a plain value in the manifest, not a Secret")
            else:
                refs.add(got)
    guards = [(o, sp) for o, sp, _ in pod_specs(inp.state) if _component(o) == GUARD]
    if not guards:
        bad.append(
            "no model-guard in front of the model servers: vLLM answers /invocations, /tokenize and /metrics "
            "without its key (D-177)"
        )
    gates = [(o, sp) for o, sp, _ in pod_specs(inp.state) if _component(o) == "gateway"]
    for what, objs in (("model-guard", guards), ("the gateway", gates)):
        for o, sp in objs:
            got = next((r for c in sp.get("containers") or [] if (r := _key_refs(c).get("TB_LLM_API_KEY"))), None)
            if not got or got == "<literal>":
                why = "every model call would be refused 401" if what == "the gateway" else "it would not start"
                bad.append(f"{what} ({_name(o)}) holds no TB_LLM_API_KEY from a Secret: {why}")
            else:
                refs.add(got)
    secrets = {r.split("/", 1)[0] for r in refs if "/" in r}
    if len(refs) > 1:
        bad.append(f"the servers, model-guard and the gateway do not read one key: {sorted(refs)}")
    if inp.state.source == "compose":
        for role, (owner, _) in sorted(pair.items()):
            nets = str(((owner.get("metadata") or {}).get("annotations") or {}).get("trialbox.io/networks", ""))
            if "model-net" in nets.split(","):
                bad.append(f"the {role} ({_name(owner)}) is on model-net: the gateway reaches it around model-guard")
    else:
        allowed = {id(o) for o, _ in [*pair.values(), *guards, *gates]}
        for o, sp, _ in pod_specs(inp.state):
            if id(o) not in allowed and any(_uses_secret(sp, sec) for sec in secrets):
                bad.append(f"{_name(o)} also holds the model key")
        for svc_name in ("llm-service", "llm-verifier"):
            svc = inp.state.named("Service", svc_name)
            sel = ((svc or {}).get("spec") or {}).get("selector") or {}
            if svc is not None and sel.get("app.kubernetes.io/component") != GUARD:
                bad.append(
                    f"Service {svc_name} selects {sel}: the gateway would reach the model server around model-guard"
                )
    if bad:
        return Check("model_key", "FAIL", "; ".join(bad))
    if inp.state.source != "cluster":
        how = "doctor --serving on the box network" if inp.state.source == "compose" else "the doctor job"
        return Check(
            "model_key",
            "PASS",
            f"declared: the servers, model-guard and the gateway read {', '.join(sorted(refs))}; nothing else "
            f"holds it ({inp.state.source}; the refusal is probed by {how})",
        )
    live_bad, good = _probe_guard(inp)
    if live_bad:
        return Check("model_key", "FAIL", "; ".join(live_bad))
    return Check("model_key", "PASS", "; ".join(good) + f"; key {', '.join(sorted(refs))}, held by the gateway only")


def check_canary(inp: PlatformInputs) -> Check:
    if (skipped := _measured_skipped(inp, "canary")) is not None:
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
    check_backup_job,
    check_log_job,
    check_db_storage,
    check_pod_limits,
    check_serving_record,
    check_host_match,
    check_gpu_serving,
    check_mig_instances,
    check_canary,
    check_model_key,
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
        "gpu_standin": inp.gpu_standin,
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
    standin = penv.get("TB_PLATFORM_GPU_STANDIN", "") in ("1", "true", "yes")  # kind with advertised devices
    inp = PlatformInputs(state, release, penv, no_gpu=no_gpu, routing_path=routing, gpu_standin=standin)
    if no_gpu and _strict(inp):
        raise PlatformError(f"{NO_GPU_REFUSED} (TB_ENV={penv.get('TB_ENV', 'PRODUCTION')})")
    if standin and _strict(inp):
        raise PlatformError(f"{STANDIN_REFUSED} (TB_ENV={penv.get('TB_ENV', 'PRODUCTION')})")
    return inp
