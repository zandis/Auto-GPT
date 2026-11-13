"""TRAIN-READY (process review 2026-11-13): check a card's branch before its lane writes ``train-ready: #<n> <sha>``.

The integrator merges a lane's head into ``train/<n>`` and the full tier runs once on the train. A head that breaks a
standing rule costs a train rebuild or a relay round through the owner. This tool checks, on the branch you are on:

* the working tree has no uncommitted or untracked file, and HEAD is what ``origin/<branch>`` holds (pushed);
* every commit of the lane since ``origin/master`` (commits that a ``train/*`` branch already holds are the
  integrator's) ends with exactly the two lines ``Co-Authored-By: Claude <noreply@anthropic.com>`` and
  ``Claude-Session: https://claude.ai/code/session_...``, and names no model;
* no commit of the lane merges ``origin/master`` into the branch, whichever parent it is (the push rule; a merge of
  a train's tip is allowed);
* ``python -m tools.prepush`` ran complete on this HEAD with no step failed, and with ``--tests`` when a Python file
  changed. A step skipped because this machine lacks its tool is printed on the train-ready line, for the integrator.

    python -m tools.train_ready --pr 512          # prints the train-ready line, or what is wrong; exit 1 if wrong
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CO_AUTHOR = "Co-Authored-By: Claude <noreply@anthropic.com>"
SESSION = re.compile(r"^Claude-Session: https://claude\.ai/code/session_[A-Za-z0-9]+$")
#: model family names as names (capitalised: a file called fable-review-... is not a model name) and model ids;
#: the owner's rule: none in a commit, a pull request title or body
MODEL_NAME = re.compile(r"\b(Opus|Sonnet|Haiku|Fable)\b")
MODEL_ID = re.compile(r"\bclaude-[a-z]+-\d", re.IGNORECASE)


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False).stdout.strip()


def message_problems(message: str) -> list[str]:
    """What is wrong with one commit message under the owner's rules (an empty list when nothing)."""
    lines = message.rstrip("\n").splitlines()
    problems = []
    if len(lines) < 2 or lines[-2] != CO_AUTHOR or not SESSION.match(lines[-1]):
        problems.append(f"does not end with the two lines `{CO_AUTHOR}` and `Claude-Session: <session URL>`")
    names = sorted({m.group(0) for r in (MODEL_NAME, MODEL_ID) for m in r.finditer(message)})
    if names:
        problems.append(f"names a model: {', '.join(names)}")
    return problems


def lane_commits(base: str, cwd: Path) -> list[str]:
    """The commits of ``base..HEAD`` that no ``train/*`` branch holds: the lane's own."""
    trains = git("for-each-ref", "--format=%(objectname)", "refs/remotes/origin/train/", cwd=cwd).split()
    return git("rev-list", f"{base}..HEAD", *(["--not", *trains] if trains else []), cwd=cwd).split()


def check(
    base: str = "origin/master", cwd: Path = ROOT, prepush_dir: Path | None = None
) -> tuple[str, list[str], list[str]]:
    """HEAD's sha, the problems that stop a train-ready line, and the steps skipped on this machine."""
    head = git("rev-parse", "HEAD", cwd=cwd)
    problems: list[str] = []
    if git("status", "--porcelain", cwd=cwd):
        problems.append("the working tree has uncommitted or untracked files (git status)")
    branch = git("branch", "--show-current", cwd=cwd)
    pushed = git("rev-parse", "--verify", "-q", f"origin/{branch}", cwd=cwd) if branch else ""
    if not pushed:
        problems.append(f"origin/{branch or '<detached HEAD>'} does not exist: push the branch first")
    elif pushed != head:
        problems.append(f"HEAD {head[:8]} is not what origin/{branch} holds ({pushed[:8]})")
    for sha in lane_commits(base, cwd):
        for p in message_problems(git("log", "-1", "--format=%B", sha, cwd=cwd)):
            problems.append(f"commit {sha[:8]} {p}")
        parents = git("rev-list", "--parents", "-n", "1", sha, cwd=cwd).split()[1:]
        for p in parents if len(parents) > 1 else []:
            if subprocess.run(["git", "merge-base", "--is-ancestor", p, base], cwd=cwd, check=False).returncode == 0:
                problems.append(f"commit {sha[:8]} merges {base} into the branch (the push rule)")
    summary = (prepush_dir or cwd / ".cache" / "prepush" / head) / "summary.json"
    skipped: list[str] = []
    if not summary.is_file():
        problems.append(f"no prepush run on this HEAD: run python -m tools.prepush ({summary} is missing)")
    else:
        s = json.loads(summary.read_text(encoding="utf-8"))
        bad = {k: v for k, v in s["results"].items() if v != "passed"}
        if s.get("dirty"):
            problems.append("the prepush run was on a tree with uncommitted changes")
        if not s.get("complete"):
            problems.append("the prepush run was partial (--only or --quick)")
        problems += [f"prepush {k}: {v}" for k, v in bad.items() if not v.startswith("skipped")]
        skipped = [k for k, v in bad.items() if v.startswith("skipped")]
        changed_py = [f for f in git("diff", "--name-only", f"{base}...HEAD", cwd=cwd).split() if f.endswith(".py")]
        if changed_py and not s.get("tests"):
            problems.append("the prepush run had no --tests, and the branch changes Python files")
    return head, problems, skipped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.train_ready", description=__doc__.split("\n\n")[0])
    ap.add_argument("--pr", type=int, required=True, help="the card's pull request number")
    ap.add_argument("--base", default="origin/master")
    args = ap.parse_args(argv)
    head, problems, skipped = check(args.base)
    if problems:
        print("not train-ready:", *(f"  - {p}" for p in problems), sep="\n")
        return 1
    note = f" (not run on this machine, CI runs them: {', '.join(skipped)})" if skipped else ""
    print(f"train-ready: #{args.pr} {head}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
