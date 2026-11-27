"""D-989's search on the audit page (lane C2's card; D-1155): which records did a model, build or prompt touch.

The audit page runs ``tb_common.provenance_index.search`` (lane A2's step 2c) for the roles of ``audit.provenance``:
the data steward and the privacy office see each record with its patient's pseudonym; the administrator sees the same
records with every pseudonym hidden (``audit.ids``: D-280). A search names at least one filter; each is audited
(``console.provenance_search``: the filters and how many rows). Synthetic chain and database only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tb_common import provenance_index as idx

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.unit.test_provenance_index import PID_A, PID_B, _chain, con  # noqa: F401 - the fixture is used by name

PW = "provenance-search-password-01"


def _box(b: dict[str, Any], c: Any, tmp_path: Path) -> None:
    # P-19: the page serves an index whose marker (in the console's audit directory) says verified: the install's one
    # rebuild, from that directory's chain (it holds no model call), then the index of the test's own chain
    idx.rebuild(c, Path(b["app"].state.audit_hooks.au.directory))
    idx.rebuild(c, _chain(tmp_path).directory)
    b["app"].state.audit_hooks.doors["provenance"] = lambda: _Kept(c)
    for name, role in (("stw", "steward"), ("dpo", "privacy"), ("ops", "admin"), ("crc", "coordinator")):
        b["users"].create(name, role, PW, f"{name}@hospa.test")


class _Kept:
    """The test's one connection, lent to each search; the page's close leaves it open for the next."""

    def __init__(self, c: Any) -> None:
        self.c = c

    def execute(self, *a: Any, **k: Any) -> Any:
        return self.c.execute(*a, **k)

    def close(self) -> None:
        pass


def _events(b: dict[str, Any]) -> list[dict[str, Any]]:
    import json

    return [e for f in sorted(Path(b["backend"].audit_dir).rglob("*.jsonl"))
            for x in f.read_text(encoding="utf-8").splitlines() if x
            for e in [json.loads(x)] if e.get("event") == "console.provenance_search"]  # fmt: skip


def test_the_steward_finds_every_record_a_build_touched(box: dict[str, Any], con: Any, tmp_path: Path) -> None:  # noqa: F811
    _box(box, con, tmp_path)
    for name in ("stw", "dpo"):
        c, _ = login(box["app"], name, PW)
        page = c.get("/audit/provenance", params={"build_sha": "b2"})
        assert page.status_code == 200, page.text[-300:]
        assert PID_A in page.text and PID_B in page.text and 'data-testid="prov-row"' in page.text
    (ev, _second) = _events(box)
    assert ev["detail"]["filters"] == {"build_sha": "b2"} and ev["detail"]["rows"] >= 2 and ev["actor"] == "console:stw"


def test_the_administrator_sees_the_records_without_pseudonyms(box: dict[str, Any], con: Any, tmp_path: Path) -> None:  # noqa: F811
    _box(box, con, tmp_path)
    c, _ = login(box["app"], "ops", PW)
    page = c.get("/audit/provenance", params={"build_sha": "b2"})
    assert page.status_code == 200 and 'data-testid="prov-row"' in page.text
    assert PID_A not in page.text and PID_B not in page.text  # D-280: no pseudonym for the administrator


def test_other_roles_are_refused_and_an_empty_search_runs_nothing(box: dict[str, Any], con: Any,  # noqa: F811
                                                                  tmp_path: Path) -> None:  # fmt: skip
    _box(box, con, tmp_path)
    crc, _ = login(box["app"], "crc", PW)
    assert crc.get("/audit/provenance", params={"build_sha": "b2"}).status_code == 403
    stw, _ = login(box["app"], "stw", PW)
    page = stw.get("/audit/provenance")
    assert (
        page.status_code == 200 and 'data-testid="prov-form"' in page.text and 'data-testid="prov-row"' not in page.text
    )
    assert _events(box) == []  # no filter: no search, nothing audited


def test_an_index_that_cannot_be_read_is_said(box: dict[str, Any], con: Any, tmp_path: Path) -> None:  # noqa: F811
    _box(box, con, tmp_path)

    def down() -> Any:
        raise OSError("the trial database does not answer")

    box["app"].state.audit_hooks.doors["provenance"] = down
    stw, _ = login(box["app"], "stw", PW)
    page = stw.get("/audit/provenance", params={"model": "m-judge"})
    assert page.status_code == 503 and 'data-testid="prov-error"' in page.text


def test_free_text_is_never_searched_or_written_to_the_chain(box: dict[str, Any], con: Any, tmp_path: Path) -> None:  # noqa: F811
    """The review of D-1155: a filter is an id; anything else (a name, a chart number with a space, markup) is
    refused before any search or audit line, and a prompt version needs its prompt id."""
    _box(box, con, tmp_path)
    stw, _ = login(box["app"], "stw", PW)
    for params in ({"model": "Wang Xiao Ming"}, {"model": "<script>x</script>"}, {"prompt_version": "4"}):
        page = stw.get("/audit/provenance", params=params)
        assert page.status_code == 400 and 'data-testid="prov-bad"' in page.text, params
        assert "<script>x" not in page.text
    assert _events(box) == []


def test_a_failed_search_is_audited_and_the_administrators_search_says_no_pseudonym(box: dict[str, Any], con: Any,  # noqa: F811
                                                                                     tmp_path: Path) -> None:  # fmt: skip
    _box(box, con, tmp_path)
    ops, _ = login(box["app"], "ops", PW)
    assert ops.get("/audit/provenance", params={"build_sha": "b2"}).status_code == 200
    (ev,) = _events(box)
    assert ev["detail"]["pids"] is False and ev["actor"] == "console:ops"

    def down() -> Any:
        raise OSError("the trial database does not answer")

    box["app"].state.audit_hooks.doors["provenance"] = down
    assert ops.get("/audit/provenance", params={"build_sha": "b2"}).status_code == 503
    assert _events(box)[-1]["detail"]["error"] is True


def test_a_search_is_refused_while_the_index_must_be_rebuilt(
    box: dict[str, Any],  # noqa: F811
    con: Any,  # noqa: F811
    tmp_path: Path,
) -> None:
    """P-19 (review P19-X1, High; P19-DESIGN-3 §2): after a restore the index may not equal the chain filtered by the
    register; while its marker says rebuild-required the page serves nothing, said as an index that cannot be read."""
    _box(box, con, tmp_path)
    idx.require_rebuild(Path(box["app"].state.audit_hooks.au.directory), "journal resync")
    c, _ = login(box["app"], "stw", PW)
    page = c.get("/audit/provenance", params={"build_sha": "b2"})
    assert page.status_code == 503 and 'data-testid="prov-error"' in page.text
    assert PID_A not in page.text and PID_B not in page.text and 'data-testid="prov-row"' not in page.text
