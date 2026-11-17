"""The return address kept across a sign-in (D-777, ``console.next_page.safe_next``) is a path of this console only.

Lane J's finding on master 15108f46 (the integrator's High): among control characters only CR and LF were refused, so
a tab, a NUL, an escape, DEL or a Unicode control, format or line separator passed. A browser drops some of them from
a URL ("/\\t/evil.example" reads as "//evil.example": another origin). Every character below 0x21, DEL, the Unicode
categories Cc, Cf, Zl and Zp are refused, and so is "//" once whitespace is taken out. One case per class. Synthetic."""

from __future__ import annotations

import pytest
from console.next_page import safe_next


@pytest.mark.parametrize("ch", [chr(c) for c in range(0x00, 0x21)] + ["\x7f"])
def test_every_ascii_control_and_space_is_refused(ch: str) -> None:
    assert safe_next(f"/studies{ch}x") == "", repr(ch)


UNICODE = [0x85, 0x9B, 0x200B, 0x200E, 0x202E, 0x2060, 0xFEFF, 0x2028, 0x2029]  # Cc, Cf, Zl, Zp


@pytest.mark.parametrize("ch", [chr(c) for c in UNICODE])
def test_unicode_controls_formats_and_separators_are_refused(ch: str) -> None:
    assert safe_next(f"/studies{ch}x") == "", repr(ch)


@pytest.mark.parametrize(
    "raw", ["/" + chr(c) + "/evil.example" for c in (0x09, 0x20, 0x0A, 0x200B)] + ["//evil.example", "/\\evil.example"]
)
def test_two_slashes_once_whitespace_is_taken_out_are_refused(raw: str) -> None:
    assert safe_next(raw) == "", repr(raw)


@pytest.mark.parametrize("raw", ["/studies/GZQO/week", "/studies/GZQO/week?list=all&pid=ab12", "/audit?kind=x%20y",
                                 "/studies/GZQO/患者"])  # fmt: skip
def test_a_plain_path_of_this_console_is_kept(raw: str) -> None:
    assert safe_next(raw) == raw


@pytest.mark.parametrize(
    "raw",
    ["/x" + chr(c) + "y" for c in (0x200B, 0x2028, 0x00)] + ["/" + chr(c) + "/evil.example" for c in (0x20, 0x3000)],
)
def test_the_role_switchs_path_back_follows_the_same_rule(raw: str) -> None:
    """``console.local_path`` (the role switch's and the language switch's way back) refuses the same characters."""
    from console.local_path import local_path

    assert local_path(raw, "/") == "/", repr(raw)
    assert local_path("/studies/GZQO/week?list=all", "/") == "/studies/GZQO/week?list=all"
