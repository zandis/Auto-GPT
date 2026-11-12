"""T-101b (D-318, URS-PI-06, FIT-026): the approved ruleset pins its prompt and terminology release; a newer prompt
puts the study in "approval needed" and SCREEN keeps the pinned prompt until the investigator re-approves."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from orchestrator.clients import StepFailed
from orchestrator.scenarios.screen import pinned_judge
from tb_common.ruleset import Ruleset, approval_state
from tb_contracts import RulesetManifest
from tb_llm.prompt_registry import (
    PromptRegistry,
    PromptRegistryError,
    default_registry,
    manifest_pins,
    sha256_bytes,
)

TEXT = "---\nid: judge\nversion: {v}\n---\n## system\nAnswer as {name}.\n## user\n{{{{ criterion }}}}\n"


def _registry(tmp_path: Path, versions: list[int]) -> PromptRegistry:
    rows = []
    for v in versions:
        raw = TEXT.format(v=v, name=f"judge v{v}").encode()
        (tmp_path / f"judge_v{v}.md").write_bytes(raw)
        rows.append(
            {
                "id": "judge",
                "version": v,
                "file": f"judge_v{v}.md",
                "sha256": sha256_bytes(raw),
                "approved_by": "synthetic test",
                "date": "2026-11-10",
                "qualification": None,
            }
        )
    return PromptRegistry({"version": "t", "prompts": rows}, tmp_path)


def _manifest(**extra: Any) -> RulesetManifest:
    return RulesetManifest.model_validate(
        {
            "id": "PIN-T",
            "kind": "trial",
            "title": "synthetic pin test",
            "version": "1.0.0",
            "status": "approved",
            "index_date_rule": "run_date",
            "scopes": {},
            "routing": {},
            "thresholds": {},
            "criteria": [],
            **extra,
        }
    )


def test_a_newer_prompt_marks_the_study_and_the_pin_still_resolves(tmp_path: Path) -> None:
    reg = _registry(tmp_path, [1])
    pins = reg.pins({"judge": None})
    assert pins == {"judge": {"version": 1, "sha256": reg.entry("judge", 1).sha256}}
    m = _manifest(prompt_pins=pins)
    assert reg.pin_drift(manifest_pins(m)) == []
    assert approval_state(m, prompt_drift=[])["state"] == "approved"
    # a new prompt version is registered: the study needs the investigator again
    reg = _registry(tmp_path, [1, 2])
    drift = reg.pin_drift(manifest_pins(m))
    assert drift == [{"id": "judge", "pinned": "judge@1", "active": "judge@2", "state": "newer"}]
    st = approval_state(m, prompt_drift=drift)
    assert st["state"] == "approval_needed" and st["reasons"][0]["kind"] == "prompt"
    # ... and the pinned text keeps resolving, not the newest
    assert reg.pinned("judge", pins["judge"]).entry.version == 1
    assert reg.get("judge").entry.version == 2


def test_a_pinned_text_that_changed_is_refused(tmp_path: Path) -> None:
    reg = _registry(tmp_path, [1])
    pin = reg.pins({"judge": 1})["judge"]
    other = {**pin, "sha256": "0" * 64}
    with pytest.raises(PromptRegistryError) as exc:
        reg.pinned("judge", other)
    assert exc.value.reason == "prompt_pin_changed"
    assert reg.pin_drift({"judge": other})[0]["state"] == "changed"
    assert reg.pin_drift({"nope": {"version": 1}})[0]["state"] == "unknown"


def test_terminology_release_change_marks_the_study() -> None:
    m = _manifest(terminology_release="TR-aaaaaaaaaaaa")
    assert approval_state(m, terminology_release="TR-aaaaaaaaaaaa", prompt_drift=[])["state"] == "approved"
    st = approval_state(m, terminology_release="TR-bbbbbbbbbbbb", prompt_drift=[])
    assert st["state"] == "approval_needed"
    assert st["reasons"] == [
        {"kind": "terminology", "pinned": "TR-aaaaaaaaaaaa", "active": "TR-bbbbbbbbbbbb", "state": "newer"}
    ]
    assert approval_state(m, terminology_release=None, prompt_drift=[])["state"] == "approved"  # unreadable: no claim
    assert approval_state(_manifest(status="draft"), prompt_drift=[])["state"] == "draft"


def test_screen_keeps_the_old_pin_on_the_real_registry() -> None:
    """judge@3 and judge@4 are both registered: a ruleset approved on judge@3 runs judge@3 and shows approval
    needed; the same pin with another text sha stops the run."""
    reg = default_registry()
    assert reg.versions("judge")[-1] > 3
    pins = reg.pins({"judge": 3})
    m = _manifest(prompt_pins=pins, models={"judge_prompt": "judge_v3"})
    rs = Ruleset(m, [], {})
    assert pinned_judge(rs) == "judge_v3"
    st = approval_state(m)
    assert st["state"] == "approval_needed" and st["reasons"][0]["pinned"] == "judge@3"
    bad = _manifest(prompt_pins={"judge": {**pins["judge"], "sha256": "1" * 64}}, models={"judge_prompt": "judge_v3"})
    with pytest.raises(StepFailed):
        pinned_judge(Ruleset(bad, [], {}))


def test_a_manifest_from_before_the_pins_reads_its_version_only() -> None:
    m = _manifest(models={"judge_prompt": "judge_v4"})
    assert manifest_pins(m) == {"judge": {"version": 4}}
    assert pinned_judge(Ruleset(m, [], {})) == "judge_v4"
    assert manifest_pins(_manifest()) == {}
    assert pinned_judge(Ruleset(_manifest(), [], {})) == "judge"


def test_a_newer_version_waiting_for_its_qualification_leaves_the_study_approved(tmp_path: Path) -> None:
    """D-359: an unqualified candidate does not send the approved study back; its qualification record does."""
    import json

    from tb_llm.prompt_registry import QUALIFICATION_DIR

    def qualified(versions: list[int]) -> PromptRegistry:
        reg = _registry(tmp_path, [1, 2])
        rows = []
        for e in reg.entries():
            row = {
                "id": e.id,
                "version": e.version,
                "file": f"judge_v{e.version}.md",
                "sha256": e.sha256,
                "approved_by": "synthetic test",
                "date": "2026-11-10",
                "qualification": None,
            }
            if e.version in versions:
                rec = tmp_path / QUALIFICATION_DIR / f"judge_v{e.version}.json"
                rec.parent.mkdir(parents=True, exist_ok=True)
                rec.write_text(json.dumps({"prompt": e.ref, "sha256": e.sha256, "schema_sha256": e.schema_sha256}))
                row["qualification"] = {
                    "record": f"{QUALIFICATION_DIR}/{rec.name}",
                    "sha256": sha256_bytes(rec.read_bytes()),
                }
            rows.append(row)
        return PromptRegistry({"version": "t", "prompts": rows}, tmp_path, root=tmp_path)

    reg = qualified([1])
    m = _manifest(prompt_pins={"judge": {"version": 1, "sha256": reg.entry("judge", 1).sha256}})
    assert reg.pin_drift(manifest_pins(m)) == []
    drift = qualified([1, 2]).pin_drift(manifest_pins(m))
    assert drift == [{"id": "judge", "pinned": "judge@1", "active": "judge@2", "state": "newer"}]


def test_the_harness_box_pins_what_its_production_gateway_serves(monkeypatch: pytest.MonkeyPatch) -> None:
    """G1 B5: the in-process box runs under this process's TB_ENV=DEV, its models behind a gateway client that stands
    for a PRODUCTION box (D-359). The approval pins the version that box serves, so SCREEN's pinned prompt is one
    PRODUCTION accepts, as on an installed box; DEV alone would pin the newest, unqualified one."""
    from types import SimpleNamespace

    from criteria_compiler.service import CompilerDeps, approval_pins
    from tb_common.llm import load_prompt

    from tools.public_e2e import attach_models

    monkeypatch.setenv("TB_ENV", "DEV")
    monkeypatch.setenv("TB_CANARY_GATE", "off")
    reg = default_registry()
    deps = CompilerDeps(None, None, None, None, {}, tz="Asia/Taipei")  # type: ignore[arg-type]
    orch = SimpleNamespace(audit=None, services=SimpleNamespace(compiler=SimpleNamespace(d=deps)))
    llm = SimpleNamespace(gateway=SimpleNamespace(prompt_environment="PRODUCTION"))
    assert attach_models(SimpleNamespace(orch=orch), llm, None) is None
    m = _manifest(models={"judge_prompt": "judge"})
    pinned = approval_pins(m, [], deps.prompt_environment)["models"]["judge_prompt"]
    assert pinned == f"judge_v{reg.served('judge', 'PRODUCTION').version}"
    load_prompt(pinned, "PRODUCTION")  # the gateway client's check: not refused (prompt_unqualified)
    # the stand-in box alone (no gateway client) keeps pinning what this process's environment serves
    assert approval_pins(m)["models"]["judge_prompt"] == f"judge_v{reg.served('judge', 'DEV').version}"
