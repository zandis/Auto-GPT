"""Site-supplied evidence for tests that explicitly run SCREEN on a synthetic lake."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from adapter.ndjson import read_type
from lake.client import LakeLocal
from orchestrator.scheduler import RESTORE_FLAG
from tb_common.flags import Flags
from tb_common.ruleset import Ruleset
from tb_common.screening_inputs import clearance_path, rule_digest

from tests.inproc_box import Box


def accept_fixture(box: Box, study: str, practitioners: list[str] | None = None) -> tuple[Path, Path]:
    orch = box.orch
    env = orch.cfg.env
    lake = orch.services.lake
    assert isinstance(lake, LakeLocal)
    generation = lake.generation()
    assert generation is not None
    rule = Ruleset.load(orch.rulesets_dir / study)
    scope = rule.manifest.scopes.screen
    routing = rule.manifest.routing
    assert scope is not None and routing is not None
    grant = clearance_path(Path(env.data_dir))
    record = Path(env.data_dir) / "screening-inputs" / generation / study / f"{rule.version}.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    flags = Flags(url=orch.db.url, audit=orch.audit)
    from console.sitestore import SiteStore

    SiteStore(orch.db.url).close()
    if flags.row("derived.stored_read") is None:
        flags.set("derived.stored_read", "off", "fixture-steward", "synthetic fixture configuration")
    if flags.row(RESTORE_FLAG) is None:
        flags.set(RESTORE_FLAG, "released", "fixture-steward", "synthetic fixture ready")

    release = flags.events(RESTORE_FLAG, limit=1)[0]
    clearance_id = f"{release['id']}:{release['at']}"

    # The synthetic site presents opaque owner stamps here. The product never issues them.
    snapshot = lake.snapshot()
    assert snapshot is not None
    directory = lake.lake._source(snapshot)
    lake_keys = [
        f"{path.stem}/{row['id']}"
        for path in sorted(directory.glob("*.ndjson"))
        for row in read_type(directory, path.stem)
    ]
    assert lake_keys
    # The fixture runs the NDJSON builder. It has no OMOP or derived input feed.
    inventory = {"lake": lake_keys, "omop": [], "derived": []}
    rows = [
        {
            "source": source,
            "key": key,
            "owner_rule_stamp": "fixture-owner-v1",
            "review_tag": "released",
            "generation": generation,
        }
        for source, keys in inventory.items()
        for key in keys
    ]
    digest = rule_digest(rule)
    data = {
        "use": {
            "stored_read": flags.row("derived.stored_read"),
            "clearance_id": clearance_id,
            "site": orch.cfg.settings.site.id,
            "ruleset": rule.id,
            "rule_version": rule.version,
            "generation": generation,
            "list_to": sorted(set(routing.list_to or [])),
            "referral_to": routing.referral_to or {},
            "aggregate_to": sorted({*(routing.aggregate_to or []), "crc1@hospa.test"}),
            "scope": {
                "practitioners": practitioners if practitioners is not None else scope.practitioners,
                "departments": [],
                "window_days": scope.appointment_window_days,
                "recent_months": scope.recent_encounter_months,
            },
        },
        "inventory": inventory,
        "rows": rows,
        "holds_released": True,
        "trusted_digest": digest,
        "accepted_digest": digest,
    }
    record.write_text(json.dumps(data), encoding="utf-8")
    clearance: dict[str, Any] = (
        json.loads(grant.read_bytes())
        if grant.exists()
        else {
            "site": orch.cfg.settings.site.id,
            "clearance_id": clearance_id,
            "state": "released",
            "accepted_records": [],
        }
    )
    if clearance["clearance_id"] != clearance_id:
        clearance.update(clearance_id=clearance_id, accepted_records=[])
    clearance["accepted_records"].append(hashlib.sha256(record.read_bytes()).hexdigest())
    grant.write_text(json.dumps(clearance), encoding="utf-8")
    return record, grant
