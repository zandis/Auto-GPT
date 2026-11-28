"""``champion`` only through ``qualify`` (T-012b, D-358; deep review LLM-007, LLM-029, CR-079).

* Every local build names its expected weights (manifest sha256 and revision) in ``models/registry.yaml``; the values
  equal what the measured serving record says about the release.
* ``pin_model`` refuses a folder whose manifest differs (the review's folder of one 16-byte file) and refuses to trust
  weights on first use when nothing is expected; ``--install`` pins ``candidate``, never ``champion``.
* ``pin_model --promote`` makes a champion only from a passing qualification record for exactly the pinned weights.
* A PRODUCTION gateway refuses a champion without that record with a named refusal (``champion_unqualified``), and any
  gateway refuses a pin that is not the expected release (``weights_unexpected``).

Every weight folder here is a few synthetic bytes; no model is downloaded.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from registry.registry import DEFAULT_PATH, Registry, RegistryError
from tb_common.policy.classes import Environment

from tests.model_pins import promote_pins, qualified, release_registry
from tests.unit.test_gateway import H, _gw, _judge_body, _mock
from tools import pin_model
from tools import qualify as q

ROOT = Path(__file__).resolve().parents[2]
JUDGE = "gemma-4-26b-a4b-it-rtxpro6000"
VERIFIER = "qwen3.5-9b-rtxpro6000"
UNEXPECTED = "qwen3.5-35b-a3b-candidate"  # a candidate whose release is not measured yet: nothing expected


def _sixteen_bytes(root: Path) -> Path:
    """The review's run: a folder holding one 16-byte file, named like weights."""
    d = root / "gemma-4-26b-a4b-it-4bit"
    d.mkdir(parents=True)
    (d / "model.safetensors").write_bytes(b"0123456789abcdef")
    return d


def _folder(root: Path, name: str, payload: bytes) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "model.safetensors").write_bytes(payload)
    (d / "config.json").write_text('{"architectures": ["Synthetic"]}', encoding="utf-8")
    return d


def _committed() -> dict[str, dict[str, Any]]:
    doc = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
    return {b["build_id"]: b for b in doc["builds"]}


# ------------------------------------------------------------------------------------------------ expected weights
def test_every_local_build_names_its_expected_weights_and_they_are_the_measured_release() -> None:
    builds = _committed()
    local = [b for b in builds.values() if b["serving"] == "vllm"]
    assert local and all("expected" in b for b in local)
    measured = json.loads((ROOT / "deploy" / "measured" / "serving_config.rtxpro6000.json").read_text("utf-8"))
    by_repo = {s["model"]: s for s in measured["servers"]}
    checked = 0
    for b in local:
        exp = b["expected"]
        if exp.get("manifest_sha256") is None:
            assert exp.get("revision") is None
            continue
        server = by_repo[b["repository"]]
        assert exp["manifest_sha256"] == pin_model.manifest_sha256_of_files(server["model_files"]), b["build_id"]
        assert exp["revision"] == server["model_dir"].rsplit("/", 1)[1], b["build_id"]
        checked += 1
    # the deployed pair of every profile is measured: judge and verifier
    for pairs in pin_model.PROFILE_PAIRS.values():
        for build, *_ in pairs:
            assert builds[build]["expected"]["manifest_sha256"], build
    assert checked >= 8


def test_the_manifest_of_a_record_file_list_is_the_manifest_of_the_folder(tmp_path: Path) -> None:
    """One hash format: the serving record's file list and pin_model's folder manifest give the same digest."""
    d = _folder(tmp_path, "m", b"weights")
    (d / ".gitattributes").write_text("hidden\n", encoding="utf-8")
    files = [
        {"path": p.relative_to(d).as_posix(), "sha256": pin_model.file_sha256(p), "bytes": p.stat().st_size}
        for p in d.rglob("*")
        if p.is_file()
    ]
    assert pin_model.manifest_sha256_of_files(files) == pin_model.weight_manifest(d).sha256


# ------------------------------------------------------------------------------------------------ no trust on first use
@pytest.mark.req("SEC-64")
def test_the_16_byte_folder_is_refused_by_pin_and_by_install(tmp_path: Path) -> None:
    out = tmp_path / "site" / "registry.site.yaml"
    d = _sixteen_bytes(tmp_path / "models")
    with pytest.raises(pin_model.PinError, match="not the weights of"):
        pin_model.pin(JUDGE, d, served_name=pin_model.JUDGE_SERVED, out=out)
    with pytest.raises(pin_model.PinError, match="not the weights of"):  # no flag lets a wrong folder through
        pin_model.pin(JUDGE, d, served_name=pin_model.JUDGE_SERVED, out=out, trust_first_use=True)
    _folder(tmp_path / "models", "qwen3.5-9b-4bit", b"sixteen-bytes!!!")
    ok, lines = pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {})
    assert not ok and all("not the weights of" in x for x in lines), lines
    assert not out.exists()  # nothing pinned, nothing routes
    assert (
        pin_model.main(["--install", "rtxpro6000", "--models-root", str(tmp_path / "models"), "--out", str(out)]) == 1
    )


@pytest.mark.req("SEC-64")
def test_trust_on_first_use_fails_closed(tmp_path: Path) -> None:
    out = tmp_path / "site" / "registry.site.yaml"
    d = _folder(tmp_path, "m", b"any weights at all")
    with pytest.raises(pin_model.PinError, match="no trust on first use"):
        pin_model.pin(UNEXPECTED, d, served_name="x", out=out)
    assert not out.exists()
    with pytest.raises(pin_model.PinError, match="candidate only"):
        pin_model.pin(UNEXPECTED, d, served_name="x", out=out, trust_first_use=True, status="shadow")
    pin_model.pin(UNEXPECTED, d, served_name="x", out=out, trust_first_use=True)  # an evaluation candidate
    entry = yaml.safe_load(out.read_text(encoding="utf-8"))["builds"][UNEXPECTED]
    assert entry["weights"]["trust"] == "first_use" and "status" not in entry
    rec = _record(tmp_path, {"judge": (UNEXPECTED, entry["sha256"])})
    with pytest.raises(pin_model.PinError, match="trusted on first use cannot be promoted"):
        pin_model.promote(UNEXPECTED, rec, out)
    # and a pin of an expected build that an earlier install trusted on first use is reported, not kept quiet
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    doc["builds"][JUDGE] = {"sha256": "ab" * 32, "served": {"serving": pin_model.JUDGE_SERVED}, "status": "champion"}
    out.write_text(yaml.safe_dump(doc), encoding="utf-8")
    ok, lines = pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {})
    assert not ok and "is not the expected manifest" in lines[0]
    reg = Registry.load(DEFAULT_PATH, out)
    with pytest.raises(RegistryError) as e:  # the hand-pinned champion is refused by name, before its status counts
        reg.resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION)
    assert e.value.reason == "weights_unexpected"


def test_install_pins_the_expected_release_as_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    models = tmp_path / "models"
    folders = {
        JUDGE: _folder(models, "gemma-4-26b-a4b-it-4bit", b"synthetic judge release"),
        VERIFIER: _folder(models, "qwen3.5-9b-4bit", b"synthetic verifier release"),
    }
    release = release_registry(tmp_path, folders, monkeypatch)
    out = tmp_path / "site" / "registry.site.yaml"
    ok, lines = pin_model.install_pins("rtxpro6000", models, out, {})
    assert ok and all("as candidate" in x for x in lines), lines
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))["builds"]
    assert {e["status"] for e in doc.values()} == {"candidate"}
    assert {e["weights"]["trust"] for e in doc.values()} == {"expected"}
    reg = Registry.load(release, out)
    assert reg.resolve("j-workhorse", "serving", role="judge", env=Environment.TEST).build.build_id == JUDGE
    # SAFE-1 A1: the release's candidate pair routes in PRODUCTION, labelled unqualified until a record is promoted
    res = reg.resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION)
    assert res.build.build_id == JUDGE and res.qualification == "unqualified"
    with pytest.raises(pin_model.PinError, match="champion only through qualify"):
        pin_model.pin(JUDGE, folders[JUDGE], served_name="x", out=out, status="champion")
    with pytest.raises(SystemExit):  # the CLI does not offer champion
        pin_model.main(["--build", JUDGE, "--model-dir", str(folders[JUDGE]), "--status", "champion"])


# ------------------------------------------------------------------------------------------------ promotion
def _record(
    tmp_path: Path, builds: dict[str, tuple[str, str]], *, failed: str = "", profile: str = "rtxpro6000"
) -> Path:
    """A qualification record as ``trialbox eval qualify`` writes it (every step, finalized and hashed)."""
    steps = {s: {"status": "passed", "reason": "", "seconds": 0.1, "detail": {}} for s in q.STEPS}
    if failed:
        steps[failed] = {"status": "failed", "reason": "planted", "seconds": 0.1, "detail": {}}
    roles = dict(builds)
    roles.setdefault("verifier", (VERIFIER, "cd" * 32))
    doc: dict[str, Any] = {
        "format": q.RECORD_FORMAT,
        "record_id": f"{profile}-test-{failed or 'ok'}",
        "profile": profile,
        "stub": False,
        "gateway": "live",
        "builds": {
            role: {
                "build_id": b,
                "alias": "j-workhorse" if role == "judge" else "v-verifier",
                "served_name": "s",
                "weights_sha256": sha,
                "revision": None,
                "context_length": 32768,
                "registry_status": "candidate",
            }
            for role, (b, sha) in roles.items()
        },
        "git_head": "0" * 40,
        "driver": "n/a",
        "cuda": "n/a",
        "operator": "test",
        "started": "2026-11-11T00:00:00+00:00",
        "finished": "2026-11-11T01:00:00+00:00",
        "steps": steps,
        "change_protocol": q.change_protocol("MC-1"),
    }
    q.finalize(doc)
    path = tmp_path / "records" / f"{doc['record_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
    return path


def test_promote_needs_a_passing_record_for_exactly_the_pinned_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models = tmp_path / "models"
    d = _folder(models, "gemma-4-26b-a4b-it-4bit", b"synthetic judge release")
    release = release_registry(tmp_path, {JUDGE: d}, monkeypatch)
    out = tmp_path / "site" / "registry.site.yaml"
    m, _ = pin_model.pin(JUDGE, d, served_name=pin_model.JUDGE_SERVED, out=out)

    refused = {
        "failed step": _record(tmp_path, {"judge": (JUDGE, m.sha256)}, failed="planted_defect"),
        "other weights": _record(tmp_path / "o", {"judge": (JUDGE, "ef" * 32)}),
        "other build": _record(tmp_path / "b", {"judge": ("gemma-4-26b-a4b-it-spark", m.sha256)}, profile="gb10"),
        "synthetic": _record(tmp_path / "s", {"judge": (JUDGE, "synthetic")}),
    }
    edited = _record(tmp_path / "e", {"judge": (JUDGE, m.sha256)})
    body = json.loads(edited.read_text(encoding="utf-8"))
    body["steps"]["n12"]["reason"] = "edited after the run"
    edited.write_text(json.dumps(body), encoding="utf-8")
    refused["edited"] = edited
    for why, rec in refused.items():
        with pytest.raises(pin_model.PinError):
            pin_model.promote(JUDGE, rec, out)
        assert pin_model.main(["--promote", JUDGE, "--record", str(rec), "--out", str(out)]) == 1, why
    assert "status" not in yaml.safe_load(out.read_text(encoding="utf-8"))["builds"][JUDGE]

    good = _record(tmp_path / "g", {"judge": (JUDGE, m.sha256)})
    assert pin_model.main(["--promote", JUDGE, "--record", str(good), "--out", str(out)]) == 0
    entry = yaml.safe_load(out.read_text(encoding="utf-8"))["builds"][JUDGE]
    assert entry["status"] == "champion" and entry["qualification"]["record_id"] == "rtxpro6000-test-ok"
    assert entry["qualification"]["weights_sha256"] == m.sha256
    assert entry["qualification"]["sha256"] == json.loads(good.read_text(encoding="utf-8"))["sha256"]
    reg = Registry.load(release, out)
    b = reg.resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION).build
    assert b.build_id == JUDGE and b.qualified_for_production
    assert next(r for r in reg.table() if r["build_id"] == JUDGE)["qualification"]["record_id"] == "rtxpro6000-test-ok"

    pin_model.pin(JUDGE, d, served_name=pin_model.JUDGE_SERVED, out=out)  # a re-pin drops the champion and its record
    entry = yaml.safe_load(out.read_text(encoding="utf-8"))["builds"][JUDGE]
    assert "status" not in entry and "qualification" not in entry


@pytest.mark.parametrize("thinking_mode", [None, "off", "on"])
def test_promote_carries_explicit_thinking_on_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, thinking_mode: str | None
) -> None:
    d = _folder(tmp_path / "models", "gemma-4-26b-a4b-it-4bit", b"synthetic judge release")
    release = release_registry(tmp_path, {JUDGE: d}, monkeypatch)
    doc = yaml.safe_load(release.read_text(encoding="utf-8"))
    next(b for b in doc["builds"] if b["build_id"] == JUDGE)["thinking_control"] = "thinking_only"
    release.write_text(yaml.safe_dump(doc), encoding="utf-8")
    out = tmp_path / "site" / "registry.site.yaml"
    manifest, _ = pin_model.pin(JUDGE, d, served_name=pin_model.JUDGE_SERVED, out=out)
    record = _record(tmp_path, {"judge": (JUDGE, manifest.sha256)})
    if thinking_mode is not None:
        body = json.loads(record.read_text(encoding="utf-8"))
        body["builds"]["judge"]["thinking_mode"] = thinking_mode
        record.write_text(json.dumps(q.finalize(body)), encoding="utf-8")

    pin_model.promote(JUDGE, record, out)
    reg = Registry.load(release, out)
    if thinking_mode == "on":
        assert reg.resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION).build.build_id == JUDGE
    else:  # SAFE-1 A1: the release weights with no thinking-on measurement route labelled, never refused
        res = reg.resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION)
        assert res.build.build_id == JUDGE and res.qualification == "unqualified"


# ------------------------------------------------------------------------------------------------ the gateway rule
def _doc(**judge: Any) -> dict[str, Any]:
    sha = "ab" * 32
    base: dict[str, Any] = {
        "build_id": "j-test-1",
        "alias": "j-workhorse",
        "status": "champion",
        "serving": "vllm",
        "context_length": 32768,  # LLM-007 (D-568): PRODUCTION routes no local build without one
        "served": {"serving": "j-test"},
        "sha256": sha,
        "licence": {"name": "test"},
        "origin": {"developer": "test"},
    }
    base.update(judge)
    return {
        "version": "registry-test",
        "aliases": {a: {"class": "J"} for a in ("trialbox-stub", "j-workhorse", "v-verifier", "x-external")},
        "builds": [base],
    }


@pytest.mark.req("MOD-7", "S1-07")
def test_a_production_gateway_refuses_an_unqualified_champion_by_name(tmp_path: Path) -> None:
    ok = lambda caller, study, step: True  # noqa: E731
    sha = "ab" * 32
    cases = {
        "no record": _doc(),
        "record of other weights": _doc(qualification=qualified("ef" * 32)),
        "record not for PRODUCTION": _doc(qualification={**qualified(sha), "qualifies_production": False}),
    }
    for i, (why, doc) in enumerate(cases.items()):
        reg = Registry(doc)
        gw = _gw(tmp_path / f"p{i}", env=Environment.PRODUCTION, registry=reg, http=_mock("j-test"), confirm=ok)
        r = gw.chat(H(Data_Class="D3", Step="s"), _judge_body())
        assert (r.status, r.body["error"]["code"]) == (403, "champion_unqualified"), (why, r.body)
        assert "trialbox eval qualify" in r.body["error"]["message"]
        # the rule is PRODUCTION's: the same build answers a TEST gateway (synthetic data, a box being set up)
        test = _gw(tmp_path / f"t{i}", env=Environment.TEST, registry=reg, http=_mock("j-test"))
        assert test.chat(H(), {**_judge_body(), "model": "j-workhorse"}).status == 200, why

    reg = Registry(_doc(qualification=qualified(sha)))
    gw = _gw(tmp_path / "q", env=Environment.PRODUCTION, registry=reg, http=_mock("j-test"), confirm=ok)
    r = gw.chat(H(Data_Class="D3", Step="s"), _judge_body())
    assert r.status == 200 and r.body["tb"]["build_id"] == "j-test-1", r.body


def test_a_hand_edited_pin_of_other_weights_is_refused_at_resolution() -> None:
    sha = "ab" * 32
    doc = _doc(expected={"manifest_sha256": "ef" * 32, "revision": "r1"}, qualification=qualified(sha))
    for env in Environment:
        with pytest.raises(RegistryError) as e:
            Registry(doc).resolve("j-workhorse", "serving", role="judge", env=env)
        assert e.value.reason == "weights_unexpected"
    doc = _doc(expected={"manifest_sha256": sha, "revision": "r1"}, revision="r2", qualification=qualified(sha))
    with pytest.raises(RegistryError) as e:
        Registry(doc).resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION)
    assert e.value.reason == "weights_unexpected"
    good = _doc(expected={"manifest_sha256": sha, "revision": "r1"}, revision="r1", qualification=qualified(sha))
    assert Registry(good).resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION).build.pinned


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("expected", {"manifest_sha256": "XYZ"}, "lowercase hex"),
        ("expected", {"sha": "ab" * 32}, "takes only"),
        ("qualification", {**qualified("ab" * 32), "sha256": "nope"}, "lowercase hex"),
        ("qualification", {**qualified("ab" * 32), "record_id": ""}, "record_id"),
        ("qualification", {**qualified("ab" * 32), "signed_by": "x"}, "takes only"),
    ],
)
def test_malformed_expected_or_qualification_fields_are_refused(field: str, value: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Registry(_doc(**{field: value}))


def test_an_override_may_set_the_record_but_never_the_expected_weights() -> None:
    from registry.registry import apply_override

    doc = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="may not set"):
        apply_override(doc, {"kind": "registry-site-override", "builds": {JUDGE: {"expected": {}}}})
    merged = apply_override(
        copy.deepcopy(doc),
        {"kind": "registry-site-override", "builds": {JUDGE: {"qualification": qualified("ab" * 32)}}},
    )
    assert Registry(merged).build(JUDGE).qualification == qualified("ab" * 32)


def test_promote_pins_helper_matches_what_promote_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The test helper (tests/model_pins.py) writes the fields promote writes, so fixtures stay honest."""
    d = _folder(tmp_path / "models", "gemma-4-26b-a4b-it-4bit", b"synthetic judge release")
    release_registry(tmp_path, {JUDGE: d}, monkeypatch)
    out = tmp_path / "site" / "o.yaml"
    m, _ = pin_model.pin(JUDGE, d, served_name="x", out=out)
    a = tmp_path / "site" / "a.yaml"
    a.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
    promote_pins(a)
    pin_model.promote(JUDGE, _record(tmp_path, {"judge": (JUDGE, m.sha256)}), out)
    got = {k: yaml.safe_load(p.read_text(encoding="utf-8"))["builds"][JUDGE] for k, p in (("helper", a), ("real", out))}
    assert set(got["helper"]["qualification"]) == set(got["real"]["qualification"])
    assert got["helper"]["status"] == got["real"]["status"] == "champion"


@pytest.mark.parametrize("record_role", ["verifier", "judge"])
def test_thinking_only_verifier_routes_through_production_judge_role(tmp_path: Path, record_role: str) -> None:
    doc = _doc(
        alias="v-verifier",
        served={"verifier": "v-test"},
        thinking_control="thinking_only",
        qualification={**qualified("ab" * 32), "thinking_on_role": record_role},
    )
    doc["aliases"]["v-verifier"]["class"] = "V"
    gw = _gw(
        tmp_path, env=Environment.PRODUCTION, registry=Registry(doc), http=_mock("v-test"), confirm=lambda *_: True
    )
    reply = gw.chat(H(Data_Class="D3"), {**_judge_body(), "model": "v-verifier"})
    if record_role == "verifier":
        assert reply.status == 200, reply.body
        assert reply.body["tb"]["alias"] == "v-verifier"
    else:
        assert (reply.status, reply.body["error"]["code"]) == (403, "thinking_unmeasured")


@pytest.mark.parametrize("env", [Environment.TEST, Environment.VALIDATION])
def test_thinking_only_build_can_answer_qualification_probe(tmp_path: Path, env: Environment) -> None:
    reg = Registry(_doc(thinking_control="thinking_only", status="candidate"))
    gw = _gw(tmp_path, env=env, registry=reg, http=_mock("j-test"), confirm=lambda *_: True)
    body = {**_judge_body(), "model": "j-workhorse"}
    reply = gw.chat(H(), body)
    assert reply.status == 200, reply.body
    if env == Environment.VALIDATION:
        patient = gw.chat(H(Data_Class="D3"), body)
        assert (patient.status, patient.body["error"]["code"]) == (403, "thinking_unmeasured")
