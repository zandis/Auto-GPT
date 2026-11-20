# The 48 GB run's preflight and a quota row that is not listed (card H-59, 2026-11-19)

**Reader:** the people who build TrialBox

Lane H. Finding H59-01 ([findings JSON](measure48-quota-row-absent-2026-11-19.json)).

## What the integrator saw

`deploy/gcp/measure48-run.sh --preflight --commit <sha>` on master exited 4 with
`asia-east1: HDB_TOTAL_GB quota not readable`. `gcloud compute regions describe asia-east1` returned 113 quota rows,
and none of them was `HDB_TOTAL_GB`. So `tools/measure48_vm.py quota` refused every launch. The 500 GB limit and
400 GB in use that lane H had came from the message of a refused create call, not from this list.

## The fix

The integrator's ruling: when the row is absent, say so and go on; keep the refusal when the row is there and short;
or pass the free figure by an option.

- Row absent from a well-formed list: one line, and the quota step passes (exit 0):
  `quota: asia-east1: HDB_TOTAL_GB is not in the region's quota list (113 rows), so the 100 GB disk quota cannot be
  checked beforehand; the create call itself refuses if it is short (--hdb-free-gb N gives the free figure by hand)`.
- Row present and short: refused, exit 4, as before. Present and enough: passes, as before.
- `--hdb-free-gb N` (on `measure48_vm.py quota` and on the driver): the free GB by hand, checked against the need
  like a listed row. A non-number is refused (exit 2).
- A failed gcloud call, or output that is not a quota list (not JSON, no `quotas` list): refused, exit 4.
- A refused create call (the disk quota, say): gcloud's reason is shown, the driver checks that no VM by the name is
  left, and the launch ends with exit 5. The VM and its boot disk are made together or not at all.

Tests: `tests/unit/test_measure48_run_h53.py`, with a synthetic 113-row list that has no `HDB_TOTAL_GB` row. The
driver tests use the stand-in gcloud; no cloud call was made.

## Not verified

The create call's real refusal text and exit status on Compute Engine; the stand-in prints a synthetic one.
