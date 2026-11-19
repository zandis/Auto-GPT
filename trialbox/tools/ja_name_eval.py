"""Card 10C-1b: measure a Japanese morphological analyser's names inside the privacy guard (decision D-1235).

    python -m tools.ja_name_eval                                   # every analyser installed, a table on stdout
    python -m tools.ja_name_eval --analysers sudachi-core,mecab-ipadic --json out.json

SudachiPy with SudachiDict-small is in the lock and is the guard's default (D-1235); the other analysers are not
(installed by hand to compare). With none installed this prints that it skipped and exits 0. For each analyser
installed it reports, on three sets, the identifiers left with a character unmasked (by the note masker or the
guard) and the ordinary lines changed, for the rules alone, the rules plus the analyser's
names under the combination rule (``ja_names.name_spans``), and the rules plus the analyser's raw proposals (the
rule's steps 1 and 2 only); and the time to mask a 10 kB note (UTF-8 bytes), median of five runs, and the
analyser's load time.

The sets: the committed probe file ``eval/phi_synth/ja_guard_probes.json`` (``masked`` and the known-gap ``missed``
lines; ``unchanged`` and the known-gap ``overmasked`` lines; ``overmasked_before`` compared with its pinned outputs),
the card's own lines ``eval/phi_synth/ja_name_lines.json`` (75 unlabelled names, 75 tempting ordinary lines), and its
held-out set ``eval/phi_synth/ja_name_lines_holdout.json`` (30 and 30, written before the rule was tuned).
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import statistics
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from tb_common import ja_names, phi_guard
from tb_common.phi_guard import MASK_CHAR, mask_note

ROOT = Path(__file__).resolve().parents[1]
SYNTH = ROOT / "eval" / "phi_synth"
PACKAGES = {  # the import an analyser needs (checked without importing it)
    "sudachi-small": ("sudachipy", "sudachidict_small"),
    "sudachi-core": ("sudachipy", "sudachidict_core"),
    "sudachi-full": ("sudachipy", "sudachidict_full"),
    "mecab-unidic-lite": ("fugashi", "unidic_lite"),
    "mecab-ipadic": ("fugashi", "ipadic"),
    "janome": ("janome",),
}


def installed(choice: str) -> bool:
    return all(importlib.util.find_spec(m) is not None for m in PACKAGES[choice])


def sets() -> dict[str, Any]:
    probes = json.loads((SYNTH / "ja_guard_probes.json").read_text())
    lines = json.loads((SYNTH / "ja_name_lines.json").read_text())
    held = json.loads((SYNTH / "ja_name_lines_holdout.json").read_text())
    return {
        "probe_masked": [(p["text"], p["ids"]) for p in probes["masked"]],
        "probe_gaps": [(p["text"], p["ids"]) for p in probes["known_gaps"]["missed"]],
        "probe_unchanged": list(probes["unchanged"]),
        "probe_gap_overmasked": list(probes["known_gaps"]["overmasked"]),
        "probe_overmasked_before": [(x["text"], x["mask"]) for x in probes["overmasked_before"]["lines"]],
        "new_names": [(p["text"], p["ids"]) for p in lines["names"]],
        "new_ordinary": list(lines["ordinary"]),
        "held_names": [(p["text"], p["ids"]) for p in held["names"]],
        "held_ordinary": list(held["ordinary"]),
    }


def _guard() -> Any:
    from guard.guard import Guard

    return Guard(None)


def unmasked(text: str, ids: list[str], guard: Any) -> list[str]:
    """The identifiers of ``ids`` that the masker or the guard leaves a character of (``test_phi_guard_ja``'s test)."""
    masked = mask_note(text)
    spans = [(f.start, f.end) for f in guard.detect(text)]
    out = []
    for value in ids:
        i = text.index(value)
        if any(
            not text[j].isspace() and (masked[j] != MASK_CHAR or not any(s <= j < e for s, e in spans))
            for j in range(i, i + len(value))
        ):
            out.append(value)
    return out


def changed(text: str, guard: Any) -> bool:
    return mask_note(text) != text or guard.detect(text) != []


@contextlib.contextmanager
def recogniser(fn: Callable[[str], list[tuple[int, int]]] | None) -> Iterator[None]:
    """The guard with ``fn`` as its only name recogniser (``None``: the rules alone, without the default analyser)."""
    saved = list(phi_guard.NAME_RECOGNISERS)
    phi_guard.NAME_RECOGNISERS[:] = [] if fn is None else [fn]
    try:
        yield
    finally:
        phi_guard.NAME_RECOGNISERS[:] = saved


def note_10kb(data: dict[str, Any]) -> str:
    """A note of 10,000 UTF-8 bytes made of every line of the sets, in order, repeated."""
    lines = [t for k in ("probe_masked", "new_names") for t, _ in data[k]]
    lines += data["probe_unchanged"] + data["new_ordinary"]
    out, size, i = [], 0, 0
    while size < 10_000:
        line = lines[i % len(lines)]
        out.append(line)
        size += len(line.encode()) + 1
        i += 1
    return "\n".join(out).encode()[:10_000].decode(errors="ignore")


def measure(data: dict[str, Any], fn: Callable[[str], list[tuple[int, int]]] | None, guard: Any) -> dict[str, Any]:
    res: dict[str, Any] = {}
    with recogniser(fn):
        for key in ("probe_masked", "probe_gaps", "new_names", "held_names"):
            missed = [(t, v) for t, ids in data[key] for v in unmasked(t, ids, guard)]
            res[key] = {"ids": sum(len(ids) for _, ids in data[key]), "missed": len(missed), "which": missed}
        for key in ("probe_unchanged", "probe_gap_overmasked", "new_ordinary", "held_ordinary"):
            bad = [t for t in data[key] if changed(t, guard)]
            res[key] = {"lines": len(data[key]), "changed": len(bad), "which": [(t, mask_note(t)) for t in bad]}
        moved = [t for t, pinned in data["probe_overmasked_before"] if mask_note(t) != pinned]
        res["probe_overmasked_before"] = {"lines": len(data["probe_overmasked_before"]), "changed": len(moved)}
        note = note_10kb(data)
        runs = []
        for _ in range(5):
            start = time.perf_counter()
            mask_note(note)
            runs.append(time.perf_counter() - start)
        res["ms_per_10kb"] = round(statistics.median(runs) * 1000, 1)
    return res


def _spans_of(an: ja_names.Analyser, *, protect: bool) -> Callable[[str], list[tuple[int, int]]]:
    def spans(text: str) -> list[tuple[int, int]]:
        return ja_names.name_spans(text, an, protect=protect)

    return spans


def run(choices: list[str]) -> dict[str, Any]:
    data, guard = sets(), _guard()
    out: dict[str, Any] = {"rules": measure(data, None, guard)}
    if installed("sudachi-small"):  # the guard as it ships: phi_guard.japanese_names (D-1235)
        out["guard"] = measure(data, phi_guard.japanese_names, guard)
    for choice in choices:
        if not installed(choice):
            out[choice] = {"skipped": "not installed"}
            continue
        start = time.perf_counter()
        an = ja_names.analyser(choice)
        an.tokens("見本太郎は本日来院")  # the first call loads the dictionary
        load = round(time.perf_counter() - start, 2)
        out[choice] = measure(data, _spans_of(an, protect=True), guard)
        out[choice]["load_s"] = load
        out[choice + " raw"] = measure(data, _spans_of(an, protect=False), guard)
    return out


def table(res: dict[str, Any]) -> str:
    head = ("| configuration | probe ids missed | known-gap ids missed | new ids missed | held-out ids missed "
            "| probe ordinary changed | known-gap ordinary changed | new ordinary changed | held-out ordinary changed "
            "| ms per 10 kB |")  # fmt: skip
    rows = [head, "|" + " --- |" * 10]
    for name, r in res.items():
        if "skipped" in r:
            rows.append(f"| {name} | skipped: {r['skipped']} |" + " |" * 8)
            continue
        cells = [f"{r[k]['missed']} / {r[k]['ids']}" for k in ("probe_masked", "probe_gaps", "new_names", "held_names")]
        cells += [
            f"{r[k]['changed']} / {r[k]['lines']}"
            for k in ("probe_unchanged", "probe_gap_overmasked", "new_ordinary", "held_ordinary")
        ]
        rows.append(f"| {name} | " + " | ".join(cells) + f" | {r['ms_per_10kb']} |")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--analysers", default=",".join(ja_names.CHOICES))
    ap.add_argument("--json", type=Path, help="write the full result (every miss and change) here")
    args = ap.parse_args(argv)
    choices = [c for c in args.analysers.split(",") if c]
    unknown = [c for c in choices if c not in PACKAGES]
    if unknown:
        ap.error(f"unknown analyser(s) {unknown}; one of {list(PACKAGES)}")
    present = [c for c in choices if installed(c)]
    if not present:
        print("ja_name_eval: skipped: no analyser installed (see tb_common.ja_names)")
        return 0
    res = run(choices)
    print(table(res))
    if args.json:
        args.json.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
