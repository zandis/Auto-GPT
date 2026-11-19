"""D-1158 (the register's V3-14, V8-03, V8-07): a note, a reason or a comment a person types is masked before it is
written into the audit chain; ids, pseudonyms and states are not touched. Synthetic values only."""

from __future__ import annotations

from pathlib import Path

from tb_common.audit import AuditLog
from tb_common.audit_text import FreeTextMasked, mask_free_text, mask_free_text_in

CHART = "70004219"
NAME = "Name: Synthia Testperson"
PHONE = "0912-000-111"
MAIL = "synthia.testperson@example.invalid"
TYPED = f"call about chart {CHART}, {NAME}, phone {PHONE}, mail {MAIL}"


def _clear(text: str) -> list[str]:
    return [v for v in (CHART, "Synthia Testperson", PHONE, MAIL) if v in text]


def test_the_typed_text_keeps_none_of_the_four_in_clear() -> None:
    out = mask_free_text(TYPED)
    assert not _clear(out), out
    assert out.startswith("call about chart ")


def test_only_the_free_text_keys_are_masked_at_any_depth() -> None:
    detail = {"note": TYPED, "Reason": TYPED, "pid": "P-70004219", "state": "open",
              "steps": [{"why": TYPED, "job": "J-1"}], "inner": {"comment": TYPED}}  # fmt: skip
    out = mask_free_text_in(detail)
    assert out["pid"] == "P-70004219" and out["state"] == "open" and out["steps"][0]["job"] == "J-1"
    for typed in (out["note"], out["Reason"], out["steps"][0]["why"], out["inner"]["comment"]):
        assert not _clear(typed), typed
    assert detail["note"] == TYPED  # the caller's dict is not changed


def test_the_wrapped_writer_masks_detail_and_top_level_text_and_delegates_the_rest(tmp_path: Path) -> None:
    log = AuditLog(tmp_path)
    au = FreeTextMasked(log)
    au.append("test.typed", actor="u:alice", note=TYPED, detail={"reason": TYPED, "ruleset": "GZQO"})
    assert au.directory == log.directory
    text = "".join(p.read_text() for p in tmp_path.rglob("*") if p.is_file())
    assert "test.typed" in text and "GZQO" in text
    assert not _clear(text), _clear(text)


def test_a_label_and_its_value_on_separate_lines_are_masked_too() -> None:
    """The review of D-1158: the reveal note folded whitespace before masking; every path masks so now."""
    for typed in ("Name:\nSynthia Testperson", "Name:\n\n  Synthia Testperson", f"chart\n{CHART}"):
        assert not _clear(mask_free_text(typed)), typed


def test_free_text_nested_in_any_other_argument_is_masked(tmp_path: Path) -> None:
    """``AuditLog.append`` moves an unknown argument into the detail: free text nested in one is masked too."""
    FreeTextMasked(AuditLog(tmp_path)).append(
        "test.nested", actor="u:alice", extra={"note": TYPED}, steps=[{"why": TYPED}]
    )
    text = "".join(p.read_text() for p in tmp_path.rglob("*.jsonl"))
    assert "test.nested" in text and not _clear(text), _clear(text)


def test_an_accepted_nights_reason_is_masked_in_every_event(tmp_path: Path) -> None:
    """The review of D-1158: an accept writes ``started`` (and ``ended`` when the publish fails) with the reason."""
    import pytest
    from datacore.dataops import DataOps

    audit = AuditLog(tmp_path / "audit", "UTC")
    ops = DataOps()
    try:
        made = []
        for snap in ("2026-11-08", "2026-11-09"):
            b, _ = ops.record_night(audit, "ingest.held", source="csv", snapshot=snap, passed=False, held=True,
                                    by="adapter", at="2026-11-10T00:00:00+00:00", actor="adapter",
                                    detail={"gate": {"outcome": "held"}})  # fmt: skip
            made.append(b)

        def boom(_b: object) -> None:
            raise RuntimeError("lake refused")

        with pytest.raises(RuntimeError):
            ops.decide(audit, made[0].id, "accept", by="steward1", at="2026-11-10T00:00:00+00:00", reason=TYPED,
                       promote=boom)  # fmt: skip
        ops.decide(audit, made[1].id, "accept", by="steward1", at="2026-11-10T00:00:00+00:00", reason=TYPED,
                   promote=lambda _b: None)  # fmt: skip
    finally:
        ops.close()
    text = "".join(p.read_text() for p in (tmp_path / "audit").glob("*.jsonl"))
    assert text.count('"phase":"started"') == 2 and '"phase":"ended"' in text
    assert not _clear(text), _clear(text)
