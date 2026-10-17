"""Fetch the open MIMIC-IV Clinical Database Demo on FHIR (v2.1.0) for the open-data end-to-end test.

Source: PhysioNet, https://physionet.org/content/mimic-iv-fhir-demo/2.1.0/ (100 de-identified patients, Open Data
Commons Open Database License v1.0). The files are **not** committed: they are downloaded into
``.cache/open_data/mimic-iv-fhir-demo/`` (gitignored), each verified against the release's ``SHA256SUMS.txt``.
Attribution and citation: ``docs/OPEN_DATA.md``.

    python tools/fetch_open_data.py                 # the default resource files (idempotent)
    python tools/fetch_open_data.py --ctgov         # also refresh tests/fixtures/open_data/ctgov_*.json

``--ctgov`` re-downloads the eligibility text of the trials used by the test from the ClinicalTrials.gov API v2 and
stores it with the NCT id and retrieval date (the hand-written rulesets in ``tests/fixtures/open_data/rulesets``
cite that text).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = "mimic-iv-fhir-demo"
VERSION = "2.1.0"
BASE = f"https://physionet.org/files/{DATASET}/{VERSION}"
DEFAULT_OUT = ROOT / ".cache" / "open_data" / DATASET
FIXTURES = ROOT / "tests" / "fixtures" / "open_data"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"
# resource files the pipeline reads (MimicMedication / MimicMedicationMix resolve medicationReference; the ICU files
# carry ICU stays and charted ICU procedures such as CRRT and invasive ventilation)
FILES = [
    "fhir/MimicPatient.ndjson.gz",
    "fhir/MimicEncounter.ndjson.gz",
    "fhir/MimicCondition.ndjson.gz",
    "fhir/MimicObservationLabevents.ndjson.gz",
    "fhir/MimicMedicationRequest.ndjson.gz",
    "fhir/MimicMedication.ndjson.gz",
    "fhir/MimicMedicationMix.ndjson.gz",
    "fhir/MimicEncounterICU.ndjson.gz",
    "fhir/MimicProcedureICU.ndjson.gz",
    "fhir/MimicProcedure.ndjson.gz",
]
EXTRA = ["LICENSE.txt"]
TRIALS = ["NCT04157751", "NCT02568722"]  # EMPULSE (acute heart failure), STARRT-AKI (severe AKI in ICU)


def _get(url: str, attempts: int = 6, timeout: int = 300) -> bytes:
    ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
    req = urllib.request.Request(url, headers={"User-Agent": "trialbox-fetch-open-data/1.0"})
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                data: bytes = resp.read()
            return data
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 404, 407):
                raise
            if i == attempts - 1:
                raise
            wait = 2 ** (i + 1)
            print(f"  {url}: {exc}; retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def parse_sums(text: str) -> dict[str, str]:
    """``SHA256SUMS.txt`` lines ``<sha256> <path>`` -> {path: sha256}."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and len(parts[0]) == 64:
            out[parts[1].lstrip("*").strip()] = parts[0].lower()
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch_mimic(out: Path, files: list[str]) -> dict[str, str]:
    out.mkdir(parents=True, exist_ok=True)
    sums_text = _get(f"{BASE}/SHA256SUMS.txt").decode("utf-8")
    (out / "SHA256SUMS.txt").write_text(sums_text, encoding="utf-8")
    sums = parse_sums(sums_text)
    done: dict[str, str] = {}
    for rel in files:
        want = sums.get(rel)
        if want is None:
            raise SystemExit(f"{rel} is not listed in {BASE}/SHA256SUMS.txt")
        target = out / rel
        if target.exists() and sha256_file(target) == want:
            done[rel] = want
            continue
        print(f"downloading {rel} ...", file=sys.stderr)
        data = _get(f"{BASE}/{rel}")
        got = hashlib.sha256(data).hexdigest()
        if got != want:
            raise SystemExit(f"sha256 mismatch for {rel}: got {got}, SHA256SUMS.txt says {want}")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(target)
        done[rel] = want
    (out / "FETCHED.json").write_text(
        json.dumps({"dataset": DATASET, "version": VERSION, "base_url": BASE, "files": done}, indent=1, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return done


def fetch_ctgov(nct_ids: list[str], out_dir: Path) -> list[Path]:
    """Eligibility module (+ identification/status/conditions) of each trial, with the retrieval date."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fields = ",".join(
        [
            "protocolSection.identificationModule",
            "protocolSection.statusModule",
            "protocolSection.conditionsModule",
            "protocolSection.eligibilityModule",
            "protocolSection.designModule.phases",
        ]
    )
    written = []
    for nct in nct_ids:
        url = f"{CTGOV}/{nct}?format=json&fields={fields}"
        study = json.loads(_get(url))
        body = {
            "nct_id": nct,
            "source_url": f"{CTGOV}/{nct}",
            "retrieved": datetime.now(UTC).date().isoformat(),
            "study": study,
        }
        path = out_dir / f"ctgov_{nct}.json"
        path.write_text(json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--file",
        action="append",
        default=[],
        help="extra release path, e.g. fhir/MimicObservationChartevents.ndjson.gz",
    )
    ap.add_argument("--ctgov", action="store_true", help="refresh the cached CT.gov eligibility fixtures")
    ap.add_argument("--ctgov-only", action="store_true", help="only refresh the CT.gov fixtures")
    args = ap.parse_args(argv)
    if not args.ctgov_only:
        done = fetch_mimic(args.out, FILES + EXTRA + list(args.file))
        for rel, sha in sorted(done.items()):
            print(f"{sha}  {rel}")
    if args.ctgov or args.ctgov_only:
        for p in fetch_ctgov(TRIALS, FIXTURES):
            print(f"wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
