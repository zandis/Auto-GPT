# The findings register, sixth upkeep (2026-11-22)

**Reader:** the people who build TrialBox: lane H and the integrator. For builders, so in one language.

Card H-82. Lane H keeps the register (`docs/handover/findings-register.md`); every change below was made by
`python -m tools.findings_register` (`--add-from`, `--sync-states`), none by hand. The fifth upkeep was card H-60
(346 rows); the fourth, H-57, added `--sync-states`.

## Pull request body (draft)

H-82: the findings register's sixth upkeep. Rows **346 before, 422 after** (master 72a293ad).

- Counts before: open High 63, open Medium 182, open Low 69, total 346 (open 313, card issued 1, fixed 32).
- Counts after: open High 58, open Medium 193, open Low 105, total 422 (open 355, card issued 1, fixed 66).
- Added with `--add-from`: 19 findings files, 76 rows (table below). Every `fixed` sha among the added rows was
  checked to be an ancestor of master.
- States moved with `--sync-states`: 7 Highs that lane F's page found fixed on master, each proof test rerun here
  (7 passed); the states come from this card's
  [states.json](findings-register-sixth-upkeep-2026-11-22/states.json) (section below).
- Refused by the tool, not added, the files not changed (other cards' files):
  `docs/handover/host-run-bench-exception-2026-11-22.json` (H74-02, H74-04: basis `read` is not one of shown,
  hypothesis, not_run, not stated) and `docs/plan/measurements/runbook-install-2026-11-17/findings.json` (card
  `H-22` is not a card name; this is the form's example file, its one finding is the seeded row
  H22-stub-production-embedder).
- Not added, not on master: lane F's F1 file (draft #1331) and the plan 10 review's R22 file (draft #1327).

## Added per card

| Card | Findings file | Rows | open | fixed |
| --- | --- | --- | --- | --- |
| H59 | `docs/handover/measure48-quota-row-absent-2026-11-19.json` | 1 | 0 | 1 |
| H10G39 | `docs/handover/bandit-weekly-ledger-2026-11-19/findings.json` | 1 | 0 | 1 |
| H10G8 | `docs/handover/vex-from-waivers-2026-11-19/findings.json` | 9 | 6 | 3 |
| H10G11 | `docs/handover/host-check-knows-the-tier-2026-11-19/findings.json` | 4 | 4 | 0 |
| H10G41 | `docs/handover/dockerfile-and-image-scanners-2026-11-19/findings.json` | 10 | 9 | 1 |
| H10G42B | `docs/handover/sql-from-strings-rules-2026-11-19/findings.json` | 4 | 4 | 0 |
| H62 | `docs/handover/exit-abort-third-sighting-2026-11-19.json` | 1 | 0 | 1 |
| H63 | `docs/handover/coverage-ratchet-lost-lines-2026-11-19.json` | 2 | 0 | 2 |
| H10E38 | `docs/handover/ja-call-sizes-2026-11-20/findings.json` | 4 | 4 | 0 |
| H10E24 | `docs/handover/candidate-licences-2026-11-20/findings.json` | 4 | 4 | 0 |
| H65 | `docs/handover/three-guard-cards-2026-11-20/findings.json` | 4 | 4 | 0 |
| H66 | `docs/handover/ballast48-reserved-memory-2026-11-20.json` | 1 | 0 | 1 |
| H9H2 | `docs/plan/measurements/mapping-calls-9h2-2026-11-20/findings.json` | 2 | 2 | 0 |
| H69 | `docs/handover/owner-as-role-and-images-memory-2026-11-20/findings.json` | 2 | 2 | 0 |
| H67 | `docs/handover/measure-on-an-existing-host-2026-11-20.json` | 3 | 0 | 3 |
| H70 | `docs/handover/install-test-runbook-gaps-2026-11-20/findings.json` | 2 | 0 | 2 |
| H72 | `docs/handover/host-run-own-names-2026-11-22.json` | 3 | 1 | 2 |
| H73 | `docs/handover/unit-shard-1-fits-again-2026-11-22/findings.json` | 3 | 3 | 0 |
| H71 | `docs/handover/support-bundle-scrub-2026-11-22/findings.json` (H71-01 to H71-16) | 16 | 6 | 10 |

Of the cards of 2026-11-19 to 22 named for this upkeep, H-61 has no findings file on master, and H74 was refused
(above). No other findings file under `docs/` on master holds an id the register lacks.

## States moved, with their proofs

Lane F's page `docs/handover/high-findings-2026-11-22.md` (draft #1331, not on master) found 18 Highs fixed or not
on master, 7 of them still `open` in the register. Each proof test was run here on master (`TB_ENV=TEST`, 7 passed);
the fixing commit was checked to be an ancestor of master. For the three bootstrap rows lane F named e719484d, a
branch commit that is not on master; master's commit carrying D-996's `deploy/bootstrap.sh` and its tests is
be8874eb, which is the sha written.

| Row | Was | Now | Proof (passes on master) |
| --- | --- | --- | --- |
| H22-no-host-tree | open | fixed be8874eb | `tests/unit/test_install_bootstrap.py::test_it_unpacks_the_signed_host_tree_places_the_key_and_runs_the_installer` |
| H22-vendor-key-after-start | open | fixed be8874eb | the same test |
| H22-bundle-sidecar-path | open | fixed be8874eb | `tests/unit/test_install_bootstrap.py::test_the_sidecar_checks_from_another_mount` |
| H22-stub-production-embedder | open | fixed be8874eb | `tests/unit/test_stub_box_embedder.py::test_stub_mode_pins_the_embedder_and_stops_a_production_install_without_it`; a healthy box is not re-measured |
| H23b-01 | open | fixed 83f0490e | `tests/unit/test_orchestrator_cap.py::test_install_writes_the_cap_above_the_default_and_removes_its_own_when_no_longer_needed` |
| W2-db-image | open | fixed 083ce607 | `tests/unit/test_poc_db_image.py::test_a_machine_without_images_builds_the_database_image_with_the_one_command` |
| V5-04 | open | fixed cf037b9d | `tests/unit/test_masking_leaks.py::test_no_planted_identifier_survives[mask-ja-national_id-insurance_symbol_no-in]` |

The register's state cell takes a sha only; the proof tests are in `states.json` (`proof`, a field the register does
not copy) and here. The rows' own findings files (size-test, install-rehearsal-sheet, masking-leaks) give no `state`
field, so `states.json` is the only source `--sync-states` reads for these ids; the seeded H22 rows have no findings
file. None is seen closed: lane R sets that.

Lane F's two "cannot tell": **H36-01** is in the register as High, `open` (source p3-review-2026-11-17: about 41 s
more per approval); not moved. **H18-03** is in the register as High (mapped), `open` (source p2b-review-2026-11-17:
"older than N years" read as N+1); not moved.

## The plan 10 review's file (draft #1327)

`docs/reviews/2026-11-22-plan-10-review/findings.json` is not on master and is not added. A dry run of `--add-from`
in a scratch worktree of the pull request's head, outside this tree, wrote its rows and passed `--check`: the tool
accepts the file's form as it is. It holds 67 findings, R22-01 to R22-67 (not 56), card `R22`.

## Not verified

- The added rows' claims and states are their cards'; this card checked their form (the tool) and that each `fixed`
  sha is on master, not each fix.
- No box was installed: H22-stub-production-embedder's healthy box is not measured.
