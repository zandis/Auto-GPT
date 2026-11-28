"""The full ClinicalTrials.gov fetch: pages are kept as served, a stopped run continues from its state, the held-out
split is read from the first-post date, and the uploaded documents are listed per MeSH family. No network: the
registry is a stub that serves three pages."""

from __future__ import annotations

import gzip
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from tools import ctgov_full_fetch as cf


def _study(
    nct: str, first_post: str | None, mesh: tuple[str, ...] = (), docs: tuple[dict[str, Any], ...] = ()
) -> dict[str, Any]:
    status = {"studyFirstPostDateStruct": {"date": first_post}} if first_post else {}
    return {
        "protocolSection": {"identificationModule": {"nctId": nct}, "statusModule": status},
        "derivedSection": {"conditionBrowseModule": {"meshes": [{"term": t} for t in mesh]}},
        "documentSection": {"largeDocumentModule": {"largeDocs": list(docs)}},
    }


PAGES = [
    [_study("NCT00000001", "2025-12-31"), _study("NCT00000002", "2026-01-01", ("Gout",))],
    [
        _study(
            "NCT00000003", "2026-03", ("Arthritis, Rheumatoid",), ({"typeAbbrev": "Prot", "filename": "Prot_000.pdf"},)
        ),
        _study("NCT00000004", None),
    ],
    [_study("NCT00000005", "2026-06-02", ("Neoplasms",))],
]


class Registry:
    """Serves PAGES by token, counts the page requests and keeps their URLs."""

    def __init__(self) -> None:
        self.page_calls = 0
        self.urls: list[str] = []

    def __call__(self, url: str) -> Any:
        if url.endswith("/version"):
            return {"dataTimestamp": "2026-11-25T10:00:05"}
        self.page_calls += 1
        self.urls.append(url)
        i = int(url.split("pageToken=t")[1].split("&", maxsplit=1)[0]) if "pageToken=t" in url else 0
        out: dict[str, Any] = {"studies": PAGES[i]}
        if i == 0:
            out["totalCount"] = 5  # the registry counts on the first page only
        if i + 1 < len(PAGES):
            out["nextPageToken"] = f"t{i + 1}"
        return out


def test_a_stopped_fetch_continues_from_its_state_and_keeps_every_record(tmp_path: Path) -> None:
    reg = Registry()
    st = cf.fetch(tmp_path, max_pages=1, pause=0, get=reg)
    assert (st["pages"], st["records"], st["done"], st["expected"]) == (1, 2, False, 5)
    st = cf.fetch(tmp_path, pause=0, get=reg)
    assert (st["pages"], st["records"], st["done"]) == (3, 5, True)
    assert reg.page_calls == 3  # the second run did not fetch page 1 again
    assert [s["protocolSection"]["identificationModule"]["nctId"] for s in cf.iter_studies(tmp_path)] == [
        f"NCT0000000{i}" for i in range(1, 6)
    ]
    assert cf.fetch(tmp_path, pause=0, get=reg)["done"] and reg.page_calls == 3  # a finished fetch asks for nothing


def test_the_held_out_split_comes_from_the_first_post_date_and_is_diffed_against_the_id_list(tmp_path: Path) -> None:
    cf.fetch(tmp_path, pause=0, get=Registry())
    ref = tmp_path / "ref.txt"
    ref.write_text("NCT00000002\nNCT00000005\nNCT00000009\n")
    r = cf.heldout(tmp_path, ref)
    assert (r["records"], r["without_first_post_date"], r["heldout_from_records"]) == (5, 1, 3)
    assert (r["only_in_ref"], r["only_in_records"]) == (1, 1)  # NCT...09 is not served; NCT...03 (month only) is new
    assert r["only_in_records_first_post_range"] == ["2026-03-01", "2026-03-01"]
    assert (tmp_path / "heldout_firstpost.txt").read_text().split() == ["NCT00000002", "NCT00000003", "NCT00000005"]


def test_documents_are_listed_per_mesh_family_with_their_url(tmp_path: Path) -> None:
    cf.fetch(tmp_path, pause=0, get=Registry())
    r = cf.documents(tmp_path)
    assert r["rheumatoid_arthritis"] == {"studies": 1, "studies_with_documents": 1, "documents": {"Prot": 1}}
    assert r["gout"]["studies"] == 1 and r["gout"]["studies_with_documents"] == 0
    rows = (tmp_path / "documents.csv").read_text().splitlines()
    assert len(rows) == 2 and rows[1].endswith("https://cdn.clinicaltrials.gov/large-docs/03/NCT00000003/Prot_000.pdf")
    assert json.loads((tmp_path / "state.json").read_text())["done"]


def test_slices_fetched_side_by_side_are_read_from_their_parent(tmp_path: Path) -> None:
    reg = Registry()
    cf.fetch(tmp_path / "part-a", pause=0, where="AREA[StudyFirstPostDate]RANGE[MIN,2025-12-31]", get=reg)
    cf.fetch(tmp_path / "part-b", pause=0, max_pages=1, where="AREA[StudyFirstPostDate]RANGE[2026-01-01,MAX]", get=reg)
    assert "filter.advanced=AREA" in reg.urls[0]
    s = cf.status(tmp_path)
    assert (s["slices"], s["all_done"], s["records"], s["expected"]) == (2, False, 7, 10)
    assert s["unfinished"] == {"part-b": "2/5"}
    assert len(list(cf.iter_studies(tmp_path))) == 7


def test_a_busy_registry_is_retried_and_a_missing_page_is_not(monkeypatch: pytest.MonkeyPatch) -> None:
    req = httpx.Request("GET", "https://registry.test/studies")
    answers = [httpx.Response(503, request=req), httpx.Response(200, json={"studies": []}, request=req)]
    monkeypatch.setattr(httpx, "get", lambda *a, **k: answers.pop(0))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert cf._get("https://registry.test/studies") == {"studies": []}
    answers[:] = [httpx.Response(404, request=req)]
    with pytest.raises(httpx.HTTPStatusError):
        cf._get("https://registry.test/studies")


def test_a_resume_keeps_the_saved_filter_and_refuses_a_different_one(tmp_path: Path) -> None:
    reg = Registry()
    w = "AREA[StudyFirstPostDate]RANGE[2026-01-01,MAX]"
    cf.fetch(tmp_path, max_pages=1, pause=0, where=w, get=reg)
    cf.fetch(tmp_path, pause=0, get=reg)  # no --where: the saved one is used with the saved token
    assert all("filter.advanced=AREA" in u for u in reg.urls) and len(reg.urls) == 3
    with pytest.raises(ValueError, match="started with filter"):
        cf.fetch(tmp_path, pause=0, where="AREA[StudyFirstPostDate]RANGE[MIN,2025-12-31]", get=reg)


def test_pages_past_9999_are_read_in_numeric_order(tmp_path: Path) -> None:
    for n in (10000, 9999, 2):
        with gzip.open(tmp_path / f"p{n:04d}.json.gz", "wt") as f:
            json.dump({"studies": [_study(f"NCT{n:08d}", None)]}, f)
    (tmp_path / "pold.json.gz").write_bytes(b"not a page")
    assert [cf._nct(s) for s in cf.iter_studies(tmp_path)] == ["NCT00000002", "NCT00009999", "NCT00010000"]


def test_status_of_a_directory_without_state_is_not_done(tmp_path: Path) -> None:
    assert cf.status(tmp_path)["all_done"] is False
    assert cf.status(tmp_path / "missing")["all_done"] is False
