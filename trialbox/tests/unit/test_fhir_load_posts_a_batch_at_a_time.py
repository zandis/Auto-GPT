"""F-44 (b): the FHIR store's load reads and posts a batch at a time, never a whole resource type.

A 50,000-patient synthetic night on the bench host died at the adapter's 6 GiB limit: ``post_batches`` read every
resource of a type into a list of batches before it posted the first (one type's file was 504 MB). It now reads a
batch, posts it, and reads the next while at most ``workers`` batches are being posted. The batches, their order,
their requests and the failure of a load with a failed batch are those of the old function, which is kept here as
the oracle. Synthetic resources only; what is counted is resources held, not the process's memory."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pytest
from adapter import load_fhir
from adapter.ndjson import read_type

URL = "http://fhir-store.test/fhir"


class _Store:
    """A FHIR store that records each transaction it is sent (the ids, in the bundle's order) and answers 200, or
    500 for a bundle whose first id is in ``fail``."""

    def __init__(self, fail: Iterable[str] = ()) -> None:
        self.fail = set(fail)
        self.bundles: list[tuple[str, ...]] = []
        self.lock = threading.Lock()
        self.on_post: Any = None

    def client(self) -> Any:
        store = self

        class _Answer:
            def __init__(self, status_code: int) -> None:
                self.status_code = status_code

        class _Client:
            def __init__(self, timeout: float = 0) -> None:
                self.timeout = timeout

            def __enter__(self) -> _Client:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

            def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> _Answer:
                assert url == URL and headers == {"Content-Type": "application/fhir+json"}
                assert json["resourceType"] == "Bundle" and json["type"] == "transaction"
                ids = tuple(str(e["resource"]["id"]) for e in json["entry"])
                assert all(
                    e["request"] == {"method": "PUT", "url": f"Observation/{i}"}
                    for e, i in zip(json["entry"], ids, strict=True)
                )
                if store.on_post is not None:
                    store.on_post(len(ids))
                with store.lock:
                    store.bundles.append(ids)
                return _Answer(500 if ids[0] in store.fail else 200)

        return _Client


def _old_post_batches(
    base_url: str, resources: Iterable[dict[str, Any]], workers: int = 4, timeout: float = 600
) -> int:
    """The function as it was before F-44 (master 36add4fc), word for word: the oracle."""
    batches: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for r in resources:
        cur.append(r)
        if len(cur) == load_fhir.BATCH:
            batches.append(cur)
            cur = []
    if cur:
        batches.append(cur)
    headers = {"Content-Type": "application/fhir+json"}

    def send(batch: list[dict[str, Any]]) -> int:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(base_url.rstrip("/"), json=load_fhir._bundle(batch), headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(f"fhir-store transaction failed ({resp.status_code})")
        return len(batch)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return sum(pool.map(send, batches))


def _night(tmp_path: Path, n: int) -> Path:
    """A generated ``Observation.ndjson`` of ``n`` synthetic resources."""
    folder = tmp_path / "2026-10-04"
    folder.mkdir()
    with (folder / "Observation.ndjson").open("w", encoding="utf-8") as fh:
        for i in range(n):
            row = {
                "resourceType": "Observation",
                "id": f"obs-{i:07d}",
                "status": "final",
                "subject": {"reference": f"Patient/syn-{i % 997:05d}"},
                "valueQuantity": {"value": i % 200},
            }
            fh.write(json.dumps(row) + "\n")
    return folder


class _Counted:
    """The type's reader, counting the resources it has handed out."""

    def __init__(self, rows: Iterable[dict[str, Any]]) -> None:
        self.rows = rows
        self.read = 0

    def __iter__(self) -> Iterator[dict[str, Any]]:
        for r in self.rows:
            self.read += 1
            yield r


def test_a_large_type_is_read_while_it_is_posted_and_never_held_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    n, workers = 40 * load_fhir.BATCH + 123, 2
    folder = _night(tmp_path, n)
    store = _Store()
    monkeypatch.setattr(httpx, "Client", store.client())
    reader = _Counted(read_type(folder, "Observation"))
    posted = 0
    held_most = 0
    count = threading.Lock()

    def on_post(size: int) -> None:  # held now: read from the file and not yet posted to the store
        nonlocal posted, held_most
        with count:
            held_most = max(held_most, reader.read - posted)
            posted += size

    store.on_post = on_post
    assert load_fhir.post_batches(URL, reader, workers=workers) == n
    assert reader.read == n and sum(len(b) for b in store.bundles) == n
    assert sorted(i for b in store.bundles for i in b) == [f"obs-{i:07d}" for i in range(n)]
    # at most the batches being posted and the one read after them; before F-44 every resource of the type
    assert held_most <= (workers + 1) * load_fhir.BATCH, held_most


@pytest.mark.parametrize("workers", [1, 3])
def test_the_posted_batches_are_the_old_functions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workers: int
) -> None:
    folder = _night(tmp_path, 3 * load_fhir.BATCH + 7)
    old, new = _Store(), _Store()
    monkeypatch.setattr(httpx, "Client", old.client())
    n_old = _old_post_batches(URL + "/", read_type(folder, "Observation"), workers=workers)
    monkeypatch.setattr(httpx, "Client", new.client())
    n_new = load_fhir.post_batches(URL + "/", read_type(folder, "Observation"), workers=workers)
    assert n_new == n_old == 3 * load_fhir.BATCH + 7
    if workers == 1:  # one at a time: the same bundles in the same order
        assert new.bundles == old.bundles
    else:  # several at a time: the same bundles, sent in whatever order the posts end
        assert sorted(new.bundles) == sorted(old.bundles)
    assert [len(b) for b in sorted(new.bundles)] == [load_fhir.BATCH] * 3 + [7]


@pytest.mark.parametrize("workers", [1, 4])
def test_a_failed_batch_fails_the_load_as_before(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workers: int) -> None:
    folder = _night(tmp_path, 5 * load_fhir.BATCH)
    failing = [f"obs-{load_fhir.BATCH:07d}", f"obs-{3 * load_fhir.BATCH:07d}"]  # the second and fourth batch
    old, new = _Store(fail=failing), _Store(fail=failing)
    monkeypatch.setattr(httpx, "Client", old.client())
    with pytest.raises(RuntimeError) as was:
        _old_post_batches(URL, read_type(folder, "Observation"), workers=workers)
    monkeypatch.setattr(httpx, "Client", new.client())
    with pytest.raises(RuntimeError) as now:
        load_fhir.post_batches(URL, read_type(folder, "Observation"), workers=workers)
    assert type(now.value) is type(was.value) and now.value.args == was.value.args
    assert now.value.args == ("fhir-store transaction failed (500)",)
    # what both send: every batch up to the first failed one, none twice; a batch not started by then is not sent
    # (``pool.map`` cancels it), so how many after it go out depends on the timing, for the old function as for this
    every = [tuple(f"obs-{i:07d}" for i in range(b * load_fhir.BATCH, (b + 1) * load_fhir.BATCH)) for b in range(5)]
    for sent in (old.bundles, new.bundles):
        assert len(set(sent)) == len(sent) and set(sent) <= set(every)
        assert set(every[:2]) <= set(sent)
    assert len(new.bundles) <= 2 + workers - 1  # the failed batch and the posts beside it, no more
