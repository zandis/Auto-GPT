"""The CI cards' check (card H-105): a CI job never shares a card with the walk or the bench.

The bench host's settings file names the CI cards (``BENCH_CI_GPUS``) and the cards CI must never touch
(``BENCH_RESERVED_GPUS``: card 1, the walk's, and the bench's own). Two checks use this module:

* on the host, before a GPU runner is registered (``launcher.py``): the CI set is not empty, shares no card with the
  reserved set, every CI card exists, and none is busy beyond the set's cap. The cards' UUIDs are written for the
  second check;
* in the job, as the runner's job-started hook (``gpu_check.py --in-job FILE``), because a registered runner can wait
  for its job: the same cards, by UUID (the container numbers its cards from 0), are still within the cap.

The CI cards are shared (the owner's ruling of 2026-11-24: every free card is used, several jobs at once), so a
process on a card does not stop a job by itself. A card is busy beyond its cap when it already holds more memory
than ``cap_mib`` or more load than ``cap_util`` (the host's settings file gives both), or when the tool cannot read
either (the check fails closed).
The query tool is the absolute path the settings file names, never one found on a caller's PATH.
Standard library only: the host's python3 and the job image's run it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

GPU_FIELDS = "index,uuid,memory.used,utilization.gpu"
QUERY_SECONDS = 60


@dataclass(frozen=True)
class Card:
    index: int
    uuid: str
    used_mib: int
    util_pct: int


def parse_ids(text: str) -> list[int]:
    """``"2,3"`` -> ``[2, 3]``; an empty text is an empty set; anything else is refused."""
    out: list[int] = []
    for part in (p.strip() for p in text.split(",")):
        if not part:
            continue
        if not part.isdigit():
            raise ValueError(f"a card is named by its index (a number), not {part!r}")
        out.append(int(part))
    return out


def _run(tool: str, args: Sequence[str]) -> str:
    if not Path(tool).is_absolute():
        raise RuntimeError(f"the card query tool must be an absolute path in the settings file, not {tool!r}")
    proc = subprocess.run([tool, *args], capture_output=True, text=True, timeout=QUERY_SECONDS, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"the card query tool failed (exit {proc.returncode}): {proc.stderr.strip()[-300:]}")
    return proc.stdout


def query(tool: str) -> list[Card]:
    """Every card the tool sees, with its memory in use and its load."""
    cards: list[Card] = []
    for line in _run(tool, [f"--query-gpu={GPU_FIELDS}", "--format=csv,noheader,nounits"]).splitlines():
        cols = [c.strip() for c in line.split(",")]
        if len(cols) != 4:
            continue
        idx, uuid, mem, util = cols
        cards.append(Card(int(idx), uuid, _num(mem), _num(util)))
    return cards


def _num(text: str) -> int:
    """A reading the tool cannot give (``[N/A]``) counts as busy: the check fails closed."""
    try:
        return int(float(text))
    except ValueError:
        return sys.maxsize


def set_problems(ci: Sequence[int], reserved: Sequence[int]) -> list[str]:
    """The CI set as the settings file gives it: not empty, and no card of the walk or the bench."""
    out = []
    if not ci:
        out.append("BENCH_CI_GPUS names no card: a GPU runner has no card of its own")
    shared = sorted(set(ci) & set(reserved))
    if shared:
        out.append(f"BENCH_CI_GPUS names card(s) {shared} that BENCH_RESERVED_GPUS keeps (the walk, the bench)")
    return out


def busy_problems(cards: Sequence[Card], cap_mib: int, cap_util: int) -> list[str]:
    out = []
    for c in cards:
        why = []
        if c.used_mib > cap_mib:
            why.append(f"{_reading(c.used_mib)} MiB in use (the cap is {cap_mib})")
        if c.util_pct > cap_util:
            why.append(f"{_reading(c.util_pct)}% load (the cap is {cap_util}%)")
        if why:
            out.append(f"CI card {c.index} is busy beyond its cap: {'; '.join(why)}")
    return out


def _reading(value: int) -> str:
    return "an unreadable" if value == sys.maxsize else str(value)


def host_check(
    tool: str, ci: Sequence[int], reserved: Sequence[int], cap_mib: int, cap_util: int
) -> tuple[list[str], list[str]]:
    """On the host: (problems, the CI cards' UUIDs). Any problem means: do not register a GPU runner."""
    problems = set_problems(ci, reserved)
    if problems:
        return problems, []
    cards = query(tool)
    by_index = {c.index: c for c in cards}
    missing = [i for i in ci if i not in by_index]
    if missing:
        return [f"CI card(s) {missing} not found by the card query tool (it sees {sorted(by_index)})"], []
    mine = [by_index[i] for i in ci]
    return busy_problems(mine, cap_mib, cap_util), [c.uuid for c in mine]


def job_check(tool: str, uuids: Sequence[str], cap_mib: int, cap_util: int) -> list[str]:
    """In the job: the cards the container was given are exactly the CI cards, by UUID, none beyond the cap."""
    if not uuids:
        return ["the job's card file names no card: a GPU job cannot start without its CI cards"]
    cards = query(tool)
    seen = {c.uuid for c in cards}
    out = []
    if seen != set(uuids):
        out.append(f"the container sees {len(seen)} card(s), not the {len(uuids)} CI card(s) it was given")
    return out + busy_problems([c for c in cards if c.uuid in uuids], cap_mib, cap_util)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--in-job", required=True, help="the card file the launcher wrote into the job's scratch folder")
    args = ap.parse_args(argv)
    try:
        spec = json.loads(Path(args.in_job).read_text(encoding="utf-8"))
        if spec.get("profile") != "gpu":
            return 0
        problems = job_check(spec["tool"], spec["uuids"], int(spec["cap_mib"]), int(spec["cap_util"]))
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        problems = [f"the CI cards could not be checked: {exc}"]
    for p in problems:
        print(f"bench CI: {p}", file=sys.stderr)
    if problems:
        print("bench CI: this job does not start: its CI cards are busy beyond their cap", file=sys.stderr)
        return 1
    print("bench CI: the CI cards are within their cap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
