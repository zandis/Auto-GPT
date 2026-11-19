"""H-58 (H10G1-04): a reference data pack that does not load at install is a FAIL line, not a warning.

Before, ``deploy/install.sh`` printed ``install: warning: reference data ... not loaded`` and ended with exit 0: an
offline box then had no trials, and only the box rehearsal's later check noticed (CI run 44458900188). Now the pack
is named in the install's FAIL list (exit 1, the stack left running as for every FAIL line, T-632), with where the
pack stays and how to load it again. The test runs the installer's own loop (cut from ``deploy/install.sh``) with a
``docker`` that answers as compose does; nothing is started.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "deploy" / "install.sh"
START = "for f in deploy/refdata/pending/*.tar; do"
END = '\nif [ "$CTGOV" = offline ]'
PACK = "trialbox-refdata-20261109"

pytestmark = pytest.mark.nodb


def _block() -> str:
    text = INSTALL.read_text(encoding="utf-8")
    assert text.count(START) == 1 and text.count(END) == 1
    return text[text.index(START) : text.index(END)]


def _run(tmp_path: Path, load_rc: int) -> subprocess.CompletedProcess[str]:
    """The loop as install.sh runs it (errexit, FAILS, the end of the install), with a docker shim whose
    ``compose run ... refdata load`` exits ``load_rc`` and whose other calls succeed."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    shim = bin_dir / "docker"
    shim.write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> "{tmp_path}/calls"\n'
        'case "$*" in *"tb_common.refdata load"*) '
        f"[ {load_rc} = 0 ] || {{ echo 'refdata: the pack does not verify' >&2; exit {load_rc}; }} ;; esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    pending = tmp_path / "deploy" / "refdata" / "pending"
    pending.mkdir(parents=True)
    (pending / f"{PACK}.tar").write_bytes(b"synthetic placeholder, not a pack\n")
    script = (
        "set -euo pipefail\n"
        f'ROOT="{tmp_path}"\nCOMPOSE=(docker compose --project-directory deploy)\nFAILS=()\n'
        + _block()
        + "\necho 'TrialBox is running.'\n"
        'if [ "${#FAILS[@]}" -gt 0 ]; then printf \'install: FAIL: %s\\n\' "${FAILS[@]}" >&2; exit 1; fi\n'
    )
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path)}
    return subprocess.run(["bash", "-c", script], env=env, cwd=tmp_path, capture_output=True, text=True, check=False)


def test_a_pack_that_does_not_load_is_a_fail_line_naming_it_and_the_retry(tmp_path: Path) -> None:
    r = _run(tmp_path, 1)
    assert r.returncode == 1, (r.stdout, r.stderr)  # the install ends with exit 1 (it printed exit 0 before)
    assert "TrialBox is running." in r.stdout  # the stack is left running, as for every FAIL line
    assert "refdata: the pack does not verify" in r.stderr  # the loader's own error is shown above the FAIL line
    fails = [ln for ln in r.stderr.splitlines() if ln.startswith("install: FAIL: ")]
    assert len(fails) == 1, r.stderr
    line = fails[0]
    assert f"{PACK}.tar" in line and "not loaded" in line  # what failed
    assert "deploy/refdata/pending" in line and "re-run deploy/install.sh" in line  # where it stays, how to retry
    assert "install: warning: reference data" not in r.stderr
    # the pack is kept for the retry, and the one-off loader's leftovers are swept as before
    assert (tmp_path / "deploy" / "refdata" / "pending" / f"{PACK}.tar").is_file()
    calls = (tmp_path / "calls").read_text(encoding="utf-8")
    assert "--name tb-refdata-sweep" in calls


def test_a_pack_that_loads_is_moved_to_loaded_and_nothing_fails(tmp_path: Path) -> None:
    r = _run(tmp_path, 0)
    assert r.returncode == 0 and "FAIL" not in r.stderr, r.stderr
    assert f"reference data loaded: {PACK}" in r.stdout
    assert (tmp_path / "deploy" / "refdata" / "loaded" / f"{PACK}.tar").is_file()
    assert not (tmp_path / "deploy" / "refdata" / "pending" / f"{PACK}.tar").exists()
