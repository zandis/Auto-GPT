# D-1005: the orchestrator's memory cap grows with the hospital

Status: reserved (lane D, card H23b-01)

## Context

The size test (H-23b, D-1137) found H23b-01 (High, shown). SCREEN of the whole hospital holds its rows in the
orchestrator, and needed 4.37 GiB at 50,000 patients and 8.22 GiB at 100,000. The orchestrator's cap is
`${TB_MEM_ORCH:-4g}`, and no installer step or overlay raised it, the reference workstation's included. So a box as
installed killed SCREEN from about 45,000 patients, whatever its memory. The finding asked: does the installer size
the cap, or does lane A2 bound SCREEN's memory (H-23's limit 1)? The integrator gave lane D the first, on 2026-11-19.

## Decision

`tools/trialbox/memcaps.py` sizes `TB_MEM_ORCH` as it sizes the adapter's and the lake's caps (T-692, D-473):

- **The record.** `deploy/measured/orchestrator_memory.json` is written by `memcaps --from-ladder` from the size
  ladder's results, today `docs/plan/measurements/size-test-2026-11-17.json` (H-23 and H-23b). For each patient
  count, the record takes the orchestrator's highest peak over every stage. A count where a stage was killed at its
  cap is left out of that table, because its peak is the cap and not the need. The record lists what it left out.
  The line's slope is the least-squares slope of the peaks. Its fixed part is raised until the line lies on or above
  every peak: 558.2 MB plus 80.682 KB per patient. No constant is guessed, and a test checks that the shipped record
  is the tool's output.
- **The installer** (`memcaps --write`, already called by `deploy/install.sh`) writes `TB_MEM_ORCH` once the need
  passes the compose default of 4 GiB, from about 45,000 patients: 4,498 MB at 50,000, 8,438 MB at 100,000. Below
  that nothing is written, so a small hospital keeps the shipped shape, the two-device workstation's 3 GiB included. A
  value this tool wrote and no longer needs is removed. A value set by hand is kept.
- **`trialbox doctor`** (`memory_caps`) fails when `TB_MEM_ORCH` is below the need. A box without the record (from
  before this card) is checked for the adapter and the lake only.

The new file rides in every bundle with the host tree (what git holds, T-631).

## What this does not do

- It does not bound SCREEN's memory. That is lane A2's limit 1 and H23b-02. When A2 lowers the peaks, a new ladder run
  and `--from-ladder` lower the line.
- It does not check that the machine has the memory. At 100,000 patients the orchestrator alone needs about 8.3 GiB.
- The line has no margin beyond the highest measured peak: 28 MB at 50,000. The peaks are resident memory on the size
  test's machine (4 vCPU, the enforcer in "measure" mode, no Docker).
- The two-device workstation's doctor check compares with the base default of 4 GiB, not its overlay's 3 GiB.

## Tests

`tests/unit/test_orchestrator_cap.py` (9).
