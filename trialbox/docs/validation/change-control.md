# Change control, change classes and the staged roll-out

*Card T-215 (deep review OPS-026, REG-027; TB-ASSESS-01 WS-12.7). Decision D-344. Status: living. No signature and
no approval step: D-311 removed every development gate. Where this page and TB-DS-04 §9.3 or TB-DS-12 §5 differ, this
page wins.*

## 1. What a change record is

A change is a pull request on the repository. Its record is the pull request: the description, the diff, the CI
results and, when it takes a decision, the decision file `docs/decisions/D-nnn-<slug>.md`. The description names:

* the card id;
* the **change class** (§2), one or more of CC1 to CC6;
* whether a class B path is touched (`software-safety-classification.md`, this folder);
* the decision number, if any;
* the tests that show the change, and the problem-log rows it closes (`problems.csv`, this folder).

A merge on green CI accepts the change. A change to a class B path also gets one automated adversarial review
(D-311). No human approval is required.

## 2. Change classes

The classes are those of TB-DS-04 §9.3, in their D-311 form. A change that fits two classes takes both and runs the
checks of both.

| Class | What it covers | Checks before it merges | Before it reaches a site |
| --- | --- | --- | --- |
| **CC1 Model-affecting** | weights, quantisation, the serving engine version, prompt text, thresholds of the cascade, excerpt budget, note-search parameters, the PHI detector, routing between the pair | CI; `trialbox eval qualify` on the changed tier with a passing qualification record (D-313); the goldens; release note "model change" | the canary on the site's hardware; approved rulesets flagged for re-approval only when the judge prompt version changes (D-318) |
| **CC2 Data path** | ingest, the adapter, mapping engine, code tables, date and unit normalisers, OMOP and lake writers, de-identification | CI including `e2e-simple`, goldens and the parity check; the PHI tests when de-identification changes | the site's mapping sample re-run after install, as an automated check |
| **CC3 Interface** | the REDCap connector, the EDC writers, mail grammar, the external API, hub messages | CI; contract tests on the simulator (`services/rc_sim/`) | the round trip against the site's test project, where the site has one |
| **CC4 UI and text** | pages, strings, translations, help | CI; the journey tests; the forbidden-word check | none beyond the release |
| **CC5 Security fix** | a dependency upgrade for an advisory, hardening, an identity or crypto fix | CI including the security scans; may merge ahead of the queue | may ship as its own release (§4) |
| **CC6 Site configuration** | a site's mapping YAML, rule book, settings, the platform partition | the configuration's own checks (`tools/mapping_check.py`, `doctor`); no product release | a change record at the site (the configuration file's history on the box); the mapping sample re-run |

**Significance.** TB-DS-12 §5.1 gives each change a significance A, B or C as well. Under D-311 it drives only which
tests run, never who approves: C (CC1; CC2 when de-identification changes; CC5 when identity, roles, reveal or
crypto change) adds the property, mutation and engine-agreement tests and the adversarial review; B and A do not.

## 3. Release

A release is a tag on `master` with green CI, its `release.json` and its release record
(`release-records/<version>.md`, this folder). The release record lists:

* the version, the commit, the image digests and the qualified model pair;
* every pull request since the last release with its change class;
* the CI results of the tagged commit and the qualification records for any CC1 change;
* the problem-log rows closed and any still open of the blocking kinds (D-311 S5: wrong answer, data loss, security);
* the SOUP changes (`soup.csv`, this folder) and the supplier changes (`supplier-assessments.md`, this folder);
* the PQ steps to repeat at a site, where §0.3 item 2 of TB-PLAN-06 applies (otherwise "none").

A release is blocked only by an open wrong-answer, data-loss or security problem (D-311 S5).

## 4. Staged roll-out

Every MINOR and MAJOR release goes out in three stages. A PATCH that is a CC5 security fix may go to all three on the
same day, in the same order.

| Stage | Where | When | Done when |
| --- | --- | --- | --- |
| 1 | the acceptance box (synthetic hospital) | day 0 | `tools/apply_update.sh` passes; `doctor` all PASS; `e2e-simple` and the canary pass on the box; the restore drill passes for a MAJOR with a migration |
| 2 | the first site in the order of the release record (today CGMH, then Japan: TB-PLAN-05 Q-02) | stage 1 plus three working days | `doctor` all PASS on the site; the canary passes; the night's run published; the morning mail sent; no new blocking problem row |
| 3 | the second site | stage 2 plus three working days | as stage 2 |

Rules:

1. **Stop and roll back.** A failed check at any stage stops the roll-out. An update that fails its own checks puts
   itself back (`docs/RUNBOOK.md` §5, step 5). After an update that passed its checks, the site goes back by applying
   the previous bundle with `tools/apply_update.sh --allow-downgrade REASON` (audited); the backup taken before the
   update is kept until stage 3 is done. The failure is a problem-log row, and the fix is a new release that starts
   again at stage 1.
2. **Who applies an update on site.** The site's administrator (the `admin` role on the box), from the signed bundle
   (`tools/apply_update.sh`, which checks the signature, the release order and the digests before anything changes).
   Where the vendor has no remote access, the vendor sends the bundle and the checklist of this table; the site's
   administrator applies it and returns the `doctor` and canary output, which the vendor files in the release record.
   The vendor never applies an update at a site through an account it does not hold there.
3. **Evidence per stage** is the tool output (`doctor`, canary, update log), filed in the release record with the
   date. There is no sign-off line (D-311).
4. **Configuration (CC6)** does not wait for a release: it follows the site's own change record, with the mapping
   sample re-run.

## 5. Emergency change

A fix for a critical vulnerability or a wrong-answer problem in production may skip the three-day wait: stage 1, then
both sites the same day. Its release record says why. The full checks of its classes still run before it merges.

## 6. What D-311 removed from this procedure

* The change control board, the peer review of CC6 by the engineer and the retrospective review of a fast-tracked
  CC5 within five working days (D-311 B10).
* The sign-off line per roll-out stage proposed in OPS-026 (D-311 B1).
* The native-speaker read of changed strings as a condition of CC4 (D-311 B12); the journey tests stay.
* The site PI's approval of anything that changes outputs of an approved ruleset; the re-approval flag of D-318
  stays as a product feature.
