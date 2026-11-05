"""D-101: approval record, human-heavy warning, report provenance, population line, sponsor pack README."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

from console.app import build_sponsor_pack
from console.auth import ROLES, User
from criteria_compiler.semantics import class_split, human_heavy
from orchestrator.i18n import LANGS, population_line
from orchestrator.reports.common import ReportMeta
from orchestrator.scenarios.screen import NO_MODEL, models_used
from tb_contracts import Job


def _crit(cid: str, kind: str, cls: str, status: str | None = None) -> SimpleNamespace:
    review = SimpleNamespace(status=status) if status else None
    return SimpleNamespace(id=cid, kind=kind, class_=cls, review=review)


def test_class_split_counts_active_criteria_only() -> None:
    crits = [
        _crit("I1", "inclusion", "structured"),
        _crit("I2", "inclusion", "mixed"),
        _crit("E1", "exclusion", "note"),
        _crit("E2", "exclusion", "human"),
        _crit("E3", "exclusion", "human", "rejected"),
        _crit("M1", "metadata", "human"),
    ]
    assert class_split(crits) == {"structured": 1, "mixed": 1, "note": 1, "human": 1}  # type: ignore[arg-type]


def test_human_heavy_is_half_or_more_left_to_a_person() -> None:
    assert human_heavy({"structured": 1, "mixed": 0, "note": 1, "human": 2})
    assert human_heavy({"structured": 4, "mixed": 0, "note": 0, "human": 19})
    assert not human_heavy({"structured": 3, "mixed": 1, "note": 2, "human": 1})
    assert not human_heavy({})


def test_models_used_names_what_ran_not_what_is_configured() -> None:
    assert models_used(None) == NO_MODEL
    assert models_used({"mode": "none", "judge_model": None}) == NO_MODEL
    pair = {"mode": "agreement", "judge_model": "j", "verifier_model": "v", "note_block": "both_agree"}
    assert models_used(pair) == "j + v (both agree)"
    single = {"mode": "agreement", "judge_model": "j", "verifier_model": None, "note_block": "never"}
    assert models_used(single) == "j (single, never-exclude)"


def test_footer_prints_the_pinned_clock_only_when_pinned() -> None:
    meta = ReportMeta("A", "Hosp A", "GZQO", "1.0.0", NO_MODEL, "2026-10-04", "01J", "2026-10-05")
    assert meta.footer.endswith("job 01J") and "clock" not in meta.footer and NO_MODEL in meta.footer
    pinned = ReportMeta(
        "A", "Hosp A", "GZQO", "1.0.0", NO_MODEL, "2026-10-04", "01J", "2026-10-05", clock="clock pinned (test stack)"
    )
    assert pinned.footer.endswith("job 01J · clock pinned (test stack)")


def test_population_line_in_every_language_and_empty_without_fields() -> None:
    pop = SimpleNamespace(disease_stage="MCI due to AD (CDR 0.5)", study_arm="treatment-naive")
    for lang in LANGS:
        line = population_line(lang, pop)
        assert "MCI due to AD (CDR 0.5)" in line and "treatment-naive" in line
    assert population_line("en", None) == ""
    assert population_line("en", SimpleNamespace(disease_stage=None, study_arm=None)) == ""


def test_investigator_reads_phi_but_cannot_request() -> None:
    assert "investigator" in ROLES
    inv = User("pi", "investigator", None)
    assert inv.can_view_phi and not inv.can_request and not inv.is_admin
    viewer = User("v", "viewer", None)
    assert not viewer.can_view_phi
    crc = User("c", "coordinator", None)
    assert crc.can_view_phi and crc.can_request


def test_sponsor_pack_readme_carries_the_provenance_and_the_files() -> None:
    job = Job(
        job_id="01JTEST0000000000000000900",
        type="FEAS",
        state="done",
        ruleset="GZQO",
        ruleset_version="1.0.0",
        requested_by="crc@hospa.test",
        received_at=datetime(2026, 10, 25, 9, 0, tzinfo=UTC),
        snapshot_date=date(2026, 10, 4),
        run_date=date(2026, 10, 5),
    )
    detail = {
        "title": "Gout flare prevention",
        "nct_id": "NCT00000000",
        "version": "1.0.0",
        "criteria": 7,
        "population": {"disease_stage": "recurrent gout", "study_arm": "ULT naive"},
        "review": {
            "approved_by": "crc@hospa.test",
            "approved_via": "web console",
            "approved_at": "2026-10-20T08:00:00+00:00",
            "rounds": 1,
            "split": {"structured": 3, "mixed": 1, "note": 2, "human": 1},
            "routing_confirmed": True,
        },
    }
    models = {"judge_model": "j", "verifier_model": None, "may_block": False}
    data = build_sponsor_pack(job, [("feasibility.pdf", b"%PDF"), ("feasibility.json", b"{}")], detail, models)
    assert data == build_sponsor_pack(job, [("feasibility.pdf", b"%PDF"), ("feasibility.json", b"{}")], detail, models)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert sorted(z.namelist()) == ["README.txt", "feasibility.json", "feasibility.pdf"]
        readme = z.read("README.txt").decode("utf-8")
    assert "Approved by: crc@hospa.test via web console on 2026-10-20" in readme
    assert "routing confirmed by the approver: yes" in readme
    assert "stage = recurrent gout; arm = ULT naive" in readme
    assert "3 filter, 1 filter then model, 2 model on notes, 1 person" in readme
    assert "filters only (no language model)" in readme and "judge j, no verifier" in readme
    assert "snapshot: 2026-10-04" in readme and "No patient-level data" in readme


def test_stage_funnel_counts_coded_filters_notes_read_and_candidates() -> None:
    from orchestrator.scenarios.evaluate import PatientVerdicts
    from orchestrator.scenarios.screen import ScreenRun, stage_funnel
    from tb_contracts import CriterionVerdict, Evidence

    crit = [
        SimpleNamespace(id="I1", class_="structured"),
        SimpleNamespace(id="E1", class_="note"),
        SimpleNamespace(id="M1", class_="mixed"),
    ]
    rs = SimpleNamespace(criteria=crit)

    def pv(pid: str, *vs: CriterionVerdict) -> PatientVerdicts:
        return PatientVerdicts(pid=pid, verdicts=list(vs), tier="review", actions=[], n_unknown=0)

    conf = Evidence(confidence=0.9)
    results = {
        "a": pv(
            "a", CriterionVerdict(id="I1", verdict="pass"), CriterionVerdict(id="E1", verdict="pass", evidence=conf)
        ),
        "b": pv(
            "b",
            CriterionVerdict(id="I1", verdict="fail"),
            CriterionVerdict(id="E1", verdict="unknown", evidence=Evidence(reason="not evaluated")),
        ),  # out on codes, notes never read
        "c": pv(
            "c", CriterionVerdict(id="I1", verdict="pass"), CriterionVerdict(id="M1", verdict="pass")
        ),  # codes settled
    }
    scoped: list[Any] = ["a", "b", "c"]
    srun = ScreenRun(rs, date(2026, 10, 5), "2026-10-04", scoped, results, [], [], [], 14, None)  # type: ignore[arg-type]
    assert stage_funnel(rs, srun, 2, lambda v: v) == [["S0", 3], ["S1", 2], ["S3", 1], ["S4", 2]]  # type: ignore[arg-type]
