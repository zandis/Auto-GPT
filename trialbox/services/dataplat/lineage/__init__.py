"""OpenLineage run events for every stage, and the lineage-completeness check (§5.15, DP-39; S1-04).

Events are plain JSON dicts shaped as OpenLineage ``RunEvent`` (``eventType``, ``eventTime``, ``producer``,
``schemaURL``, ``run``, ``job``, ``inputs``, ``outputs``) and are appended, one canonical JSON line each, to an
append-only log (``lineage.events`` in PostgreSQL later). Datasets are named by stage, source, batch or snapshot and
table; no event carries a patient-level value. Run ids are deterministic UUIDs.

Every event carries the run facet ``tb_cycle`` so that :func:`check_complete` can assemble the graph of one publish
cycle: each expected job has ``START`` and ``COMPLETE``, the publish run outputs the snapshot, and every input of
L1–L5 is an output of an earlier run of the same cycle.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tb_contracts.landing import SnapshotManifest

from dataplat.common import Clock, canonical, iso_utc, run_uuid, utc_now

PRODUCER = "https://github.com/zandis/Auto-GPT/tree/master/trialbox/services/dataplat"
RUN_EVENT_SCHEMA = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent"
TB_FACET_SCHEMA = "https://trialbox.local/spec/v4/lineage-facets.json#/$defs/"
EVENT_TYPES = frozenset({"START", "RUNNING", "COMPLETE", "FAIL", "ABORT", "OTHER"})

Event = dict[str, Any]


def facet(name: str, **fields: Any) -> dict[str, Any]:
    """A facet with the required ``_producer`` and ``_schemaURL``."""
    return {"_producer": PRODUCER, "_schemaURL": TB_FACET_SCHEMA + name, **fields}


def dataset(namespace: str, name: str, facets: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"namespace": namespace, "name": name, "facets": facets or {}}


def job_name(stage: str, *parts: str) -> str:
    return ".".join(["tb", stage, *parts])


class LineageLog:
    def __init__(self, path: Path, site_id: str, clock: Clock = utc_now) -> None:
        self.path = path
        self.namespace = f"trialbox://{site_id}"
        self.clock = clock
        path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        event_type: str,
        job: str,
        run_id: str,
        *,
        cycle_id: str,
        inputs: Sequence[dict[str, Any]] = (),
        outputs: Sequence[dict[str, Any]] = (),
        run_facets: dict[str, Any] | None = None,
    ) -> Event:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown OpenLineage eventType {event_type!r}")
        event: Event = {
            "eventType": event_type,
            "eventTime": iso_utc(self.clock()),
            "producer": PRODUCER,
            "schemaURL": RUN_EVENT_SCHEMA,
            "run": {
                "runId": run_id,
                "facets": {"tb_cycle": facet("tb_cycle", cycle_id=cycle_id), **(run_facets or {})},
            },
            "job": {"namespace": self.namespace, "name": job, "facets": {}},
            "inputs": sorted(inputs, key=lambda d: (d["namespace"], d["name"])),
            "outputs": sorted(outputs, key=lambda d: (d["namespace"], d["name"])),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(canonical(event) + "\n")
        return event

    def run(
        self,
        job: str,
        *,
        cycle_id: str,
        key: str,
        inputs: Sequence[dict[str, Any]] = (),
        outputs: Sequence[dict[str, Any]] = (),
        run_facets: dict[str, Any] | None = None,
        failed: str | None = None,
    ) -> str:
        """Emit ``START`` then ``COMPLETE`` (or ``FAIL`` with an error-message facet) for one stage run."""
        rid = run_uuid(job, cycle_id, key)
        self.emit("START", job, rid, cycle_id=cycle_id, inputs=inputs)
        facets = dict(run_facets or {})
        if failed is not None:
            facets["errorMessage"] = facet("errorMessage", message=failed[:2000], programmingLanguage="python")
        self.emit(
            "FAIL" if failed is not None else "COMPLETE",
            job,
            rid,
            cycle_id=cycle_id,
            inputs=inputs,
            outputs=outputs,
            run_facets=facets,
        )
        return rid

    def events(self) -> list[Event]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]


@dataclass
class LineageCheck:
    complete: bool
    missing: list[str] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)


def expected_jobs(manifest: SnapshotManifest) -> list[str]:
    jobs: set[str] = {"tb.l3.pseudonymise", "tb.l4.publish", "tb.l5.serve.duckdb"}
    for source in manifest.data_cut_per_source:
        jobs |= {f"tb.l0.land.{source}", f"tb.l2.standardise.{source}"}
    for contract_id in manifest.contracts:
        source, _, table = contract_id.partition("/")
        jobs.add(f"tb.l1.validate.{source}.{table}")
    return sorted(jobs)


def check_complete(events: Iterable[Event], manifest: SnapshotManifest) -> LineageCheck:
    """Is the lineage of ``manifest`` complete? Lists every missing job, event or link."""
    cycle = [e for e in events if e["run"]["facets"].get("tb_cycle", {}).get("cycle_id") == manifest.cycle_id]
    missing: list[str] = []
    by_job: dict[str, list[Event]] = {}
    for e in cycle:
        by_job.setdefault(e["job"]["name"], []).append(e)
    for job in expected_jobs(manifest):
        types = {e["eventType"] for e in by_job.get(job, [])}
        for needed in ("START", "COMPLETE"):
            if needed not in types:
                missing.append(f"{job}: no {needed} event")
    publish = [e for e in by_job.get("tb.l4.publish", []) if e["eventType"] == "COMPLETE"]
    if not any(o["name"] == manifest.snapshot_id for e in publish for o in e["outputs"]):
        missing.append(f"tb.l4.publish: snapshot {manifest.snapshot_id} is not an output")
    produced = {(o["namespace"], o["name"]) for e in cycle if e["eventType"] == "COMPLETE" for o in e["outputs"]}
    for e in cycle:
        if e["eventType"] != "COMPLETE" or e["job"]["name"].startswith("tb.l0."):
            continue
        for i in e["inputs"]:
            if (i["namespace"], i["name"]) not in produced:
                missing.append(f"{e['job']['name']}: input {i['namespace']}/{i['name']} has no producing run")
    run_ids = sorted({e["run"]["runId"] for e in cycle})
    return LineageCheck(complete=not missing, missing=sorted(set(missing)), run_ids=run_ids)


__all__ = [
    "PRODUCER",
    "RUN_EVENT_SCHEMA",
    "Event",
    "LineageCheck",
    "LineageLog",
    "check_complete",
    "dataset",
    "expected_jobs",
    "facet",
    "job_name",
]
