"""H-142: how a restore or an update ends under SIGINT, SIGTERM and SIGHUP. Standard library only (the host's
``trialbox restore`` runs it with the host's python).

**The process's own way out.** The entry's ``__main__`` block calls :func:`own_exit`: this process ends when the
command returns. A restore or an update then never gives the signals' defaults back at its end (H138-02, .b): from
its state line to the exit, SIGINT, SIGTERM and SIGHUP stay ignored, whatever its exit code, so a signal on the way
out never turns a said end into 143 or 129. A caller in the same process (the tests, another command) gets its own
handlers back as before.

**From the entry's first line.** For a restore or an update the entry notes a signal that comes before the command
takes its own handlers (``own_exit(note=True)``: the argument parsing, the imports); the command's :func:`replay`
then sends it again to its own handler, which ends it as a signal before any change ends (.a, .d, .h). Elsewhere a
signal keeps its default.

**Said, never broken by a closed terminal.** After the first signal the streams are :class:`Tolerant` (.g): a line
that cannot be written is not said, and the handling goes on (the exit's own flush included: never 120).

**Taken at once.** The three handlers change together, the signals blocked meanwhile (:func:`swap`): one that
arrives between two changes waits for the last, never meets a half-changed set. A signal the caller ignored when the
command started (``nohup``, a job started with ``&``) stays ignored (.j, as ``update.Stops`` keeps it)."""

from __future__ import annotations

import contextlib
import os
import signal
import sys
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)

_own_exit = False
_noted: list[int] = []  # the first signal before the command took its handlers (own_exit(note=True))


class Tolerant:
    """A terminal stream that a closed session cannot break: a write or a flush that fails is dropped (H-114,
    ``update.py``; H-142 .g: the restore's too)."""

    def __init__(self, stream: Any) -> None:
        self._s = stream

    def write(self, text: str) -> int:
        with contextlib.suppress(OSError, ValueError, RuntimeError):
            return int(self._s.write(text) or 0)
        return len(text)

    def flush(self) -> None:
        with contextlib.suppress(OSError, ValueError, RuntimeError):
            self._s.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._s, name)


def own_exit(note: bool = False) -> None:
    """The entry's ``__main__`` block only: this process ends when its command returns. ``note``: a restore's or an
    update's (the first signal before the command's own handlers is kept for :func:`replay`)."""
    global _own_exit
    _own_exit = True
    if note and main_thread():
        swap({s: _note for s in SIGNALS if signal.getsignal(s) is not signal.SIG_IGN})


def _note(signum: int, _frame: Any) -> None:
    if not _noted:
        _noted.append(signum)


def replay() -> None:
    """Inside the command's own handling, its handlers in: the signal the entry noted, sent again to them."""
    if _noted:
        sig = _noted.pop()
        _noted.clear()
        os.kill(os.getpid(), sig)


def tolerant() -> None:
    """From here a closed terminal never breaks a line (.g); :func:`untolerant` (``leave``) unwraps them."""
    if not isinstance(sys.stdout, Tolerant):
        sys.stdout = Tolerant(sys.stdout)
    if not isinstance(sys.stderr, Tolerant):
        sys.stderr = Tolerant(sys.stderr)


def untolerant() -> None:
    """The streams in force, unwrapped (never an older pair put back over a newer one)."""
    if isinstance(sys.stdout, Tolerant):
        sys.stdout = sys.stdout._s
    if isinstance(sys.stderr, Tolerant):
        sys.stderr = sys.stderr._s


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
    """The block runs whole (a clean-up after a signal, .f): a signal that comes meanwhile is kept and given to the
    handler that was in, once the block has ended. (Not by blocking it: in a process with other threads the kernel
    gives a signal one thread blocks to another.)"""
    if not main_thread():
        yield
        return
    got: list[int] = []
    old = swap({s: (lambda n, _f: got.append(n)) for s in SIGNALS if signal.getsignal(s) is not signal.SIG_IGN})
    try:
        yield
    finally:
        put_back(old)
        if got:
            h = old.get(got[0])
            if callable(h):
                h(got[0], None)  # the handler that was in: it raises after the clean-up, not inside it
            elif h is not signal.SIG_IGN:
                signal.raise_signal(got[0])  # the default's action, as if the signal came now


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
        untolerant()


def flush() -> None:
    for s in (sys.stdout, sys.stderr):
        with contextlib.suppress(OSError, ValueError, RuntimeError, AttributeError):  # a closed terminal: not said
            s.flush()
