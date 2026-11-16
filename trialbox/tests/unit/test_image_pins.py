"""Digest-pinned images on either Docker image store (D-176, ``tools/image_pins.py``)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from tools import image_pins as ip

ROOT = Path(__file__).resolve().parents[2]
PG = "postgres:16-alpine@sha256:" + "a" * 64
HAPI = "hapiproject/hapi:v8.12.0-2@sha256:" + "b" * 64
PG_ID = "sha256:" + "1" * 64
HAPI_ID = "sha256:" + "2" * 64


def _box(tmp_path: Path, env: str = "", pins: dict[str, str] | None = None) -> tuple[Path, list[Path]]:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    compose = deploy / "docker-compose.yml"
    compose.write_text(
        "services:\n"
        f"  db:\n    image: ${{POSTGRES_IMAGE:-{PG}}}\n"
        f"  fhir:\n    image: ${{HAPI_IMAGE:-{HAPI}}}\n"
        "  app:\n    image: ${TB_IMAGE:-trialbox-py:1.0.0}\n",
        encoding="utf-8",
    )
    (deploy / ".env").write_text(env, encoding="utf-8")
    (deploy / ".env").chmod(0o600)
    if pins is not None:
        (deploy / ip.PINS).write_text(json.dumps({"pins": [{"ref": r, "image": i} for r, i in pins.items()]}))
    return deploy, [compose]


def test_the_shipped_compose_files_pin_the_third_party_images_by_digest() -> None:
    # since D-204 the database is a TrialBox image built from deploy/docker/db.Dockerfile and shipped like trialbox-py
    # (pinned in deploy/images.lock), so HAPI and, since D-348, vLLM are the third-party pulls pinned by digest here
    compose = ROOT / "deploy" / "docker-compose.yml"
    pins = ip.compose_pins([compose])
    assert set(pins) == {"HAPI_IMAGE", "VLLM_IMAGE"}
    assert all("@sha256:" in r for r in pins.values())
    assert "${POSTGRES_IMAGE:-trialbox-postgres:16-1}" in compose.read_text(encoding="utf-8")


def test_containerd_store_keeps_digests_nothing_to_set(tmp_path: Path) -> None:
    deploy, files = _box(tmp_path, f"POSTGRES_IMAGE={PG_ID}\nX=1\n", {PG: PG_ID, HAPI: HAPI_ID})
    changes, _, missing = ip.resolve(deploy, files, has=lambda ref: ref in (PG, HAPI))
    assert missing == [] and changes == {"POSTGRES_IMAGE": None}  # an id set on an older box is cleared
    ip.write_env(deploy / ".env", changes)
    assert (deploy / ".env").read_text() == "X=1\n"
    assert (deploy / ".env").stat().st_mode & 0o777 == 0o600


def test_overlay2_store_points_compose_at_the_bundle_image_id(tmp_path: Path) -> None:
    deploy, files = _box(tmp_path, "A=1\n", {PG: PG_ID, HAPI: HAPI_ID})
    changes, _, missing = ip.resolve(deploy, files, has=lambda ref: ref in (PG_ID, HAPI_ID))
    assert missing == [] and changes == {"POSTGRES_IMAGE": PG_ID, "HAPI_IMAGE": HAPI_ID}
    ip.write_env(deploy / ".env", changes)
    assert (deploy / ".env").read_text().splitlines() == ["A=1", f"HAPI_IMAGE={HAPI_ID}", f"POSTGRES_IMAGE={PG_ID}"]
    # again: nothing changes
    assert ip.resolve(deploy, files, has=lambda ref: ref in (PG_ID, HAPI_ID))[0] == {}


def test_missing_image_or_pin_is_reported(tmp_path: Path) -> None:
    deploy, files = _box(tmp_path, "", {PG: PG_ID})
    _, _, missing = ip.resolve(deploy, files, has=lambda ref: False)
    assert len(missing) == 2 and any("no pin" in m for m in missing)
    assert ip.main(["resolve", "--deploy", str(deploy), "--files", str(files[0])]) == 1


def test_a_site_mirror_is_left_alone(tmp_path: Path) -> None:
    deploy, files = _box(tmp_path, "POSTGRES_IMAGE=registry.hospa.test/postgres:16\n", {PG: PG_ID, HAPI: HAPI_ID})
    changes, notes, missing = ip.resolve(deploy, files, has=lambda ref: ref == HAPI)
    assert changes == {} and missing == [] and any("site's own" in n for n in notes)


def test_merge_keeps_older_pins_and_drops_malformed(tmp_path: Path) -> None:
    deploy, _ = _box(tmp_path, "", {PG: PG_ID})
    new = tmp_path / "bundle-pins.json"
    new.write_text(json.dumps({"pins": [{"ref": HAPI, "image": HAPI_ID}, {"ref": "x:1", "image": "sha256:zz"}]}))
    assert ip.merge(new, deploy) == 1
    assert ip.read_pins(deploy / ip.PINS) == {PG: PG_ID, HAPI: HAPI_ID}


def test_an_update_keeps_the_bundle_pins_and_resolves_them_before_the_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.trialbox import update as up

    deploy, files = _box(tmp_path, "")
    (deploy / ".env").write_text(f"COMPOSE_FILE={files[0]}\n")
    stage = tmp_path / "stage"
    (stage / "other").mkdir(parents=True)
    (stage / "other" / ip.PINS).write_text(
        json.dumps({"pins": [{"ref": PG, "image": PG_ID}, {"ref": HAPI, "image": HAPI_ID}]})
    )
    calls: list[list[str]] = []

    def run(argv: Sequence[str], **_: Any) -> str:
        calls.append(list(argv))
        return ""

    box = up.ComposeBox(deploy, run=run)
    plan = up.Plan("b1", "", "", [], stage)
    assert "image pins: 2" in box.apply(plan, tmp_path / "rb", up.Point())
    assert ip.read_pins(deploy / ip.PINS) == {PG: PG_ID, HAPI: HAPI_ID}
    monkeypatch.setattr(ip, "docker_has", lambda ref: ref in (PG_ID, HAPI_ID))  # a store without digests
    box.restart(plan)
    assert f"POSTGRES_IMAGE={PG_ID}" in (deploy / ".env").read_text()
    assert "up" in calls[-1]
    monkeypatch.setattr(ip, "docker_has", lambda ref: False)  # neither: the update stops before the restart
    n = len(calls)
    with pytest.raises(up.UpdateFailed, match="pinned images"):
        box.restart(plan)
    # D-834: the one compose call before the stop is the read-only `config --images` (the images the stack runs)
    assert [c[-2:] for c in calls[n:]] == [["config", "--images"]]


# ------------------------------------------------------------------------------------------------ OPS-004b (D-574)
def test_an_image_no_service_of_this_box_runs_is_not_asked_for(tmp_path: Path) -> None:
    """The box rehearsal's stand-ins replace the model servers through the compose override; the installer still
    wanted the model server image on the box by its variable. What the rendered stack does not run is not needed;
    what it runs is still required."""
    deploy, files = _box(tmp_path, "", {PG: PG_ID})
    used = {PG}  # the rendered stack: the database, and the FHIR store replaced by an override's image
    _changes, notes, missing = ip.resolve(deploy, files, has=lambda ref: False, used=used)
    assert missing == [f"POSTGRES_IMAGE: {PG}"]  # what the stack runs is still required
    assert any(n.startswith("HAPI_IMAGE:") and "no service of this box's stack runs it" in n for n in notes)
    # nothing given: every pinned variable is asked for, as before
    _, _, all_missing = ip.resolve(deploy, files, has=lambda ref: False)
    assert len(all_missing) == 2


def test_an_image_already_set_to_the_bundles_id_still_counts_as_run(tmp_path: Path) -> None:
    """On the classic image store deploy/.env holds the bundle's image id for the variable, and the rendered stack
    names that id, not the digest reference."""
    deploy, files = _box(tmp_path, f"HAPI_IMAGE={HAPI_ID}\n", {HAPI: HAPI_ID, PG: PG_ID})
    _, notes, missing = ip.resolve(deploy, files, has=lambda ref: ref in (HAPI_ID, PG_ID), used={HAPI_ID, PG})
    assert missing == [] and not any("no service" in n for n in notes)


def test_the_installer_gives_the_rendered_stack_to_the_pin_check() -> None:
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    call = text[text.index("python3 -m tools.image_pins resolve") :].split("\n", 1)[0]
    assert '--used "$USED_IMAGES"' in call
    before = text[: text.index("python3 -m tools.image_pins resolve")]
    assert 'USED_IMAGES="$("${COMPOSE[@]}" config --images' in before[-600:]
    assert ip.main(["resolve", "--deploy", "x", "--files", "y", "--used", ""]) in (
        0,
        1,
    )  # an empty list is "none given"
