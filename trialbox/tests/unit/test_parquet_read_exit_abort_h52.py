"""Card H-52: a one-shot process that reads a Parquet table with pyarrow's threaded reader can abort at interpreter
exit ("terminate called without an active exception", status 134) after the read itself succeeded. CI's box
rehearsal and `trialbox doctor` hit it 1 to 2 % of the time; under load in a container it reproduced at 40 of 600.
Every `pq.read_table` in libs/, services/ and tools/ is reachable from a one-shot process (a CLI, a `docker exec`
command, the doctor, install, the nightly's steps), so each one reads with ``use_threads=False``.

The static guard (tests/unit/test_parquet_single_thread_guard_h52.py) is the real protection (a new site without the keyword fails it). The subprocess loop runs the
rehearsal's exact command; at the measured rate it would very likely catch a regression of that one site under
load, but a pass cannot prove the abort absent."""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.nodb  # files and subprocesses only; no database

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


THREADS_AROUND_READ = """import os
from criteria_compiler.terminology import installed as i
def tasks():
    return len(os.listdir("/proc/self/task"))
before = tasks()
t = {x.name: x for x in i.status(i.installed_dir())}.get("site_rehearsal")
assert t and not t.problem and t.rows == 2, t
print(before, tasks())"""


def test_rehearsal_read_starts_no_thread(tmp_path: Path) -> None:
    """Card H-62 (docs/handover/exit-abort-third-sighting-2026-11-19.md): ``pq.read_table(pa.BufferReader(bytes),
    use_threads=False)`` still ran the dataset scanner on Arrow's IO pool, whose worker could drop the last reference
    to the Python ``bytes`` after the interpreter began to finalize, and abort the process. The read now starts no
    thread, so no thread but the main one can hold the buffer. Deterministic, unlike the loop above: on master before
    H-62 the read added one thread (the IO pool's worker)."""
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
    r = subprocess.run(
        [sys.executable, "-c", THREADS_AROUND_READ],
        check=False,
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    before, after = (int(x) for x in r.stdout.split())
    assert after == before, f"the read started {after - before} thread(s): {before} before, {after} after"
