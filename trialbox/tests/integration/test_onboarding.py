"""Phase 9 DoD "a new site can be configured without code changes" (SPEC §12).

Site C exports the synthetic hospital B under its own names: other file names, other column names (the template's
local names), its own codes (sex 1/2, visit type O/I/E, NHI result Y/N/P) and a different MRN format. Onboarding uses
only configuration:

1. ``tools/settings_wizard.py --answers`` → a validated settings.yaml and a 0600 .env;
2. the csv mapping template, copied unchanged (its ``rename`` / ``values`` already describe site C), plus the lab
   lookup CSV;
3. ``tools/mapping_check.py`` passes on the export;
4. the nightly ingest passes and the lake holds exactly what site B's export gives with the demo mapping;
5. ``FEAS GZQO`` by mail from site C's CRC returns the feasibility report with the same funnel as site B.
"""

from __future__ import annotations

import csv
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.inproc_box import ingest_site, make_box

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "services/adapter/mapping/templates/csv_site.yaml"
DEMO = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
LOOKUP = ROOT / "services/adapter/mapping/tw_core/lab_local_to_loinc.csv"
ANSWERS = ROOT / "tests/fixtures/onboarding/site_c_answers.yaml"
AUTH_C = "mx.hospc.test; spf=pass smtp.mailfrom=hospc.test; dkim=pass header.d=hospc.test; dmarc=pass"
KEY_B = b"trialbox-test-site-key-B-0123456789abcd"
KEY_C = b"trialbox-test-site-key-C-0123456789abcd"
MRN_COLUMNS = {"mrn"}


def make_site_c(src: Path, dst: Path) -> None:
    """Site B's canonical export rewritten with the template's local names, codes and a 'C' MRN prefix."""
    tpl = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    dst.mkdir(parents=True)
    for table, spec in tpl["tables"].items():
        path = src / f"{table}.csv"
        if not path.exists():
            continue
        to_local = {canon: local for local, canon in (spec.get("rename") or {}).items()}
        encode = {col: {canon: local for local, canon in mp.items()} for col, mp in (spec.get("values") or {}).items()}
        with path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        cols = list(rows[0]) if rows else []
        out = []
        for r in rows:
            row: dict[str, Any] = {}
            for c in cols:
                v = r[c]
                if c in MRN_COLUMNS and v:
                    v = "C" + v[1:]
                if c in encode and v in encode[c]:
                    v = encode[c][v]
                row[to_local.get(c, c)] = v
            out.append(row)
        with (dst / f"{spec['source']}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=[to_local.get(c, c) for c in cols])
            w.writeheader()
            w.writerows(out)


@pytest.fixture(scope="module")
def site(synth_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from tools.settings_wizard import build, write

    tmp = tmp_path_factory.mktemp("onboard")
    export = tmp / "export-c"
    make_site_c(synth_dir / "site-b", export)
    # mapping: the template as is (only `extends` points at the installed TW Core definitions) + lab lookup
    mdir = tmp / "mapping" / "tw_core"
    mdir.mkdir(parents=True)
    text = TEMPLATE.read_text(encoding="utf-8").replace("extends: ../tw_core/demo_his.yaml", f"extends: {DEMO}")
    (mdir / "site_c.yaml").write_text(text, encoding="utf-8")
    shutil.copy(LOOKUP, mdir / LOOKUP.name)
    # settings via the wizard
    answers = yaml.safe_load(ANSWERS.read_text(encoding="utf-8"))
    answers["mapping"] = str(mdir / "site_c.yaml")
    settings, env, warnings = build(answers)
    assert warnings == []  # site C answers are consistent
    write(settings, env, tmp / "settings.yaml", tmp / ".env")
    return {"tmp": tmp, "export": export, "mapping": mdir / "site_c.yaml", "settings": settings, "env": tmp / ".env"}


def test_wizard_output(site: dict[str, Any]) -> None:
    from tb_common.config import load_settings

    s = load_settings(site["tmp"] / "settings.yaml")
    assert s.site.id == "DEMO-C" and s.internal_domains == ["hospc.test"] and s.mrn_regex == r"^C\d{7}$"
    assert s.cohort is not None and s.cohort.root_address == "trialbox@hospa.test" and not s.cohort.alliance_root
    assert oct(site["env"].stat().st_mode & 0o777) == "0o600"
    env = dict(line.split("=", 1) for line in site["env"].read_text().splitlines() if "=" in line and line[0] != "#")
    assert env["MAIL_INTAKE_ADDR"] == "trialbox@hospc.test" and len(env["MINIO_SECRET_KEY"]) >= 24


def test_wizard_refuses_inconsistent_answers() -> None:
    from tools.settings_wizard import WizardError, build

    answers = yaml.safe_load(ANSWERS.read_text(encoding="utf-8"))
    bad = {**answers, "mapping": str(DEMO), "practitioners": {"P1": {"name": "x", "department": "NOPE"}}}
    with pytest.raises(WizardError, match="department 'NOPE'"):
        build(bad)
    with pytest.raises(WizardError, match="mrn_regex"):
        build({**answers, "mapping": str(DEMO), "mrn_regex": "(["})


def test_mapping_check_passes(site: dict[str, Any]) -> None:
    from tools.mapping_check import check

    rep = check(site["mapping"], "csv", str(site["export"]))
    assert rep["passed"], json.dumps(rep["tables"], ensure_ascii=False)[:2000]
    assert rep["tables"]["patient"]["rows_read"] > 0 and not rep["tables"]["lab"]["unmapped_codes"]


def test_ingest_and_feas_without_code_changes(site: dict[str, Any], synth_dir: Path, tmp_path: Path) -> None:
    from adapter.pipeline import AdapterConfig, run_ingest
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake
    from tb_contracts import RebuildResult

    tmp = site["tmp"]
    sec_c = tmp / "sec-c"
    sec_c.mkdir(exist_ok=True)
    (sec_c / "site_hmac.key").write_bytes(KEY_C)
    lake_c = tmp / "lake-c"

    def rebuild(snap: str, nd: Path) -> RebuildResult:
        st = Lake(lake_c).rebuild(snap, HashEmbedder(), nd)
        return RebuildResult(
            snapshot=st.snapshot, tables=st.tables, chunks=st.chunks, embedded_new=st.embedded_new, seconds=st.seconds
        )

    cfg = AdapterConfig(
        lake_dir=lake_c, secrets_dir=sec_c, mapping_path=site["mapping"], site_id="DEMO-C", rebuild=rebuild
    )
    rep_c = run_ingest(cfg, "csv", str(site["export"]), snapshot="2026-10-04", load_fhir=False, validate=False)
    assert rep_c.passed, rep_c.errors
    sec_b = tmp_path / "sec-b"
    sec_b.mkdir()
    (sec_b / "site_hmac.key").write_bytes(KEY_B)
    rep_b = ingest_site(synth_dir / "site-b", tmp_path / "lake-b", sec_b, "2026-10-04", "DEMO-B")
    assert rep_c.counts == rep_b.counts  # nothing lost or invented by the site mapping
    sql = (
        "SELECT (SELECT count(*) FROM patient) p, (SELECT count(*) FROM patient WHERE sex = 'female') f, "
        "(SELECT count(*) FROM condition) c, (SELECT count(*) FROM encounter WHERE class = 'AMB') amb, "
        "(SELECT count(*) FROM claim WHERE outcome = 'approved') ok, (SELECT count(*) FROM consent) cons"
    )
    assert Lake(lake_c).query(sql).to_pylist() == Lake(tmp_path / "lake-b").query(sql).to_pylist()
    # FEAS by mail at site C, configured only by the wizard output
    settings = yaml.safe_load((tmp / "settings.yaml").read_text(encoding="utf-8"))
    box = make_box(tmp / "box", lake_c, sec_c, date(2026, 10, 5), settings_update=settings)
    assert box.mail("FEAS GZQO", sender="crc@hospc.test", auth=AUTH_C) == "Processed"
    box.orch.drain()
    job = box.orch.db.find(type_="FEAS")[0]
    assert job.state == "done", job.error
    names = {o.filename for o in job.outputs or []}
    assert any(n.endswith(".pdf") for n in names) and any(n.endswith(".xlsx") for n in names)
