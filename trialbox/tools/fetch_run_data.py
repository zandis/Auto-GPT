"""The data the cloud complete run needs and git does not carry (review C-02, C-03 of 2026-11-09), fetched on the VM.

    python -m tools.fetch_run_data --cache /var/lib/tb/cache [--only TAG ...]

* ``cql``: the CQL translator's ``quick-5.4.0.jar`` (Maven Central, sha256 pinned, 4.8 MB): the box reads
  FHIRHelpers-4.0.1.cql from it whenever it compiles criteria (the in-process box's translator is a fake, so no JRE
  is needed). Without it every hospital part crashed in compiling on the cloud run of 2026-11-09. This is the
  minimal variant ``deploy/gcp/hosted-demo-startup.sh`` already uses, instead of ``tools/fetch_jvm_deps.sh``'s 770 MB.
* ``medtxt``: NTCIR-16 Real-MedNLP MedTxt (CC BY 4.0, Sociocom NAIST; 1.4 MB): ``tools.medtxt_eval.fetch``.
* ``trec``: TREC Clinical Trials 2021/2022 (NIST topics and qrels; the sampled trials from NCBI's corpus, streamed and
  never kept; ClinicalTrials.gov's structured fields): ``tools.trec_ct_eval.fetch(keep_corpus=False)``.

Only public data, only what the planned parts need (``complete_run.data_needs``; no ``--only``: everything). Each
dataset is fetched once into ``--cache`` (the VM's persistent disk) and linked into ``.cache/``, where the tools read
it; a source tree's own ``.cache/<name>`` (a laptop's) is left alone. A dataset that cannot be fetched is reported on
one line ``TB-DATA-MISSING <name>: <why>``; the parts that need it then fail at once with "data missing" and never run
(``complete_run.data_missing``), so they cost no card time. Exit code: the number of datasets missing.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

QUICK_URL = "https://repo1.maven.org/maven2/org/cqframework/quick/5.4.0/quick-5.4.0.jar"
QUICK_SHA256 = "b5b1b076711d7c6ddb700f7f6d7aacc210824dc37a41405fdfd9fab09d6a2ba4"
LINKS = {"cql": "jvm", "medtxt": "medtxt", "trec": "trec_ct"}  # dataset -> its folder under .cache


def _link(cache: Path, name: str) -> Path:
    """``.cache/<name>`` -> ``<cache>/<name>`` unless the source tree has its own; returns the folder the tools use."""
    src = ROOT / ".cache" / name
    if src.is_symlink() or not src.exists():
        (cache / name).mkdir(parents=True, exist_ok=True)
        src.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            src.unlink()
        src.symlink_to((cache / name).resolve(), target_is_directory=True)
    return src


def fetch_cql(cache: Path) -> None:
    import httpx

    lib = _link(cache, "jvm") / "cql-translator" / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    jar = lib / "quick-5.4.0.jar"
    if jar.exists() and hashlib.sha256(jar.read_bytes()).hexdigest() == QUICK_SHA256:
        return
    r = httpx.get(QUICK_URL, timeout=300, follow_redirects=True)
    r.raise_for_status()
    got = hashlib.sha256(r.content).hexdigest()
    if got != QUICK_SHA256:
        raise RuntimeError(f"quick-5.4.0.jar sha256 {got[:16]}..., expected {QUICK_SHA256[:16]}...")
    tmp = jar.with_name(jar.name + ".part")
    tmp.write_bytes(r.content)
    tmp.replace(jar)


def fetch_medtxt(cache: Path) -> None:
    from tools import medtxt_eval

    _link(cache, "medtxt")
    medtxt_eval.fetch()


def fetch_trec(cache: Path) -> None:
    from tools import trec_ct_eval

    _link(cache, "trec_ct")
    trec_ct_eval.fetch(keep_corpus=False)


FETCH = {"cql": fetch_cql, "medtxt": fetch_medtxt, "trec": fetch_trec}


def needed(only: list[str]) -> list[str]:
    from tools import complete_run as cr

    if not only:
        return list(FETCH)
    want = {n for t in only for n in cr.data_needs(t)}
    return [n for n in FETCH if n in want]


def main(argv: list[str] | None = None) -> int:
    from tools import complete_run as cr

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cache", type=Path, required=True, help="where the data stays between runs (the VM's disk)")
    ap.add_argument("--only", nargs="*", default=[], help="the run's parts (complete_run --only tags); none: all")
    ap.add_argument("--tries", type=int, default=3)
    a = ap.parse_args(argv)
    a.cache.mkdir(parents=True, exist_ok=True)
    missing = 0
    for name in needed(a.only):
        why = ""
        for attempt in range(max(1, a.tries)):
            if attempt:
                time.sleep(20.0 * attempt)  # Maven Central and CT.gov answer 429 to bursts
            try:
                FETCH[name](a.cache)
                why = cr.DATA_CHECKS[name]()  # the same test the part makes before it runs
            except Exception as exc:  # any failure: reported, and the part fails fast
                why = f"{type(exc).__name__}: {exc}"[:300]
            if not why:
                break
        if why:
            missing += 1
            print(f"TB-DATA-MISSING {name}: {why}", flush=True)
        else:
            print(f"TB-DATA {name}: ready in {ROOT / '.cache' / LINKS[name]}", flush=True)
    return missing


if __name__ == "__main__":
    raise SystemExit(main())
