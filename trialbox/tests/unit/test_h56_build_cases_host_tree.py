"""H-56: the box-run rehearsal's build cases, refused at b06 on a CI runner (train 99, 2026-11-19).

`build`, `build-refused` and `build-preempt` stopped at b06-verify: tools/verify_update.py refused the bundle because
its host tree did not match its own HOST-SHA256SUMS. tools/host_tree.pack read each file twice (once to hash, once to
tar); the rehearsal packs the live checkout, and a file another test changed between the two reads gave a torn tree.
pack now reads each file once (hashed while copied into a snapshot, the tar written from the snapshot). Reproduced
before the fix by rewriting an untracked file under tools/ while the build case packed: "REJECTED: trialbox-host.tar:
host tree: tools/<file>: sha256 differs from HOST-SHA256SUMS". The ConnectionResetError in the same CI log came from
another test's in-process HTTP server; the build cases open no connection.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tools import host_tree

ROOT = Path(__file__).resolve().parents[2]
BOX_RUN = ROOT / "tests" / "rehearsal" / "box-run"
RUNNER = BOX_RUN / "rehearse-box-run.sh"


def _tree(root: Path) -> None:
    (root / "deploy").mkdir(parents=True)
    (root / "deploy" / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (root / "tools").mkdir()
    for i in range(40):
        (root / "tools" / f"t{i:02d}.py").write_bytes(os.urandom(4096))


def test_a_file_changing_while_the_tree_is_packed_never_tears_the_tree(tmp_path: Path) -> None:
    """Pack while another writer rewrites a file in the tree, many times: every tar passes check_tar."""
    src = tmp_path / "src"
    _tree(src)
    churn = src / "tools" / "zz_churn.txt"
    churn.write_bytes(b"0")
    stop = threading.Event()

    def writer() -> None:
        n = 0
        while not stop.is_set():
            n += 1
            churn.write_bytes(os.urandom(1 + (n * 7919) % 200_000))

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        for i in range(25):
            out = tmp_path / f"host-{i}.tar"
            host_tree.pack(src, out)
            sums = host_tree.check_tar(out)  # raises "sha256 differs" on a torn tree
            assert "tools/zz_churn.txt" in sums
            assert not out.with_name(out.name + ".snap").exists()  # the snapshot is gone after the pack
    finally:
        stop.set()
        t.join()


def test_pack_reads_each_file_of_the_tree_once() -> None:
    """Static: pack() opens the source files in one place only (the hash-and-copy loop), never again for the tar."""
    import inspect

    code = inspect.getsource(host_tree.pack)
    assert code.count("p.open(") == 1, code
    assert "(root / n).open" not in code and "p.stat()" not in code, code


def test_the_rehearsal_names_no_fixed_port() -> None:
    """The rehearsal's servers (the console stand-in, the VM's door) take a free port from the OS (free_port)."""
    text = RUNNER.read_text(encoding="utf-8")
    assert 's.bind(("127.0.0.1", 0))' in text
    assert not re.search(r"127\.0\.0\.1:\d{2,5}\b|--port[ =]\d|PORT=\d", text)


@pytest.mark.skipif(
    any(shutil.which(c) is None for c in ("bash", "curl", "openssl", "setsid", "tar", "git", "make")),
    reason="the box-run rehearsal needs bash, curl, openssl, setsid, tar, git and make",
)
def test_the_three_build_cases_pass_side_by_side(tmp_path: Path) -> None:
    """build, build-refused and build-preempt at the same time, each in its own folder (as xdist workers run them)."""
    cases = ["build", "build-refused", "build-preempt"]

    def run(case: str) -> tuple[str, int, str]:
        d = tmp_path / case
        d.mkdir()
        env = {**os.environ, "TB_BOXRUN_REHEARSAL_DIR": str(d)}
        r = subprocess.run([str(RUNNER), case], env=env, capture_output=True, text=True, check=False)
        return case, r.returncode, r.stdout + r.stderr

    with ThreadPoolExecutor(len(cases)) as ex:
        results = list(ex.map(run, cases))
    for case, rc, out in results:
        assert rc == 0, out
        assert f"check {case}: passed" in out and "  FAIL " not in out, out
