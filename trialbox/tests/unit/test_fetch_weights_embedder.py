from typing import Any

from tools.fetch_weights import plan


def test_plan_includes_embedder(monkeypatch: Any) -> None:
    """The embedder should be accepted by ``plan`` when ``embedder=True``."""
    # No special environment variables are needed for this test.
    env: dict[str, str] = {}
    # The profile “shared-quota” is present in the registry and has an embedder entry.
    targets = plan("shared-quota", env, embedder=True)
    # The embedder build id is ``e-embed-1``; it must appear in one of the targets.
    assert any("e-embed-1" in t.builds for t in targets)
