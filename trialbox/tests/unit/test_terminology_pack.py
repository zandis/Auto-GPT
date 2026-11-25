"""M2 (V-19): the scheduled code-system update: a signed pack is checked, applied all-or-nothing, and reversible."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from criteria_compiler.terminology import installed
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools import terminology_pack as tp

DAY = datetime(2026, 12, 1, 0, 30)
NIGHT_NOW = datetime(2026, 12, 1, 3, 0)


@dataclass
class Row:
    id: str
    status: str


REGISTER = [Row("trialbox-terminology", "own-work"), Row("loinc", "cleared"), Row("atc-index", "site-loaded")]
KEY = Ed25519PrivateKey.generate()
KEYS = {"k": KEY.public_key()}


def _parquet(path: Path, codes: list[str]) -> None:
    pq.write_table(pa.table({"code": codes, "display": [c.lower() for c in codes]}), path)


def make_pack(root: Path, version: str, *, tables: dict[str, list[str]] | None = None, register_id: str = "trialbox-terminology",
              bad_hash: bool = False, sign: bool = True) -> Path:  # fmt: skip
    pack = root / f"pack-{version}"
    pack.mkdir(parents=True)
    lines = {}
    for name, codes in (tables or {"department": ["RHEU", "NEUR", "IMG"]}).items():
        _parquet(pack / f"{name}.parquet", codes)
        sha = hashlib.sha256((pack / f"{name}.parquet").read_bytes()).hexdigest()
        lines[name] = {"file": f"{name}.parquet", "sha256": "0" * 64 if bad_hash else sha, "rows": len(codes),
                       "version": version, "licence": "TrialBox own work", "register_id": register_id}  # fmt: skip
    body = json.dumps({"version": version, "tables": lines}).encode()
    (pack / tp.PACK).write_bytes(body)
    if sign:
        (pack / tp.SIG).write_bytes(KEY.sign(body))
    return pack


@pytest.fixture
def box(tmp_path: Path) -> Path:
    term = tmp_path / "terminology"
    term.mkdir()
    src = tmp_path / "old.csv"
    src.write_text("code,display\nRHEU,rheu\n", encoding="utf-8")
    _parquet(tmp_path / "department.parquet", ["RHEU"])
    sha = hashlib.sha256((tmp_path / "department.parquet").read_bytes()).hexdigest()
    (term / "department.parquet").write_bytes((tmp_path / "department.parquet").read_bytes())
    (term / installed.MANIFEST).write_text(
        json.dumps({"tables": {"department": {"sha256": sha, "rows": 1, "version": "old"}}})
    )
    return term


def _go(pack: Path, box: Path, tmp: Path, readers: Any = None, now: datetime = DAY, night: str = "", register: Any = None) -> tuple[tuple[str, str], list[Any]]:  # fmt: skip
    log: list[Any] = []
    calls: list[Path] = []

    def rd(d: Path) -> dict[str, Any]:
        calls.append(d)
        return readers(len(calls)) if readers else {"problems": [], "fhir": [], "omop": []}

    out = tp.run(
        pack, box, tmp / "keep", KEYS, register or REGISTER, rd, lambda ev, **kw: log.append((ev, kw)), now, night
    )
    return out, log


def _tree(box: Path) -> dict[str, Any]:  # the tables' bytes and the manifest's content (restore writes it afresh)
    return {
        p.name: (json.loads(p.read_text()) if p.name == installed.MANIFEST else p.read_bytes())
        for p in sorted(box.iterdir())
        if p.is_file() and not p.name.startswith(".")
    }


def test_a_good_pack_is_applied_audited_and_the_doctor_says_current(box: Path, tmp_path: Path) -> None:
    pack = make_pack(tmp_path, "2026.12.1")
    env = {"TB_TERMINOLOGY_DIR": str(box), "TB_TERMINOLOGY_UPDATE_DIR": str(pack)}
    assert dict((k, s) for k, s, _ in tp.doctor_checks(env, DAY))["terminology_update"] == "WARN"  # due before it
    (out, text), log = _go(pack, box, tmp_path)
    assert out == "applied", text
    assert [r["code"] for r in installed.read_table(box, "department") or []] == ["RHEU", "NEUR", "IMG"]
    assert installed.manifest(box)["tables"]["department"]["version"] == "2026.12.1"
    assert [(e, k["outcome"]) for e, k in log] == [("terminology.update", "applied")]
    rows = {k: (s, t) for k, s, t in tp.doctor_checks(env, DAY)}
    assert rows["terminology_update"][0] == "PASS"
    assert "department 3 rows (2026.12.1, sha256 " in rows["terminology_tables"][1]


@pytest.mark.parametrize("what", ["hash", "older", "licence", "unsigned", "licensed"])
def test_a_bad_pack_is_refused_by_name_and_nothing_changes(box: Path, tmp_path: Path, what: str) -> None:
    (box / tp.STATE).write_text(json.dumps({"version": "2026.12.1"}))
    kws: dict[str, dict[str, Any]] = {"hash": {"bad_hash": True}, "older": {}, "licence": {"register_id": "atc-index"},
                          "unsigned": {"sign": False}, "licensed": {"tables": {"atc_index": ["A"]}}}  # fmt: skip
    kw = kws[what]
    pack = make_pack(tmp_path, "2026.12.1" if what == "older" else "2026.12.2", **kw)
    before = _tree(box)
    (out, text), log = _go(pack, box, tmp_path)
    assert out == "refused"
    assert {"hash": "wrong hash", "older": "not newer", "licence": "licence class not accepted",
            "unsigned": "unsigned pack", "licensed": "hospital's copy"}[what] in text  # fmt: skip
    assert _tree(box) == before and not (box / tp.JOURNAL).exists()
    assert [(e, k["outcome"]) for e, k in log] == [("terminology.update", "refused")]


def test_a_reader_that_fails_puts_the_old_release_back_everywhere(box: Path, tmp_path: Path) -> None:
    before = _tree(box)

    def readers(
        n: int,
    ) -> dict[str, Any]:  # the first load: the third reader (the FHIR store) fails; the second is the old release
        return {"problems": ["fhir: ConnectError"]} if n == 1 else {"problems": []}

    pack = make_pack(tmp_path, "2026.12.1")
    (out, _), log = _go(pack, box, tmp_path, readers)
    assert out == "reverted"
    assert _tree(box) == before and tp.applied_version(box) == "" and not (box / tp.JOURNAL).exists()
    assert [k["outcome"] for _, k in log] == ["reverted"]


def test_a_run_cut_short_after_the_swap_is_undone_by_the_next_one(box: Path, tmp_path: Path) -> None:
    before = _tree(box)

    def killed(n: int) -> dict[str, Any]:
        raise KeyboardInterrupt  # not an Exception: the run dies with the swap done and its journal written

    with pytest.raises(KeyboardInterrupt):
        _go(make_pack(tmp_path, "2026.12.1"), box, tmp_path, killed)
    assert (box / tp.JOURNAL).exists() and _tree(box) != before
    (out, text), _ = _go(make_pack(tmp_path, "2026.12.2"), box, tmp_path)
    assert out == "applied" and "cut-short update was undone" in text
    assert installed.manifest(box)["tables"]["department"]["version"] == "2026.12.2"


def test_a_pack_found_during_a_night_waits_and_is_applied_after_it(box: Path, tmp_path: Path) -> None:
    pack = make_pack(tmp_path, "2026.12.1")
    (out, _), log = _go(pack, box, tmp_path, now=NIGHT_NOW, night="02:00-06:00")
    assert out == "waits" and log == [] and tp.applied_version(box) == ""
    (out, _), _ = _go(pack, box, tmp_path, now=datetime(2026, 12, 1, 6, 30), night="02:00-06:00")
    assert out == "applied"


def test_the_night_may_pass_midnight() -> None:
    assert tp.in_night(datetime(2026, 12, 1, 23, 30), "22:00-05:00") and tp.in_night(
        datetime(2026, 12, 1, 4, 0), "22:00-05:00"
    )
    assert not tp.in_night(datetime(2026, 12, 1, 12, 0), "22:00-05:00") and not tp.in_night(DAY, "")


def test_find_prefers_the_folder_then_a_stick(tmp_path: Path) -> None:
    a, b = make_pack(tmp_path / "a", "1.0"), make_pack(tmp_path / "b", "1.0")
    assert tp.find(str(a), [str(b)]) == a and tp.find("", [str(b.parent)]) is None and tp.find("", [str(b)]) == b
