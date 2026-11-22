"""A country layer whose committees part is set to False has the committees part off (integrator, 2026-11-22)."""

from typing import Any

import pytest
from tb_common import committees, country_layer


class _Layer:
    broken = False

    def __init__(self, committees_value: Any) -> None:
        self._v = committees_value

    def value(self, part: str, key: str) -> Any:
        return self._v if (part, key) == ("P3", "committees") else None


@pytest.mark.parametrize(("value", "expected"), [(False, False), (None, False), ({"study_kinds": {}}, True)])
def test_committees_false_is_off(monkeypatch: pytest.MonkeyPatch, value: Any, expected: bool) -> None:
    monkeypatch.setattr(country_layer, "layer", lambda country: _Layer(value))
    assert committees.on("JP") is expected
