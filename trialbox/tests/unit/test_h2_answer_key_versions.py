"""Lane H, card H-2 (D-1104): the corrected answer key is a new version, and the old one stays.

Key v1 is the key as launch P1b used it (the builder of master ``fa639b61``); key v2 has the P1b review's corrections
B1 to B3 (the integrator's list on #649, 2026-11-16). Synthetic data, and a small slice of P1b's jmed set
(``tests/fixtures/public_accuracy_p1b``: JMED-Personas by Sociocom (NAIST), CC BY 4.0). No network."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tools.public_accuracy import __main__ as cli
from tools.public_accuracy import key, sets, site, sources

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "public_accuracy_p1b"
MANIFEST = ROOT / "eval" / "public_accuracy_key" / "MANIFEST.json"
REF = date(2026, 11, 16)  # launch P1b's build day


def _personas() -> list[dict[str, Any]]:
    """Synthetic JMED-Personas rows (made up here): the structured fields and the note disagree on purpose."""
    note = ("ペルソナ_医学的背景", "ペルソナ_受診に至った経過", "ペルソナ_診察・検査所見", "ペルソナ_治療・服薬上の課題",
            "ペルソナ_生活背景・支援状況")  # fmt: skip
    rows = []
    for i, (coded, fam, text) in enumerate(
        [
            ("糖尿病", "", "糖尿病で内服加療中。"),
            ("", "高血圧", "併存疾患として高血圧がある。"),  # B3: the note states it, the coded fields do not
            ("高血圧", "", "血圧は正常範囲。"),  # B3: the coded fields state it, the note does not
            ("", "糖尿病", "父が糖尿病。"),
            ("", "", "糖尿病のリスクは低い。高血圧傾向。"),  # a risk and a tendency are not the condition
            ("", "", "境界型糖尿病の所見。"),
            ("糖尿病 高血圧", "", "糖尿病と高血圧で通院中。"),
            ("", "", "特記すべき既往なし。"),
        ]
    ):
        r = {k: "" for k in note}
        r.update({"患者ID": f"syn{i:02d}", "年齢": str(30 + 7 * i), "性別": "男性" if i % 2 else "女性",
                  "主病名": coded, "既往歴": "", "現病歴": "", "家族歴": fam, note[0]: text})  # fmt: skip
        rows.append(r)
    return rows


def _write_jmed_cache(cache: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    p = sources.path_of("jmed_personas_01.parquet", cache)
    p.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(_personas()), p)


def _en_bundle(placed: Any) -> sets.Bundle:
    """A synthetic English set: an infant, a patient seen before July, one with no age; trials whose placed lines
    differ between the key versions (a limit in months, a bound the protocol states)."""
    b = sets.Bundle("sigir")
    for k, text, age in (
        ("syn-1", "A 6-month-old girl with a cough.", 0),
        ("syn-2", "A 50-year-old man with asthma.", 50),
        ("syn-3", "A 30-year-old woman with dyspnea.", 30),
        ("syn-4", "A man with a rash.", None),
    ):
        b.patients[k] = sets.Patient(k, "en", text, age, "F")
        b.patients[k].age_stated = sets.stated_age(text)
    for nct, lo, hi, sex, inc in (
        ("NCT90000001", "2 Months", None, None, ["Cough"]),
        ("NCT90000002", "18 Years", "65 Years", "MALE", ["Adults aged 18 to 65 years"]),
        ("NCT90000003", "40 Years", None, None, ["Dyspnea"]),
    ):
        lines, notes = placed(lo, hi, sex, inc)
        b.trials[nct] = sets.Trial(nct, "en", "Synthetic", inc, ["Pregnancy"], lines, notes=notes)
    for i, pk in enumerate(sorted(b.patients)):
        for nct in sorted(b.trials):
            b.pairs.append(sets.Pair(pk, nct, ("eligible", "excluded")[i % 2], "sigir-x"))
            b.criteria.append(sets.CriterionGold(pk, nct, "exclusion", "Pregnancy", "not excluded", [0], "sigir-c"))
    return b


# sha256 of every file the builder of master fa639b61 (launch P1b's) writes for the inputs above, at REF: computed
# with that commit's tools/public_accuracy on 2026-11-17. Key v1 must give the same bytes for ever.
V1_AS_FA639B61 = {
    "en/gold/bundle.json": "c4de530414fab38d6287eaffe6c897d4a7c24d79cb9a3b164c73aede908cdf7d",
    "en/gold/compile_gold.json": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    "en/gold/criteria.jsonl": "5c6a0fb30bae4c8866495f2f946fef5341057f6456ceffa2241f7b59b3b6ef53",
    "en/gold/ids.json": "44ba8a3057c9ba9ce3ddbe485d94be7372dc158a3f6d33c23e7b9aa0dfc1e008",
    "en/gold/pairs.jsonl": "d0bcd9829200379ae7e907dce41f79e4b0e017a182707d0fe9a32f4a0ba12f9f",
    "en/site/PROVENANCE.md": "adf07023f42675774825c1180eac9e3a9d7676916e62b8a5511e4f5a2d88a57d",
    "en/site/hospital/appointment.csv": "5542cc508e39c0c510e2ed60c7403f5f371c9114cf08825301cac2a004b7a134",
    "en/site/hospital/diagnosis.csv": "9b2d4e25f0969a8ac0b3b00058d92c9deaeaea7f18d3e6a293c97528c70f9596",
    "en/site/hospital/encounter.csv": "9d5e016d7fd8b77b57f3299b956b9c765ffa0f3a7ff94710d83ab2ccd10d7ba0",
    "en/site/hospital/note.csv": "94cab929de463eab03e99f5b64a0a0751a8c3974aecf65183bf4b83f4dc1aabe",
    "en/site/hospital/patient.csv": "0e119f3ab82aa05981010120408443b8eddb3775a8902bbd20f9d7a49d6c9b98",
    "en/site/hospital/practitioner.csv": "72e6c43603a4bd323403494dbbb9afa4b41d0291b829302dde01de560f458a77",
    "en/site/profiles/NCT90000001.yaml": "3de269a88295339cceee2975f585e63d7c7d110809670280d22717db0cc57224",
    "en/site/profiles/NCT90000002.yaml": "2f1cf35a8ca6611123c9e0e9b880aad4bd54735717165631252ce3e7b058f626",
    "en/site/profiles/NCT90000003.yaml": "19da5de73fabfbc81f5ee5bbf684f10b405ddb54f661af403424d6c27bff73c7",
    "en/site/protocols/NCT90000001.txt": "9e5ac35c12ba5c577ddc773e6bb2d519380c337634468147ed22413bf8598acd",
    "en/site/protocols/NCT90000002.txt": "515b351472527d352055127c4626cc01fe2c73ed00238aa003df342cae501d1f",
    "en/site/protocols/NCT90000003.txt": "4e547dbae21019f4c5f07643efba192945dd93666570ca5af5a68b99b94c6c80",
    "jmed/gold/bundle.json": "527cc8e16d73b5caf19eb273af78055b5a336faf64b93e0aadb53c40d5beeaa4",
    "jmed/gold/compile_gold.json": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    "jmed/gold/criteria.jsonl": "8eaffe1cddd2ec89f3140af3cbbbc6d8af490d4899cb3098226651837054bcab",
    "jmed/gold/ids.json": "95d1e0f3c3076e98de31a3538ba0befdd16174f8715655ffecea4bb0dfaecbbe",
    "jmed/gold/pairs.jsonl": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "jmed/site/PROVENANCE.md": "a1778e7eae7ab5da4452a3c29310d1f243eca4c0869e10c432df004b6c029ca2",
    "jmed/site/hospital/appointment.csv": "0f041ead1461f51e526c3a79ce8dc5ad61e8eebeb24952bc48a09304f2343c21",
    "jmed/site/hospital/diagnosis.csv": "9b2d4e25f0969a8ac0b3b00058d92c9deaeaea7f18d3e6a293c97528c70f9596",
    "jmed/site/hospital/encounter.csv": "33892f85b8cbcdfeba501db2a684013827ae430c17691153a73ed9b52b6d0fd8",
    "jmed/site/hospital/note.csv": "1e2d0d7979fc435dd011b42bb29df029fa4bb0c7a0c8c1e7b5bd634b56a28e74",
    "jmed/site/hospital/patient.csv": "2057d6cb4fe304b9e402819661a2c56de4d51bfd4d93f4665748dbcbf80a96e0",
    "jmed/site/hospital/practitioner.csv": "d779b533429437ffc02cdd9de18c9b1004dc1fca652c89725fc750b7a306c2c3",
    "jmed/site/profiles/JMED-DM.yaml": "625760e79dfd6aaa2086392be07166b746ab470af138bb11b30831231355d867",
    "jmed/site/profiles/JMED-HT.yaml": "12f6af2b2d4af1cc1f11263ba089e645cb3e61eaf5cb1141251e34a1f2bb157d",
    "jmed/site/protocols/JMED-DM.txt": "f44ffaf5cc226f3a9e19d6d58a9a0b0b3cefecc9db6e478aecdf64981e788b8f",
    "jmed/site/protocols/JMED-HT.txt": "c80f9e8b3e2468d8ba845b04d6fd78ae716200bb1a115208660322c06887a21f",
}


def _build(out: Path, version: str) -> Path:
    cache = out / "cache"
    _write_jmed_cache(cache)
    site.build(sets.read_jmed(cache, 24, version), out / "jmed", ref=REF, key=version)

    def placed(lo: Any, hi: Any, sex: Any, inc: Any) -> Any:
        return sets.placed_lines(lo, hi, sex, inc, version)

    site.build(_en_bundle(placed), out / "en", ref=REF, key=version)
    return out


def _hashes(out: Path) -> dict[str, str]:
    return {
        str(f.relative_to(out)): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(out.rglob("*"))
        if f.is_file() and "cache" not in f.relative_to(out).parts
    }


# ---------------------------------------------------------------- the old key stays, byte for byte
def test_key_v1_is_built_byte_for_byte_as_launch_p1b_had_it(tmp_path: Path) -> None:
    got = _hashes(_build(tmp_path, "v1"))
    new_files = {k for k in got if k.endswith(("/gold/key.json", "/gold/written.json"))}
    assert new_files == {f"{s}/gold/{f}" for s in ("en", "jmed") for f in ("key.json", "written.json")}
    assert {k: v for k, v in got.items() if k not in new_files} == V1_AS_FA639B61
    assert key.version_of(tmp_path / "en") == "v1" and key.describe(tmp_path / "jmed")["stamped"] is True


def test_a_folder_without_a_version_is_key_v1_and_an_unknown_version_is_refused(tmp_path: Path) -> None:
    (tmp_path / "gold").mkdir()
    (tmp_path / "gold" / "ids.json").write_text("{}", encoding="utf-8")
    assert key.version_of(tmp_path) == "v1" and key.describe(tmp_path / "gold")["stamped"] is False
    for call in (
        lambda: key.check("v3"),
        lambda: sets.placed_lines("18 Years", None, None, key="v3"),
        lambda: sets.read("jmed", tmp_path, key="v3"),
        lambda: site.build(sets.Bundle("x"), tmp_path / "b", key="v3"),
    ):
        with pytest.raises(ValueError, match="answer key 'v3'"):
            call()
    assert key.CURRENT == "v2" and set(key.KEYS) == {"v1", "v2"}


def test_the_version_switch_gives_each_version_its_own_lines_and_birth_dates() -> None:
    assert sets.placed_lines("2 Months", None, None, key="v1")[0] == ["Aged 0.17 years or older"]
    assert sets.placed_lines("2 Months", None, None)[0] == ["Aged 2 months or older"]  # v2, the default
    stated = ["Adults aged 18 to 65 years"]
    assert sets.placed_lines("18 Years", "65 Years", "MALE", stated, "v1")[0] == [
        "Aged 18 years or older",
        "Age <= 65 years",
        "Male participants only",
    ]
    assert sets.placed_lines("18 Years", "65 Years", "MALE", stated, "v2")[0] == ["Male participants only"]
    visit = date(2026, 3, 10)
    assert site.birth_date_v1(visit, 50) == "1975-07-01" and site.birth_date(visit, 50) == "1976-03-10"
    assert site.birth_date_v1(visit, 0) == "2025-07-01" and site.birth_date(visit, 0, (6, "month")) == "2025-09-10"


# ---------------------------------------------------------------- the listing of what differs, and why
def test_key_diff_lists_exactly_the_rows_b1_to_b3_change(tmp_path: Path) -> None:
    old, new = _build(tmp_path / "v1", "v1"), _build(tmp_path / "v2", "v2")
    j = key.diff(old / "jmed", new / "jmed")
    assert j["old"]["key"] == "v1" and j["new"]["key"] == "v2" and not j["not_compared"]
    assert j["counts"] == {"jmed_label": 2, "birth_date": 8}  # same patients: B3 changes labels, not the sample
    labels = {(r["patient"], r["ruleset"], r["old"], r["new"]) for r in j["rows"] if r["what"] != "birth_date"}
    assert labels == {
        ("syn01", "JMED-HT", "not excluded", "excluded"),  # the note states it, the coded fields do not
        ("syn02", "JMED-HT", "excluded", "not excluded"),  # the coded fields state it, the note does not
    }
    assert all(r["why"].startswith("B3") for r in j["rows"] if r["what"] != "birth_date")
    assert (old / "jmed" / "gold" / "ids.json").read_bytes() == (new / "jmed" / "gold" / "ids.json").read_bytes()
    e = key.diff(old / "en", new / "en")
    assert e["counts"] == {"birth_date": 3, "protocol_line": 4}  # no label of the physicians changes
    lines = {(r["ruleset"], r["old"], r["new"]) for r in e["rows"] if r["what"] == "line"}
    assert lines == {
        ("NCT90000001", "Aged 0.17 years or older", None),
        ("NCT90000001", None, "Aged 2 months or older"),
        ("NCT90000002", "Aged 18 years or older", None),
        ("NCT90000002", "Age <= 65 years", None),
    }
    infant = next(r for r in e["rows"] if r["patient"] == "syn-1")
    assert infant["why"].startswith("B1") and (infant["old"], infant["new"]) == ("2026-07-01", "2026-04-03")
    assert (old / "en" / "gold" / "pairs.jsonl").read_bytes() == (new / "en" / "gold" / "pairs.jsonl").read_bytes()


def test_key_diff_of_a_stored_gold_folder_says_what_it_could_not_compare(tmp_path: Path, capsys: Any) -> None:
    old = _build(tmp_path / "v1", "v1") / "jmed" / "gold"
    for f in ("key.json", "written.json"):  # as launch P1b stored it: built/gold only, no version
        (old / f).unlink()
    new = _build(tmp_path / "v2", "v2") / "jmed"
    assert cli.main(["key-diff", str(old), str(new)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["old"] == {"key": "v1", "what": key.KEYS["v1"], "stamped": False}
    assert out["counts"] == {"jmed_label": 2} and len(out["not_compared"]) == 2


# ---------------------------------------------------------------- launch P1b's jmed key, a slice
def test_p1b_jmed_three_wrong_exclusions_were_key_faults_and_v2_says_so() -> None:
    rows = json.loads((FIX / "jmed_key_slice.json").read_text(encoding="utf-8"))["rows"]
    word = {"JMED-DM": "糖尿病", "JMED-HT": "高血圧"}
    for r in rows:
        v2 = sets.jmed_stratum("\n".join(r["note_sentences"]), word[r["trial"]])
        assert ("excluded" if v2 == "own" else "not excluded") == r["key_v2"], r["patient"]
    wrong = [r for r in rows if r["box_excluded_on_this_line_in_p1b"]]
    assert len(wrong) == 7 and all(r["key_v1"] == "not excluded" for r in wrong)
    assert {(r["patient"], r["trial"]) for r in wrong if r["key_v2"] == "excluded"} == {
        ("f1f374875280433d8fdec6ff9ced4c28", "JMED-HT"),
        ("9f56d1cf27804387be624da5005a7f03", "JMED-HT"),
        ("f5da14174f2f4fba864c0e161bb49c21", "JMED-HT"),
    }
    # a risk, a tendency, a borderline or pre- state is not the condition (D-1104)
    for pid in ("c8fcd8aa7c2549bb9bc89a541ffa73f4", "8776d26af70147ceb2e14a5753791e7a",
                "fa7a988d66ca409c8ec481760e48fcf5", "7a329699d6e844108df064087ebc9c60",
                "928744f7bc2047efa9f7885b53626e97"):  # fmt: skip
        assert all(r["key_v2"] == "not excluded" for r in rows if r["patient"] == pid)
    assert sets.jmed_stratum("糖尿病のリスクは低い。", "糖尿病") == "none"
    assert sets.jmed_stratum("境界型糖尿病の所見。", "糖尿病") == "none"
    assert sets.jmed_stratum("軽度の高血圧傾向。", "高血圧") == "none"
    assert sets.jmed_stratum("糖尿病予備群と診断。", "糖尿病") == "none"
    assert sets.jmed_stratum("併存疾患として高血圧があり。", "高血圧") == "own"


# ---------------------------------------------------------------- the manifest and the score name the version
def test_the_manifest_keeps_v1_and_pins_launch_p1bs_stored_key() -> None:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert set(m["versions"]) == set(key.KEYS) and m["current"] == key.CURRENT
    for v, what in key.KEYS.items():
        assert m["versions"][v]["what"] == what
    p1b = m["versions"]["v1"]["launch_p1b"]["sha256"]
    assert p1b["sigir"]["criteria.jsonl"] == "3adeb9a69597f1b0c5c4a8bc7b997453af34e726947cdf06b4943d0a061e7381"
    assert p1b["sigir"]["pairs.jsonl"] == "3cec16529abe3eea714057a497a6426b238c5bca357cd777346ecae7fa554bf1"
    assert p1b["jmed"]["criteria.jsonl"] == "aea215ce5a7b3b2fac67b4d3f0b679dda89286afd70913824d30bd7bec1d326e"


def test_a_score_names_the_key_it_was_scored_on(tmp_path: Path, capsys: Any) -> None:
    b = _en_bundle(lambda lo, hi, sex, inc: sets.placed_lines(lo, hi, sex, inc, "v1"))
    site.build(b, tmp_path / "built", ref=REF, key="v1")
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "answers.json").write_text("{}", encoding="utf-8")
    assert cli.main(["score", "--out", str(tmp_path)]) == 0
    capsys.readouterr()
    assert json.loads((tmp_path / "score.json").read_text(encoding="utf-8"))["answer_key"]["key"] == "v1"
