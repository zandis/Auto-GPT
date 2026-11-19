"""Card 10A-1c: ``tools.negated_inclusion_score`` scores a stranger's file of labelled lines in one command.

Synthetic lines; no patients.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import negated_inclusion_score as tool

FIX = Path(__file__).resolve().parents[1] / "fixtures/negated_inclusion"


def test_a_tsv_is_scored_and_a_miss_fails_the_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = tmp_path / "good.tsv"
    good.write_text(
        "lang\texpect\tconcept\ttext\tothers\n"
        "en\theld\tchemotherapy\tNo prior chemotherapy.\t\n"
        "en\truns\tasthma\tAsthma not on oral corticosteroids.\t\n"
        "ja\theld\t化学療法\t化学療法：－\t\n"
        "zh\truns\t手術\t曾接受手術，但未曾接受放射治療。\t放射治療\n",
        encoding="utf-8",
    )
    assert tool.main([str(good), "--rows"]) == 0
    out = capsys.readouterr().out
    assert "missed (negated line that runs): 0 / 2" in out and "held unnecessarily (present line held): 0 / 2" in out
    bad = tmp_path / "bad.tsv"  # a label that is wrong on purpose: the line is negated but labelled as present
    bad.write_text("lang\texpect\tconcept\ttext\nen\truns\tchemotherapy\tNo prior chemotherapy.\n", encoding="utf-8")
    assert tool.main([str(bad), "--rows"]) == 0
    assert "HOLD  [en] No prior chemotherapy." in capsys.readouterr().out
    miss = tmp_path / "miss.tsv"  # a present line labelled as negated: counted as a miss, and the run fails
    miss.write_text("expect\tconcept\ttext\nheld\tasthma\tAsthma.\n", encoding="utf-8")
    assert tool.main([str(miss)]) == 1


def test_a_fixture_file_scores_as_the_table_test_does() -> None:
    rows = tool.read_rows(FIX / "card_10a1c_after.json")
    held = tool.score(rows)
    assert sum(h for r, h in zip(rows, held, strict=True) if r["expect"] == "held") == 63
    assert sum(h for r, h in zip(rows, held, strict=True) if r["expect"] == "runs") == 25


def test_a_row_without_its_label_is_refused(tmp_path: Path) -> None:
    f = tmp_path / "x.tsv"
    f.write_text("expect\tconcept\ttext\nmaybe\tasthma\tAsthma.\n", encoding="utf-8")
    assert tool.main([str(f)]) == 2
