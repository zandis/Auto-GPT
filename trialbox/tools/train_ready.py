"""TRAIN-READY (process review 2026-11-13): check a card's branch before its lane writes ``train-ready: #<n> <sha>``.

The integrator merges a lane's head into ``train/<n>`` and the full tier runs once on the train. A head that breaks a
standing rule costs a train rebuild or a relay round through the owner. This tool checks, on the branch you are on:

* the working tree has no uncommitted change, and HEAD is what the branch's upstream holds (pushed, nothing after);
* every commit since ``origin/master`` ends with exactly the two lines ``Co-Authored-By: Claude
  <noreply@anthropic.com>`` and ``Claude-Session: <session URL>``, and names no model;
* no commit merges ``origin/master`` into the branch (the push rule; a merge of a train's tip is allowed);
* ``python -m tools.prepush`` ran complete on this HEAD with every step passed (skips are listed).

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
SESSION = re.compile(r"^Claude-Session: https://\S+$")
#: model family names and model ids; the owner's rule: none in a commit, a pull request title or body
MODEL_NAME = re.compile(r"\b(opus|sonnet|haiku|fable)\b|\bclaude-[a-z0-9.-]*\d", re.IGNORECASE)


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False).stdout.strip()


def message_problems(message: str) -> list[str]:
    """What is wrong with one commit message under the owner's rules (an empty list when nothing)."""
    lines = [ln.rstrip() for ln in message.strip().splitlines()]
    problems = []
    if len(lines) < 2 or lines[-2] != CO_AUTHOR or not SESSION.match(lines[-1]):
        problems.append(f"does not end with the two lines `{CO_AUTHOR}` and `Claude-Session: <session URL>`")
    names = sorted({m.group(0) for m in MODEL_NAME.finditer(message)})
    if names:
        problems.append(f"names a model: {', '.join(names)}")
    return problems


def check(base: str = "origin/master", cwd: Path = ROOT, prepush_dir: Path | None = None) -> tuple[str, list[str]]:
    """HEAD's sha and the list of problems that stop a train-ready line."""
    head = git("rev-parse", "HEAD", cwd=cwd)
    problems: list[str] = []
    if git("status", "--porcelain", "--untracked-files=no", cwd=cwd):
        problems.append("the working tree has uncommitted changes")
    upstream = git("rev-parse", "--verify", "-q", "@{upstream}", cwd=cwd)
    if not upstream:
        problems.append("the branch has no upstream: push it first")
    elif upstream != head:
        problems.append(f"HEAD {head[:8]} is not what the upstream holds ({upstream[:8]})")
    for sha in git("rev-list", f"{base}..HEAD", cwd=cwd).split():
        for p in message_problems(git("log", "-1", "--format=%B", sha, cwd=cwd)):
            problems.append(f"commit {sha[:8]} {p}")
        merged_in = git("rev-list", "--parents", "-n", "1", sha, cwd=cwd).split()[2:]  # a merge's other parents
        for p in merged_in:
            if subprocess.run(["git", "merge-base", "--is-ancestor", p, base], cwd=cwd, check=False).returncode == 0:
                problems.append(f"commit {sha[:8]} merges {base} into the branch (the push rule)")
    summary = (prepush_dir or cwd / ".cache" / "prepush" / head) / "summary.json"
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
        if skipped:
            print(f"train-ready: note: not run here (CI runs them): {', '.join(skipped)}", file=sys.stderr)
    return head, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.train_ready", description=__doc__.split("\n\n")[0])
    ap.add_argument("--pr", type=int, required=True, help="the card's pull request number")
    ap.add_argument("--base", default="origin/master")
    args = ap.parse_args(argv)
    head, problems = check(args.base)
    if problems:
        print("not train-ready:", *(f"  - {p}" for p in problems), sep="\n")
        return 1
    print(f"train-ready: #{args.pr} {head}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
