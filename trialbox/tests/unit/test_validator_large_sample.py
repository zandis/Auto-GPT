"""The HL7 validator takes a sample of any size (review 2026-11-11-scale-timeouts, F-06).

The night's sample is 1 % of the load, so it grows with the hospital; the validator got every sampled file as one
command-line argument of one ``java`` process. Past about 65,000 Observation files (with the usual 8 MiB stack limit) the kernel refuses the command (``Argument list
too long``), the pipeline reports "validation failed to run" and the night is held: a site of 50,000 patients with 130
or more resources each could never publish its first load. The file index was also written and read as five digits,
so results from file 100,000 on were dropped. ``java`` is a small stand-in that answers one outcome per file it was
given; the wrapper under test is the real one.
"""

from __future__ import annotations

import stat
from pathlib import Path

from adapter.validate.validator import BATCH, Hl7Validator

FAKE_JAVA = """#!/usr/bin/env python3
import json, sys
a = sys.argv[1:]
out = a[a.index("-output") + 1]
files = [x for x in a if x.endswith(".json") and x != out]
with open(sys.argv[0] + ".calls", "a") as fh:
    fh.write(f"{len(files)}\\n")
ext = "http://hl7.org/fhir/StructureDefinition/operationoutcome-file"
def oo(f):
    bad = f.startswith("r00007-") or f.startswith("r99999-")
    issue = [{"severity": "error", "details": {"text": "bad"}, "expression": ["Patient.id"]}] if bad else []
    return {"resource": {"resourceType": "OperationOutcome", "extension": [{"url": ext, "valueString": f}],
                         "issue": issue}}
json.dump({"resourceType": "Bundle", "entry": [oo(f) for f in files]}, open(out, "w"))
"""


def _validator(tmp_path: Path) -> tuple[Hl7Validator, Path]:
    java = tmp_path / "java"
    java.write_text(FAKE_JAVA, encoding="utf-8")
    java.chmod(java.stat().st_mode | stat.S_IEXEC)
    return Hl7Validator(tmp_path / "validator_cli.jar", tmp_path / "home", java=str(java)), Path(f"{java}.calls")


def test_a_sample_larger_than_one_command_line_is_validated_in_batches(tmp_path: Path) -> None:
    v, calls = _validator(tmp_path)
    # 100,000 names of 32 bytes (the name and its pointer) are 3.2 MB: over the limit of one command where the
    # stack limit is the usual 8 MiB (2 MiB of arguments). The limit is the machine's, so the test does not assert
    # it; it asserts that no run got more than BATCH files, which holds on any machine
    n = 100_000
    res = v.validate([{"resourceType": "Observation", "id": "o"}] * n)
    assert res.sampled == n
    assert res.errors == 2
    assert sorted(i for i, e in res.per_file.items() if e) == [7, 99_999]  # the index is the sample's, not a batch's
    assert len(res.per_file) == n
    sizes = [int(x) for x in calls.read_text().split()]
    assert sum(sizes) == n and max(sizes) <= BATCH


def test_a_file_index_past_five_digits_is_read() -> None:
    ext = "http://hl7.org/fhir/StructureDefinition/operationoutcome-file"
    oo = {"resourceType": "OperationOutcome", "extension": [{"url": ext, "valueString": "r123456-Patient.json"}],
          "issue": [{"severity": "error", "details": {"text": "bad"}}]}  # fmt: skip
    assert list(Hl7Validator._parse(oo, 1).per_file) == [123456]
