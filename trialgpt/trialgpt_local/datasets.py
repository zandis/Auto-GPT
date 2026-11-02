"""The NCBI TrialGPT cohorts (SIGIR 2016, TREC CT 2021, TREC CT 2022): 183 synthetic patients, graded relevance labels.

    python -m trialgpt_local.datasets fetch [--zip TrialGPT-main.zip] [--corpora]

``fetch`` takes the dataset folder from a downloaded ``TrialGPT-main.zip`` (GitHub "Download ZIP") or a shallow git
clone, and with ``--corpora`` the TREC 2021/2022 trial corpora (~130 MB each) from NCBI's FTP — needed only for the
retrieval stage. The 1.1 GB ``trial_info.json`` is not needed: ``retrieved_trials.json`` carries every trial field
the prompts use.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from trialgpt_local.config import settings

COHORTS = ("sigir", "trec_2021", "trec_2022")
REPO = "https://github.com/ncbi-nlp/TrialGPT.git"
FTP = "https://ftp.ncbi.nlm.nih.gov/pub/lu/TrialGPT"


def cohort_dir(cohort: str) -> Path:
    if cohort not in COHORTS:
        raise ValueError(f"unknown cohort {cohort!r}; one of {COHORTS}")
    return settings().data_dir / "ncbi" / cohort


@dataclass
class Cohort:
    name: str
    queries: dict[str, str]  # patient id -> note
    qrels: dict[str, dict[str, int]]  # patient id -> {NCT id: 0|1|2}
    retrieved: list[dict[str, Any]]  # NCBI retrieved_trials.json (labelled trials among the retrieved, by label)
    id2queries: dict[str, Any]

    def trials_for(self, pid: str) -> list[dict[str, Any]]:
        entry = next((e for e in self.retrieved if e["patient_id"] == pid), None)
        if entry is None:
            return []
        return [t for lab in ("2", "1", "0") for t in entry.get(lab, [])]

    def labels_for(self, pid: str) -> dict[str, int]:
        entry = next((e for e in self.retrieved if e["patient_id"] == pid), None)
        if entry is None:
            return {}
        return {t["NCTID"]: int(lab) for lab in ("2", "1", "0") for t in entry.get(lab, [])}


def load(cohort: str) -> Cohort:
    d = cohort_dir(cohort)
    if not (d / "queries.jsonl").exists():
        raise FileNotFoundError(f"{d} is empty: run `python -m trialgpt_local.datasets fetch` first")
    queries = {}
    for line in (d / "queries.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            q = json.loads(line)
            queries[q["_id"]] = q["text"]
    qrels: dict[str, dict[str, int]] = {}
    for line in (d / "qrels" / "test.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        qid, nct, score = line.split("\t")
        qrels.setdefault(qid, {})[nct] = int(score)
    retrieved = json.loads((d / "retrieved_trials.json").read_text(encoding="utf-8"))
    id2q = json.loads((d / "id2queries.json").read_text(encoding="utf-8"))
    return Cohort(cohort, queries, qrels, retrieved, id2q)


def corpus(cohort: str) -> Iterator[dict[str, Any]]:
    path = cohort_dir(cohort) / "corpus.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: run `python -m trialgpt_local.datasets fetch --corpora`")
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def trial_from_corpus(entry: dict[str, Any]) -> dict[str, Any]:
    """Corpus line -> the trial dict the NCBI prompts expect (same fields as retrieved_trials.json)."""
    return {**entry["metadata"], "NCTID": entry["_id"]}


# ------------------------------------------------------------------------------------------------- fetch
def _from_zip(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if "/dataset/" in n and not n.endswith("/")]
        for n in names:
            rel = n.split("/dataset/", 1)[1]
            if ".." in Path(rel).parts:  # never write outside the target
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(n) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def _from_git(dest: Path) -> None:
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["git", "clone", "-q", "--depth", "1", REPO, td + "/repo"], check=True)
        shutil.copytree(Path(td) / "repo" / "dataset", dest, dirs_exist_ok=True)


def _download(url: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    with httpx.stream("GET", url, timeout=600, follow_redirects=True) as r:
        r.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                fh.write(chunk)
    tmp.replace(out)


def fetch(zip_path: Path | None, corpora: bool) -> None:
    dest = settings().data_dir / "ncbi"
    dest.mkdir(parents=True, exist_ok=True)
    if not (dest / "sigir" / "queries.jsonl").exists():
        _from_zip(zip_path, dest) if zip_path else _from_git(dest)
    if corpora:
        for c in ("trec_2021", "trec_2022"):
            out = dest / c / "corpus.jsonl"
            if not out.exists():
                print(f"downloading {c} corpus (~130 MB)")
                _download(f"{FTP}/{c}_corpus.jsonl", out)
    for c in COHORTS:
        d = dest / c
        files = sorted(p.name for p in d.iterdir()) if d.exists() else []
        print(c, files)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m trialgpt_local.datasets")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--zip", type=Path, help="TrialGPT-main.zip downloaded from GitHub")
    f.add_argument("--corpora", action="store_true", help="also download the TREC 2021/2022 corpora from NCBI FTP")
    a = ap.parse_args(argv)
    fetch(a.zip, a.corpora)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
