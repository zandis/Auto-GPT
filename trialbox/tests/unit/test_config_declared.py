"""T-108d (D-389): every ``TB_*`` setting the code reads is in ``tb_common.config.DECLARED`` with a type, a default
and a doc line, and nothing is declared that nothing reads.

A read is a ``"TB_..."`` string literal in the Python of ``libs``, ``services``, ``tools`` or ``deploy`` (the forms
``os.environ.get("TB_X")``, ``env["TB_X"]``, ``_ENV_MAP`` keys and the like). Names built at run time belong to a
family (``DECLARED_FAMILIES``)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tb_common.config import _ENV_MAP, DECLARED, DECLARED_FAMILIES, Declared

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database

ROOT = Path(__file__).resolve().parents[2]
SCANNED = ("libs", "services", "tools", "deploy")
LITERAL = re.compile(r"""["'](TB_[A-Z0-9_]+)["']""")
KINDS = {"str", "int", "float", "bool", "path"}
LIST_START = "the declared TB_* list"  # config.py from here on is the list itself, not a read


def read_names(roots: list[Path]) -> dict[str, str]:
    """Every ``TB_*`` literal under ``roots``, with the first file that reads it."""
    found: dict[str, str] = {}
    for root in roots:
        for f in sorted(root.rglob("*.py")):
            if ".venv" in f.parts or "generated" in f.parts:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            if f.name == "config.py" and LIST_START in text:
                text = text.split(LIST_START, 1)[0]
            for name in LITERAL.findall(text):
                found.setdefault(name, f.relative_to(root.parent).as_posix())
    return found


def undeclared(found: dict[str, str]) -> list[str]:
    return sorted(
        f"{n} (read in {where})"
        for n, where in found.items()
        if n not in DECLARED and not any(n.startswith(p) for p in DECLARED_FAMILIES)
    )


def test_every_tb_setting_read_is_declared() -> None:
    bad = undeclared(read_names([ROOT / d for d in SCANNED]))
    assert not bad, "add these to tb_common.config.DECLARED (type, default, doc):\n  " + "\n  ".join(bad)


# the installer's own shell scripts read settings too (TB_KEK_BACKEND, TB_SYSTEMD, TB_BOX_DEFER_SEAL, D-836, D-837):
# a declared row they read is not stale. Only these folders, only ${TB_X} / $TB_X; the undeclared check stays on Python
SHELL_READERS = ("deploy/*.sh", "deploy/hardening/*.sh")
SHELL_READ = re.compile(r"\$\{?(TB_[A-Z0-9_]+)")


def shell_reads(root: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for pattern in SHELL_READERS:
        for f in sorted(root.glob(pattern)):
            for name in SHELL_READ.findall(f.read_text(encoding="utf-8", errors="replace")):
                found.setdefault(name, f.relative_to(root).as_posix())
    return found


def test_nothing_is_declared_that_nothing_reads() -> None:
    found = {**shell_reads(ROOT), **read_names([ROOT / d for d in SCANNED])}
    stale = sorted(n for n in DECLARED if n not in found)
    assert not stale, f"declared but read nowhere (remove the rows): {stale}"


def test_each_row_has_a_kind_a_default_and_a_doc_line() -> None:
    for name, d in DECLARED.items():
        assert isinstance(d, Declared) and re.fullmatch(r"TB_[A-Z0-9_]+", name), name
        assert d.kind in KINDS, f"{name}: kind {d.kind!r}"
        assert d.doc.strip() and "\n" not in d.doc and len(d.doc) <= 100, f"{name}: one short doc line"
        if d.default and d.kind == "int":
            int(d.default)
        if d.default and d.kind == "float":
            float(d.default)
        if d.kind == "bool":
            assert d.default in ("", "0", "1"), f"{name}: a bool default is 0 or 1"
    for prefix, doc in DECLARED_FAMILIES.items():
        assert prefix.startswith("TB_") and prefix.endswith("_") and doc.strip()


def test_the_env_map_names_are_declared() -> None:
    assert sorted(n for n in _ENV_MAP if n.startswith("TB_") and n not in DECLARED) == []


def test_a_planted_undeclared_setting_fails(tmp_path: Path) -> None:
    pkg = tmp_path / "libs" / "planted"
    pkg.mkdir(parents=True)
    (pkg / "x.py").write_text('import os\nX = os.environ.get("TB_X")\nY = os.environ["TB_TZ"]\n', encoding="utf-8")
    bad = undeclared(read_names([tmp_path / "libs"]))
    assert bad == ["TB_X (read in libs/planted/x.py)"]
    (pkg / "y.py").write_text('import os\nZ = [k for k in os.environ if k.startswith("TB_EP_")]\n', encoding="utf-8")
    assert undeclared(read_names([tmp_path / "libs"])) == bad  # a family prefix is declared
