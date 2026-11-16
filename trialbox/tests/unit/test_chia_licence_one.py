"""Lane G's finding 5 (#593, 2026-11-14): ``eval/DATASETS.yaml`` gave the Chia corpus two licences.

The ``chia`` entry says CC BY 4.0 (Kury et al., Sci Data 2020, figshare 10.6084/m9.figshare.11855817), which is what
figshare states; ``criteria_extract_public`` still said "licence unconfirmed". One corpus has one licence. The
suite's loader and the criterion library's seed are still not built (their own card); the entry says so.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_the_chia_corpus_has_one_licence_in_the_dataset_list() -> None:
    data = yaml.safe_load((ROOT / "eval" / "DATASETS.yaml").read_text("utf-8"))["datasets"]
    chia = [d["licence"] for k, d in data.items() if k == "chia" or "chia" in d["licence"].lower()]
    assert len(chia) == 2
    assert all("CC BY 4.0" in x and "10.6084/m9.figshare.11855817" in x for x in chia)
    assert not any("unconfirmed" in x for x in chia)
