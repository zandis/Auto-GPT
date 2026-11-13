# D-533 The scale gate's dense profile: about 500 records and 40 notes per patient

- **Task:** T-687, the wave 1 row of plan v7 ("the dense profile ... under the compose memory caps"; PERF-002)
- **PR:** this branch (`agent/T-687b-dense-profile`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-471 (T-687: the scale gate, each part of the night under its compose cap), OD-10 (capacity is the
  hardware and the model's speed, never a number of the demo)

## Context

The scale gate runs the night of a hospital at 50,000 synthetic patients. Its hospital is the generator's own:
about 30 structured records and under 2 notes per patient (site A: 600 patients, 18,580 records, 1,040 notes). A
real chart is an order of magnitude thicker. The parts of the night that are sized by records, not by patients
(the snapshot's merge, the Parquet build, the note index, the backup), met a hospital of 50,000 people with the
data of 3,000.

## Decision

1. **The dense profile is 500 structured records and 40 notes per patient** (`tb_testkit.scale.DENSE_RECORDS`,
   `DENSE_NOTES`): the plan's words. They define the test hospital; they are not limits of the product.
2. **It is made by thickening the generator's feed** (`tb_testkit.scale.densify`), not by a second generator:
   every row of a chart table (encounter, diagnosis, lab, medication, vital, procedure, report; notes apart) is
   written again as copies, copy `c` under the row's key with `c` appended, every date `c` weeks earlier, the same
   patient, naming a copy of its encounter. A copy before the patient's birth is left out. People, staff, consent,
   bookings and claims are not thickened. The generator, and the fixtures made from it, are unchanged.
3. **How many copies is counted from the feed**, the smallest number that meets the target, so the profile holds
   for any generator and any size. In streams: the dense feed of 50,000 patients is never held in memory.
4. **The gate takes it as a setting**: `TB_SCALE_PROFILE` (`thin`, the default, or `dense`) and `--profile`. The
   report says the profile and what it measured (records and notes per patient).

## What a first run shows (300 patients, this container, the caps measured not enforced)

| part | dense, 300 patients: 154,382 records, 12,100 notes |
|---|---|
| ingest | 32 s, peak 0.14 GiB (cap 6 GiB) |
| lake rebuild and queries | 21 s, peak 1.23 GiB (cap 8 GiB) |
| screen | 6 s, peak 0.18 GiB (cap 4 GiB) |

At the ingest's rate here (about 5,000 records a second) the dense night of 50,000 patients (about 26 million
records) is about an hour and a half of ingest on this kind of machine before the rebuild starts. Whether the
lake's peak stays under its cap at that size is what the nightly run is for; 1.23 GiB at 154,382 records does not
say.

## Consequences

- The pull request's small run gains one dense gate at 30 patients (15 s).
- The nightly job's profile is its workflow's to set (`TB_SCALE_PROFILE: dense`); it is **not** changed here: at
  50,000 patients the dense night is many times longer than the thin one, which is a cost somebody decides.

## Not decided here

- The lint over every `timeout=` and `LIMIT`, not only those above 60 s (the same plan row): 19 more entries, each
  with a reason. A card of its own, after the lease (D-532) is on a train (it adds short waits the list must
  count).
- Notes are copies of the generator's notes: the same texts, forty times. The note index's size is real; what a
  model reads in them is not more varied than before.
