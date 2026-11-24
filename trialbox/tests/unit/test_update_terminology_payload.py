"""V-18 (D-1182): an update bundle's code systems (payload kind ``terminology``). Only a system the box may carry goes
in, under the command that loads it; the update keeps the tables it replaces aside, loads the new ones, then the
vocabulary and the FHIR store; a rollback puts the kept tables back and takes away what the update added.

Synthetic data only: invented NHI service codes and an invented ATC index (licensed, under a named person)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.terminology import installed as inst

from tools.release import ReleaseError, parse_item
from tools.sign_bundle import build, keygen
from tools.trialbox import update as up
from tools.verify_update import Rejected, verify

PERSON = "Synthetic Person"
NHI = (
    "診療項目代碼,健保支付點數,生效起日,生效迄日,英文項目名稱,中文項目名稱\n{code},1,20200101,29101231,Synthetic,合成\n"
)


@pytest.fixture(autouse=True)
def _no_real_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_DOCKER", "true")


def _nhi(where: Path, code: str, tmp: Path) -> None:
    src = tmp / f"nhi-{code}.csv"
    src.write_text(NHI.format(code=code), encoding="utf-8")
    inst.install_nhi_services(src, where, "2099")


def test_the_kept_tables_come_back_and_what_the_update_added_goes(tmp_path: Path) -> None:
    where = tmp_path / "terminology"
    atc = tmp_path / "atc.csv"
    atc.write_text("ATC code,ATC level name\nV99SY01,synthetic substance\n", encoding="utf-8")
    inst.install_atc(atc, where, accepted_by=PERSON, accepted_on="2026-11-23", version="2099")
    _nhi(where, "ZZ901C", tmp_path)
    before = inst.manifest(where)["tables"]
    keep = tmp_path / "previous" / "B9"
    assert inst.save_tables(where, keep) == ["nhi_service_list"]  # the licensed ATC index never leaves the volume
    assert not (keep / "atc_index.parquet").exists()
    _nhi(where, "ZZ902C", tmp_path)  # the update's new release of the same table
    pcs = tmp_path / "icd10pcs_order_2099.txt"
    pcs.write_text("00001 0016070 1 Synthetic short                                                       "
                   "Synthetic long title\n", encoding="utf-8")  # fmt: skip
    inst.install_icd10pcs(pcs, where, "2099")  # and a system the box did not have
    assert inst.restore_tables(where, keep) == ["nhi_service_list", "icd10pcs"]
    after = inst.manifest(where)["tables"]
    assert after["nhi_service_list"]["sha256"] == before["nhi_service_list"]["sha256"] and "icd10pcs" not in after
    assert after["atc_index"] == before["atc_index"]  # untouched
    assert [r["code"] for r in inst.read_table(where, "nhi_service_list") or []] == ["ZZ901C"]


def test_a_changed_kept_table_is_refused_and_nothing_moves(tmp_path: Path) -> None:
    where = tmp_path / "terminology"
    _nhi(where, "ZZ901C", tmp_path)
    keep = tmp_path / "keep"
    inst.save_tables(where, keep)
    _nhi(where, "ZZ902C", tmp_path)
    (keep / "nhi_service_list.parquet").write_bytes(b"not the kept table")
    with pytest.raises(ValueError, match="not the table it kept"):
        inst.restore_tables(where, keep)
    assert [r["code"] for r in inst.read_table(where, "nhi_service_list") or []] == ["ZZ902C"]


def test_the_bundle_builder_and_the_box_take_only_a_system_the_box_may_carry(tmp_path: Path) -> None:
    assert parse_item("terminology:/x/codes.zip=icd10cm/codes.zip")[2] == "icd10cm/codes.zip"
    for bad in ("terminology:/x/Loinc.csv=loinc/Loinc.csv", "terminology:/x/sct.zip=snomed/sct.zip",
                "terminology:/x/codes.zip"):  # fmt: skip
        with pytest.raises(ReleaseError, match="licensed code system never ships"):
            parse_item(bad)
    priv, pub = keygen(tmp_path / "k")
    src = tmp_path / "Loinc.csv"
    src.write_text("synthetic\n", encoding="utf-8")
    bundle = tmp_path / "b.tar"
    build(priv, "B1", [("terminology", src, "loinc/Loinc.csv")], bundle)
    with pytest.raises(Rejected, match="a licensed code system never ships"):
        verify(bundle, pub, None, trust_file=tmp_path / "u" / "trust.json",
               installed_file=tmp_path / "u" / "installed.json")  # fmt: skip


class Recorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kw: Any) -> str:
        self.calls.append(list(argv))
        return json.dumps({"release": "TL-000000000000", "fhir": [], "omop": [], "problems": []}) if (
            "tools.terminology_load" in argv) else ""  # fmt: skip


def test_the_update_keeps_aside_loads_with_no_network_then_both_readers(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_IMAGE=trialbox-py:test\n", encoding="utf-8")
    stage = tmp_path / "stage"
    (stage / "terminology" / "nhi-services").mkdir(parents=True)
    (stage / "terminology" / "nhi-services" / "services.csv").write_text(NHI.format(code="ZZ903C"), "utf-8")
    (stage / "terminology" / "nhi-services" / "VERSION").write_text("2099\n", encoding="utf-8")
    plan = up.Plan("B9", "0" * 64, "signer", [], stage)
    rec = Recorder()
    box = up.ComposeBox(deploy, rec)
    assert box.terminology(plan) == ["nhi-services/services.csv"]
    save, load, readers = rec.calls[0], rec.calls[1], rec.calls[-1]
    assert save[:5] == ["docker", "run", "--rm", "--network", "none"] and f"{deploy / 'terminology/previous/B9'}:/keep" \
        in " ".join(save)  # fmt: skip
    assert load[:5] == ["docker", "run", "--rm", "--network", "none"]
    assert load[-4:] == ["nhi-services", "/in/services.csv", "--version", "2099"]
    assert "tools.terminology_load" in readers and "criteria-compiler" in readers
    assert json.loads((deploy / "site" / "terminology-load.json").read_text("utf-8"))["release"] == "TL-000000000000"
