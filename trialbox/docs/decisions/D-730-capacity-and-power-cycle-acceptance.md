# D-730 Go-live acceptance gains a capacity criterion and a power-cycle criterion

- **Task:** T-317a, the acceptance part of T-317 ("acceptance gains capacity and power-cycle criteria"; lane D's
  queue in `docs/plan/37-remaining-work-split.md`)
- **PR:** this branch (`agent/T-317a-capacity-and-power-cycle-acceptance`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-83 (`tools/acceptance.py`, SPEC §11.2), D-492 (the night runner: one chain per night), D-377 and
  RUNBOOK §22 (the planned power cut)

## Context

Go-live acceptance (RUNBOOK §6) checked the data, the screening, the NHI forms, reproduction and the audit chain. It
did not check that the box carries the site's night in time, or that it comes back whole after a power cut, which
Japanese hospitals have every year (法定点検).

## Decision

1. `acceptance.py capacity --jobs <night.json>`: the night's jobs as the orchestrator lists them. The chain is the
   jobs whose `options.night` names the night (the night runner's screen, nav and retention), with the ingest whose
   published generation or snapshot date names it. It passes when every one ended `done` and the last ended before
   the first morning notice that follows the night's start (`TB_NOTICE_N1_AT`, in `TB_TZ`) with at least one hour
   to spare (`SPARE_H`). A job that failed or never ended fails it. With no job of the night, it fails.
2. `acceptance.py power-cycle --doctor <doctor --json> --audit-dir <dir>`: after the power came back, the doctor
   has no FAIL (WARNs are counted, not failed), and the audit chain verifies. An empty doctor answer fails.
3. Both are in `TARGETS`, so `report` lists them and the overall result waits for them.

The one-hour margin and the notice time as the deadline are this card's proposal for SPEC §11.2; the owner or the
site may set others (`SPARE_H`, `--ready-by`).

## Not covered

- The patient count of the night is not part of the criterion (the night is the site's own data, whatever its size);
  the capacity statement of T-734 is the measured one.
- The role guides in ja and zh-TW (the other part of T-317) are a later card.
