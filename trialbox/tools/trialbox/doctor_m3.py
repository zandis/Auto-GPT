"""M3's rows of the doctor: each way out of the box, what its rule is and whether its door goes through the masking."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def doctor_checks(inp: Any) -> Iterable[tuple[str, str, str]]:
    try:
        from tb_common import egress_edge
    except ImportError as exc:  # a host whose python3 lacks a library: not looked at, never a FAIL
        return [("egress", "WARN", f"not looked at: this python3 does not have {exc.name}")]
    return egress_edge.doctor_checks(inp.env)
