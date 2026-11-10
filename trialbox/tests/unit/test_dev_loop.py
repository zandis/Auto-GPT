"""The developer loop (T-658; DATA-018, DATA-019, D-201 leftovers; RUNBOOK §5 and §13): ``make e2e-simple`` on a fresh
``TB_TEST_ROOT``, missing jars named at start, the restore runbook names the reference pack, a random-order nightly
job, and the tools' own temp defaults under ``TB_SCRATCH``."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pytest

from tools import e2e_simple, pglocal

ROOT = Path(__file__).resolve().parents[2]


def test_a_fresh_root_is_marked_before_the_work_folder_is_made(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """DATA-019: the work folder inside a fresh root used to leave "files and no marker"; the root is marked first."""
    root = tmp_path / "tb-tests-fresh"
    monkeypatch.setenv("TB_TEST_ROOT", str(root))
    e2e_simple.prepare_root()
    (root / "e2e-simple").mkdir()
    assert (root / pglocal.MARKER).exists()
    assert pglocal.test_root() == root.resolve()  # what pglocal.shared_dir() checks; refused before the fix


def test_a_root_of_other_files_is_still_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "tb-tests-other"
    root.mkdir()
    (root / "notes.txt").write_text("not a test root")
    monkeypatch.setenv("TB_TEST_ROOT", str(root))
    with pytest.raises(ValueError, match="no .tb-test-root marker"):
        e2e_simple.prepare_root()
    monkeypatch.setenv("TB_TZ", "Asia/Taipei")  # main() sets it when unset; monkeypatch puts it back
    assert e2e_simple.main(["--dir", str(root / "e2e")]) == 2
    assert not (root / pglocal.MARKER).exists() and not (root / "e2e").exists()


def test_missing_jars_are_named_at_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """DATA-019: no jars: exit 2 before any stage runs, naming ``make jvm-deps``; the work folder is not made."""
    monkeypatch.setenv("TB_CQL_TRANSLATOR_LIB", str(tmp_path / "no-jars"))
    monkeypatch.delenv("TB_TEST_ROOT", raising=False)
    monkeypatch.setenv("TB_TZ", "Asia/Taipei")  # main() sets it when unset; monkeypatch puts it back
    missing = e2e_simple.missing_prerequisites()
    assert len(missing) == 1 and "make jvm-deps" in missing[0]
    work = tmp_path / "e2e"
    assert e2e_simple.main(["--dir", str(work)]) == 2
    err = capsys.readouterr().err
    assert "make jvm-deps" in err and str(tmp_path / "no-jars") in err
    assert not work.exists()


def test_a_broken_jar_is_named_too(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "quick-5.4.0.jar").write_bytes(b"not a zip")
    monkeypatch.setenv("TB_CQL_TRANSLATOR_LIB", str(tmp_path))
    assert "make jvm-deps" in e2e_simple.missing_prerequisites()[0]


def test_the_quick_jar_alone_passes_the_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The run compiles with the in-process fake translator: no Java and no cql-to-elm-cli jar (the demo image)."""
    from criteria_compiler.compile_cql import translator

    with zipfile.ZipFile(tmp_path / "quick-5.4.0.jar", "w") as zf:
        zf.writestr(translator.FHIRHELPERS_ENTRY, "library FHIRHelpers version '4.0.1'\n")
    monkeypatch.setenv("TB_CQL_TRANSLATOR_LIB", str(tmp_path))
    monkeypatch.setenv("TB_JAVA", "tb-no-such-java")
    assert e2e_simple.missing_prerequisites() == []


def test_the_make_target_marks_the_root_before_the_run() -> None:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    body = text.split("\ne2e-simple:\n", 1)[1].split("\n\n", 1)[0]
    lines = [ln.strip() for ln in body.splitlines()]
    assert "pglocal mark" in lines[0] and "tools.e2e_simple" in lines[1]


def test_the_restore_runbook_names_the_reference_pack() -> None:
    """DATA-018: the restore steps say to bring the vendor pack and how to find which one."""
    rb = (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    restore = rb.split("**Restore.**", 1)[1].split("\n\n## ", 1)[0]
    assert "reference data" in restore and "pack" in restore
    assert "refdata_packs" in restore and "backup-verify" in restore and "deploy/refdata/loaded" in restore


def test_a_random_order_nightly_job_exists() -> None:
    """D-201 left the random-order job to a sibling; it runs nightly with the plugin laid over the venv, not locked."""
    wf = ROOT.parent / ".github" / "workflows" / "trialbox-e2e.yml"
    if not wf.exists():
        pytest.skip("workflows not in this checkout")
    text = wf.read_text(encoding="utf-8")
    assert "schedule:" in text and "random-order" in text and "make test-random" in text
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = mk.split("\ntest-random-locked:\n", 1)[1].split("\n\n", 1)[0]
    assert "TB_TEST_RANDOM=1" in recipe and "-p randomly" in recipe and "--with" in recipe
    assert 'name = "pytest-randomly"' not in (ROOT / "uv.lock").read_text(encoding="utf-8")


def test_no_tool_defaults_to_a_fixed_tmp_folder() -> None:
    """D-201 "Not done": the tools' own ``--dir`` defaults were ``/tmp/tb-*``; now under the scratch root."""
    bad = []
    for path in sorted((ROOT / "tools").glob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "default" in line and re.search(r"""["']/tmp/tb[-_]""", line):
                bad.append(f"{path.relative_to(ROOT)}:{n}")
    assert not bad, bad


def test_the_e2e_default_is_under_the_scratch_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TB_SCRATCH", str(tmp_path / "scratch"))
    monkeypatch.delenv("TB_E2E_DIR", raising=False)
    assert pglocal.scratch_root() / "tb-e2e-simple" == tmp_path / "scratch" / "tb-e2e-simple"
