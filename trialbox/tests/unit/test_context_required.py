"""LLM-007 (D-568): no build on a local model server is routed in PRODUCTION without a known context, and the
install writes the context into the site pin of a build whose registry row has none (the shared-quota pair: the
partition's size is known when it is measured). Synthetic weight folders of a few bytes; no model."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from registry.registry import REFUSAL_ORDER, Registry, RegistryError
from tb_common.policy.classes import Environment

from tests.model_pins import promote_pins, release_registry
from tools import pin_model

JUDGE, VERIFIER = "gemma-4-26b-a4b-it-sharedquota", "qwen3.5-9b-sharedquota"
LENGTHS = {"JUDGE_MAX_LEN": "16384", "VERIFIER_MAX_LEN": "12288"}

pytestmark = pytest.mark.nodb


def _box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    models = tmp_path / "models"
    folders = {}
    for build, name, payload in ((JUDGE, "gemma-4-26b-a4b-it-4bit", b"judge"), (VERIFIER, "qwen3.5-9b-4bit", b"v")):
        d = models / name
        d.mkdir(parents=True)
        (d / "model.safetensors").write_bytes(b"synthetic " + payload)
        folders[build] = d
    release = release_registry(tmp_path, folders, monkeypatch)
    return release, models, tmp_path / "site" / "registry.site.yaml"


def _pins(out: Path) -> dict[str, dict[str, object]]:
    return dict(yaml.safe_load(out.read_text(encoding="utf-8"))["builds"])


# ------------------------------------------------------------------------------------------------ the premise
def test_the_shared_quota_rows_name_no_context() -> None:
    doc = yaml.safe_load((Path(pin_model.__file__).resolve().parents[1] / "models/registry.yaml").read_text("utf-8"))
    rows = {b["build_id"]: b for b in doc["builds"]}
    assert rows[JUDGE].get("context_length") is None and rows[VERIFIER].get("context_length") is None


# ------------------------------------------------------------------------------------------------ the install
def test_the_install_writes_the_servers_length_into_the_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release, models, out = _box(tmp_path, monkeypatch)
    ok, lines = pin_model.install_pins("shared-quota", models, out, dict(LENGTHS))
    assert ok, lines
    pins = _pins(out)
    assert pins[JUDGE]["context_length"] == 16384 and pins[VERIFIER]["context_length"] == 12288
    assert "context 16384 (JUDGE_MAX_LEN)" in lines[0] and "context 12288 (VERIFIER_MAX_LEN)" in lines[1]
    reg = Registry.load(release, out)
    assert reg.build(JUDGE).context_length == 16384


@pytest.mark.parametrize(
    ("value", "still_ok"),
    [(None, True), ("", True), ("unmeasured", True), ("0", False), ("-5", False), ("16k", False),
     ("16384.5", False), ("True", False)],
)  # fmt: skip
def test_without_a_whole_number_the_install_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str | None, still_ok: bool
) -> None:
    """Not measured yet (unset, or the platform's placeholder): said, and the pair's result stays, so the
    platform's pin job does not fail before the partition is measured. A value that is set and is no length is a
    mistake: not ok. Either way PRODUCTION routes nothing to the build (below)."""
    _, models, out = _box(tmp_path, monkeypatch)
    env = {"VERIFIER_MAX_LEN": "12288"} | ({} if value is None else {"JUDGE_MAX_LEN": value})
    ok, lines = pin_model.install_pins("shared-quota", models, out, env)
    assert ok is still_ok, lines
    said = next(ln for ln in lines if ln.startswith(JUDGE) and "JUDGE_MAX_LEN" in ln)
    assert "no context" in said and "routes nothing in PRODUCTION" in said
    pins = _pins(out)
    assert "context_length" not in pins[JUDGE] and pins[JUDGE]["sha256"]  # the weights' pin is kept
    assert pins[VERIFIER]["context_length"] == 12288


def test_a_build_pinned_before_gets_its_context_added(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, models, out = _box(tmp_path, monkeypatch)
    pin_model.install_pins("shared-quota", models, out, {})
    assert "context_length" not in _pins(out)[JUDGE]
    ok, lines = pin_model.install_pins("shared-quota", models, out, dict(LENGTHS))
    assert ok, lines
    assert lines[0].startswith(f"{JUDGE}: already pinned") and "context 16384 (JUDGE_MAX_LEN)" in lines[0]
    assert _pins(out)[JUDGE]["context_length"] == 16384
    ok, lines = pin_model.install_pins("shared-quota", models, out, {})  # pinned with a context: nothing to ask
    assert ok and all("context" not in ln for ln in lines), lines


def test_a_row_that_names_its_context_keeps_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The registry's value is the one the pair was measured with: the variables are not read for it."""
    build = "gemma-4-26b-a4b-it-rtxpro6000"
    d = tmp_path / "models" / "gemma-4-26b-a4b-it-4bit"
    d.mkdir(parents=True)
    (d / "model.safetensors").write_bytes(b"synthetic judge")
    release = release_registry(tmp_path, {build: d}, monkeypatch)
    out = tmp_path / "site" / "registry.site.yaml"
    _ok, lines = pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {"JUDGE_MAX_LEN": "4096"})
    assert lines[0].startswith(f"{build}: pinned") and "context" not in lines[0]
    assert "context_length" not in _pins(out)[build]
    assert Registry.load(release, out).build(build).context_length == 32768


# ------------------------------------------------------------------------------------------------ the gateway
def test_production_refuses_a_local_build_whose_context_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, models, out = _box(tmp_path, monkeypatch)
    pin_model.install_pins("shared-quota", models, out, {})
    promote_pins(out)
    reg = Registry.load(release, out)
    with pytest.raises(RegistryError) as e:
        reg.resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION)
    assert e.value.reason == "context_unknown"
    assert "JUDGE_MAX_LEN" in str(e.value) and "pin_model --install" in str(e.value)  # the reason names the fix
    assert reg.resolve("j-workhorse", "serving", role="judge", env=Environment.TEST).build.build_id == JUDGE
    assert "context_unknown" in REFUSAL_ORDER

    pin_model.install_pins("shared-quota", models, out, dict(LENGTHS))
    reg = Registry.load(release, out)
    got = reg.resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION)
    assert got.build.build_id == JUDGE and got.build.context_length == 16384


def test_the_stub_and_hosted_builds_are_not_touched() -> None:
    reg = Registry.load()
    assert reg.build("trialbox-stub-1").context_length is None
    assert not reg.build("trialbox-stub-1").context_unknown()
    assert not reg.build("or-gpt-oss-120b").context_unknown()  # hosted: the provider's limit, not this box's
    for b in reg.builds:
        assert b.context_unknown() == (b.serving == "vllm" and not b.context_length), b.build_id


# ------------------------------------------------------------------------- the review of PR #359
def test_review_a_changed_length_replaces_the_pins_and_is_said(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MED-2: a partition measured again at another size was kept at the old one without a word."""
    _, models, out = _box(tmp_path, monkeypatch)
    pin_model.install_pins("shared-quota", models, out, dict(LENGTHS))
    ok, lines = pin_model.install_pins("shared-quota", models, out, {"JUDGE_MAX_LEN": "8192", "VERIFIER_MAX_LEN": "x"})
    assert not ok  # the verifier's value is set and is no length
    assert "context 8192 (JUDGE_MAX_LEN; was 16384)" in lines[0] and _pins(out)[JUDGE]["context_length"] == 8192
    assert "VERIFIER_MAX_LEN is 'x'" in lines[1] and _pins(out)[VERIFIER]["context_length"] == 12288  # kept, and said


def test_review_a_build_outside_the_installed_pairs_gets_its_context_by_hand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """MED-1: `--install` never reaches a candidate that is in no profile's pair; the refusal named no way out."""
    build = "qwen3.5-35b-a3b-candidate"
    d = tmp_path / "m"
    d.mkdir()
    (d / "model.safetensors").write_bytes(b"synthetic")
    out = tmp_path / "site" / "o.yaml"
    args = ["--build", build, "--model-dir", str(d), "--served-name", "s", "--out", str(out), "--trust-first-use"]
    assert pin_model.main([*args, "--context", "16384"]) == 0
    assert _pins(out)[build]["context_length"] == 16384 and "context 16384" in capsys.readouterr().out
    assert pin_model.main([*args, "--context", "0"]) == 2
    promote_pins(out)
    reg = Registry.load(override=out)
    assert reg.resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION).build.build_id == build


def test_review_the_messages_name_a_fix_that_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release, models, out = _box(tmp_path, monkeypatch)
    _ok, lines = pin_model.install_pins("shared-quota", models, out, {})
    for said in ("the environment of pin_model --install", "serving.env", "--build", "--context"):
        assert said in lines[0], said
    promote_pins(out)
    with pytest.raises(RegistryError) as e:
        Registry.load(release, out).resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION)
    assert "pin_model --build" in str(e.value) and "--context" in str(e.value) and "deploy/.env" not in str(e.value)


@pytest.mark.parametrize("value", ["16k", "16384", [1], True, -5, 1.5, 0])
def test_review_a_context_that_is_not_a_whole_number_above_zero_is_not_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    """LOW-3: an override's context was not checked: '16k' resolved and then broke the gateway's size check."""
    release, models, out = _box(tmp_path, monkeypatch)
    pin_model.install_pins("shared-quota", models, out, dict(LENGTHS))
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    doc["builds"][JUDGE]["context_length"] = value
    out.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="context_length"):
        Registry.load(release, out)


def test_review_the_refusal_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A champion that is neither qualified nor sized is told the first thing first; so is an unpinned build."""
    release, models, out = _box(tmp_path, monkeypatch)
    pin_model.install_pins("shared-quota", models, out, {})
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    doc["builds"][JUDGE]["status"] = "champion"  # by hand: no qualification record
    out.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(RegistryError) as e:
        Registry.load(release, out).resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION)
    assert e.value.reason == "champion_unqualified"
    assert REFUSAL_ORDER.index("weights_unexpected") < REFUSAL_ORDER.index("context_unknown")
    assert REFUSAL_ORDER.index("context_unknown") < REFUSAL_ORDER.index("build_unpinned")
