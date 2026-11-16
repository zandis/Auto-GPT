"""D-887 (the integrator's (a), 2026-11-15): the box rehearsal pins the media's placeholder weights so that SCREEN runs
through the gateway as on a site, and proves the path a box judges by, nothing about a model. Only when ALL hold:
a rehearsal box (TB_ENV TEST, TB_REHEARSAL=1), a rehearsal bundle (installed.json says so, from release.json), and
every weight folder of the pair is the media's placeholder. The pin is a candidate named "rehearsal placeholder";
promote and qualify refuse it by name; a real folder beside a placeholder refuses the whole pin."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from registry.registry import DEFAULT_PATH, Registry, RegistryError
from tb_common.policy.classes import Environment

from tools import pin_model

ROOT = Path(__file__).resolve().parents[2]
JUDGE = "gemma-4-26b-a4b-it-rtxpro6000"
VERIFIER = "qwen3.5-9b-rtxpro6000"
REHEARSAL_BOX = {"TB_ENV": "TEST", "TB_REHEARSAL": "1"}

pytestmark = pytest.mark.nodb


def _placeholder(models: Path, name: str) -> Path:
    """As tools/rehearse_box/rehearse.sh makes them: never a model."""
    d = models / name
    d.mkdir(parents=True)
    (d / "config.json").write_text(json.dumps({"architectures": ["TrialBoxRehearsalPlaceholder"], "name": name}))
    (d / "model.safetensors").write_text(f"box-install rehearsal placeholder for {name}: not a model\n")
    return d


def _real(models: Path, name: str) -> Path:
    d = models / name
    d.mkdir(parents=True)
    (d / "config.json").write_text(json.dumps({"architectures": ["Gemma4ForConditionalGeneration"]}))
    (d / "model.safetensors").write_bytes(b"weights")
    return d


def _box(tmp: Path, *, rehearsal_bundle: bool = True, real_verifier: bool = False) -> tuple[Path, Path]:
    deploy = tmp / "deploy"
    models = deploy / "models"
    _placeholder(models, "gemma-4-26b-a4b-it-4bit")
    (_real if real_verifier else _placeholder)(models, "qwen3.5-9b-4bit")
    (deploy / "updates").mkdir(parents=True)
    rec: dict[str, Any] = {"format": "trialbox-installed/1", "release_seq": 1, "bundle_id": "rehearsal-x", "state": {}}
    if rehearsal_bundle:
        rec["rehearsal"] = True
    rec["rehearsal_box"] = True  # the mark of install.sh --rehearsal, recorded at the load (the integrator's (i))
    (deploy / "updates" / "installed.json").write_text(json.dumps(rec))
    return models, deploy / "site" / "registry.site.yaml"


def test_all_three_hold_the_pair_is_pinned_as_rehearsal_placeholder_candidates(tmp_path: Path) -> None:
    models, out = _box(tmp_path)
    ok, lines = pin_model.install_pins("rtxpro6000", models, out, dict(REHEARSAL_BOX))
    assert ok, lines
    assert all("rehearsal placeholder" in x and "as candidate" in x for x in lines), lines
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))["builds"]
    assert {e["status"] for e in doc.values()} == {"candidate"}
    assert {e["weights"]["trust"] for e in doc.values()} == {"rehearsal_placeholder"}
    reg = Registry.load(DEFAULT_PATH, out)
    assert reg.resolve("j-workhorse", "serving", role="judge", env=Environment.TEST).build.build_id == JUDGE
    # never PRODUCTION; VALIDATION is a rehearsal box's environment since the integrator's (i) (D-887), where it
    # routes only with the recorded mark (tests/unit/test_rehearsal_validation_box.py)
    with pytest.raises(RegistryError):
        reg.resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION)


@pytest.mark.parametrize(
    ("env", "bundle", "why"),
    [
        ({"TB_ENV": "TEST"}, True, "rehearsal box"),  # TB_REHEARSAL missing
        ({"TB_REHEARSAL": "1"}, True, "rehearsal box"),  # TB_ENV missing
        (REHEARSAL_BOX, False, "rehearsal bundle"),
        ({"TB_ENV": "PRODUCTION", "TB_REHEARSAL": "1"}, True, "rehearsal box"),
        # VALIDATION with TB_REHEARSAL=1 is a rehearsal box since (i) when installed.json records the mark; without
        # the record it is refused (test_rehearsal_validation_box.py); DEV never is
        ({"TB_ENV": "DEV", "TB_REHEARSAL": "1"}, True, "rehearsal box"),
    ],
)
def test_one_condition_missing_refuses_the_pin(tmp_path: Path, env: dict[str, str], bundle: bool, why: str) -> None:
    models, out = _box(tmp_path, rehearsal_bundle=bundle)
    ok, lines = pin_model.install_pins("rtxpro6000", models, out, env)
    assert not ok and any(why in x for x in lines), lines
    assert not out.exists()


def test_a_real_folder_beside_a_placeholder_refuses_the_whole_pin(tmp_path: Path) -> None:
    models, out = _box(tmp_path, real_verifier=True)
    ok, lines = pin_model.install_pins("rtxpro6000", models, out, dict(REHEARSAL_BOX))
    assert not ok and any("no mixing" in x for x in lines), lines
    assert not out.exists()


def test_a_placeholder_pin_is_never_promoted(tmp_path: Path) -> None:
    models, out = _box(tmp_path)
    assert pin_model.install_pins("rtxpro6000", models, out, dict(REHEARSAL_BOX))[0]
    with pytest.raises(pin_model.PinError, match="rehearsal placeholder"):
        pin_model.promote(JUDGE, tmp_path / "any-record.json", out)


def test_qualify_refuses_a_placeholder_pin_by_name(tmp_path: Path) -> None:
    from tools import qualify as q

    models, out = _box(tmp_path)
    assert pin_model.install_pins("rtxpro6000", models, out, dict(REHEARSAL_BOX))[0]
    got = q.placeholder_problems(out)
    assert len(got) == 2 and all("rehearsal placeholder" in p for p in got)
    assert q.placeholder_problems(tmp_path / "no-such.yaml") == []


def test_the_doctor_names_a_placeholder_pin(tmp_path: Path) -> None:
    from tools.trialbox import doctor

    models, out = _box(tmp_path)
    assert pin_model.install_pins("rtxpro6000", models, out, dict(REHEARSAL_BOX))[0]
    line = doctor.placeholder_note(Registry.load(DEFAULT_PATH, out))
    assert "rehearsal placeholder" in line and JUDGE in line and VERIFIER in line


def test_the_installer_hands_the_box_to_the_pin_and_the_record_keeps_the_bundle_kind() -> None:
    install = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    pin = install[
        install.index("python -m tools.pin_model --install") - 600 : install.index(
            "python -m tools.pin_model --install"
        )
    ]
    assert '-e TB_ENV="$TB_ENV_SITE"' in pin and '-e TB_REHEARSAL="$(envget TB_REHEARSAL)"' in pin
    update = (ROOT / "tools" / "trialbox" / "update.py").read_text(encoding="utf-8")
    assert 'record["rehearsal"] = True' in update


def test_the_shipped_promotion_leaves_a_placeholder_pair_alone_and_says_why(tmp_path: Path, capsys: Any) -> None:
    """The install's HW-003 step (--promote-shipped) on a rehearsal box: a placeholder is never promoted, so it is said
    (exit 5, a note for the installer), not reported as a pair that failed to qualify."""
    models, out = _box(tmp_path)
    assert pin_model.install_pins("rtxpro6000", models, out, dict(REHEARSAL_BOX))[0]
    rc = pin_model.main(["--promote-shipped", "rtxpro6000", "--records", str(tmp_path / "q"), "--out", str(out)])
    assert rc == 5 and "rehearsal placeholder" in capsys.readouterr().out
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))["builds"]
    assert {e["status"] for e in doc.values()} == {"candidate"}
    install = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    step = install[install.index('pin_tool --promote-shipped "$GPU"') :][:3000]
    assert 'elif [ "$rc" = 5 ]; then' in step
