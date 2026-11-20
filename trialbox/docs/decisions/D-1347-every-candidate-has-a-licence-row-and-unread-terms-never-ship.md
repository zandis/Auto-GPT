# D-1347 Every candidate model has a licence row; unread terms and community or health-developer licences never ship

- **Task:** lane H, plan 10 row 10E-24 (review 17 card 17-9; decision 93 ruled). Draft PR #1221 was ruled to lane H
  on 2026-11-19 (the integrator's comment of 23:51 UTC).
- **Date:** 2026-11-20
- **Status:** proposed
- **Builds on:** T-617b (the register's build check), D-565 (HW-004: the licence step of `qualify`), D-392 (build
  provenance), plan 10 decision 93 (community and health-developer licences excluded from the shipped box)

## Context

Root review 17 lists the candidate builds of the model bake-off (§7.2) and a licence verdict per family (§4.3). The
register held rows only for today's pair, the guard and the embedder. The builders' draft added rows whose
revisions, licence text hashes and terms were not in the repository, and changed the licence step of `qualify`
(the release gate). Its second review left six Medium findings.

## Decision

1. **Every candidate has a row.** `tools/licence_register.py` holds the candidate list (`CANDIDATES`, review 17
   §7.2 and §4.3, by register id and role). `--check` fails when one has no `model` row. The list is in the tool, so
   a missing row fails CI, not only a test.
2. **A row states only what the repository records.** Each new row cites review 17 (section and source number) for
   its licence name. A revision is written only where `models/registry.yaml` holds it. No licence text hash is
   written for a text that was not read.
3. **Unread terms never ship.** A row whose obligation or evidence says "terms not read" has status
   `terms-not-read` (or `excluded`), never `cleared`. Status `terms-not-read` must say so. Both statuses ship nothing.
4. **Decision 93 is a rule of the check.** A model row whose licence or SPDX column names a community or
   health-developer licence has status `excluded`. A build whose licence names one is never verified and never past
   `candidate`. The match lower-cases the column and drops every character but letters and digits.
5. **A cleared model row names one full commit id** (`revision <40 hex>`).
6. **Pins are held by the register check, not by `qualify`.** For a verified build on a cleared row, `--check`
   fails when the installed `revision` and `expected.revision` differ, a pin is not a full commit id, a pin is not
   the row's revision, or a build past `candidate` has no pin. An unpinned `candidate` passes, so its terms can be
   read before its weights are measured. `model_problems`, which `qualify`'s licence step calls, is unchanged.
7. **The shipped pair's rows are unchanged.** The judge's row keeps no text hash, so a licence text beside the weight
   folder is recorded as before, whatever its line endings.

## Consequences

- 13 new rows: 15 candidates in all. Only today's pair is `cleared`. Eleven new rows are `terms-not-read` and two
  are `excluded` (`model-qwen3.8-flash-next`, `model-medgemma`). Twelve say "terms not read" (the eleven and
  `model-medgemma`).
- A candidate becomes shippable only by a change that records its pinned revision and its licence text's sha256,
  and sets the row `cleared` (review 17 §7.3 rule 5). That reading needs the network and is not done here.
- `qualify` behaves as on master. A site's qualification run does not check the revision pins; CI does.
- Tests: `tests/unit/test_licence_candidates.py`; two tests in `tests/unit/test_qualify.py` (`test_10e24_*`).
