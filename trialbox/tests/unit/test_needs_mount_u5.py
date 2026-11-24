"""U-5 (D-1280, the integrator's go on #639): the console, orchestrator, adapter and mail gateway see the stand-ins
list through a read-only mount of its folder, ``deploy/site/needs`` at ``/run/tb-needs``, in every compose file set
of the tree. Each overlay extends the base file and compose merges a service's volumes by target, so the one line in
the base file reaches every set unless an overlay resets those volumes or mounts something else at the same target.
The tests read each compose file as compose does (its two merge tags kept) and hold every overlay to that.

Written as root, the list is given to the services' uid (10001) at mode 0600, so they can read it and nobody else
can. Synthetic values only."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import pytest
from tb_common import site_needs

from tools.trialbox import db_secrets as ds

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
SERVICES = ("console", "orchestrator", "adapter", "mail-gateway")
LINE = f"./site/needs:{site_needs.MOUNTED}:ro"


def _load(path: Path) -> dict[str, Any]:
    """A compose file as compose reads it: a safe loader that keeps ``!reset`` and ``!override``."""
    loader = ds._Loader(path.read_text(encoding="utf-8"))
    try:
        doc = loader.get_single_data()
    finally:
        loader.dispose()
    return doc if isinstance(doc, dict) else {}


def _volumes(body: Any) -> tuple[bool, list[Any]]:
    """(the service or its volumes start again, the volumes it lists)."""
    again, body = ds._untag(body)
    if not isinstance(body, dict):
        return again, []
    again2, vols = ds._untag(body.get("volumes"))
    return again or again2, list(vols or [])


def test_the_base_file_mounts_the_needs_folder_read_only_once_in_each_of_the_four_services() -> None:
    services = _load(DEPLOY / "docker-compose.yml")["services"]
    for name in SERVICES:
        again, vols = _volumes(services[name])
        assert not again, name
        assert [v for v in vols if isinstance(v, str) and str(site_needs.MOUNTED) in v] == [LINE], name
    others = [n for n, b in services.items() if n not in SERVICES and LINE in _volumes(b)[1]]
    assert others == []


@pytest.mark.parametrize(
    "path",
    sorted(p for p in DEPLOY.rglob("docker-compose*.yml") if p.name != "docker-compose.yml" or p.parent != DEPLOY),
    ids=lambda p: str(p.relative_to(DEPLOY)),
)
def test_no_overlay_drops_or_moves_the_mount(path: Path) -> None:
    services = _load(path).get("services") or {}
    for name in SERVICES:
        if name not in services:
            continue
        again, vols = _volumes(services[name])
        assert not again, f"{path.name} {name}: resets its volumes, which drops the needs mount"
        for v in vols:
            text = v if isinstance(v, str) else str((v or {}).get("target", ""))
            assert str(site_needs.MOUNTED) not in text or text == LINE, f"{path.name} {name}: {v}"


def test_written_as_root_the_list_is_the_services_own_at_0600(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "fchown", lambda fd, uid, gid: calls.append((uid, gid)))
    site_needs.write_stand_ins(tmp_path, ["office_mailbox"])
    assert calls == [(site_needs.SERVICE_UID, site_needs.SERVICE_UID)]
    assert stat.S_IMODE((tmp_path / site_needs.STAND_INS).stat().st_mode) == 0o600


def test_written_by_another_user_the_owner_is_left_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setattr(os, "fchown", lambda fd, uid, gid: calls.append((uid, gid)))
    site_needs.write_stand_ins(tmp_path, [])
    assert calls == []


def test_the_services_uid_is_the_one_the_compose_file_runs_them_as() -> None:
    compose = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    assert f'user: "{site_needs.SERVICE_UID}:{site_needs.SERVICE_UID}"' in compose
