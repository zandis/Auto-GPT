# D-1086 Eight unit shards, pinned from a measured table, measured again at a quarter more test files

- **Task:** lane H, card H-83 (finding H73-02); the number given by the integrator on 2026-11-22 · **Date:** 2026-11-22
- **Status:** accepted (the integrator's number; recorded by card H-87)
- **Builds on:** D-475 (the shards and their hash), D-564 item 7 (the shards' limit is measured), D-1355 (worksteal)
- **The page:** `docs/handover/unit-shard-split-measured-again-2026-11-22.md`, section "The decision", with the
  measured table `docs/handover/unit-shard-costs-h83.json` and the pins `tools/test_shard_pins.json`

## Decision

1. The unit tier runs in eight shards.
2. A test file's shard is its pin in `tools/test_shard_pins.json` when the pins are for that number of shards;
   otherwise it is the hash of D-475.
3. The pins are `tools.test_shard plan` over a per-file cost table measured from CI's shard jobs. They are never
   edited by hand, and the table says how it was measured. The shards' records prove the union as before.
4. The table is measured again, and the plan re-run, when a shard comes within 30 % of its limit on a runner, or when
   the tree has 25 % more test files than the table (a test holds this:
   `test_the_measured_table_is_not_older_than_the_suite_by_more_than_a_quarter`).
5. The limit stays at 40 minutes, with D-564's derivation beside it. It is not lowered before eight green runs of the
   new split are measured.
