# QMS-lite: how the quality records are kept

*Card T-215 (deep review CR-096 QMS-lite part, REG-027, REG-030; TB-ASSESS-01 WS-12.1). Decision D-344. Status:
living. No signature, no approver and no committee: D-311 removed every development gate.*

This is the quality system for the pilot. It is light on purpose: every record is written by the pull request or the
tool that does the work, and CI checks what can be checked. It is the description a hospital or a sponsor files as
the vendor's quality system (the "vendor assessment pack", §6).

## 1. Document control

| Kind | Where | Controlled by |
| --- | --- | --- |
| The eight documents | `README.md`, `docs/ARCHITECTURE.md`, `docs/RUNBOOK.md`, `docs/SECURITY.md`, `docs/DATA.md`, `docs/VALIDATION.md`, `docs/USER_GUIDE.md`, `docs/DECISIONS.md` (D-139) | git history; `tools/doclint.py` in CI |
| Decisions | `docs/decisions/D-nnn-<slug>.md` and `docs/decisions/REGISTRY.md` (D-306) | `tools/decisions_index.py --check` in CI |
| Plans and design | `docs/plan/`, `docs/plan/design/` | git history |
| Validation records | `docs/validation/` (layout: `README.md`, this folder) | git history; the tests of `tests/unit/test_validation_records.py` |
| Reviews | `docs/reviews/` | git history; a review is never edited after it is merged |

A document's version is its git commit. A document that states a version number in its header changes it in the same
pull request as the content. Nothing is controlled outside the repository, except the site's configuration on the
box, whose history the box keeps.

## 2. Records and who writes them

| Record | Where | Written by |
| --- | --- | --- |
| Change record | the pull request, with its change class | the author of the change (`change-control.md`, this folder) |
| Release record | `release-records/<version>.md` (this folder) | the release step |
| Problem log | `problems.csv` (this folder, T-654) | whoever finds the problem; closed by the fix PR with its test |
| SOUP list | `soup.csv` (this folder, T-654) | the PR that adds or upgrades a component |
| Supplier assessments | `supplier-assessments.md` (this folder) | the PR that adds a supplier or changes what it supplies |
| Model qualification | the qualification record of `trialbox eval qualify` (D-313) | the qualify command |
| Training | §3 | the person trained, or the tool |
| Periodic review | the next release record | the release step |

## 3. Training records

Training is recorded where it happens:

* **Site users** (PI, CRC, steward, administrator): the role guide read and the first sign-in, from the box's audit
  chain (the account's first sign-in and the acknowledgement event). A list per site is read from the audit chain
  when a site or sponsor asks; a page that exports it is not built yet.
* **Agent sessions** (the developers of TrialBox): the brief and the card each session works from are in the pull
  request; a session's training is its card and the documents its card says to read first.
* **People on the vendor side** who apply an update or answer support: one line in the release record per person and
  release ("read `change-control.md` §4 on <date>"). No signature.

## 4. Evidence that survives a sponsor audit

A number or a claim used as validation evidence follows these rules (REG-030):

1. **Raw first.** A gate figure is reported as measured. An adjusted figure (for example the N-12 audit adjustment,
   which rests on a sampled label check by an AI assistant, not a clinician: `docs/VALIDATION.md`) is a note beside
   the raw figure, never the gate figure, until a qualified person repeats the label sample.
2. **Data named.** Every figure names its data: synthetic, public (with the source and version) or real (only under
   TB-PLAN-06 §0.3). Synthetic and public figures are not real-data accuracy.
3. **Independent test sets.** A set used for tuning is never the set that reports the result; the qualification
   record names both.
4. **Reproducible.** The figure names the commit, the build hashes and the command that made it.
5. **Attributable.** The record says which tool or which session produced it and when; a human-entered value names
   the person.
6. **Not reconstructed.** A record is written when the work is done, by the pull request or the tool, not afterwards.

## 5. Problem resolution

The problem log is `problems.csv` (this folder, card T-654). The deep review's register rows (TB-REG-01 and the
2026-11-10 deep review) stay where they are; a row enters the problem log when a card picks it up. Deviations and
corrective and preventive actions follow VMP §6 (`docs/plan/25-vmp.md`).

## 6. The vendor assessment pack

What a hospital or a sponsor receives, on request, for its own supplier file:

1. this page and `docs/plan/25-vmp.md`;
2. `standards-position.md` and `software-safety-classification.md` (this folder);
3. `development-plan.md` (this folder): how a change is made and checked;
4. the release record of the release they run, with its SBOM and `soup.csv`;
5. `change-control.md` (this folder) and the incident procedure (card T-318);
6. the test summary: the CI results of the tagged commit and the qualification record of the model pair.

## 7. Periodic review

Six-monthly after the first site goes live, and after any incident: the problem log, the drift chart, the
qualification records, the SOUP advisories, the supplier list and the open changes. The outcome is a section of the
next release record. No signer (D-311).

## 8. Removed by D-311

Signed lifecycle records (B14); the change control board and named reviewers (B10); reviewer hours per pull request
as a record (TB-ASSESS-01 WS-12.1; it measured a human review that no longer exists); approval of the URS and the FS
list by named people.
