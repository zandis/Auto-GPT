"""NEW-B-32 (D-673): an answer of the lake service without its key is an error of the lake, never "no", "none" or
a name.

After D-672 (``snapshot()``), the client's other readers still turned a 200 answer of the wrong shape into a
plain value: ``promote`` read a missing ``promoted`` as False ("a newer night is served"), ``generation`` and
``site_in_sync`` a missing key as None ("not known"), ``hold`` a missing ``generation`` as the snapshot's name
("held, not pinned"), ``release`` a missing ``released`` as False. A 200 of the wrong shape is what a proxy, a
half-deployed service or another responder gives."""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from lake.client import LakeBadAnswer, LakeHttp
from tb_common.http import ServiceError

ROOT = Path(__file__).resolve().parents[2]
NIGHT = "2026-10-04"


def _lake(answers: dict[str, Any], status: int = 200) -> LakeHttp:
    """A client whose lake answers each path with the given body (a str is sent as text, not JSON)."""

    def answer(request: httpx.Request) -> httpx.Response:
        for path, body in answers.items():
            if request.url.path.startswith(path):
                return httpx.Response(status, text=body) if isinstance(body, str) else httpx.Response(status, json=body)
        raise AssertionError(f"not expected: {request.url.path}")

    lake = LakeHttp("http://lake")
    lake.client = httpx.Client(transport=httpx.MockTransport(answer))
    return lake


#: reader -> (the path it reads, the call, a right answer and what the call gives for it)
READERS: dict[str, tuple[str, Callable[[LakeHttp], Any], Any, Any]] = {
    "promote": ("/promote", lambda c: c.promote(NIGHT), {"promoted": True, "current": NIGHT}, True),
    "hold": (
        "/holds",
        lambda c: c.hold(NIGHT, "J1", pin=True),
        {"holder": "J1", "generation": f"{NIGHT}.g2"},
        f"{NIGHT}.g2",
    ),
    "release": ("/holds/J1", lambda c: c.release("J1"), {"holder": "J1", "released": True}, True),
    "holds": ("/holds", lambda c: c.holds(), {"holds": {"J1": NIGHT}}, {"J1": NIGHT}),
    "generation": (
        "/generations/",
        lambda c: c.generation(NIGHT),
        {"generation": f"{NIGHT}.g2", "site_in_sync": True},
        f"{NIGHT}.g2",
    ),
    "site_in_sync": (
        "/generations/",
        lambda c: c.site_in_sync(NIGHT),
        {"generation": None, "site_in_sync": False},
        False,
    ),
    "put_site": ("/site", lambda c: c.put_site({}), {"counts": {"Patient": 3}}, {"Patient": 3}),
    "chunks_search": (
        "/chunks/search",
        lambda c: c.chunks_search("p1", "q"),
        {"hits": [{"did": "d1"}]},
        [{"did": "d1"}],
    ),
    "start_rebuild": (
        "/rebuild",
        lambda c: c.start_rebuild(NIGHT),
        {"state": "running", "job": "j"},
        {"state": "running", "job": "j"},
    ),
    "rebuild_state": ("/rebuild/", lambda c: c.rebuild_state(NIGHT), {"state": "done"}, {"state": "done"}),
}

WRONG: list[Any] = [{}, {"other": 1}, [], ["x"], "<html>a proxy's page</html>", "", "null", "7"]


@pytest.mark.parametrize("reader", sorted(READERS))
def test_a_right_answer_reads_as_before(reader: str) -> None:
    path, call, right, gives = READERS[reader]
    assert call(_lake({path: right})) == gives


def _wrong_answers() -> list[tuple[str, Any]]:
    """Every reader with every wrong answer. A rebuild job's state is an object of the job's own keys, read by
    ``follow_rebuild``: for those two readers only an answer that is no object is wrong here."""
    jobs = ("start_rebuild", "rebuild_state")
    return [(r, w) for r in sorted(READERS) for w in WRONG if not (r in jobs and isinstance(w, dict))]


@pytest.mark.parametrize(("reader", "wrong"), _wrong_answers(), ids=lambda v: repr(v)[:24])
def test_a_200_answer_without_the_readers_key_is_an_error_of_the_lake(reader: str, wrong: Any) -> None:
    path, call, _right, _gives = READERS[reader]
    with pytest.raises(LakeBadAnswer) as got:
        call(_lake({path: wrong}))
    assert isinstance(got.value, ServiceError) and got.value.service == "lake" and got.value.status == 200
    assert "proxy" not in str(got.value)  # what the answer lacks, never the body


@pytest.mark.parametrize(
    ("reader", "answer"),
    [
        ("promote", {"promoted": "yes"}),
        ("promote", {"promoted": None}),
        ("promote", {"promoted": 1}),
        ("release", {"released": "no"}),
        ("hold", {"generation": 7}),
        ("hold", {"generation": ""}),
        ("holds", {"holds": ["J1"]}),
        ("generation", {"generation": 3, "site_in_sync": True}),
        ("site_in_sync", {"generation": None, "site_in_sync": "yes"}),
        ("put_site", {"counts": [3]}),
        ("chunks_search", {"hits": {"did": "d1"}}),
    ],
)
def test_a_key_of_the_wrong_kind_is_an_error_too(reader: str, answer: Any) -> None:
    path, call, _right, _gives = READERS[reader]
    with pytest.raises(LakeBadAnswer):
        call(_lake({path: answer}))


def test_the_answers_that_mean_no_or_not_known_are_the_lakes_own_words_for_it() -> None:
    assert _lake({"/promote": {"promoted": False, "current": "2026-10-05"}}).promote(NIGHT) is False
    assert _lake({"/holds/": {"holder": "J1", "released": False}}).release("J1") is False
    assert _lake({"/holds": {"holder": "J1", "generation": None}}).hold(NIGHT, "J1") == NIGHT  # held, not pinned
    known = {"generation": None, "site_in_sync": None}  # a date built before generations
    assert _lake({"/generations/": known}).generation(NIGHT) is None
    assert _lake({"/generations/": known}).site_in_sync(NIGHT) is None


def test_a_refusal_of_the_lake_raises_as_before() -> None:
    for reader in ("promote", "hold", "generation", "put_site", "chunks_search"):
        path, call, _right, _gives = READERS[reader]
        with pytest.raises(httpx.HTTPStatusError):
            call(_lake({path: {"detail": "refused"}}, status=409))


def test_the_vector_ranking_falls_back_on_any_answer_it_cannot_read() -> None:
    """Its docstring says any failure to get an answer is the fallback answer; a 200 that is not JSON raised."""
    for wrong in WRONG:
        out = _lake({"/vec/s2b": wrong}).vec_s2b("p1", ["d1"], "q")
        assert out["state"] == "fallback", wrong
    ranked = {"state": "vec", "ranked": ["d1"]}
    assert _lake({"/vec/s2b": ranked}).vec_s2b("p1", ["d1"], "q") == ranked


def test_a_query_answer_that_is_not_a_table_is_an_error_of_the_lake() -> None:
    with pytest.raises(LakeBadAnswer):
        _lake({"/query": "<html>a proxy's page</html>"}).query("SELECT 1")


# ------------------------------------------------------------------------------------------- every reader
def test_every_method_of_the_client_reads_its_answer_through_the_one_reader() -> None:
    """No method of ``LakeHttp`` calls ``.json()`` itself or subscripts an answer: a new reader goes through
    ``_object`` / ``_key`` (or is ``snapshot``, D-672, and ``vec_s2b``, which falls back), and is listed here."""
    tree = ast.parse((ROOT / "services/lake/client.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LakeHttp")
    own = {"snapshot"}  # reads /healthz by its own rule (D-672)
    direct, reads = [], set()
    for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        names = {ast.unparse(c.func) for c in calls}
        if any(n.endswith(".json") for n in names) and fn.name not in own:
            direct.append(fn.name)
        if names & {"_object", "_key", "_table", "self.snapshot"} or fn.name in own:
            reads.add(fn.name)
    assert direct == [], f"read through _object/_key, not .json(): {direct}"
    listed = set(READERS) | own | {"vec_s2b", "query", "rebuild"}
    public = {n.name for n in cls.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}
    assert public == listed, f"a method of the client that is not listed with its answer: {sorted(public ^ listed)}"
    assert reads >= listed - {"rebuild"}, sorted(listed - {"rebuild"} - reads)
