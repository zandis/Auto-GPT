# D-733 Two tests that needed an order run in any order

- **Task:** NIGHT-ORDER, tonight's nightly reds of lane D (TrialBox nightly #110, run 43631693731, master 5ff9f813;
  R1, nightly green three nights in a row)
- **PR:** this branch (`agent/NIGHT-ORDER-two-tests-that-need-an-order`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-201 and D-560 (the nightly's unit suite in random order), D-721 (OMOP-STORE), D-635 (PG-LEAK)

## Context

The nightly runs the unit suite in random order (pytest-randomly). Two of lane D's tests passed in file order only:

1. `test_omop_store_roles.py::test_a_service_refuses_to_make_a_second_lakes_store` (shard 1/6, "DID NOT RAISE
   OmopError"): it asked for the store of `OTHER_LAKE`, which the admin's test of the same module makes; after that
   test there is nothing left to refuse.
2. `test_db_connections_given_back.py::test_2_the_next_test_finds_them_closed` (shard 5/6, `0 == 4`): it checked what
   test 1 had left, so it proved something only when test 1 ran before it.

Both reproduced with the order given on the command line.

## Decision

1. The refusal test asks for the store of a lake folder no other test makes (`/srv/never-made-by-<role>/lake`).
   It refuses, says which store, folder and box lake, and leaves nothing made, in any order.
2. The two PG-LEAK tests are the same shape: each leaves four connections and checks that what the other left is
   closed and that nothing of an earlier test is open. Whichever runs second proves that the harness closed the
   first one's connections after that test.

## Test

Before: the two orders that broke them gave `3 failed`. After: both orders pass, and both files pass under
pytest-randomly with six seeds of this session and the six seeds tonight's nightly used.
