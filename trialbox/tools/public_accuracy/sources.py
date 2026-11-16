"""Every public file the accuracy run reads: URL, sha256 pin, size, licence. Fetched into ``.cache/public_accuracy``.

The pattern of ``tools/fetch_open_data.py`` and ``tools/fetch_run_data.py``: a file is written only when its sha256 is
the pinned one (``tools.fetch_pinned``: https only, three tries, a wrong sha256 refused at once), the corpus text stays
in ``.cache`` (gitignored) and is never committed, and ``FETCHED.json`` beside the files records what came from where,
under which licence, on which day. A pin that no longer matches means the publisher changed the file: the fetch stops
and the pin is reviewed by hand, never updated by the fetcher.

Live records (ClinicalTrials.gov studies, jRCT pages, PMC articles, GDC case projects) have no published file to pin.
They are fetched one by one, at most one request every :data:`POLITE_S` seconds, and stored with the URL, the
retrieval date and the sha256 of what came back (``LIVE.json``), as ``tools/fetch_open_data.fetch_ctgov`` stores its
records.

Colour (the catalogues of 2026-11-14): **green** = an open licence a product vendor may use for internal testing
(public domain, CC0, CC BY, CC BY-SA, Apache, OGDL-TW, PDL); **yellow** = usable with the caveat stated in the row
(no licence stated, or a request to the owner). Red sets are not here.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.parse
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache" / "public_accuracy"
# Seconds between two live requests to one host: ClinicalTrials.gov answers about 50 requests a minute before it
# rate-limits (1.2 s; tools/trec_ct_eval.py), and jRCT asks for no crawling, so one record every 3 s at most
POLITE_S = 3.0
USER_AGENT = "trialbox-public-accuracy/1.0"


@dataclass(frozen=True)
class Source:
    id: str  # file name under .cache/public_accuracy/<set>/
    set: str  # the reader in tools.public_accuracy.sets
    url: str
    sha256: str
    bytes: int
    licence: str  # as the source states it, with where it says so
    spdx: str
    colour: str  # green | yellow
    caveat: str  # what limits the use ("" for none)
    attribution: str  # the credit NOTICE carries
    keep: bool = True  # False: streamed and checked against the pin, only the sampled records kept (large corpora)


NIST_NOTE = "NIST pages state no licence terms (catalogue 2026-11-14): yellow, internal validation with a risk note"
TFDA_NOTE = (
    "a live export: TFDA re-exports when its list changes, so this pin breaks then; re-pin after reading the changes"
)

SOURCES: tuple[Source, ...] = (
    # ---------------------------------------------------------------- TREC Clinical Trials (NIST)
    *(
        Source(
            f"{kind}{y}.{ext}",
            "trec",
            f"https://trec.nist.gov/data/trials/{kind}{y}.{ext}",
            sha,
            size,
            "no licence stated (https://trec.nist.gov/data/trials2021.html)",
            "LicenseRef-NIST-TREC-no-terms",
            "yellow",
            NIST_NOTE,
            "TREC Clinical Trials Track, National Institute of Standards and Technology",
        )
        for kind, y, ext, sha, size in (
            ("qrels", "2021", "txt", "ba7a2cddc90285e75cd76adcd483394a6c9bacf7017113222058ba6537e6d8ac", 676496),
            ("qrels", "2022", "txt", "e569a531489e03f7b1fab03fe169c8ea66f4a59e8180fa9858b1a6e4bdcb0c5c", 666030),
            ("qrels", "2023", "txt", "4f0cd4ad573e37d08002fb401bb7ab22a643537753880d9427c96119696582a3", 636340),
            ("topics", "2021", "xml", "94bda921ce7c40a0353f251abb2ea938c77331759a9f83a36abd145ab5840aca", 64618),
            ("topics", "2022", "xml", "c5d37709ba14f6cb341b0bea35a7f43bd1cf93647f939659667975229a7abe91", 32423),
            ("topics", "2023", "xml", "12987f6311f518fa64abe41ada207a442e4deb72e7926f5185b2be82e29ac122", 19307),
        )
    ),
    *(
        Source(
            f"trec_{y}_corpus.jsonl",
            "trec",
            f"https://ftp.ncbi.nlm.nih.gov/pub/lu/TrialGPT/trec_{y}_corpus.jsonl",
            sha,
            size,
            "U.S. Government work, public domain notice (NCBI TrialGPT); trial texts are ClinicalTrials.gov records",
            "LicenseRef-US-Public-Domain",
            "green",
            "streamed, never kept: only the sampled trials stay",
            "TrialGPT, NCBI, U.S. National Library of Medicine; data from ClinicalTrials.gov",
            keep=False,
        )
        for y, sha, size in (
            ("2021", "01692c847b2da798c57a8e0a74273ec262a7e42ad3f02b4ff5a87a6442462f9c", 137406767),
            ("2022", "baf63d82df91d3c1bf1f8ec53c6747d9585a4c81e221a4e1bbb3042da64be76a", 138075558),
        )
    ),
    # ---------------------------------------------------------------- SIGIR 2016 via NCBI TrialGPT
    *(
        Source(
            name,
            "sigir",
            f"https://raw.githubusercontent.com/ncbi-nlp/TrialGPT/main/dataset/sigir/{path}",
            sha,
            size,
            "U.S. Government work, public domain notice (NCBI TrialGPT LICENSE); the SIGIR 2016 collection "
            "itself: CC BY-SA 4.0, CSIRO (https://researchdata.edu.au/a-test-collection-clinical-trials/664508)",
            "CC-BY-SA-4.0",
            "green",
            "share-alike: data adapted from the SIGIR notes carries CC BY-SA 4.0",
            "Koopman B., Zuccon G., A test collection for matching patients to clinical trials, SIGIR 2016, CSIRO, "
            "CC BY-SA 4.0; redistributed by NCBI TrialGPT (public domain notice)",
        )
        for name, path, sha, size in (
            (
                "sigir_queries.jsonl",
                "queries.jsonl",
                "97ce3172bf6f80f3a5ac81371b83c9f031eccb243004b12cb5fd0015d372aa9b",
                31247,
            ),
            (
                "sigir_qrels_test.tsv",
                "qrels/test.tsv",
                "5298efb4859cfcdfe2cae5748eb1df1d4970c383c35a87e20145d1b3c25ea8ab",
                102092,
            ),
            (
                "sigir_corpus.jsonl",
                "corpus.jsonl",
                "4b430f25e1557d188017f9a2eeac20905a32fd9862cbd74fa7e8ca6cbf6836d4",
                16420196,
            ),
        )
    ),
    Source(
        "trialgpt_criterion.parquet",
        "sigir",
        "https://huggingface.co/datasets/ncbi/TrialGPT-Criterion-Annotations/resolve/main/data/"
        "train-00000-of-00001.parquet",
        "14c547184fac9b013cd17441fd028845b40150c76b022e58334f5494077e5234",
        176088,
        "public domain notice (https://huggingface.co/datasets/ncbi/TrialGPT-Criterion-Annotations)",
        "LicenseRef-US-Public-Domain",
        "green",
        "the notes inside are SIGIR's (CC BY-SA 4.0, CSIRO)",
        "TrialGPT, NCBI, U.S. National Library of Medicine",
    ),
    # ---------------------------------------------------------------- Taiwan FDA trial list (zh-Hant)
    Source(
        "tfda_205_csv.zip",
        "tfda",
        "https://data.fda.gov.tw/data/opendata/export/205/csv",
        "83cee056621188a4efdb3532288f90af3aca050275de31654e51349575a1160e",
        44433520,
        "Open Government Data License, version 1.0 (Taiwan), any purpose (https://data.gov.tw/dataset/177198)",
        "OGDL-Taiwan-1.0",
        "green",
        TFDA_NOTE,
        "台灣藥品臨床試驗現況資料集, Taiwan Food and Drug Administration, OGDL-TW 1.0",
    ),
    # ---------------------------------------------------------------- criteria compile gold
    Source(
        "chia_without_scope.zip",
        "chia",
        "https://ndownloader.figshare.com/files/21728853",
        "723457a4eb0ad57ac352b4976d1cdfc81b96e36233906474dc9c845cdc759c7c",
        2397117,
        "CC BY 4.0 (https://api.figshare.com/v2/articles/11855817)",
        "CC-BY-4.0",
        "green",
        "",
        "Kury F. et al., Chia, Sci Data 7, 281 (2020), figshare 10.6084/m9.figshare.11855817, CC BY 4.0",
    ),
    # ---------------------------------------------------------------- notes with a gold of their own
    Source(
        "tcga_reports.csv.zip",
        "tcga",
        "https://data.mendeley.com/public-files/datasets/hyg5xkznpx/files/60abe141-9352-4a54-943c-3d015eabefea/"
        "file_downloaded",
        "bbbc0ee0c75d8feb0bb246b4fa40e8e29bba9775d4a9e4f41e0b73a7955e1c12",
        10913820,
        "CC BY 4.0 (https://data.mendeley.com/datasets/hyg5xkznpx/1)",
        "CC-BY-4.0",
        "green",
        "",
        "Kefeli J., Tatonetti N., TCGA-Reports, Mendeley Data V1, doi:10.17632/hyg5xkznpx.1, CC BY 4.0",
    ),
    Source(
        "aci_bench_2023.zip",
        "aci",
        "https://ndownloader.figshare.com/files/41498793",
        "ed5f7cf5542fe5bfe1e6021613d40bcd7450ffbff561b5afa9c2289049881612",
        1319280,
        "CC BY 4.0 (https://api.figshare.com/v2/articles/22494601)",
        "CC-BY-4.0",
        "green",
        "",
        "Yim W. et al., ACI-BENCH, Sci Data 2023, CC BY 4.0",
    ),
    Source(
        "maccrobat2020.zip",
        "maccrobat",
        "https://ndownloader.figshare.com/files/21489405",
        "a2d34ccd1a605d9147fc7368293e61dcf2090357b26f7bce6c2b3d257204acc6",
        1070089,
        "CC BY 4.0 (https://api.figshare.com/v2/articles/9764942)",
        "CC-BY-4.0",
        "green",
        "",
        "Caufield J.H. et al., MACCROBAT, figshare 10.6084/m9.figshare.9764942, CC BY 4.0",
    ),
    Source(
        "jmed_personas_01.parquet",
        "jmed",
        "https://huggingface.co/datasets/sociocom/JMED-Personas/resolve/main/data/parquet/"
        "JMED-Personas-100K_01.parquet",
        "2fe12c69adada2358ece790d3f595a4039f202806338abcc1e75711ae5382cde",
        17564136,
        "CC BY 4.0 (https://huggingface.co/datasets/sociocom/JMED-Personas card)",
        "CC-BY-4.0",
        "green",
        "synthetic patients: measures recall and the data path, never real-note accuracy",
        "JMED-Personas-100k, Social Computing Laboratory, NAIST, CC BY 4.0",
    ),
    Source(
        "opentw_medicine.parquet",
        "opentw",
        "https://huggingface.co/datasets/OpenTWBench/tw-exam-bench/resolve/main/data/medicine.parquet",
        "be7f901669b56836d7c438a88a51026917a95ecfbc91cd3f196b3db728d09efc",
        2977813,
        "Apache-2.0 (https://huggingface.co/datasets/OpenTWBench/tw-exam-bench card; source: national exam papers)",
        "Apache-2.0",
        "green",
        "one- or two-sentence exam vignettes, not charts",
        "OpenTWBench tw-exam-bench, Apache-2.0; questions from the Ministry of Examination, Taiwan",
    ),
)
BY_ID = {s.id: s for s in SOURCES}

# Looked at and not fetched: the reason, for the run plan and the owner
BLOCKED: dict[str, str] = {
    "bioscope-clinical": "the public BioScope file (https://rgai.inf.u-szeged.hu/sites/rgai.inf.u-szeged.hu/files/"
    "bioscope.zip, sha256 b20b525506f783ab9c120548ac4022ab587bf7cc419beaf759f7253f0cf0b1d1, CC BY 2.0) ships the "
    "clinical radiology part with every word masked (clinical_merger/clinical_records_anon.xml: '*'); the text must "
    "be merged from the CMC 2007 challenge files (computationalmedicine.org), whose terms are not checked",
    "trialgpt-criterion-hf": "not needed: the same 1,015 labels are committed (eval/criterion_ml/annotations.jsonl); "
    "the Hugging Face parquet is pinned only to show they agree",
}
SETS = tuple(dict.fromkeys(s.set for s in SOURCES))

# Records fetched one by one (no published file to pin): host, licence, colour, caveat
LIVE: dict[str, dict[str, str]] = {
    "ctgov": {
        "host": "clinicaltrials.gov",
        "licence": "ClinicalTrials.gov terms (register row ctgov-public-protocols)",
        "colour": "green",
        "caveat": "the current version of each record, not the TREC snapshot",
    },
    "jrct": {
        "host": "jrct.mhlw.go.jp",
        "licence": "Public Data License 1.0 (Japan; CC BY 4.0 compatible)",
        "colour": "yellow",
        "caveat": "single records only: comprehensive collection needs the jRCT helpdesk's "
        "written permission (https://jrct.mhlw.go.jp/agreement)",
    },
    "pmc": {
        "host": "eutils.ncbi.nlm.nih.gov",
        "licence": "CC BY per article (checked on each article's own licence)",
        "colour": "green",
        "caveat": "Simplified Chinese converted to Traditional by TrialBox: needs Taiwanese "
        "clinician review; not Taiwanese charts",
    },
    "gdc": {
        "host": "api.gdc.cancer.gov",
        "licence": "NCI GDC open-access clinical data (project of a TCGA case)",
        "colour": "green",
        "caveat": "used only to name each TCGA report's cancer project (the gold)",
    },
}


def set_dir(name: str, cache: Path = CACHE) -> Path:
    return cache / name


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def path_of(source_id: str, cache: Path = CACHE) -> Path:
    s = BY_ID[source_id]
    return set_dir(s.set, cache) / s.id


def fetch_one(s: Source, cache: Path = CACHE, get: Callable[[str, Path, str], None] | None = None) -> str:
    """The file at its pin: kept when it is there with the pinned sha256, else fetched (``tools.fetch_pinned``).
    Returns ``"kept"`` or ``"fetched"``; a sha256 other than the pin raises ``fetch_pinned.PinError``."""
    from tools import fetch_pinned

    out = set_dir(s.set, cache) / s.id
    if out.exists() and sha256_file(out) == s.sha256:
        return "kept"
    if get is not None:
        get(s.url, out, s.sha256)
    else:  # fetch_pinned's checks with this package's User-Agent (NIST refuses urllib's default one with 403)
        fetch_pinned.fetch(s.url, out, s.sha256, get=_get)
    return "fetched"


def record(cache: Path, set_name: str, rows: Iterable[dict[str, Any]], name: str = "FETCHED.json") -> Path:
    """``FETCHED.json`` (or ``LIVE.json``) of a set folder: merged with what is there, newest row per key wins."""
    d = set_dir(set_name, cache)
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    have: dict[str, Any] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    for r in rows:
        have[str(r.get("id") or r.get("url"))] = r
    f.write_text(json.dumps(have, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return f


def fetch(sets: Iterable[str] | None = None, cache: Path = CACHE) -> dict[str, str]:
    """Every pinned file of ``sets`` (all when None). {source id: kept|fetched}."""
    want = set(sets or SETS)
    unknown = want - set(SETS) - set(LIVE)
    if unknown:
        raise SystemExit(f"unknown set(s) {sorted(unknown)}: one of {', '.join(SETS)}")
    out: dict[str, str] = {}
    for s in SOURCES:
        if s.set not in want or not s.keep:  # a streamed corpus is read (and checked) by its set's reader
            continue
        print(f"{s.set}: {s.id} ({s.bytes / 1e6:.1f} MB) ...", file=sys.stderr)
        out[s.id] = fetch_one(s, cache)
        record(cache, s.set, [{**asdict(s), "checked": datetime.now(UTC).date().isoformat()}])
    return out


# ---------------------------------------------------------------- live records, one by one
_LAST: dict[str, float] = {}


def https_open(url: str, timeout: float) -> Any:
    """The open answer to one https GET of ``url`` with this package's User-Agent, through the configured proxy
    (``SSL_CERT_FILE`` as the CA file when set). The opener speaks https only: no ``file:``, ``ftp:`` or plain
    ``http:`` handler is in it, a redirect is followed only to https, and an answer that ended anywhere else is
    refused. Errors are urllib's (``HTTPError`` and ``URLError``, both OSErrors) or a ``ValueError`` for a scheme
    other than https."""
    import ssl
    import urllib.request

    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError(f"{url}: only https is fetched")
    ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler(),
        urllib.request.HTTPSHandler(context=ctx),
        urllib.request.HTTPRedirectHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    resp = opener.open(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout)
    if urllib.parse.urlsplit(resp.geturl()).scheme != "https":
        resp.close()
        raise ValueError(f"{url}: the answer came from {resp.geturl()}, not an https address")
    return resp


def _get(url: str, timeout: float = 120.0) -> bytes:
    """One https GET through the configured proxy (``SSL_CERT_FILE`` as the CA file when set): :func:`https_open`."""
    with https_open(url, timeout) as resp:
        data: bytes = resp.read()
    return data


def polite_get(
    url: str,
    *,
    get: Callable[[str], bytes] = _get,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    wait: float | None = None,
) -> bytes:
    """``get(url)``, after waiting so that two requests to one host are at least ``wait`` (:data:`POLITE_S`) apart.
    A 429 or a transfer fault is tried twice more, waiting four times as long each time."""
    host = urllib.parse.urlsplit(url).hostname or ""
    gap = POLITE_S if wait is None else wait
    err: Exception | None = None
    for attempt in range(3):
        last = _LAST.get(host)
        if last is not None and clock() - last < gap * 4**attempt:
            sleep(gap * 4**attempt - (clock() - last))
        _LAST[host] = clock()
        try:
            return get(url)
        except OSError as exc:  # urllib's HTTPError and URLError are OSErrors
            err = exc
            if getattr(exc, "code", None) in (400, 401, 403, 404):
                raise
    assert err is not None
    raise err


def live_record(cache: Path, kind: str, url: str, data: bytes) -> dict[str, Any]:
    row = {
        "url": url,
        "kind": kind,
        "retrieved": datetime.now(UTC).date().isoformat(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        **LIVE[kind],
    }
    return row
