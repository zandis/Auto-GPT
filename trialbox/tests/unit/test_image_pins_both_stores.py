"""H-149: a digest-pinned image loaded from the signed bundle is proved on either image store of the container engine.

On major version 29 the default image store is the newer image store: a loaded image keeps neither the registry's
digest nor the config digest as its id (``Id`` is the manifest digest), so the pin check of D-176 found every pinned
third-party image missing and the install stopped at "starting the stack". The recorded ``image inspect`` answers of
both stores are in ``tests/fixtures/image_pins`` (synthetic, written from the engine's documented formats).

The invariant (``test_the_loaded_image_is_proved_by_its_layers_and_config_or_refused``): on the newer image store the
compose variable is set to the store's own id only when the image under the bundle's tag has exactly the signed layer
diff ids and config; any other image is refused, and nothing else is ever written (no digest reference, no config
digest the store does not keep).
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import tarfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from tools import image_pins as ip

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "image_pins"
HAPI = "hapiproject/hapi:v8.12.0-2@sha256:0ff86aac4c7bd13a1ee226444a70263bb46ed1c28ef543c30a44f865b80ca04e"
TAG = "hapiproject/hapi:v8.12.0-2"
CONFIG = (FIX / "hapi-config.json").read_bytes()
CONFIG_ID = "sha256:" + hashlib.sha256(CONFIG).hexdigest()
MANIFEST = (FIX / "hapi-manifest.json").read_bytes()
MANIFEST_ID = "sha256:" + hashlib.sha256(MANIFEST).hexdigest()


def _inspect(store: str) -> dict[str, Any]:
    doc = json.loads((FIX / f"inspect-{store}-store.json").read_text(encoding="utf-8"))
    assert isinstance(doc, list) and len(doc) == 1
    return dict(doc[0])


def _archive(tmp_path: Path, config: bytes = CONFIG, name: str = "hapi.tar") -> Path:
    """A ``save`` archive of the fixture image in the OCI layout the engine writes from version 25 on."""
    hexd = hashlib.sha256(config).hexdigest()
    members = {
        "manifest.json": json.dumps([{"Config": f"blobs/sha256/{hexd}", "RepoTags": [TAG], "Layers": []}]).encode(),
        f"blobs/sha256/{hexd}": config,
        f"blobs/sha256/{MANIFEST_ID.split(':')[1]}": MANIFEST,
        "index.json": json.dumps({"schemaVersion": 2, "manifests": [{"digest": MANIFEST_ID}]}).encode(),
    }
    out = tmp_path / name
    with tarfile.open(out, "w") as tf:
        for n, data in members.items():
            ti = tarfile.TarInfo(n)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return out


def _box(tmp_path: Path, pin: dict[str, Any] | None, env: str = "") -> tuple[Path, list[Path]]:
    deploy = tmp_path / "deploy"
    deploy.mkdir(parents=True)
    compose = deploy / "docker-compose.yml"
    compose.write_text(f"services:\n  fhir:\n    image: ${{HAPI_IMAGE:-{HAPI}}}\n", encoding="utf-8")
    (deploy / ".env").write_text(env, encoding="utf-8")
    (deploy / ".env").chmod(0o600)
    if pin is not None:
        (deploy / ip.PINS).write_text(json.dumps({"pins": [pin]}), encoding="utf-8")
    return deploy, [compose]


def _signed_pin(tmp_path: Path) -> dict[str, Any]:
    out = tmp_path / "bundle-image-pins.json"
    assert ip.main(["bundle-pins", str(out), f"{HAPI}={TAG}={_archive(tmp_path)}"]) == 0
    pins = json.loads(out.read_text(encoding="utf-8"))["pins"]
    assert len(pins) == 1
    return dict(pins[0])


def _store(doc: dict[str, Any] | None, keeps: Sequence[str] = ()) -> tuple[Any, Any]:
    """``has`` and ``inspect`` of a box whose store holds ``doc`` under its tags and id, and resolves ``keeps``."""

    def inspect(ref: str) -> dict[str, Any] | None:
        if doc is not None and (ref in (doc.get("RepoTags") or []) or ref == doc.get("Id")):
            return doc
        return None

    return (lambda ref: ref in keeps or (doc is not None and ref == doc.get("Id"))), inspect


# ------------------------------------------------------------------------------------------------ the bundle's side
def test_the_bundle_pin_is_read_out_of_the_saved_archive(tmp_path: Path) -> None:
    pin = _signed_pin(tmp_path)
    cfg = json.loads(CONFIG)
    assert pin["ref"] == HAPI and pin["image"] == CONFIG_ID and pin["tag"] == TAG
    assert pin["layers"] == cfg["rootfs"]["diff_ids"] and len(pin["layers"]) == 3
    assert pin["config"]["Architecture"] == "amd64" and pin["config"]["Os"] == "linux"
    assert pin["config"]["Entrypoint"] == cfg["config"]["Entrypoint"] and pin["config"]["User"] == "65532"


def test_an_archive_whose_config_is_not_its_digest_pins_no_layers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A config that is not the content its name says, or one without layers, gives today's pin (the id only) and
    a warning: such a pin proves nothing on the newer image store, where the box refuses it."""
    bad = _archive(tmp_path, CONFIG, "bad.tar")
    swapped = tmp_path / "swapped.tar"
    with tarfile.open(bad) as src, tarfile.open(swapped, "w") as dst:
        for m in src.getmembers():
            f = src.extractfile(m)
            assert f is not None
            data = f.read()
            if m.name.startswith("blobs/") and data == CONFIG:
                data = data.replace(b'"65532"', b'"0"')
                m.size = len(data)
            dst.addfile(m, io.BytesIO(data))
    out = tmp_path / "out.json"
    assert ip.main(["bundle-pins", str(out), f"{HAPI}={TAG}={swapped}"]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["pins"] == [{"ref": HAPI, "image": CONFIG_ID}]
    assert "is not the content its digest names" in capsys.readouterr().err
    deploy, files = _box(tmp_path / "box", {"ref": HAPI, "image": CONFIG_ID})
    has, inspect = _store(_inspect("newer"))
    assert ip.resolve(deploy, files, has=has, inspect=inspect)[2] == [f"HAPI_IMAGE: {HAPI}"]


def test_make_bundle_writes_the_pins_with_the_pin_tool() -> None:
    text = (ROOT / "tools" / "make_bundle.sh").read_text(encoding="utf-8")
    assert "tools.image_pins bundle-pins" in text
    assert "CONFIG_ID=" not in text  # the config digest alone is no longer the whole pin


# ------------------------------------------------------------------------------------------------ the box's side
def test_both_recorded_stores_agree_on_what_the_image_is_proved_by(tmp_path: Path) -> None:
    pin = ip.read_pin_records(_box(tmp_path, _signed_pin(tmp_path))[0] / ip.PINS)[HAPI]
    classic, newer = _inspect("classic"), _inspect("newer")
    assert classic["Id"] == CONFIG_ID and newer["Id"] == MANIFEST_ID != CONFIG_ID
    assert newer["RepoDigests"] == [f"hapiproject/hapi@{MANIFEST_ID}"] and HAPI.split("@")[1] not in json.dumps(newer)
    assert ip.differs(pin, classic) == "" and ip.differs(pin, newer) == ""


def test_classic_store_points_compose_at_the_config_digest(tmp_path: Path) -> None:
    deploy, files = _box(tmp_path, _signed_pin(tmp_path))
    has, inspect = _store(_inspect("classic"))
    changes, _, missing = ip.resolve(deploy, files, has=has, inspect=inspect)
    assert missing == [] and changes == {"HAPI_IMAGE": CONFIG_ID}


def test_newer_store_was_missing_before_h149(tmp_path: Path) -> None:
    """The bench's failure: neither the digest reference nor the config digest resolves on the newer image store."""
    has, _ = _store(_inspect("newer"))
    assert not has(HAPI) and not has(CONFIG_ID)


def test_the_loaded_image_is_proved_by_its_layers_and_config_or_refused(tmp_path: Path) -> None:
    """The invariant. The newer image store's answer, as recorded: set to the store's own id. Every changed answer:
    refused, nothing set."""
    pin = _signed_pin(tmp_path)
    deploy, files = _box(tmp_path, pin, "A=1\n")
    good = _inspect("newer")
    has, inspect = _store(good)
    changes, notes, missing = ip.resolve(deploy, files, has=has, inspect=inspect)
    assert missing == [] and changes == {"HAPI_IMAGE": MANIFEST_ID}
    assert any("proved by its layers and config" in n for n in notes)
    ip.write_env(deploy / ".env", changes)
    assert (deploy / ".env").read_text(encoding="utf-8").splitlines() == ["A=1", f"HAPI_IMAGE={MANIFEST_ID}"]
    assert ip.resolve(deploy, files, has=has, inspect=inspect)[0] == {}  # again: nothing to change

    layers = list(good["RootFS"]["Layers"])
    other = "sha256:" + "9" * 64
    mutants: dict[str, Any] = {
        "a layer differs": lambda d: d["RootFS"].__setitem__("Layers", [*layers[:2], other]),
        "a layer is missing": lambda d: d["RootFS"].__setitem__("Layers", layers[:2]),
        "a layer more": lambda d: d["RootFS"].__setitem__("Layers", [*layers, other]),
        "the layers reordered": lambda d: d["RootFS"].__setitem__("Layers", layers[::-1]),
        "another entrypoint": lambda d: d["Config"].__setitem__("Entrypoint", ["sh"]),
        "a command added": lambda d: d["Config"].__setitem__("Cmd", ["--debug"]),
        "another environment": lambda d: d["Config"].__setitem__("Env", [*d["Config"]["Env"], "X=1"]),
        "another user": lambda d: d["Config"].__setitem__("User", "0"),
        "another working dir": lambda d: d["Config"].__setitem__("WorkingDir", "/"),
        "another platform": lambda d: d.__setitem__("Architecture", "arm64"),
        "a label added": lambda d: d["Config"].__setitem__("Labels", {"x": "y"}),
        "no root fs": lambda d: d.pop("RootFS"),
        "no id": lambda d: d.pop("Id"),
    }
    for name, change in mutants.items():
        bad = copy.deepcopy(good)
        change(bad)
        has, inspect = _store(bad)
        deploy2, files2 = _box(tmp_path / name.replace(" ", "-"), pin)
        changes, notes, missing = ip.resolve(deploy2, files2, has=has, inspect=inspect)
        assert changes == {} and missing == [f"HAPI_IMAGE: {HAPI}"], name
        assert any("not proved on this box" in n for n in notes), name


def test_a_pin_from_before_h149_is_not_enough_on_the_newer_store(tmp_path: Path) -> None:
    deploy, files = _box(tmp_path, {"ref": HAPI, "image": CONFIG_ID})  # no layers: today's pin
    has, inspect = _store(_inspect("newer"))
    changes, notes, missing = ip.resolve(deploy, files, has=has, inspect=inspect)
    assert changes == {} and missing == [f"HAPI_IMAGE: {HAPI}"] and any("H-149" in n for n in notes)


def test_the_cli_sets_the_store_id_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy, files = _box(tmp_path, _signed_pin(tmp_path))
    has, inspect = _store(_inspect("newer"))
    monkeypatch.setattr(ip, "docker_has", has)
    monkeypatch.setattr(ip, "docker_inspect", inspect)
    assert ip.main(["resolve", "--deploy", str(deploy), "--files", str(files[0])]) == 0
    assert f"HAPI_IMAGE={MANIFEST_ID}" in (deploy / ".env").read_text(encoding="utf-8")
    assert (deploy / ".env").stat().st_mode & 0o777 == 0o600
    assert f"deploy/.env HAPI_IMAGE={MANIFEST_ID}" in capsys.readouterr().out
    bad = _inspect("newer")
    bad["RootFS"]["Layers"] = bad["RootFS"]["Layers"][:1]
    monkeypatch.setattr(ip, "docker_inspect", _store(bad)[1])
    (deploy / ".env").write_text("", encoding="utf-8")
    assert ip.main(["resolve", "--deploy", str(deploy), "--files", str(files[0])]) == 1
    got = capsys.readouterr()
    assert "layers differ" in got.out and f"MISSING HAPI_IMAGE: {HAPI}" in got.err
    assert (deploy / ".env").read_text(encoding="utf-8") == ""


def test_merge_keeps_the_layers_of_the_signed_pin(tmp_path: Path) -> None:
    pin = _signed_pin(tmp_path)
    deploy, _ = _box(tmp_path, {"ref": HAPI, "image": CONFIG_ID})
    src = tmp_path / "new.json"
    src.write_text(json.dumps({"pins": [pin]}), encoding="utf-8")
    assert ip.merge(src, deploy) == 1
    assert ip.read_pin_records(deploy / ip.PINS)[HAPI]["layers"] == pin["layers"]
    assert ip.read_pins(deploy / ip.PINS) == {HAPI: CONFIG_ID}
    assert not list(deploy.glob(".*.tmp"))


def test_an_update_resolves_on_the_newer_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.trialbox import update as up

    pin = _signed_pin(tmp_path)
    deploy, files = _box(tmp_path, None)
    (deploy / ".env").write_text(f"COMPOSE_FILE={files[0]}\n", encoding="utf-8")
    stage = tmp_path / "stage"
    (stage / "other").mkdir(parents=True)
    (stage / "other" / ip.PINS).write_text(json.dumps({"pins": [pin]}), encoding="utf-8")
    calls: list[list[str]] = []

    def run(argv: Sequence[str], **_: Any) -> str:
        calls.append(list(argv))
        return ""

    box = up.ComposeBox(deploy, run=run)
    plan = up.Plan("b1", "", "", [], stage)
    assert "image pins: 1" in box.apply(plan, tmp_path / "rb", up.Point())
    has, inspect = _store(_inspect("newer"))
    monkeypatch.setattr(ip, "docker_has", has)
    monkeypatch.setattr(ip, "docker_inspect", inspect)
    box.restart(plan)
    assert f"HAPI_IMAGE={MANIFEST_ID}" in (deploy / ".env").read_text(encoding="utf-8")
    assert "up" in calls[-1]


def test_the_update_load_check_accepts_the_newer_store_id(tmp_path: Path) -> None:
    """update.py's check after ``load``: the newer image store's ``Id`` is a manifest digest of the archive's
    index.json, which tar_images reads; anything else is refused."""
    from tools.trialbox import update as up

    configs, manifests = up.tar_images(_archive(tmp_path))
    assert configs == {TAG: CONFIG_ID} and manifests == {MANIFEST_ID}
    answers = {"id": str(_inspect("newer")["Id"])}

    def run(argv: Sequence[str], **_: Any) -> str:
        return answers["id"] + "\n"

    box = up.ComposeBox(tmp_path, run=run)
    plan = up.Plan("b1", "", "", [], tmp_path)
    plan.release = {"images": {"hapi": {"image": TAG, "digest": CONFIG_ID}}}
    box.check_loaded(plan, TAG, {configs[TAG], *manifests})
    answers["id"] = "sha256:" + "9" * 64
    with pytest.raises(up.UpdateFailed, match="not the bundle's image"):
        box.check_loaded(plan, TAG, {configs[TAG], *manifests})
