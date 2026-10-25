"""``trialbox eval``: public evaluation suites (spec v4 §16, §17.7; S1-13, ENG-16).

    python -m tools.trialbox eval judge_public            # recorded GPT-4 outputs through tb-gateway; exact reference
    python -m tools.trialbox eval ingest_fhir_demo        # MIMIC-IV FHIR demo through dataplat (skips if absent)
    python -m tools.trialbox eval criteria_extract_public # Chia loader: blocked until the licence is confirmed

With ``TB_GATEWAY_URL`` set, ``judge_public`` sends its calls to that running gateway (live mode) instead of the
recorded outputs: ``TB_GATEWAY_MODEL`` names the alias to ask for, ``TB_EVAL_LIMIT`` caps the number of pairs (0 or
unset: all), and ``TB_GATEWAY_EXPECT_SHA`` requires every answer to come from that build. A live model is not expected
to reproduce the recorded reference, so live mode passes on the suite's ``live`` floors (valid JSON rate, no refusals)
and reports accuracy next to the reference.

Every run is archived as ``<archive>/<suite>/<run_id>.json`` with the sha256 of each dataset file it read, the
metrics, the reference and the verdict. Suites run in the TEST environment on D0 data only: a dataset classed above
the environment ceiling in ``eval/DATASETS.yaml`` is refused before anything is read.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[2]
SUITES = ROOT / "eval" / "suites"
ARCHIVE = ROOT / ".cache" / "eval" / "results"
JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"label": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "integer"}}},
    "required": ["label", "evidence"],
    "additionalProperties": False,
}


class SuiteRefused(RuntimeError):
    pass


def load_suite(name: str) -> dict[str, Any]:
    path = SUITES / name / "suite.yaml"
    if not path.exists():
        raise SuiteRefused(f"unknown suite {name!r}")
    doc: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc


def check_dataset_class(dataset: str, env: str = "TEST") -> None:
    """ENG-16: DEV and TEST refuse any dataset above D0; an unlisted dataset is refused too."""
    from tb_common.policy.classes import Environment, PolicyError, check_env
    from tb_contracts.dataclass import ClassLabel, parse_class

    doc = yaml.safe_load((ROOT / "eval" / "DATASETS.yaml").read_text(encoding="utf-8")) or {}
    entry = (doc.get("datasets") or {}).get(dataset)
    if entry is None:
        raise SuiteRefused(f"dataset {dataset!r} has no class in eval/DATASETS.yaml")
    try:
        check_env(ClassLabel(data_class=parse_class(entry.get("data_class"))), Environment(env))
    except (PolicyError, ValueError) as e:
        raise SuiteRefused(str(e)) from e


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# ------------------------------------------------------------------------------------------------ recorded upstream
class RecordedUpstream:
    """Serves recorded outputs as the ``trialbox-stub`` build behind the gateway (no model, no network).

    Outputs are keyed by the sha256 of the rendered messages, so the gateway path (labels, class check, route,
    tripwire, registry resolution, served-model echo, audit) is exercised exactly as for a live build."""

    def __init__(self, outputs: dict[str, dict[str, Any]]) -> None:
        self.outputs = outputs
        self.calls = 0

    @staticmethod
    def key(messages: Any) -> str:
        return hashlib.sha256(_canonical(messages).encode("utf-8")).hexdigest()

    def client(self) -> httpx.Client:
        def handler(req: httpx.Request) -> httpx.Response:
            body = json.loads(req.content)
            out = self.outputs.get(self.key(body.get("messages")))
            if out is None:
                return httpx.Response(404, json={"error": "no recorded output for this request"})
            self.calls += 1
            content = json.dumps(out, ensure_ascii=False)
            return httpx.Response(
                200,
                json={
                    "model": body["model"],
                    "choices": [{"message": {"role": "assistant", "content": content}}],
                    "usage": {"prompt_tokens": len(_canonical(body["messages"])) // 4, "completion_tokens": 8},
                },
            )

        return httpx.Client(transport=httpx.MockTransport(handler))


def stub_gateway(http: httpx.Client, audit_dir: Path, environment: str = "TEST") -> Any:
    """An in-process tb-gateway on the shipped routing policy and registry, with ``http`` as the model upstream."""
    from gateway.core import Gateway, GatewayConfig
    from gateway.policy import RoutingPolicy
    from guard.guard import Guard
    from registry.registry import Registry
    from tb_common.audit import AuditLog
    from tb_common.policy.classes import Environment, Topology

    return Gateway(
        RoutingPolicy.load(),
        Registry.load(),
        AuditLog(audit_dir),
        GatewayConfig(topology=Topology.A, environment=Environment(environment)),
        http=http,
        guard=Guard(None),
        env={},
    )


def gateway_client(gw: Any, caller: str) -> Any:
    from fastapi.testclient import TestClient
    from gateway.app import create_app
    from tb_llm import GatewayClient

    return GatewayClient("http://testserver/v1", caller, http=TestClient(create_app(gw)))


# ------------------------------------------------------------------------------------------------ suites
def run_judge_public(workdir: Path, suite: dict[str, Any]) -> dict[str, Any]:
    from tb_llm import CallLabels, GatewayRefused, json_schema_format

    from tools import mlbench

    check_dataset_class(str(suite["dataset"]))
    pairs = mlbench.load_pairs()
    notes = mlbench.load_notes(str(suite.get("lang", "en")))
    recorded = {
        RecordedUpstream.key(mlbench.messages(p, notes[p.patient_id])): {"label": p.gpt4_label, "evidence": []}
        for p in pairs
    }
    upstream = RecordedUpstream(recorded)
    live_url = os.environ.get("TB_GATEWAY_URL", "").strip()
    limit = int(os.environ.get("TB_EVAL_LIMIT") or 0) if live_url else 0
    if limit > 0:
        pairs = pairs[:limit]
    if live_url:
        from tb_llm import GatewayClient

        client = GatewayClient(live_url, suite["gateway"]["caller"], model=os.environ.get("TB_GATEWAY_MODEL") or None)
    else:
        client = gateway_client(stub_gateway(upstream.client(), workdir / "gateway_audit"), suite["gateway"]["caller"])
    g = suite["gateway"]
    labels = CallLabels(
        data_class=str(suite["data_class"]),
        purpose=str(g["purpose"]),
        study_id="none",
        context_of_use=str(g["context_of_use"]),
        role=str(g["role"]),
        prompt=str(g["prompt"]),
    )
    rows: list[dict[str, Any]] = []
    refused = 0
    builds: set[str] = set()
    for p in pairs:
        try:
            res = client.chat(
                mlbench.messages(p, notes[p.patient_id]),
                labels,
                response_format=json_schema_format("judge", JUDGE_SCHEMA),
            )
        except GatewayRefused:
            refused += 1
            rows.append({"annotation_id": p.annotation_id, "label": None, "valid_json": False, "evidence": []})
            continue
        builds.add(f"{res.alias}:{res.build_sha}")
        data = res.data or {}
        label = mlbench.norm_label(data.get("label"), p.criterion_type)
        rows.append({"annotation_id": p.annotation_id, "label": label, "valid_json": label is not None, "evidence": []})
    metrics = mlbench.score(rows, {p.annotation_id: p for p in pairs})
    ref = suite["reference"]
    got = {k: round(float(metrics[k]), 3) for k in ref}
    passed = got == {k: float(v) for k, v in ref.items()} and refused == 0
    gateway: dict[str, Any] = {"calls": upstream.calls, "refused": refused, "builds": sorted(builds)}
    if live_url:
        floors = suite.get("live") or {}
        expect = os.environ.get("TB_GATEWAY_EXPECT_SHA", "").strip()
        build_ok = not expect or {b.rsplit(":", 1)[-1] for b in builds} == {expect}
        passed = (
            refused <= int(floors.get("max_refused", 0))
            and float(metrics["valid_rate"]) >= float(floors.get("min_valid_rate", 0.95))
            and build_ok
        )
        gateway = {
            "mode": "live",
            "url": live_url,
            "model": client.model,
            "calls": len(pairs) - refused,
            "refused": refused,
            "builds": sorted(builds),
            "expected_sha": expect or None,
            "limit": limit or None,
        }
    return {
        "metrics": {k: metrics[k] for k in ("n", "accuracy", "false_block_rate", "false_block_upper95", "valid_rate")},
        "reference": ref,
        "reproduced": got,
        "passed": passed,
        "gateway": gateway,
        "datasets": {f: file_sha256(ROOT / f) for f in suite["files"]},
    }


def run_ingest_fhir_demo(workdir: Path, suite: dict[str, Any], source_dir: Path | None = None) -> dict[str, Any]:
    check_dataset_class(str(suite["dataset"]))
    src = source_dir or ROOT / str(suite["source_dir"])
    fetched = src / "FETCHED.json"
    if not (src / "fhir" / "MimicPatient.ndjson.gz").exists() or not fetched.exists():
        return {
            "status": "skipped",
            "passed": None,
            "reason": "MIMIC demo not fetched (python -m tools.fetch_open_data)",
        }
    manifest = json.loads(fetched.read_text(encoding="utf-8"))
    hashes: dict[str, str] = {}
    for rel, want in sorted((manifest.get("files") or {}).items()):
        got = file_sha256(src / rel)
        if got != want:
            return {"status": "failed", "passed": False, "reason": f"{rel}: sha256 differs from FETCHED.json"}
        hashes[rel] = got
    from dataplat.common import fixed_clock
    from dataplat.pipeline import run_pipeline
    from tb_common.crypto import ed25519_generate

    res = run_pipeline(
        src,
        workdir / "dataplat",
        kind="mimic_fhir",
        site_key=b"trialbox-open-data-demo-key-0123456789abcdef",
        clock=fixed_clock(datetime(2026, 9, 30, 12, 0, tzinfo=UTC)),
        snapshot="2026-09-30",
        signing_key=ed25519_generate(),
    )
    exp = suite["expect"]
    blocking = len(res.validation.blocking_reasons) if res.validation is not None else -1
    patients = (
        res.manifest.tables["Patient"].rows if res.manifest is not None and "Patient" in res.manifest.tables else 0
    )
    lineage = bool(res.lineage is not None and res.lineage.complete)
    observed = {
        "outcome": res.outcome,
        "blocking_dq_errors": blocking,
        "lineage_complete": lineage,
        "patients": patients,
    }
    return {
        "status": "ran",
        "metrics": observed,
        "reference": exp,
        "passed": observed == exp,
        "datasets": {**hashes, "version": str(manifest.get("version"))},
    }


def run_criteria_extract_public(workdir: Path, suite: dict[str, Any]) -> dict[str, Any]:
    from tools.mlbench_tasks.chia import ChiaLicenceUnconfirmed, load_chia

    try:
        load_chia(workdir)
    except ChiaLicenceUnconfirmed as e:
        return {"status": "blocked", "passed": None, "reason": str(e), "datasets": {}}
    return {"status": "ran", "passed": None, "datasets": {}}  # pragma: no cover - unreachable until licence confirmed


RUNNERS: dict[str, Callable[[Path, dict[str, Any]], dict[str, Any]]] = {
    "judge_public": run_judge_public,
    "ingest_fhir_demo": run_ingest_fhir_demo,
    "criteria_extract_public": run_criteria_extract_public,
}


def archive(suite: str, result: dict[str, Any], root: Path = ARCHIVE, *, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    body = {"suite": suite, "archived_at": stamp, **result}
    digest = hashlib.sha256(_canonical({k: v for k, v in body.items() if k != "archived_at"}).encode()).hexdigest()
    dest = root / suite / f"{stamp}_{digest[:12]}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def run_suite(name: str, workdir: Path, archive_root: Path = ARCHIVE) -> tuple[dict[str, Any], Path]:
    if name not in RUNNERS:
        raise SuiteRefused(f"unknown suite {name!r}; available: {', '.join(RUNNERS)}")
    suite = load_suite(name)
    result = RUNNERS[name](workdir, suite)
    result["suite_version"] = suite.get("version")
    return result, archive(name, result, archive_root)
