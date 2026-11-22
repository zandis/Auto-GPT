"""Gate 2's planted mistakes (review 2026-11-22 §3.5 step 5, §5.3): the acceptance of the cross-path test itself.

Each mutation is applied, one at a time, to a scratch copy of ``trialbox/`` (never to this tree), and the cross-path
test (``tests/unit/test_gate2_cross_path.py``) is run on the copy. A mutation is **caught** when the run has a
finding the unmutated run does not have (the unmutated run may itself be red: a road that is already red must not
make a mutation on it look caught, so the comparison is finding by finding, per test id).

    python -m tools.gate2_planted --work <scratch dir> [--only a,b] [-n 3] [--out results.json]

Prints one line per mutation: ``<id> <what> -> red|green`` and, when red, the new findings' invariant, person and
road. Writes the whole result as JSON with ``--out``. Exit 0 when every mutation is caught, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST = "tests/unit/test_gate2_cross_path.py"
IGNORE = shutil.ignore_patterns(
    ".venv", ".cache", "node_modules", "__pycache__", ".pytest_cache", "*.pyc", ".mypy_cache", ".ruff_cache"
)


@dataclass(frozen=True)
class Mutation:
    id: str
    what: str
    edits: tuple[tuple[str, str, str], ...]  # (file, old text, new text); old must occur exactly once
    new_files: tuple[tuple[str, str], ...] = ()


#: where a resource's own key is made (``Mapper._row_identity``): a planted line goes just before the gate's call
_OWN_KEY = "        if self._patient_owned(rs):\n            return self._resolve(rs, row, rs.type, col, rs.table,"
_BYPASS = '''"""A visit key made on its own (a planted mistake of tools/gate2_planted.py)."""


def visit_key(rtype: str, number: str) -> str:
    return f"{rtype}-{number}"
'''

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "a",
        "the source namespace dropped from the record key in resolve_record",
        (
            (
                "libs/tb_common/identity.py",
                '["record", rule_version, namespace, table, resource_type, owner, parts, occurrence]',
                '["record", rule_version, table, resource_type, owner, parts, occurrence]',
            ),
        ),
    ),
    Mutation(
        "b",
        "the national-identifier conflict check removed",
        (("libs/tb_common/identity.py", '        state.check_detail(site_key, owner, "national", national_id)\n', ""),),
    ),
    Mutation(
        "c",
        "the birth-date conflict check removed (resolve_record's and the mapper's call of it)",
        (
            ("libs/tb_common/identity.py", '        state.check_detail(site_key, owner, "birth", birth_date)\n', ""),
            (
                "services/adapter/mapping/engine.py",
                '            self._identity.check_detail(self.key, identity.owner, "birth", str(res["birthDate"]))\n',
                "            pass\n",
            ),
        ),
    ),
    Mutation(
        "d",
        "a visit key built with an f-string in a new file, bypassing resolve_record (the mapped feeds' visits and "
        "their references)",
        (
            (
                "services/adapter/mapping/engine.py",
                _OWN_KEY,
                '        if rs.type == "Encounter":\n'
                "            from adapter.mapping.g2_planted_keys import visit_key\n\n"
                "            return visit_key(rs.type, str(row[col]))\n" + _OWN_KEY,
            ),
            (
                "services/adapter/mapping/engine.py",
                "        targets = self._targets.get(rtype, [])\n        target: ResourceSpec | None\n",
                '        if rtype == "Encounter":\n'
                "            from adapter.mapping.g2_planted_keys import visit_key\n\n"
                "            return visit_key(rtype, str(row[col]))\n"
                "        targets = self._targets.get(rtype, [])\n        target: ResourceSpec | None\n",
            ),
        ),
        (("services/adapter/mapping/g2_planted_keys.py", _BYPASS),),
    ),
    Mutation(
        "e",
        "a lab key made by hashing the bare record id, no owner or namespace (the mapped feeds' labs)",
        (
            (
                "services/adapter/mapping/engine.py",
                _OWN_KEY,
                '        if rs.type == "Observation":\n'
                "            return resource_id(self.key, rs.type, str(row[col]))\n" + _OWN_KEY,
            ),
        ),
    ),
    Mutation(
        "f",
        "chart normalisation skipped on the bulk import road (its patient ids hashed as written)",
        (
            (
                "services/adapter/pipeline.py",
                '    return pid_for_mrn(key, rid) if rtype == "Patient" else resource_id(key, rtype, rid)',
                '    raw = __import__("hmac").new(key, rid.encode(), "sha256").hexdigest()[:32]\n'
                '    return raw if rtype == "Patient" else resource_id(key, rtype, rid)',
            ),
        ),
    ),
    Mutation(
        "g",
        "the correction's previous key ignored in resolve_record",
        (
            ("libs/tb_common/identity.py", "        owners.add(previous.owner)\n", "        pass\n"),
            (
                "libs/tb_common/identity.py",
                "    return ResolvedRecord(owner, key, previous.record_key if previous else None,",
                "    return ResolvedRecord(owner, key, None,",
            ),
        ),
    ),
    Mutation(
        "h",
        "the opt-out lookup skips the alias path (merged charts not followed)",
        (
            (
                "libs/tb_common/optout.py",
                "    if not pids:\n        return pids\n    schema = db.schema",
                "    if pids or not pids:\n        return pids\n    schema = db.schema",
            ),
        ),
    ),
)

_CASE = re.compile(r"^E\s+AssertionError: (\S+) / (\S+) / (\S+): \d+ findings")
_FINDING = re.compile(r"^E {9}([a-z-]+) store=(\S+) person=(\S+): (.*)$")
_FAILED = re.compile(r"^(FAILED|ERROR) (\S+)")


@dataclass
class Run:
    rc: int
    seconds: float
    failed: set[str] = field(default_factory=set)
    findings: set[tuple[str, str, str, str]] = field(default_factory=set)  # (case, invariant, person, store)


def parse(text: str) -> Run:
    run = Run(rc=0, seconds=0.0)
    case = ""
    for line in text.splitlines():
        if m := _CASE.match(line):
            case = f"{m[1]}-{m[2]}-{m[3]}"
        elif (m := _FINDING.match(line)) and case:
            run.findings.add((case, m[1], m[3], m[2]))
        elif m := _FAILED.match(line):
            run.failed.add(m[2])
    return run


def copy_tree(dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ROOT, dest, ignore=IGNORE, symlinks=True)


def apply(tree: Path, m: Mutation) -> None:
    for rel, old, new in m.edits:
        path = tree / rel
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            raise SystemExit(f"mutation {m.id}: the text to change occurs {text.count(old)} times in {rel}")
        path.write_text(text.replace(old, new), encoding="utf-8")
    for rel, body in m.new_files:
        (tree / rel).write_text(body, encoding="utf-8")


def restore(tree: Path, m: Mutation) -> None:
    for rel, _, _ in m.edits:
        shutil.copyfile(ROOT / rel, tree / rel)
    for rel, _ in m.new_files:
        (tree / rel).unlink(missing_ok=True)


def run_test(tree: Path, log: Path, workers: int, basetemp: Path) -> Run:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(tree / p) for p in ("libs", "services", "."))}
    # the copy, never this tree: the venv's editable install would otherwise answer the imports
    probe = subprocess.run(
        [sys.executable, "-c", "import adapter, tb_common; print(adapter.__file__, tb_common.__file__)"],
        cwd=tree,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0 or str(tree) not in probe.stdout:
        raise SystemExit(f"the copy's modules are not the ones imported: {probe.stdout.strip()} {probe.stderr[-300:]}")
    t0 = time.monotonic()
    with log.open("w", encoding="utf-8") as fh:
        rc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-n", str(workers), "--basetemp", str(basetemp), TEST],
            cwd=tree,
            env=env,
            check=False,
            stdout=fh,
            stderr=subprocess.STDOUT,
        ).returncode
    run = parse(log.read_text(encoding="utf-8", errors="replace"))
    run.rc, run.seconds = rc, round(time.monotonic() - t0, 1)
    return run


def describe(new: set[tuple[str, str, str, str]]) -> str:
    by: dict[tuple[str, str], set[str]] = {}
    for case, inv, person, _store in new:
        by.setdefault((inv, person), set()).add(
            case.split("-")[0] if not case.startswith("fhir_bulk") else "_".join(case.split("-")[0].split("_")[:3])
        )
    return "; ".join(f"{inv}[{p}] on {','.join(sorted(roads))}" for (inv, p), roads in sorted(by.items()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--work", type=Path, required=True, help="a scratch folder (the copy and the logs go there)")
    ap.add_argument("--only", default="", help="mutation ids, comma separated (default: all)")
    ap.add_argument("-n", type=int, default=3, help="pytest workers (default 3)")
    ap.add_argument("--out", type=Path, help="write the results as JSON here")
    args = ap.parse_args(argv)
    only = {x for x in args.only.split(",") if x}
    todo = [m for m in MUTATIONS if not only or m.id in only]
    tree = args.work / "trialbox"
    copy_tree(tree)
    base = run_test(tree, args.work / "baseline.log", args.n, args.work / "pytest-baseline")
    print(
        f"baseline: rc {base.rc}, {len(base.failed)} failing cases, {len(base.findings)} findings, {base.seconds} s",
        flush=True,
    )
    results = []
    for m in todo:
        apply(tree, m)
        try:
            got = run_test(tree, args.work / f"mutation-{m.id}.log", args.n, args.work / f"pytest-{m.id}")
        finally:
            restore(tree, m)
        new = got.findings - base.findings
        newly_failed = got.failed - base.failed
        red = bool(new or newly_failed)
        line = f"{m.id} {m.what} -> {'red' if red else 'green'}"
        if new:
            line += f": {describe(new)}"
        elif newly_failed:
            line += f": newly failing {sorted(newly_failed)[:3]}"
        print(line, flush=True)
        results.append(
            {
                "id": m.id,
                "what": m.what,
                "red": red,
                "new_findings": sorted(map(list, new)),
                "newly_failed": sorted(newly_failed),
                "seconds": got.seconds,
            }
        )
    if args.out:
        args.out.write_text(
            json.dumps(
                {
                    "baseline": {
                        "failed": sorted(base.failed),
                        "findings": len(base.findings),
                        "seconds": base.seconds,
                    },
                    "mutations": results,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return 0 if all(r["red"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
