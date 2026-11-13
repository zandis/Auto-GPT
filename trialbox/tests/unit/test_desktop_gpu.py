"""NEW-WIN-6 (D-607): the health line for a card shared with the desktop (plan v7 section 2.3, rule 6).

The card's figures here are written, not read: no Windows machine and no card ran. What the line says on a real
workstation while a desktop user works is test P-11 (and lines 57 to 62 of the P-0 sheet)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tb_common import metrics
from tb_common.config import DECLARED

NOW = datetime(2026, 11, 13, 3, 0, tzinfo=UTC)
TH = metrics.Thresholds()
WSL2 = "6.6.87.2-microsoft-standard-WSL2"
TOTAL, MODELS = 97887, 62574  # the shipped record's card and the pair's measured share (MiB)
UP = {"ok": True, "code": "ok", "at": "2026-11-13T02:10:00+00:00"}
DOWN = {"ok": False, "code": "failed", "at": "2026-11-13T02:10:00+00:00"}


def _box(tmp: Path, *, kernel: str = WSL2, records: dict[str, Any] | None = None) -> tuple[Path, Path]:
    proc, deploy = tmp / "proc", tmp / "deploy"
    (proc / "sys/kernel").mkdir(parents=True)
    (proc / "sys/kernel/osrelease").write_text(kernel + "\n")
    for folder in ("site", "measured"):
        (deploy / folder).mkdir(parents=True)
    for rel, doc in (records or {"measured/serving_config.rtxpro6000.json": {"memory_used_mib": MODELS}}).items():
        (deploy / rel).write_text(json.dumps(doc))
    return proc, deploy


def _check(used: int, *, canary: dict[str, Any] | None = UP, models: float | None = MODELS) -> metrics.Check:
    facts = {"at": NOW.isoformat(), "gpu": {"used_mib": used, "total_mib": TOTAL, "models_mib": models}}
    health = metrics.evaluate(facts, canary, NOW, TH)
    return next(c for c in health.checks if c.name == "desktop_gpu")


def test_the_thresholds_are_the_declared_settings() -> None:
    assert DECLARED["TB_HEALTH_DESKTOP_GPU_WARN"].default == str(int(TH.desktop_gpu_warn_pct))
    assert DECLARED["TB_HEALTH_DESKTOP_GPU_RED"].default == str(int(TH.desktop_gpu_red_pct))
    th = metrics.Thresholds.from_env({"TB_HEALTH_DESKTOP_GPU_WARN": "50", "TB_HEALTH_DESKTOP_GPU_RED": "60"})
    assert (th.desktop_gpu_warn_pct, th.desktop_gpu_red_pct) == (50.0, 60.0)


def test_a_host_that_is_not_a_windows_workstation_has_no_such_line(tmp_path: Path) -> None:
    proc, deploy = _box(tmp_path, kernel="6.8.0-48-generic")
    called: list[int] = []
    assert metrics.gpu_facts(deploy, {}, proc=proc, card=lambda: called.append(1)) is None
    assert called == []  # the card is not even asked
    health = metrics.evaluate({"at": NOW.isoformat(), "gpu": None}, UP, NOW, TH)
    assert not [c for c in health.checks if c.name == "desktop_gpu"]


def test_office_work_beside_the_models_is_ok_and_says_both_figures() -> None:
    c = _check(MODELS + 3 * 1024)  # a browser, a video call
    assert c.level == "ok"
    assert (
        "programs outside TrialBox hold 3.0 GiB of the graphics card; 34.5 GiB is spare beside the models (9 %)"
        in c.text
    )


@pytest.mark.parametrize(
    ("outside_gib", "level"), [(24.0, "ok"), (24.2, "warn"), (29.2, "warn"), (29.4, "red"), (34.4, "red")]
)
def test_the_line_turns_at_the_declared_shares_of_the_spare_memory(outside_gib: float, level: str) -> None:
    c = _check(MODELS + int(outside_gib * 1024))
    assert c.level == level, c.text
    if level == "red":
        assert "may not fit after a restart" in c.text and "Close the program" in c.text


def test_with_the_models_down_everything_on_the_card_is_the_desktops(tmp_path: Path) -> None:
    # the models are not loaded: 30 GiB in use is 30 GiB of somebody else's, and the models would no longer fit
    assert _check(30 * 1024, canary=DOWN).level == "red"
    assert _check(30 * 1024, canary=None).level == "red"  # the orchestrator did not answer: not taken as "up"
    assert _check(2 * 1024, canary=DOWN).level == "ok"
    # the same reading with the models up is less than the models hold: nothing outside
    c = _check(30 * 1024)
    assert c.level == "ok" and "hold 0.0 GiB" in c.text


def test_a_card_that_cannot_be_read_or_has_no_record_is_a_warning_never_ok() -> None:
    facts = {"at": NOW.isoformat(), "gpu": {"used_mib": None, "total_mib": None, "models_mib": MODELS}}
    c = next(c for c in metrics.evaluate(facts, UP, NOW, TH).checks if c.name == "desktop_gpu")
    assert c.level == "warn" and "could not be read" in c.text
    c = _check(70000, models=None)
    assert (
        c.level == "warn" and "no serving record says what the models need" in c.text and "68.4 of 95.6 GiB" in c.text
    )


def test_models_measured_larger_than_the_card_are_red() -> None:
    assert _check(1000, models=TOTAL + 1).level == "red"


def test_the_facts_come_from_the_card_and_the_boxs_serving_record(tmp_path: Path) -> None:
    proc, deploy = _box(tmp_path)
    facts = metrics.gpu_facts(deploy, {}, proc=proc, card=lambda: (70000, TOTAL))
    assert facts == {"used_mib": 70000, "total_mib": TOTAL, "models_mib": float(MODELS)}
    json.dumps(facts)
    assert metrics.gpu_facts(deploy, {}, proc=proc, card=lambda: None) == {
        "used_mib": None,
        "total_mib": None,
        "models_mib": float(MODELS),
    }


def test_the_sites_record_wins_the_profile_names_it_and_two_are_never_guessed_between(tmp_path: Path) -> None:
    recs = {"measured/serving_config.rtxpro6000.json": {"memory_used_mib": MODELS},
            "site/serving_config.rtxpro6000.json": {"memory_used_mib": 60000}}  # fmt: skip
    proc, deploy = _box(tmp_path, records=recs)
    assert metrics.gpu_facts(deploy, {}, proc=proc, card=lambda: (1, 2))["models_mib"] == 60000.0  # type: ignore[index]
    two = {"measured/serving_config.rtxpro6000.json": {"memory_used_mib": MODELS},
           "measured/serving_config.rtx5090.json": {"memory_used_mib": 20000}}  # fmt: skip
    proc, deploy = _box(tmp_path / "b", records=two)
    assert metrics.gpu_facts(deploy, {}, proc=proc, card=lambda: (1, 2))["models_mib"] is None  # type: ignore[index]
    got = metrics.gpu_facts(deploy, {"TB_GPU_PROFILE": "rtx5090"}, proc=proc, card=lambda: (1, 2))
    assert got is not None and got["models_mib"] == 20000.0


@pytest.mark.parametrize(
    "doc", [{"memory_used_mib": "62574"}, {"memory_used_mib": True}, {"memory_used_mib": -1}, {}, []]
)
def test_a_record_without_a_usable_figure_gives_no_models_share(tmp_path: Path, doc: Any) -> None:
    proc, deploy = _box(tmp_path, records={"measured/serving_config.rtxpro6000.json": doc})
    got = metrics.gpu_facts(deploy, {}, proc=proc, card=lambda: (1, 2))
    assert got is not None and got["models_mib"] is None


def test_the_runner_writes_the_cards_facts_only_on_a_workstation_and_the_line_reaches_the_metrics_page(
    tmp_path: Path,
) -> None:
    assert metrics.host_facts(tmp_path, {}, None, NOW)["gpu"] is None  # this machine is not WSL2
    facts = {"at": NOW.isoformat(), "gpu": {"used_mib": MODELS + 30 * 1024, "total_mib": TOTAL, "models_mib": MODELS}}
    health = metrics.evaluate(facts, UP, NOW, TH)
    assert health.level == "red" and "programs outside TrialBox hold 30.0 GiB" in health.line()
    assert "desktop_gpu" in metrics.prometheus(health, "console")


def test_the_shipped_record_carries_the_figure_the_line_needs() -> None:
    root = Path(__file__).resolve().parents[2]
    for path in sorted((root / "deploy/measured").glob("serving_config.*.json")):
        assert json.loads(path.read_text(encoding="utf-8"))["memory_used_mib"] > 0, path.name


# ------------------------------------------------------------------- the Windows side: which programs, which accounts


def _policy() -> Any:
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("wsl2_policy_w6", root / "deploy/windows/wsl2_policy.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lines(facts: dict[str, str]) -> list[str]:
    policy = _policy()
    v = policy.Verdicts(True)
    policy.check_gpu_programs(facts, v)
    policy.check_admin_accounts(facts, v)
    return list(v.lines)


def test_the_host_check_names_the_programs_that_hold_the_card() -> None:
    lines = _lines({"gpu_programs_known": "1", "gpu_wsl_mib": "62574", "gpu_outside_mib": "30100",
                    "gpu_outside_top": "blender:28000,chrome:1500,dwm:600", "admin_accounts": "1"})  # fmt: skip
    assert lines[0] == ("PASS  graphics card by program (Windows): WSL2 holds 62574 MiB; programs outside TrialBox "
                        "hold 30100 MiB (blender 28000 MiB, chrome 1500 MiB, dwm 600 MiB)")  # fmt: skip
    assert lines[1].startswith("PASS  administrator accounts: one")


@pytest.mark.parametrize(
    ("facts", "says"),
    [
        ({"gpu_programs_known": "0"}, "WARN  graphics card by program: Windows gave no figures"),
        (
            {"gpu_programs_known": "1", "gpu_wsl_mib": "", "gpu_outside_mib": "5"},
            "WARN  graphics card by program: the figures could not be read",
        ),
        ({"admin_accounts": "3"}, "WARN  administrator accounts: 3."),
        ({"admin_accounts": ""}, "WARN  administrator accounts: not read"),
    ],
)
def test_what_windows_did_not_give_is_a_warning_and_more_administrators_are_said(
    facts: dict[str, str], says: str
) -> None:
    assert any(ln.startswith(says) for ln in _lines(facts)), _lines(facts)


def test_facts_of_an_earlier_release_add_no_line() -> None:
    assert _lines({"facts_version": "1"}) == []


def test_host_facts_reads_the_card_by_program_without_names_of_people_and_without_writing() -> None:
    root = Path(__file__).resolve().parents[2]
    ps = (root / "deploy/windows/host_facts.ps1").read_text(encoding="utf-8")
    for key in ("gpu_programs_known", "gpu_wsl_mib", "gpu_outside_mib", "gpu_outside_top", "admin_accounts"):
        assert f'Fact "{key}"' in ps, key
    assert (
        "Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory" in ps
    )  # a class name, not a localised counter path
    assert "Get-Counter" not in ps and '-SID "S-1-5-32-544"' in ps
    # the administrators are counted, never listed
    assert "$m.Name" not in ps and "$members.Name" not in ps


# --------------------------------------------------------------------------------- the rule the desktop user reads


def test_the_desktop_rule_is_in_three_languages_with_the_same_parts_and_no_verdict_words() -> None:
    from tb_common.wording import check

    root = Path(__file__).resolve().parents[2]
    shapes = {}
    for lang in ("en", "ja", "zh-TW"):
        text = (root / f"docs/handover/desktop-use.{lang}.md").read_text(encoding="utf-8")
        assert check(text) == [], lang
        lines = text.splitlines()
        shapes[lang] = ([ln.count("#") for ln in lines if ln.startswith("#")], sum(ln.startswith("- ") for ln in lines),
                        sum(ln[:2] in ("1.", "2.", "3.") for ln in lines))  # fmt: skip
        for must in ("TrialBox", "Prefer No Sysmem Fallback", "NVIDIA", "WSL2", "D-607"):
            assert must in text, (lang, must)
    assert shapes["en"] == shapes["ja"] == shapes["zh-TW"] == ([1, 2, 2, 2, 2, 2, 2], 9, 3)
