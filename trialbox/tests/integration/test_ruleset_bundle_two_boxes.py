"""10D-28 (D-1369; review 19-9), the proof: a rule set approved on one box screens on another box that received it
in a vendor-signed update bundle, with the same answers, and the answers are the carried version's.

Two in-process boxes (``tests/inproc_box.py``) read the same synthetic hospital.

1. The head box screens the shipped GZQO v1.0.0, approved at that box (the answers "as shipped").
2. The head box approves **GZQO v1.0.1, which is not shipped**: criterion GZQO-INC-01 asks for age 60 or more instead
   of 18. The draft is written into the head box's repository by the test (not compiled from a protocol); its
   approval goes through the compiler's own approval (``Compiler.approve``, as the APPROVE command runs it), which
   rebuilds the SQL from the criteria. The head box screens v1.0.1: the answers differ from the shipped version's.
3. The head box exports v1.0.1 as a rule-set part; the vendor signs a bundle that carries the part alone (the vendor
   key); the second box, which never held GZQO, verifies and applies it through the update path
   (``tests/unit/test_ruleset_in_update_bundle.ScreenOnlyBox``: the real verifier, ``Updater`` and rule-set import),
   lists GZQO as arrived in a vendor bundle, and screens v1.0.1 by e-mail.
4. Every listed patient, tier and criterion answer on the second box equals the head box's v1.0.1 answers, and they
   are not the shipped version's: the second box screened with what the bundle carried, not with a rule set that was
   on it already. The matching engine is not changed by the card.

The part carries no routing or scope (D-1369): the second box screens with its own, which its operator sets first
with ``import_ruleset --site-profile`` (audited; here the synthetic site's people, the same hospital; the example
profile the box ships with does not count). A box that holds a version already refuses a
part of that version with other content; for the dry run the head box exports a new id or version, as here.
Not done here: the container box's steps (backup, images, restart: ``tools/trialbox/update.py`` ``ComposeBox``,
unchanged). Synthetic data only.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import tb_contracts as c
import yaml
from criteria_compiler.export_part import compiled_on, export
from criteria_compiler.import_ruleset import put_site_profile
from criteria_compiler.repo import RulesetRepo
from tb_common.audit import AuditLog
from tb_common.crypto import pid_for_mrn
from tb_common.ruleset import RulesetNotApproved, arrived_in_bundle, load_approved

from tests.inproc_box import Box, ingest_site, make_box, unzip_phi
from tests.unit.test_ruleset_in_update_bundle import ScreenOnlyBox, apply_bundle
from tools import ruleset_bundle, sign_bundle

KEY = b"trialbox-test-site-key-0123456789abcdef"
Answers = dict[str, tuple[str, tuple[tuple[str, str], ...]]]


def _screen(box: Box, version: str) -> Answers:
    """``SCREEN GZQO version=<version>`` by e-mail; the candidate list as {pseudonym: (tier, ((criterion, answer),
    ...))}."""
    before = {j.job_id for j in box.orch.db.find(type_="SCREEN")}
    box.sent.clear()
    assert box.mail(f"SCREEN GZQO version={version}") == "Processed"
    box.orch.drain()
    (job,) = [j for j in box.orch.db.find(type_="SCREEN") if j.job_id not in before]
    assert job.state == "done", job.error
    mail = next(s for s in reversed(box.sent) if s.subject.startswith("[GZQO] SCREEN candidates") and
                "pi@hospa.test" in s.to)  # fmt: skip
    files = unzip_phi(box, mail)
    cl = c.CandidateList.model_validate_json(next(v for k, v in files.items() if k.endswith(".json")))
    return {r.pid: (r.tier, tuple(sorted((v.id, v.verdict) for v in r.criteria))) for r in cl.rows}


def _approve_v101(box: Box, repo_dir: Path) -> None:
    """GZQO v1.0.1 on the head box: a draft with GZQO-INC-01 at age 60, approved by the compiler's own approval."""
    repo = RulesetRepo(repo_dir)
    files = {p[len("GZQO/") :]: b for p, b in repo.files("main", "GZQO/").items()}
    m = yaml.safe_load(files["manifest.yaml"])
    m.update(version="1.0.1", status="draft")
    for key in ("review", "equivalence"):
        m.pop(key, None)
    files["manifest.yaml"] = yaml.safe_dump(m, allow_unicode=True, sort_keys=False).encode()
    ir = json.loads(files["ir/GZQO-INC-01.json"])
    ir["logic"]["age"]["min"] = 60.0
    ir.update(label="Age ≥60", text="Male or female participants aged 60 years or older at screening.",
              review={"status": "draft"})  # fmt: skip
    files["ir/GZQO-INC-01.json"] = (json.dumps(ir, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
    files = {p: b for p, b in files.items() if not p.startswith("tests/")}
    repo.write_dir("draft/01JD28HEAD0000000000000000", "main", "GZQO/", files, "draft GZQO v1.0.1 (test)")
    criteria = [str(x) for x in m["criteria"]]
    res = box.orch.services.compiler.approve(
        c.ApproveRequest(
            ruleset="GZQO",
            version="1.0.1",
            by="pi@hospa.test",
            via="web console",
            decisions=[c.ReviewDecision(id=cid, status="approve") for cid in criteria],
        )
    )
    assert res.status == "approved", (res.status, res.blocking)
    assert ">= 60" in (repo_dir / "GZQO" / "sql" / "GZQO.sql").read_text()  # the SQL was rebuilt from the criteria


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

    as_shipped = _screen(head, "1.0.0")
    _approve_v101(head, tmp_path / "head" / "repo")
    on_head = _screen(head, "1.0.1")
    assert len(on_head) > 5 and on_head != as_shipped  # the carried version answers differently

    # the head box exports, the vendor signs a bundle with the part alone, the site box applies it
    data, origin = export(RulesetRepo(tmp_path / "head" / "repo"), "GZQO",
                          compiled_on({"bundle_id": "2026.11-1", "release_seq": 3, "commit": "a" * 40}))  # fmt: skip
    assert origin["version"] == "1.0.1"
    part = tmp_path / "GZQO-1.0.1.part.zip"
    part.write_bytes(data)
    priv, pub = sign_bundle.keygen(tmp_path / "vendor")
    ruleset_bundle.build(priv, "2026.11-1-rs1", [part], tmp_path / "rs.tar", release_seq=4)
    updates = tmp_path / "updates"
    updates.mkdir()
    (updates / "installed.json").write_text(json.dumps({"format": "trialbox-installed/1", "release_seq": 3,
                                                        "bundle_id": "2026.11-1", "state": {}}))  # fmt: skip
    site_repo = RulesetRepo(tmp_path / "site" / "repo")
    shipped = yaml.safe_load(site_repo.read("main", "profiles/GZQO.yaml") or b"")
    own = {"routing": shipped["routing"], "scopes": shipped["scopes"]}  # the operator's own file, the same people
    put_site_profile(site_repo, "GZQO", yaml.safe_dump(own).encode(), "operator", audit=AuditLog(tmp_path / "s-audit"))
    box = ScreenOnlyBox(tmp_path / "site" / "repo", AuditLog(tmp_path / "update-audit"))
    assert apply_bundle(tmp_path / "rs.tar", pub, box, updates, tmp_path / "stage")["ok"]
    assert arrived_in_bundle(tmp_path / "site" / "repo", "GZQO", "1.0.1")
    assert origin["part_sha256"] in RulesetRepo(tmp_path / "site" / "repo").tag_message("GZQO/v1.0.1")

    on_site = _screen(site, "1.0.1")
    assert on_site == on_head  # every listed patient, tier and criterion answer
    assert on_site != as_shipped  # and not what a rule set already on a box would give
    mrns = {pid_for_mrn(KEY, r["mrn"]) for r in csv.DictReader((synth_dir / "site-a" / "patient.csv").open())}
    assert set(on_head) <= mrns  # the same synthetic hospital's patients
