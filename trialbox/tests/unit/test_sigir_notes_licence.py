"""Card H-37 (lane J's review 20, finding 1): the SIGIR 2016 patient notes are CC BY-SA 4.0 (Koopman and Zuccon,
CSIRO, https://researchdata.edu.au/a-test-collection-clinical-trials/664508, read 2026-11-18), not public domain.

NCBI's TrialGPT copy carries a U.S. Government public domain notice, which covers NCBI's criterion labels; the notes
inside it, and TrialBox's zh-TW, ja and mixed translations of them, are CC BY-SA 4.0. Every dataset entry that names
the SIGIR notes says so, and the criterion_ml folder carries the attribution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "https://researchdata.edu.au/a-test-collection-clinical-trials/664508"


def _entries() -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = yaml.safe_load((ROOT / "eval" / "DATASETS.yaml").read_text("utf-8"))[
        "datasets"
    ]
    return entries


def test_every_entry_naming_the_sigir_notes_says_cc_by_sa() -> None:
    entries = _entries()
    sigir = {k: d["licence"] for k, d in entries.items() if "sigir" in d["licence"].lower() or k == "criterion_ml"}
    assert {"criterion_ml", "judge_public", "public_site", "open_cohorts", "phi_second_opinion"} <= set(sigir)
    for key, licence in sigir.items():
        assert "CC BY-SA 4.0" in licence or "as criterion_ml" in licence, key


def test_criterion_ml_names_each_part_and_its_source() -> None:
    licence = _entries()["criterion_ml"]["licence"]
    assert SOURCE in licence
    assert "translations" in licence and "adaptations, CC BY-SA 4.0" in licence
    assert "public domain notice (LICENSE.NCBI)" in licence
    assert "ClinicalTrials.gov" in licence


def test_the_folder_carries_the_attribution() -> None:
    folder = ROOT / "eval" / "criterion_ml"
    notice = (folder / "NOTICE.md").read_text("utf-8")
    for needed in (
        SOURCE,
        "Koopman",
        "Zuccon",
        "CSIRO",
        "creativecommons.org/licenses/by-sa/4.0",
        "machine translations",
    ):
        assert needed in notice, needed
    for name in ("notes_en.json", "notes_zh-TW.json", "notes_ja.json", "notes_mixed.json", "annotations.jsonl"):
        assert name in notice and (folder / name).exists(), name
    readme = (folder / "README.md").read_text("utf-8")
    assert "**CC BY-SA 4.0**" in readme and "NOTICE.md" in readme
