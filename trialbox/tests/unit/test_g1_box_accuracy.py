"""The box run's accuracy group and its validation mode (tools/box_run.py, deploy/gcp/box_vm.py, the VM script,
tools/public_accuracy/plan.py RUN_A, onbox.py, the item builder's per-set offsets). Synthetic data only."""

from __future__ import annotations

import base64
import csv
import importlib.util
import itertools
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from tools import box_run
from tools.complete_run import BOOT_HOURS, PRICE_PER_HOUR, SINGLE_CALL_CPS
from tools.public_accuracy import plan, sets, site

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("box_vm", ROOT / "deploy" / "gcp" / "box_vm.py")
assert _spec and _spec.loader
box_vm = importlib.util.module_from_spec(_spec)
sys.modules["box_vm"] = box_vm
_spec.loader.exec_module(box_vm)

VM_SCRIPT = (ROOT / "deploy" / "gcp" / "box-install-run.sh").read_text(encoding="utf-8")


# ---------------------------------------------------------------- Run A and its estimate
def test_run_a_is_the_plans_derivation() -> None:
    """The counts are public-accuracy-run-plan.md section 1's (table() on the pinned data), the hours its rule."""
    a = plan.RUN_A
    assert sum(s.protocols for s in a) == 1615
    assert (sum(s.compile_calls_low for s in a), sum(s.compile_calls_high for s in a)) == (1615, 19359)
    assert sum(s.screen_calls_high for s in a) == 49000
    lo = sum(plan.acc_hours(s)["hours_low"] for s in a)
    hi = sum(plan.acc_hours(s)["hours_high"] for s in a)
    assert (round(lo, 2), round(hi, 2)) == (2.95, 18.2)
    trec = plan.acc_set("trec")
    want_hi = trec.compile_calls_high / SINGLE_CALL_CPS + trec.screen_calls_high / plan.SCREEN_CPS_16 + 803 * 4.1
    assert plan.acc_hours(trec)["hours_high"] == round(want_hi / 3600, 2)
    assert [s.name for s in a if not s.screen] == ["tfda", "jrct", "chia"]
    with pytest.raises(ValueError):
        plan.acc_set("bioscope")


def test_the_vm_script_agrees_with_run_a_on_compile_only_sets_and_fetch_sets() -> None:
    co = re.search(r"acc_compile_only\(\) \{ case \"\$1\" in ([a-z|]+)\)", VM_SCRIPT)
    assert co and set(co.group(1).split("|")) == {s.name for s in plan.RUN_A if not s.screen}
    assert "trec2023) echo trec" in VM_SCRIPT
    assert all(s.fetch in (s.name, "trec") for s in plan.RUN_A)


def test_the_estimate_of_a_validation_start_with_run_a_has_low_and_high_with_sources() -> None:
    e = box_run.estimate(["start", "acc"], "validation")
    (x,) = e["launches"]
    acc = [r for r in x["rows"] if r["group"] == "acc"]
    assert [r["step"].split(":")[0] for r in acc[1:]] == [s.name for s in plan.RUN_A]
    assert all(r["kind"] == "plan" and "public-accuracy-run-plan.md" in r["source"] for r in acc[1:])
    assert acc[0]["kind"] == "unknown" and acc[0]["seconds"] is None
    # the known part: the VM start, the measured model loads and canary of the start group, Run A low and high
    assert x["known_hours"] < x["known_hours_high"]
    assert round(sum(r["seconds"] for r in acc[1:]) / 3600, 2) == pytest.approx(2.95, abs=0.02)
    assert round(sum(r["seconds_high"] for r in acc[1:]) / 3600, 2) == pytest.approx(18.2, abs=0.02)
    assert x["usd_known_high_spot"] == round(x["known_hours_high"] * PRICE_PER_HOUR, 2)
    assert x["cap_hours"] == 4 + math.ceil(18.2 * box_run.ACC_CAP_FACTOR)
    assert x["rows"][0]["step"] == "VM start" and x["rows"][0]["seconds"] == BOOT_HOURS * 3600
    assert any("install.sh --answers" in r["step"] for r in x["rows"])
    assert e["mode"] == "validation" and len(e["acc_sets"]) == len(plan.RUN_A)
    txt = box_run.render_estimate(e)
    assert "known part" in txt and " to " in txt and "Mode: validation" in txt


def test_only_takes_some_sets_in_the_given_order_and_scales_them() -> None:
    # the given order (cheapest first, the lead's ruling of 2026-11-15); Run A's order without --only
    assert box_run.acc_sets("tcga:100,jmed") == [("tcga", 100), ("jmed", 300)]
    assert [n for n, _ in box_run.acc_sets()] == [a.name for a in plan.RUN_A]
    assert box_run.acc_cap_hours(box_run.acc_sets("trec:3000,trec2023,tfda,sigir")) == box_run.ACC_CAP_MAX_HOURS == 24
    small = box_run.acc_cap_hours([("tcga", 50)])
    assert small == max(1, math.ceil(plan.acc_hours(plan.acc_set("tcga"))["hours_high"] * 0.1 * 1.3))
    for bad in ("nope", "tcga:x", "tcga:0"):
        with pytest.raises(ValueError):
            box_run.acc_sets(bad)
    with pytest.raises(ValueError):
        box_run.estimate(["acc"], "staging")


def test_metadata_in_validation_mode(tmp_path: Path) -> None:
    build = {
        "tb-src": "gs://b/s",
        "tb-commit": "c",
        "tb-release-id": "val-c",
        "tb-release-seq": "1",
        "tb-out": "gs://b/o",
    }
    names = box_run.metadata(["build"], build, tmp_path / "b", "validation")
    assert "tb-vendor-key-secret" not in names and (tmp_path / "b" / "tb-mode").read_text() == "validation"
    with pytest.raises(ValueError, match="tb-vendor-key-version"):
        box_run.metadata(["build"], build, tmp_path / "p", "production")
    with pytest.raises(ValueError, match="tb-acc-tools"):
        box_run.metadata(["acc"], {}, tmp_path / "a")
    box_run.metadata(["acc"], {"tb-acc-tools": "gs://b/t.tgz"}, tmp_path / "c", "validation", "sigir:20,tfda:4")
    assert (tmp_path / "c" / "tb-acc-sets").read_text() == "sigir:20 tfda:4"
    assert (
        int((tmp_path / "c" / "tb-max-minutes").read_text())
        == box_run.acc_cap_hours([("sigir", 20), ("tfda", 4)]) * 60 - 5
    )


def test_the_validation_check_answers_with_its_blockers() -> None:
    vc = box_run.validation_check()
    assert set(vc) >= {"can_run", "blockers", "calls", "pair_status", "tripwire_settings_declared"}
    assert vc["can_run"] is (not vc["blockers"])
    assert vc["environment"] == "VALIDATION" and vc["pair_status"]


# ---------------------------------------------------------------- the item builder's per-set offsets
def _bundle(name: str = "sigir") -> sets.Bundle:
    b = sets.Bundle(name)
    b.patients = {f"{name}:1": sets.Patient(f"{name}:1", "en", "A woman with diabetes (synthetic).", 60, "F")}
    b.trials = {"NCT90000001": sets.Trial("NCT90000001", "en", "Synthetic", ["Diabetes"], ["Pregnancy"])}
    b.pairs = [sets.Pair(f"{name}:1", "NCT90000001", "eligible", name)]
    return b


def test_sets_on_one_box_keep_their_own_ids(tmp_path: Path) -> None:
    from datetime import date

    mrn0, pi0, pre = site.SET_OFFSETS["sigir"]
    site.build(_bundle(), tmp_path, ref=date(2026, 11, 20), mrn0=mrn0, pi0=pi0, rs_prefix=pre)
    ids = json.loads((tmp_path / "gold" / "ids.json").read_text(encoding="utf-8"))
    assert ids["rulesets"] == {"NCT90000001": "SNCT90000001"} and ids["investigators"] == {"SNCT90000001": f"P{pi0}"}
    assert ids["patients"] == {"sigir:1": str(mrn0 + 1)}
    appt = list(csv.DictReader((tmp_path / "site" / "hospital" / "appointment.csv").open(encoding="utf-8-sig")))
    assert appt and all(a["appt_datetime"] > "2026-11-20" for a in appt), "booked after the box's day"
    starts = sorted(v[0] for v in site.SET_OFFSETS.values())
    assert all(b - a >= 100000 for a, b in itertools.pairwise(starts))
    assert len({v[2] for v in site.SET_OFFSETS.values()}) == len(site.SET_OFFSETS)
    assert site.ruleset_ids({"TFDA:X": _bundle().trials["NCT90000001"]}, "F") == {"TFDA:X": "FTW0001"}
    with pytest.raises(ValueError):
        site.ruleset_ids(_bundle().trials, "TOO-LONG-PREFIX")
    with pytest.raises(ValueError):
        site.build(_bundle(), tmp_path / "x", mrn0=99999999)


# ---------------------------------------------------------------- the VM helper's accuracy pieces
def test_classify_redact_and_list_rows() -> None:
    assert box_vm.classify("ir_extract: (tb_refusal phi_tripwire: PHI tripwire hit)") == "refused_by_tripwire"
    assert box_vm.classify({"message": "no_eligible_build: champion only"}) == "refused_by_gateway"
    assert box_vm.classify("reportlab: 'NoneType' object") == "failed"
    out = "".join(box_vm.redact(["ok line\n", "    admin password: hunter2-synthetic\n", "enrolment code: 1\n"]))
    assert "hunter2" not in out and out.count("[redacted]") == 2 and "ok line" in out
    rows = box_vm.list_rows(
        {"rows": [{"pid": "p1", "tier": "high", "criteria": [{"id": "c1", "verdict": "fail", "basis": "pair",
                                                               "evidence": {"quote": "q"}}]}, {"tier": "x"}]},
    )  # fmt: skip
    assert rows == [{"pid": "p1", "tier": "high", "actions": [], "verdicts": [
        {"id": "c1", "verdict": "fail", "basis": "pair", "quote": "q"}]}]  # fmt: skip
    assert box_vm.list_rows([{"pid": "p2"}], "excluded")[0]["tier"] == "excluded"
    # F25: the product's excluded list names the excluding criteria with no "verdict" key, evidence flattened
    ex = box_vm.list_rows({"rows": [{"pid": "p3", "criteria": [{"id": "c2", "source": "coded", "quote": "E11"}]}]},
                          "excluded")  # fmt: skip
    assert ex[0]["verdicts"] == [{"id": "c2", "verdict": "fail", "basis": "coded", "quote": "E11"}]


def test_merge_feed_keeps_one_header_and_each_row_once(tmp_path: Path) -> None:
    for n, rows in (("a", [["1", "x"], ["2", "y"]]), ("b", [["2", "y"], ["3", "z"]])):
        (tmp_path / n).mkdir()
        with (tmp_path / n / "patient.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            csv.writer(fh).writerows([["mrn", "v"], *rows])
    res = box_vm.merge_feed(tmp_path / "into", [tmp_path / "a", tmp_path / "b"])
    assert res["tables"] == {"patient.csv": 3}
    with (tmp_path / "b" / "patient.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        csv.writer(fh).writerows([["mrn", "other"], ["4", "w"]])
    with pytest.raises(ValueError, match="header"):
        box_vm.merge_feed(tmp_path / "into2", [tmp_path / "a", tmp_path / "b"])


def test_the_routes_verdict_needs_the_pair_and_the_compile() -> None:
    ok_rows = [
        {"role": "judge", "class": "D3", "routes": True,
         "builds": [{"alias": "j-workhorse", "routes": True}, {"alias": "v-verifier", "routes": True}]},
        {"role": "extract_criteria", "class": "D1", "routes": True, "builds": []},
        {"role": "concept_select", "class": "D1", "routes": True, "builds": []},
    ]  # fmt: skip
    assert box_vm.routes_verdict({"routes": ok_rows}, {})["routes_ok"] is True
    one = json.loads(json.dumps(ok_rows))
    one[0]["builds"][1]["routes"] = False
    assert "only ['j-workhorse']" in box_vm.routes_verdict({"routes": one}, {})["blocked"][0]
    ceiling = [{"role": "judge", "class": "D3", "routes": False, "why": "ceiling D2"}, *ok_rows[1:]]
    v = box_vm.routes_verdict({"routes": ceiling, "environment": "VALIDATION"}, {"embedder": "hash"})
    assert v["routes_ok"] is False and "ceiling D2" in v["blocked"][0] and v["embedder"] == "hash"


class FakeBox:
    """The installed box as acc_set reaches it: one job per message id, the tripwire on a named protocol."""

    def __init__(self, tripwire: str = "") -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.by_mid: dict[str, str] = {}
        self.sent: list[str] = []
        self.tripwire = tripwire

    def call(self, svc: str, cmd: str, a: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        a = a or {}
        if cmd == "send":
            kind, rs = a["subject"].split()[:2]
            if a["mid"] not in self.by_mid:
                jid = f"j{len(self.jobs) + 1}"
                self.by_mid[a["mid"]] = jid
                fail = kind == "FEAS" and rs == self.tripwire
                self.jobs[jid] = {"kind": kind, "rs": rs, "fail": fail, "subject": a["subject"], "from": a["from"]}
                self.sent.append(f"{kind} {rs}")
            return {"action": "job", "job": self.by_mid[a["mid"]], "reason": ""}
        if cmd == "wait":
            j = self.jobs[a["job"]]
            st = "failed" if j["fail"] else ("awaiting_approval" if j["kind"] == "FEAS" else "done")
            err = "ir_extract: tb_refusal phi_tripwire" if j["fail"] else None
            return {"job": a["job"], "state": st, "error": err, "ruleset_version": "1.0.0", "waited": "ended"}
        if cmd == "fetch":
            j = self.jobs[a["job"]]
            if j["kind"] == "FEAS" and not j["fail"]:
                import io
                import zipfile

                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as z:
                    z.writestr(f"{j['rs']}/ir/exc-1.json", json.dumps({"id": "exc-1", "kind": "exclusion",
                                                                          "text": {"source": "Pregnancy"}}))  # fmt: skip
                return {"files": {f"review_{j['rs']}_v1.0.0_r1.xlsx": base64.b64encode(b"x").decode(),
                                  f"ruleset_{j['rs']}_v1.0.0-draft.zip": base64.b64encode(buf.getvalue()).decode()}}  # fmt: skip
            if j["kind"] == "SCREEN":
                doc = {"rows": [{"pid": "boxpid-1", "tier": "high", "criteria": [{"id": "exc-1", "verdict": "pass"}]}]}
                return {"files": {f"candidate_list_{j['rs']}_v1.0.0.json": base64.b64encode(json.dumps(doc).encode()).decode()}}  # fmt: skip
            return {"files": {}}
        if cmd == "pidmap":
            return {m: f"boxpid-{i}" for i, m in enumerate(a["mrns"], 1)}
        raise AssertionError(cmd)


def _built(tmp_path: Path, trials: int = 2) -> Path:
    b = _bundle()
    for i in range(2, trials + 1):
        b.trials[f"NCT9000000{i}"] = sets.Trial(f"NCT9000000{i}", "en", "Synthetic", ["Asthma"], [])
    site.build(b, tmp_path / "built")
    return tmp_path / "built"


def test_acc_set_counts_the_tripwire_and_never_mails_a_protocol_twice(tmp_path: Path) -> None:
    built = _built(tmp_path)
    box = FakeBox(tripwire="NCT90000002")
    kw = {"sender": "crc1@hospa.test", "reviewer": "pi@hospa.test", "run_id": "r1", "compile_only": False, "job_s": 5}
    res = box_vm.acc_set("sigir", built, tmp_path / "work", box, **kw)
    assert res["counts"]["refused_by_tripwire"] == 1 and res["counts"]["screened"] == 1 and res["pass"] is False
    assert box.sent == ["FEAS NCT90000001", "APPROVE NCT90000001", "SCREEN NCT90000001", "FEAS NCT90000002"]
    screen = next(j for j in box.jobs.values() if j["kind"] == "SCREEN")
    ids = json.loads((built / "gold" / "ids.json").read_text(encoding="utf-8"))
    assert screen["subject"] == f"SCREEN NCT90000001 pract={ids['investigators']['NCT90000001']}"
    assert next(j for j in box.jobs.values() if j["kind"] == "APPROVE")["from"] == "pi@hospa.test"
    answers = json.loads((tmp_path / "work" / "answers.json").read_text(encoding="utf-8"))
    assert answers["NCT90000001"]["patients"]["boxpid-1"]["tier"] == "high"
    assert answers["NCT90000001"]["draft"][0]["text"] == "Pregnancy"
    assert answers["NCT90000002"]["outcome"] == "refused_by_tripwire"
    # resumed (a pre-emption after the set finished): nothing is mailed again
    box_vm.acc_set("sigir", built, tmp_path / "work", box, **kw)
    assert len(box.sent) == 4


def test_acc_set_compile_only_and_a_resume_mid_protocol(tmp_path: Path) -> None:
    built = _built(tmp_path)
    box = FakeBox()
    work = tmp_path / "work"
    work.mkdir()
    # the VM was cut after the first protocol's FEAS was mailed and recorded: the resume waits for that job
    first = box.call("mail-gateway", "send", {"subject": "FEAS NCT90000001", "from": "c@x", "mid": "<acc-r2-tfda-NCT90000001-feas@trialbox.invalid>"})  # fmt: skip
    (work / "progress.json").write_text(
        json.dumps({"NCT90000001": {"ruleset": "NCT90000001", "feas_job": first["job"]}})
    )
    res = box_vm.acc_set("tfda", built, work, box, sender="c@x", reviewer="r@x", run_id="r2", compile_only=True,
                         job_s=5)  # fmt: skip
    assert res["counts"] == {"protocols": 2, "compiled": 2, "refused_by_tripwire": 0, "patients_answered": 0}
    assert res["pass"] is True and box.sent == ["FEAS NCT90000001", "FEAS NCT90000002"]


def test_a_redone_set_screens_under_the_approval_of_the_attempt_before(tmp_path: Path) -> None:
    """F29: the box keeps an approved ruleset version; FEAS of it again fails with no workbook. The redo screens under
    the earlier attempt's approval (same version), never mails a new APPROVE, and says so."""
    built = _built(tmp_path, trials=1)
    box = FakeBox(tripwire="NCT90000001")  # this FEAS fails with no files, as the box's did
    old = tmp_path / "old"
    old.mkdir()
    (old / "progress.json").write_text(json.dumps({"NCT90000001": {
        "approve": "done", "approve_job": "jA", "version": "1.0.0", "draft": [{"id": "exc-1", "text": "Pregnancy"}]}}))  # fmt: skip
    box.jobs["jA"] = {"kind": "APPROVE", "rs": "NCT90000001", "fail": False, "subject": "APPROVE", "from": "pi"}
    kw = {"sender": "c@x", "reviewer": "pi@x", "run_id": "r1-r2", "compile_only": False, "job_s": 5}
    nothing = tmp_path / "nothing"  # a newer attempt that approved nothing (its own FEAS failed)
    nothing.mkdir()
    (nothing / "progress.json").write_text(json.dumps({"NCT90000001": {"feas": "failed", "version": "1.0.0"}}))
    box_vm.acc_set("sigir", built, tmp_path / "work", box, earlier=[nothing, old], **kw)
    a = json.loads((tmp_path / "work" / "answers.json").read_text(encoding="utf-8"))["NCT90000001"]
    assert box.sent == ["FEAS NCT90000001", "SCREEN NCT90000001"] and a["approved_in"]
    assert a["outcome"] == "screened" and a["draft"][0]["text"] == "Pregnancy" and a["patients"]
    # without the earlier attempt the failed FEAS ends the protocol, as before
    box2 = FakeBox(tripwire="NCT90000001")
    box_vm.acc_set("sigir", built, tmp_path / "work2", box2, **kw)
    assert box2.sent == ["FEAS NCT90000001"]


def test_acc_score_joins_through_the_boxs_pseudonyms(tmp_path: Path) -> None:
    d = tmp_path / "out"
    sd = d / "acc" / "sigir"
    built = _built(sd, trials=1)
    ids = json.loads((built / "gold" / "ids.json").read_text(encoding="utf-8"))
    (mrn,) = ids["patients"].values()
    (sd / "work").mkdir()
    (sd / "work" / "pidmap.json").write_text(json.dumps({mrn: "boxpid-x"}))
    (sd / "work" / "answers.json").write_text(json.dumps({"NCT90000001": {"screen": "done", "patients": {
        "boxpid-x": {"tier": "excluded", "verdicts": []}}}}))  # fmt: skip
    res = box_run.acc_score(d)
    assert res["sigir"]["scored"] is True
    row = json.loads((sd / "score.json").read_text())["pairs"]["rows"][0]
    assert row["excluded"] == 1 and row["unanswered"] == 0, "the box's answer reached the gold by chart number"


def test_the_results_name_the_mode_and_the_accuracy_counts(tmp_path: Path) -> None:
    (tmp_path / "parts").mkdir()
    (tmp_path / "records").mkdir()

    def part(step: str, **detail: Any) -> None:
        p = {"step": step, "status": "done", "seconds": 1.0, "minutes": 0.02, "detail": detail}
        if "pass_" in detail:
            p["pass"] = detail.pop("pass_")
        (tmp_path / "parts" / f"{step}.json").write_text(json.dumps(p))

    part("01-bundle", refused=[], mode="validation", not_a_release=True)
    part("03-wizard", environment="VALIDATION")
    part("51-acc-settings", tripwire="on: no setting used", limits={"after": {"rate_limits_per_day": {"FEAS": 0}}})
    part("60-acc-jmed", counts={"protocols": 2, "screened": 1, "refused_by_tripwire": 1}, uploaded=True, pass_=False)
    (tmp_path / "records" / "acc-routes.json").write_text(json.dumps(
        {"environment": "VALIDATION", "served_prompts": ["judge@5"], "embedder": "hash", "routes_ok": True}))  # fmt: skip
    (tmp_path / "state.json").write_text(json.dumps({"ended": "TB-BOX-RUN-COMPLETE"}))
    r = box_run.results(tmp_path)
    pv = r["provenance"]
    assert pv["mode"] == "validation" and pv["not_a_release"] is True and pv["environment"] == "VALIDATION"
    assert pv["served_prompts_in_environment"] == ["judge@5"] and pv["tripwire"] == "on: no setting used"
    g2 = {c["check"]: c["pass"] for c in r["tests"]["G-2 validation start"]}
    assert g2["the box says VALIDATION (deploy/.env, after install.sh --answers)"] is True
    acc = r["tests"]["Public accuracy on the installed box (scores: acc-score, outside the box)"]
    jm = next(c for c in acc if c["check"].startswith("jmed"))
    assert jm["pass"] is False and jm["detail"]["refused_by_tripwire"] == 1


def test_onbox_is_one_program_named_for_the_stand_in_and_imports_no_lane_g_tool() -> None:
    src = (ROOT / "tools" / "public_accuracy" / "onbox.py").read_text(encoding="utf-8")
    assert src.splitlines()[0] == "# tb-boxrun: acc"
    assert not re.search(r"^\s*(from|import) tools\b", src, re.M), "the box's image has no lane G tool"
    assert set(re.findall(r'"(\w+)": cmd_', src)) == {"env", "send", "wait", "fetch", "routes", "embedder",
                                                      "pidmap", "audit", "traces"}  # fmt: skip


def test_the_validation_sites_answers_make_a_validation_box_through_the_real_wizard(tmp_path: Path) -> None:
    import yaml

    from tools import settings_wizard

    answers = yaml.safe_load((ROOT / "deploy" / "gcp" / "validation-site-answers.yaml").read_text(encoding="utf-8"))
    settings, env, _ = settings_wizard.build(answers, [])
    settings_wizard.write(settings, env, tmp_path / "settings.yaml", tmp_path / ".env")
    lines = (tmp_path / ".env").read_text(encoding="utf-8").splitlines()
    assert "TB_ENV=VALIDATION" in lines and "TB_MAIL_PER_RECIPIENT_PER_DAY=0" in lines
    assert "TB_JOBS_PER_SENDER_PER_DAY=0" in lines, "the declared daily job limit lifted for the run (D-775)"
    assert any(x.startswith("TB_MAIL_AUTHSERV_ID=mx.") for x in lines), "the mail intake can authenticate a sender"
    assert settings["reviewers"] and settings["allowlist"]["senders"]
    assert "password" not in json.dumps(answers).lower(), "no secret in the committed answers"
    box_run.metadata(["start"], {"tb-bundle": "gs://b/x", "tb-bundle-sha256": "0" * 64, "tb-vendor-pub": "gs://b/p"},
                     tmp_path / "m", "validation")  # fmt: skip


def test_acc_tools_is_the_committed_tools_at_head(tmp_path: Path) -> None:
    import tarfile

    res = box_run.acc_tools(tmp_path / "acc-tools.tgz")
    assert re.fullmatch(r"[0-9a-f]{40}", res["commit"])
    with tarfile.open(tmp_path / "acc-tools.tgz") as t:
        names = set(t.getnames())
    for want in ("tools/__init__.py", "tools/public_accuracy/onbox.py", "tools/public_accuracy/site.py",
                 "tools/public_site.py", "tools/fetch_pinned.py", "eval/criterion_ml/annotations.jsonl"):  # fmt: skip
        assert want in names, want
    assert not any(n.startswith(("services/", "libs/")) for n in names), "only lane G's tools, never the product"
