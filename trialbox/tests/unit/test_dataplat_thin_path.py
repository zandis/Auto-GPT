"""L2–L5 thin path, MPI and lineage (spec v4 §5.3, §5.13, §5.14, §5.15, DP-32, DP-35, DP-39, PRIV-10; S1-04)."""

from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import re
import shutil
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from dataplat import curated
from dataplat.common import fixed_clock
from dataplat.lineage import check_complete, expected_jobs
from dataplat.mpi import MergeEvent, Mpi, SiteKeys
from dataplat.pipeline import PipelineResult, run_pipeline
from dataplat.serving import Serving, ServingError
from tb_common.crypto import ed25519_generate
from tb_contracts.dataclass import DataClass

ROOT = Path(__file__).resolve().parents[2]
SITE_KEY = b"trialbox-test-site-key-0123456789abcdef"
SITE_ID = "DEMO-A"
CLOCK = fixed_clock(datetime(2026, 10, 5, 2, 0, tzinfo=UTC))
SIGNING = ed25519_generate()
MIMIC_DIR = ROOT / ".cache" / "open_data" / "mimic-iv-fhir-demo"


def counter_ids() -> Callable[[], str]:
    it = itertools.count(1)
    return lambda: f"{next(it):032x}"


def _run(src: Path, work: Path, snapshot: str = "2026-10-04", **kw: Any) -> PipelineResult:
    return run_pipeline(
        src,
        work,
        site_key=SITE_KEY,
        clock=CLOCK,
        snapshot=snapshot,
        signing_key=SIGNING,
        id_factory=counter_ids(),
        **kw,
    )


@pytest.fixture(scope="module")
def published(synth_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> PipelineResult:
    return _run(synth_dir / "site-a", tmp_path_factory.mktemp("dp_thin") / "work")


def _mrns(synth_dir: Path) -> set[str]:
    return {line.split(",")[0] for line in (synth_dir / "site-a" / "patient.csv").read_text().splitlines()[1:]}


@pytest.mark.req("S1-04", "DP-01", "DP-32")
def test_site_a_becomes_a_signed_pinned_snapshot(published: PipelineResult) -> None:
    res = published
    assert res.outcome == "PUBLISH" and res.manifest is not None
    m = res.manifest
    assert curated.verify(m)
    assert m.data_class.data_class == DataClass.D3
    assert m.contracts["demo_his/lab"] == "1.0.0" and m.mapping_spec["demo_his"].startswith("sha256:")
    assert res.batch is not None and m.batches == [res.batch.batch_id]
    assert m.publish_gate == res.gate.gate_id and m.data_cut_per_source == {"demo_his": "2026-10-05T02:00:00Z"}
    assert m.tables["Patient"].rows == 600 and m.lake_tables["patient"] == 600
    # counts carry through L2 → L3 → L4 unchanged (no merges, no identity quarantine)
    assert res.counts["L2"] == res.counts["L3"] == res.counts["L4"]
    # readers resolve the snapshot only through the signed manifest (DP-32)
    serving = Serving(res.workdir / "l5", res.workdir / "l4", res.workdir / "l4" / "lake", tz="Asia/Taipei")
    assert serving.current() == res.current
    con = serving.connect()
    try:
        row = con.execute("SELECT count(*) FROM patient").fetchone()
        assert row is not None and row[0] == 600
    finally:
        con.close()


@pytest.mark.req("PRIV-10", "DP-35")
def test_no_mrn_leaves_l0_and_the_mpi(published: PipelineResult, synth_dir: Path) -> None:
    mrns = _mrns(synth_dir)
    work = published.workdir
    texts = [p.read_text(encoding="utf-8") for p in (work / "l4" / "snapshots").rglob("*.ndjson")]
    texts += [(work / "lineage" / "events.jsonl").read_text(encoding="utf-8")]
    texts += [p.read_text(encoding="utf-8") for p in (work / "l4" / "snapshots").rglob("manifest.json")]
    quoted = re.compile(r'"(\d{8})"')
    found = {v for t in texts for v in quoted.findall(t)}
    assert not (found & mrns)
    # the MPI holds MRNs only as HMAC lookups and AES-GCM ciphertext
    raw = (work / "vault" / "mpi.sqlite").read_bytes()
    assert not any(m.encode() in raw for m in list(mrns)[:50])


@pytest.mark.req("PRIV-10", "DP-35")
def test_pid_is_hmac_of_kpid_over_a_random_mpi_id(tmp_path: Path) -> None:
    keys = SiteKeys.derive(SITE_KEY, SITE_ID)
    with Mpi(tmp_path / "a.sqlite", keys, clock=CLOCK) as a, Mpi(tmp_path / "b.sqlite", keys, clock=CLOCK) as b:
        ma, mb = a.register("10000001"), b.register("10000001")
        assert ma != mb and len(ma) == 32  # random 128-bit, never derived from the MRN
        assert a.register("10000001") == ma  # stable once registered
        k_pid = HKDF(algorithm=hashes.SHA256(), length=32, salt=SITE_ID.encode(), info=b"tb/pid/v1").derive(SITE_KEY)
        assert a.pid(ma) == hmac.new(k_pid, ma.encode(), hashlib.sha256).hexdigest()[:32]
        assert a.mrns(ma) == ["10000001"]


@pytest.mark.req("S1-04", "DP-35", "PRIV-10")
def test_a40_merge_maps_two_mrns_to_one_pid(synth_dir: Path, tmp_path: Path) -> None:
    keep, gone = "10000001", "10000002"
    res = _run(synth_dir / "site-a", tmp_path / "work", merges=[MergeEvent(gone, keep, "A40^MSG00001")])
    assert res.outcome == "PUBLISH" and res.manifest is not None
    assert res.counts["L3"]["Patient"] == res.counts["L2"]["Patient"] - 1 == 599
    keys = SiteKeys.derive(SITE_KEY, SITE_ID)
    with Mpi(tmp_path / "work" / "vault" / "mpi.sqlite", keys) as mpi:
        a, b = mpi.lookup(keep), mpi.lookup(gone)
        assert a is not None and a == b
        pid = mpi.pid(a)
        assert mpi.mrns(a) == sorted([gone, keep])
        assert [r for r in mpi.aliases() if r[1] == pid and r[2] == "merge"]
    # both patients' encounters now point at the one surviving pid
    enc = [
        json.loads(x)
        for x in (tmp_path / "work" / "l4" / "snapshots" / "2026-10-04" / "ndjson" / "Encounter.ndjson")
        .read_text()
        .splitlines()
    ]
    src = (synth_dir / "site-a" / "encounter.csv").read_text().splitlines()[1:]
    n_both = sum(1 for line in src if line.split(",")[1] in (keep, gone))
    assert sum(1 for e in enc if e["subject"]["reference"] == f"Patient/{pid}") == n_both
    eq = next(e for e in res.reconciliation.equations if e.level == "L2→L3") if res.reconciliation else None
    assert eq is not None and eq.verdict == "pass"


@pytest.mark.req("S1-04", "DP-39")
def test_lineage_is_complete_and_openlineage_shaped(published: PipelineResult) -> None:
    assert published.lineage is not None and published.lineage.complete, published.lineage
    assert published.manifest is not None
    events = [json.loads(x) for x in (published.workdir / "lineage" / "events.jsonl").read_text().splitlines()]
    for e in events:
        assert set(e) == {"eventType", "eventTime", "producer", "schemaURL", "run", "job", "inputs", "outputs"}
        assert e["eventType"] in ("START", "COMPLETE", "FAIL")
        assert e["eventTime"].endswith("Z")
        uuid.UUID(e["run"]["runId"])
        assert e["job"]["namespace"] == "trialbox://DEMO-A"
        for facet in e["run"]["facets"].values():
            assert "_producer" in facet and "_schemaURL" in facet
    jobs = {e["job"]["name"] for e in events}
    assert set(expected_jobs(published.manifest)) <= jobs
    assert {"tb.l0.land.demo_his", "tb.l1.validate.demo_his.lab", "tb.l2.standardise.demo_his"} <= jobs
    assert set(published.manifest.lineage_runs) == {e["run"]["runId"] for e in events}
    # a broken chain is reported: drop the L3 run and the check names what is missing
    broken = [e for e in events if e["job"]["name"] != "tb.l3.pseudonymise"]
    chk = check_complete(broken, published.manifest)
    assert not chk.complete
    assert any("tb.l3.pseudonymise" in m for m in chk.missing)


@pytest.mark.req("S1-04", "DP-32")
def test_serving_pin_and_rollback(synth_dir: Path, published: PipelineResult, tmp_path: Path) -> None:
    work = tmp_path / "work"
    shutil.copytree(published.workdir, work)
    res2 = _run(synth_dir / "site-a", work, snapshot="2026-10-05")
    assert res2.outcome == "PUBLISH" and res2.current is not None
    assert res2.current.snapshot_id == "snap_2026-10-05"
    assert res2.manifest is not None and res2.manifest.previous_snapshot == "snap_2026-10-04"
    serving = Serving(work / "l5", work / "l4", work / "l4" / "lake", tz="Asia/Taipei", clock=CLOCK)
    back = serving.pin_previous("ops: lake pin T-1")
    assert back.snapshot_id == "snap_2026-10-04"
    assert (work / "l4" / "lake" / "CURRENT").read_text() == "2026-10-04"
    # a tampered manifest is refused by the reader
    mpath = work / "l4" / "snapshots" / "2026-10-04" / "manifest.json"
    mpath.chmod(0o644)
    mpath.write_text(mpath.read_text().replace('"rows":600', '"rows":601'))
    with pytest.raises(ServingError):
        serving.manifest()


@pytest.mark.req("S1-04")
def test_second_run_is_reproducible(published: PipelineResult, synth_dir: Path, tmp_path: Path) -> None:
    again = _run(synth_dir / "site-a", tmp_path / "work")
    a, b = published.manifest, again.manifest
    assert a is not None and b is not None
    assert a.tables == b.tables and a.lake_sha256 == b.lake_sha256
    assert curated.manifest_sha(a) == curated.manifest_sha(b)


@pytest.mark.skipif(not (MIMIC_DIR / "fhir" / "MimicPatient.ndjson.gz").exists(), reason="MIMIC demo not fetched")
@pytest.mark.req("S1-04", "DP-25", "DP-39")
def test_mimic_demo_becomes_a_snapshot_with_full_lineage(tmp_path: Path) -> None:
    """Runs only where ``tools/fetch_open_data.py`` has fetched the demo into .cache/open_data (never fetched here)."""
    res = run_pipeline(
        MIMIC_DIR,
        tmp_path / "work",
        kind="mimic_fhir",
        site_key=b"trialbox-open-data-demo-key-0123456789abcdef",
        clock=fixed_clock(datetime(2026, 9, 30, 12, 0, tzinfo=UTC)),
        snapshot="2026-09-30",
        signing_key=SIGNING,
        id_factory=counter_ids(),
    )
    assert res.outcome == "PUBLISH", res.blocking_reasons
    assert res.validation is not None and not res.validation.blocking_reasons  # 0 blocking DQ errors
    assert res.lineage is not None
    assert res.lineage.complete, res.lineage.missing
    assert res.manifest is not None and res.manifest.tables["Patient"].rows == 100
