"""H-76, the follow-up of H-71: a test per finding, red before its fix and green after. Every random value is drawn
from a seed of the test's own id (``Seeded`` in ``test_support_bundle_planted.py``): no run depends on the order,
the worker or ``--dist``. Synthetic values only."""

from __future__ import annotations

import random

import pytest

from tests.unit.test_support_bundle_review1 import ENCODED
from tools import bundle_scrub as bs

#: pseudonyms that left in part when the raw line's phone pattern cut them before the decoded view read the line
#: (found by drawing 20 000 pseudonyms; the invariant test failed on master about once in 60 runs)
FLAKE_PIDS = [
    "81e464e3dfaa0b022044419fbefa9f1c",
    "d8817e0af088239924d57d1e46814959",
    "a4382307164f7a7aeac52f0812439029",
    "26c022565768fa8585689c072bad30b1",
    "b361e31377878455f7e058958255d770",
    "7a78124708f93f3bd003236707c9b2a5",
]


def _left(pid: str, out: str) -> list[str]:
    """Every run of 8 or more of the pseudonym's digits that is still in ``out`` (any case)."""
    low = out.lower()
    return [pid[i : i + 8] for i in range(len(pid) - 7) if pid[i : i + 8] in low]


@pytest.mark.parametrize("pid", FLAKE_PIDS)
def test_flake_the_pseudonyms_that_left_are_masked_whole(pid: str) -> None:
    line = f"next=%252Fp%252F{pid}%253Fpassword%253Dabc"
    assert _left(pid, bs.Scrubber.for_bundle().text(line)) == []


@pytest.mark.parametrize("form", ENCODED)
def test_flake_class_no_raw_rule_cuts_a_token_before_the_decoded_view(form: str) -> None:
    """The class: a token that the raw line hides (its encoded neighbour joins it) must reach the decoded view whole.
    150 pseudonyms a form, from a fixed seed; no 8 of their digits may stay."""
    rng = random.Random(f"H-76 flake class {form}")
    s = bs.Scrubber.for_bundle()
    for _ in range(150):
        pid = rng.getrandbits(128).to_bytes(16, "big").hex()
        out = s.text("x=" + form.format(t=pid) + "&y=1 tail")
        assert _left(pid, out) == [], (pid, out)
