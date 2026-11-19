"""What the adapter keeps of a failure (NEW-B-27, D-668): the error's type, and its words only when they are the
adapter's own.

The run record (``adapter.runs``; the orchestrator reads it into the job's error and the mail) and the ingest
report's ``errors`` are read outside the adapter. An error the adapter did not expect was written by code it does
not own (a driver, a parser, the standard library), and such a text quotes what it choked on: a row's value. So:

* **the adapter's own sentences stay whole**: the classes of :func:`_own`, raised with sentences written here that
  hold dates, snapshot names, file paths and settings, never a row's value. The exact class, not a subclass made
  somewhere else;
* **a mapping error keeps its words up to the first value** (``pipeline.reject_key``, D-520: the form already
  decided for a rejected row's key);
* **anything else is its type**. The error's text is kept nowhere; the adapter's log has the type and the frames
  it failed in (:func:`log_failure`), which is what finds the line.

The same class as D-664 for the lake's answers.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable

REST = "the error's text is not kept, it can hold a row's value; the adapter's log has where it failed"


def _own() -> tuple[type[BaseException], ...]:
    from tb_common.crypto import KeyMissingError
    from tb_common.feedguard import FeedGuardError
    from tb_common.id_rule import IdRuleError

    from adapter.pipeline import FutureNight, LakeBudgetError, NoRoomForNight, SiteKeyError
    from adapter.publish import NothingToPublish
    from adapter.runs import RunLockHeld

    return (
        SiteKeyError, FutureNight, NothingToPublish, RunLockHeld, FeedGuardError, KeyMissingError, NoRoomForNight,
        LakeBudgetError, IdRuleError,
    )  # fmt: skip


def words(exc: BaseException, run: str = "") -> str:
    """What is kept of ``exc`` outside the log. ``run``: the run to look for in the log. Never raises."""
    try:
        from adapter.mapping.engine import MappingError
        from adapter.pipeline import reject_key

        if any(type(exc) is own for own in _own()):
            return f"{type(exc).__name__}: {exc}"
        if isinstance(exc, MappingError):
            return reject_key(exc)
        return f"{type(exc).__name__} ({REST}{f'; run {run}' if run else ''})"
    except Exception:  # an error that cannot even be named or read
        return f"an error ({REST})"


class LakeFailed(RuntimeError):
    """The lake, run in the adapter's own process, failed on an error that is not one of its refusals (NEW-B-28,
    D-669). The message is the lake's safe answer for it (``lake.store.error_answer``, D-664): the error's type
    and the lake's fixed sentence, never the engine's text."""


def local_lake[T](call: Callable[[], T]) -> T:
    """Run a call of the lake library as the lake service would answer it (D-669). The lake's own refusals pass as
    they are, class and words: the publish reads the class (busy, refused: D-462, D-271) and the words ("built
    again since", D-531), and the service passes the same ones whole. Anything else is logged as its type and
    where it failed, and raised as :class:`LakeFailed` with the lake's safe answer."""
    from lake.store import LakeLimitError, LakeSaid, LakeSchemaError, RebuildError, StaleSnapshotError, error_answer
    from omop.schema import OmopError

    try:
        return call()
    except (RebuildError, OmopError, LakeSaid, LakeLimitError, LakeSchemaError, StaleSnapshotError):
        raise
    except FileNotFoundError:  # "no lake snapshot <date>": the lake's own words (the service answers 404 with them)
        raise
    except Exception as exc:
        log_failure(logging.getLogger("adapter"), "the lake in this process failed", exc)
        try:
            said = error_answer(exc, "build")
        except Exception:
            said = f"an error ({REST})"
        raise LakeFailed(said) from None


def log_failure(log: logging.Logger, what: str, exc: BaseException) -> None:
    """Log a failure as its type and where it failed: the frames (file, line, function), never the error's text
    (no feed value in a log: the data-handling rule D-520 builds on; the same form as the lake's build log, D-664).
    Never raises."""
    try:
        frames = [f"{f.filename}:{f.lineno} in {f.name}" for f in traceback.extract_tb(exc.__traceback__)]
        log.error("%s: %s", what, type(exc).__name__, extra={"error": type(exc).__name__, "frames": frames})
    except Exception:
        log.error("%s", what)


__all__ = ["REST", "LakeFailed", "local_lake", "log_failure", "words"]
