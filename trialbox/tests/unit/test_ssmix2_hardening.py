"""T-615a: the SS-MIX2 reader on what vendor files hold (STD-020, STD-021, STD-023, STD-025, STD-013's SS-MIX2 half).

All data is synthetic: the hard cases come from ``tools.ssmix2_export.hard_cases``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from adapter.mapping.engine import Mapper, Mapping
from adapter.sources.ssmix2 import hl7
from adapter.sources.ssmix2.source import Ssmix2Source, obx_value, storage_dir

from tools.ssmix2_export import cp50220, hard_cases

ROOT = Path(__file__).resolve().parents[2]
JP_MAPPING = ROOT / "services/adapter/mapping/jp_core/ssmix2_site.yaml"


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, str]]:
    root = tmp_path_factory.mktemp("hard") / "storage"
    return root, hard_cases(root)


def _src(root: Path, quarantine_max_pct: float = 1.0) -> Ssmix2Source:
    return Ssmix2Source(root, licensed={}, quarantine_max_pct=quarantine_max_pct)


# ------------------------------------------------------------------------------------------------ STD-020: encodings
def test_the_five_byte_patterns_load_and_an_unreadable_file_is_quarantined(
    storage: tuple[Path, dict[str, str]],
) -> None:
    """Acceptance: the five byte patterns load (half-width katakana, NEC row 13 and IBM extension inside ESC $ B,
    JIS X 0212, Shift_JIS under the wrong and the right MSH-18); a file no codec reads is quarantined, counted and
    listed, and the other patients' files still load."""
    root, _ = storage
    src = _src(root)
    names = {r["mrn"]: r["name"] for r in src.rows("patient", "patient", None, None)}
    assert names == {
        "99000001": "ﾔﾏﾀﾞ　ﾊﾅｺ",
        "99000002": "髙橋　①子㈱",
        "99000003": "丂田　花子",
        "99000004": "佐藤　ﾊﾅｺ",
        "99000005": "鈴木　①子",
        "99000007": "山田　花子",
    }
    assert src.stats["ADT-00:quarantined (unreadable bytes)"] == 1
    assert src.stats["ADT-00:read as cp932"] == 2 and src.stats["ADT-00:read as iso2022_jp_ext"] == 3
    ((typ, where, why),) = src.quarantined
    assert typ == "ADT-00" and "99000006" in where and why.startswith("unreadable bytes")
    # one of seven files is over the default 1 %: the night is held; a looser limit counts it only
    assert "1 of 7 SS-MIX2 files quarantined" in str(src.quarantine_reason("patient"))
    loose = _src(root, quarantine_max_pct=20.0)
    list(loose.rows("patient", "patient", None, None))
    assert loose.quarantine_reason("patient") is None and loose.quarantined
    assert src.quarantine_reason("lab") is None


def test_decoding_never_replaces_a_byte() -> None:
    for data in (b"MSH|^~\\&|\r\x80\xff\r", b"MSH|^~\\&|\r\x1b$B\x29\x21\x1b(B\r", b"MSH|\r\x1b$Z!!\r"):
        with pytest.raises(hl7.Undecodable):
            hl7.decode_bytes(data)
    assert hl7.decode_bytes(b"MSH|^~\\&|\rPID|||1\r") == ("MSH|^~\\&|\rPID|||1\r", "ascii")
    assert hl7.decode_bytes("MSH|\rPID|||1||山田\r".encode())[1] == "utf-8"


def test_iso2022_jp_text_reads_as_it_always_did() -> None:
    """T-613b: ISO-2022-JP holds no µ (U+00B5) and no U+FF0D; the Greek μ and the JIS minus U+2212 of a JIS file
    read as before, and a Shift_JIS or CP50220 file with the same characters reads the same text."""
    text = "OBX|1|NM|CRE||88|μmol/L||陰性（−）〜"
    for codec in ("iso2022_jp", "cp932"):
        with pytest.raises(UnicodeEncodeError):
            "µ".encode(codec)
    assert hl7.decode_bytes(text.encode("iso2022_jp")) == (text, "iso2022_jp")
    assert hl7.decode_bytes(text.encode("cp932").replace(b"\x81\x60", b"\x81\x60")) == (text, "cp932")
    assert hl7.decode_bytes(cp50220(text + "①")) == (text + "①", "iso2022_jp_ext")
    assert "－" not in hl7.decode("－".encode("cp932").decode("cp932").encode("cp932") + b"|\xb1")


# ------------------------------------------------------------------------------------------------ STD-021: OML-11
def test_obx2_value_types() -> None:
    def obx(vt: str, value: str) -> hl7.Segment:
        return hl7.parse(f"MSH|^~\\&|\rOBX|1|{vt}|X||{value}").all("OBX")[0]

    assert obx_value(obx("CWE", "1^陰性^JHSD0001")) == "陰性"
    assert obx_value(obx("CE", "POS^^L")) == "POS"
    assert obx_value(obx("SN", "<^0.03")) == "<0.03"
    assert obx_value(obx("SN", "^1^:^40")) == "1:40"
    assert obx_value(obx("NM", " 0.82 ")) == "0.82"
    assert obx_value(obx("ST", "a\\S\\b")) == "a^b"


def test_lab_status_correction_and_sample_time(storage: tuple[Path, dict[str, str]]) -> None:
    """Acceptance: a ``D`` result is a tombstone; a ``C`` result replaces the same order, test and sub-id (the
    replaced id becomes a tombstone); the sample time falls back OBX-14, OBR-7, SPM-17, the folder's date."""
    root, _ = storage
    src = _src(root)
    rows = {r["lab_no"]: r for r in src.rows("lab", "lab", None, None)}
    assert set(rows) == {"H-CWE", "H-SN", "H-CORR", "H-10DIGIT", "H-SPM", "H-DIR"}
    assert [r["lab_no"] for r in src.deleted_rows("lab", "lab", None, None)] == ["H-DEL", "H-ORIG"]
    assert all("_same" not in r for r in rows.values())
    assert rows["H-CORR"]["result_value"] == "0.82" and rows["H-CORR"]["result_status"] == "corrected"
    assert rows["H-CORR"]["ref_range"] == "0.46-0.79" and rows["H-CORR"]["abnormal_flag"] == "H"
    assert rows["H-CWE"]["result_value"] == "陰性" and rows["H-SN"]["result_value"] == "<0.03"
    got = {k: (rows[k]["sample_datetime"], rows[k]["sample_time_from"]) for k in ("H-CWE", "H-SN", "H-SPM", "H-DIR")}
    assert got == {
        "H-CWE": ("2026-10-01 08:30:00", "OBR-7"),
        "H-SN": ("2026-10-01 09:00:00", "OBX-14"),
        "H-SPM": ("2026-10-02 07:00:00", "SPM-17"),
        "H-DIR": ("2026-10-03", "folder"),
    }
    assert rows["H-10DIGIT"]["sample_datetime"] == "2026-10-01 10:00:00"
    # a second read gives the same tombstones, not twice as many
    list(src.rows("lab", "lab", None, None))
    assert len(list(src.deleted_rows("lab", "lab", None, None))) == 2


def test_jp_mapping_reads_the_lab_hard_cases(storage: tuple[Path, dict[str, str]]) -> None:
    root, _ = storage
    mp = Mapper(Mapping.load(JP_MAPPING), b"k" * 32, "JP")
    obs = list(mp.map_table("lab", iter(_src(root).rows("lab", "lab", None, None))))
    assert len(obs) == 6 and all(o.get("effectiveDateTime") for o in obs)
    ranges = [o["referenceRange"] for o in obs if "referenceRange" in o]
    assert ranges == [[{"text": "0.46-0.79"}]]


# ------------------------------------------------------------------------------------------------ STD-023, STD-013
def test_ten_digit_time_keeps_its_hour() -> None:
    assert hl7.ts("2026110110") == "2026-11-01 10:00:00"
    assert hl7.ts("202611011030") == "2026-11-01 10:30:00"
    assert hl7.ts("20261101") == "2026-11-01"
    assert hl7.ts("20261101+0900") == "2026-11-01"


def test_pid30_marks_deceased_and_repetitions_are_chosen(storage: tuple[Path, dict[str, str]]) -> None:
    """Acceptance: PID-30 ``Y`` marks the patient deceased without a PID-29 date; PID-3 is the ``PI`` repetition and
    PID-5 the ideographic one."""
    root, _ = storage
    rows = {r["mrn"]: r for r in _src(root).rows("patient", "patient", None, None)}
    dead = rows["99000007"]
    assert dead["deceased"] == "Y" and dead["death_date"] == "" and dead["name"] == "山田　花子"
    assert rows["99000001"]["deceased"] == ""
    mp = Mapper(Mapping.load(JP_MAPPING), b"k" * 32, "JP")
    pats = [r for r in mp.map_table("patient", iter([dead, rows["99000001"]])) if r["resourceType"] == "Patient"]
    assert pats[0]["deceasedBoolean"] is True and "deceasedDateTime" not in pats[0]
    assert "deceasedBoolean" not in pats[1] and "deceasedDateTime" not in pats[1]
    dated = {**dead, "death_date": "2026-10-01"}
    (pat,) = [r for r in mp.map_table("patient", iter([dated])) if r["resourceType"] == "Patient"]
    assert "deceasedBoolean" not in pat and pat["deceasedDateTime"].startswith("2026-10-01")


# ------------------------------------------------------------------------------------------------ STD-025: row reject
def _store(root: Path, mrn: str, typ: str, order: str, segs: list[str]) -> None:
    d = storage_dir(root, mrn, "20261001", typ)
    d.mkdir(parents=True, exist_ok=True)
    pid = (
        [] if any(s.startswith("PID|") for s in segs) else [f"PID|||{mrn}^^^^PI"]
    )  # every SS-MIX2 message carries its patient (PR #1095 fourth review b)
    body = "\r".join(["MSH|^~\\&|HIS||TB||20261001||X|1|P|2.5||||||~ISO IR87", *pid, *segs]) + "\r"
    (d / f"{mrn}_20261001_{typ}_{order}_20261001000000000_-_1").write_bytes(body.encode("iso2022_jp"))


def _night(tmp: Path, pg_cluster_url: str, root: Path, prefix: str):  # type: ignore[no-untyped-def]
    from adapter.pipeline import AdapterConfig, run_ingest

    sec = tmp / "sec"
    sec.mkdir(exist_ok=True)
    (sec / "site_hmac.key").write_bytes(b"trialbox-test-site-key-0123456789abcdef")
    (sec / "site_hmac.key").chmod(0o600)
    sep = "&" if "?" in pg_cluster_url else "?"
    cfg = AdapterConfig(lake_dir=tmp / "ingest", secrets_dir=sec, mapping_path=JP_MAPPING, site_id="JP-RJ",
                        tz="Asia/Tokyo", audit_dir=tmp / "audit", validation_max_pct=100.0,
                        db_url=f"{pg_cluster_url}{sep}tb_prefix={prefix}_")  # fmt: skip
    return run_ingest(cfg, "ssmix2", str(root), snapshot="2026-11-01", load_fhir=False, rebuild_lake=False,
                      validate=False)  # fmt: skip


def _labs(root: Path, n: int, bad: int) -> None:
    _store(root, "10000001", "ADT-00", "-", ["EVN||", "PID|||10000001^^^^PI||山田^花子||19600101|F"])
    for i in range(n):
        when = "20261399090000" if i < bad else "20261001090000"  # month 13: the mapping cannot read it
        obx = ["OBX", "1", "NM", "3D046000001906202^HbA1c^JC10", "", "6.0", "%", *[""] * 15]
        obx[11], obx[14], obx[21] = "F", when, f"L{i}"
        _store(root, "10000001", "OML-11", f"L{i}", [f"OBR|1|L{i}", "|".join(obx)])


def test_one_bad_row_is_rejected_and_counted_the_table_goes_on(
    tmp_path: Path, pg_cluster_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance (STD-025): one row with an unreadable date is rejected and counted; the rows after it load; the
    night is held only when rejects pass the limit."""
    import adapter.pipeline as pipeline

    root = tmp_path / "ok" / "storage"
    _labs(root, 4, 1)
    monkeypatch.setattr(pipeline, "REJECT_MAX_PCT", 30.0)
    rep = _night(tmp_path / "ok", pg_cluster_url, root, "rjok")
    assert not rep.errors, rep.errors
    snap = tmp_path / "ok" / "ingest" / "ndjson" / "2026-11-01"
    comp = json.loads((snap / "completeness.json").read_text(encoding="utf-8"))
    assert comp["tables"]["lab"]["rows"] == 4
    # D-520: the key names the exception's type before the value-free message
    assert comp["tables"]["lab"]["rejected"] == {"MappingError: unparseable datetime <value>": 1}
    obs = (snap / "Observation.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(obs) == 3 and "2026-13" not in "".join(obs)

    held_root = tmp_path / "held" / "storage"
    _labs(held_root, 4, 2)
    rep = _night(tmp_path / "held", pg_cluster_url, held_root, "rjheld")
    assert any("lab: 2 of 4 rows rejected" in e for e in rep.errors), rep.errors
