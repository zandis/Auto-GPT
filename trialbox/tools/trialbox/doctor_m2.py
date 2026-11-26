"""M2's doctor row (F0's hook): the terminology update's state, read on the host, where a pack's folders are (H-144: the
standard library only). Every table with its rows, version and hash is ``doctor.check_terminology_tables``, the box
image's. The bodies are in ``tools/terminology_pack.py``."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from tools import terminology_pack

if TYPE_CHECKING:
    from tools.trialbox.doctor import DoctorInputs


def code_systems(env: Mapping[str, str]) -> Path:
    """The code systems' folder as this python sees it: the box image's mount, or on a host the volume behind it."""
    from tools.trialbox import audit_heads, launch

    named = Path((env.get("TB_TERMINOLOGY_DIR") or "").strip() or "/data/terminology")
    if launch.in_box_image() or named.is_dir():
        return named
    project = env.get("COMPOSE_PROJECT_NAME") or audit_heads.PROJECT
    return Path(env.get("TB_DOCKER_VOLUMES") or audit_heads.VOLUMES) / f"{project}_tb-terminology" / "_data"


def doctor_checks(inp: DoctorInputs) -> list[tuple[str, str, str]]:
    return [terminology_pack.update_row(inp.env, code_systems(inp.env))]
