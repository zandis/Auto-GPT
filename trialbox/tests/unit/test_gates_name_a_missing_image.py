"""I-7 (D-886; F3a of the installer first contact): `make release-gates` names every local image it lacks and the
target that builds it (the demo image comes from `make demo-bundle`, not `make images`) before it scans anything."""

from __future__ import annotations

from typing import Any

import pytest

from tools.supply_chain import __main__ as cli
from tools.supply_chain import release, vulns

pytestmark = pytest.mark.nodb


def _inspect(have: set[str]) -> Any:
    def inspect(ref: str) -> dict[str, Any]:
        if ref not in have:
            raise vulns.ReportError(f"{ref}: not a local image")
        return {"image_id": "sha256:" + "a" * 64, "repo_digests": [], "platform": "linux/amd64"}

    return inspect


def test_each_missing_local_image_is_named_with_its_build_target() -> None:
    targets = [release.parse_target(t) for t in ("trialbox-py:1.0.0", "trialbox-demo:step5", "trialbox-jvm:1.0.0",
                                                 "registry:caddy:2=linux/amd64")]  # fmt: skip
    got = release.missing_local(targets, inspect=_inspect({"trialbox-py:1.0.0"}))
    assert got == [
        "trialbox-demo:step5 is not a local image: build it with `make demo-bundle` (or leave it out: SC_OWN_IMAGES)",
        "trialbox-jvm:1.0.0 is not a local image: build it with `make images` (or leave it out: SC_OWN_IMAGES)",
    ]


def test_registry_images_are_not_looked_for_locally() -> None:
    assert release.missing_local([release.parse_target("registry:caddy:2=linux/amd64")], inspect=_inspect(set())) == []


def test_release_gates_stop_before_any_scan(monkeypatch: pytest.MonkeyPatch, capsys: Any, tmp_path: Any) -> None:
    monkeypatch.setattr(release, "inspect_local", _inspect(set()))
    monkeypatch.setattr(release, "run_gates", lambda *a, **k: pytest.fail("scanned with an image missing"))
    rc = cli.main(["release-gates", "--image", "trialbox-demo:step5", "--cache-dir", str(tmp_path)])
    assert rc == 1 and "make demo-bundle" in capsys.readouterr().err
