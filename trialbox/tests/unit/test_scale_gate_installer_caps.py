"""T-02 / TRIAGE-1 G3 (configuration parity): the scale gate ran its 50,000-patient night under the compose files' dev
caps and passed, while the R1 box, under the caps the installer gave it, OOM-killed the same night (E2E P-02: the
adapter at 3,520 MiB). The gate now runs under the installer's caps for its reference box (the walk's 96 GiB machine
with one 96 GB card); this test holds the gate's caps equal to the installer's, and no proof tool reads the compose
defaults as its caps."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tb_testkit.scale import compose_caps

from tools import scale_gate as sg
from tools.box.plan import DEPLOY, memory_caps

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]


def test_the_gate_s_caps_are_the_installer_s_for_its_box() -> None:
    env, _ = memory_caps(sg.BOX_RAM_GIB, sg.BOX_PROFILE, DEPLOY)
    got = sg.installer_caps()
    for service, var in (("adapter", "TB_MEM_ADAPTER"), ("orchestrator", "TB_MEM_ORCH"), ("lake", "TB_MEM_LAKE")):
        mib = int(env[var].removesuffix("m"))
        assert got[service] == mib * 1024 * 1024, (service, got[service], env[var])


def test_the_params_default_to_that_box_and_run_takes_its_caps() -> None:
    p = sg.Params(out=Path("unused"), patients=sg.FULL)
    assert (p.box_ram_gib, p.box_profile) == (96.0, "rtxpro6000") and p.caps == {}
    text = Path(sg.__file__).read_text(encoding="utf-8")
    assert "p.caps = p.caps or installer_caps(p.box_ram_gib, p.box_profile)" in text


def test_the_dev_defaults_are_not_the_installer_s_caps() -> None:
    """Why parity matters: on the reference box the installer's adapter cap is not the compose default."""
    assert compose_caps()["adapter"] != sg.installer_caps()["adapter"]


#: the tools whose green is an acceptance proof of "fits at the declared size" (the size ladder measures peaks: its
#: caps bound a measurement, not a claim, and it is not listed)
PROOF_TOOLS = ("tools/scale_gate.py",)


def test_no_proof_tool_takes_the_compose_defaults_as_its_caps() -> None:
    bare = re.compile(r"\bcompose_caps\(\)")
    users = [t for t in PROOF_TOOLS if bare.search((ROOT / t).read_text(encoding="utf-8"))]
    assert users == [], users
