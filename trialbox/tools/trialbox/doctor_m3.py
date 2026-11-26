"""M3's rows of the doctor: each way out of the box, what its rule is and whether its door goes through the masking."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from tb_common import egress_edge  # what a host's python lacks, doctor.module_rows says (OCR 1523-14)


def doctor_checks(inp: Any) -> Iterable[tuple[str, str, str]]:
    return egress_edge.doctor_checks(inp.env)
