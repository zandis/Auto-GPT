"""H-142 (.k): the files that keep what must not be lost are written whole beside themselves and renamed, never
rewritten in place. ``deploy/site/backup-audit-pending.jsonl`` holds the audit events the orchestrator could not take
(a restore's, a backup's): rewritten in place, a kill mid-write (or a full disk) emptied it and every kept event was
lost. The rehearsal's ``deploy/.env`` put-back is the same form (Low)."""

from __future__ import annotations

import json
import os
import random
import re
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEPT = 20000  # events the orchestrator could not take: a few MB, so a kill lands in the rewrite

#: ComposeOps.audit with the orchestrator down, over and over: each run reads the kept events, adds its own and
#: writes them back. ``limit``: the largest file this process may write (a full disk), 0 for none
CHILD = textwrap.dedent(
    """
    import os, resource, sys
    from pathlib import Path
    root, deploy, ready, limit, once = sys.argv[1], Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]), sys.argv[5] == "1"
    sys.path[:0] = [root, os.path.join(root, "libs"), os.path.join(root, "services")]
    from tools.trialbox import backup_schedule as bs

    class Down:
        def _c(self, *args):
            return list(args)

        def run(self, argv, **kw):
            raise RuntimeError("synthetic: the orchestrator is down")

    ops = bs.ComposeOps.__new__(bs.ComposeOps)
    ops.deploy, ops.box = deploy, Down()
    if limit:
        resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
    open(ready, "w").write("ready")
    n = 0
    while True:
        ops.audit("backup.synthetic", {"n": n})
        n += 1
        if once:
            break
    """
)


def _box(tmp_path: Path) -> tuple[Path, Path, list[str]]:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    pending = deploy / "site" / "backup-audit-pending.jsonl"
    kept = [json.dumps({"event": "backup.restore_failed", "sha": "", "detail": {"kept": i, "pad": "x" * 200}})
            for i in range(KEPT)]  # fmt: skip
    pending.write_text("".join(x + "\n" for x in kept), encoding="utf-8")
    return deploy, pending, kept


def _start(tmp_path: Path, deploy: Path, limit: int = 0, once: bool = False) -> tuple[subprocess.Popen[str], Path]:
    child, ready = tmp_path / "child.py", tmp_path / "ready"
    child.write_text(CHILD, encoding="utf-8")
    ready.unlink(missing_ok=True)
    argv = [sys.executable, str(child), str(ROOT), str(deploy), str(ready), str(limit), "1" if once else "0"]
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    return subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True), ready


def _all_kept(pending: Path, kept: list[str]) -> None:
    lines = pending.read_text(encoding="utf-8").splitlines()
    assert lines[: len(kept)] == kept, f"{len(lines)} lines, the kept events lost or cut"
    for ln in lines:
        json.loads(ln)  # every line whole


def test_a_kill_9_while_the_kept_events_are_rewritten_loses_none(tmp_path: Path) -> None:
    """kill -9 at swept moments of a run that rewrites the kept events: after each, every one is still there and
    every line whole. Before: the file was emptied by the rewrite (all kept events lost)."""
    deploy, pending, kept = _box(tmp_path)
    rng = random.Random(142)
    for _ in range(8):
        p, ready = _start(tmp_path, deploy)
        t = time.monotonic()
        while not ready.exists() and p.poll() is None and time.monotonic() - t < 30:
            time.sleep(0.005)
        time.sleep(rng.uniform(0.02, 0.4))
        p.send_signal(signal.SIGKILL)
        p.wait(timeout=30)
        _all_kept(pending, kept)


def _function(script: str, name: str) -> str:
    """One shell function of the rehearsal's box.sh, as written there."""
    m = re.search(rf"^(?P<ind> *){name}\(\) \{{\n.*?^(?P=ind)\}}\n", script, re.S | re.M)
    assert m, name
    return textwrap.dedent(m.group(0))


BOX_SH = (ROOT / "tools" / "rehearse_box" / "box.sh").read_text(encoding="utf-8")


def test_the_rehearsals_env_put_back_never_cuts_deploy_env(tmp_path: Path) -> None:
    """box.sh's live-restore put-back wrote deploy/.env in place (``cat > deploy/.env``): a write that fails part-way
    (a full disk: here ``ulimit -f``) left it cut. It is a copy renamed over it now: the file is whole, old or new."""
    box = tmp_path / "box"
    (box / "deploy" / "site").mkdir(parents=True)
    rr = tmp_path / "rr"
    rr.mkdir()
    env = "".join(f"TB_SYNTHETIC_{i}={'v' * 60}\n" for i in range(100))  # about 8 KB
    (rr / "env.before").write_text(env, encoding="utf-8")
    now = "TB_SYNTHETIC_NOW=1\n" * 10
    (box / "deploy" / ".env").write_text(now, encoding="utf-8")
    script = f'BOX="{box}"; rr="{rr}"\n{_function(BOX_SH, "put_back")}\nulimit -f 4\nput_back\n'
    subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, check=False)
    assert (box / "deploy" / ".env").read_text(encoding="utf-8") in (env, now)


def test_the_rehearsals_envset_keeps_the_files_mode_and_its_other_lines(tmp_path: Path) -> None:
    box = tmp_path / "box"
    (box / "deploy").mkdir(parents=True)
    f = box / "deploy" / ".env"
    f.write_text("TB_A=1\nTB_B=2\n", encoding="utf-8")
    f.chmod(0o640)
    script = f'BOX="{box}"\n{_function(BOX_SH, "envset")}\nenvset TB_A 3 && envset TB_B && envset TB_C "a b"\n'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stderr
    assert f.read_text(encoding="utf-8") == "TB_A=3\nTB_C=a b\n" and f.stat().st_mode & 0o777 == 0o640
    assert sorted(p.name for p in f.parent.iterdir()) == [".env"]  # no temp file left
