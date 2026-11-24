"""H-114c (the integrator's ruling 7129325585 on the review of #1461, 1461-1's remaining half): a SIGKILL inside the
host-tree switch itself, before any rollback ran. The switch's moves reached ``point.json`` only when the install
returned, so ``tools/apply_update.sh rollback`` read the record of before the switch: the copied files stayed set
aside in ``releases/.replaced-*`` while the box was said to be back on the previous release. Now the record is saved
before each move, and the put-back of a copied install also removes the links the switch made but never recorded.

Each case runs the real ``Updater``, ``apply_host``, ``restore_host`` and ``recover`` in child processes; the first
one SIGKILLs itself between two moves of the switch (no rollback runs), the second one recovers."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

KILL = r"""
import json, os, signal, sys
from pathlib import Path
from tools import host_tree as ht
from tools import update_status as us
from tools.trialbox import update as up

t, phase, case, after = Path(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4])
files = (*ht.REQUIRED, "deploy/install.sh", "libs/x.py", "tools/a.py", "tools/b.py", "tools/c.py")
src, base, stage = t / "src", t / "box", t / "stage"
bid = "B2" if case == "host-tree" else "B1"
kind = "copied" if case.startswith("copied") else case
updates = base / "deploy" / "updates"


def plan_of(b):
    compat = {"format": us.COMPAT_FORMAT, "bundle_id": b, "rows": [{}], "provides": {}}
    plan = up.Plan(b, "f" * 64, "vendor", [], stage, release_seq=3 if b == "B2" else 2, compat=compat,
                   trust_after={"format": us.TRUST_FORMAT, "keys": {"ed25519:" + "1" * 16: {}}})
    plan.trust_sha256 = us.file_sha256(updates / us.TRUST)  # as verify read it: the box's trust of now
    return plan


class Box:
    name = "stand-in"
    def running(self): return True
    def backup(self, plan, rb): return "nas"
    def snapshot(self, plan, rb, point): return None
    def apply(self, plan, rb, point): return list(up.apply_host(plan, base, rb, point))
    def restart(self, plan): return None
    def post_apply(self, plan): return []
    def check(self, plan): return "healthy"
    def audit(self, event, plan, detail): return None
    def rollback(self, plan, rb, point): up.restore_host(base, point)


if phase == "run":
    for n in files:
        for root, text in ((src, "new"), (base, "old")):
            (root / n).parent.mkdir(parents=True, exist_ok=True)
            (root / n).write_text(f"{text} {n}\n")
    if case == "copied-link":
        (src / "deploy" / "new.sh").write_text("new deploy/new.sh\n")
    if case == "host-tree":  # the box is on host tree B1 already; B2 adds two paths where the site keeps its own files
        (stage / "host").mkdir(parents=True)
        ht.pack(src, stage / "host" / ht.HOST_TAR)
        up.Updater(Box(), updates, say=lambda _m: None).run(plan_of("B1"))
        for n in ("deploy/extra.sh", "tools/site.py"):
            (src / n).write_text(f"new {n}\n")
            (base / n).write_text(f"site {n}\n")
        (stage / "host" / ht.HOST_TAR).unlink()
    (stage / "host").mkdir(parents=True, exist_ok=True)
    ht.pack(src, stage / "host" / ht.HOST_TAR)
    real, moves = ht._aside, []

    def aside(*a, **kw):  # the real step, whatever it takes, then the kill
        real(*a, **kw)
        moves.append(a[3])
        if len(moves) == after:  # a power cut, or the console limit's SIGKILL, between two moves of the switch
            os.kill(os.getpid(), signal.SIGKILL)

    ht._aside = aside
    if case == "copied-link":  # a path only the release has: linked with no move, killed right after (unrecorded)
        real_link = Path.symlink_to

        def link(self, target, *a, **kw):
            real_link(self, target, *a, **kw)
            if self.name == "new.sh" and "releases" not in self.parts:
                os.kill(os.getpid(), signal.SIGKILL)

        Path.symlink_to = link
        after = 10**6  # no kill at a move
    up.Updater(Box(), updates, say=lambda _m: None).run(plan_of(bid))
    print("NOT KILLED")
else:
    r = up.Updater(Box(), updates, say=lambda _m: None).recover(bid)
    want = {n: f"old {n}\n" for n in files} if kind == "copied" else {}
    if case == "host-tree":
        want = {"deploy/extra.sh": "site deploy/extra.sh\n", "tools/site.py": "site tools/site.py\n"}
    bad = [n for n, text in want.items() if (base / n).is_symlink() or not (base / n).is_file()
           or (base / n).read_text() != text]
    cur = os.path.normpath(base / "current")
    dangling = [str(p.relative_to(base)) for p in base.rglob("*") if p.is_symlink() and "releases" not in p.parts
                and os.path.normpath(os.path.join(p.parent, os.readlink(p))).startswith(cur + os.sep)]
    print(json.dumps({"ok": r["ok"], "not_back": bad, "links_left": dangling if kind == "copied" else [],
                      "current": os.readlink(base / "current") if (base / "current").is_symlink() else None,
                      "marker": us.marker(updates)}))
"""


def _run(script: Path, t: Path, phase: str, case: str, after: int) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    env.update(PYTHONPATH=f"{ROOT}:{ROOT / 'libs'}", TB_DOCKER="true")
    return subprocess.run([sys.executable, str(script), str(t), phase, case, str(after)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120, check=False)  # fmt: skip


@pytest.mark.parametrize(
    ("case", "after"), [("copied", 1), ("copied", 2), ("copied", 4), ("copied-link", 0), ("host-tree", 1)]
)
def test_a_sigkill_inside_the_switch_is_put_back_whole_by_the_next_rollback(tmp_path: Path, case: str,
                                                                            after: int) -> None:  # fmt: skip
    """THE INVARIANT of H-114c: whichever move the SIGKILL follows, ``recover`` puts every copied (or site) file back
    in its place, no link through ``current`` is left on a copied install, and a box on a host tree is on its
    previous release again."""
    import json

    script = tmp_path / "kill.py"
    script.write_text(KILL, encoding="utf-8")
    t = tmp_path / "t"
    first = _run(script, t, "run", case, after)
    assert first.returncode == -signal.SIGKILL, (first.returncode, first.stdout, first.stderr[-2000:])
    second = _run(script, t, "recover", case, after)
    assert second.returncode == 0, second.stderr[-2000:]
    out = json.loads(second.stdout.strip().splitlines()[-1])
    assert out["ok"] and out["marker"] is None, out
    assert out["not_back"] == [] and out["links_left"] == [], out
    assert out["current"] == ("releases/B1" if case == "host-tree" else None), out
