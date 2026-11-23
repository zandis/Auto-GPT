"""Card 10H-1 (plan 10, Track H; review 20, item 20-2): evaluation data carries the licence its source publishes.

The SIGIR 2016 patient descriptions are CC BY-SA 4.0 (Koopman and Zuccon, CSIRO,
https://researchdata.edu.au/a-test-collection-clinical-trials/664508, re-read 2026-11-19), and so are this project's
translations of them. No text file may call them public domain in any spelling; NCBI's "public domain notice" may be
named only for NCBI's labels, code or corpora. Every file that holds their text carries the attribution, and lies in a
data set of ``eval/DATASETS.yaml`` that names the register row. Every data set names its rows of
``docs/licences/register.csv`` and states each row's licence.

The same checks are part of ``python -m tools.licence_register --check`` (CI job ``checks``, every tier), so they
cannot be skipped by leaving this file out.
"""

from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

from tools import licence_register as lr

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database

ROOT = lr.ROOT
SIGIR_SOURCE = "https://researchdata.edu.au/a-test-collection-clinical-trials/664508"
SENTENCE = "A 58-year-old woman presents with a three-week history of exertional dyspnoea and cough."
CONSENT = "The patient will provide informed consent, and will comply with the trial protocol without any issues."
ATTRIBUTION = "SIGIR 2016, Koopman and Zuccon, CSIRO, CC BY-SA 4.0.\n"


def _rows() -> dict[str, dict[str, str]]:
    with (ROOT / "docs/licences/register.csv").open(encoding="utf-8", newline="") as fh:
        return {r["id"]: r for r in csv.DictReader(fh)}


# ------------------------------------------------------------------------------------------------ the repository
def test_no_file_calls_the_sigir_notes_public_domain_and_each_copy_is_attributed() -> None:
    files = lr.sigir_derived_files()
    for f in ("eval/criterion_ml/notes_en.json", "eval/criterion_ml/notes_ja.json",
              "eval/criterion_ml/notes_zh-TW.json", "eval/criterion_ml/notes_mixed.json",
              "tests/fixtures/public_accuracy_p1b/replay_slice.json",
              "docs/plan/measurements/p2b-review-2026-11-17.md", "tests/unit/test_no_inferred_diagnosis.py"):  # fmt: skip
        assert f in files, f
    assert "services/matching/registry_match/core.py" not in files  # only NCBI's added consent sentence
    assert lr.sigir_problems(ROOT) == []
    assert lr.dataset_file_problems(ROOT, files) == []


def test_every_data_set_states_the_licence_of_its_register_rows() -> None:
    assert lr.dataset_problems(ROOT, lr.load()) == []
    entries = yaml.safe_load((ROOT / lr.DATASETS).read_text("utf-8"))["datasets"]
    sigir = {k for k, d in entries.items() if lr.SIGIR_ROW in (d.get("register") or [])}
    assert {"criterion_ml", "judge_public", "public_site", "open_cohorts", "phi_second_opinion", "trialgpt_compare",
            "match_registry", "public_accuracy_key", "bakeoff", "public_accuracy_p1b"} <= sigir  # fmt: skip
    assert entries["medtxt"]["register"] == ["medtxt"]


def test_the_sigir_row_is_cc_by_sa_with_the_publishers_citation() -> None:
    row = _rows()["pubacc-sigir-2016"]
    assert row["spdx"] == "CC-BY-SA-4.0" and row["source"] == SIGIR_SOURCE
    assert "https://doi.org/10.4225/08/58e2e83d92c2b" in row["obligation"]
    assert "eval/criterion_ml" in row["evidence"] and "nothing committed" not in row["evidence"]
    for f in ("NOTICE", "eval/criterion_ml/NOTICE.md"):
        assert "https://doi.org/10.4225/08/58e2e83d92c2b" in (ROOT / f).read_text("utf-8"), f
    notice = (ROOT / "eval/criterion_ml/NOTICE.md").read_text("utf-8")
    assert "the words are unchanged" not in notice and "translated by this project" in notice


def test_medtxt_jmed_dict_mini_manbyo_and_mimic_have_rows() -> None:
    rows = _rows()
    medtxt = rows["medtxt"]  # 148 reports used, 100 on offer "due to licensing issues": cleared by the owner's ruling
    assert medtxt["spdx"] == "CC-BY-4.0" and medtxt["status"] == "cleared"  # 2026-11-23, #639 7116492812 (was: asked)
    assert "7116492812" in medtxt["evidence"]  # the ruling it rests on
    assert rows["jmed-dict-mini"]["spdx"] == "CC-BY-4.0" and "SNOMED" in rows["jmed-dict-mini"]["obligation"]
    manbyo = rows["manbyo"]
    assert manbyo["status"] == "permission-to-ask" and "asked" in manbyo["licence"]
    assert "feel free to use it" in manbyo["licence"] and "CC BY" not in manbyo["spdx"]
    assert "Bennett, A., Ulrich, H." in rows["mimic-iv-fhir-demo"]["obligation"]
    assert not any(rows[r]["paths"] for r in ("medtxt", "jmed-dict-mini", "manbyo"))  # none is committed


# ------------------------------------------------------------------------------------------------ the rules
def _sigir_tree(tmp_path: Path, readme: str = ATTRIBUTION, entry: Mapping[str, object] | None = None) -> Path:
    shutil.copytree(ROOT / "docs/licences", tmp_path / "docs/licences")
    notes = tmp_path / "eval/criterion_ml"
    notes.mkdir(parents=True)
    (notes / "notes_en.json").write_text(json.dumps({"sigir-20141": [SENTENCE, CONSENT]}), encoding="utf-8")
    (notes / "NOTICE.md").write_text(ATTRIBUTION, encoding="utf-8")
    copy = tmp_path / "tests/fixtures/x"
    copy.mkdir(parents=True)
    (copy / "slice.json").write_text(json.dumps({"id": "sigir-20141", "note": SENTENCE}), encoding="utf-8")
    (copy / "README.md").write_text(readme, encoding="utf-8")
    licence = "SIGIR 2016, CC BY-SA 4.0 (CSIRO)"
    entry = entry or {"path": "tests/fixtures/x", "kind": "open", "licence": licence, "register": [lr.SIGIR_ROW]}
    crit = {"path": "eval/criterion_ml", "kind": "open", "licence": licence, "register": [lr.SIGIR_ROW]}
    (tmp_path / lr.DATASETS).write_text(yaml.safe_dump({"datasets": {"x": entry, "c": crit}}), encoding="utf-8")
    return tmp_path


def _load(root: Path) -> list[lr.Row]:
    return lr.load(root / "docs/licences/register.csv")


def _write(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")


def test_a_clean_tree_passes(tmp_path: Path) -> None:
    root = _sigir_tree(tmp_path)
    assert lr.sigir_derived_files(root) == ["eval/criterion_ml/notes_en.json", "tests/fixtures/x/slice.json"]
    assert lr.sigir_problems(root) == []
    assert lr.dataset_problems(root, _load(root)) == []
    assert lr.dataset_file_problems(root, lr.sigir_derived_files(root)) == []


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        ("tools/site.py", '"**Real.** SIGIR 2016 patient descriptions (NCBI TrialGPT release, public domain); "\n'),
        ("eval/bakeoff/summary.md", "Open data only (SIGIR notes, public domain).\n"),
        ("docs/x.md", "The SIGIR notes are public_domain.\n"),
        ("spec/x.md", "| zh-TW, ja and mixed renderings of the 53 notes | Derivative of Public-Domain text |\n"),
        (
            "tools/bench.py",
            '"""Data: NCBI annotations (1,015 pairs; the SIGIR notes carry NCBI\'s public domain notice)."""\n',
        ),
        ("docs/y.md", "The labels and the notes:\nthe 53 SIGIR notes,\nU.S. Government work, public domain.\n"),
    ],
)
def test_calling_the_notes_public_domain_anywhere_fails(tmp_path: Path, rel: str, text: str) -> None:
    root = _sigir_tree(tmp_path)
    _write(root, rel, text)
    got = lr.sigir_problems(root)
    assert len(got) == 1 and got[0].startswith(f"{rel}: line ") and "calls SIGIR 2016 material public domain" in got[0]


@pytest.mark.parametrize(
    "text",
    [
        "Criterion labels (annotations.jsonl): NCBI TrialGPT, public domain notice (LICENSE.NCBI).\n",
        "SIGIR 2016 cohort, CC BY-SA 4.0 (CSIRO), as redistributed by NCBI TrialGPT (public domain notice).\n",
        "The SIGIR notes are not public domain: CC BY-SA 4.0.\n",
        "ICD-10-CM is U.S. public domain (CMS).\n\nThe SIGIR notes are CC BY-SA 4.0.\n",
        '"LicenseRef-US-Public-Domain",  # the SPDX id of the labels row\n',
    ],
)
def test_ncbi_s_notice_on_its_labels_and_other_sources_pass(tmp_path: Path, text: str) -> None:
    root = _sigir_tree(tmp_path)
    _write(root, "docs/ok.md", "About the SIGIR notes.\n\n" + text)
    assert lr.sigir_problems(root) == []


def test_a_copy_of_the_note_text_needs_the_attribution(tmp_path: Path) -> None:
    root = _sigir_tree(tmp_path)
    _write(root, "docs/review.md", f"The run quoted: {SENTENCE}\n")
    assert lr.sigir_problems(root) == [
        "docs/review.md: holds SIGIR 2016 note text without its attribution (CC BY-SA 4.0, CSIRO), in the file or "
        "in a README.md or NOTICE.md of its folder"
    ]


def test_an_attributed_copy_and_ncbi_s_consent_sentence_pass(tmp_path: Path) -> None:
    root = _sigir_tree(tmp_path)
    _write(root, "docs/review.md", f"The run quoted: {SENTENCE}\n{ATTRIBUTION}")
    _write(root, "docs/consent.md", f"{CONSENT}\n")  # NCBI's own added sentence is not CSIRO's text
    assert "docs/consent.md" not in lr.sigir_derived_files(root)
    assert lr.sigir_problems(root) == []


def test_a_copy_in_a_data_folder_needs_a_data_set_that_names_the_row(tmp_path: Path) -> None:
    root = _sigir_tree(tmp_path)
    _write(root, "eval/other/answers.json", json.dumps({"quote": SENTENCE}))
    _write(root, "eval/other/README.md", ATTRIBUTION)
    assert lr.dataset_file_problems(root, lr.sigir_derived_files(root)) == [
        "eval/other/answers.json: holds SIGIR 2016 note text but no eval/DATASETS.yaml entry naming "
        "pubacc-sigir-2016 covers it"
    ]


def test_a_data_set_readme_that_names_sigir_states_its_licence(tmp_path: Path) -> None:
    root = _sigir_tree(tmp_path)
    _write(root, "eval/outcomes/README.md", "Outcomes of the SIGIR set (NCBI, LICENSE.NCBI).\n")
    assert lr.sigir_problems(root) == ["eval/outcomes/README.md: names SIGIR 2016 but not its licence, CC BY-SA 4.0"]


def test_a_data_set_whose_licence_disagrees_with_its_rows_fails(tmp_path: Path) -> None:
    bad = {"path": "tests/fixtures/x", "kind": "open", "licence": "SIGIR 2016 notes, public domain (NCBI)"}
    root = _sigir_tree(tmp_path, entry=bad)
    got = lr.dataset_problems(root, _load(root))
    assert any("names no register row" in p for p in got)
    assert any("names SIGIR material but not register row pubacc-sigir-2016" in p for p in got)
    assert any("calls SIGIR-derived material public domain" in p for p in got)
    assert any("says public domain, but no register row it names does" in p for p in got)
    wrong = {"kind": "open", "licence": "MedTxt, CC BY-SA 4.0", "register": ["medtxt", "no-such-row"]}
    (root / lr.DATASETS).write_text(yaml.safe_dump({"datasets": {"m": wrong}}), encoding="utf-8")
    got = lr.dataset_problems(root, _load(root))
    assert "eval/DATASETS.yaml m: register row no-such-row does not exist" in got
    assert "eval/DATASETS.yaml m: licence does not say 'CC BY 4.0', as register row medtxt (CC-BY-4.0) does" in got
