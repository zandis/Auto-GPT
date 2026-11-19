"""Card 10H-1 (plan 10, Track H; review 20, item 20-2): evaluation data carries the licence its source publishes.

The SIGIR 2016 patient descriptions are CC BY-SA 4.0 (Koopman and Zuccon, CSIRO,
https://researchdata.edu.au/a-test-collection-clinical-trials/664508, re-read 2026-11-19), and so are TrialBox's
translations of them: no file that holds their text, and no README, NOTICE.md or PROVENANCE.md beside it, may call
them public domain. NCBI's "public domain notice" covers NCBI's criterion labels only. More generally, every data set
of ``eval/DATASETS.yaml`` names its rows of ``docs/licences/register.csv`` and states each row's licence.

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

pytestmark = pytest.mark.guard

ROOT = lr.ROOT
SIGIR_SOURCE = "https://researchdata.edu.au/a-test-collection-clinical-trials/664508"


def _rows() -> dict[str, dict[str, str]]:
    with (ROOT / "docs/licences/register.csv").open(encoding="utf-8", newline="") as fh:
        return {r["id"]: r for r in csv.DictReader(fh)}


# ------------------------------------------------------------------------------------------------ the repository
def test_no_sigir_derived_file_says_public_domain() -> None:
    files = lr.sigir_derived_files()
    for f in ("eval/criterion_ml/notes_en.json", "eval/criterion_ml/notes_ja.json",
              "eval/criterion_ml/notes_zh-TW.json", "eval/criterion_ml/notes_mixed.json",
              "tests/fixtures/public_accuracy_p1b/replay_slice.json"):  # fmt: skip
        assert f in files, f
    assert lr.sigir_problems(ROOT, files) == []


def test_every_data_set_states_the_licence_of_its_register_rows() -> None:
    assert lr.dataset_problems(ROOT, lr.load()) == []
    entries = yaml.safe_load((ROOT / lr.DATASETS).read_text("utf-8"))["datasets"]
    sigir = {k for k, d in entries.items() if lr.SIGIR_ROW in (d.get("register") or [])}
    assert {"criterion_ml", "judge_public", "public_site", "open_cohorts", "phi_second_opinion",
            "trialgpt_compare", "match_registry", "public_accuracy_key"} <= sigir  # fmt: skip
    assert entries["medtxt"]["register"] == ["medtxt"]


def test_the_sigir_row_is_cc_by_sa_with_the_publishers_citation() -> None:
    row = _rows()["pubacc-sigir-2016"]
    assert row["spdx"] == "CC-BY-SA-4.0" and row["source"] == SIGIR_SOURCE
    assert "https://doi.org/10.4225/08/58e2e83d92c2b" in row["obligation"]
    assert "eval/criterion_ml" in row["evidence"] and "nothing committed" not in row["evidence"]
    for f in ("NOTICE", "eval/criterion_ml/NOTICE.md"):
        assert "https://doi.org/10.4225/08/58e2e83d92c2b" in (ROOT / f).read_text("utf-8"), f


def test_medtxt_jmed_dict_mini_and_manbyo_have_rows() -> None:
    rows = _rows()
    assert rows["medtxt"]["spdx"] == "CC-BY-4.0" and rows["medtxt"]["status"] == "cleared"
    assert rows["jmed-dict-mini"]["spdx"] == "CC-BY-4.0" and "SNOMED" in rows["jmed-dict-mini"]["obligation"]
    manbyo = rows["manbyo"]
    assert manbyo["status"] == "permission-to-ask" and "asked" in manbyo["licence"]
    assert "feel free to use it" in manbyo["licence"] and "CC BY" not in manbyo["spdx"]
    assert not any(rows[r]["paths"] for r in ("medtxt", "jmed-dict-mini", "manbyo"))  # none is committed


# ------------------------------------------------------------------------------------------------ the rules
def _load(root: Path) -> list[lr.Row]:
    return lr.load(root / "docs/licences/register.csv")


def _sigir_tree(tmp_path: Path, readme: str, entry: Mapping[str, object]) -> Path:
    shutil.copytree(ROOT / "docs/licences", tmp_path / "docs/licences")
    notes = tmp_path / "eval/criterion_ml"
    notes.mkdir(parents=True)
    sentence = "A 58-year-old woman presents with a three-week history of exertional dyspnoea and cough."
    (notes / "notes_en.json").write_text(json.dumps({"sigir-20141": [sentence]}), encoding="utf-8")
    copy = tmp_path / "tests/fixtures/x"
    copy.mkdir(parents=True)
    (copy / "slice.json").write_text(json.dumps({"id": "sigir-20141", "note": sentence}), encoding="utf-8")
    (copy / "README.md").write_text(readme, encoding="utf-8")
    (tmp_path / lr.DATASETS).write_text(yaml.safe_dump({"datasets": {"x": entry}}), encoding="utf-8")
    return tmp_path


def test_a_copy_of_the_notes_called_public_domain_fails(tmp_path: Path) -> None:
    good = {"kind": "open", "licence": "SIGIR 2016, CC BY-SA 4.0 (CSIRO)", "register": [lr.SIGIR_ROW]}
    root = _sigir_tree(tmp_path, "SIGIR 2016 notes, CC BY-SA 4.0 (CSIRO).\n", good)
    assert lr.sigir_derived_files(root) == ["eval/criterion_ml/notes_en.json", "tests/fixtures/x/slice.json"]
    assert lr.sigir_problems(root) == []
    assert lr.dataset_problems(root, _load(root)) == []
    (root / "tests/fixtures/x/README.md").write_text("The SIGIR notes are in the public domain.\n", encoding="utf-8")
    assert lr.sigir_problems(root) == ["tests/fixtures/x/README.md: beside SIGIR 2016 note text (CC BY-SA 4.0, "
                                       "CSIRO), says public domain"]  # fmt: skip
    (root / "tests/fixtures/x/README.md").write_text("The SIGIR notes, via NCBI.\n", encoding="utf-8")
    assert "but not its licence" in lr.sigir_problems(root)[0]
    (root / "tests/fixtures/x/README.md").write_text("NCBI public domain notice; SIGIR CC BY-SA 4.0.\n", "utf-8")
    assert lr.sigir_problems(root) == []


def test_a_data_set_whose_licence_disagrees_with_its_rows_fails(tmp_path: Path) -> None:
    readme = "SIGIR CC BY-SA 4.0\n"
    bad = {"kind": "open", "licence": "SIGIR 2016 notes, public domain (NCBI)"}
    root = _sigir_tree(tmp_path, readme, bad)
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
