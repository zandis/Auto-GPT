"""Gate 2's planted mistakes (review 2026-11-22 §3.5 step 5, §5.3): the acceptance of the cross-path test itself.

Each mutation is applied, one at a time, to a scratch copy of ``trialbox/`` (never to this tree), and the cross-path
test (``tests/unit/test_gate2_cross_path.py``) is run on the copy. A mutation is **caught** when the run has a
finding the unmutated run does not have. The unmutated run may itself be red, so the comparison is of every
finding line in full (its invariant, store, person and detail: counts, keys, markers), counted per test case: new
damage to a person who is already red shows as a new or more frequent line.

Each caught mutation says which invariants caught it, and whether any of them saw it **on published rows** (sharing,
splitting, references, opt-out, hold, stability, path independence over rows the box published) or only as
"nothing was published" (a night the product itself refused, or a store left empty).

    python -m tools.gate2_planted --work <scratch dir> [--only a,b] [-n 2] [-k as_written] [--out results.json]

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
from collections import Counter
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

from tb_common.identity import ResolvedRecord


def visit_key(rtype: str, number: str) -> str:
    return f"{rtype}-{number}"


def visit_record(rec: ResolvedRecord, number: str) -> ResolvedRecord:
    return ResolvedRecord(rec.owner, f"Encounter-{number}", None, rec.namespace, rec.resource_type, rec.table)
'''
_GATE = "self._resolve(rs, row, rs.type, col, rs.table, str(rs.id.get('suffix', '')))"

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
        "their references; a bare string, which the mapper's own checks refuse)",
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
        "a lab key made by hashing the bare record id, no owner or namespace (the mapped feeds' labs; a bare string)",
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
        "d2",
        "a visit key built with an f-string in a new file, passed off as the gate's own record (the mapped feeds' "
        "visits; the owner still resolved, so the mapper's runtime checks accept it)",
        (
            (
                "services/adapter/mapping/engine.py",
                _OWN_KEY,
                '        if rs.type == "Encounter":\n'
                "            from adapter.mapping.g2_planted_keys import visit_record\n\n"
                f"            return visit_record({_GATE}, str(row[col]))\n" + _OWN_KEY,
            ),
        ),
        (("services/adapter/mapping/g2_planted_keys.py", _BYPASS),),
    ),
    Mutation(
        "e2",
        "a lab key made by hashing the bare record id, passed off as the gate's own record (the mapped feeds' labs)",
        (
            (
                "services/adapter/mapping/engine.py",
                _OWN_KEY,
                '        if rs.type == "Observation":\n'
                f"            rec = {_GATE}\n"
                "            return ResolvedRecord(rec.owner, resource_id(self.key, rs.type, str(row[col])), None, "
                "rec.namespace, rec.resource_type, rec.table)\n" + _OWN_KEY,
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
        "j",
        "the OMOP opt-out withhold tombstones the records but leaves their CDM rows (and the person row)",
        (
            (
                "services/omop/load.py",
                "    before = _drop_rows(tx, by_table)\n",
                "    before: dict[tuple[str, int], str] = {}\n",
            ),
            (
                "services/omop/load.py",
                '    tx.execute("DELETE FROM person WHERE person_id = ANY(?)", (persons,))\n',
                "",
            ),
        ),
    ),
    Mutation(
        "k",
        "the lake's note chunk key made without the document id",
        (
            (
                "services/lake/store.py",
                "arrow[\"chunk_key\"] = [f\"{r['did']}#{r['chunk_no']}\" for r in part]",
                'arrow["chunk_key"] = [f"{r[\'chunk_no\']}" for r in part]',
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
_DIGEST = re.compile(r"\b[0-9a-f]{8,}\b")
_FAILED = re.compile(r"^(FAILED|ERROR) (\S+)")


@dataclass
class Run:
    rc: int
    seconds: float
    failed: set[str] = field(default_factory=set)
    findings: Counter[tuple[str, str]] = field(default_factory=Counter)  # (case, finding line) -> how many


def parse(text: str) -> Run:
    run = Run(rc=0, seconds=0.0)
    case = ""
    for line in text.splitlines():
        if m := _CASE.match(line):
            case = f"{m[1]}-{m[2]}-{m[3]}"
        elif (m := _FINDING.match(line)) and case:
            # the line in full but for the digests a key or a pseudonym prints: a mutation that changes how keys are
            # spelled must not look like new damage, while a new count, person, store, marker or kind of row does
            run.findings[(case, _DIGEST.sub("#", line[10:]))] += 1
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


def run_test(tree: Path, log: Path, workers: int, basetemp: Path, select: str = "") -> Run:
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
            [sys.executable, "-m", "pytest", "-q", "-n", str(workers), "--basetemp", str(basetemp), TEST]
            + (["-k", select] if select else []),
            cwd=tree,
            env=env,
            check=False,
            stdout=fh,
            stderr=subprocess.STDOUT,
        ).returncode
    run = parse(log.read_text(encoding="utf-8", errors="replace"))
    run.rc, run.seconds = rc, round(time.monotonic() - t0, 1)
    return run


def unpublished(line: str, refused: bool) -> bool:
    """A finding that says only that nothing was published: a refused night, an empty store, or (in a case where a
    night was refused or a store left empty) a zero count. In a case whose nights were published, a zero count is a
    record lost on published rows."""
    if line.startswith(("published ", "read ")):
        return True
    return refused and bool(re.search(r": 0 \S+ rows, expected [1-9]", line))


def describe(new: Counter[tuple[str, str]]) -> tuple[str, list[str]]:
    """The invariants that caught a mutation on published rows (with person and roads), and those that saw only
    that nothing was published."""
    on_rows: dict[tuple[str, str], set[str]] = {}
    only: set[str] = set()
    refused = {case for case, line in new if line.startswith(("published ", "read "))}
    for case, line in new:
        m = _FINDING.match("E" + " " * 9 + line)
        inv, person = (m[1], m[3]) if m else (line.split()[0], "?")
        road = case.split("-")[0]
        if unpublished(line, case in refused):
            only.add(inv)
        else:
            on_rows.setdefault((inv, person), set()).add(road)
    text = "; ".join(f"{inv}[{p}] on {','.join(sorted(roads))}" for (inv, p), roads in sorted(on_rows.items()))
    return text, sorted(only)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--work", type=Path, required=True, help="a scratch folder (the copy and the logs go there)")
    ap.add_argument("--only", default="", help="mutation ids, comma separated (default: all)")
    ap.add_argument("-n", type=int, default=2, help="pytest workers (default 2)")
    ap.add_argument("--out", type=Path, help="write the results as JSON here")
    ap.add_argument("-k", dest="select", default="", help="a pytest -k expression (e.g. one order: as_written)")
    ap.add_argument("--from-logs", action="store_true", help="judge the logs an earlier run left in --work again")
    args = ap.parse_args(argv)
    only = {x for x in args.only.split(",") if x}
    todo = [m for m in MUTATIONS if not only or m.id in only]
    tree = args.work / "trialbox"

    def logged(name: str) -> Run:
        return parse((args.work / name).read_text(encoding="utf-8", errors="replace"))

    if not args.from_logs:
        copy_tree(tree)
    base = (
        logged("baseline.log")
        if args.from_logs
        else run_test(tree, args.work / "baseline.log", args.n, args.work / "pytest-baseline", args.select)
    )
    print(
        f"baseline: rc {base.rc}, {len(base.failed)} failing cases, {base.findings.total()} findings, {base.seconds} s",
        flush=True,
    )
    results = []
    for m in todo:
        if args.from_logs:
            got = logged(f"mutation-{m.id}.log")
        else:
            apply(tree, m)
            try:
                got = run_test(
                    tree, args.work / f"mutation-{m.id}.log", args.n, args.work / f"pytest-{m.id}", args.select
                )
            finally:
                restore(tree, m)
        new = got.findings - base.findings
        newly_failed = got.failed - base.failed
        red = bool(new or newly_failed)
        on_rows, saw = describe(new)
        line = f"{m.id} {m.what} -> {'red' if red else 'green'}"
        if on_rows:
            line += f": on published rows: {on_rows}"
        if saw:
            line += f"; nothing published ({', '.join(saw)})"
        if red and not on_rows:
            line += " [caught ONLY because the product published nothing]"
        if newly_failed and not new:
            line += f": newly failing {sorted(newly_failed)[:3]}"
        print(line, flush=True)
        results.append(
            {
                "id": m.id,
                "what": m.what,
                "red": red,
                "on_published_rows": on_rows,
                "nothing_published": saw,
                "new_findings": [[c, ln, n] for (c, ln), n in sorted(new.items())],
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
                        "findings": base.findings.total(),
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
