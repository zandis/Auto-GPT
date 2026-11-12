"""Model provenance, the judge's pinned chat template and the bake-off builds (T-674, D-392; deep review DEP-007,
DEP-008, DEP-009, PLAN-036 / RSK-60).

* No deployed build (a GPU profile's pair, and the front desk on the judge's server) has a ``null`` revision: the
  release revision, its source and the manifest sha256 are recorded, and the verifier's licence file and recipe are
  the files of the measured release.
* Every profile's compose file starts the judge with ``--chat-template`` at the file the registry names; ``pin_model``
  records the template's sha256 in the pin and refuses a missing or different file; the serving record names the
  template's sha256.
* The judge challenger is in the registry with its bake-off run queued in the GPU ledger, and the second verifier
  candidate is recorded unmeasured.

Every file here is synthetic; nothing is downloaded and no GPU is used.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from registry.registry import DEFAULT_PATH, Registry, RegistryError
from tb_common.policy.classes import Environment

from tests.model_pins import release_registry
from tools import pin_model
from tools import serving_config as sc

ROOT = Path(__file__).resolve().parents[2]
MEASURED = ROOT / "deploy" / "measured" / "serving_config.rtxpro6000.json"
COMPOSE = {g: ROOT / "deploy" / f"docker-compose.{g}.yml" for g in ("rtxpro6000", "gb10", "rtx5090", "shared-quota")}
JUDGE = "gemma-4-26b-a4b-it-rtxpro6000"
VERIFIER = "qwen3.5-9b-rtxpro6000"
CHALLENGER = "gemma-4-31b-it-qat-challenger"
SECOND_VERIFIER = "ministral-3-14b-verifier-candidate"
_REV = re.compile(r"^[0-9a-f]{40}$")


def _doc() -> dict[str, Any]:
    return yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _builds(doc: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    return {b["build_id"]: b for b in (doc or _doc())["builds"]}


def deployed(doc: dict[str, Any]) -> list[str]:
    """The builds a site profile deploys: every profile pair, and every local build served on the judge's server
    from the judge's release (the front desk)."""
    builds = _builds(doc)
    pairs = {b for rows in pin_model.PROFILE_PAIRS.values() for b, *_ in rows}
    judge_repos = {builds[b]["repository"] for b in pairs if builds[b]["alias"] == "j-workhorse"}
    front = {k for k, b in builds.items() if b["alias"] == "f-frontdesk" and b.get("repository") in judge_repos}
    return sorted(pairs | front)


def provenance_problems(doc: dict[str, Any]) -> list[str]:
    """Why a deployed build's provenance is incomplete; empty when every deployed build is recorded."""
    builds = _builds(doc)
    bad: list[str] = []
    for bid in deployed(doc):
        b = builds[bid]
        exp, prov = b.get("expected") or {}, b.get("provenance") or {}
        if not (isinstance(exp.get("revision"), str) and _REV.match(exp["revision"])):
            bad.append(f"{bid}: expected.revision is {exp.get('revision')!r}")
        if not exp.get("manifest_sha256"):
            bad.append(f"{bid}: expected.manifest_sha256 is null")
        if prov.get("revision") is None or prov.get("revision") != exp.get("revision"):
            bad.append(f"{bid}: provenance.revision {prov.get('revision')!r} is not the expected revision")
        if not prov.get("source") or prov.get("source") != b.get("repository"):
            bad.append(f"{bid}: provenance.source is not the repository")
        if prov.get("copy") not in ("publisher-quantisation", "own-copy", "own-quantisation"):
            bad.append(f"{bid}: provenance.copy {prov.get('copy')!r}")
        if "licence_file" not in prov:
            bad.append(f"{bid}: no licence_file")
        if b["alias"] in ("j-workhorse", "f-frontdesk"):
            tpl = b.get("chat_template") or {}
            for key in ("source", "revision", "file"):
                if not tpl.get(key):
                    bad.append(f"{bid}: chat_template.{key} is null")
            # HW-005 (D-567): named in full, so the pin trusts no file at first use
            if not re.fullmatch(r"[0-9a-f]{40}", str(tpl.get("revision"))):
                bad.append(f"{bid}: chat_template.revision is not a full revision")
            if not re.fullmatch(r"[0-9a-f]{64}", str(tpl.get("sha256"))):
                bad.append(f"{bid}: chat_template.sha256 is not a sha256")
    return bad


# ------------------------------------------------------------------------------------------------ provenance
def test_no_deployed_build_has_a_null_revision() -> None:
    doc = _doc()
    assert len(deployed(doc)) == 11 and JUDGE in deployed(doc) and VERIFIER in deployed(doc)
    assert provenance_problems(doc) == []


@pytest.mark.parametrize("field", ["expected", "provenance", "chat_template"])
def test_a_null_revision_in_a_deployed_build_fails(field: str) -> None:
    doc = copy.deepcopy(_doc())
    b = _builds(doc)[JUDGE]
    b[field]["revision"] = None
    assert any("revision" in x and JUDGE in x for x in provenance_problems(doc))


def test_the_verifier_is_an_own_copy_with_its_licence_file_kept() -> None:
    """D-392 default (the owner's question is open): own copy of the publisher's quantisation; the licence file and
    the recipe are files of the measured release, so they are in its weight manifest."""
    measured = json.loads(MEASURED.read_text(encoding="utf-8"))
    files = {f["path"]: f["sha256"] for s in measured["servers"] if s["role"] == "verifier" for f in s["model_files"]}
    for bid in ("qwen3.5-9b-rtxpro6000", "qwen3.5-9b-spark", "qwen3.5-9b-rtx5090"):
        prov = _builds()[bid]["provenance"]
        assert (prov["copy"], prov["default"]) == ("own-copy", True), bid
        assert prov["base"]["repository"] == "Qwen/Qwen3.5-9B" and prov["base"]["revision"]
        assert files[prov["licence_file"]["path"]] == prov["licence_file"]["sha256"]
        assert files[prov["recipe"]["path"]] == prov["recipe"]["sha256"]
    register = (ROOT / "docs" / "licences" / "register.csv").read_text(encoding="utf-8")
    assert _builds()[VERIFIER]["provenance"]["licence_file"]["sha256"] in register


def test_the_judge_template_is_the_developers_not_the_quantisers() -> None:
    for bid in deployed(_doc()):
        b = _builds()[bid]
        if b["alias"] == "v-verifier":
            assert "chat_template" not in b, bid  # the verifier keeps its folder's template (thinking off by kwargs)
            continue
        tpl = b["chat_template"]
        assert tpl["source"] == "google/gemma-4-26B-A4B-it" and tpl["source"] != b["repository"]
        assert tpl["file"] == "chat-templates/gemma-4-26b-a4b-it/chat_template.jinja"
        assert tpl["sha256"] is None or re.match(r"^[0-9a-f]{64}$", tpl["sha256"])  # never guessed


# ------------------------------------------------------------------------------------------------ compose
class _ComposeLoader(yaml.SafeLoader):
    """Compose's merge tags (``!override``, ``!reset``) read as plain values."""


def _tagged(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)  # type: ignore[arg-type]


_ComposeLoader.add_multi_constructor("!", _tagged)


def _command(path: Path, service: str) -> list[str]:
    doc = yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader)  # a SafeLoader subclass
    return [str(c) for c in doc["services"][service]["command"]]


@pytest.mark.parametrize("gpu", sorted(COMPOSE))
def test_every_profile_starts_the_judge_with_the_pinned_template(gpu: str) -> None:
    judge, verifier = _command(COMPOSE[gpu], "llm-service"), _command(COMPOSE[gpu], "llm-verifier")
    flags = [f for f in judge if f.startswith("--chat-template=")]
    assert len(flags) == 1, gpu
    m = re.fullmatch(r"--chat-template=/models/\$\{" + pin_model.TEMPLATE_VAR + r":-([^}]+)\}", flags[0])
    assert m and m.group(1) == _builds()[JUDGE]["chat_template"]["file"], flags[0]
    assert not any(f.startswith("--chat-template=") for f in verifier)
    resolved = [re.sub(r"\$\{[A-Z_]+:\?[^}]*\}", "1", re.sub(r"\$\{[A-Z_]+:-([^}]+)\}", r"\1", f)) for f in judge]
    parsed = sc.parse_args(resolved)
    assert parsed["chat_template"] == "/models/" + m.group(1) and "--chat-template" not in parsed["extra_args"]


# ------------------------------------------------------------------------------------------------ pin_model
def _folder(root: Path, name: str, payload: bytes) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "model.safetensors").write_bytes(payload)
    return d


def _release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Path]]:
    models = tmp_path / "models"
    folders = {
        JUDGE: _folder(models, "gemma-4-26b-a4b-it-4bit", b"synthetic judge"),
        VERIFIER: _folder(models, "qwen3.5-9b-4bit", b"synthetic verifier"),
    }
    return release_registry(tmp_path, folders, monkeypatch), folders


def test_install_pins_the_template_with_the_weights(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release, folders = _release(tmp_path, monkeypatch)
    out = tmp_path / "site" / "registry.site.yaml"
    ok, lines = pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {})
    assert ok and "chat template google/gemma-4-26B-A4B-it" in lines[0] and "chat template" not in lines[1], lines
    pins = yaml.safe_load(out.read_text(encoding="utf-8"))["builds"]
    tpl = pins[JUDGE]["weights"]["chat_template"]
    want = _builds(yaml.safe_load(release.read_text(encoding="utf-8")))[JUDGE]["chat_template"]
    assert (tpl["sha256"], tpl["trust"], tpl["revision"]) == (want["sha256"], "expected", want["revision"])
    assert "chat_template" not in pins[VERIFIER]["weights"]
    line = (out.parent / "manifests" / f"{JUDGE}.template.sha256").read_text(encoding="utf-8")
    assert line == f"{tpl['sha256']}  chat_template.jinja\n"
    assert pin_model.verify_all(tmp_path / "models", out)[0]
    # the template is changed after the pin: verify-all (install's next step) refuses the box
    (tmp_path / "models" / want["file"]).write_text("{{ messages }}", encoding="utf-8")
    ok, lines = pin_model.verify_all(tmp_path / "models", out)
    assert not ok and any("chat template changed since the pin" in x for x in lines), lines
    assert folders  # weights unchanged: only the template is refused


def test_install_refuses_a_judge_without_its_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release, _ = _release(tmp_path, monkeypatch)
    (tmp_path / "models" / _builds()[JUDGE]["chat_template"]["file"]).unlink()
    out = tmp_path / "site" / "registry.site.yaml"
    ok, lines = pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {})
    assert not ok and "no chat template at" in lines[0] and "as candidate" in lines[1], lines
    assert JUDGE not in yaml.safe_load(out.read_text(encoding="utf-8"))["builds"]
    reg = Registry.load(release, out)
    with pytest.raises(RegistryError):  # nothing pinned for the judge: it routes nothing
        reg.resolve("j-workhorse", "serving", role="judge", env=Environment.TEST)


def test_a_template_other_than_the_registrys_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, folders = _release(tmp_path, monkeypatch)
    other = tmp_path / "other.jinja"
    other.write_text("{{ messages[-1].content }}", encoding="utf-8")
    out = tmp_path / "site" / "registry.site.yaml"
    with pytest.raises(pin_model.PinError, match="is not the expected"):
        pin_model.pin(JUDGE, folders[JUDGE], served_name=pin_model.JUDGE_SERVED, out=out, chat_template=other)
    with pytest.raises(pin_model.PinError, match="names no chat_template"):
        pin_model.pin(VERIFIER, folders[VERIFIER], served_name="v", endpoint="verifier", out=out, chat_template=other)
    assert not out.exists()


def test_a_template_not_yet_fetched_is_recorded_on_first_use(tmp_path: Path) -> None:
    """A row with no template sha256 (one being prepared; no deployed row since HW-005): the site's file is
    recorded, marked. The committed row names its hash, so the same file is refused for it."""
    committed = _builds()[JUDGE]
    row = {**committed, "chat_template": {**committed["chat_template"], "sha256": None}}
    f = tmp_path / "chat_template.jinja"
    f.write_text("synthetic", encoding="utf-8")
    got = pin_model.pin_template(JUDGE, row, f)
    assert got["trust"] == "first_use" and got["sha256"] == pin_model.file_sha256(f)
    with pytest.raises(pin_model.PinError, match="is not the expected ae53464bf3be"):
        pin_model.pin_template(JUDGE, committed, f)


TEMPLATE_REVISION = "4d7ae4984b7db7de8f8457170b3f1a419ee76d52"
TEMPLATE_SHA256 = "ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4"


def test_hw005_every_judge_and_front_desk_row_names_the_template_by_its_hash() -> None:
    """D-567: read from the developer's repository at this revision on 2026-11-12; one file for the seven rows."""
    rows = [b for b in _builds().values() if b.get("chat_template")]
    assert len(rows) == 7
    for b in rows:
        tpl = b["chat_template"]
        assert (tpl["source"], tpl["revision"], tpl["sha256"]) == (
            "google/gemma-4-26B-A4B-it", TEMPLATE_REVISION, TEMPLATE_SHA256,
        ), b["build_id"]  # fmt: skip
        assert b["provenance"]["base"] == {"repository": "google/gemma-4-26B-A4B-it", "revision": TEMPLATE_REVISION}
    text = (ROOT / "models" / "registry.yaml").read_text(encoding="utf-8")
    assert "pin_model records the site's file" not in text  # the old note of a hash still to come


def test_hw005_a_deployed_row_without_the_template_hash_is_a_provenance_problem() -> None:
    doc = copy.deepcopy(_doc())
    b = next(x for x in doc["builds"] if x["build_id"] == JUDGE)
    b["chat_template"]["sha256"] = None
    b["chat_template"]["revision"] = "4d7ae4984b7d"
    assert provenance_problems(doc) == [
        f"{JUDGE}: chat_template.revision is not a full revision",
        f"{JUDGE}: chat_template.sha256 is not a sha256",
    ]


def test_hw005_the_flag_stays_while_the_weight_folders_template_is_another_file() -> None:
    """The measured record lists the weight folder's own chat_template.jinja. It is not the developer's file, so
    compose keeps --chat-template; when the two hashes are equal the flag can go (D-567). The folder's hash is
    written here from that record: a retaken record with another folder template changes this line, on purpose."""
    record = json.loads((ROOT / "deploy" / "measured" / "serving_config.rtxpro6000.json").read_text(encoding="utf-8"))
    found: list[str] = []

    def walk(v: object) -> None:
        if isinstance(v, dict):
            if v.get("path") == "chat_template.jinja" and v.get("sha256"):
                found.append(str(v["sha256"]))
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(record)
    assert found and found[0].startswith("94899c0f") and TEMPLATE_SHA256 not in found
    for name in ("rtxpro6000", "gb10", "rtx5090", "shared-quota"):
        compose = (ROOT / "deploy" / f"docker-compose.{name}.yml").read_text(encoding="utf-8")
        assert "--chat-template=/models/${JUDGE_CHAT_TEMPLATE:-chat-templates/gemma-4-26b-a4b-it/" in compose, name


def test_a_box_pinned_before_the_template_gets_it_added(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _release(tmp_path, monkeypatch)
    out = tmp_path / "site" / "registry.site.yaml"
    assert pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {})[0]
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    del doc["builds"][JUDGE]["weights"]["chat_template"]  # as an install before T-674 wrote it
    out.write_text(yaml.safe_dump(doc), encoding="utf-8")
    ok, lines = pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {})
    assert ok and lines == [f"{JUDGE}: already pinned; chat template chat_template.jinja added to the pin",
                            f"{VERIFIER}: already pinned"], lines  # fmt: skip
    assert yaml.safe_load(out.read_text(encoding="utf-8"))["builds"][JUDGE]["weights"]["chat_template"]["sha256"]


# ------------------------------------------------------------------------------------------------ serving record
def _record(server: dict[str, Any]) -> dict[str, Any]:
    base = {
        "role": "judge", "container": "judge", "vllm_version": "0.32.0", "model": "/models/m", "max_model_len": 32768,
        "max_num_seqs": 16, "enforce_eager": True, "gpu_memory_utilization": 0.4,
        "model_files": [{"path": "model.safetensors", "bytes": 1, "sha256": "ab" * 32}],
        "model_files_sha256": "cd" * 32,
    }  # fmt: skip
    return {
        "schema": sc.SCHEMA,
        "card": {"name": "NVIDIA RTX PRO 6000", "memory_total_mib": 97887, "driver": "580"},
        "servers": [{**base, **server}],
    }


def test_the_serving_record_names_the_template_sha(tmp_path: Path) -> None:
    models = tmp_path / "models"
    path = models / "chat-templates" / "t" / "chat_template.jinja"
    path.parent.mkdir(parents=True)
    path.write_text("synthetic template", encoding="utf-8")
    sha = pin_model.file_sha256(path)
    container = "/models/chat-templates/t/chat_template.jinja"
    assert sc.template_sha256(models, container) == sha  # what capture writes for the server
    assert sc.template_sha256(models, "/models/missing.jinja") is None
    good = _record({"chat_template": container, "chat_template_sha256": sha})
    assert sc.validate(good) == [] and sc.chat_template_of(good) == (container, sha)
    assert sc.template_problems(good, sha) == []
    assert sc.template_problems(good, "ef" * 32) and "is not the pinned" in sc.template_problems(good, "ef" * 32)[0]
    unnamed = _record({"chat_template": container, "chat_template_sha256": None})
    assert sc.validate(unnamed) == ["judge.chat_template_sha256"]
    old = json.loads(MEASURED.read_text(encoding="utf-8"))  # measured 2026-11-08, before the flag: re-measure (D-392)
    assert sc.validate(old) == [] and "without --chat-template" in sc.template_problems(old, None)[0]


# ------------------------------------------------------------------------------------------------ bake-off builds
def test_the_challenger_is_in_the_registry_and_its_run_is_queued_not_run() -> None:
    b = _builds()[CHALLENGER]
    assert (b["alias"], b["status"], b["serving"]) == ("j-workhorse", "candidate", "vllm")
    assert b["repository"].startswith("google/") and b["origin"]["non_prc"] is True
    assert b["expected"] == {"manifest_sha256": None, "revision": None}  # nothing measured, nothing guessed
    assert b["bakeoff"]["ledger"] == "S4" and b["bakeoff"]["state"] == "queued"
    ledger = (ROOT / "docs" / "plan" / "gpu-ledger.md").read_text(encoding="utf-8")
    row = next(r for r in ledger.splitlines() if r.startswith("| S4 |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[3] == "T-674" and cells[-1].startswith("queued") and cells[6:10] == ["", "", "", ""]  # not run
    reg = Registry.load()
    assert not reg.build(CHALLENGER).pinned
    with pytest.raises(RegistryError) as e:  # unpinned: routes nothing until the S4 run pins it
        reg.resolve("j-workhorse", "serving", role="bakeoff", env=Environment.TEST)
    assert f"{CHALLENGER}: sha256 not pinned" in str(e.value)


def test_a_second_verifier_candidate_is_recorded_unmeasured() -> None:
    b = _builds()[SECOND_VERIFIER]
    assert (b["alias"], b["status"]) == ("v-verifier", "candidate")
    assert b["origin"]["non_prc"] is True and b["origin"]["country"] != "CN"  # RSK-60: a non-PRC verifier
    assert b["bakeoff"]["state"] == "unmeasured" and b["bakeoff"]["risk"] == "RSK-60"
    assert b["expected"] == {"manifest_sha256": None, "revision": None}
    assert b["licence"]["verified"] is False  # stays candidate until its licence row is checked


def test_cards_show_the_provenance() -> None:
    from registry.cards import stale

    assert stale(Registry.load()) == []
    card = (ROOT / "models" / "cards" / f"{VERIFIER}.md").read_text(encoding="utf-8")
    assert "own-copy, the default until the owner answers" in card and "| Licence file | `LICENSE` sha256" in card
    assert "| Chat template | `google/gemma-4-26B-A4B-it`" in (ROOT / "models" / "cards" / f"{JUDGE}.md").read_text(
        encoding="utf-8"
    )
    assert "queued (GPU ledger row S4)" in (ROOT / "models" / "cards" / f"{CHALLENGER}.md").read_text("utf-8")


# ------------------------------------------------------------------------- HW-005: the review of PR #358
def _old_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    """A box installed before the registry named the template's hash: its own file was recorded on first use.
    Returns (the template's path, the site override, the release registry that now names the hash)."""
    from registry import registry as reg_mod

    release, _ = _release(tmp_path, monkeypatch)
    doc = yaml.safe_load(release.read_text(encoding="utf-8"))
    before = copy.deepcopy(doc)
    for b in before["builds"]:
        if b.get("chat_template"):
            b["chat_template"]["sha256"] = None
    old = tmp_path / "registry.before.yaml"
    old.write_text(yaml.safe_dump(before, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(reg_mod, "DEFAULT_PATH", old)
    template = tmp_path / "models" / _builds(doc)[JUDGE]["chat_template"]["file"]
    template.write_text("{{ another template }}", encoding="utf-8")
    out = tmp_path / "site" / "registry.site.yaml"
    ok, lines = pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {})
    assert ok, lines
    pin = yaml.safe_load(out.read_text(encoding="utf-8"))["builds"][JUDGE]["weights"]["chat_template"]
    assert pin["trust"] == "first_use"
    monkeypatch.setattr(reg_mod, "DEFAULT_PATH", release)  # the update: the registry now names the hash
    return template, out, release


def test_hw005_review_a_box_pinned_on_first_use_is_refused_until_the_named_file_is_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HIGH-1: after an update the install said "already pinned" and verify-all compared the file with the pin's
    own hash only: the box went on serving a file nobody checked."""
    from tests.model_pins import TEMPLATE_TEXT

    template, out, _ = _old_box(tmp_path, monkeypatch)
    ok, lines = pin_model.verify_all(tmp_path / "models", out)
    assert not ok and any("is not the registry's" in x and "re-pin" in x for x in lines), lines
    ok, lines = pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {})
    assert not ok and "is not the expected" in lines[0], lines  # the wrong file is still there: said, not kept
    template.write_text(TEMPLATE_TEXT, encoding="utf-8")  # the registry's file is put in place
    ok, lines = pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {})
    assert ok and "chat template" in lines[0] and "replaced by the registry's" in lines[0], lines
    pin = yaml.safe_load(out.read_text(encoding="utf-8"))["builds"][JUDGE]["weights"]["chat_template"]
    assert pin["trust"] == "expected" and pin["sha256"] == pin_model.file_sha256(template)
    assert pin_model.verify_all(tmp_path / "models", out)[0]


def test_hw005_review_a_template_trusted_on_first_use_is_never_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MED-2: promote looked at the weights' trust only."""
    _template, out, _ = _old_box(tmp_path, monkeypatch)
    with pytest.raises(pin_model.PinError, match="chat template .* trusted on first use"):
        pin_model.promote(JUDGE, tmp_path / "no-record-is-read-before-this.json", out)
