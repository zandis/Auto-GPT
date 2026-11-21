"""One night through the adapter, in process, for the tools that used to drive the retired data platform (T-659b).

The box has one ingest path, ``services/adapter`` (D-370, D-381). The end-to-end tools (``tools.cascade_e2e``,
``tools.trialbox eval ingest_fhir_demo``, the test bench, ``tools.bench``) run a night of open or synthetic data
through it here, with the data contracts on, a local lake built with the hash embedder, and the pid map in the run's
trial database (``tools.pglocal``). D0 and synthetic data only.

    night = run_local(Path("tests/fixtures/synthetic_patients/site-a"), Path("out"), snapshot="2026-10-04")
    night.published, night.gate.outcome, night.blocking_reasons, night.lake_dir, night.lineage_complete

A ``csv`` source is a synthetic site export (``tools/make_fixtures.py``) mapped by the demo HIS mapping; a
``mimic_fhir`` source is the MIMIC-IV FHIR demo, normalised (``adapter.mapping.mimic``) and read as ``fhir_bulk``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from tb_common.config import Config

ROOT = Path(__file__).resolve().parents[1]
DEMO_MAPPING = ROOT / "services" / "adapter" / "mapping" / "tw_core" / "demo_his.yaml"
Kind = Literal["csv", "mimic_fhir"]

# the MIMIC demo defaults of tools/open_data_e2e.py (run date 2026-10-01, 36-month FEAS lookback)
MIMIC_RUN_DATE = date(2026, 10, 1)
MIMIC_LOOKBACK_MONTHS = 36
MIMIC_TZ = "America/New_York"


def mimic_default_window(
    run_date: date = MIMIC_RUN_DATE, lookback_months: int = MIMIC_LOOKBACK_MONTHS
) -> tuple[date, date]:
    """The normaliser window of the open-data run: last encounters land inside the FEAS lookback."""
    from tb_common.timeutil import add_months, month_ends

    idx = month_ends(run_date, lookback_months)
    return add_months(idx[0], -1) + timedelta(days=45), idx[-1] - timedelta(days=20)


@dataclass
class LocalNight:
    """What one local night gives back: the adapter's report, its one gate record, the contract checks, lineage."""

    report: Any  # tb_contracts.IngestReport
    gate: Any  # tb_contracts.landing.PublishGateRecord
    validation: Any  # tb_contracts.landing.ValidationReport | None (None: no contracts for this source)
    lineage: dict[str, Any]
    lake_dir: Path
    night_dir: Path
    snapshot: str
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    quarantine: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def published(self) -> bool:
        return bool(self.report.passed)

    @property
    def outcome(self) -> str:
        return str(self.gate.outcome)

    @property
    def blocking_reasons(self) -> list[str]:
        return [r.value for r in self.gate.blocking_reasons]

    @property
    def lineage_complete(self) -> bool:
        from adapter.governance import lineage_complete

        return lineage_complete(self.lineage)


def run_local(
    source_dir: Path,
    work: Path,
    *,
    kind: Kind = "csv",
    site_id: str | None = None,
    site_key: bytes,
    snapshot: str,
    tz: str | None = None,
    mimic_window: tuple[date, date] | None = None,
    contracts: bool = True,
    validate: bool = True,
    screening_site: Config | None = None,
) -> LocalNight:
    """Run one night of ``source_dir`` through ``adapter.pipeline.run_ingest`` into ``work/lake``."""
    from adapter import governance
    from adapter.ndjson import snapshot_dir
    from adapter.pipeline import COMPLETENESS, AdapterConfig, run_ingest
    from adapter.validate.validator import StructuralValidator
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake
    from tb_contracts import RebuildResult
    from tb_contracts.landing import PublishGateRecord, ValidationReport

    from tools import pglocal

    work.mkdir(parents=True, exist_ok=True)
    tz = tz or ("Asia/Taipei" if kind == "csv" else MIMIC_TZ)
    if screening_site is not None:
        if site_id and site_id != screening_site.settings.site.id:
            raise ValueError("local night site differs from the installed site")
        site_id = screening_site.settings.site.id
    site_id = site_id or ("DEMO-A" if kind == "csv" else "MIMIC-DEMO")
    secrets = Path(screening_site.env.secrets_dir) if screening_site else work / "secrets"
    secrets.mkdir(parents=True, exist_ok=True)
    key_path = secrets / "site_hmac.key"
    if screening_site:
        from tb_common.crypto import load_key

        if load_key(key_path) != site_key:
            raise ValueError("local night site key differs from the installed key")
    else:
        key_path.write_bytes(site_key)
    lake_dir = work / "lake"

    def rebuild(snap: str, nd: Path) -> RebuildResult:
        st = Lake(lake_dir, tz).rebuild(snap, HashEmbedder(), nd)
        return RebuildResult(
            snapshot=st.snapshot,
            tables=st.tables,
            chunks=st.chunks,
            embedded_new=st.embedded_new,
            seconds=st.seconds,
            generation=st.generation,
        )

    if kind == "csv":
        source_kind, path = "csv", source_dir
    else:
        from adapter.mapping.mimic.normalise import MimicNormaliser, MimicTables

        fhir = source_dir / "fhir" if (source_dir / "fhir").is_dir() else source_dir
        ws, we = mimic_window or mimic_default_window()
        path = work / "bulk"
        MimicNormaliser(MimicTables.load(), ws, we).run(fhir, path)
        source_kind = "fhir_bulk"
    cfg = AdapterConfig(
        lake_dir=lake_dir,
        screening_site=screening_site,
        secrets_dir=secrets,
        mapping_path=DEMO_MAPPING if kind == "csv" else work / "unused-mapping.yaml",
        site_id=site_id,
        tz=tz,
        audit_dir=work / "audit",
        rebuild=rebuild,
        # MIMIC is not TW Core: its structural error rate is reported, not gated (as in tools/open_data_e2e.py)
        validation_max_pct=0.5 if kind == "csv" else 100.0,
        db_url=pglocal.for_work(work),
        contracts_dir=governance.DEMO_HIS if contracts and kind == "csv" else None,
    )
    report = run_ingest(
        cfg, source_kind, str(path), snapshot=snapshot, load_fhir=False, validate=validate,
        validator=StructuralValidator(),
    )  # fmt: skip
    night = snapshot_dir(lake_dir, snapshot)
    gate = PublishGateRecord.model_validate_json((night / governance.GATE).read_text(encoding="utf-8"))
    crep_path = night / governance.CONTRACT_REPORT
    crep = ValidationReport.model_validate_json(crep_path.read_text(encoding="utf-8")) if crep_path.exists() else None
    lineage = json.loads((night / governance.LINEAGE).read_text(encoding="utf-8"))
    comp = json.loads((night / COMPLETENESS).read_text(encoding="utf-8"))
    counts = {"source": {t: int(v["rows"]) for t, v in comp.get("tables", {}).items()}, "snapshot": dict(report.counts)}
    if crep is not None:
        counts["accepted"] = {t.table: t.accepted for t in crep.tables}
    quarantine = {t.table: dict(t.quarantine_by_reason) for t in crep.tables if t.quarantined} if crep else {}
    return LocalNight(report, gate, crep, lineage, lake_dir, night, snapshot, counts, quarantine)


__all__ = ["MIMIC_TZ", "LocalNight", "mimic_default_window", "run_local"]
