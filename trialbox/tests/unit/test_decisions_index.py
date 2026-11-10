"""tools/decisions_index.py (T-002, D-306): one decision number, one text, one owner; decision branches merge cleanly."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools import decisions_index as di

REPO = Path(__file__).resolve().parents[2]

LOG = """# Decisions log

## Phase 0

**D-01 First.** Text.

**D-02 Second.** Text.
"""

REGISTRY = """# Decision number registry

| Number | State | Holder | Note |
| --- | --- | --- | --- |
| D-01..D-02 | merged | phase 0 | log |
| D-03 | unused | — | gap |
| D-04 | reserved | T-101 | first card |
| D-05 | reserved | T-102a | second card |
"""


def make(root: Path, log: str = LOG, registry: str = REGISTRY, files: dict[str, str] | None = None) -> Path:
    (root / "docs" / "decisions").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "DECISIONS.md").write_text(log, encoding="utf-8")
    (root / "docs" / "decisions" / "REGISTRY.md").write_text(registry, encoding="utf-8")
    for name, text in (files or {}).items():
        (root / "docs" / "decisions" / name).write_text(text, encoding="utf-8")
    return root


def problems(root: Path) -> list[str]:
    return di.check(di.load(root))


def test_master_is_clean() -> None:
    assert di.main(["--check"]) == 0


def test_master_registry_holds_the_agreed_rows() -> None:
    c = di.load(REPO)
    rows = {(r.first, r.last): r for r in c.rows}
    assert rows[(271, 271)].state == "merged"  # fix group D-271 (PR #97), a file since the log froze
    assert rows[(272, 272)].state == "merged"  # fix group D-272 (audit integrity), a file
    assert rows[(273, 289)].state == "reserved"  # the rest of the critical-issues fix groups
    assert rows[(152, 159)].state == "unused" and rows[(164, 169)].state == "unused"
    assert rows[(99, 99)].state == "missing"
    for num, card in [(300, "T-101"), (301, "T-105"), (302, "T-102a"), (303, "T-106"), (304, "T-106"),
                      (305, "T-012a"), (306, "T-002"), (307, "T-508"), (308, "T-501")]:  # fmt: skip
        assert card in rows[(num, num)].holder
    for num in (208, 211, 240, 262):
        assert rows[(num, num)].state == "reserved"
    assert rows[(210, 210)].state == "merged" and "T-111" in rows[(210, 210)].holder  # PR #83, a file


def test_index_prints_every_number(capsys: pytest.CaptureFixture[str]) -> None:
    assert di.main([]) == 0
    out = capsys.readouterr().out
    assert "| D-201 | merged | T-003 |" in out and "| D-302 | reserved |" in out and "| D-99 | missing |" in out


def test_two_files_in_different_ranges_pass(tmp_path: Path) -> None:
    root = make(tmp_path, files={"D-04-a.md": "**D-04 A.** Task T-101.\n", "D-05-b.md": "# D-05 B\n\nCard T-102a.\n"})
    assert problems(root) == []


def test_duplicate_across_log_and_file_fails(tmp_path: Path) -> None:
    root = make(tmp_path, files={"D-02-again.md": "**D-02 Again.** Task T-101.\n"})
    assert any("D-2: in DECISIONS.md" in e for e in problems(root))


def test_two_files_on_one_number_fail(tmp_path: Path) -> None:
    root = make(tmp_path, files={"D-04-a.md": "**D-04 A.** T-101.\n", "D-04-b.md": "**D-04 B.** T-101.\n"})
    assert any("D-4: two files" in e for e in problems(root))


def test_twice_in_the_log_fails(tmp_path: Path) -> None:
    root = make(tmp_path, log=LOG + "\n**D-02 Second again.** Text.\n")
    assert any("twice in DECISIONS.md" in e for e in problems(root))


def test_file_with_no_registry_row_fails(tmp_path: Path) -> None:
    root = make(tmp_path, files={"D-09-new.md": "**D-09 New.** Task T-101.\n"})
    errs = problems(root)
    assert any("D-9: D-09-new.md has no row in REGISTRY.md" in e for e in errs)


def test_gap_without_a_row_fails(tmp_path: Path) -> None:
    root = make(tmp_path, registry=REGISTRY.replace("| D-03 | unused | — | gap |\n", ""))
    assert any("no row for D-3 " in e for e in problems(root))


def test_two_rows_on_one_number_fail(tmp_path: Path) -> None:
    root = make(tmp_path, registry=REGISTRY + "| D-05 | reserved | T-103 | clash |\n")
    assert any("D-5: two registry rows" in e for e in problems(root))


def test_new_entry_in_the_frozen_log_fails(tmp_path: Path) -> None:
    root = make(tmp_path, log=LOG + "\n**D-04 Appended.** Text.\n")
    assert any("the log is frozen" in e for e in problems(root))


def test_file_outside_its_cards_number_fails(tmp_path: Path) -> None:
    root = make(tmp_path, files={"D-04-x.md": "**D-04 X.** Task T-999 took a number it was not given.\n"})
    assert any("does not name its card (T-101)" in e for e in problems(root))


def test_file_name_and_head_must_agree(tmp_path: Path) -> None:
    root = make(tmp_path, files={"D-04-x.md": "**D-05 X.** T-101.\n", "D-5_bad.md": "**D-05** T-102a\n"})
    errs = problems(root)
    assert any("head: the first line must name D-04" in e for e in errs)
    assert any("D-5_bad.md: name" in e for e in errs)


def test_state_against_text(tmp_path: Path) -> None:
    root = make(tmp_path, registry=REGISTRY.replace("| D-05 | reserved |", "| D-05 | merged |"),
                files={"D-03-x.md": "**D-03 X.**\n"})  # fmt: skip
    errs = problems(root)
    assert any("merged, but D-5 has no text" in e for e in errs)
    assert any("D-3: D-03-x.md lands on a row marked unused" in e for e in errs)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def test_two_branches_each_adding_a_decision_and_a_contract_merge_cleanly(tmp_path: Path) -> None:
    """Acceptance of T-002: decision files and generated contract models do not conflict between two branches."""
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    shutil.copy(REPO / "tools" / "gen_contracts.py", root / "tools" / "gen_contracts.py")
    shutil.copytree(REPO / "schemas", root / "schemas", ignore=shutil.ignore_patterns("v4"))
    make(root)
    gen = [sys.executable, "tools/gen_contracts.py"]
    assert subprocess.run(gen, cwd=root, capture_output=True, check=False).returncode == 0
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.org"], ["config", "user.name", "t"], ["config", "commit.gpgsign", "false"],
                 ["add", "-A"], ["commit", "-qm", "base"]):  # fmt: skip
        assert _git(root, *args).returncode == 0
    branches = {
        "a": ("D-04-a.md", "**D-04 A.** Task T-101.\n", "aaa_note", "AaaNote", '"text": {"type": "string"}'),
        "b": ("D-05-b.md", "**D-05 B.** Task T-102a.\n", "zzz_flag", "ZzzFlag", '"on": {"type": "boolean"}'),
    }
    for name, (fname, text, stem, title, prop) in branches.items():
        assert _git(root, "checkout", "-q", "-b", name, "main").returncode == 0
        (root / "docs" / "decisions" / fname).write_text(text, encoding="utf-8")
        (root / "schemas" / f"{stem}.schema.json").write_text(
            '{"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "' + stem + '.schema.json", '
            f'"title": "{title}", "description": "Schema version 1.", "type": "object", '
            f'"additionalProperties": false, "properties": {{{prop}}}}}\n',
            encoding="utf-8",
        )
        assert subprocess.run(gen, cwd=root, capture_output=True, check=False).returncode == 0
        assert _git(root, "add", "-A").returncode == 0 and _git(root, "commit", "-qm", name).returncode == 0
    merged = _git(root, "merge", "-q", "--no-edit", "a")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert problems(root) == []
    check = subprocess.run([*gen, "--check"], cwd=root, capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stderr
    models = (root / "libs" / "tb_contracts" / "generated" / "models.py").read_text(encoding="utf-8")
    assert "class AaaNote(" in models and "class ZzzFlag(" in models
