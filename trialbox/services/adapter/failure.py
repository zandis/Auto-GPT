"""What the adapter keeps of a failure (NEW-B-27, D-668): the error's type, and its words only when they are the
adapter's own.

The run record (``adapter.runs``; the orchestrator reads it into the job's error and the mail) and the ingest
report's ``errors`` are read outside the adapter. An error the adapter did not expect was written by code it does
not own (a driver, a parser, the standard library), and such a text quotes what it choked on: a row's value. So:

* **the adapter's own sentences stay whole**: the classes of :data:`_own`, raised with sentences written here that
  hold dates, snapshot names, file paths and settings, never a row's value. The exact class, not a subclass made
  somewhere else;
* **a mapping error keeps its words up to the first value** (``pipeline.reject_key``, D-520: the form already
  decided for a rejected row's key);
* **anything else is its type**, and where the rest is: the adapter's log holds the text and the traceback
  (``log.exception`` at the place that caught it).

The same class as D-664 for the lake's answers.
"""

from __future__ import annotations

REST = "the error's text is in the adapter's log only, it can hold a row's value"


def _own() -> tuple[type[BaseException], ...]:
    from tb_common.crypto import KeyMissingError
    from tb_common.feedguard import FeedGuardError

    from adapter.pipeline import FutureNight, SiteKeyError
    from adapter.publish import NothingToPublish
    from adapter.runs import RunLockHeld

    return (SiteKeyError, FutureNight, NothingToPublish, RunLockHeld, FeedGuardError, KeyMissingError)


def words(exc: BaseException, run: str = "") -> str:
    """What is kept of ``exc`` outside the log. ``run``: the run to look for in the log."""
    from adapter.mapping.engine import MappingError
    from adapter.pipeline import reject_key

    if type(exc) in _own():
        return f"{type(exc).__name__}: {exc}"
    if isinstance(exc, MappingError):
        return reject_key(exc)
    return f"{type(exc).__name__} ({REST}{f'; run {run}' if run else ''})"


__all__ = ["REST", "words"]
