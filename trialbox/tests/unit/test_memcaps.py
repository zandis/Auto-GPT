"""Memory caps of the adapter and the lake sized from the patient count (T-692, D-473; scale review F-05, OD-10).

``deploy/install.sh`` writes ``TB_MEM_ADAPTER`` and ``TB_MEM_LAKE`` from the measured record and the patient count;
a cap set by hand is kept; ``trialbox doctor`` fails when a cap is below the need. Synthetic counts only."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools.trialbox import doctor, memcaps

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]


def _record(tmp: Path, adapter_kb: float = 0.0, lake_kb: float = 100.0) -> Path:
    doc = {
        "format": memcaps.FORMAT,
        "measured_at": "2026-11-12T00:00:00+00:00",
        "services": {
            "adapter": {"fixed_mb": 100, "per_patient_kb": adapter_kb},
            "lake": {"fixed_mb": 500, "per_patient_kb": lake_kb},
        },
    }
    p = tmp / "ingest_memory.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _lake(tmp: Path, n: int) -> Path:
    lake = tmp / "lake"
    nd = lake / "ndjson" / "2026-10-04"
    nd.mkdir(parents=True)
    (nd / "Patient.ndjson").write_text("".join(f'{{"id": "p{i}"}}\n' for i in range(n)), encoding="utf-8")
    (lake / "CURRENT").write_text("2026-10-04\n", encoding="utf-8")
    return lake


def test_the_shipped_record_is_measured_and_the_compose_defaults_are_read() -> None:
    rec = memcaps.load_record()
    assert rec["measured_at"] and set(rec["services"]) == {"adapter", "lake"}
    assert memcaps.compose_default("TB_MEM_ADAPTER") == "6g" and memcaps.compose_default("TB_MEM_LAKE") == "8g"
    assert memcaps.size_mb("6g") == 6144 and memcaps.size_mb("512m") == 512 and memcaps.size_mb("1048576") == 1


def test_the_need_grows_with_the_patients_and_never_drops_below_the_compose_default(tmp_path: Path) -> None:
    rec = memcaps.load_record(_record(tmp_path))
    small = memcaps.need_mb(1000, rec, {})
    assert small == {"adapter": 6144, "lake": 8192}  # the defaults: a small hospital needs less
    big = memcaps.need_mb(500_000, rec, {"TB_VALIDATOR_XMX": "3g"})
    # the lake: (500 MB + 100 KB x 500,000) / 0.6 (DuckDB takes 40 % of the cap)
    assert big["lake"] == pytest.approx((500 + 100 * 500_000 / 1024) / 0.6, abs=1)
    assert big["adapter"] == 6144  # the adapter streams: its need does not grow


def test_the_count_is_the_lake_s_current_snapshot_else_the_setting(tmp_path: Path) -> None:
    assert memcaps.patients({"TB_SITE_PATIENTS": "50000"}, _lake(tmp_path, 7)) == (7, "lake snapshot 2026-10-04")
    assert memcaps.patients({"TB_SITE_PATIENTS": "50000"}, None) == (50000, "TB_SITE_PATIENTS")
    assert memcaps.patients({}, None)[0] is None
    with pytest.raises(ValueError, match="TB_SITE_PATIENTS"):
        memcaps.patients({"TB_SITE_PATIENTS": "lots"}, None)


def test_install_writes_the_caps_and_keeps_one_set_by_hand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _record(tmp_path)
    monkeypatch.setattr(memcaps, "RECORD", rec)
    env = tmp_path / ".env"
    env.write_text("TB_ENV=PRODUCTION\nTB_SITE_PATIENTS=500000\n", encoding="utf-8")
    assert memcaps.main(["--env-file", str(env), "--write"]) == 0
    first = memcaps._parse_env(env.read_text(encoding="utf-8"))
    lake_mb = memcaps.size_mb(first["TB_MEM_LAKE"])
    assert lake_mb > 8192 and first["TB_MEM_ADAPTER"] == "6144m"
    # the hospital grows: install sizes its own caps again
    env.write_text(env.read_text(encoding="utf-8").replace("500000", "900000"), encoding="utf-8")
    memcaps.main(["--env-file", str(env), "--write"])
    again = memcaps._parse_env(env.read_text(encoding="utf-8"))
    assert memcaps.size_mb(again["TB_MEM_LAKE"]) > lake_mb
    # the operator sets the lake's cap by hand: kept; the adapter's is still sized
    text = re.sub(r"^TB_MEM_LAKE=.*$", "TB_MEM_LAKE=96g", env.read_text(encoding="utf-8"), flags=re.M)
    env.write_text(text, encoding="utf-8")
    memcaps.main(["--env-file", str(env), "--write"])
    kept = memcaps._parse_env(env.read_text(encoding="utf-8"))
    assert kept["TB_MEM_LAKE"] == "96g" and kept["TB_MEM_ADAPTER"] == "6144m"
    assert env.read_text(encoding="utf-8").count(memcaps.MARKER) == 1


def test_no_count_leaves_the_compose_defaults(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env = tmp_path / ".env"
    env.write_text("TB_ENV=DEV\n", encoding="utf-8")
    assert memcaps.main(["--env-file", str(env), "--write"]) == 0
    assert "TB_MEM_" not in env.read_text(encoding="utf-8") and "compose defaults stay" in capsys.readouterr().out


def test_doctor_fails_a_cap_below_the_need(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "measured").mkdir(parents=True)
    _record(deploy / "measured")
    (deploy / "docker-compose.yml").write_text((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    lake = _lake(tmp_path, 3)
    base = {"TB_ENV": "PRODUCTION"}
    ok = doctor.check_memory_caps(doctor.DoctorInputs(env=base, deploy=deploy, ingest_lake=lake))
    assert ok.status == "PASS" and "3 patients (lake snapshot 2026-10-04)" in ok.detail
    env = {**base, "TB_SITE_PATIENTS": "500000"}
    low = doctor.check_memory_caps(doctor.DoctorInputs(env=env, deploy=deploy))
    assert low.status == "FAIL" and "TB_MEM_LAKE 8192 MB <" in low.detail
    sized = memcaps.need_mb(500_000, memcaps.load_record(deploy / "measured" / "ingest_memory.json"), env)
    env["TB_MEM_LAKE"] = f"{sized['lake']}m"
    assert doctor.check_memory_caps(doctor.DoctorInputs(env=env, deploy=deploy)).status == "PASS"
    none = doctor.check_memory_caps(doctor.DoctorInputs(env=base, deploy=deploy))
    assert none.status == "WARN"
    gone = doctor.check_memory_caps(doctor.DoctorInputs(env=base, deploy=tmp_path / "elsewhere"))
    assert gone.status == "WARN" and "not checked" in gone.detail
