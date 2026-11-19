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
    return {t: int(db.fetchval(f"SELECT count(*) FROM {t} WHERE study = ?", (k.STUDY,)))
            for t in ("draft", "decision", "sent", "copy_tick", "signature")}  # fmt: skip


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
