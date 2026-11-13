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

REST = "the error's text is not kept, it can hold a row's value; the adapter's log has where it failed"


def _own() -> tuple[type[BaseException], ...]:
    from tb_common.crypto import KeyMissingError
    from tb_common.feedguard import FeedGuardError

    from adapter.pipeline import FutureNight, SiteKeyError
    from adapter.publish import NothingToPublish
    from adapter.runs import RunLockHeld

    return (SiteKeyError, FutureNight, NothingToPublish, RunLockHeld, FeedGuardError, KeyMissingError)


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


def log_failure(log: logging.Logger, what: str, exc: BaseException) -> None:
    """Log a failure as its type and where it failed: the frames (file, line, function), never the error's text
    (no feed value in a log: the data-handling rule D-520 builds on; the same form as the lake's build log, D-664).
    Never raises."""
    try:
        frames = [f"{f.filename}:{f.lineno} in {f.name}" for f in traceback.extract_tb(exc.__traceback__)]
        log.error("%s: %s", what, type(exc).__name__, extra={"error": type(exc).__name__, "frames": frames})
    except Exception:
        log.error("%s", what)


__all__ = ["REST", "log_failure", "words"]
