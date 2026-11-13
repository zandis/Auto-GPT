# D-635 A test gives its database connections back

- **Task:** PG-LEAK (found by the integrator by running the whole test tree in one run, 2026-11-13)
- **PR:** this branch (`agent/PG-LEAK-tests-give-connections-back`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-201 (one throwaway PostgreSQL per test worker, `tools/pglocal.py`)

## Context

The whole test tree in one run (63 minutes, one machine) ended with "remaining connection slots are reserved"
on a worker's own cluster. Measured by lane D with a probe that counts the cluster's client connections after
each test: every test that builds a console app through the shared `box` fixture left 8 connections open for
the rest of the worker's life (`tests/console/test_items_page.py`: 8, 16, 24 ... 88 after eleven tests). A store
opens one connection (`tb_common.db.Database`), an app has several stores, and nothing closed them when the
test ended; the objects stay referenced, so the garbage collector does not close them either. With
`max_connections=300` a worker lasts about 37 such tests; CI's six shards are shorter and had not reached it.

This is not a product finding: a service holds its stores for the life of its process, and the process's end
closes them. The tests build hundreds of apps in one process.

## Decision

1. The test harness closes what a test opened. `tests/db_connections.py` records every connection opened
   through `psycopg.connect` while a test runs; when the test and all its fixtures are done, the ones it opened
   are closed. A connection opened while a fixture of a wider scope (class, module, package, session) is being
   set up belongs to that fixture and is left alone.
2. No test is changed and no fixture needs to remember: the rule is in one place, and a new test that builds an
   app cannot bring the leak back.
3. `max_connections` of the throwaway cluster stays 300. Raising it would move the wall, not remove the slope.

4. In the same card, asked by the integrator: two tests of the gateway held a wall-clock bound that a loaded
   runner broke once each on 2026-11-13 (1.06 s against "under 1 s"; 386 ms against "under 250 ms"). The bound
   measured the machine. Each now says what it means with no real-time bound: the slot-wait test gives the
   gateway a clock the test moves (the wait is exactly 250 ms, the server's time exactly 0); the load test
   asserts orderings and what the gateway asked its queue for (health answers while calls still hang; the front
   desk's call asks for the interactive wait and never the batch budget; once the breaker is open the call does
   not queue at all).

## Consequences

- A worker's cluster holds only the connections of the test that is running, plus those of wide fixtures.
- A test that hands a connection to a thread it does not stop loses that connection when it ends; the thread's
  next query fails. That was already a test leaving work behind.
