"""Did a merge train already prove the tree of the commit just pushed to master? (CI-COST, D-578)

    python3 trialbox/tools/ci_proved_tree.py        # prints "true" or "false"; the reason goes to stderr
    python3 trialbox/tools/ci_proved_tree.py --image-legs   # the image gates' question: also a passed image leg

A train's pull request runs the full tier on its head. When the train is merged with a merge commit and master had
nothing the train lacked, the merge commit's tree is the train head's tree, byte for byte: the full tier of the push
to master would test the same files again. This says "true" only when all of these hold:

* the pushed commit has exactly two parents, its tree equals the second parent's tree, and the first parent (master
  before the merge) is an ancestor of the second: the train's own run tested the train merged into that master;
* the second parent is the head of a merged pull request into master, from this repository, whose branch is
  ``train/*``;
* GitHub Actions recorded a run of every full-tier job (:data:`FULL_TIER`) on that head, and every one passed: a
  proved push skips all of them, so all of them must have been green.

Anything else says "false", and so does any error (no ``gh``, no answer, a shallow checkout): the full tier runs.
Standard library only: the ``changes`` job runs it before any environment exists.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

#: every job a proved push skips (the full tier of trialbox-ci.yml; tests/unit/test_ci_tiers.py holds the two equal)
FULL_TIER = ("unit-shard", "unit", "property", "goldens", "e2e-simple", "demo-boot", "security", "standards", "images")
APP = "github-actions"
TRAIN_PREFIX = "train/"
BASE = "master"
PAGE = 100
IMAGE_LEG = "images ("  # a leg of trialbox-images.yml; the CI gate's hadolint job is plain `images`
MAX_PAGES = 10  # 1,000 check runs on one commit: more than that and the answer is "false"


def _job(name: str) -> str:
    """``goldens (omop)`` -> ``goldens``: the leg of a matrix counts for its job."""
    return name.split(" (", 1)[0]


def proved(
    head_tree: str,
    parents: list[str],
    train_tree: str,
    master_in_train: bool,
    repo: str,
    pulls: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    image_legs: bool = False,
) -> tuple[bool, str]:
    """The rule on plain data: (proved, why).

    ``image_legs``: the image gates ask (trialbox-images.yml). The CI gate's hadolint job is also named ``images``, so
    the full-tier rule alone would be met on a train whose image gates never ran; the image gates also need at least
    one leg of their own (``images (<runner>, <platform>)``) on the train's head, every one passed (adversarial review
    of the deep review `architecture`)."""
    if len(parents) != 2:
        return False, f"not a merge of two ({len(parents)} parent(s))"
    if not head_tree or head_tree != train_tree:
        return False, "tree differs from the merged head's tree"
    if not master_in_train:
        # the train's run tested the train merged into master as it was then; equal trees after a revert on master
        # are a tree no run tested
        return False, "master had commits the train did not hold"
    train = parents[1]
    refs = []
    for p in pulls:
        head, base = p.get("head") or {}, p.get("base") or {}
        if (
            p.get("merged_at")
            and str(head.get("ref", "")).startswith(TRAIN_PREFIX)
            and head.get("sha") == train
            and base.get("ref") == BASE
            and (head.get("repo") or {}).get("full_name") == repo
        ):
            refs.append(str(head.get("ref")))
    if not refs:
        return False, "no merged train pull request into master has this head"
    ours = [r for r in runs if (r.get("app") or {}).get("slug") == APP]
    for job in ("unit", *[j for j in FULL_TIER if j != "unit"]):
        of_job = [r for r in ours if _job(str(r.get("name", ""))) == job]
        if job == "unit":
            of_job = [r for r in of_job if r.get("name") == "unit"]  # the aggregate itself, not a shard
        if not of_job:
            return False, f"no {job} check on the train's head"
        bad = sorted({str(r.get("conclusion")) for r in of_job if r.get("conclusion") != "success"})
        if bad:
            return False, f"{job} was {', '.join(bad)} on the train's head"
    if image_legs and not any(str(r.get("name", "")).startswith(IMAGE_LEG) for r in ours):
        return False, "no image-gate leg ran on the train's head"
    return True, f"proved by {refs[0]}"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def _api(path: str) -> Any:
    out = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def _check_runs(repo: str, sha: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        got = list(_api(f"repos/{repo}/commits/{sha}/check-runs?per_page={PAGE}&page={page}").get("check_runs") or [])
        out += got
        if len(got) < PAGE:
            return out
    raise ValueError("too many check runs")


def main(argv: list[str] | None = None) -> int:
    legs = "--image-legs" in (sys.argv[1:] if argv is None else argv)
    try:
        parents = _git("rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
        head_tree = _git("rev-parse", "HEAD^{tree}")
        repo = os.environ["GITHUB_REPOSITORY"]
        if len(parents) != 2:
            ok, why = proved(head_tree, parents, "", False, repo, [], [])
        else:
            train_tree = _git("rev-parse", f"{parents[1]}^{{tree}}")
            inside = subprocess.run(["git", "merge-base", "--is-ancestor", parents[0], parents[1]], check=False)
            if head_tree != train_tree or inside.returncode != 0:
                ok, why = proved(head_tree, parents, train_tree, inside.returncode == 0, repo, [], [])
            else:
                pulls = list(_api(f"repos/{repo}/commits/{parents[1]}/pulls"))
                runs = _check_runs(repo, parents[1])
                ok, why = proved(head_tree, parents, train_tree, True, repo, pulls, runs, image_legs=legs)
    except (OSError, KeyError, ValueError, AttributeError, TypeError, subprocess.CalledProcessError) as exc:
        ok, why = False, f"could not ask ({type(exc).__name__}); the full tier runs"
    print(f"ci_proved_tree: {why}", file=sys.stderr)
    print("true" if ok else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
