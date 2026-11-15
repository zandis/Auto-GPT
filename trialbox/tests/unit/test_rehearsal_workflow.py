"""I-8 (D-887): the box-install rehearsal runs in CI by hand and on every pull request that touches the installer path,
in two variants: the TEST rehearsal as it is, and VALIDATION's settings (no TPM, the passphrase KEK, the poc host
profile, two installs of one bundle, a root-owned deploy/site). No schedule (D-511)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT.parent / ".github" / "workflows" / "trialbox-rehearse-box.yml"
REHEARSE = (ROOT / "tools" / "rehearse_box" / "rehearse.sh").read_text(encoding="utf-8")
BOX = (ROOT / "tools" / "rehearse_box" / "box.sh").read_text(encoding="utf-8")
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")

pytestmark = pytest.mark.nodb

# the installer path the integrator named (#639, 2026-11-15)
INSTALLER_PATH = [
    "trialbox/deploy/install.sh", "trialbox/deploy/box-install.sh", "trialbox/deploy/hardening/**",
    "trialbox/deploy/check_host.sh", "trialbox/deploy/docker-compose*.yml", "trialbox/tools/make_bundle.sh",
    "trialbox/tools/apply_update.sh", "trialbox/tools/verify_update.py", "trialbox/tools/sign_bundle.py",
    "trialbox/tools/release.py", "trialbox/tools/supply_chain/**", "trialbox/tools/trialbox/**",
    "trialbox/tools/rehearse_box/**", "trialbox/tools/qualify.py", "trialbox/tools/pin_model.py",
    "trialbox/deploy/docker/**", "trialbox/Makefile",
]  # fmt: skip


def _wf() -> dict[Any, Any]:
    doc = yaml.safe_load(WF.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def _on(doc: dict[Any, Any]) -> dict[str, Any]:
    on = doc.get("on", doc.get(True))
    assert isinstance(on, dict)
    return on


def test_by_hand_and_on_installer_pull_requests_never_on_a_schedule() -> None:
    on = _on(_wf())
    assert set(on) == {"workflow_dispatch", "pull_request"}
    paths = on["pull_request"]["paths"]
    assert set(INSTALLER_PATH) <= set(paths)
    assert ".github/workflows/trialbox-rehearse-box.yml" in paths


def test_both_variants_run_the_real_rehearsal_and_keep_the_report() -> None:
    job = _wf()["jobs"]["rehearse"]
    assert job["strategy"]["fail-fast"] is False
    assert [v["variant"] for v in job["strategy"]["matrix"]["include"]] == ["test", "validation"]
    text = WF.read_text(encoding="utf-8")
    assert "make venv scanners trivy-db" in text and "make rehearse-box" in text
    assert "TB_REHEARSE_VARIANT: ${{ matrix.variant }}" in text
    assert "report.md" in text and "GITHUB_STEP_SUMMARY" in text
    assert re.findall(r"uses: [^@\s]+@([0-9a-f]+)", text) and not re.findall(r"uses: [^@\s]+@v\d", text)


def test_the_variant_is_checked_and_said_in_the_report() -> None:
    assert 'VARIANT="${TB_REHEARSE_VARIANT:-test}"' in REHEARSE
    assert 'case "$VARIANT" in test|validation)' in REHEARSE
    assert '-e TB_RH_VARIANT="$VARIANT"' in REHEARSE
    assert '"variant"' in REHEARSE.split("report.json")[-1]


def test_validation_installs_twice_on_one_bundle() -> None:
    steps = re.findall(r"\bstep ([a-z0-9-]+) [01] ", REHEARSE)
    assert steps.index("reinstall") == steps.index("install") + 1
    assert re.search(r'^\[ "\$VARIANT" = validation \] && step reinstall 1 in_box reinstall', REHEARSE, re.M)
    body = BOX[BOX.index("\nreinstall)") : BOX.index(";;", BOX.index("\nreinstall)"))]
    assert "install_box" in body and "wait_healthy" in body and "kek.json" in body


def test_validation_settings_reach_the_installer() -> None:
    fn = BOX[BOX.index("install_box() (") : BOX.index("\n)\n", BOX.index("install_box() ("))]
    for want in ("TB_HOST_PROFILE=poc", "TB_KEK_BACKEND=passphrase", "TB_KEK_PASSPHRASE", "chown -R root:root",
                 "deploy/site"):  # fmt: skip
        assert want in fn, want
    assert "--rehearsal" in fn  # the model stand-ins are honoured on a TEST box only (D-726)
    # the box host sees the host's KEK folder and the volumes at their own paths, as a site's host does
    up = REHEARSE[REHEARSE.index("host_up() {") : REHEARSE.index("\n}\n", REHEARSE.index("host_up() {"))]
    assert "/run/trialbox:/run/trialbox" in up and "/volumes:" in up


def test_an_explicit_kek_backend_seals_a_test_box_too() -> None:
    """D-887: TB_KEK_BACKEND in the installer's environment asks for sealed keys on any box (D-836 made it the
    back end's switch without a hardening.conf, whose presence also sets the firewall and SSH)."""
    branch = next(ln for ln in INSTALL.splitlines() if ln.startswith("elif") and '[ -f "$HB_CONF" ]' in ln)
    assert '[ -n "${TB_KEK_BACKEND:-}" ]' in branch and '[ -f "$HB_CONF" ]' in branch


CHECK_HOST = (ROOT / "deploy" / "check_host.sh").read_text(encoding="utf-8")


def test_the_host_checks_doctor_sees_the_site_key_and_an_outside_compose_file() -> None:
    """D-887, found by the rehearsal's CI run (the host check had never run on a box): doctor in the image read no
    site key (FAIL site_key) and no override compose file outside deploy/ (FAIL chartno_rule, db_passwords)."""
    assert "-v $SEC_HOST:/run/secrets/trialbox:ro" in CHECK_HOST
    loop = CHECK_HOST[CHECK_HOST.index("for cf in") : CHECK_HOST.index("done", CHECK_HOST.index("for cf in"))]
    assert "COMPOSE_FILE" in loop and '"$ROOT_DIR/deploy/"*' in loop and "-v $cf:$cf:ro" in loop


def test_a_rehearsal_box_warns_for_the_egress_table_every_other_box_fails() -> None:
    start = CHECK_HOST.index("# network egress")
    block = CHECK_HOST[start : CHECK_HOST.index("\nfi\n", start)]
    assert "if rehearsal_box; then" in block and "no NET_ADMIN" in block
    helper = next(ln for ln in CHECK_HOST.splitlines() if ln.startswith("rehearsal_box()"))
    assert '[ "$TBENV" = TEST ] && [ "$(envget TB_REHEARSAL)" = 1 ]' in helper
    luks = CHECK_HOST[CHECK_HOST.index('LUKS_DEVS=""') : CHECK_HOST.index("done", CHECK_HOST.index('LUKS_DEVS=""'))]
    assert "elif rehearsal_box; then" in luks and 'facility fail "LUKS:' in luks
    assert 'facility fail "egress allowlist not loaded' in block


def test_the_rehearsal_host_has_the_sites_zone_and_no_swap() -> None:
    fn = BOX[BOX.index("install_box() (") : BOX.index("\n)\n", BOX.index("install_box() ("))]
    assert "site_answers.yaml" in fn and "/etc/timezone" in fn
    assert "sudo swapoff -a" in WF.read_text(encoding="utf-8")
