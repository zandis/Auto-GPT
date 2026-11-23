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
from tools import support_bundle as sb

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


#: the time bounds of the scrub's tests, in one place (#1354 round 3, L4): a line of 48 masks, and the ratio of 4,000
#: masks to 1,000 on one line (linear is 4; a quadratic path is 16; no slack added)
BOUNDS = {"line_of_48_masks_s": 0.5, "four_times_the_masks_ratio": 6.0}


@pytest.mark.parametrize(
    "unit",
    ["03-1234-5678", "0912-345-678", "RA01-0042", "password=abcd1234", "a1b2c3d4e5f60718293a4b5c6d7e8f90"],
)
def test_review_the_scrub_of_one_line_is_linear_in_its_masks(unit: str) -> None:
    """No line of 48 masks may take more than its bound, and four times the masks may take at most the bound's ratio
    of the time (a linear scrub; the hang grew 16-fold with each 4 masks). Timed at 1,000 and 4,000 masks, where the
    time is far above a timer's noise, so the ratio needs no slack."""
    line = {n: "%2F " + " ".join([unit] * n) + " 'token': abcdefgh12" for n in (48, 1000, 4000)}
    t48 = _timed(lambda: bs.Scrubber.for_bundle().text(line[48]))
    assert t48 < BOUNDS["line_of_48_masks_s"], f"{t48:.2f} s"
    t1 = _timed(lambda: bs.Scrubber.for_bundle().text(line[1000]))
    t4 = _timed(lambda: bs.Scrubber.for_bundle().text(line[4000]))
    assert t4 <= BOUNDS["four_times_the_masks_ratio"] * t1, f"1,000 masks {t1:.3f} s, 4,000 masks {t4:.3f} s"


def test_review_the_raw_line_is_kept_only_when_it_is_the_view_mark_for_mark() -> None:
    """The condition of the fix, held directly (the mutation pass found no line that told an equal length or a part
    from the whole): a different mark, a mark missing, the same length, and one inside the other are not the same."""
    same = "next=/p/[pseudonym #bcdfg]?password=[redacted]"
    assert bs._same_masks(same, same)
    assert not bs._same_masks("next=/p/[MRN]?password=[redacted]", same)  # another mark in its place
    assert not bs._same_masks("next=/p/9659a6d97592b[PHONE]aba1a4b274", "next=/p/[pseudonym #bcdfg]")
    assert not bs._same_masks("ab[x]cd", "abc[x]d")  # the same length
    assert not bs._same_masks("a[x]", "a[x]b") and not bs._same_masks("a[x]b", "a[x]")  # a part of the other
    assert not bs._same_masks("pid=ABCDEF[x]", "pid=abcdef[x]")  # a case of its own: not the same text


@pytest.mark.parametrize(
    "line",
    [
        "GET /p/%2F--passwd%20D9tshbrt5tntdg%20A123456789 200",  # found by the mutation search of round 3
        "GET /p/%2F--token%20Q7xk2mVb9tLpw%20RA01-0042 200",
        "x=%2F--api-key%20Wm4k8pZq2xJr%2003-1234-5678",
    ],
)
def test_review_an_encoded_flag_value_beside_an_identifier_leaves_nothing(line: str) -> None:
    """#1354 round 3, L5: a raw line the same length as its view, but not the view, is not kept (a mutant that kept
    it left the value; only the direct ``_same_masks`` test told it apart before)."""
    value = line.split("%20")[1]
    out = bs.Scrubber.for_bundle().text(line)
    assert value.lower() not in (out + bs._decode(out)).lower(), out


@pytest.mark.parametrize(
    "line",
    [
        "--password Kq7w%20Zx9m",
        '"password": "Kq7w\\u0022Zx9m"',
        "Authorization: Bearer Kq7w%0AZx9m",
        "password=Kq7w%0aZx9m",
        "password=Kq7w&#10;Zx9m",
    ],
)
def test_review_a_secret_masked_on_the_raw_line_stays_masked_when_the_line_is_written_decoded(line: str) -> None:
    """#1354 round 3, H2: an encoded separator inside a secret's value (a space, a quote, a line break) cuts the value
    in the decoded view, so the view alone masks only its first part. The secret rule runs on the raw line first,
    and no part of the value is left (through the bundle's path: ``scrub_text``, then ``redact_secrets``)."""
    out, _ = sb.redact_secrets(bs.scrub_text(line))
    seen = out + "\n" + bs._decode(out)
    assert "Kq7w" not in seen and "Zx9m" not in seen, out


@pytest.mark.parametrize("line", ["%2F %2F[--password%20Wq3bKmZt9x]", "%2F %2F[--password%20Wq3bKmZt9x] user=amy"])
def test_review_a_secret_inside_a_log_s_own_brackets_is_not_taken_for_a_mask(line: str) -> None:
    """#1354 round 3, L5: a log's own ``[...]`` is text, not a mask; a comparison that blanked every bracket kept the
    raw line with the value in it (only the direct ``_same_masks`` test told it apart before)."""
    out, _ = sb.redact_secrets(bs.scrub_text(line))
    assert "wq3bkmzt9x" not in (out + "\n" + bs._decode(out)).lower(), out
