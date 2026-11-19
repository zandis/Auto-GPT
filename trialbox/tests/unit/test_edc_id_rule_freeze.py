"""D-1253: EDC keeps the lake-id rule per study. A study whose decided, signed or sent values cite lake rows of the
earlier rule (it was never stamped with the current one) is frozen for prefill: a draft run and a send are refused
with the reason; its records stay, and its signatures still verify. A study with no trail stamps itself at its first
draft run. Nothing append-only is deleted and no trigger is disabled. Synthetic data only (``tests.edc_kit``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from edc.store import ID_RULE_FROZEN, EdcError
from tb_common import id_rule

from tests import edc_kit as k
from tests.unit.test_edc import _confirm_all, _draft, _sign


def _signed_study(tmp_path: Path) -> tuple[Any, dict[str, Any]]:
    svc, _sim, _token = k.service(tmp_path)
    k.ready(svc)
    _confirm_all(svc)
    return svc, _sign(svc)


def test_a_study_stamps_itself_at_its_first_draft_run_and_goes_on(tmp_path: Path) -> None:
    svc, sig = _signed_study(tmp_path)
    rule = svc.store.db.fetchval("SELECT rule FROM tb_id_rule_study WHERE study = ?", (k.STUDY,))
    assert rule == id_rule.RULE
    assert svc.status(k.STUDY)["id_rule_frozen"] is False
    assert svc.send_redcap(k.STUDY, "crc")["count"] == 6 and svc.store.intact(sig)


def test_a_study_of_the_earlier_rule_is_frozen_and_its_records_stay(tmp_path: Path) -> None:
    svc, sig = _signed_study(tmp_path)
    svc.store.db.execute("DELETE FROM tb_id_rule_study WHERE study = ?", (k.STUDY,))  # as before D-1253
    drafts_before = svc.store.db.fetchval("SELECT count(*) FROM draft WHERE study = ?", (k.STUDY,))
    assert svc.status(k.STUDY)["id_rule_frozen"] is True
    with pytest.raises(EdcError) as caught:
        _draft(svc)
    assert caught.value.code == "edc.id_rule_frozen" and ID_RULE_FROZEN in str(caught.value)
    with pytest.raises(EdcError) as caught:
        svc.send_redcap(k.STUDY, "crc")
    assert caught.value.code == "edc.id_rule_frozen"
    # nothing written by the refused run or send, and the signed record still verifies and is still exportable
    assert svc.store.db.fetchval("SELECT count(*) FROM draft WHERE study = ?", (k.STUDY,)) == drafts_before
    assert svc.store.db.fetchval("SELECT count(*) FROM sent WHERE study = ?", (k.STUDY,)) == 0
    assert svc.store.intact(svc.store.signature(int(sig["id"])))
    assert "ODM" in svc.export_odm(k.STUDY, "crc")
    assert svc.store.db.fetchval("SELECT count(*) FROM tb_id_rule_study") == 0  # never stamped by a refusal
