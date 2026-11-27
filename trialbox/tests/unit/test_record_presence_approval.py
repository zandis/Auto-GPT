"""Gate 1: a person records an approval of one exact held line (``tools/record_presence_approval.py``).

The record has the same form as the shipped ones, names the person, and is audited before it is written. With it the
held line runs; without the audit event nothing is recorded. Synthetic protocol and recorded model answers only.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from criteria_compiler.ir_extract import presence_approvals as pa
from criteria_compiler.ir_extract.postprocess import postprocess
from criteria_compiler.semantics import compiled
from criteria_compiler.service import _presence_passages
from criteria_compiler.terminology.mapper import Terminology
from doc_parser.parser import parse
from tb_common.audit import AuditLog
from tb_common.ruleset import SEED_RULESETS
from tb_contracts import LlmExtractOutput

from tools import record_presence_approval as tool

ROOT = Path(__file__).resolve().parents[2]
# Withheld from the shipped approvals (a planned, hypothetical clause): a person may still approve it.
LINE = "GZQO-EXC-05"


@pytest.fixture
def ruleset_dir(tmp_path: Path) -> Path:
    target = tmp_path / "GZQO"
    shutil.copytree(SEED_RULESETS / "GZQO", target)
    return target


def _events(audit_dir: Path) -> list[dict[str, object]]:
    return [json.loads(r) for p in audit_dir.glob("*.jsonl") for r in p.read_text().splitlines()]


def test_a_persons_approval_is_recorded_audited_and_releases_only_that_line(ruleset_dir: Path, tmp_path: Path) -> None:
    approvals, audit_dir = tmp_path / "approvals.json", tmp_path / "audit"
    code = tool.main(
        ["--ruleset-dir", str(ruleset_dir), "--criterion", LINE, "--actor", "Reviewer A",
         "--approvals", str(approvals), "--audit-dir", str(audit_dir), "--date", "2026-11-22"]
    )  # fmt: skip
    assert code == 0
    (approval,) = pa.read_approvals(approvals)
    assert (approval.protocol, approval.criterion, approval.basis) == ("GZQO", LINE, "person")
    assert approval.actor == approval.recorded_by == "Reviewer A" and approval.label == pa.PERSON_LABEL
    assert approval.text == "Prior or planned bariatric surgery." and approval.date == "2026-11-22"
    (event,) = [e for e in _events(audit_dir) if e["event"] == tool.EVENT]
    assert event["actor"] == "Reviewer A" and event["input_sha"] == approval.text_sha256
    assert event["detail"] == {
        "criterion": LINE, "approval_label": pa.PERSON_LABEL, "approval_basis": "person", "approvals_file": approvals.name
    }  # fmt: skip
    # first extraction of the protocol: the line runs on the person's approval, on any box
    document = next((ROOT / "tests/fixtures/protocols").glob("GZQO*.pdf"))
    sources = [
        s
        for sec in _presence_passages(parse(document.read_bytes(), document.name, backend="lite")).values()
        for *_, s in sec
    ]
    extracted = LlmExtractOutput.model_validate_json(
        (ROOT / "services/llm_stub/cassettes/ir_extract/GZQO.json").read_bytes()
    )
    term = Terminology()
    post = postprocess(
        "GZQO", extracted, term, sources=sources, audit=AuditLog(tmp_path / "a2"), approvals=(approval,),
        environment="PRODUCTION",
    )  # fmt: skip
    released = {c.id: c for c in compiled(post.criteria)}
    assert LINE in released and pa.release_note(released[LINE]) == approval.release_note()
    assert "Reviewer A" in (pa.release_note(released[LINE]) or "")
    assert {c.id for c in compiled(post.criteria) if pa.release_note(c)} == {LINE}


def test_nothing_is_recorded_without_the_audit_event(
    ruleset_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit = AuditLog(tmp_path / "audit")

    def refuse(*args: object, **kwargs: object) -> dict[str, object]:
        raise OSError("disk full")

    monkeypatch.setattr(audit, "append", refuse)
    approvals = tmp_path / "approvals.json"
    code, message = tool.record(ruleset_dir, LINE, "Reviewer A", approvals, audit, "2026-11-22")
    assert code == 2 and not approvals.exists()
    assert message.splitlines() == [tool.MESSAGES["audit"][lang] for lang in ("en", "zh-TW", "ja")]


@pytest.mark.parametrize(
    ("criterion", "actor", "key"),
    [
        ("GZQO-INC-01", "Reviewer A", "not_presence"),  # an age criterion: nothing to approve
        (LINE, "  ", "invalid"),
        (LINE, pa.SHIPPED_BY, "invalid"),  # a person's approval names a person
        ("GZQO-EXC-99", "Reviewer A", "invalid"),
    ],
)
def test_a_line_or_name_that_cannot_be_approved_is_refused(
    criterion: str, actor: str, key: str, ruleset_dir: Path, tmp_path: Path
) -> None:
    approvals = tmp_path / "approvals.json"
    code, message = tool.record(ruleset_dir, criterion, actor, approvals, AuditLog(tmp_path / "audit"), "2026-11-22")
    assert code == 2 and not approvals.exists() and not _events(tmp_path / "audit")
    assert message.splitlines()[0] == tool.MESSAGES[key]["en"].format(criterion=criterion)


def test_a_second_approval_of_the_same_line_is_refused_and_the_file_kept(ruleset_dir: Path, tmp_path: Path) -> None:
    approvals, audit = tmp_path / "approvals.json", AuditLog(tmp_path / "audit")
    assert tool.record(ruleset_dir, LINE, "Reviewer A", approvals, audit, "2026-11-22")[0] == 0
    before = approvals.read_bytes()
    code, _ = tool.record(ruleset_dir, LINE, "Reviewer B", approvals, audit, "2026-11-23")
    assert code == 2 and approvals.read_bytes() == before
    assert len([e for e in _events(tmp_path / "audit") if e["event"] == tool.EVENT]) == 1
