from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from tb_common.ruleset import Ruleset
from tb_common.screening_inputs import (
    REFUSAL,
    ScreeningRefused,
    ScreeningUse,
    rule_digest,
)

GENERATION = "2026-10-04.g2"
DIGEST = "a" * 64


def inputs() -> dict[str, Any]:
    use = {
        "clearance_id": "release-2",
        "stored_read": "off",
        "site": "synthetic",
        "generation": GENERATION,
        "ruleset": "STUDY",
        "rule_version": "1.0.0",
        "list_to": ["coordinator"],
        "referral_to": {},
        "aggregate_to": [],
        "scope": {"practitioners": ["practitioner-a"], "departments": [], "window_days": 30, "recent_months": 6},
    }
    inventory = {store: ["row-a"] for store in ("lake", "omop", "derived")}
    rows = [
        {
            "source": store,
            "key": "row-a",
            "generation": GENERATION,
            "owner_rule_stamp": "stamp",
            "review_tag": "released",
        }
        for store in inventory
    ]
    return {
        "use": use,
        "inventory": inventory,
        "rows": rows,
        "holds_released": True,
        "trusted_digest": DIGEST,
        "accepted_digest": DIGEST,
    }


def encode(data: object) -> bytes:
    return json.dumps(data).encode()


def clearance(record: bytes) -> dict[str, Any]:
    return {
        "site": "synthetic",
        "clearance_id": "release-2",
        "state": "released",
        "accepted_records": [hashlib.sha256(record).hexdigest()],
        "database": "synthetic/1",
    }


@pytest.fixture
def admit_screening_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Install the supplied test bytes in a site and exercise the worker's gate with an actual file audit."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from orchestrator import core, derive, scheduler
    from tb_common import screening_inputs as gate
    from tb_common.audit import AuditLog
    from tb_common.db import Database
    from tb_common.flags import Flags

    ctx = MagicMock()
    ctx.cfg.env.data_dir = ctx.cfg.env.secrets_dir = str(tmp_path)
    ctx.cfg.settings.site.id = "synthetic"
    ctx.job.job_id = "unit-job"
    ctx.job.type = "SCREEN"
    ctx.job.ruleset = "STUDY"
    ctx.job.snapshot_date = None
    ctx.job.ruleset_version = None
    ctx.job.options = {}
    ctx.orch.services.lake.generation.return_value = GENERATION
    ctx.orch.db.get.return_value = ctx.job
    meta = gate.inventory_hash(["row-a"])
    ctx.orch.services.lake.query.return_value.to_pylist.return_value = [
        {"lake_inventory": meta, "omop_inventory": meta}
    ]
    monkeypatch.setattr(core, "screening_worker", lambda: ctx)
    monkeypatch.setattr(scheduler, "require_open", lambda *a, **kw: None)
    monkeypatch.setattr(gate, "release_id", lambda flags: "release-2")
    monkeypatch.setattr(gate, "database_mark", lambda url: "synthetic/1")
    monkeypatch.setattr(Flags, "row", lambda *a: "off")
    state = MagicMock()
    state.return_value.__enter__.return_value.fetchval.return_value = "open"
    monkeypatch.setattr(Database, "connect", state)
    monkeypatch.setattr(derive, "bind_screen_reader", lambda *a: ["row-a"])
    rule = SimpleNamespace(id="STUDY", version="1.0.0", manifest=SimpleNamespace(status="approved"))
    monkeypatch.setattr(gate, "load_approved", lambda *a, **kw: rule)
    audit = AuditLog(tmp_path / "audit")

    def exercise(raw: bytes, use: ScreeningUse, digest: str, grant: bytes, write: Any) -> tuple[str, str]:
        path = gate.record_path(tmp_path, use.generation, use.ruleset, use.rule_version)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        gate.clearance_path(tmp_path).write_bytes(grant)
        monkeypatch.setattr(gate, "rule_digest", lambda rule: digest)

        def append(event: str, **fields: Any) -> dict[str, Any]:
            if write(fields["input_sha"]).get("input_sha") != fields["input_sha"]:
                return {}
            return audit.append(event, **fields)

        ctx.orch.audit.append = append
        from orchestrator.scenarios import screen

        monkeypatch.setattr(screen, "screening_use", lambda *args: use)
        return gate.admit_screening_inputs()

    return exercise


def test_permit_and_audit_the_exact_generation_and_version(admit_screening_inputs: Any) -> None:
    data = inputs()
    record = encode(data)
    use = ScreeningUse.model_validate_json(encode(data["use"]))
    events: list[str] = []

    def write(digest: str) -> dict[str, str]:
        events.append(digest)
        return {"input_sha": digest}

    assert admit_screening_inputs(record, use, DIGEST, encode(clearance(record)), write) == (
        GENERATION,
        "1.0.0",
    )
    assert events == [hashlib.sha256(record).hexdigest()]


@pytest.mark.parametrize(
    "fault",
    [
        "missing_store",
        "missing_key",
        "missing_row",
        "extra_row",
        "duplicate",
        "duplicate_key",
        "held_duplicate",
        "held",
        "review",
        "unknown_tag",
        "stamp",
        "row_generation",
        "holds",
        "trusted",
        "accepted",
        "bad_digest",
        "site",
        "rule",
        "version",
        "generation",
        "unversioned",
        "recipients",
        "hospital",
        "scope",
        "missing_clearance",
        "stale_clearance",
        "held_clearance",
        "other_site",
        "unaccepted_record",
        "bad_json",
    ],
)
def test_refusals_have_one_key_and_do_not_audit_admission(fault: str, admit_screening_inputs: Any) -> None:
    data = inputs()
    actual = deepcopy(data["use"])
    row = data["rows"][0]
    if fault == "missing_store":
        del data["inventory"]["derived"]
    elif fault == "missing_key":
        data["inventory"]["lake"].clear()
    elif fault == "missing_row":
        data["rows"].pop()
    elif fault in ("extra_row", "duplicate", "held_duplicate"):
        extra = dict(row)
        if fault == "extra_row":
            extra["key"] = "unexpected"
        if fault == "held_duplicate":
            extra["review_tag"] = "held"
        data["rows"].insert(0, extra)
    elif fault == "duplicate_key":
        data["inventory"]["lake"].append("row-a")
    elif fault in ("held", "review", "unknown_tag"):
        row["review_tag"] = {"held": "held", "review": "needs_review", "unknown_tag": "maybe"}[fault]
    elif fault == "stamp":
        row["owner_rule_stamp"] = " "
    elif fault == "row_generation":
        row["generation"] = "2026-10-04.g1"
    elif fault == "holds":
        data["holds_released"] = False
    elif fault in ("trusted", "accepted", "bad_digest"):
        data["trusted_digest" if fault == "trusted" else "accepted_digest"] = "b" * 64 if fault != "bad_digest" else ""
    elif fault in ("site", "rule", "version", "generation"):
        actual[{"rule": "ruleset", "version": "rule_version"}.get(fault, fault)] += "2"
    elif fault == "unversioned":
        actual["generation"] = data["use"]["generation"] = GENERATION.partition(".")[0]
    elif fault == "recipients":
        actual["list_to"] = ["someone-else"]
    elif fault == "hospital":
        actual["scope"]["practitioners"] = None
    elif fault == "scope":
        actual["scope"]["practitioners"] = data["use"]["scope"]["practitioners"] = []

    record = b"{}" if fault == "bad_json" else encode(data)
    grant = clearance(record)
    if fault == "missing_clearance":
        grant.clear()
    elif fault == "stale_clearance":
        grant["clearance_id"] = "previous"
    elif fault == "held_clearance":
        grant["state"] = "held"
    elif fault == "other_site":
        grant["site"] = "another-site"
    elif fault == "unaccepted_record":
        grant["accepted_records"] = []
    use = ScreeningUse.model_validate_json(encode(actual))
    with pytest.raises(ScreeningRefused, match=REFUSAL):
        admit_screening_inputs(record, use, DIGEST, encode(grant), lambda _: pytest.fail("audited an admission"))


def test_audit_failure_refuses(admit_screening_inputs: Any) -> None:
    data = inputs()
    record = encode(data)
    use = ScreeningUse.model_validate_json(encode(data["use"]))

    def unavailable(_: str) -> dict[str, str]:
        raise OSError

    with pytest.raises(ScreeningRefused, match=REFUSAL):
        admit_screening_inputs(record, use, DIGEST, encode(clearance(record)), unavailable)
    with pytest.raises(ScreeningRefused, match=REFUSAL):
        admit_screening_inputs(record, use, DIGEST, encode(clearance(record)), lambda _: {})


def test_rule_digest_covers_loaded_content_even_when_version_is_unchanged() -> None:
    rule = Ruleset.load(Path(__file__).resolve().parents[2] / "rulesets" / "GZQO")
    before = rule_digest(rule)
    rule.sql += " "
    assert before != rule_digest(rule)


def test_caller_cannot_supply_admission_authority() -> None:
    from tb_common import screening_inputs

    data = inputs()
    record = encode(data)
    use = ScreeningUse.model_validate(data["use"])
    with pytest.raises((ScreeningRefused, TypeError)):
        invoke: Any = screening_inputs.admit_screening_inputs
        invoke(record, use, DIGEST, encode(clearance(record)), lambda d: {"input_sha": d})
    with pytest.raises(ScreeningRefused, match=REFUSAL):
        invoke()
