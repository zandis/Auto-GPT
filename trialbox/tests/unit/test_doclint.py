"""tools/doclint.py (TB-PLAN-04 step 9, D-139): the nine documents are clean, and the checks catch what they claim."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import doclint


def test_the_repository_is_clean() -> None:
    assert doclint.main([]) == 0


def test_the_nine_documents() -> None:
    assert len(doclint.DOCS) == 9 and "docs/DECISIONS.md" in doclint.DOCS and "docs/DEVELOPING.md" in doclint.DOCS
    assert not doclint.check_set()


def test_slug_matches_github() -> None:
    assert doclint.slug("11. Cloud runs (owner's OK first)") == "11-cloud-runs-owners-ok-first"
    assert doclint.slug("Secrets (D-128, D-138): the one place") == "secrets-d-128-d-138-the-one-place"


@pytest.fixture
def fake_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "real.py").write_text("")
    monkeypatch.setattr(doclint, "ROOT", tmp_path)
    monkeypatch.setattr(doclint, "ignored", lambda rel: False)
    return tmp_path


def test_catches_links_anchors_paths_and_headings(fake_root: Path) -> None:
    (fake_root / "docs" / "B.md").write_text("# B\n\n## Real part\n")
    (fake_root / "docs" / "A.md").write_text(
        "# A\n\n#### skipped\n\n## Twice\n\n## Twice\n\n"
        "[ok](B.md#real-part) [bad anchor](B.md#nope) [gone](C.md) [web](https://example.org)\n\n"
        "`tools/real.py` `tools/missing.py` `deploy/site/<gpu>.json`\n\n```\n[in a block](nowhere.md)\n```\n"
    )
    errs = doclint.check_doc("docs/A.md")
    text = "\n".join(errs)
    assert "head: level 4 after level 1" in text
    assert "head: twice" in text
    assert "#nope is not a heading" in text
    assert "C.md does not exist" in text
    assert "tools/missing.py does not exist" in text
    assert "real.py" not in text and "example.org" not in text and "nowhere.md" not in text and "<gpu>" not in text
    assert doclint.check_doc("docs/B.md") == []


def test_decisions_is_history(fake_root: Path) -> None:
    (fake_root / "docs" / "DECISIONS.md").write_text("# Decisions\n\n`tools/removed_long_ago.py` [x](gone.md)\n")
    assert doclint.check_doc("docs/DECISIONS.md", history=True) == []


def test_retired_names() -> None:
    hits = [m.group(0) for m in doclint.RETIRED_RE.finditer("see docs/HANDOFF.md and SPEC.md, not SIMPLE-PLAN.md")]
    assert hits == ["docs/HANDOFF.md", "SPEC.md"]
    assert not list(doclint.RETIRED_RE.finditer("spec/archive/SPEC.md and docs/RUNBOOK.md"))


def test_links_and_paths_only_warn_unless_strict(fake_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D-311: a broken link or path in a document is a warning; set, head and gone problems still fail."""
    monkeypatch.setattr(doclint, "DOCS", ["docs/A.md"])
    monkeypatch.setattr(doclint, "check_gone", lambda: [])
    (fake_root / "docs" / "A.md").write_text("# A\n\n[gone](C.md) `tools/missing.py`\n")
    assert doclint.main([]) == 0
    assert doclint.main(["--strict"]) == 1
    (fake_root / "docs" / "A.md").write_text("no title\n")
    assert doclint.main([]) == 1


def test_a_drill_name_with_no_test_fails(fake_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10K-9 (D-1362): a drill a page names must be a ``def`` under tests/; a planted name with no test fails the run,
    in the runbook and in the site tabletops; the records (reviews, plan measurements, decisions) are history."""
    (fake_root / "tests" / "unit").mkdir(parents=True)
    (fake_root / "tests" / "unit" / "test_x.py").write_text("import os\n\n\ndef test_runbook_12_real(tmp_path):\n    "
                                                            "assert os\n", encoding="utf-8")  # fmt: skip
    (fake_root / "docs" / "runbook").mkdir()
    (fake_root / "docs" / "plan" / "sites").mkdir(parents=True)
    (fake_root / "docs" / "plan" / "measurements").mkdir()
    (fake_root / "docs" / "decisions").mkdir()
    page = fake_root / "docs" / "runbook" / "12-x.md"
    page.write_text("# 12. X\n\n**Drill (T-213b):** `test_runbook_12_real` (in process).\n", encoding="utf-8")
    old = "it named `test_runbook_22_gone_long_ago`, which did not exist\n"
    (fake_root / "docs" / "plan" / "measurements" / "m.md").write_text(old, encoding="utf-8")
    (fake_root / "docs" / "decisions" / "D-1.md").write_text(old, encoding="utf-8")
    assert doclint.check_drills() == []
    # a planted name on a runbook page fails, with the page and line
    page.write_text(page.read_text(encoding="utf-8") + "\nSee also `test_runbook_12_planted_drill`.\n",
                    encoding="utf-8")  # fmt: skip
    errs = doclint.check_drills()
    assert len(errs) == 1 and errs[0].startswith("docs/runbook/12-x.md:5: drill: test_runbook_12_planted_drill")
    # in a site tabletop too
    tab = fake_root / "docs" / "plan" / "sites" / "tabletop.md"
    tab.write_text("| 1 | x | `test_runbook_04_tabletop_only` |\n", encoding="utf-8")
    assert any("tabletop.md:1: drill: test_runbook_04_tabletop_only" in e for e in doclint.check_drills())
    # a name mentioned but not defined (a call, a string) is no test
    (fake_root / "tests" / "unit" / "test_y.py").write_text(
        'NAME = "test_runbook_12_planted_drill"\n', encoding="utf-8"
    )
    assert len(doclint.check_drills()) == 2
    # the run fails on it (a failing kind, not a warning)
    monkeypatch.setattr(doclint, "DOCS", [])
    monkeypatch.setattr(doclint, "HUBS", {})
    monkeypatch.setattr(doclint, "check_gone", lambda: [])
    monkeypatch.setattr(doclint, "handover_problems", lambda: [])
    assert doclint.main([]) == 1
    page.write_text("# 12. X\n\n**Drill (T-213b):** `test_runbook_12_real` (in process).\n", encoding="utf-8")
    tab.write_text("| 1 | x | none (not rehearsed by a test) |\n", encoding="utf-8")
    assert doclint.main([]) == 0


def test_every_drill_the_runbook_names_is_a_test() -> None:
    """The repository as it is: each drill named in docs/runbook has its def under tests/."""
    names = {n for p in (REPO / "docs" / "runbook").glob("*.md")
             for n in doclint.DRILL_NAME.findall(p.read_text(encoding="utf-8"))}  # fmt: skip
    assert names and names <= doclint.drill_defs(), sorted(names - doclint.drill_defs())


# --- T-669, D-352: the hot documents as section files ---------------------------------------------------------------

REPO = Path(__file__).resolve().parents[2]


def test_the_four_hubs_have_section_folders_and_a_current_index() -> None:
    for hub, folder in doclint.HUBS.items():
        assert (REPO / folder).is_dir(), folder
        secs, errs = doclint.sections(hub)
        assert errs == [], errs
        assert any(s.file for s in secs.values())
        problems = [e for e in doclint.check_sections(hub) if not any(k in e for k in doclint.WARN_KINDS)]
        assert problems == [], hub  # link and path problems only warn (D-311)


def test_old_links_and_section_numbers_still_resolve() -> None:
    """Links into the old single files (README, VALIDATION, the other documents) and "RUNBOOK §N" in code."""
    for target in (
        "RUNBOOK.md#1-install-a-new-site-about-one-day",
        "RUNBOOK.md#9-proof-of-concept-with-docker",
        "RUNBOOK.md#11-cloud-runs-owners-ok-first",
        "RUNBOOK.md#12-identity-and-tls-d-192-d-193",
        "DATA.md#2-mapping-a-site",
        "DATA.md#6-open-and-public-data-in-the-tests",
        "SECURITY.md#1-the-host",
        "SECURITY.md#2-network",
        "SECURITY.md#7-laws-a-site-must-check",
    ):
        file, anchor = target.split("#")
        assert anchor in doclint.anchors(REPO / "docs" / file), target
    runbook = doclint.sections("docs/RUNBOOK.md")[0]
    for n, words in {
        5: "backup",
        8: "DGX Spark",
        12: "Identity",
        13: "parallel",
        16: "rehearsal",
        17: "platform",
    }.items():
        assert words.lower() in runbook[n].title.lower(), n
    assert ("RUNBOOK §11 section: qualify a model pair (D-313)", "runbook/11-qualify.md") in runbook[11].parts


def test_runbook_numbers_are_one_table() -> None:
    table = doclint.numbers_table((REPO / "docs" / "RUNBOOK.md").read_text(encoding="utf-8"))
    secs = doclint.sections("docs/RUNBOOK.md")[0]
    assert set(table) == set(secs) and sorted(table) == list(range(1, max(table) + 1))
    assert {n for n, s in secs.items() if not s.file} == {
        n for n, (_, holder) in table.items() if holder != "on master"
    }


def _hub(root: Path, table: str = "") -> None:
    (root / "docs" / "runbook").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "RUNBOOK.md").write_text(
        f"# Runbook\n\nOpening.\n\n{doclint.BEGIN}\n\n{doclint.END}\n{table}", encoding="utf-8"
    )


@pytest.fixture
def hub_root(fake_root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(doclint, "HUBS", {"docs/RUNBOOK.md": "docs/runbook"})
    return fake_root


def test_the_index_is_generated_and_checked(hub_root: Path) -> None:
    table = "\n## Section numbers\n\n| § | Title | Holder | Audience |\n| --- | --- | --- | --- |\n"
    table += "| 1 | Install | on master | site |\n| 2 | Later | T-999 | site |\n"
    _hub(hub_root, table)
    rb = hub_root / "docs" / "runbook"
    # every page names its reader (T-735a, D-729)
    (rb / "01-install.md").write_text(
        "# 1. Install a box\n\n**Reader:** hospital IT.\n\nText.\n\n## Before you start\n\nMore.\n"
    )
    (rb / "01-extra.md").write_text("# An extra page\n\n**Reader:** the box owner.\n\nText.\n")
    errs = doclint.check_sections("docs/RUNBOOK.md")
    assert any("index: out of date" in e for e in errs)
    assert doclint.write_index("docs/RUNBOOK.md") and not doclint.write_index("docs/RUNBOOK.md")
    assert doclint.check_sections("docs/RUNBOOK.md") == []
    text = (hub_root / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    assert "## 1. Install a box" in text and "runbook/01-install.md#before-you-start" in text
    assert "[An extra page](runbook/01-extra.md)" in text
    assert "## 2. Later (reserved for T-999)" in text
    assert {"1-install-a-box", "2-later-reserved-for-t-999"} <= doclint.anchors(hub_root / "docs" / "RUNBOOK.md")
    assert text.endswith(table)  # the hand-kept table is left alone
    whole = doclint.whole("docs/RUNBOOK.md")
    assert whole.startswith("# Runbook\n\nOpening.") and "\n## 1. Install a box\n" in whole
    assert "\n### Before you start\n" in whole and "\n## An extra page\n" in whole


def test_number_and_set_problems_fail(hub_root: Path) -> None:
    table = (
        "\n## Section numbers\n\n| § | Title | Holder | Audience |\n| --- | --- | --- | --- |\n| 1 | A | x | site |\n"
    )
    _hub(hub_root, table)
    rb = hub_root / "docs" / "runbook"
    (rb / "01-a.md").write_text("# 1. A\n")
    (rb / "01-b.md").write_text("# 1. B\n")  # one number twice
    (rb / "02-c.md").write_text("# 3. C\n")  # name and title disagree
    (rb / "04-part.md").write_text("# a part of nothing\n")
    (rb / "05-e.md").write_text("# 5. E\n")  # no row in the table
    (rb / "notes.md").write_text("# Notes\n")  # not NN-<slug>.md
    doclint.write_index("docs/RUNBOOK.md")
    text = "\n".join(doclint.check_sections("docs/RUNBOOK.md"))
    assert "§1 is written twice" in text
    assert "the title says §3, the file name says §2" in text
    assert "a part of §4, which has no section file" in text
    assert "§5 has no row in the section-numbers table" in text
    assert "docs/runbook/notes.md: set:" in text


def test_a_missing_index_fails(hub_root: Path) -> None:
    (hub_root / "docs" / "runbook").mkdir(parents=True)
    (hub_root / "docs" / "RUNBOOK.md").write_text("# Runbook\n")
    assert any(
        "index: the generated-index marker lines are missing" in e for e in doclint.check_sections("docs/RUNBOOK.md")
    )
    with pytest.raises(SystemExit):
        doclint.write_index("docs/RUNBOOK.md")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def test_two_branches_each_adding_a_runbook_section_and_a_data_row_merge_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance of T-669: on a copy of the real RUNBOOK and DATA, two branches each write a reserved RUNBOOK section
    (and regenerate the index) and add a row to a DATA table; git merges them with no conflict and the index is
    still current."""
    root = tmp_path / "repo"
    for hub in ("docs/RUNBOOK.md", "docs/DATA.md"):
        (root / hub).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / hub, root / hub)
        shutil.copytree(REPO / doclint.HUBS[hub], root / doclint.HUBS[hub])
    monkeypatch.setattr(doclint, "ROOT", root)
    monkeypatch.setattr(doclint, "HUBS", {h: doclint.HUBS[h] for h in ("docs/RUNBOOK.md", "docs/DATA.md")})
    # The real table may have fewer than two free numbers left; the copy adds two spare rows after its last row.
    runbook = root / "docs/RUNBOOK.md"
    rows = runbook.read_text(encoding="utf-8").splitlines()
    last = max(i for i, line in enumerate(rows) if re.match(r"\| \d+ \|", line))
    top = int(rows[last].split("|")[1])
    rows[last + 1 : last + 1] = [f"| {top + k} | Spare {k} | T-000 | site |" for k in (1, 2)]
    runbook.write_text("\n".join(rows) + "\n", encoding="utf-8")
    doclint.write_index("docs/RUNBOOK.md")
    reserved = [n for n, s in doclint.sections("docs/RUNBOOK.md")[0].items() if not s.file][:2]
    assert len(reserved) == 2
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.org"], ["config", "user.name", "t"],
                 ["config", "commit.gpgsign", "false"], ["add", "-A"], ["commit", "-qm", "base"]):  # fmt: skip
        assert _git(root, *args).returncode == 0
    data = {"a": "docs/data/01-what-the-box-reads.md", "b": "docs/data/05-integration-scenarios.md"}
    for (name, rel), number in zip(data.items(), reserved, strict=True):
        assert _git(root, "checkout", "-q", "-b", name, "main").returncode == 0
        (root / "docs" / "runbook" / f"{number:02d}-branch-{name}.md").write_text(
            f"# {number}. Branch {name} page\n\n**Reader:** the box owner.\n\nSteps.\n\n## Check {name}\n\nDone.\n",
            encoding="utf-8",
        )
        lines = (root / rel).read_text(encoding="utf-8").splitlines()
        last = max(i for i, line in enumerate(lines) if line.startswith("| "))
        lines.insert(last + 1, "| " + " | ".join([f"row {name}"] * lines[last].count(" | ")) + f" | {name} |")
        (root / rel).write_text("\n".join(lines) + "\n", encoding="utf-8")
        for hub in doclint.HUBS:
            doclint.write_index(hub)
        assert _git(root, "add", "-A").returncode == 0 and _git(root, "commit", "-qm", name).returncode == 0
    merged = _git(root, "merge", "-q", "--no-edit", "a")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    for hub in doclint.HUBS:
        assert [e for e in doclint.check_sections(hub) if ": link: " not in e and ": path: " not in e] == [], hub
    index = (root / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    assert f"## {reserved[0]}. Branch a page" in index and f"## {reserved[1]}. Branch b page" in index
    assert "| row a |" in (root / data["a"]).read_text(encoding="utf-8")
    assert "| row b |" in (root / data["b"]).read_text(encoding="utf-8")
