"""Fetch the public reference data and build the offline pack ``trialbox-refdata-<YYYYMMDD>`` (D-140).

Each source below has a pinned URL, its licence and terms, its attribution, how often it changes, and a parser that
turns the download into the pack's records (``tb_common.refdata``: kinds ctgov, trial and term). The decision for
each source is recorded here and in DECISIONS.md D-140:

* **ship**: the vendor fetches it, builds the pack and ships it in the signed update bundle (payload kind refdata).
* **site-fetch**: the licence forbids redistribution, or the download needs the hospital's own account. The vendor
  never ships it; the hospital downloads it itself and loads it with ``site-load`` (a pack part of its own, kept
  across vendor updates).
* **not usable**: listed so nobody tries again; no fetcher.

Country modules add their items to the same registry (D-170): ``tb_common.refdata_tw`` (NHI drug -> ATC, ICD-10-CM/PCS
2014 <-> 2023, NHI lab -> LOINC, zh-TW synonyms) and ``tb_common.refdata_jp`` (D-173 to D-175: the WHO ICD-10 <->
ICD-10-CM bridge, YJ -> ATC, CTCAE v5.0, ja synonyms; MEDIS 病名, JLAC10 -> LOINC and the JCOG CTCAE translation as
site-fetch loaders). Each item has its own parser and records its version and sha256; an item with a licence reader
has its licence read at the source when it is fetched.

    python tools/refdata_fetch.py sources                                  # the table (markdown)
    python tools/refdata_fetch.py fetch --raw .cache/refdata/raw tfda_trials mhlw_yakka icd10cm
    python tools/refdata_fetch.py fetch --raw .cache/refdata/raw nhi_drug_atc tw_icd_2014_2023 nhi_lab_loinc \
        naer_medical_terms tw_zh_synonyms                                  # the Taiwan items (D-170 to D-172)
    python tools/refdata_fetch.py fetch --raw .cache/refdata/raw icd10cm icd10_who_cm_bridge jp_yj_atc ctcae_v5_en \
        ja_synonyms                                                        # the Japan items (D-173 to D-175)
    python tools/refdata_fetch.py fetch --raw .cache/refdata/raw ctgov --slice 200   # one API page, JP/TW sites
    python tools/refdata_fetch.py fetch --raw .cache/refdata/raw loinc --file Loinc_2.81.zip   # account download
    python tools/refdata_fetch.py build --raw .cache/refdata/raw --out dist/   # dist/trialbox-refdata-<date>.tar
    python tools/refdata_fetch.py sample --out /tmp/pack                             # the committed samples, no network
    python tools/refdata_fetch.py site-load umin_ctr --file ctr_data_j.csv.gz        # at the hospital, its own download
    python tools/refdata_fetch.py site-load medis_byomei_icd10 --file NMAIN.TXT --columns 病名交換用コード,...

The full ClinicalTrials.gov download (API v2 bulk JSON zip) was about 2.8 GB for 610,756 studies on 2026-11-06
(10.6 GB unpacked); the pack keeps every record unchanged, gzip'd as JSON lines (about 2.2 GB). Fetch it outside the
repository (``--raw`` under ``.cache``). Standard library plus httpx and openpyxl.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import shutil
import sys
import tarfile
import zipfile
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "libs", ROOT / "services"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tb_common import refdata as rd  # noqa: E402
from tb_common import refdata_jp as jp  # noqa: E402
from tb_common import refdata_tw as tw  # noqa: E402

SAMPLES = ROOT / "tests" / "fixtures" / "refdata"
OGDL, OGDL_URL = tw.OGDL, tw.OGDL_URL
NLM_TERMS = (
    "ClinicalTrials.gov data are provided by the U.S. National Library of Medicine (NLM) and may be used and "
    "redistributed; NLM asks users to state the source and the date of download, to say what was changed, and not to "
    "imply NLM endorsement. Some records may include material whose copyright stays with the sponsor. The records "
    "are not changed in the pack (only gzip'd as JSON lines)."
)
NLM_DISCLAIMER = (
    "ClinicalTrials.gov is a service of the U.S. National Library of Medicine. The information is provided by study "
    "sponsors and investigators, who are responsible for its accuracy; listing a study does not mean it has been "
    "evaluated by the U.S. Federal Government. This copy was downloaded on {date} and may not be current: check "
    "ClinicalTrials.gov before acting on it. NLM does not endorse TrialBox."
)


# One registry of items (D-170): the sources below plus the country modules' items (tb_common.refdata_tw).
Source = rd.Item


SOURCES: tuple[Source, ...] = (
    Source(
        "ctgov", "ClinicalTrials.gov, all studies (API v2 bulk download)", "ctgov", "ship",
        "https://clinicaltrials.gov/api/v2/studies/download?format=json.zip",
        "NLM terms and conditions (U.S. public registry data)",
        "https://clinicaltrials.gov/about-site/terms-conditions", NLM_TERMS,
        "Data from ClinicalTrials.gov, U.S. National Library of Medicine. " + NLM_DISCLAIMER,
        "daily at the source; monthly in the pack",
        "about 2.8 GB zip, 10.6 GB unpacked, 610,756 studies (2026-11-06); about 2.2 GB in the pack",
        "Chosen over AACT: the same API v2 record the box already reads (live mode, registry mirror), no relational "
        "join of 40+ pipe files to rebuild a record, published by NLM itself.",
        "ctg-studies.json.zip",
    ),
    Source(
        "tfda_trials", "TFDA drug clinical trials (data.gov.tw 177198)", "trial", "ship",
        "https://data.fda.gov.tw/data/opendata/export/205/csv", OGDL, OGDL_URL,
        "Free use, reuse and redistribution, commercial included, with attribution of the provider.",
        "台灣藥品臨床試驗現況資料集, Taiwan Food and Drug Administration (衛生福利部食品藥物管理署), via data.gov.tw "
        "(dataset 177198), Open Government Data License 1.0.",
        "monthly", "about 44 MB zip, 5,983 trials (2026-11-09)",
        "The file has no 執行狀態 column although the metadata lists one: status is unknown in the pack.",
        "205.csv.zip",
    ),
    Source(
        "tfda_indication", "TFDA trial indications with ICD codes (data.gov.tw 177212)", "term", "ship",
        "https://data.fda.gov.tw/data/opendata/export/206/csv", OGDL, OGDL_URL,
        "Free use, reuse and redistribution, commercial included, with attribution of the provider.",
        "台灣藥品臨床試驗現況之宣稱適應症 (ICD9編號) 資料集, Taiwan FDA, via data.gov.tw (dataset 177212), Open "
        "Government Data License 1.0.",
        "monthly", "about 0.4 MB zip, 19,234 rows",
        "Metadata is wrong: no trial key, the ICD9 description columns are empty in 73 % of rows and about 1,800 "
        "codes are ICD-10 shaped. Kept as an indication-text -> code lookup and joined to tfda_trials by the "
        "indication text.",
        "206.csv.zip",
    ),
    Source(
        "mhlw_yakka", "MHLW 薬価基準収載品目リスト (内用薬, 注射薬, 外用薬, 歯科用薬剤)", "term", "ship",
        "https://www.mhlw.go.jp/topics/2026/04/tp20260401-01.html",
        "Public Data License 1.0 (PDL1.0), MHLW website terms",
        "https://www.digital.go.jp/resources/open_data/public_data_license_v1.0",
        "Free use and redistribution with the source stated and edits marked.",
        "出典：厚生労働省「薬価基準収載品目リスト及び後発医薬品に関する情報について」(加工して作成)",
        "monthly (with each listing)", "about 1.3 MB xlsx, about 13,000 items",
        "The list gives the 12-character 薬価基準収載医薬品コード; a YJ code that differs from it still needs the "
        "licensed YJ file of step 7 (D-137).",
        "yakka.xlsx",
    ),
    Source(
        "nhi_drugs", "NHI drug items 健保用藥品項查詢項目檔 (data.gov.tw 23715)", "term", "ship",
        "https://info.nhi.gov.tw/api/iode0000s01/Dataset?rId=A21030000I-E41001-001", OGDL, OGDL_URL,
        "Free use, reuse and redistribution, commercial included, with attribution of the provider.",
        "健保用藥品項查詢項目檔, National Health Insurance Administration (衛生福利部中央健康保險署), via data.gov.tw "
        "(dataset 23715), Open Government Data License 1.0.",
        "monthly", "about 90 MB CSV, one row per code and validity period",
        filename="nhi_drugs.csv",
    ),
    Source(
        "icd10cm", "ICD-10-CM code descriptions FY2027 (CDC NCHS)", "term", "ship",
        "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/ICD10CM/2027/icd10cm-code-descriptions-2027.zip",
        "Public domain (U.S. government work)", "https://www.cdc.gov/nchs/icd/icd-10-cm/",
        "No restriction.", "ICD-10-CM, National Center for Health Statistics, CDC (FY2027).",
        "yearly (October 1) and April addenda", "2.2 MB zip, about 74,000 codes",
        filename="icd10cm-code-descriptions-2027.zip",
    ),
    Source(
        "tw_icd10_zh", "Taiwan ICD-10-CM/PCS 2023 Chinese edition (NHIA)", "term", "ship",
        "https://www.nhi.gov.tw/ch/cp-13108-67ddf-2508-1.html", OGDL, OGDL_URL,
        "Government open data; free use with attribution of the provider.",
        "2023年中文版ICD-10-CM/PCS, 衛生福利部中央健康保險署, Open Government Data License 1.0.",
        "with each Taiwan edition (years)", "about 10 MB xlsx",
        "www.nhi.gov.tw answered 403 from here: the vendor downloads the workbook and passes --file.",
        "tw_icd10.xlsx", fetch=False,
    ),
    Source(
        "loinc", "LOINC table (Regenstrief)", "term", "ship",
        "https://loinc.org/downloads/", "LOINC licence (Regenstrief Institute)", "https://loinc.org/license/",
        "Redistribution in a product is allowed with the LOINC copyright notice, the licence text and the version; "
        "the content may not be changed. The download needs a free loinc.org account, so the vendor downloads it "
        "and passes --file.",
        "This material contains content from LOINC (http://loinc.org). LOINC is copyright © Regenstrief Institute, "
        "Inc. and the Logical Observation Identifiers Names and Codes (LOINC) Committee and is available at no cost "
        "under the license at http://loinc.org/license. LOINC® is a registered United States trademark of "
        "Regenstrief Institute, Inc.",
        "twice a year", "about 80 MB zip, about 100,000 terms",
        "loinc.org answered 403 from here; licence reading from the parallel licence review (2026-11-09).",
        "Loinc.zip", fetch=False,
    ),
    Source(
        "umin_ctr", "UMIN-CTR daily snapshot", "trial", "site-fetch",
        "https://upload.umin.ac.jp/ctr_csv/ctr_data_j.csv.gz", "UMIN-CTR terms and conditions",
        "https://www.umin.ac.jp/ctr/csvdata.html",
        "No use for marketing, promotional or commercial purposes; the dataset may not be redistributed, and "
        "software may not download it on the user's behalf (UMIN FAQ). Show the date UMIN processed it, keep it "
        "current, attribute UMIN-CTR.",
        "Data from UMIN-CTR (University hospital Medical Information Network), downloaded by the hospital.",
        "daily at the source", "about 30 MB gz",
        "Never bundled and never fetched by TrialBox: the hospital logs in with its own UMIN ID, downloads the file, "
        "and runs site-load.",
        "ctr_data_j.csv.gz", fetch=False,
    ),
    Source(
        "jrct", "jRCT (Japan Registry of Clinical Trials)", "trial", "site-fetch",
        "https://jrct.mhlw.go.jp/", "jRCT terms of use", "https://jrct.mhlw.go.jp/",
        "No bulk download or public API; bulk use needs the jRCT help desk's permission (asked, pending).",
        "jRCT, Ministry of Health, Labour and Welfare.", "-", "-",
        "Pending the help desk's answer; JAPIC-CTI and JMACCT were merged into jRCT on 2023-03-06.", fetch=False,
    ),
    Source(
        "who_ictrp", "WHO ICTRP", "trial", "not usable", "https://trialsearch.who.int/",
        "WHO ICTRP terms", "https://www.who.int/clinical-trials-registry-platform", "No commercial use.",
        "-", "-", "-", fetch=False,
    ),
    Source(
        "japic_cti", "JAPIC-CTI / JMACCT", "trial", "not usable", "https://www.japic.or.jp/",
        "-", "-", "Merged into jRCT on 2023-03-06; no separate registry to fetch.", "-", "-", "-", fetch=False,
    ),
    Source(
        "tfda_sites", "TFDA trial sites, drugs and ingredients (data.gov.tw 177215, 177216, 177218)", "trial",
        "not usable", "https://data.fda.gov.tw/data/opendata/export/207/csv", OGDL, OGDL_URL,
        "Open data, but no column links a row to a trial (no protocol number or 收文號); the sites file carries "
        "investigators' names; in 177218 the dose column holds units and the unit column is mostly empty.",
        "-", "monthly", "4.9 MB, 0.2 MB, 0.4 MB zips", fetch=False,
    ),
    *tw.ITEMS,  # D-170 to D-172: the Taiwan maps and synonyms
    *jp.ITEMS,  # D-173 to D-175: the Japan maps, CTCAE and synonyms (MEDIS, JLAC10, JCOG: site-fetch loaders)
)  # fmt: skip
BY_ID = {s.id: s for s in SOURCES}


# ------------------------------------------------------------------------------------------------ download
def download(url: str, dest: Path, attempts: int = 3, timeout: float = 600) -> dict[str, Any]:
    """Stream ``url`` to ``dest`` (sha256 on the way); a cut-off transfer is retried and never kept."""
    import httpx

    dest.parent.mkdir(parents=True, exist_ok=True)
    last = ""
    for _ in range(attempts):
        part = dest.with_suffix(dest.suffix + ".part")
        h = hashlib.sha256()
        n = 0
        try:
            with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as r, part.open("wb") as fh:
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code}")
                want = int(r.headers.get("content-length") or 0)
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
                    h.update(chunk)
                    n += len(chunk)
            if want and n != want:
                raise RuntimeError(f"cut off at {n} of {want} bytes")
            if dest.suffix == ".zip" and not zipfile.is_zipfile(part):
                raise RuntimeError(f"cut off at {n} bytes (not a whole zip)")
            part.replace(dest)
            return {"url": url, "downloaded_at": _now(), "sha256": h.hexdigest(), "bytes": n}
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            part.unlink(missing_ok=True)
    raise RuntimeError(f"{url}: {last} (after {attempts} tries)")


def local_file(path: Path, dest: Path, url: str) -> dict[str, Any]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = path.read_bytes()
    dest.write_bytes(data)
    return {"url": url, "downloaded_at": _now(), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "file": path.name}  # fmt: skip


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def ctgov_slice(dest: Path, n: int, countries: tuple[str, ...] = ("Japan", "Taiwan")) -> dict[str, Any]:
    """A small slice for tests and checks: the first ``n`` studies with a site in the countries (one API page)."""
    import httpx

    url = "https://clinicaltrials.gov/api/v2/studies"
    params: dict[str, str | int] = {"query.locn": " OR ".join(countries), "pageSize": min(n, 1000), "format": "json"}
    r = httpx.get(url, params=params, timeout=120)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return {"url": str(r.url), "downloaded_at": _now(), "sha256": hashlib.sha256(r.content).hexdigest(),
            "bytes": len(r.content), "slice": n}  # fmt: skip


MHLW_XLSX = re.compile(r'href="(/topics/\d{4}/\d{2}/xls/tp\d{8}-01_0([1-4])\.xlsx)"')


def fetch_mhlw(dest: Path) -> dict[str, Any]:
    """The index page, then the newest workbook of each of the four lists (01 内用薬, 02 注射薬, 03 外用薬,
    04 歯科用薬剤: the page lists the newest first). The download's sha256 is over the four files' sha256s."""
    import httpx

    index = BY_ID["mhlw_yakka"].url
    r = httpx.get(index, timeout=60)
    r.raise_for_status()
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "index.html").write_bytes(r.content)
    page = r.content.decode("shift_jis", errors="replace")
    newest: dict[str, str] = {}
    for m in MHLW_XLSX.finditer(page):
        newest.setdefault(m.group(2), m.group(1))
    if set(newest) != {"1", "2", "3", "4"}:
        raise RuntimeError(f"{index}: expected the four list workbooks, found {sorted(newest)}")
    parts = []
    for k in sorted(newest):
        meta = download("https://www.mhlw.go.jp" + newest[k], dest / f"yakka_0{k}.xlsx", timeout=120)
        parts.append({**meta, "path": f"yakka_0{k}.xlsx"})
    return _joined(index, parts) | {"workbooks": [p["url"] for p in parts]}


def _joined(url: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
    """A download of several files: each part's path, URL, sha256 and bytes, and one sha256 over the parts' sha256s
    in order (the manifest lists the parts; the page shows each part's own sha256)."""
    joined = "".join(p["sha256"] for p in parts)
    return {"url": url, "downloaded_at": _now(), "sha256": hashlib.sha256(joined.encode()).hexdigest(),
            "bytes": sum(int(p["bytes"]) for p in parts),
            "parts": [{k: p[k] for k in ("path", "url", "sha256", "bytes")} for p in parts]}  # fmt: skip


# A licence read at the source is the item's own reader (Item.licence_reader, D-173): the data.gov.tw dataset API
# for the Taiwan items (tb_common.refdata_tw.datagov_tw_licence), a licence page for others.


def fetch_parts(s: Source, dest: Path, file: Path | None) -> dict[str, Any]:
    """An item of several files (``extra_files``): the main file, then each further file beside it. The download's
    sha256 is over the files' sha256s in order (as for the MHLW workbooks)."""
    first = local_file(file, dest, s.url) if file is not None else download(s.url, dest)
    parts = [{**first, "path": dest.name}]
    for name, url in s.extra_files:
        parts.append({**download(url, dest.parent / name), "path": name})
    return _joined(s.url, parts)


def fetch(
    ids: list[str], raw: Path, file: Path | None = None, slice_n: int = 0, licence_check: bool = True
) -> list[str]:
    """Download each item into ``raw/<id>/`` with ``fetch.json`` (URL, date, sha256, bytes, version). The only
    place that reaches the network: the box reads the built pack from the update bundle."""
    done = []
    for sid in dict.fromkeys(BY_ID[i].derived_from or i for i in ids):  # a derived item reads its parent's file
        s = BY_ID[sid]
        if s.distribution != "ship":
            raise SystemExit(f"{sid} is {s.distribution}: {s.note or s.terms}")
        dest = raw / sid / (s.filename or f"{sid}.bin")
        if s.url.startswith("repo:"):
            meta = local_file(ROOT / s.url.removeprefix("repo:"), dest, s.url)
        elif s.extra_files:
            meta = fetch_parts(s, dest, file)
        elif sid == "ctgov" and slice_n:
            dest = raw / sid / "slice.json"
            meta = ctgov_slice(dest, slice_n)
        elif file is not None:
            meta = local_file(file, dest, s.url)
        elif not s.fetch:
            raise SystemExit(f"{sid}: no automatic download ({s.note or s.terms}); pass --file")
        elif sid == "mhlw_yakka":
            meta = fetch_mhlw(raw / sid)
            dest = raw / sid / "index.html"
        else:
            meta = download(s.url, dest)
        meta.setdefault("parts", [{"path": dest.name, "url": meta["url"], "sha256": meta["sha256"],
                                   "bytes": meta["bytes"]}])  # fmt: skip
        if s.sha256 and meta["parts"][0]["sha256"] != s.sha256:
            raise SystemExit(
                f"{sid}: {s.url} is pinned to sha256 {s.sha256}, the download is "
                f"{meta['parts'][0]['sha256']}: the published file changed, check it before shipping"
            )
        for item in (s, *(c for c in SOURCES if c.derived_from == sid)):
            dm = read_licence(item, licence_check)
            if dm is None:
                continue
            if item is s:
                meta.update({"version": dm.get("version", ""), "licence_check": dm})
            else:
                meta.setdefault("versions", {})[item.id] = dm.get("version", "")
                meta.setdefault("licence_checks", {})[item.id] = dm
        (raw / sid / "fetch.json").write_text(json.dumps({**meta, "path": dest.name}, indent=1), encoding="utf-8")
        done.append(f"{sid}: {meta['bytes']:,} bytes, sha256 {meta['sha256'][:16]}")
    return done


def read_licence(item: Source, licence_check: bool = True) -> dict[str, Any] | None:
    """The item's own licence reader (``Item.licence_reader``, D-173), run at fetch time: its evidence for
    ``fetch.json``, or None for an item without one. Stops when the source does not answer or the licence no longer
    reads as expected; ``licence_check=False`` (``--no-licence-check``) skips the read and records that."""
    if item.licence_reader is None:
        if item.meta_url:
            raise SystemExit(
                f"{item.id}: has a dataset API URL ({item.meta_url}) but no licence reader: add one before fetching"
            )
        return None
    if not licence_check:
        return {"skipped": "--no-licence-check"}
    got = item.licence_reader(item)
    if got is None:
        raise SystemExit(
            f"{item.id}: the licence could not be read at the source (it did not answer); retry, or pass "
            "--no-licence-check after reading the terms by hand"
        )
    if not got.ok:
        raise SystemExit(
            f"{item.id}: the licence now reads {got.read!r} at {got.url}, not {got.expected!r}: read the terms "
            "before shipping"
        )
    return got.evidence()


# ------------------------------------------------------------------------------------------------ parsers
_csv_rows = rd.csv_rows


def _unzip_one(path: Path, suffix: str = ".csv") -> bytes:
    if not zipfile.is_zipfile(path):
        return path.read_bytes()
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(suffix)]
        if not names:
            raise ValueError(f"{path.name}: no {suffix} inside")
        return z.read(names[0])


def parse_ctgov(path: Path) -> Iterator[dict[str, Any]]:
    """The bulk zip (one ``NCTxxxxxxxx.json`` per study), an API page ``{"studies": [...]}`` or a cached record."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for name in sorted(n for n in z.namelist() if n.endswith(".json")):
                study = json.loads(z.read(name))
                yield {"nct_id": study["protocolSection"]["identificationModule"]["nctId"], "study": study}
        return
    doc = json.loads(path.read_text(encoding="utf-8"))
    studies: list[Any] = doc["studies"] if isinstance(doc, dict) and "studies" in doc else [doc.get("study", doc)]
    for study in studies:
        yield {"nct_id": study["protocolSection"]["identificationModule"]["nctId"], "study": study}


def _tw_date(s: str) -> str:
    m = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s or "")
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


_roc = tw.roc


def parse_tfda_indication(path: Path) -> Iterator[dict[str, Any]]:
    """One term per distinct indication text, with every code the file gives for it (ICD-9 or ICD-10 shaped)."""
    by_text: dict[str, dict[str, Any]] = {}
    for r in _csv_rows(_unzip_one(path)):
        text = r.get("適應症中文", "")
        if not text:
            continue
        t = by_text.setdefault(text, {"codes": [], "descriptions": []})
        code = r.get("ICD9_NO", "")
        if code and code not in t["codes"]:
            t["codes"].append(code)
        desc = r.get("ICD9_英文說明") or r.get("ICD9_中文說明")
        if desc and desc not in t["descriptions"]:
            t["descriptions"].append(desc)
    for text, t in sorted(by_text.items()):
        code = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        yield {"system": "urn:trialbox:tfda-indication", "code": code, "display": text, "extra": t}


def parse_tfda_trials(path: Path, indications: dict[str, list[str]] | None = None) -> Iterator[dict[str, Any]]:
    seen: set[str] = set()
    for r in _csv_rows(_unzip_one(path)):
        tid = r.get("TFDA收文號") or r.get("臨床試驗計畫書編號")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        ind = r.get("適應症中文", "")
        yield {
            "registry": "TFDA",
            "trial_id": tid,
            "protocol_no": r.get("臨床試驗計畫書編號", ""),
            "title": r.get("臨床試驗計畫中文名稱", ""),
            "status": r.get("執行狀態", ""),  # not in the 2026-11 file although the metadata lists it
            "phase": r.get("臨床試驗期別", ""),
            "sponsor": r.get("臨床試驗申請者", ""),
            "conditions": [ind] if ind else [],
            "countries": ["Taiwan"],
            "inclusion": r.get("納入條件", ""),
            "exclusion": r.get("排除條件", ""),
            "start": _tw_date(r.get("試驗預計執行期間起", "")),
            "end": _tw_date(r.get("試驗預計執行期間迄", "")),
            "updated": _tw_date(r.get("資料更新時間", "")),
            "codes": (indications or {}).get(ind, []),
            "record": r,
        }


def parse_mhlw_yakka(paths: list[Path]) -> Iterator[dict[str, Any]]:
    """The 薬価基準収載品目リスト workbooks: header row with 薬価基準収載医薬品コード, 成分名, 規格, 品名, 薬価."""
    import openpyxl

    seen: set[str] = set()
    for path in paths:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            head: list[str] = []
            for row in ws.iter_rows(values_only=True):
                cells = ["" if c is None else str(c).strip() for c in row]
                if not head:
                    if "薬価基準収載医薬品コード" in cells:
                        head = cells
                    continue
                r = dict(zip(head, cells, strict=False))
                code = r.get("薬価基準収載医薬品コード", "")
                if not re.match(r"^[0-9A-Z]{12}$", code) or code in seen:
                    continue
                seen.add(code)
                extra = {k: r.get(k, "") for k in ("区分", "成分名", "規格", "メーカー名", "先発医薬品", "薬価",
                                                     "経過措置による使用期限")}  # fmt: skip
                extra["generic_addable"] = r.get("診療報酬において加算等の算定対象となる後発医薬品", "")
                yield {"system": "urn:mhlw:yakka-kijun", "code": code, "display": r.get("品名", ""), "extra": extra}
        wb.close()


def parse_nhi_drugs(path: Path) -> Iterator[dict[str, Any]]:
    """One term per 藥品代號: the row with the latest 有效起日 (the file has one row per validity period)."""
    for code, r in sorted(tw.latest_nhi_rows(path).items()):
        extra = {k: r.get(k, "") for k in ("藥品英文名稱", "成分", "規格量", "規格單位", "單複方", "支付價",
                                            "有效起日", "有效迄日", "劑型", "ATC代碼", "藥品分類")}  # fmt: skip
        yield {"system": "urn:tw:nhi:drug", "code": code, "display": r.get("藥品中文名稱", ""), "extra": extra}


def parse_icd10cm(path: Path) -> Iterator[dict[str, Any]]:
    """``icd10cm-codes-<year>.txt``: the code (no dot), spaces, the description. The dot goes after 3 places."""
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if re.search(r"icd10cm-codes-\d{4}\.txt$", n))
        text = z.read(name).decode("utf-8", errors="replace")
    for line in text.splitlines():
        m = re.match(r"^([A-Z][0-9][0-9A-Z]{1,5})\s+(.+)$", line.strip())
        if m:
            c = m.group(1)
            yield {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": c[:3] + ("." + c[3:] if len(c) > 3 else ""),
                   "display": m.group(2).strip(), "extra": {}}  # fmt: skip


def parse_loinc(path: Path) -> Iterator[dict[str, Any]]:
    """``LoincTableCore.csv`` (or ``Loinc.csv``) inside the release zip, or the CSV itself."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.endswith(("LoincTableCore.csv", "/Loinc.csv", "Loinc.csv")))
            data = z.read(name)
    else:
        data = path.read_bytes()
    for r in _csv_rows(data):
        if r.get("LOINC_NUM"):
            extra = {k: r.get(k, "") for k in ("COMPONENT", "PROPERTY", "SYSTEM", "SCALE_TYP", "CLASS", "STATUS")}
            yield {"system": "http://loinc.org", "code": r["LOINC_NUM"],
                   "display": r.get("LONG_COMMON_NAME", ""), "extra": extra}  # fmt: skip


def parse_tw_icd10_zh(path: Path) -> Iterator[dict[str, Any]]:
    """The NHIA workbook: columns found by header (a code column with ICD in its name, 英文 and 中文 names)."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        cols: dict[str, int] = {}
        pcs = "PCS" in ws.title.upper()
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c).strip() for c in row]
            if not cols:
                for i, h in enumerate(cells):
                    if "ICD" in h.upper() and "code" not in cols and ("碼" in h or "CODE" in h.upper()):
                        cols["code"] = i
                    elif "英文" in h and "en" not in cols:
                        cols["en"] = i
                    elif "中文" in h and "zh" not in cols:
                        cols["zh"] = i
                if not {"code", "zh"} <= set(cols):
                    cols = {}
                continue
            code = cells[cols["code"]] if cols["code"] < len(cells) else ""
            if not code:
                continue
            system = "urn:tw:nhi:icd-10-pcs-2023" if pcs else "urn:tw:nhi:icd-10-cm-2023"
            yield {"system": system, "code": code, "display": cells[cols["zh"]],
                   "extra": {"en": cells[cols["en"]] if "en" in cols else ""}}  # fmt: skip
    wb.close()


# UMIN-CTR column names, matched by alias (the hospital's download; check them against a real file at the first site)
UMIN_COLS = {
    "id": ("試験ID", "UMIN試験ID", "Unique ID issued by UMIN", "UMIN ID"),
    "title": ("一般向け試験名", "試験名", "Public title", "Official scientific title"),
    "condition": ("対象疾患名", "Condition"),
    "status": ("試験進捗状況", "Recruitment status"),
    "updated": ("最終更新日", "Last modified on"),
}


def parse_umin(path: Path) -> Iterator[dict[str, Any]]:
    data = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else _unzip_one(path)
    for r in _csv_rows(data):
        got = {k: next((r[a] for a in aliases if r.get(a)), "") for k, aliases in UMIN_COLS.items()}
        if not got["id"]:
            continue
        yield {"registry": "UMIN-CTR", "trial_id": got["id"], "title": got["title"], "status": got["status"],
               "conditions": [got["condition"]] if got["condition"] else [], "countries": ["Japan"],
               "updated": got["updated"], "codes": [], "record": r}  # fmt: skip


# ------------------------------------------------------------------------------------------------ build
def _meta(raw: Path, sid: str) -> tuple[dict[str, Any], Path]:
    src = BY_ID[sid].derived_from or sid
    f = raw / src / "fetch.json"
    meta = json.loads(f.read_text(encoding="utf-8"))
    if src != sid:
        meta = {**meta, "version": (meta.get("versions") or {}).get(sid) or meta.get("version", "")}
    return meta, raw / src / meta["path"]


def check_raw(raw: Path, sid: str, meta: dict[str, Any], pinned: bool = True) -> list[dict[str, Any]]:
    """Every part of a fetched item re-hashed and compared with fetch.json; every ``extra_files`` member present; a
    version-pinned URL's file equal to its pin. Returns the parts (path, url, sha256, bytes) for the manifest. A
    raw file changed or lost after the fetch never builds into a pack with the old hash."""
    s = BY_ID[sid]
    src = s.derived_from or sid
    parts = meta.get("parts") or [{"path": meta["path"], "url": meta.get("url") or s.url, "sha256": meta["sha256"],
                                   "bytes": meta.get("bytes", 0)}]  # fmt: skip
    have = {p["path"] for p in parts}
    missing = [name for name, _ in BY_ID[src].extra_files if name not in have]
    if missing:
        raise SystemExit(f"{src}: {', '.join(missing)} missing from the fetch (fetch {src} again)")
    for p in parts:
        f = raw / src / p["path"]
        if not f.is_file():
            raise SystemExit(f"{src}: {p['path']} is missing (fetch {src} again)")
        got = rd.sha256_file(f)
        if got != p["sha256"]:
            raise SystemExit(
                f"{src}: {p['path']} has sha256 {got}, fetch.json says {p['sha256']}: the raw file "
                "changed after the fetch"
            )
    if len(parts) == 1 and meta.get("sha256") != parts[0]["sha256"]:
        raise SystemExit(f"{src}: fetch.json's sha256 does not match its file")
    if pinned and BY_ID[src].sha256 and parts[0]["sha256"] != BY_ID[src].sha256:
        raise SystemExit(f"{src}: pinned to sha256 {BY_ID[src].sha256}, the file is {parts[0]['sha256']}")
    return [{"file": p["path"], "url": p["url"], "sha256": p["sha256"], "bytes": int(p.get("bytes") or 0)}
            for p in parts]  # fmt: skip


def _version(s: Source, meta: dict[str, Any], path: Path) -> str:
    """The item's version (D-170): stated in the file (``version_of``), the dataset's modified date read at fetch
    time, a fixed version, or else the download date (a daily list's only version)."""
    if s.distribution == "site-fetch" and meta.get("version"):
        return str(meta["version"])  # the release the hospital named at site-load
    if s.version_of is not None:
        return s.version_of(path)
    return str(meta.get("version") or s.version or f"downloaded {str(meta['downloaded_at'])[:10]}")


def _entry(s: Source, meta: dict[str, Any], files: list[dict[str, Any]], path: Path,
           parts: list[dict[str, Any]]) -> dict[str, Any]:  # fmt: skip
    downloaded = str(meta["downloaded_at"])[:10]
    return {
        "id": s.id, "name": s.name, "kind": s.kind, "url": meta.get("url") or s.url,
        "downloaded_at": meta["downloaded_at"], "download_sha256": meta["sha256"], "version": _version(s, meta, path),
        "records": sum(int(f["records"]) for f in files), "licence": s.licence, "licence_url": s.licence_url,
        "terms": s.terms, "attribution": s.attribution.replace("{date}", downloaded), "refresh": s.refresh,
        "distribution": s.distribution, "files": files, "parts": parts,
        **({"slice": meta["slice"]} if meta.get("slice") else {}),
        **({"country": s.country} if s.country else {}), **({"decision": s.decision} if s.decision else {}),
    }  # fmt: skip


Writer = Callable[[str, Iterable[dict[str, Any]]], dict[str, Any]]


def build(raw: Path, out: Path, day: str | None = None, ids: list[str] | None = None, sample: bool = False,
          suffix: str = "", site: bool = False) -> Path:  # fmt: skip
    """Parse every fetched source under ``raw`` into ``out/trialbox-refdata-<day>[-suffix]/`` and its ``.tar``.

    A vendor build (the default) builds ``ship`` items only: a site-fetch item's file (the hospital's MEDIS or
    UMIN download, left under ``raw`` by ``site-load``) is never put into a pack that ships; naming one in ``ids``
    is refused. ``site=True`` (``site_load`` only) builds the hospital's own part from site-fetch items only."""
    want = "site-fetch" if site else "ship"
    if ids:
        wrong = [i for i in ids if BY_ID[i].distribution != want]
        if wrong:
            raise SystemExit(
                f"{', '.join(wrong)}: not {want} items; a "
                + (
                    "site build takes site-fetch items only"
                    if site
                    else "vendor build never packs a site-fetch or unusable item (the hospital runs site-load)"
                )
            )
    ids = ids or [s.id for s in SOURCES if s.distribution == want
                  and (raw / (s.derived_from or s.id) / "fetch.json").is_file()]  # fmt: skip
    day = day or date.today().strftime("%Y%m%d")
    pack = out / (f"trialbox-refdata-{day}" + (f"-{suffix}" if suffix else ""))
    pack.mkdir(parents=True, exist_ok=True)
    entries = []

    def write(rel: str, recs: Iterable[dict[str, Any]]) -> dict[str, Any]:
        n = rd.write_jsonl_gz(pack / rel, rd.check_records({"id": s.id, "kind": s.kind}, recs))
        if n == 0:
            raise SystemExit(f"{s.id}: 0 records from the parser (the source changed shape?): not built")
        return rd.file_entry(pack, rel, n)

    indications: dict[str, list[str]] = {}
    for sid in sorted(ids, key=lambda x: x != "tfda_indication"):  # the indication codes first: tfda_trials uses them
        s = BY_ID[sid]
        meta, path = _meta(raw, sid)
        parts = check_raw(raw, sid, meta, pinned=not sample)
        if sid == "ctgov":
            files = [write("ctgov/studies.jsonl.gz", parse_ctgov(path))]
        elif sid == "tfda_indication":
            terms = list(parse_tfda_indication(path))
            indications = {t["display"]: t["extra"]["codes"] for t in terms}
            files = [write("tfda_indication/terms.jsonl.gz", terms)]
        elif sid == "tfda_trials":
            files = [write("tfda_trials/trials.jsonl.gz", parse_tfda_trials(path, indications))]
        elif sid == "mhlw_yakka":
            books = sorted((raw / sid).glob("*.xlsx"))
            files = [write("mhlw_yakka/terms.jsonl.gz", parse_mhlw_yakka(books))]
        elif s.parse is not None:
            files = [write(f"{sid}/{KIND_FILE[s.kind]}.jsonl.gz", s.parse(path))]
        elif sid in PARSERS:
            files = [write(f"{sid}/{'trials' if s.kind == 'trial' else 'terms'}.jsonl.gz", PARSERS[sid](path))]
        else:
            raise SystemExit(f"{sid}: no parser")
        entries.append(_entry(s, meta, files, path, parts))
    as_of = max(str(e["downloaded_at"])[:10] for e in entries)
    rd.write_manifest(pack, as_of, entries, sample=sample)
    rd.verify(pack)
    return rd.pack_tar(pack, out / f"{pack.name}.tar")


KIND_FILE = {"ctgov": "studies", "trial": "trials", "term": "terms", "map": "map", "synonym": "synonyms"}
PARSERS: dict[str, Callable[[Path], Iterator[dict[str, Any]]]] = {
    "nhi_drugs": parse_nhi_drugs,
    "icd10cm": parse_icd10cm,
    "loinc": parse_loinc,
    "tw_icd10_zh": parse_tw_icd10_zh,
    "umin_ctr": parse_umin,
}


def sample_raw(raw: Path) -> Path:
    """The committed samples laid out as a fetch would leave them (no network): the four synthetic CT.gov trials of
    the cassettes plus two real records already in the fixtures, and tiny TFDA, MHLW, NHI and ICD-10-CM excerpts."""
    import openpyxl

    stamp = {"downloaded_at": "2026-11-09T00:00:00+00:00"}

    def put(sid: str, name: str, data: bytes, url: str) -> None:
        (raw / sid).mkdir(parents=True, exist_ok=True)
        (raw / sid / name).write_bytes(data)
        meta = {**stamp, "url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "path": name}
        (raw / sid / "fetch.json").write_text(json.dumps(meta), encoding="utf-8")

    studies = []
    for f in sorted((ROOT / "services/criteria_compiler/cassettes/ctgov").glob("*.json")):
        studies += json.loads(f.read_text(encoding="utf-8"))["studies"]
    for f in sorted((ROOT / "tests/fixtures/open_data").glob("ctgov_NCT*.json")):
        studies.append(json.loads(f.read_text(encoding="utf-8"))["study"])
    put("ctgov", "sample.json", json.dumps({"studies": studies}).encode(), BY_ID["ctgov"].url)
    for sid, name in (("tfda_trials", "tfda_trials_sample.csv"), ("tfda_indication", "tfda_indication_sample.csv"),
                      ("nhi_drugs", "nhi_drugs_sample.csv")):  # fmt: skip
        put(sid, name, (SAMPLES / name).read_bytes(), BY_ID[sid].url)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "icd10cm-code-descriptions-2027/icd10cm-codes-2027.txt", (SAMPLES / "icd10cm_sample.txt").read_text()
        )
    put("icd10cm", "icd10cm-sample.zip", buf.getvalue(), BY_ID["icd10cm"].url)
    wb = openpyxl.Workbook()
    ws = wb.worksheets[0]
    for row in csv.reader(io.StringIO((SAMPLES / "mhlw_yakka_sample.csv").read_text(encoding="utf-8"))):
        ws.append([float(c) if re.fullmatch(r"\d+\.\d+|\d+", c) and len(c) < 8 else (c or None) for c in row])
    xb = io.BytesIO()
    wb.save(xb)
    put("mhlw_yakka", "yakka_sample.xlsx", xb.getvalue(), BY_ID["mhlw_yakka"].url)
    # D-170 to D-172: excerpts of the real files (the ICD map, the PAS ConceptMap, NAER) and the curated list
    icd = BY_ID["tw_icd_2014_2023"]
    (raw / icd.id).mkdir(parents=True, exist_ok=True)
    icd_parts = []
    for name, url, sample_name in (
        (icd.filename, icd.url, "tw_icd_2014_2023_cm_sample.csv"),
        (icd.extra_files[0][0], icd.extra_files[0][1], "tw_icd_2014_2023_pcs_sample.csv"),
    ):
        data = (SAMPLES / sample_name).read_bytes()
        (raw / icd.id / name).write_bytes(data)
        icd_parts.append({"path": name, "url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    joined = _joined(icd.url, icd_parts) | stamp | {"path": icd.filename}
    (raw / icd.id / "fetch.json").write_text(json.dumps(joined), encoding="utf-8")  # fmt: skip
    tb = io.BytesIO()
    with tarfile.open(fileobj=tb, mode="w:gz") as tf:
        for f in sorted((SAMPLES / "nhi_pas_sample").glob("*.json")):
            ti = tarfile.TarInfo(f"package/{f.name}")
            data = f.read_bytes()
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    put("nhi_lab_loinc", "nhi_pas.tgz", tb.getvalue(), BY_ID["nhi_lab_loinc"].url)
    put("naer_medical_terms", "naer_medical_terms.csv", (SAMPLES / "naer_medical_terms_sample.csv").read_bytes(),
        BY_ID["naer_medical_terms"].url)  # fmt: skip
    put("tw_zh_synonyms", "zh_tw_clinical_synonyms.csv", tw.REPO_SYNONYMS.read_bytes(), BY_ID["tw_zh_synonyms"].url)
    for sid in ("tw_icd_2014_2023", "naer_medical_terms"):
        meta = json.loads((raw / sid / "fetch.json").read_text(encoding="utf-8"))
        (raw / sid / "fetch.json").write_text(json.dumps({**meta, "version": "sample"}), encoding="utf-8")
    # D-173 to D-175: the Japan items that ship (the bridge reads the ICD-10-CM sample above); NCI's CTCAE v5.0
    # workbook as an excerpt of six terms (public domain; the MedDRA code column is blank in the excerpt)
    put("jp_yj_atc", "jp_yj_atc.csv", jp.REPO_YJ_ATC.read_bytes(), BY_ID["jp_yj_atc"].url)
    put("ja_synonyms", "ja_clinical_synonyms.csv", jp.REPO_SYNONYMS.read_bytes(), BY_ID["ja_synonyms"].url)
    cw = openpyxl.Workbook()
    cs = cw.worksheets[0]
    cs.title = "CTCAE v5.0 Clean Copy"
    for row in csv.reader(io.StringIO((SAMPLES / "ctcae_v5_sample.csv").read_text(encoding="utf-8"))):
        cs.append(row)
    cb = io.BytesIO()
    cw.save(cb)
    put("ctcae_v5_en", "ctcae-v5.0.xlsx", cb.getvalue(), BY_ID["ctcae_v5_en"].url)
    return raw


def site_load(sid: str, file: Path, out: Path, load: bool = True, db_url: str | None = None,
              columns: list[str] | None = None, version: str = "") -> Path:  # fmt: skip
    """At the hospital: a site-fetch source the hospital downloaded itself -> its own pack part, loaded beside the
    vendor's pack. TrialBox never downloads it. ``columns``: the column names, in file order, of a release without
    a header row (MEDIS), kept beside the file as ``columns.txt`` (the file itself is not changed). ``version``: the
    release printed on the download (MEDIS Ver.5.19); else the item's own reading of the file, or the load date."""
    s = BY_ID[sid]
    if s.distribution != "site-fetch" or (s.parse is None and sid not in PARSERS):
        raise SystemExit(f"{sid} is not a site-fetch source with a loader")
    raw = out / "raw"
    if (raw / sid).exists():
        shutil.rmtree(raw / sid)  # an earlier load's file or columns must not mix with this one
    meta = local_file(file, raw / sid / file.name, s.url)
    if columns:
        (raw / sid / "columns.txt").write_text(",".join(columns), encoding="utf-8")
        meta["columns"] = columns
    if version.strip():
        meta["version"] = version.strip()
    (raw / sid / "fetch.json").write_text(json.dumps({**meta, "path": file.name}), encoding="utf-8")
    tar = build(raw, out, ids=[sid], suffix=f"site-{sid.replace('_', '-')}", site=True)
    if load:
        with rd.opened(tar) as pack, rd.RefStore(db_url) as st:
            st.load(pack, by=f"site-load:{sid}", origin="site")
    return tar


def table_md() -> str:
    head = "| Source | Decision | Licence | Size | Refresh | Note |\n| --- | --- | --- | --- | --- | --- |\n"
    return head + "".join(f"| {s.name} | {s.distribution} | {s.licence} | {s.size} | {s.refresh} | "
                          f"{(s.note or s.terms).replace('|', '/')} |\n" for s in SOURCES)  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sources")
    f = sub.add_parser("fetch")
    f.add_argument("ids", nargs="+", choices=[s.id for s in SOURCES])
    f.add_argument("--raw", type=Path, default=ROOT / ".cache" / "refdata" / "raw")
    f.add_argument("--file", type=Path, help="an account download (LOINC, the NHIA workbook) instead of the URL")
    f.add_argument("--slice", type=int, default=0, help="ctgov only: one API page of N studies with JP/TW sites")
    f.add_argument(
        "--no-licence-check",
        action="store_true",
        help="do not read the items' licences at the source (recorded in fetch.json as skipped)",
    )
    b = sub.add_parser("build")
    b.add_argument("--raw", type=Path, default=ROOT / ".cache" / "refdata" / "raw")
    b.add_argument("--out", type=Path, default=ROOT / ".cache" / "refdata")
    b.add_argument("--date", help="YYYYMMDD (default today)")
    b.add_argument("--ids", nargs="*")
    sm = sub.add_parser("sample")
    sm.add_argument("--out", type=Path, required=True)
    sl = sub.add_parser("site-load")
    sl.add_argument("id", choices=[s.id for s in SOURCES if s.distribution == "site-fetch"])
    sl.add_argument("--file", type=Path, required=True, help="the file the hospital downloaded itself")
    sl.add_argument("--out", type=Path, default=Path("/tmp/trialbox-site-refdata"))
    sl.add_argument("--columns", help="comma-separated column names in file order, for a file without a header row")
    sl.add_argument("--version", default="", help="the release printed on the download (e.g. MEDIS Ver.5.19)")
    a = ap.parse_args(argv)
    if a.cmd == "sources":
        print(table_md(), end="")
    elif a.cmd == "fetch":
        for line in fetch(a.ids, a.raw, a.file, a.slice, not a.no_licence_check):
            print(line)
    elif a.cmd == "build":
        print(build(a.raw, a.out, a.date, a.ids))
    elif a.cmd == "sample":
        print(build(sample_raw(a.out / "raw"), a.out, "20261109", sample=True))
    else:
        cols = [c.strip() for c in a.columns.split(",") if c.strip()] if a.columns else None
        print(site_load(a.id, a.file, a.out, columns=cols, version=a.version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
