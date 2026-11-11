"""Site pins for tests on synthetic weight folders (T-012b).

Since T-012b a pin is checked against the build's expected weights in ``models/registry.yaml`` and a PRODUCTION
gateway routes a ``champion`` only with a qualification record for its pinned weights. Tests that need a box with a
routable pair on a few synthetic bytes use these helpers:

* :func:`release_registry` writes a copy of the committed registry whose ``expected`` weights are the synthetic
  folders' manifests (and whose judge chat template is a synthetic file beside them, T-674) and points ``registry.registry.DEFAULT_PATH`` and ``TB_REGISTRY_PATH`` at it (so
  ``tools/pin_model.py`` and the gateway check the synthetic release, not the real one);
* :func:`qualified` is the qualification reference ``pin_model --promote`` writes, for exactly the given weights;
* :func:`promote_pins` marks pinned builds of a site override champion with such a reference, as a promotion from
  a passing record would (the real promotion, with a record, is tested in ``tests/unit/test_champion_qualify.py``).

No real model, no download: every folder is a few bytes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

RECORD_SHA = "5a" * 32


def qualified(weights_sha256: str, record_id: str = "test-qualification-record") -> dict[str, Any]:
    return {
        "record_id": record_id,
        "record": f"{record_id}.json",
        "sha256": RECORD_SHA,
        "profile": "rtxpro6000",
        "weights_sha256": weights_sha256,
        "qualifies_production": True,
        "promoted_at": "2026-11-11T00:00:00Z",
    }


TEMPLATE_TEXT = "{% for m in messages %}<turn>{{ m.role }}\n{{ m.content }}</turn>\n{% endfor %}<turn>model\n"


def synthetic_template(models_root: Path, row: dict[str, Any]) -> str:
    """Write a synthetic chat template where the build's ``chat_template.file`` puts it under ``models_root``
    (T-674); returns its sha256, the value a release registry then expects."""
    import hashlib

    path = models_root / str(row["file"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE_TEXT, encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def release_registry(tmp_path: Path, folders: dict[str, Path], monkeypatch: pytest.MonkeyPatch | None = None) -> Path:
    """A registry copy whose builds in ``folders`` expect those folders' manifests; patched in when ``monkeypatch``
    is given. Returns the copy's path."""
    from registry import registry as reg_mod

    from tools.pin_model import weight_manifest

    doc = yaml.safe_load(reg_mod.DEFAULT_PATH.read_text(encoding="utf-8"))
    for b in doc["builds"]:
        if b["build_id"] in folders:
            b["expected"] = {"manifest_sha256": weight_manifest(folders[b["build_id"]]).sha256, "revision": None}
            if (b.get("chat_template") or {}).get("file"):  # T-674: the judge's template, beside the weights
                b["chat_template"]["sha256"] = synthetic_template(folders[b["build_id"]].parent, b["chat_template"])
    path = tmp_path / "registry.release.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    if monkeypatch is not None:
        monkeypatch.setattr(reg_mod, "DEFAULT_PATH", path)
        monkeypatch.setenv("TB_REGISTRY_PATH", str(path))
    return path


def promote_pins(out: Path, builds: list[str] | None = None) -> None:
    """Status champion and a qualification reference for the pinned weights of ``builds`` (default: every pin)."""
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    for build_id, entry in doc["builds"].items():
        if builds is None or build_id in builds:
            entry["status"] = "champion"
            entry["qualification"] = qualified(entry["sha256"])
    out.write_text(yaml.safe_dump(doc, sort_keys=True, allow_unicode=True), encoding="utf-8")
