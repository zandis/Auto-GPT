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
    # (pinned in deploy/images.lock), so only HAPI is a third-party pull pinned by digest here
    compose = ROOT / "deploy" / "docker-compose.yml"
    pins = ip.compose_pins([compose])
    assert set(pins) == {"HAPI_IMAGE"}
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
    assert len(calls) == n
