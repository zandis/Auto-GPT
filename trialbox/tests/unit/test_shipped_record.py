"""HW-003 with LLM-005 (D-569): the vendor's qualification record ships under ``deploy/qualification/<profile>/``
and ``pin_model --promote-shipped`` promotes the pinned pair when the record qualified exactly the box's weights,
model server image and chat template; ``install.sh`` keeps the promotion only when the box's canary passes.
Synthetic weight folders of a few bytes and records written here; no model."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from registry.registry import Registry, RegistryError
from tb_common.policy.classes import Environment

from tests.model_pins import release_registry
from tests.unit.test_champion_qualify import _record
from tools import pin_model
from tools import qualify as q

ROOT = Path(__file__).resolve().parents[2]
JUDGE, VERIFIER = "gemma-4-26b-a4b-it-rtxpro6000", "qwen3.5-9b-rtxpro6000"
DIGEST = "sha256:" + "ab" * 32

pytestmark = pytest.mark.nodb


class Box:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = tmp_path
        self.models = tmp_path / "models"
        folders = {}
        for build, name in ((JUDGE, "gemma-4-26b-a4b-it-4bit"), (VERIFIER, "qwen3.5-9b-4bit")):
            d = self.models / name
            d.mkdir(parents=True)
            (d / "model.safetensors").write_bytes(f"synthetic {build}".encode())
            folders[build] = d
        self.release = release_registry(tmp_path, folders, monkeypatch)
        self.out = tmp_path / "site" / "registry.site.yaml"
        ok, lines = pin_model.install_pins("rtxpro6000", self.models, self.out, {})
        assert ok, lines
        self.records = tmp_path / "qualification"
        self.lock = tmp_path / "images.lock"
        self.lock.write_text(json.dumps({"third_party": {"vllm": {"image": "vllm/vllm-openai:t", "digest": DIGEST}}}))

    def pins(self) -> dict[str, dict[str, Any]]:
        return dict(yaml.safe_load(self.out.read_text(encoding="utf-8"))["builds"])

    def record(self, name: str = "ok", **change: Any) -> Path:
        """A passing record for the pinned pair, as the vendor's run on the same card type writes it."""
        pins = self.pins()
        builds = {"judge": (JUDGE, change.pop("judge_sha", pins[JUDGE]["sha256"])),
                  "verifier": (change.pop("verifier_build", VERIFIER), pins[VERIFIER]["sha256"])}  # fmt: skip
        src = _record(
            self.root / name, builds, failed=change.pop("failed", ""), profile=change.pop("profile", "rtxpro6000")
        )
        doc = json.loads(src.read_text(encoding="utf-8"))
        detail = {
            "model_server_image": {"image": "vllm/vllm-openai:t", "digest": DIGEST},
            "chat_template_sha256": pins[JUDGE]["weights"]["chat_template"]["sha256"],
            "driver": "595.58", "gpu": "RTX PRO 6000",
        }  # fmt: skip
        detail.update(change)
        doc["steps"]["serving_record"]["detail"] = {k: v for k, v in detail.items() if v is not None}
        doc["record_id"] = f"rtxpro6000-test-{name}"
        q.finalize(doc)
        path = self.records / "rtxpro6000" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
        return path

    def promote(self) -> tuple[bool, list[str]]:
        return pin_model.promote_shipped("rtxpro6000", self.records, self.out, images_lock=self.lock)

    def routes(self) -> bool:
        reg = Registry.load(self.release, self.out)
        try:
            reg.resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION)
            reg.resolve("v-verifier", "verifier", role="judge", env=Environment.PRODUCTION)
        except RegistryError:
            return False
        return True


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Box:
    return Box(tmp_path, monkeypatch)


# ------------------------------------------------------------------------------------------------ the promotion
def test_before_a_record_the_pinned_pair_routes_nothing_in_production(box: Box) -> None:
    assert not box.routes()
    ok, lines = box.promote()
    assert not ok and "no shipped qualification record for profile rtxpro6000" in lines[0]
    assert {p.get("status") for p in box.pins().values()} == {"candidate"} and not box.routes()


def test_a_record_for_exactly_this_box_promotes_both_builds(box: Box) -> None:
    rec = box.record()
    ok, lines = box.promote()
    assert ok, lines
    pins = box.pins()
    for build in (JUDGE, VERIFIER):
        assert pins[build]["status"] == "champion"
        assert pins[build]["qualification"]["record"] == rec.name
        assert pins[build]["qualification"]["weights_sha256"] == pins[build]["sha256"]
    assert box.routes()
    assert any("595.58" in ln and "RTX PRO 6000" in ln and "canary" in ln for ln in lines)  # what it was taken on
    ok, lines = box.promote()  # the install runs again before the canary passed: still waiting for it
    assert ok and any("waits for the canary" in ln for ln in lines), lines
    pin_model.confirm_shipped("rtxpro6000", box.out)
    ok, lines = box.promote()
    assert ok and all("already champion" in ln for ln in lines), lines


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"judge_sha": "ef" * 32}, "qualified other weights"),
        (
            {"model_server_image": {"image": "vllm/vllm-openai:t", "digest": "sha256:" + "cd" * 32}},
            "model server image",
        ),
        ({"model_server_image": None}, "does not name the model server image"),
        ({"chat_template_sha256": "12" * 32}, "chat template"),
        ({"chat_template_sha256": None}, "does not name the judge's chat template"),
        ({"failed": "canary"}, "failed steps canary"),
        ({"profile": "gb10"}, "is for profile gb10"),
        ({"verifier_build": "qwen3.5-9b-spark"}, f"does not name build {VERIFIER}"),
    ],
)
def test_a_record_that_is_not_this_boxs_promotes_nothing_and_says_why(
    box: Box, change: dict[str, Any], said: str
) -> None:
    rec = box.record("other", **change)
    ok, lines = box.promote()
    assert not ok and any(ln.startswith(f"{rec.name}: ") and said in ln for ln in lines), lines
    assert {p.get("status") for p in box.pins().values()} == {"candidate"} and not box.routes()


def test_an_edited_record_is_refused(box: Box) -> None:
    rec = box.record()
    doc = json.loads(rec.read_text(encoding="utf-8"))
    doc["steps"]["n12"]["reason"] = "edited after the run"
    rec.write_text(json.dumps(doc), encoding="utf-8")
    ok, lines = box.promote()
    assert not ok and "edited after it was written" in lines[0] and not box.routes()
    rec.write_text("{ not json", encoding="utf-8")
    ok, lines = box.promote()
    assert not ok and "not a readable qualification record" in lines[0]


def test_the_matching_record_is_found_among_others(box: Box) -> None:
    box.record("a-older", judge_sha="ef" * 32)
    good = box.record("b-this")
    ok, _lines = box.promote()
    assert ok and box.pins()[JUDGE]["qualification"]["record"] == good.name


def test_a_build_that_is_not_pinned_stops_the_promotion(box: Box) -> None:
    box.record()
    doc = yaml.safe_load(box.out.read_text(encoding="utf-8"))
    del doc["builds"][VERIFIER]
    box.out.write_text(yaml.safe_dump(doc), encoding="utf-8")
    ok, lines = box.promote()
    assert not ok and f"{VERIFIER}: not pinned" in lines[0]
    assert box.pins()[JUDGE].get("status") == "candidate"  # both or neither


def test_demote_puts_the_pair_back_to_candidate(box: Box) -> None:
    box.record()
    assert box.promote()[0] and box.routes()
    lines = pin_model.demote_pair("rtxpro6000", box.out)
    assert len(lines) == 2 and all("back to candidate" in ln for ln in lines)
    pins = box.pins()
    assert {p["status"] for p in pins.values()} == {"candidate"} and not box.routes()
    assert all("qualification" not in p for p in pins.values())
    assert pins[JUDGE]["sha256"] and pins[JUDGE]["weights"]["chat_template"]  # the pins themselves are kept
    assert pin_model.demote_pair("rtxpro6000", box.out) == []  # nothing to put back


def test_the_cli(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["--records", str(box.records), "--images-lock", str(box.lock), "--out", str(box.out)]
    assert pin_model.main(["--promote-shipped", "rtxpro6000", *args]) == 3  # nothing to promote: its own code
    box.record()
    assert pin_model.main(["--promote-shipped", "rtxpro6000", *args]) == 0
    assert "champion" in capsys.readouterr().out
    assert pin_model.main(["--confirm-shipped", "rtxpro6000", "--out", str(box.out)]) == 0  # the canary passed
    assert pin_model.main(["--promote-shipped", "rtxpro6000", *args]) == 4  # champion already: its own code
    assert pin_model.main(["--demote-pair", "rtxpro6000", "--out", str(box.out)]) == 0
    assert not box.routes()


# ------------------------------------------------------------------------------------------------ the record
def test_the_serving_record_names_the_model_server_image_and_the_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = json.loads((ROOT / "deploy" / "images.lock").read_text(encoding="utf-8"))["third_party"]["vllm"]
    assert q.model_server_image() == {"image": lock["image"], "digest": lock["digest"]}
    box = Box(tmp_path, monkeypatch)
    monkeypatch.setenv("TB_REGISTRY_OVERRIDE", str(box.out))
    assert q.pinned_template_sha256(JUDGE) == box.pins()[JUDGE]["weights"]["chat_template"]["sha256"]
    assert q.pinned_template_sha256(VERIFIER) is None
    doc = q.qualify(q.Options(profile="ci", stub=True, operator="t", sources=()), steps=("serving_record",))
    detail = doc["steps"]["serving_record"]["detail"]
    assert detail["model_server_image"] == q.model_server_image() and "chat_template_sha256" in detail


def test_the_shipped_records_folder_rides_in_the_host_tree_and_committed_records_qualify() -> None:
    from tools import host_tree

    assert "deploy" in host_tree.TOP_DIRS and not any(s.startswith("deploy/qualification") for s in host_tree.STATE)
    readme = (ROOT / "deploy" / "qualification" / "README.md").read_text(encoding="utf-8")
    assert "--promote-shipped" in readme and "<profile>" in readme
    for rec in sorted((ROOT / "deploy" / "qualification").glob("*/*.json")):  # none yet: lane G's first record
        doc = json.loads(rec.read_text(encoding="utf-8"))
        assert q.check_record(doc, profile=rec.parent.name, environment="PRODUCTION") == [], rec.name


# ------------------------------------------------------------------------------------------------ the install
START = "# HW-003 (D-569): the shipped qualification record"
END = "\n# T-632 (OPS-014): every overlay renders"


def _install_block(
    tmp_path: Path, promote_rc: int, canary_rc: int = 0, *, restart_rc: int = 0, demote_rc: int = 0, tree: bool = False
) -> subprocess.CompletedProcess[str]:
    """The installer's own block with a `docker` and a `python3` that answer as told; what they were asked is
    written to `calls`. ``tree``: deploy/qualification and deploy/images.lock are links, as tools/host_tree.py
    makes them on a box installed from a bundle."""
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert text.count(START) == 1 and text.count(END) == 1
    block = text[text.index(START) : text.index(END)]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    (bin_dir / "docker").write_text(
        f'#!/bin/sh\necho "docker $*" >> {calls}\n'
        f'case "$*" in *--promote-shipped*) echo "promote says"; exit {promote_rc};; '
        f'*--demote-pair*) exit {demote_rc};; *"restart gateway"*) exit {restart_rc};; esac\nexit 0\n'
    )
    (bin_dir / "python3").write_text(
        f'#!/bin/sh\necho "python3 $*" >> {calls}\ncase "$*" in *selftest*) echo "canary says"; exit {canary_rc};; esac\nexit 0\n'
    )
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    (tmp_path / "deploy" / "site").mkdir(parents=True)
    (tmp_path / "deploy" / "site" / "registry.site.yaml").write_text("kind: registry-site-override\n")
    if tree:
        cur = tmp_path / "current" / "deploy"
        (cur / "qualification" / "rtxpro6000").mkdir(parents=True)
        (cur / "images.lock").write_text("{}")
        (tmp_path / "deploy" / "qualification").symlink_to("../current/deploy/qualification")
        (tmp_path / "deploy" / "images.lock").symlink_to("../current/deploy/images.lock")
    script = (
        "set -euo pipefail\nsay() { printf '==> %s\\n' \"$*\"; }\n"
        f'MODE=gpu\nGPU=rtxpro6000\nROOT="{tmp_path}"\nIMAGE_PY=trialbox-py:1.0.0\nCOMPOSE=(docker compose)\nFAILS=()\n'
        + block
        + '\necho "block done"\nprintf \'FAIL: %s\\n\' ${FAILS[@]+"${FAILS[@]}"}\n'
    )
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    r = subprocess.run(["bash", "-c", script], env=env, cwd=tmp_path, capture_output=True, text=True, check=False)
    r.calls = calls.read_text(encoding="utf-8") if calls.exists() else ""  # type: ignore[attr-defined]
    r.fails = [ln for ln in r.stdout.splitlines() if ln.startswith("FAIL: ") and ln != "FAIL: "]  # type: ignore[attr-defined]
    return r


def test_the_install_promotes_and_keeps_the_pair_when_the_canary_passes(tmp_path: Path) -> None:
    r = _install_block(tmp_path, 0, 0)
    assert r.returncode == 0 and "block done" in r.stdout, r.stderr
    calls = r.calls  # type: ignore[attr-defined]
    assert "--promote-shipped rtxpro6000 --records /q --images-lock /images.lock" in calls
    order = [calls.index(x) for x in ("--promote-shipped", "restart gateway", "up -d --wait gateway", "selftest",
                                      "--confirm-shipped rtxpro6000", "restart orchestrator")]  # fmt: skip
    assert order == sorted(order)  # the gateway is waited for; the orchestrator's own start canary opens its gate
    assert "--demote-pair" not in calls and r.fails == []  # type: ignore[attr-defined]


def test_the_install_puts_the_pair_back_when_the_canary_fails(tmp_path: Path) -> None:
    r = _install_block(tmp_path, 0, 1)
    calls = r.calls  # type: ignore[attr-defined]
    assert calls.index("selftest") < calls.index("--demote-pair rtxpro6000") and "--confirm-shipped" not in calls
    assert calls.count("restart gateway") == 2  # once on the promoted pins, once on the pins put back
    assert len(r.fails) == 1 and "the canary on this box did not pass" in r.fails[0]  # type: ignore[attr-defined]
    assert "it is back to candidate" in r.fails[0]  # type: ignore[attr-defined]


def test_review_a_gateway_that_does_not_restart_is_a_failed_canary_not_a_stop(tmp_path: Path) -> None:
    """HIGH-2: the restart was unguarded under `set -e`: the block ended there, promoted and never canaried."""
    r = _install_block(tmp_path, 0, 0, restart_rc=1)
    calls = r.calls  # type: ignore[attr-defined]
    assert "block done" in r.stdout and "selftest" not in calls and "--demote-pair rtxpro6000" in calls
    assert len(r.fails) == 1  # type: ignore[attr-defined]


def test_review_a_demotion_that_fails_is_said_as_such(tmp_path: Path) -> None:
    r = _install_block(tmp_path, 0, 1, demote_rc=1)
    assert len(r.fails) == 1 and "could NOT be put back" in r.fails[0]  # type: ignore[attr-defined]
    assert "--demote-pair rtxpro6000" in r.fails[0] and "it is back to candidate" not in r.fails[0]  # type: ignore[attr-defined]


def test_review_the_links_of_a_bundle_install_are_resolved_before_they_are_mounted(tmp_path: Path) -> None:
    """HIGH-1: tools/host_tree.py makes deploy/qualification and deploy/images.lock links into ../current; mounted
    as part of deploy/ they dangle inside the container, and every install said "no shipped record"."""
    r = _install_block(tmp_path, 0, 0, tree=True)
    line = next(ln for ln in r.calls.splitlines() if "--promote-shipped" in ln)  # type: ignore[attr-defined]
    assert f"-v {tmp_path}/current/deploy/qualification:/q:ro" in line
    assert f"-v {tmp_path}/current/deploy/images.lock:/images.lock:ro" in line
    assert f"-v {tmp_path}/deploy/site:/d/site" in line


@pytest.mark.parametrize("rc", [3, 1])
def test_without_a_matching_record_the_install_goes_on_with_a_fail_line(tmp_path: Path, rc: int) -> None:
    r = _install_block(tmp_path, rc, 0)
    calls = r.calls  # type: ignore[attr-defined]
    assert r.returncode == 0 and "selftest" not in calls and "restart gateway" not in calls
    assert len(r.fails) == 1 and "the model pair is not qualified on this box" in r.fails[0]  # type: ignore[attr-defined]
    assert "deploy/qualification" in r.fails[0]  # type: ignore[attr-defined]


def test_a_pair_that_was_champion_before_the_install_is_left_alone(tmp_path: Path) -> None:
    """A pair qualified on the box by its own record, or promoted and confirmed by an earlier install."""
    r = _install_block(tmp_path, 4, 1)
    calls = r.calls  # type: ignore[attr-defined]
    assert r.returncode == 0 and "selftest" not in calls and "--demote-pair" not in calls
    assert r.fails == []  # type: ignore[attr-defined]


# ------------------------------------------------------------------------------------------------ the review of #361
def test_review_a_promotion_waits_for_its_canary_until_it_is_confirmed(box: Box) -> None:
    """HIGH-2: an install that died between the promotion and the canary left a champion; the next install said
    "already champion" and never ran the canary."""
    box.record()
    args = ["--records", str(box.records), "--images-lock", str(box.lock), "--out", str(box.out)]
    assert pin_model.main(["--promote-shipped", "rtxpro6000", *args]) == 0
    pending = box.out.parent / pin_model.PENDING_NAME
    assert json.loads(pending.read_text(encoding="utf-8"))["record_id"] == "rtxpro6000-test-ok"
    assert pin_model.main(["--promote-shipped", "rtxpro6000", *args]) == 0  # still to be canaried, not "already"
    assert pin_model.main(["--confirm-shipped", "rtxpro6000", "--out", str(box.out)]) == 0
    assert not pending.exists()
    assert pin_model.main(["--promote-shipped", "rtxpro6000", *args]) == 4
    assert pin_model.main(["--confirm-shipped", "rtxpro6000", "--out", str(box.out)]) == 1  # nothing waits


def test_review_demote_touches_only_what_the_shipped_record_promoted(box: Box) -> None:
    """LOW-10: a judge promoted on the box from its own record lost its reference when the canary failed."""
    own = _record(box.root / "own", {"judge": (JUDGE, box.pins()[JUDGE]["sha256"]),
                                      "verifier": (VERIFIER, box.pins()[VERIFIER]["sha256"])})  # fmt: skip
    doc = json.loads(own.read_text(encoding="utf-8"))
    doc["record_id"] = "qualified-on-this-box"
    q.finalize(doc)
    own.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
    pin_model.promote(JUDGE, own, box.out)
    box.record()
    assert box.promote()[0]
    lines = pin_model.demote_pair("rtxpro6000", box.out)
    assert len(lines) == 1 and lines[0].startswith(VERIFIER)
    assert box.pins()[JUDGE]["status"] == "champion" and box.pins()[VERIFIER]["status"] == "candidate"
    assert not (box.out.parent / pin_model.PENDING_NAME).exists()


def test_review_a_judge_pinned_without_its_template_is_not_promoted(box: Box) -> None:
    """MED-5: the template check was skipped when the pin held none."""
    box.record(chat_template_sha256=None)
    doc = yaml.safe_load(box.out.read_text(encoding="utf-8"))
    del doc["builds"][JUDGE]["weights"]["chat_template"]
    box.out.write_text(yaml.safe_dump(doc), encoding="utf-8")
    ok, lines = box.promote()
    assert not ok and "pinned without the chat template" in lines[0] and not box.routes()


def test_review_a_shipped_promotion_is_checked_again_and_taken_back_when_the_release_changed(box: Box) -> None:
    """MED-6: after an update with another model server image the pair stayed champion on the old record."""
    box.record()
    assert box.promote()[0]
    pin_model.confirm_shipped("rtxpro6000", box.out)
    box.lock.write_text(json.dumps({"third_party": {"vllm": {"image": "v", "digest": "sha256:" + "cd" * 32}}}))
    ok, lines = box.promote()
    assert not ok and any("model server image" in ln for ln in lines) and any("back to candidate" in ln for ln in lines)
    assert not box.routes()


def test_review_a_champion_by_hand_without_a_record_is_not_called_qualified(box: Box) -> None:
    """LOW-11: status champion written by hand made the install say nothing while PRODUCTION routed nothing."""
    doc = yaml.safe_load(box.out.read_text(encoding="utf-8"))
    for b in (JUDGE, VERIFIER):
        doc["builds"][b]["status"] = "champion"
    box.out.write_text(yaml.safe_dump(doc), encoding="utf-8")
    ok, lines = box.promote()
    assert not ok and "no shipped qualification record" in lines[0]


def test_review_a_promotion_that_breaks_half_way_changes_nothing(box: Box, monkeypatch: pytest.MonkeyPatch) -> None:
    """LOW-9: only PinError was caught: another error from the second build left the first one champion."""
    box.record()
    real = pin_model.promote

    def second_fails(build: str, *a: Any, **kw: Any) -> str:
        if build == VERIFIER:
            raise PermissionError("planted")
        return real(build, *a, **kw)

    monkeypatch.setattr(pin_model, "promote", second_fails)
    ok, lines = box.promote()
    assert not ok and "planted" in lines[0]
    assert {p.get("status") for p in box.pins().values()} == {"candidate"}
    assert not (box.out.parent / pin_model.PENDING_NAME).exists()


def test_review_a_profile_without_a_qualification_profile_says_so(box: Box) -> None:
    """MED-7: the judge-alone profile has no qualification profile, so no record can ever be shipped for it."""
    ok, lines = pin_model.promote_shipped("rtx4090", box.records, box.out, images_lock=box.lock)
    assert not ok and "has no qualification profile" in lines[0]
