"""OPS-004b (D-574): the release gates look at every image a bundle carries. ``tools/make_bundle.sh`` takes the
box's compose file and the identity overlay (Caddy, Authelia: on every PRODUCTION box); the gates' list in the
Makefile left the overlay out, so those two images were never scanned and a bundle with them could not pass
``bundle-check``. Every third-party image of a bundle also has a licence budget, as the others have."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools.supply_chain import allowlist

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb


def _compose_call(text: str, start: str) -> str:
    """The ``docker compose ... config --images`` command that follows ``start``, as one line."""
    block = text[text.index(start) :]
    block = block[block.index("docker compose") : block.index("config --images")]
    return " ".join(block.replace("\\\n", " ").split())


def _files_and_profiles(call: str) -> tuple[set[str], set[str]]:
    files = {Path(f.strip('"')).name for f in re.findall(r"-f (\S+)", call)}
    return files, set(re.findall(r"--profile (\S+)", call))


def test_the_gates_list_holds_every_file_and_profile_the_bundle_takes_its_images_from() -> None:
    bundle = _compose_call((ROOT / "tools" / "make_bundle.sh").read_text(encoding="utf-8"), "done < <(")
    gates = _compose_call((ROOT / "Makefile").read_text(encoding="utf-8"), "SC_THIRD_PARTY ?=")
    b_files, b_profiles = _files_and_profiles(bundle)
    g_files, g_profiles = _files_and_profiles(gates)
    assert "docker-compose.identity.yml" in b_files  # the premise: a bundle carries the identity overlay
    assert b_files <= g_files, f"in a bundle, not gated: {sorted(b_files - g_files)}"
    assert b_profiles <= g_profiles, f"in a bundle, not gated: {sorted(b_profiles - g_profiles)}"


def test_the_gates_list_renders_without_a_site() -> None:
    """The overlay refuses to render without the console's name; the list gives a placeholder, as the bundle does,
    so that a missing name never ends in a list with no third-party image."""
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    line = mk[mk.index("SC_THIRD_PARTY ?=") :].split("\n\n", 1)[0].split("\n# ", 1)[0]
    assert "TB_TLS_HOSTNAME=bundle.invalid" in line


def _bundle_repositories() -> set[str]:
    """The third-party image repositories named in the two compose files a bundle is made from."""
    repos = set()
    for name in ("docker-compose.yml", "docker-compose.identity.yml"):
        for m in re.finditer(r"^\s+image:\s*(\S+)", (ROOT / "deploy" / name).read_text(encoding="utf-8"), re.M):
            ref = re.sub(r"^\$\{[A-Z_]+:-(.*)\}$", r"\1", m.group(1).strip('"'))
            repo = ref.split("@", 1)[0].rsplit(":", 1)[0]
            if not repo.startswith("trialbox-"):
                repos.add(repo)
    return repos


def test_every_third_party_image_of_a_bundle_is_pinned_and_has_a_licence_budget() -> None:
    repos = _bundle_repositories()
    assert {"caddy", "authelia/authelia", "hapiproject/hapi", "vllm/vllm-openai"} <= repos
    lock = json.loads((ROOT / "deploy" / "images.lock").read_text(encoding="utf-8"))
    pinned = {str(e["image"]).rsplit(":", 1)[0] for e in lock["third_party"].values()}
    assert repos <= pinned, f"not in images.lock: {sorted(repos - pinned)}"
    allow, _ = allowlist.load(today=None)
    budgeted = {b.image for b in allow.budgets if b.ecosystem == "*"}
    assert repos <= budgeted, f"no licence budget: {sorted(repos - budgeted)}"
