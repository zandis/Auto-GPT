"""Are the test ids of these files the same in two collections (D-1119)?

    python -m tools.collect_stable tests/unit/test_a.py tests/console/test_b.py ...   # from trialbox/

pytest collects the given test files twice, each time in a fresh process, and the ids are compared. An id that
carries the clock, random bytes or a dictionary order that changes between processes (a ``parametrize`` value
rendered into the id) differs between the two, and the shards of the full tier then disagree about what was
collected: ``tools.test_shard check`` fails after every shard has run, half an hour later. Here it fails in seconds,
naming the ids seen in one collection only.

The guard step of the `checks` job (.github/workflows/trialbox-ci.yml) runs it on a pull request over the test files
the pull request adds or changes. A path that is not an existing ``test_*.py`` file is left out (a deleted test, a
helper, a document); with none left there is nothing to compare, and it says so. Exit 0 when the two collections are
the same, 1 when an id differs, 2 when a collection fails (the error is printed).
"""

from __future__ import annotations

import subprocess
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path


def test_files(paths: Sequence[str]) -> list[str]:
    """The given paths that are existing test files, in their order, each once."""
    out: list[str] = []
    for p in paths:
        path = Path(p)
        if path.name.startswith("test_") and path.suffix == ".py" and path.is_file() and p not in out:
            out.append(p)
    return out


def collect(files: Sequence[str]) -> list[str]:
    """The test ids pytest collects from ``files`` in a fresh process; RuntimeError when the collection fails."""
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:randomly", "-p", "no:cacheprovider"]
    r = subprocess.run([*cmd, *files], capture_output=True, text=True, check=False)
    if r.returncode not in (0, 5):  # 5: nothing collected
        raise RuntimeError(f"pytest --collect-only exited {r.returncode}:\n{(r.stdout + r.stderr)[-3000:]}")
    return [ln.strip() for ln in r.stdout.splitlines() if "::" in ln and not ln[:1].isspace()]


def differences(first: Sequence[str], second: Sequence[str]) -> list[str]:
    """The ids in one collection and not the other (or a different number of times), sorted."""
    a, b = Counter(first), Counter(second)
    return sorted(set((a - b) | (b - a)))


def main(argv: Sequence[str] | None = None) -> int:
    files = test_files(list(sys.argv[1:] if argv is None else argv))
    if not files:
        print("collect_stable: no test file among the paths given: nothing to compare")
        return 0
    try:
        first, second = collect(files), collect(files)
    except RuntimeError as exc:
        print(f"collect_stable: {exc}", file=sys.stderr)
        return 2
    diff = differences(first, second)
    if diff:
        print(f"collect_stable: {len(diff)} test id(s) differ between two collections of the same files "
              "(an id that carries the clock or random bytes; name the parametrize cases with ids=):",
              file=sys.stderr)  # fmt: skip
        for test_id in diff:
            print(f"  {test_id}", file=sys.stderr)
        return 1
    print(f"collect_stable: {len(first)} test id(s) of {len(files)} file(s), the same in two collections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
