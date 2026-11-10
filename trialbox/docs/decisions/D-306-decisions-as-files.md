**D-306 Decisions are files with numbers from one registry; the safety core has code owners; generated files are
regenerated, never hand-merged.** Task T-002 of TB-PLAN-06 (`docs/plan/28-master-plan-v6.md` §6.1 rules 3, 4 and 9,
§6.2.3) and of TB-ASSESS-01 (`docs/reviews/2026-11-09-assessment-and-tasks.md` §3.1; WS-17.5, WS-12.1; RSK-14,
RSK-29). Closes CR-077 and the file part of CR-080; helps PLAN-033 and PLAN-024. Branch
`agent/T-002-decisions-registry`. Date: 2026-11-10.

*The problem.* Every branch appended its decision to the end of `docs/DECISIONS.md`, so any two branches conflicted
there; numbers were taken by guess, so D-201 and D-205 were each claimed twice and D-191 was cited before it was
written (CR-077). The generated contract models carried a digest of all schemas on line 2, so any two branches that
each added a schema conflicted there too (PLAN-033). The safety core had no code owner (CR-080).

*Decisions.* One decision is one file `docs/decisions/D-<nnn>-<slug>.md`; its first line names the number, its
opening names its card. `docs/DECISIONS.md` is frozen at D-270 and takes no new entry. Numbers come from
`docs/decisions/REGISTRY.md`, one row per number or range, with a state (`merged`, `reserved`, `unused`, `missing`)
and a holder. The integrator writes the row before the branch is cut; a card's pull request never edits the
registry, and a file may land under a `reserved` row, so two pull requests never touch the same line. New numbers
start at D-300; D-270 to D-289 stay with the critical-issues fix groups; the reservations D-208 to D-262 of
TB-ASSESS-01 stay valid and D-190 to D-207 are void (the numbers on master stay). Every number from D-01 to the top
of the registry has a row: the gaps are marked `unused`, and D-99, cited in code but never written, is `missing`.

*The check.* `python -m tools.decisions_index --check` runs in CI job `docs`. It fails on a number written twice (in
the log, in two files, or in the log and a file), a decision file with no row, a file name and first line that
disagree, a new entry in the frozen log, a `merged` row without text or an `unused` or `missing` row with text, a
number no row covers or two rows cover, and a file under a row that names a card when the file does not. The index
with titles is printed by `python -m tools.decisions_index` and never committed: a committed index would be one more
file every decision branch edits.

*Generated files.* `libs/tb_contracts/generated/models.py`, `docs/plan/25-traceability.csv`, the goldens and the
decisions index are regenerated, never hand-merged: on a conflict, take master's copy, run the generator, commit.
`trialbox/CONTRIBUTING.md` says so, and the CI jobs `contracts`, `trace`, `goldens` and `docs` fail when a committed
file differs from its generator. `tools/gen_contracts.py` no longer writes the schemas digest into the header; its
`--check` compares the whole file, so nothing is lost, and two branches that each add a schema now merge cleanly
(`tests/unit/test_decisions_index.py` merges two such branches).

*Code owners.* `.github/CODEOWNERS` makes the owner the owner of everything and lists the safety-core paths
(matching and the cascade, the criteria engines, the guard, authz and sign-in, the prefill path, the audit trail, the
pseudonym map, lab values) on their own lines. The human safety-core reviewer is not named: naming them is owner
action OD-9, and until then those lines name the owner alone. Branch protection that requires code-owner review is
the owner's setting (ENG-005).

*Licence.* Not decided. `pyproject.toml` says "Proprietary"; the root `LICENSE` is the host project's MIT licence
and does not cover `trialbox/`. TB-ASSESS-01 says the owner names the licence and a placeholder is refused, so no
`trialbox/LICENSE` is written; it is an open owner item.

*Consequences.* A decision branch adds one new file and nothing else in the decision area, so decision files never
conflict. Open pull requests that still append to the log (PR #80, D-180) or reuse a number held on master (PR #75's
D-201, PR #82's D-204 and D-205) fail the check until they become files under their registry numbers.

*Evidence.* `tests/unit/test_decisions_index.py`: master passes; a duplicate across the log and a file, two files on
one number, a file with no row, an unmarked gap, a new log entry, a file that does not name its card and a bad file
name each fail; two files in different ranges pass; two throw-away branches that each add a decision file and a
contract schema merge with no conflict and pass both checks.
