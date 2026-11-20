# H-10E-24: a licence row for every candidate model

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** 10E-24 (plan 10, track E; review 17 card 17-9; decision 93 ruled). Lane H since the integrator's comment
  on PR #1221 of 2026-11-19, 23:51 UTC.
- **Date:** 2026-11-20
- **Decision:** [D-1347](../decisions/D-1347-every-candidate-has-a-licence-row-and-unread-terms-never-ship.md)
- **Findings:** [`candidate-licences-2026-11-20/findings.json`](candidate-licences-2026-11-20/findings.json)
  (H10E24-01 to H10E24-04)
- **Tests:** `tests/unit/test_licence_candidates.py`; `tests/unit/test_qualify.py` (`test_10e24_*`)

No licence page was opened for this card. Every licence fact in a new row comes from root review 17
(`docs/reviews/2026-11-root/17-accuracy-and-models.md`) or `models/registry.yaml`, and the row cites it.

## 1. Why the builders' branch was not kept

Draft PR #1221 (`agent/10E-24-record-candidate-licences`, head `8f653e71`) wrote revisions, licence text hashes and
licence terms for the candidates that the repository does not hold, so they could not be cited. It also changed the
licence step of `qualify` (the release gate) and added a text hash to the shipped judge's row. Most of it would
have been reverted, so this branch starts from master `d28f6c03`.

## 2. What changed

| File | Change |
| --- | --- |
| `tools/licence_register.py` | `CANDIDATES` (review 17's candidates by register id and role). `candidate_problems`: a row per candidate; decision 93's licences `excluded`; unread terms never cleared; a cleared model row names a full commit id. `pin_problems`: a verified build's pins. Statuses `terms-not-read` and `excluded`, which ship nothing. Both run in `check()` beside `models/registry.yaml`. `model_problems` is unchanged. |
| `docs/licences/register.csv` | 13 new model rows. 11 `terms-not-read`, 2 `excluded`. The existing rows are unchanged. |
| `docs/decisions/D-1347-…md`, `REGISTRY.md` | The decision, and its row as reserved. |

## 3. The review's findings and how each is closed

Each Medium has a test that fails on the builders' head `8f653e71` and passes here.

| Finding (integrator, 23:51 UTC) | Closed by | Test |
| --- | --- | --- |
| Medium, `qualify.py:605`: revision and weight hash passed into the gate | `qualify.py` is not changed. The pins are held by `--check`. | `test_10e24_medium_1_the_licence_step_asks_no_revision_of_a_build` |
| Medium, `register.csv:31`: a new text hash on the judge's row refuses CRLF text | The judge's row is not changed and keeps no hash. | `test_10e24_medium_2_the_committed_judge_row_pins_no_text_so_line_endings_do_not_matter` |
| Medium, the candidate list only in the tests | `CANDIDATES` is in the tool, and `--check` fails on a missing row. | `test_medium_3_a_missing_candidate_row_fails_the_check_itself` |
| Medium, `expected.revision` hides the installed `revision` | Both pins are compared with each other and with the row. | `test_medium_4_the_installed_revision_is_checked_against_the_expected_one` |
| Medium, `main` accepted as a pin; an empty pin on a measured champion | A pin and a cleared row's revision must be 40 hex. A build past candidate needs a pin. | `test_medium_5_a_promoted_build_needs_an_immutable_commit` |
| Medium, a source revision alone marks a candidate measured | No pin is asked of a `candidate`. The provenance is not read. | `test_medium_6_an_unmeasured_candidate_can_have_its_terms_verified_before_its_pins` |
| Low, every verified build treated as shipped | That test is not carried. The shipped set is the rows that are `cleared`. | `test_every_candidate_has_a_model_row_and_only_todays_pair_is_cleared` |
| Low, a bad commit accepted when it is in the evidence URL | Pins are checked as 40 hex, not found in the evidence. | `test_medium_5_…` |

Decision 93 has planted tests: `test_an_excluded_licence_marked_shippable_fails_the_check` and
`test_a_planted_candidate_under_such_a_licence_cannot_ship` (the CLI exits 1 on the row and on the build).

## 4. What was not done

- No licence text was read, so no candidate became shippable (H10E24-01).
- The registry's older unverified candidates have no rows (H10E24-02).
- A site's `qualify` run does not check pins (H10E24-04).
