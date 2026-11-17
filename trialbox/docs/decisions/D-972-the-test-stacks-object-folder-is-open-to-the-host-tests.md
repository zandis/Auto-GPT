# D-972 the test stack's object folder is open to the host's tests

- **Task:** lane D, the owner of the nightly; the integrator's request on #639 (2026-11-16) to trace the nightly's reds
- **PR:** this branch (`agent/NIGHTLY-RED-the-test-stack-objects-folder-is-writable`)
- **Date:** 2026-11-16
- **Status:** accepted
- **Builds on:** D-121 (the test stack's objects bind-mounted for the integration tests)

## Context

The nightly's compose job (`make up-test`, then `make test-compose`) failed
`tests/integration/test_compile_compose.py::test_compile_and_approve_round_trip` every night on record (11-14, 11-15
and 11-16; on 11-13 the whole module errored in set-up) with
`PermissionError: [Errno 13] Permission denied: '.../trialbox/deploy/.objects/attachments'`.

`deploy/.objects` is bind-mounted into the test stack (`deploy/docker-compose.test.yml`, `TB_HOST_OBJECTS_DIR`) so the
host's integration tests read and write objects directly (D-121). The services run as uid 10001
(`deploy/docker/python.Dockerfile`); the runner's tests run as the runner's user. `make up-test` made only the top
folder. A bucket the services made first, `attachments` with mode 755 and owner 10001, then refused the host test its
job folder (`attachments/<job>/`).

## Decision

1. `make objects-dir` makes the folder and every bucket of `tb_common.objstore.BUCKETS` (`OBJECTS_BUCKETS` in the
   Makefile, held equal by the unit test) with mode 0777, and `make up-test` runs it before the stack starts. Both the
   services and the host's tests can then create their folders in any bucket.
2. When it cannot open a folder (an earlier stack made it as another user), it stops and says to remove the folder;
   it never goes on with a folder the tests cannot write.
3. Only the test stack uses this folder, and it holds synthetic test objects only. A box's object store (`deploy/
   docker-compose.yml`, a named volume) is not touched.

## Test

`tests/unit/test_test_stack_objects_writable.py`: `up-test` runs `objects-dir` before `up -d --wait`;
`OBJECTS_BUCKETS` equals `BUCKETS`; `make objects-dir` really leaves every bucket writable by another user; a folder
it cannot open stops it with the folder named. The nightly's compose job is the end-to-end check.

## The other compose reds

The other five failing tests of that job are not this folder's; they go to their lanes through the integrator
(#639).
