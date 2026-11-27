"""INT-M10 (min), item a: the licence inventory page rides in every release bundle, and names its lawyer's list.

The page (``docs/licences/licence-inventory.md``) is the hand-checked half of a release's licences; the generated half
is ``sbom/licences.md``. Here: the bundle carries the page as ``sbom/licence-inventory.md`` beside the generated report,
byte for byte; the lawyer's list names each item the integrator asked for; models appear by their role only, never by
a build, an alias or a family of ``models/registry.yaml``. The bundle is built with the stand-in docker and the
synthetic kit of ``test_release_bundle.py``.
"""

from __future__ import annotations

import json
import re
import tarfile
from pathlib import Path
from typing import Any

import yaml

from tests.unit import test_release_bundle as rb

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "licences" / "licence-inventory.md"
IN_BUNDLE = "sbom/licence-inventory.md"
ROLES = {"judge", "verifier", "embedder"}  # the words the page may use: a role, never a build
kit = rb.kit  # the synthetic bundle kit (stand-in docker, signing key, registry), as test_release_bundle.py makes it


def _section(text: str, heading: str) -> str:
    m = re.search(rf"^## \d+\. {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, heading
    return m.group(1)


def _read(tf: tarfile.TarFile, name: str) -> bytes:
    fh = tf.extractfile(name)
    assert fh is not None, name
    return fh.read()


def test_the_bundle_carries_the_inventory_page_beside_the_generated_report(kit: dict[str, Any]) -> None:
    gates, sbom = rb._gate_record(kit["tmp"], [*rb.OWN, rb.BACKUP, rb.HAPI, rb.VLLM])
    res = rb._make(kit, "--release-seq", "4", "--gates", str(gates), "--sbom-dir", str(sbom))
    assert res.returncode == 0, res.stdout[-3000:] + res.stderr[-3000:]
    with tarfile.open(kit["tmp"] / "release" / "out.tar") as tf:
        manifest = json.loads(_read(tf, "manifest.json"))
        files = {f["path"] for f in manifest["files"]}
        assert {IN_BUNDLE, "sbom/licences.md"} <= files, sorted(files)
        assert _read(tf, f"files/{IN_BUNDLE}") == PAGE.read_bytes()  # the payload lies under files/


def test_the_lawyers_list_names_every_item_asked_for() -> None:
    lawyer = _section(PAGE.read_text(encoding="utf-8"), "For the owner's lawyer")
    for item in ("psycopg", "docxtpl", "py7zr", "LGPL", "dulwich", "Apache-2.0", "object-store image",
                 "The judge model", "The verifier model", "The embedder"):  # fmt: skip
        assert item in lawyer, item
    dulwich = next(ln for ln in lawyer.splitlines() if ln.startswith("| dulwich"))
    assert "chooses **Apache-2.0**" in dulwich, dulwich


def test_models_appear_by_role_only() -> None:
    reg = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text(encoding="utf-8"))
    names: set[str] = set(reg.get("aliases") or {})
    for b in reg.get("builds") or []:
        names.update(str(b[k]) for k in ("build_id", "family", "repository") if b.get(k))
    text = PAGE.read_text(encoding="utf-8").lower()
    named = sorted(n for n in names - ROLES if len(n) > 3 and n.lower() in text)
    assert not named, named
