"""Did a merge train already prove the tree of the commit just pushed to master? (CI-COST, D-578)

    python3 trialbox/tools/ci_proved_tree.py        # prints "true" or "false"; the reason goes to stderr

A train's pull request runs the full tier on its head. When the train is merged with a merge commit and master had
nothing the train lacked, the merge commit's tree is the train head's tree, byte for byte: the full tier of the push
to master would test the same files again. This says "true" only when all of these hold:

* the pushed commit has exactly two parents, and its tree equals the second parent's tree;
* the second parent is the head of a merged pull request whose branch is ``train/*``;
* every ``unit`` check run GitHub Actions recorded for that head passed.

Anything else says "false", and so does any error (no ``gh``, no answer, a shallow checkout): the full tier runs.
Standard library only: the ``changes`` job runs it before any environment exists. The nightly run keeps the whole
suite on master whatever this says.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

UNIT = "unit"  # the aggregate job of the unit shards: skipped shards are not a pass (D-564)
APP = "github-actions"
TRAIN_PREFIX = "train/"


def proved(
    head_tree: str, parents: list[str], train_tree: str, pulls: list[dict[str, Any]], runs: list[dict[str, Any]]
) -> tuple[bool, str]:
    """The rule on plain data: (proved, why)."""
    if len(parents) != 2:
        return False, f"not a merge of two ({len(parents)} parent(s))"
    if not head_tree or head_tree != train_tree:
        return False, "tree differs from the merged head's tree"
    train = parents[1]
    refs = [
        str((p.get("head") or {}).get("ref"))
        for p in pulls
        if p.get("merged_at")
        and str((p.get("head") or {}).get("ref", "")).startswith(TRAIN_PREFIX)
        and (p.get("head") or {}).get("sha") == train
    ]
    if not refs:
        return False, "no merged train pull request has this head"
    units = [r for r in runs if r.get("name") == UNIT and (r.get("app") or {}).get("slug") == APP]
    if not units:
        return False, "no unit check on the train's head"
    bad = sorted({str(r.get("conclusion")) for r in units if r.get("conclusion") != "success"})
    if bad:
        return False, f"unit was {', '.join(bad)} on the train's head"
    return True, f"proved by {refs[0]}"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def _api(path: str) -> Any:
    out = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def main() -> int:
    try:
        parents = _git("rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
        head_tree = _git("rev-parse", "HEAD^{tree}")
        if len(parents) != 2:
            ok, why = proved(head_tree, parents, "", [], [])
        else:
            train_tree = _git("rev-parse", f"{parents[1]}^{{tree}}")
            if head_tree != train_tree:
                ok, why = proved(head_tree, parents, train_tree, [], [])
            else:
                repo = os.environ["GITHUB_REPOSITORY"]
                pulls = _api(f"repos/{repo}/commits/{parents[1]}/pulls")
                checks = _api(f"repos/{repo}/commits/{parents[1]}/check-runs?check_name={UNIT}&per_page=100")
                ok, why = proved(head_tree, parents, train_tree, list(pulls), list(checks.get("check_runs") or []))
    except (OSError, KeyError, ValueError, AttributeError, TypeError, subprocess.CalledProcessError) as exc:
        ok, why = False, f"could not ask ({type(exc).__name__}); the full tier runs"
    print(f"ci_proved_tree: {why}", file=sys.stderr)
    print("true" if ok else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
