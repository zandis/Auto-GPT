# D-584 Our own REDCap test instance: built from a release zip the owner supplies, never from one we fetch or keep

- **Task:** NEW-EDC-0 (plan v7.2 sections 2 (Q4, Q5) and 2.4; the conformance tests R1 to R9 of the deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/10-redcap-edc.md` section 8)
- **PR:** this branch (`agent/NEW-EDC-0-redcap-test-instance`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-494 (the owner's answers: "You install redcap and run"; the API send is live at go-live), D-434
  (the switch per study: `on` sends through the API, `copy` writes nothing), ICD-04 (the REDCap link)

## Context

Nothing in the REDCap link or the pre-fill send has ever talked to a real REDCap (EDC-001). REDCap is not open
source: an institution gets it under the REDCap Consortium licence and may not pass the code on.

## Decision

1. **The zip is the owner's.** The release zip, in the version the sites run, is placed once by the owner (or the
   institution's REDCap administrator) at the path of the setting `TB_REDCAP_ZIP`; the default is
   `deploy/site/redcap/redcap.zip`, in a folder the repository ignores. The zip is never committed, never in a
   bundle, never in CI, and no tool of ours downloads REDCap. Without the zip every command stops and says where
   to put it.
2. **One tool, `tools/redcap_instance.py`.** `check` reads the zip without unpacking it (its version, the files an
   install needs, no path that leaves the folder). `up` unpacks it under `deploy/site/redcap/` and starts PHP and
   MariaDB from `deploy/redcap-test/compose.yml`, bound to the loopback address only, then installs REDCap from the
   zip's own SQL. `project` builds the test project and its users and tokens. `run` runs R1 to R9 and writes the
   record. `all` does the four in order.
3. **The test project is data in the repository** (`tests/edc_kit.py`, `CONFORMANCE`): the CRF of the kit, the
   longitudinal and repeating set of `tests/unit/test_edc_t302b.py` (two arms, four events, the repeating `ae`
   instrument, a calculated field, branching logic), and one checkbox field, one `date_dmy` field and one
   `number_1dp` field. Synthetic data only.
4. **Four tokens and a locker.** A user with export and import rights; one with export only; one bound to a data
   access group; one whose rights expired; and a user who may lock a form. The tokens are random, made at set-up,
   written to `deploy/site/redcap/instance.json` (mode 0600, ignored by the repository) and never printed.
5. **The record of a run** is a JSON file beside it (`conformance-<date>.json`): for each of R1 to R9 the status and
   body REDCap gave (cut to a declared length), what was written, and pass or fail against the review's "pass"
   column. Synthetic values only; no token in it.
6. **A stand-in for the dry run.** `--stand-in` runs `project` and `run` against the simulator (`rc_sim`) in the
   tool's own process. It proves the tool, not REDCap: the simulator is known to accept what REDCap refuses
   (EDC-001), and the record says which tests it fails.
7. **Not a box service.** The compose file is not one of the box's compose files (`deploy/docker-compose*.yml`), is
   in no bundle and no network sheet, and runs on a developer's or the owner's machine. Its images are public
   (PHP with Apache, MariaDB); REDCap's code is only ever in the ignored folder.

## What the owner must do

Put the REDCap release zip at `trialbox/deploy/site/redcap/redcap.zip` (or set `TB_REDCAP_ZIP`), then run
`python -m tools.redcap_instance all` on a machine with Docker. The instance runs under the supplying institution's
licence.

## Not in this card

- NEW-EDC-1: the run on the instance recorded as cassettes that CI replays, and the simulator made as strict.
- The repairs R1 to R9 will ask for (EDC-002, -003, -007, -008).
