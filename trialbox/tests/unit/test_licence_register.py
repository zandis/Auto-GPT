"""The licence register as data (T-617b, STD-044, LLM-012, D-342): ``docs/licences/register.csv`` covers every
shipped data file, no SNOMED CT ships, and the model licence rows of ``models/registry.yaml`` agree with it."""

from __future__ import annotations

import shutil
import sys
import types
from pathlib import Path

import pytest
import yaml

from tools import licence_register as lr

ROOT = lr.ROOT
HEADER = ",".join(lr.COLUMNS) + "\n"


def _row(rid: str, paths: str = "", kind: str = "code-system", status: str = "cleared", **over: str) -> str:
    base = {c: "x" for c in lr.COLUMNS}
    base.update(id=rid, kind=kind, status=status, checked="2026-11-10", text_sha256="", athena="", paths=paths)
    base.update(over)
    return ",".join(base[c] for c in lr.COLUMNS) + "\n"


def _tree(tmp_path: Path, rows: str) -> Path:
    (tmp_path / "docs/licences").mkdir(parents=True)
    (tmp_path / "docs/licences/register.csv").write_text(HEADER + rows, encoding="utf-8")
    (tmp_path / "vocab").mkdir()
    (tmp_path / "vocab/lab_to_loinc.csv").write_text("local,loinc\nA,2160-0\n", encoding="utf-8")
    (tmp_path / "vocab/notes.csv").write_text("id,text\n1,hello\n", encoding="utf-8")  # a data file beside it
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain/notes.csv").write_text("id,text\n1,hello\n", encoding="utf-8")  # not a data folder
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored/atc.csv").write_text("code,display\n", encoding="utf-8")
    (tmp_path / ".dockerignore").write_text("ignored\n", encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------------------------------------------ the repository
def test_the_committed_register_passes_the_build_check() -> None:
    assert lr.check() == []


def test_the_detector_sees_the_known_data_files() -> None:
    files = set(lr.shipped_data_files())
    for f in (
        "services/criteria_compiler/terminology/src/atc.csv",
        "services/criteria_compiler/terminology/loinc_tw.parquet",
        "services/adapter/mapping/mimic/tables/icu_item_to_icd10pcs.csv",
        "rulesets/GZQO/valuesets/VS_GOUT.json",
        "catalogue/phenotypes.csv",
        "tests/fixtures/refdata/jrct_sample.csv",
    ):
        assert f in files, f
    assert not any(f.startswith(".cache/") or f.startswith(".venv/") for f in files)


def test_every_row_has_its_licence_facts() -> None:
    rows = lr.load()
    ids = {r.id for r in rows}
    assert {"loinc", "ucum", "atc", "snomed-ct", "rxnorm", "rxnorm-extension"} <= ids
    snomed = next(r for r in rows if r.id == "snomed-ct")
    assert snomed.status == "removed" and not snomed.paths
    atc = next(r for r in rows if r.id == "atc")
    assert atc.status == "permission-to-ask" and "docs/licences/atc-permission-request.md" in atc.raw["evidence"]
    assert (ROOT / "docs/licences/atc-permission-request.md").is_file()


def test_every_vocabulary_the_athena_loader_allows_has_a_row() -> None:
    """The allow-list of PR #145 (T-105b); the check reads ``omop.vocab_load.ATHENA_ALLOW`` once it is on master."""
    covered = {v for r in lr.load() for v in r.athena}
    pr145 = {"LOINC", "UCUM", "RxNorm", "RxNorm Extension", "ATC", "Gender", "Race", "Ethnicity", "Visit",
             "Type Concept", "None", "Domain", "Vocabulary", "Concept Class", "Relationship", "Metadata",
             "Note Encoding", "Language", "Condition Status", "Meas Type", "Cost", "Cost Type", "Episode",
             "Episode Type", "OMOP Extension"}  # fmt: skip
    assert pr145 <= covered and "SNOMED" not in covered


def test_an_athena_vocabulary_with_no_row_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("omop.vocab_load")
    fake.ATHENA_ALLOW = frozenset({"LOINC", "Made Up"})  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "omop.vocab_load", fake)
    assert lr.athena_problems(lr.load()) == [
        "Athena vocabulary 'Made Up' is allowed by the loader but has no register row (column athena)"
    ]


# ------------------------------------------------------------------------------------------------ the build check
def test_a_shipped_data_file_with_no_row_fails_the_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("omop.vocab_load")
    fake.ATHENA_ALLOW = frozenset()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "omop.vocab_load", fake)  # the fake tree has no Athena rows
    root = _tree(tmp_path, _row("loinc", "vocab/lab_to_loinc.csv"))
    assert lr.shipped_data_files(root) == ["vocab/lab_to_loinc.csv", "vocab/notes.csv"]
    assert lr.check(root) == ["vocab/notes.csv: shipped data file with no row in docs/licences/register.csv"]
    root = _tree(tmp_path / "ok", _row("loinc", "vocab/*.csv"))
    assert lr.check(root) == []


def test_a_stale_pattern_and_a_row_that_ships_nothing_with_paths_fail(tmp_path: Path) -> None:
    rows = _row("loinc", "vocab/*.csv;vocab/gone.csv") + _row("site", "vocab/*.csv", status="site-loaded")
    problems = lr.check(_tree(tmp_path, rows))
    assert "register row loinc: pattern 'vocab/gone.csv' matches no shipped data file" in problems
    assert any(p.startswith("register row site: a code-system row with status site-loaded") for p in problems)


def test_bad_rows_fail(tmp_path: Path) -> None:
    rows = _row("a", "vocab/*.csv") + _row("a", kind="poem", status="maybe", checked="soon", text_sha256="12")
    problems = lr.check(_tree(tmp_path, rows))
    assert "register row a: id twice" in problems
    assert any("kind 'poem'" in p for p in problems) and any("status 'maybe'" in p for p in problems)
    assert "register row a: checked must be a date (YYYY-MM-DD)" in problems
    assert "register row a: text_sha256 is not a sha256" in problems
    (tmp_path / "docs/licences/register.csv").write_text("id,kind\n", encoding="utf-8")
    with pytest.raises(ValueError, match="columns"):
        lr.load(tmp_path / "docs/licences/register.csv")


def test_a_shipped_snomed_code_fails_the_build(tmp_path: Path) -> None:
    root = _tree(tmp_path, _row("all", "vocab/*.*"))
    (root / "vocab/icu_item_to_snomed.csv").write_text("itemid,snomed\n1,40617009\n", encoding="utf-8")
    (root / "vocab/vs.json").write_text(
        '{"resourceType": "ValueSet", "compose": {"include": [{"system": "http://snomed.info/sct"}]}}', "utf-8"
    )
    problems = lr.check(root)
    assert any(p.startswith("vocab/icu_item_to_snomed.csv: SNOMED CT column") for p in problems)
    assert "vocab/vs.json: names the SNOMED CT system (row snomed-ct: v1 ships none)" in problems


def test_the_snomed_remnants_are_gone() -> None:
    """STD-044 (3): the MIMIC ICU map and the OMOP operator concepts held SNOMED CT. The TWPAS route is the one
    SNOMED CT code the box writes, because the IG's required value set has no other oral code (D-376, amends D-342)."""
    from omop import vocab

    assert not (ROOT / "services/adapter/mapping/mimic/tables/icu_item_to_snomed.csv").exists()
    assert all(c[3] != "SNOMED" for c in vocab.STANDARD)
    assert {vocab.OPERATOR[k] for k in ("<", "<=", "=", ">", ">=")} == {4171756, 4171754, 4172703, 4172704, 4171755}
    src = (ROOT / "services/orchestrator/reports/twpas_bundle.py").read_text(encoding="utf-8")
    assert src.count("snomed.info") == 1 and "Oral route" not in src  # the one route code, no SNOMED CT description


# ------------------------------------------------------------------------------------------------ model rows
def _builds() -> list[dict[str, object]]:
    doc = yaml.safe_load((ROOT / "models/registry.yaml").read_text(encoding="utf-8"))
    return list(doc["builds"])


@pytest.mark.req("MOD-8")
def test_every_verified_model_licence_is_backed_by_its_row() -> None:
    rows = {r.id: r for r in lr.load()}
    verified = [b for b in _builds() if b["licence"]["verified"]]  # type: ignore[index]
    assert {b["licence"]["register"] for b in verified} == {  # type: ignore[index]
        "model-trialbox-stub",
        "model-gemma-4-26b-a4b-nvfp4",
        "model-qwen3.5-9b-awq-4bit",
        "model-gpt-oss-safeguard-20b",
        "model-bge-m3",  # ENG-003 (D-563): the embedder is a build with a verified licence now
    }
    for rid in ("model-qwen3.5-9b-awq-4bit", "model-gpt-oss-safeguard-20b"):
        assert len(rows[rid].raw["text_sha256"]) == 64 and "revision" in rows[rid].raw["version"]
    assert lr.model_problems(list(rows.values()), _builds()) == []


def test_a_model_licence_that_disagrees_with_its_row_fails() -> None:
    rows = lr.load()
    good = next(b for b in _builds() if b["build_id"] == "qwen3.5-9b-rtxpro6000")
    lic = dict(good["licence"])  # type: ignore[call-overload]
    cases = {
        "no register": {**good, "licence": {**lic, "register": None}},
        "wrong repo": {**good, "repository": "someone/else"},
        "wrong spdx": {**good, "licence": {**lic, "spdx": "MIT"}},
        "not a model row": {**good, "licence": {**lic, "register": "loinc"}},
        "champion unverified": {**good, "status": "champion", "licence": {**lic, "verified": False}},
    }
    got = {k: lr.model_problems(rows, [b]) for k, b in cases.items()}
    assert "licence verified without a register row" in got["no register"][0]
    assert "repository 'someone/else' is not row" in got["wrong repo"][0]
    assert "spdx 'MIT'" in got["wrong spdx"][0]
    assert any("is not a model row" in p for p in got["not a model row"])
    assert got["champion unverified"] == [
        "build qwen3.5-9b-rtxpro6000: status champion with an unverified licence (stays candidate)"
    ]


def test_the_cli_check_passes_on_the_repository(capsys: pytest.CaptureFixture[str]) -> None:
    assert lr.main(["--check"]) == 0
    assert "0 problems" in capsys.readouterr().out


def test_the_check_runs_on_a_copy(tmp_path: Path) -> None:
    """The check reads only its root: a copy of the register and registry over a small tree."""
    root = _tree(tmp_path, _row("loinc", "vocab/*.csv"))
    (root / "models").mkdir()
    shutil.copy(ROOT / "models/registry.yaml", root / "models/registry.yaml")
    assert any("licence verified without a register row" in p for p in lr.check(root))


# Review 17 §7.2, in judge-then-verifier order.
STAGE_H = {
    "model-gemma-4-26b-a4b-it": "google/gemma-4-26B-A4B-it",
    "model-gemma-4-31b-it": "google/gemma-4-31B-it",
    "model-qwen3.8-27b": "Qwen/Qwen3.8-27B",
    "model-qwen3.6-35b-a3b": "Qwen/Qwen3.6-35B-A3B",
    "model-gpt-oss-120b": "openai/gpt-oss-120b",
    "model-llm-jp-4.1-32b-a3b-thinking": "llm-jp/llm-jp-4.1-32b-a3b-thinking",
    "model-weblab-medllm-gpt-oss-120b": "weblab-LLM-M/Weblab-MedLLM-gpt-oss-120b",
    "model-qwen3.5-9b-awq-4bit": "cyankiwi/Qwen3.5-9B-AWQ-4bit",
    "model-gemma-4-12b-it": "google/gemma-4-12B-it",
    "model-nemotron-nano-9b-v2-japanese": "nvidia/NVIDIA-Nemotron-Nano-9B-v2-Japanese",
    "model-gpt-oss-20b": "openai/gpt-oss-20b",
}


def test_stage_h_has_one_build_specific_row_per_slot() -> None:
    rows = lr.load()
    shipped = {b["licence"]["register"] for b in _builds() if b["licence"]["verified"]}
    assert len(STAGE_H) == 11
    assert shipped & STAGE_H.keys() == {"model-qwen3.5-9b-awq-4bit"}
    for rid, source in STAGE_H.items():
        (row,) = [r for r in rows if r.kind == "model" and r.source == source]
        assert row.id == rid
        revision = row.raw["version"].removeprefix("revision ")
        assert len(revision) == 40 and revision in row.raw["evidence"]
        if rid == "model-nemotron-nano-9b-v2-japanese":
            assert row.status == "pending"
        else:
            assert row.status == "cleared"
            assert row.spdx == "Apache-2.0" and len(row.raw["text_sha256"]) == 64
            assert "Stage H evaluation only" in row.raw["obligation"] or rid in shipped
        for locale in ("en", "zh-TW", "ja"):
            assert f"[{locale}]" in row.raw["obligation"]

    by_id = {r.id: r for r in rows}
    for rid in ("model-llm-jp-4.1-32b-a3b-thinking", "model-weblab-medllm-gpt-oss-120b"):
        assert "Provider required" in by_id[rid].raw["obligation"]


def test_cleared_stage_h_rows_preserve_publisher_licence_hashes() -> None:
    # SHA-256 of pinned LICENSE bytes or the ASF 2.0 text referenced by the pinned cards.
    asf = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
    oss = "58d1e17ffe5109a7ae296caafcadfdbe6a7d176f0bc4ab01e12a689b0499d8bd"
    qwen = "bbedc3fda3305820b977265f01b8619d87570a6739de3a5582c3464840f1e57a"
    assert {r.id: r.raw["text_sha256"] for r in lr.load() if r.id in STAGE_H and r.status == "cleared"} == {
        "model-gemma-4-26b-a4b-it": asf,
        "model-gemma-4-31b-it": asf,
        "model-qwen3.8-27b": qwen,
        "model-qwen3.6-35b-a3b": "50cbab8a892c5f2993b8c7351a99182507472def3b1374558308605d99b86b32",
        "model-gpt-oss-120b": oss,
        "model-llm-jp-4.1-32b-a3b-thinking": asf,
        "model-weblab-medllm-gpt-oss-120b": oss,
        "model-qwen3.5-9b-awq-4bit": qwen,
        "model-gemma-4-12b-it": asf,
        "model-gpt-oss-20b": oss,
    }


def test_full_precision_and_shipped_gemma_have_distinct_pins() -> None:
    rows = lr.load()
    by_id = {r.id: r for r in rows}
    full = by_id["model-gemma-4-26b-a4b-it"]
    nvfp4 = by_id["model-gemma-4-26b-a4b-nvfp4"]
    judge = next(b for b in _builds() if b["build_id"] == "gemma-4-26b-a4b-it-rtxpro6000")
    verifier = next(b for b in _builds() if b["build_id"] == "qwen3.5-9b-rtxpro6000")
    assert lr.model_problems(rows, [judge, verifier]) == []
    assert nvfp4.source == judge["repository"]
    assert nvfp4.raw["version"] == f"revision {judge['expected']['revision']}"
    base = judge["provenance"]["base"]
    assert full.source == base["repository"]
    assert full.raw["version"] == f"revision {base['revision']}"
    wrong_pin = {**judge, "expected": {"revision": base["revision"]}}
    assert any("revision" in p for p in lr.model_problems(rows, [wrong_pin]))


def test_section_4_3_exclusions_are_documented() -> None:
    rows = {r.id: r for r in lr.load()}
    shipped_sources = {b["repository"] for b in _builds() if b["licence"]["verified"]}
    for rid, reason in {
        "model-qwen3.8-flash-next": "Community",
        "model-medgemma": "Health AI Developer Foundations",
        "model-qwen4-max": "Hosted only",
    }.items():
        row = rows[rid]
        assert row.status in {"removed", "pending"} and row.source not in shipped_sources
        assert reason in row.raw["obligation"]
        for locale in ("en", "zh-TW", "ja"):
            assert f"[{locale}]" in row.raw["obligation"]


@pytest.mark.parametrize(
    ("licence", "spdx"),
    [
        ("Qwen Community License 1.0", "LicenseRef-Qwen-Community-1.0"),
        ("Health AI Developer Foundations", "LicenseRef-Health-AI-Developer-Foundations"),
    ],
)
def test_excluded_licence_fails_even_with_matching_cleared_row(
    licence: str,
    spdx: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = _row("loinc", "vocab/*.csv")
    rows += _row("synthetic-model", kind="model", source="fixture/model", licence=licence, spdx=spdx)
    root = _tree(tmp_path, rows)
    fake = types.ModuleType("omop.vocab_load")
    fake.ATHENA_ALLOW = frozenset()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "omop.vocab_load", fake)
    registry = root / "models/registry.yaml"
    registry.parent.mkdir()
    build = {
        "build_id": "synthetic-shipped",
        "status": "champion",
        "repository": "fixture/model",
        "licence": {"verified": True, "register": "synthetic-model", "name": licence, "spdx": spdx},
    }
    registry.write_text(yaml.safe_dump({"builds": [build]}), encoding="utf-8")
    check_tree = lr.check
    monkeypatch.setattr(lr, "check", lambda: check_tree(root))
    assert lr.main(["--check"]) == 1
    (problem,) = capsys.readouterr().err.splitlines()
    assert all(part in problem for part in ("synthetic-shipped", licence, "93"))


def test_verified_flag_cannot_clear_pending_nemotron() -> None:
    rows = lr.load()
    row = next(r for r in rows if r.id == "model-nemotron-nano-9b-v2-japanese")
    assert row.status == "pending" and not row.raw["text_sha256"]
    build = {
        "build_id": "synthetic-nemotron", "status": "champion", "repository": row.source,
        "revision": row.raw["version"].removeprefix("revision "),
        "licence": {"verified": True, "register": row.id, "spdx": row.spdx},
    }
    assert any("synthetic-nemotron" in p and "pending" in p for p in lr.model_problems(rows, [build]))
