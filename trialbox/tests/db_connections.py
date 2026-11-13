"""A test gives its database connections back (PG-LEAK, D-635).

A store opens one connection for its life (``tb_common.db.Database``); an app has several. A service's process ends
and closes them. A test builds an app, ends, and nothing closed them: the objects stay referenced, so the garbage
collector does not either. Measured on 2026-11-13: a console app test left 8 open for the worker's life, and the
whole tree in one run reached the throwaway cluster's ``max_connections``.

So the harness closes what a test opened. :data:`TRACKER` records every connection made through ``psycopg.connect``
(what ``Database`` and the tests' own code call). ``tests/conftest.py`` asks it, when a test and all its fixtures
are done, to close the ones opened since that test began. A connection opened while a fixture of a wider scope
(class, module, package, session) is being set up belongs to that fixture and is never closed here.
"""

from __future__ import annotations

import contextlib
import threading
import weakref
from typing import Any

import psycopg


class Tracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._made: list[tuple[weakref.ref[Any], bool]] = []  # (connection, opened for a wide fixture)
        self._wide = 0
        self._real: Any = None

    # ---------------------------------------------------------------------------------------- recording
    def install(self) -> None:
        """Wrap ``psycopg.connect`` once for this process (a worker)."""
        if self._real is not None:
            return
        self._real = psycopg.connect

        def connect(*args: Any, **kwargs: Any) -> Any:
            con = self._real(*args, **kwargs)
            with self._lock:
                self._made.append((weakref.ref(con), self._wide > 0))
            return con

        psycopg.connect = connect

    def wide(self, delta: int) -> None:
        """A fixture wider than one test is being set up (+1) or is set up (-1)."""
        with self._lock:
            self._wide += delta

    def mark(self) -> int:
        with self._lock:
            return len(self._made)

    # ---------------------------------------------------------------------------------------- giving back
    def close_since(self, mark: int) -> int:
        """Close every connection opened since ``mark`` that no wide fixture owns; how many were still open."""
        with self._lock:
            mine, self._made[mark:] = self._made[mark:], [x for x in self._made[mark:] if x[1]]
        closed = 0
        for ref, wide in mine:
            con = ref()
            if wide or con is None or con.closed:
                continue
            with contextlib.suppress(Exception):  # a connection another thread broke is closed all the same
                con.close()
            closed += 1
        return closed

    def open_from_tests(self) -> int:
        """Connections a test opened that are still open now (0 between tests)."""
        with self._lock:
            made = list(self._made)
        return sum(1 for ref, wide in made if not wide and (con := ref()) is not None and not con.closed)


TRACKER = Tracker()
