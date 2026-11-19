"""Card H-52: a one-shot process that reads a Parquet table with pyarrow's threaded reader can abort at interpreter
exit ("terminate called without an active exception", status 134) after the read itself succeeded. CI's box
rehearsal and `trialbox doctor` hit it 1 to 2 % of the time; under load in a container it reproduced at 40 of 600.
Every `pq.read_table` in libs/, services/ and tools/ is reachable from a one-shot process (a CLI, a `docker exec`
command, the doctor, install, the nightly's steps), so each one reads with ``use_threads=False``.

The static guard is the real protection (a new site without the keyword fails it). The subprocess loop runs the
rehearsal's exact command; at the measured rate it would very likely catch a regression of that one site under
load, but a pass cannot prove the abort absent."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCANNED = ("libs", "services", "tools")
pytestmark = pytest.mark.nodb  # files and subprocesses only; no database

READERS = {"read_table"}  # pyarrow.parquet's whole-table reader; ParquetFile and dataset() are not used here (H-52)


def _parquet_aliases(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.asname or a.name for a in node.names if a.name == "pyarrow.parquet"}
        elif isinstance(node, ast.ImportFrom) and node.module == "pyarrow":
            names |= {a.asname or a.name for a in node.names if a.name == "parquet"}
    return names


def _sites() -> list[tuple[str, int, bool]]:
    out: list[tuple[str, int, bool]] = []
    for top in SCANNED:
        for path in sorted((ROOT / top).rglob("*.py")):
            if ".venv" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if "pyarrow" not in text:
                continue
            tree = ast.parse(text, str(path))
            aliases = _parquet_aliases(tree)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                f = node.func
                if f.attr in READERS and isinstance(f.value, ast.Name) and f.value.id in aliases:
                    single = any(
                        k.arg == "use_threads" and isinstance(k.value, ast.Constant) and k.value.value is False
                        for k in node.keywords
                    )
                    out.append((str(path.relative_to(ROOT)), node.lineno, single))
    return out


@pytest.mark.guard
def test_every_parquet_read_is_single_threaded() -> None:
    sites = _sites()
    # the scan must see the sites it guards (15 at H-52); an empty scan would pass for the wrong reason
    assert len(sites) >= 15, sites
    threaded = [f"{p}:{n}" for p, n, single in sites if not single]
    assert not threaded, (
        "pq.read_table without use_threads=False (H-52: a one-shot process can abort at exit after a threaded read): "
        + ", ".join(threaded)
    )


READ_IT = """from criteria_compiler.terminology import installed as i
t = {x.name: x for x in i.status(i.installed_dir())}.get("site_rehearsal")
assert t and not t.problem and t.rows == 2, t
print(f"{t.name} {t.rows} rows")"""  # tools/rehearse_box/box.sh, the terminology check run in each reader


@pytest.mark.slow
def test_rehearsal_read_exits_zero_every_time(tmp_path: Path) -> None:
    from criteria_compiler.terminology import installed

    site = tmp_path / "rehearsal_local.csv"
    site.write_text("local_code,local_name,code\nL1,Local one,E11.9\nL2,Local two,I10\n", encoding="utf-8")
    term = tmp_path / "terminology"
    assert installed.install_site_list(site, term, "rehearsal", system="icd10cm") == {"site_rehearsal": 2}
    env = {
        **os.environ,
        installed.DIR_ENV: str(term),
        "PYTHONPATH": os.pathsep.join(str(ROOT / p) for p in ("libs", "services", ".")),
    }

    def once(_: int) -> tuple[int, str, str]:
        r = subprocess.run(
            [sys.executable, "-c", READ_IT],
            check=False,
            env=env,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    with ThreadPoolExecutor(2) as pool:
        runs = list(pool.map(once, range(40)))
    bad = [r for r in runs if r[0] != 0 or r[1] != "site_rehearsal 2 rows"]
    assert not bad, f"{len(bad)} of {len(runs)} runs failed; first: {bad[0]}"
