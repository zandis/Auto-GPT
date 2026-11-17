"""Lane G's fixes after the integrator's launch P1b (the three reviews; integrator's comment on PR #649, 2026-11-16):
the driver (D1-D8), the benchmark builder (B1-B3) and the scorer (S1-S4). Synthetic data only; no VM, no network.

The VM script's gate (D2) is rehearsed end to end by tests/unit/test_g1_box_install_run.py's cases gate-closed,
gate-401 and gate-never (tests/rehearsal/box-run); the text checks here pin what those cases cannot see."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_g1_box_accuracy import FakeBox, _built, box_vm
from tools import box_run, public_site
from tools.public_accuracy import onbox, score, sets, site

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
VM_SCRIPT = (ROOT / "deploy" / "gcp" / "box-install-run.sh").read_text(encoding="utf-8")
DRIVER = (ROOT / "deploy" / "gcp" / "box-run.sh").read_text(encoding="utf-8")
KW: dict[str, Any] = {"sender": "c@x", "reviewer": "pi@x", "run_id": "r1", "compile_only": False, "job_s": 3600}


# ---------------------------------------------------------------- D1: a protocol filter that matches nothing
def test_d1_acc_set_refuses_a_filter_naming_an_id_the_set_lacks(tmp_path: Path) -> None:
    built = _built(tmp_path, trials=2)
    with pytest.raises(ValueError, match="G2TCGA-BRCA, not a protocol of set sigir"):
        box_vm.acc_set("sigir", built, tmp_path / "work", FakeBox(), protocols=["G2TCGA-BRCA"], **KW)
    for p in (built / "site" / "protocols").glob("*.txt"):
        p.unlink()
    with pytest.raises(ValueError, match="no protocol to run"):
        box_vm.acc_set("sigir", built, tmp_path / "work", FakeBox(), **KW)


def test_d1_the_local_listing_shows_the_tag_prefix_and_refuses_a_wrong_id() -> None:
    r = box_run.acc_ids("tcga", "m2", "tcga:G2TCGA-BRCA")
    assert r["sets"]["tcga"]["prefix"] == "Gm2" and "Gm2TCGA-BRCA" in r["sets"]["tcga"]["ids"]
    assert any("G2TCGA-BRCA not among its ids (prefix 'Gm2'" in x for x in r["refused"])
    assert any("matches no protocol" in x for x in r["refused"])
    assert box_run.acc_ids("tcga", "m2", "tcga:Gm2TCGA-BRCA")["refused"] == []
    assert box_run.acc_ids("tcga", "", "jmed:MJMED-DM")["refused"][0].startswith("jmed:MJMED-DM: set jmed is not")
    # a sampled set with no local cache: its ids are not known here
    r = box_run.acc_ids("sigir", "m2", "sigir:SNCT00163709", cache=Path("/nonexistent"))
    # D-1125: a set whose ids are not known here takes no filter at all (it took any id with the prefix before)
    assert r["sets"]["sigir"]["ids"] is None and r["sets"]["sigir"]["prefix"] == "Sm2"
    assert r["refused"] and "cannot be checked here" in r["refused"][0]
    assert box_run.main(["acc-ids", "--only", "tcga", "--rs-tag", "m2", "--protocols", "tcga:G2TCGA-BRCA"]) == 4


def test_d1_the_launch_stops_before_the_vm_starts(tmp_path: Path) -> None:
    vals = {"tb-acc-tools": "x", "tb-acc-rs-tag": "m2", "tb-acc-protocols": "tcga:G2TCGA-BRCA"}
    with pytest.raises(ValueError, match="--acc-protocols"):
        box_run.metadata(["acc"], vals, tmp_path, "validation", "tcga")
    assert not (tmp_path / "tb-acc-sets").exists()
    vals["tb-acc-protocols"] = "tcga:Gm2TCGA-BRCA"
    assert "tb-acc-protocols" in box_run.metadata(["acc"], vals, tmp_path, "validation", "tcga")
    # the driver asks before the estimate, the bucket and the VM, on a launch and on a resume
    i, j = DRIVER.index("br acc-ids"), DRIVER.index('if [ "$ESTIMATE" = 1 ]')
    assert i < j < DRIVER.index("gc_start ||")


# ---------------------------------------------------------------- D2: the gate step
def test_d2_the_gate_is_read_with_the_token_once_first_and_waits_at_most_480_s() -> None:
    body = VM_SCRIPT[VM_SCRIPT.index("d_gate() {") : VM_SCRIPT.index("# qualify, promote, resolve.")]
    # D-1125: from the console's container, the caller the orchestrator lets onto GET /models (the mail gateway got
    # a 403 on launch P2); tests/unit/test_h13_driver_callers.py holds it against the orchestrator's own table
    assert "in_svc console" in body and "in_svc mail-gateway" not in body and "auth_headers()" in body
    assert "docker run" not in body and "urllib.request" not in body  # never a bare container without the token
    assert body.index("d_gate_read once") < body.index("dc restart orchestrator")
    assert '"allows_block": true' in body and "TB_GATE_WAIT_S:-480" in body and "1500" not in body
    assert "(401, 403)" in body and "SystemExit(3)" in body
    assert "TB-GATE-REFUSED" in body and "TB-GATE-CLOSED" in body and "return 1" in body


# ---------------------------------------------------------------- D3: --resume keeps and takes --acc-rs-tag
def _resume(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """``box-run.sh --dry-run --no-wait --resume`` of a run whose launch had tag m2 (nothing is called: gcloud is
    printed)."""
    out = tmp_path / "run"
    if not out.exists():  # the launch's own files, once
        (out / "md").mkdir(parents=True)
        (out / "metadata-keys").write_text("startup-script tb-helper tb-acc-sets tb-acc-rs-tag")
        (out / "md" / "tb-acc-rs-tag").write_text("m2")
        (out / "md" / "tb-acc-sets").write_text("tcga:20")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PY": sys.executable, "TB_BUCKET": "gs://x",
           "TB_BOXRUN_DIR": str(out)}  # fmt: skip
    return subprocess.run([str(ROOT / "deploy" / "gcp" / "box-run.sh"), "--dry-run", "--no-wait", "--resume", "box-r1",
                           *args], env=env, capture_output=True, text=True, check=False)  # fmt: skip


def test_d3_resume_takes_the_rs_tag_it_is_given_and_keeps_the_launchs(tmp_path: Path) -> None:
    r = _resume(tmp_path, "--acc-rs-tag", "m3")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "run" / "md" / "tb-acc-rs-tag").read_text() == "m3" and "tb-acc-rs-tag=" in r.stdout
    r = _resume(tmp_path)
    assert r.returncode == 0 and (tmp_path / "run" / "md" / "tb-acc-rs-tag").read_text() == "m3"
    assert "tb-acc-rs-tag=" in r.stdout  # kept: the run's sets were built with it


def test_d1_a_resume_with_a_filter_of_the_wrong_tag_starts_nothing(tmp_path: Path) -> None:
    r = _resume(tmp_path, "--acc-protocols", "tcga:G2TCGA-BRCA")
    assert r.returncode == 2 and "refused (no VM started)" in r.stderr and "prefix 'Gm2'" in r.stderr
    assert "instances start" not in r.stdout


# ---------------------------------------------------------------- D4: the set's budget
class SlowFeasBox(FakeBox):
    """A FEAS whose wait runs out while ``slow`` is set (the set's budget cut it)."""

    slow = True

    def call(self, svc: str, cmd: str, a: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        r = super().call(svc, cmd, a, timeout)
        if cmd == "wait" and self.slow and self.jobs[(a or {})["job"]]["kind"] == "FEAS":
            r["state"], r["waited"] = "running", "timeout"
        return r


def test_d4_a_protocol_cut_by_the_budget_is_not_run_time_budget_and_a_resume_takes_it_up(tmp_path: Path) -> None:
    built, work = _built(tmp_path, trials=1), tmp_path / "work"
    box = SlowFeasBox()
    res = box_vm.acc_set("sigir", built, work, box, deadline_s=30, min_start_s=0, **KW)
    a = json.loads((work / "progress.json").read_text())["NCT90000001"]
    assert a["outcome"] == "not_run_time_budget" and "feas_job" in a and res["counts"].get("timeout_feas") is None
    box.slow = False  # a resume with time left: the same job is waited for, never mailed again
    res = box_vm.acc_set("sigir", built, work, box, deadline_s=0, min_start_s=0, **KW)
    assert res["counts"]["screened"] == 1 and box.sent.count("FEAS NCT90000001") == 1


def test_d4_no_protocol_is_started_close_to_the_deadline(tmp_path: Path) -> None:
    built, box = _built(tmp_path, trials=2), FakeBox()
    res = box_vm.acc_set("sigir", built, tmp_path / "work", box, deadline_s=60, min_start_s=600, **KW)
    assert res["counts"]["not_run_time_budget"] == 2 and box.sent == [] and res["pass"] is False


def test_d4_a_wait_that_runs_out_on_its_own_limit_stays_timeout_feas(tmp_path: Path) -> None:
    built = _built(tmp_path, trials=1)
    res = box_vm.acc_set("sigir", built, tmp_path / "work", SlowFeasBox(), **{**KW, "job_s": 5})
    assert res["counts"]["timeout_feas"] == 1


# ---------------------------------------------------------------- D5: the audit's since, as instants
def test_d5_the_audit_since_is_compared_as_instants_in_the_site_zone() -> None:
    def rec(ts: str) -> str:
        return json.dumps({"ts": ts, "event": "llm.gateway.call", "prompt_version": "judge@3"})

    # the set started 11:00 UTC = 19:00 in Asia/Taipei; a string compare let 12:00+08:00 (04:00 UTC) in
    lines = [rec("2026-11-16T12:00:00.000+08:00"), rec("2026-11-16T18:59:59.000+08:00"),
             rec("2026-11-16T19:00:01.000+08:00"), rec("2026-11-16T21:30:00.000+08:00"), rec("not a time")]  # fmt: skip
    got = onbox.audit_counts(lines, "2026-11-16T11:00:00", "Asia/Taipei")
    assert got["calls_by_prompt"] == {"judge@3": 2} and got["time_unreadable"] == 1
    # a record with no offset is read in the site's zone
    assert onbox.audit_counts([rec("2026-11-16T19:30:00")], "2026-11-16T11:00:00", "Asia/Taipei")["calls_by_prompt"]
    assert not onbox.audit_counts([rec("2026-11-16T18:30:00")], "2026-11-16T11:00:00", "Asia/Taipei")["calls_by_prompt"]
    assert onbox.audit_counts(lines[:1], "", "Asia/Taipei")["calls_by_prompt"] == {"judge@3": 1}


# ---------------------------------------------------------------- D6: nothing silent, nothing cut
def test_d6_a_give_up_is_said_and_recorded_and_answers_keep_approve_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real, n = box_vm._answers, {"calls": 0}

    def flaky(work: Path, prog: dict[str, Any]) -> None:
        n["calls"] += 1
        if n["calls"] <= 20:
            raise RuntimeError("dictionary changed size during iteration")
        real(work, prog)

    monkeypatch.setattr(box_vm, "_answers", flaky)

    class ApproveFails(FakeBox):
        def call(self, svc: str, cmd: str, a: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
            r = super().call(svc, cmd, a, timeout)
            if cmd == "wait" and self.jobs[(a or {})["job"]]["kind"] == "APPROVE":
                r["state"], r["error"] = "failed", "approve: the workbook's version is not the draft's"
            return r

    work = tmp_path / "work"
    res = box_vm.acc_set("sigir", _built(tmp_path, trials=1), work, ApproveFails(), **KW)
    assert res["save_give_ups"] == 1 and "gave up writing answers.json after 20 tries" in capsys.readouterr().err
    assert json.loads((work / "save-give-ups.json").read_text())[0]["what"] == "answers.json"
    a = json.loads((work / "answers.json").read_text())["NCT90000001"]
    assert a["approve_error"] == "approve: the workbook's version is not the draft's"


def test_d6_a_files_answer_is_logged_as_size_and_sha_and_services_lines_are_whole() -> None:
    blob = b"PK" + bytes(range(256)) * 40
    line = json.dumps({"job": "j1", "files": {"r-draft.zip": base64.b64encode(blob).decode()}}) + "\n"
    logged = box_vm.log_line(line)
    assert "(cut)" not in logged and hashlib.sha256(blob).hexdigest() in logged and f'"bytes": {len(blob)}' in logged
    assert box_vm.log_line("x" * 9000).endswith(" ... (cut)\n") and box_vm.log_line("short\n") == "short\n"
    svc = VM_SCRIPT[VM_SCRIPT.index("acc_services()") : VM_SCRIPT.index("ACC_UP=false")]
    assert "cut -c1-300" not in svc and "cut -c1-20000" in svc and "head -c" in svc


# ---------------------------------------------------------------- D7: protocols in flight
def test_d7_compile_bound_sets_run_three_at_once_and_the_report_says_how_many(tmp_path: Path) -> None:
    assert [n for n, _ in box_run.acc_sets() if box_run.compile_bound(n)] == ["sigir", "trec2023", "trec", "tfda",
                                                                               "jrct", "chia"]  # fmt: skip
    fn = VM_SCRIPT[VM_SCRIPT.index("acc_streams_default()") :].splitlines()[0]
    assert "sigir|trec|trec2023|tfda|jrct|chia) echo 3" in fn and "*) echo 1" in fn
    assert 'ns=$(acc_streams_default "$name")' in VM_SCRIPT and "--acc-streams" in DRIVER
    res = box_vm.acc_set("sigir", _built(tmp_path, trials=4), tmp_path / "work", FakeBox(), streams=3, **KW)
    assert res["streams"] == 3 and 1 <= res["in_flight_max"] <= 3
    parts = {"60-acc-sigir": {"pass": True, "detail": {"counts": {}, "streams": 3, "in_flight_max": 3}}}
    chk = box_run.acc_checks(None, parts, {})[1]
    assert chk["detail"]["streams"] == 3 and chk["detail"]["in_flight_max"] == 3
    # the report says it in the check's own line (its detail is cut at 400 characters)
    assert chk["check"].endswith("protocols in flight: 3 at most of 3")
    report = box_run.render_results({"provenance": {}, "tests": {"acc": [chk]}})
    assert "protocols in flight: 3 at most of 3" in report


def test_d7_the_run_sets_no_pair_budget_a_notes_only_ruleset_gets_its_populations_pairs() -> None:
    """Lane A2's D-953 (#866) is on master: a notes-only SCREEN with no budget set gets its population's pairs, so
    the run no longer writes TB_SCREEN_MAX_PAIRS (it would cap every coded SCREEN too); it records the box's own."""
    from orchestrator.scenarios import screen_cascade

    body = VM_SCRIPT[VM_SCRIPT.index("step_acc_settings() {") : VM_SCRIPT.index("step_acc_routes() {")]
    assert "envset_box TB_SCREEN_MAX_PAIRS" not in body and "ACC_MAX_PAIRS" not in VM_SCRIPT
    assert "note max_pairs" in body and "D-953" in body
    assert "notes_only_budget(rs, pids)" in Path(screen_cascade.__file__).read_text(encoding="utf-8")
    assert screen_cascade.max_pairs_of({}, {}) is None  # no budget set: the cascade takes notes_only_budget's


# ---------------------------------------------------------------- D8: the source bundle proved
def _repo(path: Path) -> str:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    for m in ("a", "b"):
        subprocess.run(["git", "-C", str(path), "-c", "user.email=t@x", "-c", "user.name=t", "commit", "-q",
                        "--allow-empty", "-m", m], check=True)  # fmt: skip
    return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()  # fmt: skip


def test_d8_the_source_bundle_is_cloned_and_checked_out_before_upload(tmp_path: Path) -> None:
    sha = _repo(tmp_path / "r")
    made = box_run.src_bundle(sha, out=tmp_path / "src.bundle", root=tmp_path / "r")
    assert made["ok"] is True and made["head"] == sha
    assert box_run.src_bundle(sha, check=tmp_path / "src.bundle", root=tmp_path / "r")["ok"] is True
    bad = box_run.src_bundle("0" * 40, check=tmp_path / "src.bundle", root=tmp_path / "r")
    assert bad["ok"] is False and "checkout" in bad["why"]
    assert box_run.src_bundle(sha, check=tmp_path / "missing.bundle")["ok"] is False
    (tmp_path / "junk.bundle").write_bytes(b"not a bundle")
    assert box_run.src_bundle(sha, check=tmp_path / "junk.bundle")["ok"] is False
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{tmp_path / 'r'}", str(tmp_path / "shallow")],
                   check=True)  # fmt: skip
    sh = box_run.src_bundle(sha, out=tmp_path / "s.bundle", root=tmp_path / "shallow")
    assert sh["ok"] is False and "shallow" in sh["why"]
    assert not subprocess.run(["git", "-C", str(tmp_path / "r"), "for-each-ref", "refs/tb-release", "refs/heads/tb-release-*"],
                              capture_output=True, text=True, check=True).stdout  # fmt: skip
    i = DRIVER.index("br preflight --steps")
    assert i < DRIVER.index('gc storage cp "$SRC_BUNDLE"') < DRIVER.index('gc compute instances start "$VM"', i)


def test_d8_the_bundle_made_here_clones_on_the_vm_and_the_proof_clones_as_the_vm_does(tmp_path: Path) -> None:
    """H-1: #889's bundle named its commit by a ref outside refs/heads, which a plain ``git clone`` (the VM's
    b01-source) does not take: the clone was empty and the checkout failed, while the proof, which fetched every
    ref, said ok. The bundle is now a branch, and the proof clones exactly as the VM does."""
    sha = _repo(tmp_path / "r")
    assert box_run.src_bundle(sha, out=tmp_path / "src.bundle", root=tmp_path / "r")["ok"] is True
    vm = tmp_path / "vm"  # b01-source's own three commands
    subprocess.run(["git", "clone", "-q", str(tmp_path / "src.bundle"), str(vm)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(vm), "checkout", "-q", "--detach", sha], check=True)
    assert subprocess.run(["git", "-C", str(vm), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip() == sha  # fmt: skip
    # a bundle of a ref a clone does not take (as #889 made it) is refused
    subprocess.run(["git", "-C", str(tmp_path / "r"), "update-ref", f"refs/tb-release/{sha}", sha], check=True)
    subprocess.run(["git", "-C", str(tmp_path / "r"), "bundle", "create", str(tmp_path / "old.bundle"),
                    f"refs/tb-release/{sha}"], check=True, capture_output=True)  # fmt: skip
    old = box_run.src_bundle(sha, check=tmp_path / "old.bundle", root=tmp_path / "r")
    assert old["ok"] is False and "checkout" in old["why"]
    short = box_run.src_bundle(sha[:12], check=tmp_path / "src.bundle", root=tmp_path / "r")
    assert short["ok"] is False and "full 40-character commit" in short["why"]


# ---------------------------------------------------------------- H-1: the preflight, every free check at once
def _driver(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """``box-run.sh`` with no gcloud on the PATH, no TB_BUCKET and no credentials (a preflight needs none)."""
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PY": sys.executable, "TMPDIR": str(tmp_path)}
    return subprocess.run([str(ROOT / "deploy" / "gcp" / "box-run.sh"), *args], env=env, capture_output=True,
                          text=True, check=False)  # fmt: skip


def test_h1_the_preflight_refuses_each_option_that_would_fail_on_the_vm() -> None:
    acc, tcga = ["acc"], "tcga"
    assert box_run.launch_checks(acc, {"tb-acc-rs-tag": "m2", "tb-acc-protocols": "tcga:Gm2TCGA-BRCA"}, tcga) == []
    assert any("G2TCGA-BRCA not among its ids (prefix 'Gm2'; ids Gm2TCGA-BRCA" in x
               for x in box_run.launch_checks(acc, {"tb-acc-rs-tag": "m2", "tb-acc-protocols": "tcga:G2TCGA-BRCA"}, tcga))  # fmt: skip
    assert "is empty" in box_run.launch_checks(acc, {"tb-acc-protocols": " "}, tcga)[0]
    assert "letters, digits" in box_run.launch_checks(acc, {"tb-acc-rs-tag": "m 2"}, tcga)[0]
    assert "from 1 to 3" in box_run.launch_checks(acc, {"tb-acc-streams": "tcga:4"}, tcga)[0]
    assert box_run.launch_checks(acc, {"tb-acc-streams": "tcga:5", "tb-site-env": "TB_WORKERS=6"}, tcga) == []
    assert "not in this launch" in box_run.launch_checks(acc, {"tb-acc-streams": "sigir:3"}, tcga)[0]
    assert "seconds" in box_run.launch_checks(acc, {"tb-acc-deadline": "tcga:1h"}, tcga)[0]
    assert box_run.launch_checks(acc, {"tb-acc-deadline": "tcga:900", "tb-acc-min-start": "300"}, tcga) == []
    assert "full 40-character" in box_run.launch_checks(["dev"], {"tb-commit": "3b2f5e38"})[0]
    assert box_run.streams_of("sigir,tcga") == {"sigir": 3, "tcga": 1}
    assert box_run.streams_of("sigir,tcga", "sigir:2") == {"sigir": 2, "tcga": 1}


def test_h1_the_driver_preflight_runs_every_free_check_and_starts_nothing(tmp_path: Path) -> None:
    acc = ["--preflight", "--mode", "validation", "--steps", "start,acc", "--release-id", "val-x", "--only", "tcga",
           "--acc-rs-tag", "m2"]  # fmt: skip
    r = _driver(tmp_path, *acc, "--acc-protocols", "tcga:G2TCGA-BRCA")  # launch P1b's filter
    assert r.returncode == 2 and "refused (no VM started)" in r.stderr and "Gm2TCGA-BRCA" in r.stderr
    r = _driver(tmp_path, *acc, "--acc-protocols", "tcga:Gm2TCGA-BRCA", "--acc-streams", "tcga:9")
    assert r.returncode == 6 and "FAILED" in r.stderr and "tcga:9" in r.stderr
    r = _driver(tmp_path, *acc, "--acc-protocols", "tcga:Gm2TCGA-BRCA")
    assert r.returncode == 0, r.stderr
    assert "every free check passed" in r.stdout and "protocols in flight per set" in r.stderr
    sha = _repo(tmp_path / "r")
    dev = ["--preflight", "--steps", "dev", "--release-id", "dev-x", "--commit", sha]
    r = _driver(tmp_path, *dev)  # the bucket's bundle is never taken unproved
    assert r.returncode == 6 and "--src-bundle FILE is needed" in r.stderr
    assert box_run.src_bundle(sha, out=tmp_path / "src.bundle", root=tmp_path / "r")["ok"]
    r = _driver(tmp_path, *dev, "--src-bundle", str(tmp_path / "src.bundle"))
    assert r.returncode == 0, r.stderr
    (tmp_path / "junk.bundle").write_bytes(b"not a bundle")
    assert _driver(tmp_path, *dev, "--src-bundle", str(tmp_path / "junk.bundle")).returncode == 6
    for out in (r.stdout, r.stderr):  # nothing uploaded, nothing started: not even printed as a dry run would
        assert "storage cp" not in out and "instances start" not in out and "add-metadata" not in out
    # D-1129 (card H-14): a resume has its own free look now (what it would take up); a collect still has none
    r = _driver(tmp_path, "--preflight", "--resume", "box-r1")
    assert r.returncode == 0 and "only in the bucket" in r.stderr and "instances start" not in r.stdout
    assert _driver(tmp_path, "--preflight", "--collect", "box-r1").returncode == 2
    assert "--preflight" in DRIVER[: DRIVER.index("set -euo pipefail")]


# ---------------------------------------------------------------- B1: the birth date
def test_b1_birth_is_the_visit_minus_the_stated_age_months_kept_for_infants(tmp_path: Path) -> None:
    visit, run = date(2026, 3, 10), date(2026, 11, 1)
    born = date.fromisoformat(site.birth_date(visit, 50))
    assert born == date(1976, 3, 10)
    age_at_run = run.year - born.year - ((run.month, run.day) < (born.month, born.day))
    assert age_at_run == 50  # was 51 with 1 July of the year
    assert public_site.stated_age_en("A 6-month-old boy with fever") == (6, "month")
    assert public_site.stated_age_en("a 61-year-old woman") == (61, "year")
    assert (
        public_site.stated_age_ja("生後6か月の女児") == (6, "month") and public_site.stated_age_ja("60歳代男性") is None
    )
    assert site.birth_date(visit, 0, (6, "month")) == "2025-09-10"
    assert site.birth_date(visit, 0, (3, "week")) == "2026-02-17" and site.birth_date(visit, None) == ""
    assert public_site.birth_on(date(2024, 2, 29), 1) == date(2023, 2, 28)
    b = sets.Bundle("sigir")
    text = "A 6-month-old girl with a cough (synthetic)."
    b.patients = {"s:1": sets.Patient("s:1", "en", text, 0, "F", age_stated=sets.stated_age(text))}
    b.trials = {"NCT90000001": sets.Trial("NCT90000001", "en", "Synthetic", ["Cough"], [])}
    site.build(b, tmp_path, ref=run)
    row = (tmp_path / "site" / "hospital" / "patient.csv").read_text(encoding="utf-8-sig").splitlines()[1].split(",")
    enc = (tmp_path / "site" / "hospital" / "encounter.csv").read_text(encoding="utf-8-sig").splitlines()[1].split(",")
    v = date.fromisoformat(enc[2][:10])
    assert row[3] == public_site.birth_on(v, 6, "month").isoformat() and row[3][:4] in (str(v.year - 1), str(v.year))


# ---------------------------------------------------------------- B2: placed age lines
def test_b2_placed_lines_keep_the_unit_and_skip_a_bound_the_protocol_states() -> None:
    inc, _ = sets.placed_lines("2 Months", None, None)
    assert inc == ["Aged 2 months or older"]  # never "Aged 0.17 years or older"
    inc, notes = sets.placed_lines("18 Years", "65 Years", "MALE", ["Adults aged 18 to 65 years", "Asthma"])
    assert inc == ["Male participants only"] and any("left out" in n for n in notes)
    inc, _ = sets.placed_lines("40 Years", None, None, ["Aged 18 years or older", "A score of 40 or more"])
    assert inc == ["Aged 40 years or older"]  # another bound, and a 40 that is not an age


# ---------------------------------------------------------------- B3: the JMED truth from the note
def test_b3_jmed_truth_comes_from_the_chart_the_box_reads() -> None:
    assert sets.jmed_stratum("10年前から糖尿病で内服加療中。", "糖尿病") == "own"
    assert sets.jmed_stratum("父が糖尿病。本人は健康。", "糖尿病") == "family-only"
    assert sets.jmed_stratum("糖尿病はない。", "糖尿病") == "none"
    assert sets.jmed_stratum("母に高血圧。\n高血圧症で降圧薬を服用。", "高血圧") == "own"
    r = {k: "" for k in sets.JMED_NOTE_FIELDS}
    r["ペルソナ_医学的背景"] = "高血圧と糖尿病を長年患っている。"
    assert sets.jmed_stratum(sets.jmed_note(r), "糖尿病") == "own"  # stated in the note, not in 主病名/既往歴/現病歴


# ---------------------------------------------------------------- S1-S4: the scorer
def _ans(rs: str, pats: dict[str, Any], draft: list[dict[str, Any]]) -> dict[str, Any]:
    return {rs: {"ruleset": rs, "draft": draft, "patients": pats, "screen": "done"}}


def test_s1_pair_and_criterion_label_conflicts_are_counted_apart() -> None:
    ids = {"lang": {"S1": "en"}}
    pairs = [{"mrn": "chart-a", "ruleset": "S1", "label": "eligible", "stratum": "sigir-eligible"},
             {"mrn": "chart-b", "ruleset": "S1", "label": "eligible", "stratum": "sigir-eligible"}]  # fmt: skip
    crits = [{"mrn": "chart-a", "ruleset": "S1", "kind": "exclusion", "label": "excluded", "text": "Pregnancy"},
             {"mrn": "chart-b", "ruleset": "S1", "kind": "exclusion", "label": "not excluded", "text": "Pregnancy"}]  # fmt: skip
    pats = {score.pid_of(m): {"tier": "excluded", "verdicts": []} for m in ("chart-a", "chart-b")}
    r = score.score_pairs(ids, pairs, _ans("S1", pats, []), crits=crits)
    assert r["label_conflicts"]["pairs"] == 1 and r["label_conflicts"]["by_lang"]["en"]["excluded"] == 1
    s = r["summary"]["en"]
    assert s["eligible_lost"]["k"] == 2 and s["eligible_lost_where_the_criterion_labels_exclude"] == 1


def test_s2_a_matched_row_with_no_verdict_is_no_verdict_not_no_block() -> None:
    ids = {"lang": {"S1": "en"}}
    crits = [{"mrn": "chart-a", "ruleset": "S1", "kind": "exclusion", "label": "not excluded", "text": "Pregnancy",
              "patient": "p1"}]  # fmt: skip
    draft = [{"id": "exc-1", "kind": "exclusion", "text": "Pregnancy"}]
    pats = {score.pid_of("chart-a"): {"tier": "high", "verdicts": [{"id": "other", "verdict": "pass"}]}}
    r = score.score_criteria(ids, crits, _ans("S1", pats, draft))
    assert r["no_verdict"] == 1 and r["answered"] == 0 and r["rows"][0].get("no_block") is None
    assert r["wrong_exclusion"]["n"] == 0


def test_s3_s4_exclusions_by_a_line_the_benchmark_wrote_are_counted(tmp_path: Path) -> None:
    ids = {"lang": {"MJMED-DM": "ja", "SNCT1": "en"}}
    written = {"MJMED-DM": ["20歳以上"], "SNCT1": ["Aged 40 years or older", "Female participants only"]}
    draft_j = [{"id": "inc-1", "kind": "inclusion", "text": "20歳以上", "class": "structured"},
               {"id": "exc-1", "kind": "exclusion", "text": "糖尿病の既往がある患者"}]  # fmt: skip
    draft_s = [{"id": "inc-9", "kind": "inclusion", "text": "Aged 40 years or older", "class": "structured"}]
    answers = {
        **_ans("MJMED-DM", {"a": {"tier": "excluded", "verdicts": [{"id": "inc-1", "verdict": "fail"}]},
                            "b": {"tier": "high", "verdicts": [{"id": "inc-1", "verdict": "pass"}]}}, draft_j),
        **_ans("SNCT1", {"c": {"tier": "excluded", "verdicts": [{"id": "inc-9", "verdict": "fail"}]}}, draft_s),
    }  # fmt: skip
    r = score.score_written(ids, written, answers, [])
    rows = {(x["ruleset"], x["line"]): x for x in r["rows"]}
    assert rows[("MJMED-DM", "20歳以上")]["excluded"] == 1 and rows[("MJMED-DM", "20歳以上")]["answered"] == 2
    assert rows[("SNCT1", "Aged 40 years or older")]["excluded"] == 1
    assert rows[("SNCT1", "Female participants only")]["compiled"] is False
    assert r["patients_excluded"] == 2 and r["summary"]["ja"]["excluded"] == 1
    # the builder writes the lines, and score() reads them
    b = sets.Bundle("jmed")
    b.patients = {"j:1": sets.Patient("j:1", "ja", "高血圧で通院中。", 19, "F")}
    b.trials = {
        "JMED-DM": sets.Trial("JMED-DM", "ja", "t", ["20歳以上"], ["糖尿病の既往がある患者"], written=["20歳以上"])
    }
    b.criteria = [sets.CriterionGold("j:1", "JMED-DM", "exclusion", "糖尿病の既往がある患者", "not excluded")]
    site.build(b, tmp_path / "built")
    assert json.loads((tmp_path / "built" / "gold" / "written.json").read_text()) == {"JMED-DM": ["20歳以上"]}
    pid = score.pid_of(json.loads((tmp_path / "built" / "gold" / "ids.json").read_text())["patients"]["j:1"])
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "answers.json").write_text(json.dumps(_ans("JMED-DM", {pid: {
        "tier": "excluded", "verdicts": [{"id": "inc-1", "verdict": "fail"}]}}, draft_j)))  # fmt: skip
    out = score.score(tmp_path / "built", tmp_path / "work")
    assert out["written_lines"]["patients_excluded"] == 1


# ---------------------------------------------------------------- H-1: acc-score carries H-3's keys when present
@pytest.mark.parametrize("extra", [{}, {"protocols": {"summary": {"n": 2}}, "pathology": {"excluded": 384},
                                        "unjudged_exclusions": {"summary": {"n": 1}}}])  # fmt: skip
def test_h1_acc_score_summary_takes_h3s_keys_only_when_the_score_has_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: dict[str, Any]
) -> None:
    sd = tmp_path / "acc" / "tcga"
    (sd / "built" / "gold").mkdir(parents=True)
    (sd / "built" / "gold" / "ids.json").write_text("{}")
    (sd / "work").mkdir()
    (sd / "work" / "answers.json").write_text("{}")
    monkeypatch.setattr(score, "score", lambda built, work: {"pairs": {"summary": {"n": 3}}, **extra})
    got = box_run.acc_score(tmp_path)["tcga"]["summary"]
    assert got["pairs"] == {"n": 3}
    for k in ("protocols", "pathology", "unjudged_exclusions"):
        assert (k in got) == (k in extra)
    if extra:
        assert got["protocols"] == {"n": 2} and got["pathology"] == {"excluded": 384}
