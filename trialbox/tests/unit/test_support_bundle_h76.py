"""H-76, the follow-up of H-71: a test per finding, red before its fix and green after. Every random value is drawn
from a seed of the test's own id (``Seeded`` in ``test_support_bundle_planted.py``): no run depends on the order,
the worker or ``--dist``. Synthetic values only."""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable

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


# ------------------------------------------------------------------------------------------------ review of #1354
def _chart(digits: int, bound: str = "0-9") -> re.Pattern[str]:
    """A chart-number pattern of ``digits`` digits. ``bound`` is what may not stand beside it: ``0-9A-Za-z`` as
    ``mrn_pattern`` wraps a site's pattern, or digits only, as the review's probe did (and as the log scrubber's own
    phone patterns are bounded), which fires between the letters of a hex run."""
    return re.compile(rf"(?<![{bound}])[0-9]{{{digits}}}(?![{bound}])")


def _run_left(pid: str, out: str, n: int = 5) -> list[str]:
    """Every run of ``n`` or more of the pseudonym's characters still in ``out`` (any case)."""
    low = out.lower()
    return [pid[i : i + n] for i in range(len(pid) - n + 1) if pid[i : i + n] in low]


def _timed(fn: Callable[[], object]) -> float:
    best = 1e9
    for _ in range(3):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best


def test_review_h1_a_line_that_cannot_be_lined_up_does_not_hang_the_scrub() -> None:
    """#1354 H1: 24 masks on a 335-character line took 9.7 s (0.04 s on master); each 4 more masks multiplied it by
    16. The bound is a small multiple of master's time, on a slow runner too."""
    probe = "%2F " + " ".join(["03-1234-5678"] * 24) + " 'token': abcdefgh12"
    took = _timed(lambda: bs.Scrubber.for_bundle().text(probe))
    assert took < 0.5, f"{took:.2f} s"


def test_review_m1_two_raw_rules_that_cut_a_pseudonym_leave_nothing_of_it() -> None:
    """#1354 M1: with a 7-digit chart pattern the raw rules cut the pseudonym into pieces under 8 digits each, and
    the shortcut kept the raw line: ``next=%2Fe3b296e[MRN]c702d[PHONE]c2e7``."""
    pid = "e3b296e6352540c702d051568971c2e7"
    out = bs.Scrubber.for_bundle(mrn=_chart(7)).text(f"next=%2F{pid}")
    assert _run_left(pid, out) == [], out


@pytest.mark.parametrize("bound", ["0-9", "0-9A-Za-z"])
@pytest.mark.parametrize("digits", range(5, 11))
def test_review_m1_class_no_pair_of_raw_rules_leaves_part_of_a_pseudonym(digits: int, bound: str) -> None:
    """The class: a site's chart pattern of 5 to 10 digits and the log scrubber's phone patterns, each able to cut a
    pseudonym hidden by an encoding. 150 seeded pseudonyms, each in one of the encoded forms: no run of 5 or more of
    its characters may remain (a run of 4 can stand in other text by chance; the page says so)."""
    rng = random.Random(f"H-76a review M1 class {digits} {bound}")
    s = bs.Scrubber.for_bundle(mrn=_chart(digits, bound))
    for _ in range(150):
        pid = "".join(rng.choice("0123456789abcdef" if rng.random() < 0.5 else "0123456789") for _ in range(32))
        form = rng.choice(ENCODED)
        out = s.text("x=" + form.format(t=pid) + "&y=1")
        assert _run_left(pid, out) == [], (form, pid, out)


@pytest.mark.parametrize(
    "unit",
    ["03-1234-5678", "0912-345-678", "RA01-0042", "password=abcd1234", "a1b2c3d4e5f60718293a4b5c6d7e8f90"],
)
def test_review_the_scrub_of_one_line_is_linear_in_its_masks(unit: str) -> None:
    """No line may take more than 0.5 s at 48 masks, and doubling the masks may not much more than double the time
    (a linear scrub; the hang grew 16-fold with each 4 masks)."""
    lines = {n: "%2F " + " ".join([unit] * n) + " 'token': abcdefgh12" for n in (24, 48)}
    t24 = _timed(lambda: bs.Scrubber.for_bundle().text(lines[24]))
    t48 = _timed(lambda: bs.Scrubber.for_bundle().text(lines[48]))
    assert t48 < 0.5, f"{t48:.2f} s"
    assert t48 <= 2.5 * t24 + 0.02, f"24 masks {t24:.3f} s, 48 masks {t48:.3f} s"
