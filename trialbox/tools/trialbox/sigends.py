"""H-142: how a restore or an update ends under SIGINT, SIGTERM and SIGHUP. Standard library only (the host's
``trialbox restore`` runs it with the host's python).

**The process's own way out.** The entry's ``__main__`` block calls :func:`own_exit`: this process ends when the
command returns. A restore or an update then never gives the signals' defaults back at its end (H138-02, .b): from
its state line to the exit, SIGINT, SIGTERM and SIGHUP stay ignored, whatever its exit code, so a signal on the way
out never turns a said end into 143 or 129. A caller in the same process (the tests, another command) gets its own
handlers back as before.

**Taken at once.** The three handlers change together, the signals blocked meanwhile (:func:`swap`): one that
arrives between two changes waits for the last, never meets a half-changed set. A signal the caller ignored when the
command started (``nohup``, a job started with ``&``) stays ignored (.j, as ``update.Stops`` keeps it)."""

from __future__ import annotations

import contextlib
import signal
import sys
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)

_own_exit = False


def own_exit() -> None:
    """The entry's ``__main__`` block only: this process ends when its command returns."""
    global _own_exit
    _own_exit = True


def owned() -> bool:
    """True in a process whose way out is the command's own (:func:`own_exit`)."""
    return _own_exit


def main_thread() -> bool:
    return threading.current_thread() is threading.main_thread()


def swap(new: Mapping[int, Any]) -> dict[int, Any]:
    """Each signal of ``new`` given its handler, all at once (blocked while they change); the old ones returned.
    Elsewhere than the main thread nothing changes (signals are delivered there)."""
    if not main_thread() or not new:
        return {}
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
    try:
        return {sig: signal.signal(sig, h) for sig, h in new.items()}
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)


def take(handler: Callable[[int, Any], Any], sigs: Iterable[int] = SIGNALS) -> dict[int, Any]:
    """The command's handler for each of ``sigs`` that the caller did not ignore (.j). Returned: the handlers of all
    three as they were, for :func:`leave` (the end may have ignored any of them)."""
    if not main_thread():
        return {}
    was: dict[int, Any] = {s: h for s in SIGNALS if (h := signal.getsignal(s)) is not None}
    swap({s: handler for s in sigs if was.get(s) is not signal.SIG_IGN})
    return was


def ignore() -> dict[int, Any]:
    """SIGINT, SIGTERM and SIGHUP ignored from here; the old handlers returned."""
    return swap(dict.fromkeys(SIGNALS, signal.SIG_IGN))


@contextlib.contextmanager
def held() -> Iterator[None]:
    """The block runs whole (a clean-up after a signal, .f): the three signals wait, blocked, until it ends and are
    then delivered as usual. Nothing in it may start a process (a child would inherit the block)."""
    if not main_thread():
        yield
        return
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)


def put_back(old: Mapping[int, Any]) -> None:
    swap(dict(old))


def leave(old: Mapping[int, Any]) -> None:
    """The command's end. On the process's own way out every one of the three stays ignored to the exit, its
    streams flushed first (an unflushed line is lost to a signal's death); else ``old`` is put back."""
    if _own_exit:
        ignore()
        flush()
    else:
        put_back(old)


def flush() -> None:
    for s in (sys.stdout, sys.stderr):
        with contextlib.suppress(OSError, ValueError, RuntimeError, AttributeError):  # a closed terminal: not said
            s.flush()
