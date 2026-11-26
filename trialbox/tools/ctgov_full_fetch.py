"""Full ClinicalTrials.gov re-fetch: every module of every study, paged, resumable (public data, no patient data).

The corpus fetched earlier was field-filtered and has no first-post date, so the held-out split was taken from a
separate id query. This fetch leaves ``fields`` out, so each record carries all its modules (status dates, uploaded
protocol documents, MeSH browse terms, results). The registry serves one stream slowly (about 100 KB/s), so the
full copy is cut into first-post-date slices (``--where``), one output directory each under one parent, fetched
side by side. The readers take the parent.

    python tools/ctgov_full_fetch.py fetch --out I:/tb-protocols/ctgov_full/part-2020 \\
        --where "AREA[StudyFirstPostDate]RANGE[2020-01-01,2020-12-31]"   # resumable; run again to continue
    python tools/ctgov_full_fetch.py status --dir I:/tb-protocols/ctgov_full           # records against the registry
    python tools/ctgov_full_fetch.py heldout --dir I:/tb-protocols/ctgov_full --ref heldout_ncts.txt
    python tools/ctgov_full_fetch.py documents --dir I:/tb-protocols/ctgov_full        # uploaded documents per family

``fetch`` writes ``pNNNN.json.gz`` ({"studies": [...]}) and ``state.json`` (next page token, count, registry version).
A page file is written before the state moves, so a stop at any point loses at most the page in flight.
Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import http.client
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

API = "https://clinicaltrials.gov/api/v2"
DOC_URL = "https://cdn.clinicaltrials.gov/large-docs/{tail}/{nct}/{filename}"
UA = "trialbox-landscape-fetch"
# the five disease families of the synthetic hospital, as the registry's MeSH condition terms (own term or ancestor)
FAMILIES = {
    "gout": ("Gout",),
    "rheumatoid_arthritis": ("Arthritis, Rheumatoid",),
    "alzheimer": ("Alzheimer Disease",),
    "oncology": ("Neoplasms",),
    "type2_diabetes": ("Diabetes Mellitus, Type 2",),
}


def _get(url: str, tries: int = 6) -> Any:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=300) as r:  # gzip on the wire: a page is 17 MB raw, 4 MB packed
                body = r.read()
                return json.loads(gzip.decompress(body) if r.headers.get("Content-Encoding") == "gzip" else body)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or i == tries - 1:
                raise
        except (OSError, http.client.HTTPException, ValueError):  # a dropped or cut-short response, bad JSON included
            if i == tries - 1:
                raise
        time.sleep(5 * 2**i)
    raise AssertionError("unreachable")


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def fetch(
    out: Path,
    page_size: int = 1000,
    pause: float = 1.0,
    max_pages: int = 0,
    where: str = "",
    get: Callable[[str], Any] = _get,
) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    sp = out / "state.json"
    # ponytail: a stored page token can lapse if the run is left stopped for long; delete state.json and the pages then
    st: dict[str, Any] = (
        json.loads(sp.read_text()) if sp.exists() else {"pages": 0, "tok": None, "done": False, "records": 0}
    )
    if not st["pages"]:
        st["version"] = get(f"{API}/version").get("dataTimestamp")
        st["where"] = where
    done_now = 0
    while not st["done"] and not (max_pages and done_now >= max_pages):
        q = {"pageSize": str(page_size), "format": "json", "countTotal": "true"}
        if where:
            q["filter.advanced"] = where
        if st["tok"]:
            q["pageToken"] = st["tok"]
        r = get(f"{API}/studies?{urllib.parse.urlencode(q)}")
        n = st["pages"] + 1
        if n == 1:
            st["expected"] = int(r["totalCount"])  # the slice's size as the registry counts it; later pages omit it
        _write_atomic(out / f"p{n:04d}.json.gz", gzip.compress(json.dumps({"studies": r["studies"]}).encode(), 6))
        st.update(pages=n, tok=r.get("nextPageToken"), records=st["records"] + len(r["studies"]))
        st["done"] = not st["tok"]
        _write_atomic(sp, json.dumps(st).encode())
        done_now += 1
        print(f"{out.name} page {n}: {st['records']:,} of {st['expected']:,}", flush=True)
        if not st["done"]:
            time.sleep(pause)
    return st


def status(d: Path) -> dict[str, Any]:
    """Records on disk against what each slice's first page said it holds, and whether every slice is finished."""
    sts = {p.parent.name: json.loads(p.read_text()) for p in sorted(d.glob("**/state.json"))}
    return {
        "slices": len(sts),
        "all_done": all(s["done"] for s in sts.values()),
        "records": sum(s["records"] for s in sts.values()),
        "expected": sum(s["expected"] for s in sts.values()),
        "unfinished": {k: f"{s['records']}/{s['expected']}" for k, s in sts.items() if not s["done"]},
    }


def iter_studies(d: Path) -> Iterator[dict[str, Any]]:
    for p in sorted(d.glob("**/p[0-9][0-9][0-9][0-9].json.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            yield from json.load(f)["studies"]


def _nct(s: dict[str, Any]) -> str:
    return str(s["protocolSection"]["identificationModule"]["nctId"])


def first_post(s: dict[str, Any]) -> str | None:
    d = (s["protocolSection"].get("statusModule", {}).get("studyFirstPostDateStruct") or {}).get("date")
    return (d + "-01" if len(d) == 7 else d) if d else None  # the registry may give a month only


def heldout(d: Path, ref: Path, since: str = "2026-01-01") -> dict[str, Any]:
    """Studies first posted on or after ``since``, from the records themselves, diffed against the id list ``ref``."""
    new: dict[str, str] = {}
    ids: set[str] = set()
    n = 0
    missing: list[str] = []
    for s in iter_studies(d):
        n += 1
        ids.add(_nct(s))
        fp = first_post(s)
        if fp is None:
            missing.append(_nct(s))
        elif fp >= since:
            new[_nct(s)] = fp
    old = set(ref.read_text().split())
    only_old, only_new = old - set(new), set(new) - old
    (d / "heldout_firstpost.txt").write_text("\n".join(sorted(new)) + "\n")
    return {
        "records": n,
        "distinct_ncts": len(ids),
        "without_first_post_date": len(missing),
        "heldout_from_records": len(new),
        "heldout_ref": len(old),
        "only_in_ref": len(only_old),
        "only_in_ref_absent_from_records": len(only_old - ids),
        "only_in_records": len(only_new),
        "only_in_records_first_post_range": [min(new[i] for i in only_new), max(new[i] for i in only_new)]
        if only_new
        else None,
        "diff_pct_of_ref": round(100 * (len(only_old) + len(only_new)) / max(len(old), 1), 3),
    }


def families_of(s: dict[str, Any]) -> list[str]:
    b = s.get("derivedSection", {}).get("conditionBrowseModule") or {}
    terms = {m["term"] for k in ("meshes", "ancestors") for m in b.get(k, [])}
    return [f for f, ts in FAMILIES.items() if terms & set(ts)]


def documents(d: Path) -> dict[str, Any]:
    """One row per uploaded document of a study in a family; counts per family. A study can sit in several families."""
    rows = []
    studies: Counter[str] = Counter()
    with_docs: Counter[str] = Counter()
    kinds: dict[str, Counter[str]] = {f: Counter() for f in FAMILIES}
    for s in iter_studies(d):
        fams = families_of(s)
        docs = (s.get("documentSection", {}).get("largeDocumentModule") or {}).get("largeDocs", [])
        for f in fams:
            studies[f] += 1
            with_docs[f] += bool(docs)
            for x in docs:
                kinds[f][x.get("typeAbbrev", "")] += 1
                rows.append(
                    {
                        "family": f,
                        "nct": _nct(s),
                        "type": x.get("typeAbbrev"),
                        "has_protocol": x.get("hasProtocol"),
                        "has_sap": x.get("hasSap"),
                        "has_icf": x.get("hasIcf"),
                        "date": x.get("date"),
                        "bytes": x.get("size"),
                        "url": DOC_URL.format(tail=_nct(s)[-2:], nct=_nct(s), filename=x["filename"]),
                    }
                )
    with (d / "documents.csv").open("w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=list(rows[0]) if rows else ["family"])
        w.writeheader()
        w.writerows(rows)
    return {
        f: {"studies": studies[f], "studies_with_documents": with_docs[f], "documents": dict(kinds[f])}
        for f in FAMILIES
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--out", type=Path, required=True)
    f.add_argument("--page-size", type=int, default=1000)
    f.add_argument("--pause", type=float, default=1.0)
    f.add_argument("--max-pages", type=int, default=0, help="stop after N pages this run (0 = to the end)")
    f.add_argument("--where", default="", help="registry filter.advanced expression: one slice of the registry")
    s = sub.add_parser("status")
    s.add_argument("--dir", type=Path, required=True)
    h = sub.add_parser("heldout")
    h.add_argument("--dir", type=Path, required=True)
    h.add_argument("--ref", type=Path, required=True)
    h.add_argument("--since", default="2026-01-01")
    d = sub.add_parser("documents")
    d.add_argument("--dir", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        res = fetch(a.out, a.page_size, a.pause, a.max_pages, a.where)
    elif a.cmd == "status":
        res = status(a.dir)
    elif a.cmd == "heldout":
        res = heldout(a.dir, a.ref, a.since)
    else:
        res = documents(a.dir)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
