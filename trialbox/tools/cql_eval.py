"""CQL verdicts without a FHIR server (T-504, D-321): the clinical-reasoning engine HAPI FHIR 8.12 runs behind
``Library/$evaluate`` (cqf-fhir-cql 4.13.0, CQL engine and translator 5.4.0), in process over an in-memory repository.

Build-time only, like ``tools/build_rulesets.py``: it needs a JDK and the jars of ``tools/cql_local/pom.xml``
(``--fetch`` runs Maven once into ``.cache/jvm/cql-local/lib``). Nothing at a site uses it.

* :class:`LocalFhir` stands in for ``tb_common.fhir.FhirEvaluator`` in the compiler's equivalence gate (``load`` and
  ``evaluate_many``), reading the patients' FHIR resources from the adapter's NDJSON;
* ``python -m tools.cql_eval --check RA-BIO`` replays a committed ruleset's ``tests/patients.ndjson`` and compares the
  verdicts with its ``tests/expected.json`` (recorded from HAPI): the check that this engine answers as HAPI does.

    python -m tools.cql_eval --fetch
    python -m tools.cql_eval --check RA-BIO GZQO RA-COH
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tb_common.fhir import FhirEvaluator, library_resource  # noqa: E402
from tb_contracts import PatientEvaluation  # noqa: E402

SRC = ROOT / "tools" / "cql_local"
LIB = Path(os.environ.get("TB_CQL_LOCAL_LIB", ROOT / ".cache" / "jvm" / "cql-local" / "lib"))
ENGINE = "cqf-fhir-cql 4.13.0 LibraryEngine in process (CQL engine 5.4.0, as HAPI 8.12 CR $evaluate)"
TEST_KEY = b"trialbox-test-site-key-0123456789abcdef"


def available() -> bool:
    return LIB.is_dir() and any(LIB.glob("cqf-fhir-cql-*.jar")) and shutil.which("java") is not None


def fetch() -> None:
    LIB.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["mvn", "-q", "-B", "-f", str(SRC / "pom.xml"), "dependency:copy-dependencies", f"-DoutputDirectory={LIB}"],
        check=True,
    )


def run(
    resources: list[str], library: str, version: str, index_date: date, exprs: list[str], pids: list[str]
) -> list[dict[str, Any]]:
    """Evaluate ``exprs`` of ``library`` for each pid; ``resources`` are FHIR JSON lines (patients' resources,
    ValueSets and the Library resources). Returns one FHIR Parameters per patient (``id`` = the pid)."""
    if not available():
        raise RuntimeError(f"the local CQL engine is missing: python -m tools.cql_eval --fetch (into {LIB})")
    cp = os.pathsep.join(str(p) for p in sorted(LIB.glob("*.jar")))
    with tempfile.TemporaryDirectory(prefix="tb-cql-") as td:
        t = Path(td)
        (t / "res.ndjson").write_text("\n".join(resources) + "\n", encoding="utf-8")
        (t / "pids.txt").write_text("\n".join(pids) + "\n", encoding="utf-8")
        args = [str(t / "res.ndjson"), library, version, index_date.isoformat(), ",".join(exprs), str(t / "pids.txt")]
        done = subprocess.run(
            ["java", "-Xmx3g", "-cp", cp, str(SRC / "CqlLocal.java"), *args, str(t / "out.ndjson")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
        )
        if done.returncode != 0:
            tail = [x for x in done.stderr.splitlines() if not x.startswith("Picked up")][-12:]
            raise RuntimeError("the local CQL engine failed:\n" + "\n".join(tail))
        return [json.loads(x) for x in (t / "out.ndjson").read_text(encoding="utf-8").splitlines() if x.strip()]


class LocalFhir:
    """``FhirEvaluator``'s ``load`` and ``evaluate_many`` over the adapter's NDJSON (``ndjson_dir``: one snapshot)."""

    def __init__(self, ndjson_dir: Path) -> None:
        self.ndjson_dir = ndjson_dir
        self.libraries: dict[str, dict[str, Any]] = {}
        self.valuesets: dict[str, dict[str, Any]] = {}
        self._by_patient: dict[str, list[str]] | None = None

    def load(self, libraries: list[dict[str, Any]], valuesets: Iterable[dict[str, Any]]) -> None:
        for vs in valuesets:
            self.valuesets[str(vs["id"])] = vs
        for lib in libraries:
            self.libraries[str(lib["name"])] = lib

    def patient_lines(self) -> dict[str, list[str]]:
        """pid -> the JSON lines of the Patient and every resource that refers to it (notes left out)."""
        if self._by_patient is None:
            out: dict[str, list[str]] = {}
            for f in sorted(self.ndjson_dir.glob("*.ndjson")):
                if f.stem == "DocumentReference":
                    continue
                for line in f.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    if r["resourceType"] == "Patient":
                        out.setdefault(r["id"], []).append(line)
                        continue
                    for pid in _patient_refs(r):
                        out.setdefault(pid, []).append(line)
            self._by_patient = out
        return self._by_patient

    def evaluate_many(
        self, library_name: str, pids: list[str], index_date: date, expressions: list[str]
    ) -> list[PatientEvaluation]:
        lines = self.patient_lines()
        res = sorted({x for p in pids for x in lines.get(p, [])})
        res += [json.dumps(v) for v in self.valuesets.values()] + [json.dumps(v) for v in self.libraries.values()]
        version = str(self.libraries[library_name]["version"])
        out = run(res, library_name, version, index_date, expressions, pids)
        return [FhirEvaluator.parse(str(b["id"]), index_date, b, expressions) for b in out]


def _patient_refs(r: dict[str, Any]) -> set[str]:
    text = json.dumps(r)
    out = set()
    start = 0
    while True:
        i = text.find('"Patient/', start)
        if i < 0:
            return out
        j = text.find('"', i + 1)
        out.add(text[i + 9 : j])
        start = j


def libraries(rs: Any) -> list[dict[str, Any]]:
    """The Library resources of a loaded ``tb_common.ruleset.Ruleset`` (its library and TB_Common, CQL and ELM)."""
    out = []
    for name, cql in rs.cql.items():
        head = next(x for x in cql.splitlines() if x.startswith("library "))
        out.append(library_resource(name, head.split(" version ")[1].strip().strip("'"), cql, rs.elm.get(name)))
    return out


def check(ruleset: str) -> tuple[int, int, list[tuple[str, str, Any, Any]]]:
    """Replay ``rulesets/<id>/tests/patients.ndjson`` and compare with ``tests/expected.json``."""
    from criteria_compiler.compile_cql.generator import CqlGenerator
    from tb_common.crypto import pid_for_mrn
    from tb_common.ruleset import Ruleset

    rs = Ruleset.load(ROOT / "rulesets" / ruleset)
    exp = json.loads((ROOT / "rulesets" / ruleset / "tests" / "expected.json").read_text(encoding="utf-8"))
    lines = (ROOT / "rulesets" / ruleset / "tests" / "patients.ndjson").read_text(encoding="utf-8").splitlines()
    lines += [json.dumps(v) for v in rs.valuesets.values()] + [json.dumps(x) for x in libraries(rs)]
    mrn = {pid_for_mrn(TEST_KEY, m): m for m in exp["patients"]}
    exprs = CqlGenerator.expression_names(rs.ordered())
    index = date.fromisoformat(exp["index_date"])
    agree = total = 0
    bad: list[tuple[str, str, Any, Any]] = []
    for body in run(lines, rs.library, rs.library_version, index, exprs, sorted(mrn)):
        got = FhirEvaluator.parse(str(body["id"]), index, body, exprs).results
        for cid, v in exp["patients"][mrn[str(body["id"])]].items():
            total += 1
            if got.get(cid) == v:
                agree += 1
            else:
                bad.append((mrn[str(body["id"])], cid, v, got.get(cid)))
    return agree, total, bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fetch", action="store_true", help="fetch the engine's jars with Maven")
    ap.add_argument("--check", nargs="*", default=[], metavar="RULESET")
    a = ap.parse_args(argv)
    if a.fetch:
        fetch()
    rc = 0
    for rid in a.check:
        agree, total, bad = check(rid)
        print(f"{rid}: {agree}/{total} verdicts as recorded{'' if not bad else f'; first differences {bad[:5]}'}")
        rc |= int(agree != total)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
