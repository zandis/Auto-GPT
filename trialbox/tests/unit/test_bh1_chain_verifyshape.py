"""BH1-09: ``tb_common.audit.verify`` raises on a well-formed JSON line that is not an object.

Entry point: ``tb_common.audit.verify`` (used by ``tools/audit_verify.py``, the console's ``/audit/verify`` and the
nightly signer). A line ``[]`` or ``"x"`` in a day file passes ``json.loads`` and then ``rec.pop("hash", None)``
raises (TypeError / AttributeError), so the check stops with a traceback instead of returning ``ok=False`` with the
file and line, as it does for invalid JSON. Synthetic events only, in tmp_path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from tb_common.audit import AuditLog, verify


def _chain(tmp_path: Path, extra: str) -> Path:
    d = tmp_path / "audit"
    log = AuditLog(d, "UTC")
    log.append("job.synthetic", ts=datetime(2026, 1, 1, tzinfo=UTC), actor="test")
    log.append("job.synthetic", ts=datetime(2026, 1, 1, 0, 1, tzinfo=UTC), actor="test")
    day = sorted(d.glob("*.jsonl"))[0]
    first, second = day.read_text(encoding="utf-8").splitlines()
    day.write_text("\n".join([first, extra, second]) + "\n", encoding="utf-8")  # the bad line is line 2
    return d


@pytest.mark.xfail(strict=True, reason="open finding: BH1-09: a non-object JSON line makes verify raise")
@pytest.mark.parametrize("line", ["[]", '"x"', "1"])
def test_verify_reports_a_non_object_line(tmp_path: Path, line: str) -> None:
    res = verify(_chain(tmp_path, line))
    assert not res.ok
    assert any(":2:" in e for e in res.errors)


def test_verify_reports_invalid_json(tmp_path: Path) -> None:
    """Control: an unparsable line is reported, not raised."""
    res = verify(_chain(tmp_path, "{not json"))
    assert not res.ok and any(":2:" in e for e in res.errors)
