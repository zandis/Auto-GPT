"""``trialbox eval qualify``: one command qualifies a model pair for a hardware profile and writes the record (D-313).

    python -m tools.trialbox eval qualify --profile ci --stub                  # the stub pair, in process (CI, tests)
    python -m tools.trialbox eval qualify --profile rtxpro6000 --gateway-url http://127.0.0.1:8010/v1 \\
        --model-dir judge=<weights> --model-dir verifier=<weights> --server-log <vllm log> \\
        --evidence n12=<file> --evidence public_e2e=<file> --evidence goldens=<file> --operator <name>
    python -m tools.qualify --check <record.json> [--profile P] [--environment PRODUCTION]

Every call goes through tb-gateway, as the box sends it: the judge on alias ``j-workhorse`` and the verifier on
``v-verifier`` (``--stub``: an in-process gateway in TEST in front of ``services/llm_stub``, both roles on the stub
build). The steps, in order (:data:`STEPS`); each one ends ``passed`` or ``failed`` with a reason:

* ``pin``: the profile's two builds from ``models/registry.yaml``, their served names and weight hashes (the stub's
  are ``synthetic``); the gateway lists both aliases; every answer carries the pinned build (``tb.build_sha``); two
  different builds for judge and verifier (the stub pair is one build: allowed on ``ci`` only);
* ``serving_record``: git HEAD and whether the tree is clean, driver and CUDA versions (``nvidia-smi``), the routing,
  registry and prompt-registry versions, and the active prompt set with each text and schema sha;
* ``licence``: each build's licence row is verified in the registry and backed by its row of
  ``docs/licences/register.csv`` (same repository and SPDX id, cleared; T-617b); for real weights the weight folder
  (``--model-dir``) holds a licence file, and when the register row has the text's sha256 the file is that text. A
  build whose source holds no licence file (``provenance.licence_file: none-in-source``; HW-004, D-565) is checked
  against the register row alone (it names the build's revision and a source URL); its text rides beside the
  folder, in ``<models root>/licences/<weight folder's name>/``, outside the pinned manifest;
* ``schema``: every prompt of the active set is sent once with an adversarial line in its data
  (``eval/qualification/schema_probes.yaml``); 100 % must be valid on the first attempt and not cut off (LLM-020);
* ``longest_prompt``: the longest prompt the product sends per role (the judge's full-record fallback, the uploaded
  chart, both sized from the profile's context since T-603) must fit the profile's context with the prompt's
  ``max_tokens``, and is sent and answered (LLM-015);
* ``log_marker``: a marker string is planted in a note excerpt; after the call it must not be found in the gateway's
  audit files, in the logs of this process or in any ``--server-log`` (the model server's container log; LLM-042);
* ``canary``: the 54-case pair canary (``orchestrator.selftest``), reported by model name;
* ``pair_gate``: PR #64's judge gate in pair mode: each item put to judge and verifier through the gateway and
  combined with ``tb_common.pair.combine``, scored by :func:`tools.judge_bakeoff.metrics` (LLM-031);
* ``determinism``: the same items twice at concurrency 16, no response cache: 0 changed exclusions; the share of
  changed verdicts is reported (LLM-021);
* ``throughput``: the two numbers of LLM-025 from the pair run: seconds per note-stage patient and seconds per
  criterion check, p50 and p95;
* ``injection``: the prompt-injection and false-positive suite (``eval/injection/cases.yaml``,
  :mod:`tools.injection_eval`; T-208, D-346): the judge and verifier as the pair, the judge build as the reader of
  charts, consent forms and protocols; 0 changed facts over the attacks and at most 2 % false positives on the
  controls (the stub must also give every expected fact);
* ``n12``, ``public_e2e``, ``goldens``: evidence steps: a JSON result (``--evidence step=file``) written at this git
  HEAD with ``passed`` or ``ok`` true. With ``--stub`` (profile ``ci`` only) they run in wiring form: the tool's
  command answers ``--help``, and the record says so;
* ``planted_defect``: the same pair with a planted defect (every decided verdict flipped) must fail both the canary
  and the pair gate; a qualification that cannot see a broken model proves nothing.

The ``n12`` evidence must say ``"basis": "unadjusted"``: the gate figure is the raw one (D-343, REG-030). Every
record cites the model change protocol (``docs/validation/model-change-protocol.md``): its path, the sha256 of its
text and the change id qualified (``--change``, default ``MC-0``, a first qualification).

The record (``schemas/qualification_record.schema.json``) is ``failed`` unless every step of :data:`STEPS` is in it
and ``passed``; :func:`check_record` recomputes that, the body sha256 and the profile, and refuses synthetic weights
for PRODUCTION. Records go to ``eval/qualification/`` (``--stub``: ``.cache/qualification/``). No note text, prompt
or answer is written: hashes, counts and verdict codes only. Exit 0 passed, 1 failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

import yaml  # noqa: E402
from tb_common.llm import LlmClient, LlmError, LlmResult  # noqa: E402

from tools import licence_register  # noqa: E402

RECORD_SCHEMA = ROOT / "schemas" / "qualification_record.schema.json"
RECORD_FORMAT = "qualification-record/1"
OUT_DIR = ROOT / "eval" / "qualification"
STUB_OUT_DIR = ROOT / ".cache" / "qualification"
PROBES = ROOT / "eval" / "qualification" / "schema_probes.yaml"
# the model change protocol every record cites (T-649b, D-343): the change ids of its table "Foreseen changes"
CHANGE_PROTOCOL = ROOT / "docs" / "validation" / "model-change-protocol.md"
CHANGE_TYPES = ("MC-0", "MC-1", "MC-2", "MC-3", "MC-4", "MC-5", "MC-6", "MC-7", "MC-8")
STEPS = (
    "pin",
    "serving_record",
    "licence",
    "schema",
    "longest_prompt",
    "log_marker",
    "canary",
    "pair_gate",
    "determinism",
    "throughput",
    "injection",
    "n12",
    "public_e2e",
    "goldens",
    "planted_defect",
)
EVIDENCE_STEPS = {
    "n12": ["-m", "tools.n12_screen", "--help"],  # D-826: N-12 from SCREEN (lane A2's tool), not the benchmark path
    "public_e2e": ["-m", "tools.public_e2e", "--help"],
    "goldens": ["-m", "tools.goldens", "--help"],
}
# hardware profile -> the suffix of its builds in models/registry.yaml (``ci``: the stub pair)
PROFILES = {"ci": "", "rtxpro6000": "rtxpro6000", "gb10": "spark", "rtx5090": "rtx5090", "shared-quota": "shared-quota"}
JUDGE_ALIAS, VERIFIER_ALIAS = "j-workhorse", "v-verifier"
STUB_BUILD = "trialbox-stub-1"
# the verifier of the ci pair: the stub under its second served name, so the pair is two models (D-276)
STUB_VERIFIER_BUILD = "stub-verifier-1"
STUB_VERIFIER_ALIAS = "stub-verifier"
SYNTHETIC = "synthetic"
CALLER = "orchestrator"  # the product's caller for the note judge (models/routing.yaml)
PROBE_CALLER = "testbench"
REPEAT_WORKERS = 16
# the deterministic stub's canary result (services/llm_stub on the orchestrator/selftest cases): it answers every case
# "unknown", so it fails the canary; on profile ci the step passes only on exactly this result
STUB_CANARY: dict[str, Any] = {
    "cases": 54,
    "judge": {"answered": 54, "correct": 18},
    "verifier": {"answered": 54, "correct": 18},
    "pair_decided_wrong": 0,
}
LICENCE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md", "license.txt", "COPYING")
# HW-004 (D-565): a registry row whose `provenance.licence_file` is this names a source repository that holds no
# licence file. The expected manifest is every visible file of that source, so a licence file put into the weight
# folder breaks the pin: the licence step reads the register row, and the text rides beside the folder, in
# <models root>/licences/<weight folder's name>/, outside the manifest (as the chat template does).
NONE_IN_SOURCE = "none-in-source"
NONE_IN_SOURCE_FILE = "none in source (register row)"
LICENCE_BESIDE = "licences"
_FULL_REVISION = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")
_tl = threading.local()


class QualifyError(RuntimeError):
    """A usage error: the command cannot start (exit 2)."""


# ---------------------------------------------------------------------------------------------------- clients
class QClient(LlmClient):
    """``tb_common.llm.LlmClient`` through the gateway, as the box calls it, that also keeps what the gateway says
    about each answer (build, cache, latency) in a thread-local list. Qualification data is synthetic: class D0.
    ``defect``: every decided verdict is flipped (the planted-defect run)."""

    def __init__(self, gateway: Any, *, alias: str | None, name: str = "", defect: bool = False) -> None:
        # ``name`` (the build id) is what the canary reports; the gateway drops a body's model and asks for ``alias``
        super().__init__("http://unused.invalid", name or alias or "", gateway=gateway)
        self.alias = alias
        self.defect = defect

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        kw["data_class"] = "D0"
        res = super().chat_json(prompt_id, variables, schema, **kw)
        calls = _calls()
        if calls:
            calls[-1]["data"] = res.data
            calls[-1]["attempts"] = res.attempts
        if self.defect and res.data.get("verdict") in ("pass", "fail"):
            flipped = {**res.data, "verdict": "fail" if res.data["verdict"] == "pass" else "pass"}
            return replace(res, data=flipped)
        return res

    def _via_gateway(self, body: dict[str, Any], prompt: Any, job_id: str | None, data_class: str | None) -> Any:
        t0 = time.perf_counter()
        payload = super()._via_gateway(body, prompt, job_id, data_class)
        tb = payload.get("tb") or {}
        usage = payload.get("usage") or {}
        _calls().append(
            {
                "s": time.perf_counter() - t0,
                "alias": str(tb.get("alias") or ""),
                "build_id": str(tb.get("build_id") or ""),
                "build_sha": str(tb.get("build_sha") or ""),
                "cache": str(tb.get("cache") or ""),
                "finish": str((payload.get("choices") or [{}])[0].get("finish_reason") or ""),
                "in": int(usage.get("prompt_tokens") or 0),
                "out": int(usage.get("completion_tokens") or 0),
            }
        )
        return payload


def _calls() -> list[dict[str, Any]]:
    if not hasattr(_tl, "calls"):
        _tl.calls = []
    out: list[dict[str, Any]] = _tl.calls
    return out


@dataclass
class Target:
    """Where the calls go: an HTTP client for the gateway (in-process or live) and the audit folders it writes."""

    base_url: str
    http: Any
    audit_dirs: list[Path]
    live: bool

    def gateway(self, caller: str = CALLER, model: str | None = None) -> Any:
        from tb_llm import GatewayClient

        return GatewayClient(self.base_url, caller, http=self.http, model=model)

    def models(self) -> list[str]:
        from tb_common.service_auth import auth_headers

        resp = self.http.get(f"{self.base_url}/models", headers=auth_headers())
        resp.raise_for_status()
        return [str(m.get("id")) for m in resp.json().get("data") or []]


def stub_target(work: Path, upstream: Any = None) -> Target:
    """An in-process tb-gateway (TEST, no response cache) in front of the in-process ``llm_stub`` (``upstream``:
    another HTTP client for the model server, for tests)."""
    from fastapi.testclient import TestClient
    from gateway.app import create_app
    from gateway.core import Gateway, GatewayConfig
    from gateway.policy import RoutingPolicy
    from guard.guard import Guard
    from llm_stub.app import app as stub
    from registry.registry import Registry
    from tb_common.audit import AuditLog
    from tb_common.policy.classes import Environment, Topology

    audit = work / "audit"
    gw = Gateway(
        RoutingPolicy.load(),
        Registry.load(),
        AuditLog(audit),
        GatewayConfig(topology=Topology.A, environment=Environment.TEST),
        http=upstream or TestClient(stub),
        guard=Guard(None),
        env={},
        cache_size=0,
    )
    return Target("http://testserver/v1", TestClient(create_app(gw)), [audit], live=False)


def live_target(url: str, audit_dirs: list[Path]) -> Target:
    import httpx

    return Target(url.rstrip("/"), httpx.Client(timeout=600.0, trust_env=False), audit_dirs, live=True)


# ---------------------------------------------------------------------------------------------------- context
@dataclass
class Build:
    role: str
    build_id: str
    alias: str
    served: str
    weights_sha256: str
    revision: str | None
    context_length: int | None
    licence: dict[str, Any]
    status: str
    repository: str | None = None
    licence_file: Any = None  # the registry row's provenance.licence_file: {path, sha256}, NONE_IN_SOURCE or None


@dataclass
class Options:
    profile: str
    stub: bool
    operator: str
    sources: tuple[str, ...]
    items: int = 0  # 0: every item of the sources
    repeat_items: int = 200
    workers: int = 4
    model_dirs: dict[str, Path] = field(default_factory=dict)
    server_logs: list[Path] = field(default_factory=list)
    evidence: dict[str, Path] = field(default_factory=dict)
    change: str = "MC-0"  # the protocol's change id this run qualifies (MC-0: a first qualification)


@dataclass
class Ctx:
    opts: Options
    target: Target
    builds: dict[str, Build]
    judge: QClient
    verifier: QClient
    work: Path
    log: io.StringIO
    state: dict[str, Any] = field(default_factory=dict)


def registry_doc() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text(encoding="utf-8")) or {}
    return doc


def profile_builds(profile: str, doc: dict[str, Any] | None = None) -> dict[str, Build]:
    """The judge and verifier builds of ``profile``; :class:`QualifyError` when the registry has none."""
    if profile not in PROFILES:
        raise QualifyError(f"unknown profile {profile!r} (known: {', '.join(PROFILES)})")
    rows = (doc or registry_doc()).get("builds") or []
    out: dict[str, Build] = {}
    for role, alias in (("judge", JUDGE_ALIAS), ("verifier", VERIFIER_ALIAS)):
        if profile == "ci":
            want_id = STUB_VERIFIER_BUILD if role == "verifier" else STUB_BUILD
            hit = [b for b in rows if b.get("build_id") == want_id]
        else:
            hit = [
                b
                for b in rows
                if b.get("alias") == alias and str(b.get("build_id", "")).endswith("-" + PROFILES[profile])
            ]
        if len(hit) != 1:
            raise QualifyError(f"profile {profile}: {len(hit)} {alias} builds in models/registry.yaml (need one)")
        b = hit[0]
        served = next(iter((b.get("served") or {}).values()), None) or ""
        out[role] = Build(
            role,
            str(b["build_id"]),
            str(b["alias"]),
            str(served),
            # T-012b: a local build's weights are the release the registry expects (the site pin must equal it)
            str(b.get("sha256") or SYNTHETIC)
            if b.get("serving") == "stub"
            else str(b.get("sha256") or (b.get("expected") or {}).get("manifest_sha256") or ""),
            b.get("revision") or (b.get("expected") or {}).get("revision"),
            b.get("context_length"),
            dict(b.get("licence") or {}),
            str(b.get("status") or ""),
            b.get("repository"),
            (b.get("provenance") or {}).get("licence_file"),
        )
    if profile == "ci":
        out["judge"].weights_sha256 = out["verifier"].weights_sha256 = SYNTHETIC
    return out


# ---------------------------------------------------------------------------------------------------- steps
@dataclass
class StepResult:
    status: str  # passed | failed
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


def ok(detail: dict[str, Any] | None = None, reason: str = "") -> StepResult:
    return StepResult("passed", reason, detail or {})


def bad(reason: str, detail: dict[str, Any] | None = None) -> StepResult:
    return StepResult("failed", reason, detail or {})


def step_pin(ctx: Ctx) -> StepResult:
    j, v = ctx.builds["judge"], ctx.builds["verifier"]
    detail: dict[str, Any] = {
        r: {"build_id": b.build_id, "weights_sha256": b.weights_sha256} for r, b in ctx.builds.items()
    }
    problems: list[str] = []
    listed = ctx.target.models()
    detail["gateway_models"] = sorted(listed)
    want = {j.alias, v.alias} if ctx.opts.profile != "ci" else {"trialbox-stub", STUB_VERIFIER_ALIAS}
    missing = sorted(want - set(listed))
    if missing:
        problems.append(f"the gateway does not list {', '.join(missing)}")
    if j.build_id == v.build_id:
        problems.append("judge and verifier are the same build: the two-model rule needs two")
    for b in ctx.builds.values():
        if ctx.opts.profile != "ci" and not (len(b.weights_sha256) == 64 and b.weights_sha256 != SYNTHETIC):
            problems.append(f"{b.build_id} has no pinned weight hash in models/registry.yaml")
    # one judge call each way: the answer must come from the pinned build
    from tools.judge_bakeoff import synthetic_items

    it = next(i for i in synthetic_items() if i.excerpts)
    seen: dict[str, str] = {}
    for role, client in (("judge", ctx.judge), ("verifier", ctx.verifier)):
        _tl.calls = []
        try:
            client.chat_json("judge", _judge_vars(it.criterion_text, it.note_question, it.index_date, it.excerpts))
        except LlmError as exc:
            problems.append(f"the gateway gave no {role} answer ({str(exc)[:120]})")
            continue
        c = _calls()[-1]
        seen[role] = c["build_sha"]
        b = ctx.builds[role]
        if c["build_id"] != b.build_id:
            problems.append(f"the {role} answer came from build {c['build_id'] or '?'}, not {b.build_id}")
        if ctx.opts.profile != "ci" and c["build_sha"] != b.weights_sha256:
            problems.append(f"the {role} answer carries build sha {c['build_sha'][:16]}, not the pinned weights")
    detail["answer_build_sha"] = seen
    return bad("; ".join(problems), detail) if problems else ok(detail)


def _judge_vars(criterion: str, question: str, index_date: str, excerpts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "criterion_text": criterion,
        "note_question": question,
        "index_date": index_date[:10],
        "excerpts": [{k: e.get(k) for k in ("date", "note_type", "text")} for e in excerpts],
    }


def _run(cmd: list[str], timeout: float = 30.0) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, type(exc).__name__
    return p.returncode, p.stdout.strip()


def git_head() -> tuple[str, bool]:
    """The code this record names, and whether it differs from it: a git commit, or on a box installed from a signed
    bundle the release tree's ``release:<sha256>`` (QUALIFY-BOX, D-734; ``tools.code_identity``)."""
    from tools import code_identity

    return code_identity.head(ROOT)


def dirty_problem(head: str, dirty: bool) -> str:
    """What a dirty tree is called: a checkout with uncommitted changes, or a release that differs from its sums."""
    if not dirty:
        return ""
    if head.startswith("release:"):
        return "the installed release differs from its signed HOST-SHA256SUMS: a record must name one release"
    return "the working tree has uncommitted changes: a record must name one commit"


def gpu_versions() -> dict[str, str]:
    """Driver and CUDA version from ``nvidia-smi``; ``none`` when this host has no NVIDIA driver."""
    if shutil.which("nvidia-smi") is None:
        return {"driver": "none", "cuda": "none", "gpu": "none"}
    rc, out = _run(["nvidia-smi", "--query-gpu=driver_version,name", "--format=csv,noheader"])
    rc2, full = _run(["nvidia-smi"])
    cuda = next((w.split()[0] for w in full.split("CUDA Version:")[1:2]), "unknown") if rc2 == 0 else "unknown"
    first = out.splitlines()[0].split(",") if rc == 0 and out else ["unknown", "unknown"]
    return {"driver": first[0].strip(), "cuda": cuda, "gpu": first[-1].strip()}


def model_server_image(root: Path = ROOT) -> dict[str, str]:
    """HW-003 (D-569): the model server image this release pins (``deploy/images.lock``): reference and digest. A
    record names it, so a shipped record is used only on a box that runs the same image."""
    lock = json.loads((root / "deploy" / "images.lock").read_text(encoding="utf-8"))
    entry = (lock.get("third_party") or {}).get("vllm") or {}
    return {"image": str(entry.get("image") or ""), "digest": str(entry.get("digest") or "")}


def pinned_template_sha256(build_id: str) -> str | None:
    """The sha256 of the chat template in ``build_id``'s site pin (``TB_REGISTRY_OVERRIDE``, else the box's
    ``deploy/site/registry.site.yaml``); None when the build has no pin or is served with its own template."""
    path = Path(os.environ.get("TB_REGISTRY_OVERRIDE") or ROOT / "deploy" / "site" / "registry.site.yaml")
    if not path.is_file():
        return None
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entry = (doc.get("builds") or {}).get(build_id) or {}
    sha = ((entry.get("weights") or {}).get("chat_template") or {}).get("sha256")
    return str(sha) if sha else None


def code_note(head: str) -> str:
    """D-881: what the record says of a code named by the image alone."""
    return "no release tree: code named by the image digest" if head.startswith("image:") else ""


def code_problems(head: str, env: Mapping[str, str]) -> list[str]:
    """Why ``head`` cannot name the code of this record: unknown, or (D-881) only an image id on a box that is not
    run under the poc host profile (a site box has its signed release tree)."""
    if head == "unknown":
        return ["no git HEAD and no signed release tree (HOST-SHA256SUMS): the record cannot name its code"]
    if head.startswith("image:") and (env.get("TB_HOST_PROFILE") or "").strip() != "poc":
        return ["no signed release tree: an image id alone names a site box's code only under TB_HOST_PROFILE=poc"]
    return []


def step_serving_record(ctx: Ctx) -> StepResult:
    from gateway.policy import RoutingPolicy
    from tb_llm.prompt_registry import default_registry

    head, dirty = git_head()
    reg = default_registry()
    prompts = [{"prompt": e.ref, "sha256": e.sha256, "schema_sha256": e.schema_sha256} for e in reg.active_set()]
    detail = {
        "git_head": head,
        "git_dirty": dirty,
        **gpu_versions(),
        "python": platform.python_version(),
        "routing_version": RoutingPolicy.load().version,
        "registry_version": str(registry_doc().get("version") or ""),
        "prompt_registry_version": reg.version,
        "prompts": prompts,
        # HW-003 (D-569): what a shipped record is matched on at a site, beside the weights
        "model_server_image": model_server_image(),
        "chat_template_sha256": pinned_template_sha256(ctx.builds["judge"].build_id),
    }
    ctx.state["serving"] = detail
    if code_note(head):
        detail["code"] = code_note(head)
    problems = code_problems(head, os.environ)
    if dirty and ctx.opts.profile != "ci":
        problems.append(dirty_problem(head, dirty))
    if ctx.opts.profile != "ci" and detail["driver"] == "none":
        problems.append("no NVIDIA driver on this host")
    return bad("; ".join(problems), detail) if problems else ok(detail)


def _none_in_source(b: Build, reg: Any, folder: Path | None, row: dict[str, Any]) -> list[str]:
    """HW-004 (D-565): the licence check of a build whose source holds no licence file. The register row is the
    evidence: it names the build's revision and a source URL (that it is cleared, for this repository and SPDX id,
    is `licence_register.model_problems`). The text beside the weight folder is recorded when it is there, and is
    refused when it is not the text the row checked."""
    row["text"] = None
    if reg is None:
        return []  # said by model_problems: a verified licence without a register row
    out = []
    named = _FULL_REVISION.findall(reg.raw["version"])  # exactly one full revision, and it is the build's
    if not b.revision or named != [b.revision]:
        out.append(f"{b.build_id}: register row {reg.id} does not name the build's revision {b.revision}")
    if "https://" not in reg.raw["evidence"]:
        out.append(f"{b.build_id}: register row {reg.id} names no source URL in its evidence")
    if folder is None:
        return out
    folder = folder.resolve()  # a link to the weight folder: the folder's own name and place
    if not folder.name or folder.parent.name == "snapshots":
        # a model cache's snapshot: beside it is the cache's `snapshots` folder, where another folder would be
        # read as a snapshot (tools/serving_config.py). The text rides beside a flat <models root>/<folder> only
        return out
    beside = folder.parent / LICENCE_BESIDE / folder.name
    found = [n for n in LICENCE_FILES if (beside / n).is_file()]
    if found:
        data = (beside / found[0]).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        row["text"], row["text_sha256"] = f"{LICENCE_BESIDE}/{folder.name}/{found[0]}", sha
        if not data.strip():
            out.append(f"{b.build_id}: the licence text beside the weight folder is empty ({row['text']})")
        elif reg.raw["text_sha256"] and sha != reg.raw["text_sha256"]:
            out.append(f"{b.build_id}: the licence text beside the weight folder is not the text checked in "
                       f"register row {reg.id}")  # fmt: skip
    return out


def step_licence(ctx: Ctx) -> StepResult:
    problems: list[str] = []
    detail: dict[str, Any] = {}
    registers = licence_register.load()
    for role, b in ctx.builds.items():
        row = {"name": b.licence.get("name"), "verified": bool(b.licence.get("verified"))}
        if not row["name"] or not row["verified"]:
            problems.append(f"{b.build_id}: licence not verified in models/registry.yaml")
        else:  # the register row behind it (T-617b): same repository, same SPDX id, cleared
            build = {"build_id": b.build_id, "licence": b.licence, "status": b.status, "repository": b.repository}
            problems += licence_register.model_problems(registers, [build])
        reg = next((r for r in registers if r.id == b.licence.get("register")), None)
        row["register"] = reg.id if reg else None
        if b.weights_sha256 == SYNTHETIC:
            row["file"] = "in repository (synthetic weights)"
        elif b.licence_file == NONE_IN_SOURCE:
            row["file"] = NONE_IN_SOURCE_FILE
            problems += _none_in_source(b, reg, ctx.opts.model_dirs.get(role), row)
        else:
            d = ctx.opts.model_dirs.get(role)
            found = [n for n in LICENCE_FILES if d is not None and (d / n).is_file()]
            row["file"] = found[0] if found else None
            if d is None:
                problems.append(f"{b.build_id}: no --model-dir {role}=<folder> to check the licence file")
            elif not found:
                problems.append(f"{b.build_id}: no licence file in the weight folder")
            elif d is not None and reg is not None and reg.raw["text_sha256"]:
                sha = hashlib.sha256((d / found[0]).read_bytes()).hexdigest()
                row["file_sha256"] = sha
                if sha != reg.raw["text_sha256"]:
                    problems.append(f"{b.build_id}: the licence file is not the text checked in register row {reg.id}")
        detail[role] = row
    return bad("; ".join(problems), detail) if problems else ok(detail)


def _probe_vars(v: Any, text: str) -> Any:
    if isinstance(v, str):
        return v.replace("{adversarial}", text)
    if isinstance(v, list):
        return [_probe_vars(x, text) for x in v]
    if isinstance(v, dict):
        return {k: _probe_vars(x, text) for k, x in v.items()}
    return v


def step_schema(ctx: Ctx) -> StepResult:
    import jsonschema
    from tb_common.llm import load_prompt, render
    from tb_contracts import inline_schema
    from tb_llm import CallLabels, GatewayRefused, json_schema_format
    from tb_llm.prompt_registry import default_registry, ref_schema

    doc = yaml.safe_load(PROBES.read_text(encoding="utf-8")) or {}
    probes: dict[str, Any] = doc.get("probes") or {}
    roles = yaml.safe_load((ROOT / "libs" / "tb_llm" / "v1_roles.yaml").read_text(encoding="utf-8")) or {}
    reg = default_registry()
    gw = ctx.target.gateway(PROBE_CALLER)
    results: dict[str, str] = {}
    not_probed: list[str] = []
    problems: list[str] = []
    for e in reg.active_set():
        p = probes.get(e.id)
        if p is None:
            results[e.ref] = "no_probe"
            problems.append(f"{e.ref}: no probe in {PROBES.name}")
            continue
        if ctx.opts.stub and p.get("stub") is False:
            not_probed.append(e.ref)
            continue
        prompt = load_prompt(f"{e.id}_v{e.version}")
        schema = ref_schema(e.schema_ref) if e.schema_ref else inline_schema(str(e.schema))
        lab = {**(roles.get(e.id) or {}), **(p.get("labels") or {})}
        labels = CallLabels(
            data_class="D0",
            purpose="evaluation",
            study_id="qualify",
            context_of_use=str(lab.get("context_of_use") or ""),
            role=str(lab.get("role") or ""),
            prompt=e.ref,
            prompt_sha=e.sha256,
        )
        body = {
            "messages": render(prompt, _probe_vars(p.get("variables") or {}, str(doc.get("adversarial") or ""))),
            "response_format": json_schema_format(e.id, schema),
            "max_tokens": prompt.meta.max_tokens,
        }
        try:
            payload = gw.complete(body, labels)
        except (GatewayRefused, Exception) as exc:
            code = getattr(exc, "reason", "") or type(exc).__name__
            results[e.ref] = f"error:{code}"
            problems.append(f"{e.ref}: no answer ({code})")
            continue
        choice = (payload.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            results[e.ref] = "truncated"
            problems.append(f"{e.ref}: answer cut off")
            continue
        try:
            jsonschema.validate(json.loads(str(choice.get("message", {}).get("content") or "")), schema)
        except (ValueError, jsonschema.ValidationError):
            results[e.ref] = "invalid"
            problems.append(f"{e.ref}: answer not valid against its schema")
            continue
        results[e.ref] = "valid"
    sent = [r for r in results.values()]
    detail = {
        "probes": results,
        "not_probed_on_stub": not_probed,
        "valid": sum(r == "valid" for r in sent),
        "sent": len(sent),
    }
    return bad("; ".join(problems), detail) if problems else ok(detail)


# The longest prompt each role sends (LLM-015): the judge's full-record fallback and the chart a coordinator uploads.
# Since T-603 both are sized from the model's context (NoteJudge.budget, sitesetup.charts.chart_parts): the longest
# prompt on a profile is the one filled to that profile's budget; with no context known, the old fixed sizes.
def longest_prompts(context: int | None = None) -> dict[str, tuple[str, dict[str, Any]]]:
    from orchestrator.scenarios.evaluate import FULL_RECORD_TOKENS, _tokens
    from sitesetup.charts import MAX_CHART_CHARS, chart_parts
    from tb_common.llm import load_prompt, render
    from tb_llm.budget import estimate_messages, text_budget

    line = "2026-10-01 経過良好。血圧 128/76、HbA1c 6.9 %。痛風発作なし。\n"
    text = line * 8
    judge: dict[str, Any] = {
        "criterion_text": "No active gout flare",
        "note_question": "Is the patient currently having a gout flare?",
        "index_date": "2026-10-05",
        "excerpts": [],
    }
    budget = FULL_RECORD_TOKENS
    if context:
        p = load_prompt("judge")
        budget = min(budget, text_budget(context, estimate_messages(render(p, judge)), p.meta.max_tokens))
    excerpts, n = [], 0
    while n + _tokens(text) <= budget:  # as NoteJudge.full_record fills its budget
        excerpts.append({"date": "2026-10-01", "note_type": "progress", "text": text})
        n += _tokens(text)
    judge["excerpts"] = excerpts
    chart_vars = {"language": "ja", "language_name": "Japanese", "text": ""}
    chart = (line * (MAX_CHART_CHARS // len(line) + 1))[:MAX_CHART_CHARS]
    if context:
        p = load_prompt("chart_facts")
        room = text_budget(context, estimate_messages(render(p, chart_vars)), p.meta.max_tokens)
        chart = chart_parts(chart, room)[0]  # the first part is the fullest (sitesetup.charts.extract)
    return {"judge": ("judge", judge), "chart_facts": ("chart_facts", {**chart_vars, "text": chart})}


def _estimate(messages: list[dict[str, str]]) -> int:
    from tb_llm.budget import estimate_messages

    return estimate_messages(messages)


def step_longest_prompt(ctx: Ctx) -> StepResult:
    from tb_common.llm import LlmError, load_prompt, render

    context = ctx.builds["judge"].context_length
    detail: dict[str, Any] = {"context_length": context, "roles": {}}
    problems: list[str] = []
    for role, (pid, variables) in longest_prompts(context).items():
        prompt = load_prompt(pid)
        need = _estimate(render(prompt, variables)) + prompt.meta.max_tokens
        row: dict[str, Any] = {"prompt": f"{prompt.meta.id}@{prompt.meta.version}", "tokens_needed": need}
        detail["roles"][role] = row
        if context is not None and need > context:
            row["result"] = "too_long"
            problems.append(f"{role}: the longest prompt needs about {need} tokens, the profile has {context}")
            continue
        _tl.calls = []
        try:
            ctx.judge.chat_json(pid, variables)
        except LlmError as exc:
            row["result"] = "no_answer"
            problems.append(f"{role}: the longest prompt got no answer ({str(exc)[:80]})")
            continue
        c = _calls()
        if any(x["finish"] == "length" for x in c) or (c and c[-1].get("attempts", 1) > 1):
            row["result"] = "truncated_or_retried"
            problems.append(f"{role}: the longest prompt was cut off or needed a retry")
            continue
        row["result"] = "answered"
    return bad("; ".join(problems), detail) if problems else ok(detail)


class _Capture(logging.Handler):
    def __init__(self, buf: io.StringIO) -> None:
        super().__init__(logging.DEBUG)
        self.buf = buf

    def emit(self, record: logging.LogRecord) -> None:
        with suppress(Exception):
            self.buf.write(record.getMessage() + " " + json.dumps(record.__dict__, default=str) + "\n")


# no digits, and no M, N, R (a run "MRN" reads as a medical record number)
_MARKER_LETTERS = "BCDFGHJKLPQTVWXZ"


def new_marker() -> str:
    # letters only: a run of hex digits can look like a phone or ID number and trip the gateway's PHI tripwire (~0.6 %
    # of runs), which refuses the call and fails the log_marker step for a reason that has nothing to do with the log
    return "TBQMARK" + "".join(secrets.choice(_MARKER_LETTERS) for _ in range(16))


def step_log_marker(ctx: Ctx) -> StepResult:
    marker = new_marker()
    before = {p: _size(p) for p in ctx.opts.server_logs}
    variables = _judge_vars(
        "No active gout flare",
        "Is the patient currently having a gout flare?",
        "2026-10-05",
        [{"date": "2026-10-01", "note_type": "progress", "text": f"No gout flare today. Ref {marker}."}],
    )
    ctx.judge.chat_json("judge", variables)
    ctx.verifier.chat_json("judge", variables)
    places: dict[str, bool] = {}
    for d in ctx.target.audit_dirs:
        places[f"audit:{d.name}"] = any(marker in f.read_text(encoding="utf-8", errors="replace") for f in _files(d))
    places["process_log"] = marker in ctx.log.getvalue()
    for p in ctx.opts.server_logs:
        places[f"server_log:{p.name}"] = marker in _tail(p, before.get(p, 0))
    detail = {"searched": sorted(places), "found_in": sorted(k for k, v in places.items() if v)}
    problems = []
    if ctx.target.live and not ctx.opts.server_logs:
        problems.append("no --server-log given: the model server's log was not searched")
    if ctx.target.live and not ctx.target.audit_dirs:
        problems.append("no --audit-dir given: the gateway's audit files were not searched")
    if detail["found_in"]:
        problems.append(f"the planted marker was found in {', '.join(detail['found_in'])}")
    return bad("; ".join(problems), detail) if problems else ok(detail)


def _files(d: Path) -> list[Path]:
    return sorted(p for p in d.rglob("*") if p.is_file()) if d.is_dir() else []


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def _tail(p: Path, start: int) -> str:
    try:
        with p.open("rb") as fh:
            fh.seek(start if start <= _size(p) else 0)
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def step_canary(ctx: Ctx) -> StepResult:
    from orchestrator import selftest

    rep = selftest.run_selftest(ctx.judge, ctx.verifier)
    models = {m["role"]: {k: m.get(k) for k in ("model", "cases", "answered", "correct", "flips", "ok")}
              for m in rep["models"]}  # fmt: skip
    pair = rep.get("pair") or {}
    detail = {
        "ok": bool(rep["ok"]),
        "cases": rep["cases"],
        "models": models,
        "pair": {k: pair.get(k) for k in ("decided_wrong", "agreed", "decided") if k in pair},
        "problems": rep["problems"],
    }
    counts = _canary_counts(rep)
    ctx.state["canary_counts"] = counts
    if ctx.opts.stub:  # the stub is not a model: its canary result is known, and a change in it is a failure
        detail["stub_known_result"] = STUB_CANARY
        if counts != STUB_CANARY:
            return bad(f"the stub's canary result changed: {counts}, known {STUB_CANARY}", detail)
        return ok(detail, f"{ctx.judge.model}: the stub's known canary result ({_canary_text(counts)})")
    if not rep["ok"]:
        return bad("; ".join(rep["problems"]) or "the canary failed", detail)
    return ok(detail, f"judge {ctx.judge.model} and verifier {ctx.verifier.model}: {_canary_text(counts)}")


def _canary_counts(rep: dict[str, Any]) -> dict[str, Any]:
    by = {m["role"]: m for m in rep.get("models") or []}
    out: dict[str, Any] = {"cases": rep.get("cases")}
    for role in ("judge", "verifier"):
        out[role] = {k: (by.get(role) or {}).get(k) for k in ("answered", "correct")}
    out["pair_decided_wrong"] = (rep.get("pair") or {}).get("decided_wrong")
    return out


def _canary_text(c: dict[str, Any]) -> str:
    return (
        f"judge {c['judge']['correct']}/{c['cases']}, verifier {c['verifier']['correct']}/{c['cases']} correct, "
        f"{c['pair_decided_wrong']} decided wrong by the pair"
    )


def _items(ctx: Ctx) -> list[Any]:
    from tools import judge_bakeoff as jb

    if "items" not in ctx.state:
        items, skipped = jb.build_set(ctx.opts.sources)
        if ctx.opts.items:
            items = items[: ctx.opts.items]
        ctx.state["items"] = items
        ctx.state["skipped_sources"] = skipped
    out: list[Any] = ctx.state["items"]
    return out


def pair_item(judge: QClient, verifier: QClient, it: Any) -> Any:
    """One item through the pair, as the box judges it (``NoteJudge`` with a verifier), as a judge_bakeoff row."""
    from orchestrator.scenarios.evaluate import NoteJudge
    from tb_common.quotes import quote_in

    from tools import judge_bakeoff as jb

    row = jb.Row(
        it.id, it.source, it.cluster, it.pair, it.kind, it.gold, it.gated, gold_eligibility=jb.gold_eligibility(it)
    )
    if not it.excerpts:
        row.reason = "no_notes"
        return row
    _tl.calls = []
    nj = NoteJudge(lake=None, llm=judge, verifier=verifier)
    t0 = time.perf_counter()
    r = nj.judge_excerpts(it.criterion_text, it.note_question, date.fromisoformat(it.index_date[:10]), it.excerpts,
                          "full_record")  # fmt: skip
    row.latency_s = round(time.perf_counter() - t0, 4)
    calls = list(_calls())
    row.predicate, row.reason = r.predicate, str(r.reason or "")
    row.eligibility = jb.eligibility(it.kind, r.predicate)
    row.call_latency_s = [round(float(c["s"]), 4) for c in calls]
    row.tokens_in, row.tokens_out = sum(c["in"] for c in calls), sum(c["out"] for c in calls)
    row.attempts = len(calls)
    first = next((c for c in calls if "data" in c), None)
    if nj.failures or first is None:
        row.error = "no_answer"
        return row
    row.served_model = first["build_id"]
    row.raw_verdict = str(first["data"].get("verdict", "unknown"))
    if row.raw_verdict in ("pass", "fail"):
        q = str(first["data"].get("quote") or "")
        hits = [e for e in it.excerpts if quote_in(q, str(e["text"]))]
        qd = str(first["data"].get("quote_date") or "")[:10]
        row.quote_found = bool(hits)
        row.quote_date_ok = any(qd == str(e["date"])[:10] for e in hits)
    row.__dict__["_cache"] = [c["cache"] for c in calls]
    row.__dict__["_out"] = [json.dumps(c.get("data"), sort_keys=True, ensure_ascii=False) for c in calls]
    return row


PROGRESS_EVERY_S = 30.0  # D-838: the pair gate's heartbeat (a box's watchdog took 20 silent minutes for a hang)


def run_pair(
    judge: QClient,
    verifier: QClient,
    items: list[Any],
    workers: int,
    say: Callable[[str], None] | None = None,
    every_s: float = PROGRESS_EVERY_S,
) -> list[Any]:
    """Each item through the pair, in the items' order. D-838: every ``every_s`` seconds, and once at the end, one
    line says how many are answered, whichever item is slow."""
    say = say or (lambda m: print(m, file=sys.stderr, flush=True))
    n, done, t0 = len(items), [0], time.monotonic()
    stop, lock = threading.Event(), threading.Lock()

    def heartbeat() -> None:
        while not stop.wait(every_s):
            say(f"qualify: pair_gate: {done[0]}/{n} items answered ({time.monotonic() - t0:.0f} s)")

    def one(it: Any) -> Any:
        row = pair_item(judge, verifier, it)
        with lock:
            done[0] += 1
        return row

    beat = threading.Thread(target=heartbeat, daemon=True)
    beat.start()
    try:
        with ThreadPoolExecutor(max(1, workers)) as ex:
            rows = list(ex.map(one, items))
    finally:
        stop.set()
        beat.join()
    say(f"qualify: pair_gate: {n}/{n} items answered ({time.monotonic() - t0:.0f} s)")
    return rows


def _gate(ctx: Ctx) -> Any:
    from tools import judge_bakeoff as jb

    gated = tuple(s for s in ctx.opts.sources if jb.GATED.get(s))
    return jb.GateConfig(require=gated)


def step_pair_gate(ctx: Ctx) -> StepResult:
    from tools import judge_bakeoff as jb

    items = _items(ctx)
    t0 = time.perf_counter()
    rows = run_pair(ctx.judge, ctx.verifier, items, ctx.opts.workers)
    wall = time.perf_counter() - t0
    ctx.state["pair_rows"] = rows
    ctx.state["pair_wall_s"] = wall
    m = jb.metrics(rows, "", _gate(ctx))
    g = m["gated"]
    detail = {
        "sources": list(ctx.opts.sources),
        "skipped_sources": ctx.state.get("skipped_sources") or {},
        "items": len(items),
        "asked": g["asked"],
        "exclusions": g["wrong_exclusion"]["n"],
        "wrong_exclusions": g["wrong_exclusion"]["exact"][0],
        "wrong_exclusion_wilson95": g["wrong_exclusion"]["wilson95"],
        "no_answer": g["no_answer"],
        "checks": m["gate"]["checks"],
    }
    if not m["gate"]["passed"]:
        return bad("gate failed: " + ", ".join(k for k, v in m["gate"]["checks"].items() if not v), detail)
    return ok(detail)


def step_determinism(ctx: Ctx) -> StepResult:
    items = [it for it in _items(ctx) if it.excerpts][: ctx.opts.repeat_items]
    a = run_pair(ctx.judge, ctx.verifier, items, REPEAT_WORKERS)
    b = run_pair(ctx.judge, ctx.verifier, items, REPEAT_WORKERS)
    changed = [x.id for x, y in zip(a, b, strict=True) if x.predicate != y.predicate]
    changed_excl = [x.id for x, y in zip(a, b, strict=True) if (x.eligibility == "fail") != (y.eligibility == "fail")]
    changed_out = sum(x.__dict__.get("_out") != y.__dict__.get("_out") for x, y in zip(a, b, strict=True))
    cached = sum(c == "hit" for r in [*a, *b] for c in r.__dict__.get("_cache", []))
    detail = {
        "items": len(items),
        "concurrency": REPEAT_WORKERS,
        "changed_verdicts": len(changed),
        "changed_verdict_share": round(len(changed) / len(items), 4) if items else None,
        "changed_exclusions": len(changed_excl),
        "changed_outputs": changed_out,
        "cache_hits": cached,
    }
    problems = []
    if not items:
        problems.append("no item to repeat")
    if cached:
        problems.append(f"{cached} answers came from the gateway cache: not a repeat run")
    if changed_excl:
        problems.append(f"{len(changed_excl)} exclusions changed between two runs of the same items")
    return bad("; ".join(problems), detail) if problems else ok(detail)


def step_throughput(ctx: Ctx) -> StepResult:
    from tools.bakeoff_live import _pct

    rows = [r for r in ctx.state.get("pair_rows") or [] if r.reason != "no_notes" and not r.error]
    by_patient: dict[str, float] = {}
    for r in rows:
        by_patient[r.cluster] = by_patient.get(r.cluster, 0.0) + r.latency_s
    per_check = [r.latency_s for r in rows]
    per_patient = list(by_patient.values())
    detail = {
        "workers": ctx.opts.workers,
        "seconds_per_note_stage_patient": {"p50": round(_pct(per_patient, 0.5), 3),
                                           "p95": round(_pct(per_patient, 0.95), 3), "n": len(per_patient)},
        "seconds_per_criterion_check": {"p50": round(_pct(per_check, 0.5), 3),
                                        "p95": round(_pct(per_check, 0.95), 3), "n": len(per_check)},
        "note_stage_share": "not measured here: the G1 run reports it per trial (LLM-025)",
    }  # fmt: skip
    if not rows:
        return bad("no answered pair item to time (run pair_gate first)", detail)
    return ok(detail)


def step_injection(ctx: Ctx) -> StepResult:
    from tools import injection_eval as ie

    # the protocol locator calls as the document parser does (caller doc-parser, role extract_criteria)
    alias = None if ctx.opts.stub else JUDGE_ALIAS
    locator = QClient(ctx.target.gateway("doc-parser", model=alias), alias=alias, name=ctx.judge.model)
    models = ie.Models(judge=ctx.judge, verifier=ctx.verifier, locator=locator)
    rep = ie.run(ie.load_cases(), models, strict=ctx.opts.stub)
    s = rep.summary()
    keys = ("cases", "attacks", "controls", "changed", "changed_ids", "false_positives", "false_positive_ids",
            "false_positive_share", "not_as_expected", "by_target", "by_language", "checks")  # fmt: skip
    detail = {k: s[k] for k in keys}
    if not s["passed"]:
        return bad("injection suite failed: " + ", ".join(k for k, v in s["checks"].items() if not v), detail)
    fps = f"{s['false_positives']}/{s['controls']}"
    return ok(detail, f"{s['attacks']} attacks, 0 changed facts; {fps} false positives")


def step_evidence(name: str) -> Callable[[Ctx], StepResult]:
    def run(ctx: Ctx) -> StepResult:
        path = ctx.opts.evidence.get(name)
        if path is None:
            if not ctx.opts.stub:
                return bad(f"no --evidence {name}=<result.json>")
            rc, _ = _run([sys.executable, *EVIDENCE_STEPS[name]], timeout=120.0)
            wiring = {"mode": "wiring", "command": " ".join(["python", *EVIDENCE_STEPS[name]])}
            return ok(wiring, "wiring only (--stub)") if rc == 0 else bad(f"{wiring['command']} exited {rc}", wiring)
        try:
            raw = path.read_bytes()
            doc = json.loads(raw)
        except (OSError, ValueError) as exc:
            return bad(f"evidence {path.name} unreadable ({type(exc).__name__})")
        head, _ = git_head()
        detail: dict[str, Any] = {"mode": "evidence", "file": path.name, "sha256": hashlib.sha256(raw).hexdigest()}
        passed = isinstance(doc, dict) and (doc.get("passed") is True or doc.get("ok") is True)
        ev_head = str(doc.get("head") or doc.get("git_head") or "") if isinstance(doc, dict) else ""
        detail["head"] = ev_head or None
        if not passed:
            return bad(f"evidence {path.name} does not say passed", detail)
        if name == "n12":  # the gate figure is the unadjusted one (D-343, REG-030)
            detail["basis"] = doc.get("basis")
            if doc.get("basis") != "unadjusted":
                return bad(f"evidence {path.name} does not say basis unadjusted: N-12 gates on the raw figure", detail)
            detail["source"] = doc.get("source")  # D-826: from the product path (tools.n12_screen), not a benchmark
            if doc.get("source") != "screen":
                return bad(f"evidence {path.name} does not say source screen: N-12 is read from SCREEN's own run "
                           "(python -m tools.n12_screen)", detail)  # fmt: skip
        if ev_head and ev_head != head:
            return bad(f"evidence {path.name} is from {ev_head[:12]}, not this HEAD", detail)
        if not ev_head and not ctx.opts.stub:
            return bad(f"evidence {path.name} names no git HEAD", detail)
        return ok(detail)

    return run


def step_planted_defect(ctx: Ctx) -> StepResult:
    """The same pair with every decided verdict flipped: the canary and the pair gate must both fail."""
    from orchestrator import selftest

    from tools import judge_bakeoff as jb

    dj = QClient(ctx.judge.gateway, alias=ctx.judge.alias, name=ctx.judge.model, defect=True)
    dv = QClient(ctx.verifier.gateway, alias=ctx.verifier.alias, name=ctx.verifier.model, defect=True)
    canary = selftest.run_selftest(dj, dv)
    items = _items(ctx)
    rows = run_pair(dj, dv, items, ctx.opts.workers)
    gate = jb.metrics(rows, "", _gate(ctx))["gate"]
    detail = {
        "canary_ok": bool(canary["ok"]),
        "canary_counts": _canary_counts(canary),
        "gate_passed": bool(gate["passed"]),
    }
    if ctx.opts.stub:  # the stub answers every canary case "unknown", with or without the defect (STUB_CANARY)
        detail["note"] = "the stub fails the canary either way: here only the gate's verdict tells"
    problems = []
    if canary["ok"]:
        problems.append("the canary passed a model with a planted defect")
    if gate["passed"]:
        problems.append("the pair gate passed a model with a planted defect")
    return bad("; ".join(problems), detail) if problems else ok(detail, "the planted defect was caught")


STEP_FUNCS: dict[str, Callable[[Ctx], StepResult]] = {
    "pin": step_pin,
    "serving_record": step_serving_record,
    "licence": step_licence,
    "schema": step_schema,
    "longest_prompt": step_longest_prompt,
    "log_marker": step_log_marker,
    "canary": step_canary,
    "pair_gate": step_pair_gate,
    "determinism": step_determinism,
    "throughput": step_throughput,
    "injection": step_injection,
    "n12": step_evidence("n12"),
    "public_e2e": step_evidence("public_e2e"),
    "goldens": step_evidence("goldens"),
    "planted_defect": step_planted_defect,
}


# ---------------------------------------------------------------------------------------------------- record
def canonical(doc: dict[str, Any]) -> bytes:
    body = {k: v for k, v in doc.items() if k != "sha256"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def finalize(doc: dict[str, Any]) -> dict[str, Any]:
    """Status from the steps (any step of :data:`STEPS` missing or not ``passed`` -> ``failed``), then the sha."""
    steps = doc.get("steps") or {}
    failed = [s for s in STEPS if (steps.get(s) or {}).get("status") != "passed"]
    doc["failed_steps"] = failed
    doc["status"] = "failed" if failed else "passed"
    synthetic = any(b.get("weights_sha256") == SYNTHETIC for b in (doc.get("builds") or {}).values())
    doc["qualifies_production"] = doc["status"] == "passed" and not synthetic and not doc.get("stub")
    doc["sha256"] = hashlib.sha256(canonical(doc)).hexdigest()
    return doc


def schema_problems(doc: Any) -> list[str]:
    import jsonschema

    schema = json.loads(RECORD_SCHEMA.read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in v.iter_errors(doc)]


def check_record(
    doc: Any, *, profile: str | None = None, build_id: str | None = None, environment: str | None = None
) -> list[str]:
    """Why this record does not qualify (empty: it does). The status is recomputed from the steps, so a record that
    says ``passed`` with a step missing or failed, or whose body was edited, is refused."""
    problems = schema_problems(doc)
    if problems or not isinstance(doc, dict):
        return problems or ["not a JSON object"]
    if hashlib.sha256(canonical(doc)).hexdigest() != doc.get("sha256"):
        return ["the record's sha256 does not match its body (edited after it was written)"]
    again = finalize(json.loads(json.dumps(doc)))
    if again["status"] != doc["status"] or again["failed_steps"] != doc["failed_steps"]:
        problems.append("the status does not follow from the steps")
    if doc["status"] != "passed":
        problems.append(f"status {doc['status']}: failed steps {', '.join(doc['failed_steps'])}")
    if profile is not None and doc["profile"] != profile:
        problems.append(f"the record is for profile {doc['profile']}, not {profile}")
    if build_id is not None and build_id not in {b["build_id"] for b in doc["builds"].values()}:
        problems.append(f"the record does not name build {build_id}")
    if (environment or "").upper() == "PRODUCTION" and not doc.get("qualifies_production"):
        problems.append("synthetic weights or a stub run cannot qualify a PRODUCTION champion")
    return problems


@contextmanager
def capture_logs() -> Iterator[io.StringIO]:
    """Every log record of this process (the in-process gateway and stub included) into a buffer, for the marker
    search, instead of stdout; the root handlers are put back at the end."""
    buf = io.StringIO()
    root = logging.getLogger()
    old_handlers, old_level = list(root.handlers), root.level
    root.handlers[:] = [_Capture(buf)]
    root.setLevel(logging.DEBUG)
    try:
        yield buf
    finally:
        root.handlers[:] = old_handlers
        root.setLevel(old_level)


def _run_steps(
    opts: Options, tgt: Target, builds: dict[str, Build], work: Path, steps: tuple[str, ...]
) -> dict[str, Any]:
    stub = opts.profile == "ci"
    with capture_logs() as log:
        judge = QClient(
            tgt.gateway(model=None if stub else JUDGE_ALIAS),
            alias=None if stub else JUDGE_ALIAS,
            name=builds["judge"].build_id,
        )
        verifier = QClient(
            tgt.gateway(model=STUB_VERIFIER_ALIAS if stub else VERIFIER_ALIAS),
            alias=STUB_VERIFIER_ALIAS if stub else VERIFIER_ALIAS,
            name=builds["verifier"].build_id,
        )
        ctx = Ctx(opts, tgt, builds, judge, verifier, work, log)
        results: dict[str, Any] = {}
        for name in steps:
            t0 = time.perf_counter()
            try:
                r = STEP_FUNCS[name](ctx)
            except Exception as exc:
                r = bad(f"{type(exc).__name__}: {str(exc)[:200]}")
            results[name] = {"status": r.status, "reason": r.reason, "seconds": round(time.perf_counter() - t0, 2),
                             "detail": r.detail}  # fmt: skip
            print(f"qualify: {name}: {r.status}" + (f" ({r.reason})" if r.reason else ""), file=sys.stderr)
    results["_serving"] = ctx.state.get("serving") or {}
    return results


def qualify(opts: Options, target: Target | None = None, *, steps: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Run ``steps`` (default: all) and return the finalized record. A step that raises is ``failed`` with the
    exception's class; the record is still written, so a failed qualification leaves its evidence."""
    if opts.stub and opts.profile != "ci":
        raise QualifyError("--stub qualifies the stub pair on profile ci only")
    builds = profile_builds(opts.profile)
    started = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix="tb-qualify-") as tmp:
        work = Path(tmp)
        tgt = target or stub_target(work)  # builds the apps first: their start resets the root logger
        results = _run_steps(opts, tgt, builds, work, steps or STEPS)
        serving = results.pop("_serving", {})
    head, _ = git_head()
    doc: dict[str, Any] = {
        "format": RECORD_FORMAT,
        "record_id": f"{opts.profile}-{builds['judge'].build_id}-{started.strftime('%Y%m%dT%H%M%SZ')}",
        "profile": opts.profile,
        "stub": opts.stub,
        "gateway": "in-process (TEST, stub upstream)" if not tgt.live else "live",
        "builds": {
            r: {
                "build_id": b.build_id,
                "alias": b.alias,
                "served_name": b.served,
                "weights_sha256": b.weights_sha256,
                "revision": b.revision,
                "context_length": b.context_length,
                "registry_status": b.status,
            }
            for r, b in builds.items()
        },
        "git_head": serving.get("git_head") or head,
        "driver": serving.get("driver") or gpu_versions()["driver"],
        "cuda": serving.get("cuda") or gpu_versions()["cuda"],
        "operator": opts.operator,
        "started": started.isoformat(timespec="seconds"),
        "finished": datetime.now(UTC).isoformat(timespec="seconds"),
        "steps": results,
        "change_protocol": change_protocol(opts.change),
    }
    return finalize(doc)


def change_protocol(change: str) -> dict[str, str]:
    """The citation of the model change protocol: its path, the sha256 of its text and the change id qualified."""
    if change not in CHANGE_TYPES:
        raise QualifyError(f"unknown change {change}: one of {', '.join(CHANGE_TYPES)}")
    try:
        sha = hashlib.sha256(CHANGE_PROTOCOL.read_bytes()).hexdigest()
    except OSError as exc:
        raise QualifyError(f"the model change protocol {CHANGE_PROTOCOL.name} is missing") from exc
    return {"document": CHANGE_PROTOCOL.relative_to(ROOT).as_posix(), "sha256": sha, "change": change}


def write_record(doc: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{doc['record_id']}.json"
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------------------------- CLI
def _pairs(values: list[str], what: str) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for v in values:
        k, sep, p = v.partition("=")
        if not sep or not k or not p:
            raise QualifyError(f"{what} takes name=path, got {v!r}")
        out[k] = Path(p)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trialbox eval qualify", description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", choices=sorted(PROFILES), help="the hardware profile qualified")
    ap.add_argument("--stub", action="store_true", help="the stub pair through an in-process gateway (profile ci)")
    ap.add_argument("--gateway-url", default=os.environ.get("TB_GATEWAY_URL", ""), help="a running tb-gateway")
    ap.add_argument("--audit-dir", type=Path, action="append", default=[], help="the gateway's audit folder")
    ap.add_argument("--server-log", type=Path, action="append", default=[], help="a model server's log file")
    ap.add_argument("--model-dir", action="append", default=[], help="judge=<folder> / verifier=<folder>")
    ap.add_argument("--evidence", action="append", default=[], help="n12= / public_e2e= / goldens=<result.json>")
    ap.add_argument("--sources", default="", help="pair-gate sources (default: synthetic,medtxt; --stub: synthetic)")
    ap.add_argument("--items", type=int, default=0, help="cap the pair-gate items (0: all)")
    ap.add_argument("--repeat-items", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--change", default="MC-0", choices=CHANGE_TYPES, help="the protocol change id")
    ap.add_argument("--operator", default=os.environ.get("USER", "unknown"))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--check", type=Path, default=None, help="check a record instead of running one")
    ap.add_argument("--environment", default="", help="--check: the environment it must qualify for")
    a = ap.parse_args(argv)
    try:
        if a.check is not None:
            doc = json.loads(a.check.read_text(encoding="utf-8"))
            problems = check_record(doc, profile=a.profile, environment=a.environment or None)
            for p in problems:
                print(f"refused: {p}")
            print("qualifies" if not problems else "does not qualify")
            return 0 if not problems else 1
        if not a.profile:
            raise QualifyError("--profile is required")
        if not a.stub and not a.gateway_url:
            raise QualifyError("give --gateway-url (or TB_GATEWAY_URL), or --stub for the ci profile")
        sources = tuple(s for s in a.sources.split(",") if s) or (("synthetic",) if a.stub else ("synthetic", "medtxt"))
        evidence = _pairs(a.evidence, "--evidence")
        unknown = sorted(set(evidence) - set(EVIDENCE_STEPS))
        if unknown:
            raise QualifyError(f"--evidence for unknown step(s) {', '.join(unknown)}")
        opts = Options(
            a.profile,
            a.stub,
            a.operator,
            sources,
            a.items,
            a.repeat_items,
            a.workers,
            _pairs(a.model_dir, "--model-dir"),
            a.server_log,
            evidence,
            a.change,
        )
        target = None if a.stub else live_target(a.gateway_url, a.audit_dir)
        doc = qualify(opts, target)
    except QualifyError as exc:
        print(f"qualify: {exc}", file=sys.stderr)
        return 2
    path = write_record(doc, a.out or (STUB_OUT_DIR if a.stub else OUT_DIR))
    print(json.dumps({"status": doc["status"], "failed_steps": doc["failed_steps"], "record": str(path)}, indent=1))
    return 0 if doc["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
