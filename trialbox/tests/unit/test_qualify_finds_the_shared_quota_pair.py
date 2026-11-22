"""``eval qualify`` finds the builds of every profile it names in the shipped registry.

The shared-quota profile once carried a suffix the registry does not use, so its pair was never found.
"""

import pytest

from tools.qualify import PROFILES, profile_builds


def test_the_shared_quota_profile_finds_its_pair() -> None:
    builds = profile_builds("shared-quota")
    assert builds["judge"].build_id == "gemma-4-26b-a4b-it-sharedquota"
    assert builds["verifier"].build_id == "qwen3.5-9b-sharedquota"


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_every_profile_finds_a_judge_and_a_verifier(profile: str) -> None:
    builds = profile_builds(profile)
    assert builds["judge"].build_id
    assert builds["verifier"].build_id
