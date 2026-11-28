"""MVP-B (REAL2 M-3, E2E P-06): at 100,000 patients the candidates list, the week page and the patient sheet took
9.7 to 20.7 s. Each view read and parsed the run's whole stored list (twice on the week page), wrote every listed
pseudonym into ``weekly_seen`` again, and worked out every row's fit again. A view now:

* reads the run's stored list once per study and run, never at each view (a run's outputs never change);
* writes only the pseudonyms ``weekly_seen`` has not recorded;
* works out a row's fit once per list and criteria words; a page that adds to a fit (another study's patient)
  adds to its own copy, so a second view shows the same as the first.

Synthetic data only. The 100,000-row timing itself is ``tests/perf/test_console_pages_100k.py`` (marker ``perf``)."""

from __future__ import annotations

from typing import Any

import pytest
from console import studies as st
from console.backend import RulesetInfo
from tb_common import db as tbdb
from tb_contracts import RegistryEntry

from tests.console.test_console_app import name_pi
from tests.console.test_role_pages import _user
from tests.console.test_site_realities_t629 import T0, A
from tests.console.timing_walk import JOB, PID, clients

PAGES = ("/studies/GZQO/week", f"/studies/GZQO/patients/{PID}", "/studies/GZQO/candidates", "/studies/GZQO/week")


def _list_key(box: dict[str, Any]) -> str:
    job = box["backend"].jobs[JOB]
    return str(next(o.minio_key for o in job.outputs if o.filename.startswith("candidate_list_")))


def test_the_runs_stored_list_is_read_once_for_every_page_view(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    bk, reads = box["backend"], []
    get = bk.get_object

    def counted(k: str) -> bytes:
        if "/candidate_list_" in k:
            reads.append(k)
        return get(k)  # type: ignore[no-any-return]

    monkeypatch.setattr(bk, "get_object", counted)
    crc = clients(box)["coordinator"]  # signing in opens the home page, which may read the run's list first
    for path in PAGES:
        assert crc.get(path, follow_redirects=False).status_code == 200, path
    assert reads == [_list_key(box)], reads  # once; was 6 for these four views alone


def test_a_second_view_writes_no_seen_row_and_works_out_no_listed_fit_again(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    crc = clients(box)["coordinator"]
    assert crc.get(PAGES[0], follow_redirects=False).status_code == 200
    inserts: list[int] = []
    many = tbdb.Tx.executemany

    def counted(self: tbdb.Tx, text: str, rows: Any) -> None:
        if "INSERT INTO weekly_seen" in text:
            inserts.append(len(rows))
        many(self, text, rows)

    monkeypatch.setattr(tbdb.Tx, "executemany", counted)
    fits: list[int] = []
    fit_facts = st.fit_facts

    def counted_fit(*a: Any, **k: Any) -> st.Fit:
        fits.append(1)
        return fit_facts(*a, **k)

    monkeypatch.setattr(st, "fit_facts", counted_fit)
    assert crc.get(PAGES[0], follow_redirects=False).status_code == 200
    assert inserts == [], inserts  # every listed pseudonym is recorded already
    assert len(fits) <= 1, len(fits)  # the side panel's own; was 5 (two listed rows, twice, and the panel)


def test_the_first_view_still_records_each_listed_patient_once(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``weekly_seen`` is what makes a row "new": the first view of a run still writes its listed patients."""
    inserts: list[list[Any]] = []
    many = tbdb.Tx.executemany

    def counted(self: tbdb.Tx, text: str, rows: Any) -> None:
        if "INSERT INTO weekly_seen" in text:
            inserts.append([r[1] for r in rows])
        many(self, text, rows)

    monkeypatch.setattr(tbdb.Tx, "executemany", counted)
    crc = clients(box)["coordinator"]  # signing in opens the home page, which may already show the run
    assert crc.get(PAGES[0], follow_redirects=False).status_code == 200
    written = [pid for batch in inserts for pid in batch]
    assert sorted(written) == sorted(set(written)) and PID in written, inserts


def test_another_studys_patient_reads_the_same_on_every_view(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A kept fit is shared between views: the "in another study" item is added to the view's copy, once."""
    bk = box["backend"]
    clients(box)
    trials = [RulesetInfo("GZQO", "1.0.0", "approved", "trial"), RulesetInfo("STB", "1.0.0", "approved", "trial")]
    monkeypatch.setattr(bk, "rulesets", lambda: trials)
    bk.registry[("STB", A)] = RegistryEntry.model_validate({"ruleset": "STB", "pid": A, "status": "enrolled",
                                                            "updated_at": T0, "updated_by": "console:crc",
                                                            "source": "manual"})  # fmt: skip
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    said = "In another study: check this protocol"
    pages = [pi.get("/studies/GZQO/week?list=all&pid=" + A).text for _ in range(3)]
    assert said in pages[0]
    assert pages[0].count(said) == pages[1].count(said) == pages[2].count(said), [p.count(said) for p in pages]
