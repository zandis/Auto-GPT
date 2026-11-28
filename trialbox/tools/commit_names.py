"""No commit message on a pull request into ``int/*`` names a model (the owner's rule of 2026-11-28).

A message fails when any line names one of :data:`MODEL`'s words (case-insensitive, as the integrator's pre-push
grep), or when a trailer (``git interpret-trailers --parse``) carries a version (``5.5``, ``Claude 5``). The trailer
the repository asks for is ``Co-Authored-By: Claude <noreply@anthropic.com>`` plus a ``Claude-Session:`` line.
Standard library only: the workflow ``trialbox-commit-names.yml`` runs it with the runner's python3.

    python3 -m tools.commit_names <base>..<head>     # exit 1 when a commit of the range fails
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

MODEL = re.compile(r"opus|sonnet|fable|haiku|gpt|codex", re.IGNORECASE)
VERSION = re.compile(r"\d+\.\d+|claude[\s_-]*\d", re.IGNORECASE)


def _trailers(message: str) -> list[str]:
    out = subprocess.run(["git", "interpret-trailers", "--parse"], input=message, capture_output=True, text=True,
                         check=True).stdout  # fmt: skip
    return out.splitlines()


def problems(message: str) -> list[str]:
    """What is wrong with one commit message (empty when nothing is): the kind and where, never the text (the log of
    a run shows only these)."""
    found = [f"names a model (line {n})" for n, line in enumerate(message.splitlines(), 1) if MODEL.search(line)]
    return found + [f"a version in a trailer (trailer {n})" for n, t in enumerate(_trailers(message), 1)
                    if VERSION.search(t)]  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("range", help="<base>..<head>: the pull request's own commits")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args(argv)
    git = ["git", "-C", a.repo]
    shas = subprocess.run([*git, "rev-list", a.range], capture_output=True, text=True, check=True).stdout.split()
    bad = 0
    for sha in shas:
        message = subprocess.run([*git, "log", "-1", "--format=%B", sha], capture_output=True, text=True,
                                 check=True).stdout  # fmt: skip
        for p in problems(message):
            print(f"{sha[:12]}: {p}", file=sys.stderr)
            bad += 1
    print(f"commit names: {len(shas)} commit(s) read, {bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
