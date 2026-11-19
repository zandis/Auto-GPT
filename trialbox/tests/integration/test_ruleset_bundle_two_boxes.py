"""10D-28 (D-1369; review 19-9), the proof: a rule set approved on one box screens on another box that received it
in a vendor-signed update bundle, with the same answers.

Two in-process boxes (``tests/inproc_box.py``) read the same synthetic hospital. The head box holds GZQO approved at
that box and screens it. It exports the approved version as a rule-set part; the vendor signs a bundle that carries
the part alone (the vendor key); the second box, which never held GZQO, verifies and applies the bundle through the
update path (``tests/unit/test_ruleset_in_update_bundle.ScreenOnlyBox``: the real verifier, ``Updater`` and rule-set
import), lists GZQO as arrived in a vendor bundle, and screens the same patients by e-mail. Every listed patient, tier
and criterion answer is the same on both boxes. The matching engine is not changed by the card.

What the test does not do: compile the protocol on the head box (GZQO is the shipped compile, approved at the head
box; the compile itself is covered by the compiler's tests) and run the container box's steps (backup, images,
restart: ``tools/trialbox/update.py`` ``ComposeBox``, unchanged). Synthetic data only.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import tb_contracts as c
from criteria_compiler.export_part import compiled_on, export
from criteria_compiler.repo import RulesetRepo
from tb_common.audit import AuditLog
from tb_common.crypto import pid_for_mrn
from tb_common.ruleset import RulesetNotApproved, arrived_in_bundle, load_approved

from tests.inproc_box import Box, ingest_site, make_box, unzip_phi
from tests.unit.test_ruleset_in_update_bundle import ScreenOnlyBox, apply_bundle
from tools import ruleset_bundle, sign_bundle

KEY = b"trialbox-test-site-key-0123456789abcdef"


def _screen(box: Box) -> dict[str, tuple[str, tuple[tuple[str, str], ...]]]:
    """``SCREEN GZQO`` by e-mail; the candidate list as {pseudonym: (tier, ((criterion, answer), ...))}."""
    assert box.mail("SCREEN GZQO version=1.0.0") == "Processed"
    box.orch.drain()
    job = box.orch.db.find(type_="SCREEN")[0]
    assert job.state == "done", job.error
    mail = next(s for s in reversed(box.sent) if s.subject.startswith("[GZQO] SCREEN candidates") and
                "pi@hospa.test" in s.to)  # fmt: skip
    files = unzip_phi(box, mail)
    cl = c.CandidateList.model_validate_json(next(v for k, v in files.items() if k.endswith(".json")))
    return {r.pid: (r.tier, tuple(sorted((v.id, v.verdict) for v in r.criteria))) for r in cl.rows}


def test_a_rule_set_from_the_head_box_screens_the_same_on_the_site_box(
    synth_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TB_ENV", raising=False)  # both are site boxes (PRODUCTION by the one rule, D-127)
    sec = tmp_path / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(KEY)
    ingest_site(synth_dir / "site-a", tmp_path / "lake", sec, "2026-10-04")
    head = make_box(tmp_path / "head", tmp_path / "lake", sec)
    site = make_box(tmp_path / "site", tmp_path / "lake", sec, without_rulesets=("GZQO",))
    with pytest.raises(RulesetNotApproved):  # before the bundle the site box has no GZQO to screen with
        load_approved(tmp_path / "site" / "repo", "GZQO")

    on_head = _screen(head)

    # the head box exports, the vendor signs a bundle with the part alone, the site box applies it
    data, origin = export(RulesetRepo(tmp_path / "head" / "repo"), "GZQO",
                          compiled_on({"bundle_id": "2026.11-1", "release_seq": 3, "commit": "a" * 40}))  # fmt: skip
    part = tmp_path / "GZQO-1.0.0.part.zip"
    part.write_bytes(data)
    priv, pub = sign_bundle.keygen(tmp_path / "vendor")
    ruleset_bundle.build(priv, "2026.11-1-rs1", [part], tmp_path / "rs.tar", release_seq=4)
    updates = tmp_path / "updates"
    updates.mkdir()
    (updates / "installed.json").write_text(json.dumps({"format": "trialbox-installed/1", "release_seq": 3,
                                                        "bundle_id": "2026.11-1", "state": {}}))  # fmt: skip
    box = ScreenOnlyBox(tmp_path / "site" / "repo", AuditLog(tmp_path / "update-audit"))
    assert apply_bundle(tmp_path / "rs.tar", pub, box, updates, tmp_path / "stage")["ok"]
    assert arrived_in_bundle(tmp_path / "site" / "repo", "GZQO", "1.0.0")
    assert origin["content_sha256"] in RulesetRepo(tmp_path / "site" / "repo").tag_message("GZQO/v1.0.0")

    on_site = _screen(site)
    assert len(on_head) > 5
    assert on_site == on_head  # every listed patient, tier and criterion answer
    mrns = {pid_for_mrn(KEY, r["mrn"]) for r in csv.DictReader((synth_dir / "site-a" / "patient.csv").open())}
    assert set(on_head) <= mrns  # the same synthetic hospital's patients
