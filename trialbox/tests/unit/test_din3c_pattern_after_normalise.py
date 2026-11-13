"""NEW-DIN-3c (D-546): a typed chart number is held to the site's pattern after it is written the site's way.

With the rule ``digits:8`` (D-579) the pattern is ``^\\d{8}$``. A coordinator who types ``123456``, or full-width
digits, means chart ``00123456``: the rule makes it so before it is hashed. Three places matched the pattern
against the number as typed and refused it. They now match the normalised number; a number the rule does not make
fit is refused as before."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator.candidates import CandidateRegistry, RegistryError
from orchestrator.clients import StepFailed
from orchestrator.db import JobDB
from orchestrator.scenarios import case
from sitesetup.store import SetupError
from tb_common.audit import AuditLog
from tb_common.crypto import pid_for_mrn
from tb_contracts import RegistryUpdate

from tests.unit.test_site_setup import KEY as SETUP_KEY
from tests.unit.test_site_setup import svc  # noqa: F401 - the fixture by name

KEY = b"din3c-test-key-0123456789abcdef0123"
PATTERN = r"^\d{8}$"
WHOLE = "00123456"  # synthetic
TYPED = ["123456", "００１２３４５６", " 00123456 ", "１２３４５６"]
WRONG = ["1234567890", "12A456", "012345678"]  # too long (never cut, D-591), not digits, wider than the rule


@pytest.fixture(autouse=True)
def _rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_CHARTNO_RULE", "digits:8")


def _registry(tmp_path: Path) -> CandidateRegistry:
    sec = tmp_path / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(KEY)
    return CandidateRegistry(JobDB(), AuditLog(tmp_path / "audit"), sec, PATTERN)


def test_the_registry_takes_a_number_the_rule_makes_whole(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    want = pid_for_mrn(KEY, WHOLE)
    for typed in TYPED:
        assert reg.pid_for(RegistryUpdate(mrn=typed, status="candidate", by="crc")) == want, typed
    for typed in WRONG:
        with pytest.raises(RegistryError, match="does not look like a chart number"):
            reg.pid_for(RegistryUpdate(mrn=typed, status="candidate", by="crc"))


def test_a_case_request_takes_it_too(tmp_path: Path) -> None:
    ctx: Any = SimpleNamespace(cfg=SimpleNamespace(settings=SimpleNamespace(mrn_regex=PATTERN),
                                                   env=SimpleNamespace(secrets_dir=str(tmp_path))))  # fmt: skip
    for typed in TYPED:  # past the pattern; this box has no site key, which is the next answer
        assert "no site key" in case.resolve_subject(ctx, typed).note, typed
    for typed in WRONG:
        with pytest.raises(StepFailed, match="does not look like a chart number"):
            case.resolve_subject(ctx, typed)


def test_site_setup_takes_it_for_a_pasted_chart(svc: Any) -> None:  # noqa: F811
    assert svc.mrn_regex == PATTERN
    want = pid_for_mrn(SETUP_KEY, WHOLE)
    for typed in TYPED:
        svc.add_chart("practice", typed, "pasted.txt", b"Gout flare. Uric acid 9.2.", "crc", "en", pasted=True)
    charts = [i for i in svc.store.inputs("practice") if i["kind"] == "chart"]
    assert len(charts) == len(TYPED) and {i["pid"] for i in charts} == {want}  # every spelling: the one patient
    for typed in WRONG:
        with pytest.raises(SetupError, match="not a chart number of this hospital"):
            svc.add_chart("practice", typed, "pasted.txt", b"Gout flare.", "crc", "en", pasted=True)


def test_a_short_typed_number_masks_the_chart_number_and_nothing_else(svc: Any) -> None:  # noqa: F811
    """The review's MED-1: the chart's text is masked for the number as the site writes it. Typed ``2`` is chart
    ``00000002``; masking the typed text would have replaced every 2 in the chart."""
    text = "Chart 00000002. Gout flare. Uric acid 9.2 mg/dL on 2024-03-01. Dose 2 tablets."
    assert svc.redact(text, "2").startswith("Chart [MRN]. Gout flare. Uric acid 9.2 mg/dL")
    assert "Dose 2 tablets" in svc.redact(text, "2")
    assert svc.redact("Chart 00123456 seen.", "123456") == "Chart [MRN] seen."
    assert svc.redact("Chart 00123456 seen.", "００１２３４５６") == "Chart [MRN] seen."
    assert svc.redact("No. ００１２３４５６ seen.", "００１２３４５６") == "No. [MRN] seen."  # as typed, when as long
    svc.add_chart("practice", "2", "pasted.txt", text.encode(), "crc", "en", pasted=True)
    iid = max(i["id"] for i in svc.store.inputs("practice"))
    stored = (svc.root / f"practice/inputs/{iid}.lake.txt").read_text(encoding="utf-8")
    assert "9.2 mg/dL" in stored and "00000002" not in stored
