"""Security review 2026-11-13: a ``back=`` value from a request leads back into the console only. Before the fix
``/help``, ``/cmd`` and ``/ask`` passed ``/\\evil.example/x`` through, which a browser resolves to another site."""

from __future__ import annotations

import pytest
from console import site_pages, step4
from console.local_path import local_path


@pytest.mark.parametrize(
    "value", ["//evil.example/x", "/\\evil.example/x", "/\\/evil.example", "https://evil.example", "/a\tb", "/a\nb", ""]
)
def test_a_value_that_can_leave_the_site_gives_the_default(value: str) -> None:
    assert local_path(value, "/home") == "/home"
    assert step4._safe_back(value) == "/home"


@pytest.mark.parametrize("value", ["/home", "/studies/GZQO/week?tab=1", "/"])
def test_a_local_path_is_kept(value: str) -> None:
    assert local_path(value, "/home") == value
    assert step4._safe_back(value) == value


def test_the_ask_page_uses_the_one_rule() -> None:
    source = site_pages.__file__
    with open(source, encoding="utf-8") as f:
        text = f.read()
    assert 'back if back.startswith("/") and not back.startswith("//")' not in text
    assert "local_path(back" in text
