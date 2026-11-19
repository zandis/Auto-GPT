"""Card 10G-43 (OT-5): the one property the malformed-input tests check on every reader.

**Returns or refuses; no other exception; under N s and M MB.** A reader given any input either returns, or raises
its own documented refusal (the exception class its caller catches); anything else (``IndexError``, ``KeyError``,
``csv.Error``, ``zipfile.BadZipFile``, ``UnicodeDecodeError`` that is not the refusal, ...) fails the property. Each
call is timed and its peak Python allocation measured (``tracemalloc``), against :data:`MAX_SECONDS` and
:data:`MAX_MB` for inputs of at most :data:`MAX_INPUT` bytes.

A reader's defect found by a property is a finding of card 10G-43 (``H10G43-NN``): its minimal input is kept as an
explicit ``@example`` in a test marked ``xfail(strict=True)`` with the finding id, so the suite stays green and the
fix flips it (the fixing card removes the mark).

The settings (:data:`SETTINGS`) keep the seven files under about a minute: bounded examples, no deadline (the bound
is :data:`MAX_SECONDS`, measured here), derandomized so the gate is the same on every run, no example database.
"""

from __future__ import annotations

import time
import tracemalloc
from collections.abc import Callable
from typing import Any

import pytest

hypothesis = pytest.importorskip("hypothesis", reason="hypothesis is a dev dependency (T-737); `make venv`")

from hypothesis import HealthCheck, settings  # noqa: E402

MAX_SECONDS = 2.0  # N: one call on one generated input
MAX_MB = 64  # M: the peak of Python's own allocations during that call
MAX_INPUT = 64 * 1024  # the generated inputs stay below this many bytes

SETTINGS = settings(
    max_examples=60,
    deadline=None,
    derandomize=True,
    database=None,
    report_multiple_bugs=False,  # one exception per test, so an xfail names the one it expects (Escaped)
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much],
)


class Escaped(AssertionError):
    """The reader raised something other than its refusal: the property fails, naming the exception."""


def returns_or_refuses(call: Callable[[], Any], refusals: tuple[type[BaseException], ...]) -> Any:
    """Run ``call``; return its result, or None when it raised one of ``refusals``. Any other exception fails, and
    so does a call over :data:`MAX_SECONDS` or :data:`MAX_MB`."""
    tracemalloc.start()
    t0 = time.perf_counter()
    try:
        out = call()
    except refusals:
        out = None
    except Exception as exc:  # the property: nothing else gets out of a reader
        raise Escaped(f"{type(exc).__module__}.{type(exc).__qualname__}: {str(exc)[:200]}") from exc
    finally:
        took = time.perf_counter() - t0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert took <= MAX_SECONDS, f"one call took {took:.2f} s (bound {MAX_SECONDS} s)"
    assert peak <= MAX_MB << 20, f"one call peaked at {peak / (1 << 20):.1f} MB (bound {MAX_MB} MB)"
    return out
