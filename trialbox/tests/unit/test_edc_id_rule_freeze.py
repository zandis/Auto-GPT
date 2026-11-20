"""D-1253: EDC keeps the lake-id rule per study.

* The migration stamps rule 1 on every study that has drafts when it runs; a study with none yet starts at rule 2 at
  its first draft run.
* A rule-1 study with a decided, signed or sent value is frozen for prefill: every write path of its values (a draft
  run, an ODM import, a decision, a copy tick, a send, REDCap's erase of hidden values) is refused with the reason,
  before anything is written. Its records stay and its signatures still verify; nothing marks a value
  ``source_changed`` because of the change of rule.
* A rule-1 study with open drafts only waits for the one rebuild (``tools/id_rule_rebuild.py``), which clears those
  drafts and stamps it rule 2.

Nothing append-only is deleted and no trigger is disabled. Synthetic data only (``tests.edc_kit``)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from edc import copyassist
from edc.store import ID_RULE_FROZEN, ID_RULE_WAITING, EdcError, EdcStore
from tb_common import id_rule

from tests import edc_kit as k
from tests.unit.test_edc import _confirm_all, _draft, _sign


def _signed_study(tmp_path: Path) -> tuple[Any, dict[str, Any]]:
    svc, _sim, _token = k.service(tmp_path)
    k.ready(svc)
    _confirm_all(svc)
    return svc, _sign(svc)


def _as_before_d1253(svc: Any) -> None:
    """The store as the release before D-1253 left it, then migrated by this one: version 9 is applied again."""
    db = svc.store.db
    db.execute("DROP TABLE tb_id_rule_study")
    db.execute("DELETE FROM _schema_version WHERE version = 9")
    EdcStore(sign_key=k.SIGN_KEY)  # the service starting on the updated box: the migration runs


def _rule(svc: Any, study: str = k.STUDY) -> Any:
    return svc.store.db.fetchval("SELECT rule FROM tb_id_rule_study WHERE study = ?", (study,))


def test_a_study_stamps_itself_at_its_first_draft_run_and_goes_on(tmp_path: Path) -> None:
    svc, sig = _signed_study(tmp_path)
    assert _rule(svc) == id_rule.RULE
    assert svc.status(k.STUDY)["id_rule_frozen"] is False
    assert svc.send_redcap(k.STUDY, "crc")["count"] == 6 and svc.store.intact(sig)


def test_the_migration_stamps_every_study_with_drafts_rule_1_and_a_later_study_starts_at_2(tmp_path: Path) -> None:
    svc, _sig = _signed_study(tmp_path)
    _as_before_d1253(svc)
    assert _rule(svc) == 1
    assert _rule(svc, "NEWSTUDY") is None  # no drafts: no rule until its first draft run, which stamps 2
    with svc.store.db.transaction() as tx:
        svc.store._study_rule(tx, "NEWSTUDY")
    assert _rule(svc, "NEWSTUDY") == id_rule.RULE


def _counts(svc: Any) -> dict[str, int]:
    db = svc.store.db
    asked = {  # written out, one per table (no query made from strings)
        "draft": "SELECT count(*) FROM draft WHERE study = ?",
        "decision": "SELECT count(*) FROM decision WHERE study = ?",
        "sent": "SELECT count(*) FROM sent WHERE study = ?",
        "copy_tick": "SELECT count(*) FROM copy_tick WHERE study = ?",
        "signature": "SELECT count(*) FROM signature WHERE study = ?",
    }
    return {t: int(db.fetchval(q, (k.STUDY,))) for t, q in asked.items()}


def test_a_study_of_the_earlier_rule_with_a_trail_is_frozen_on_every_write_path(tmp_path: Path) -> None:
    svc, sig = _signed_study(tmp_path)
    _as_before_d1253(svc)
    before = _counts(svc)
    changed_before = svc.store.db.fetchval("SELECT count(*) FROM draft WHERE source_changed IS NOT NULL")
    assert svc.status(k.STUDY)["id_rule_frozen"] is True
    some = int(next(iter(svc.store.drafts(k.STUDY, k.RECORD, current=False)))["id"])
    paths: dict[str, Callable[[], Any]] = {
        "draft run": lambda: _draft(svc),
        "decision": lambda: svc.decide(k.STUDY, some, "confirm", by="crc"),
        "copy tick": lambda: copyassist.tick(svc, k.STUDY, k.RECORD, [some], "copied", "crc"),
        "send": lambda: svc.send_redcap(k.STUDY, "crc"),
        "erase hidden": lambda: svc.erase_hidden(k.STUDY, k.RECORD, "", "crc"),
    }
    for name, write in paths.items():
        with pytest.raises(EdcError) as caught:
            write()
        assert caught.value.code == "edc.id_rule_frozen", name
        assert ID_RULE_FROZEN in str(caught.value), name
    # nothing written by any refused path; no value marked source_changed by the change of rule
    assert _counts(svc) == before
    assert svc.store.db.fetchval("SELECT count(*) FROM draft WHERE source_changed IS NOT NULL") == changed_before == 0
    assert svc.store.db.fetchval("SELECT count(*) FROM decision WHERE action = 'source_changed'") == 0
    # the signed record still verifies and is still exportable, and the study stays rule 1
    assert svc.store.intact(svc.store.signature(int(sig["id"])))
    assert "ODM" in svc.export_odm(k.STUDY, "crc")
    assert _rule(svc) == 1


def test_a_study_of_the_earlier_rule_with_open_drafts_only_waits_for_the_rebuild(tmp_path: Path) -> None:
    svc, _sim, _token = k.service(tmp_path)
    k.ready(svc)
    _draft(svc)  # open drafts, nothing decided
    _as_before_d1253(svc)
    assert _rule(svc) == 1 and svc.status(k.STUDY)["id_rule_frozen"] is False
    with pytest.raises(EdcError) as caught:
        _draft(svc)
    assert caught.value.code == "edc.id_rule_frozen" and ID_RULE_WAITING in str(caught.value)
    assert id_rule.COMMAND in ID_RULE_WAITING


def test_a_study_whose_only_decided_value_cites_no_lake_row_is_not_frozen_and_the_rebuild_frees_it(
    tmp_path: Path, db_url: str
) -> None:
    """Review round 3, item 6: one definition of "has a trail" (``edc.store.cites_old_rows``), used by EDC and by the
    rebuild. A draft decided "not found" cites no lake row, so its rule-1 study is not frozen: EDC says it waits, the
    rebuild's plan counts it as waiting, never as frozen. The rebuild clears its open drafts, keeps the decided one
    as it is, and stamps the study rule 2; then every write path goes on. Never stuck between the two."""
    import os

    from tools import id_rule_rebuild as rb

    svc, _sim, _token = k.service(tmp_path)
    k.ready(svc)
    _draft(svc)
    drafts = [int(d["id"]) for d in svc.store.drafts(k.STUDY, k.RECORD, current=False)]
    first = drafts[0]
    svc.store.db.execute("UPDATE draft SET citation = NULL, final_citation = NULL WHERE id = ?", (first,))  # not found
    svc.decide(k.STUDY, first, "reject", reason="not in the chart", by="crc")
    _as_before_d1253(svc)
    assert _rule(svc) == 1 and svc.status(k.STUDY)["id_rule_frozen"] is False
    with pytest.raises(EdcError) as caught:
        _draft(svc)
    assert ID_RULE_WAITING in str(caught.value)  # waiting, as the rebuild sees it too
    url = os.environ["TB_DB_URL"]
    got = rb.plan(tmp_path / "lake", url)["edc"]
    assert got["frozen_studies"] == {} and got["open_drafts"] == {k.STUDY: len(drafts) - 1}
    done = rb.rebuild(tmp_path / "lake", url)["edc"]
    assert done["studies_now_rule_2"] == [k.STUDY] and done["open_drafts_cleared"] == len(drafts) - 1
    assert _rule(svc) == id_rule.RULE and svc.status(k.STUDY)["id_rule_frozen"] is False
    kept = svc.store.db.fetchall("SELECT id, fate FROM draft WHERE study = ?", (k.STUDY,))
    assert [(int(i), f) for i, f in kept] == [(first, "rejected")]  # the decided value, as it was
    _draft(svc)  # the study goes on


def test_the_trail_tables_are_every_table_that_names_a_draft(tmp_path: Path) -> None:
    """Review round 3, item 6: ``TRAIL_TABLES`` is held to the migrated schema, so EDC and the rebuild never miss an
    act on a draft added by a later migration."""
    from edc.store import TRAIL_TABLES

    svc, _sim, _token = k.service(tmp_path)
    got = svc.store.db.fetchall(
        "SELECT DISTINCT table_name FROM information_schema.columns WHERE table_schema = current_schema() AND "
        "column_name = 'draft_id' ORDER BY table_name"
    )
    assert tuple(str(r[0]) for r in got) == TRAIL_TABLES
