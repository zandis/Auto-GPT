# The findings register

**Reader:** the people who build TrialBox: every lane, the integrator, and lane R. One row per finding, from every
card and every verification.

This is the one findings register of plan 8 (section 5b, release criterion 11; decision D-1180). What a card or a
verification finds goes here, with a severity, an owning lane and a state. A finding is closed when it is seen closed.
The integrator keeps the register; lane R keeps it honest. The stale problem log (`docs/validation/problems.csv`) and
the older review registers stay as records of what was found then; a finding of theirs that is still open enters
here when a card picks it up.

## Who adds and who closes

- **Adding.** Every card that finds something adds its rows in its own pull request, under one heading for the card.
  A card with a `findings.json` runs `python -m tools.findings_register --add-from <file>` (the form is in the tool's
  opening text). The card's own page stays the full account; a row here is one line that links to it.
- **Closing.** The owning lane proposes the new state in the pull request that does it: `card issued #<pr>` when a card
  is open for it, `fixed <sha>` with the commit that fixes it, or `not a defect: <why>`. Lane R re-checks a fix and
  adds ", seen closed by <who> on <date>". A row is never deleted and an id is never reused.
- **Checking.** `python -m tools.findings_register --check` runs in `make lint` and in CI's `checks` job. It is strict:
  below the first card heading every line must be a card heading, a blank line, a table's header or rule, or a row,
  so a malformed line or row turns the fast tier red and no row can be skipped unseen. A parse error names its line;
  a row error names the line and the id. The sha of `fixed` and the number of `card issued` are checked for their
  form only.
- **The release (criterion 11).** `--check --release` fails while a finding stops the release. A High passes only as
  `fixed <sha>, seen closed by <who> on <date>` or `not a defect: <why>`. A Medium passes only as `fixed <sha>` or
  `not a defect: <why>`: a card issued is not a card done. A Low never stops it. This mode is not in CI.

## The rules of a row

- **Id.** The card and the finding: `<card>-<local>`, where the card is the card's name without its hyphen (H-20 is
  `H20`). Lane V's ids are the card and a number (`V2-07`). A seeded row keeps the id its source gave, after the card
  (lane H's walk F-16 is `H20-F-16`; the install run's `no-host-tree` is `H22-no-host-tree`). A source that gives no
  ids is numbered here in its own order, two digits (`H18-01`). The id must start with its heading's card.
- **Severity.** High: a patient harmed or wrongly excluded, data leaked or not erased, a role doing what the matrix
  forbids, an audit trail that can be wrong, or a box that cannot be installed or restored. Medium: a person slowed or
  misled, or a document's claim not true. Low: wording only. A severity the register mapped from a source's other
  scale says "(mapped)".
- **Basis.** `shown` (a run or a test showed it), `hypothesis` (read from code or text, not run), `not_run`, or
  `not stated` (a seeded row whose source does not say).
- **State.** Exactly one of: `open`; `card issued #<pr>`; `fixed <sha>` (7 to 40 hex), optionally followed by
  ", seen closed by <who> on <date>"; `not a defect: <why>`.
- **Date.** A real calendar date, written YYYY-MM-DD. **Source.** A relative link to a file inside `trialbox/`.
- **Lane.** A2, B2, C2, C2a, C2b, D, E, G, H, W, R, Int or V.

## Counts and merges

The file keeps no counts: run `--counts`. Rows are never sorted. Each card adds under its own heading, and the file
is merged as a union (`.gitattributes`), so rows that two branches append are both kept with no conflict: two cards
appending to one table, to two tables, or each adding a new card at the end of the file.

A state change is different. When one branch changes a row's state and another changes a neighbouring row's state
or appends right after that row (also a new card at the end of the file after the last row), the union keeps both
copies of the changed row and `--check` fails on the id used twice. The integrator then runs
`python -m tools.findings_register --resolve` on the merged tree: when the copies differ only in the state and
exactly one state other than `open` is among them, one row with that state stays where the first copy was. Two
different states other than `open` (two branches that changed the same row), or copies that differ in another cell,
are left for a person. Whether GitHub's merge button reads the union setting is not checked; the trains merge with
git.

## The seeded rows

The first rows (card V-0, D-1180) are the findings of three pages of 2026-11-17, none dropped. Each severity is
mapped by the rule above from what the finding says; the source's own word is not copied.

- H20, lane H's walk of a study's life: its 22 findings (F-20 was settled by H-25 on master, D-1124, and F-22 came with it). Basis `shown`: the page is written from the logs of its three
  runs. "Blocks the step" became High; every other finding is Medium (a person slowed or misled) except the four that
  are wording only (F-02, F-09, F-12, F-19), which are Low. F-10 happens on a test-day box only (`tools/demo.py`
  with `--day data`), which the installer never starts, so it is Medium, not an audit trail that can be wrong.
- H22, the install runbook followed alone: its 12 findings, with the ids of its `findings.json`. "Stops the install"
  became High, "slows the reader" Medium. Basis `shown` where a run saw it, `hypothesis` where the page says "text".
- H18, launch P2b reviewed offline: the page gives no ids and no severity. Its 8 proposed cards are H18-01 to H18-08,
  in the page's order; H18-09 to H18-14 are the other statements of something wrong or unproven in its sections 1 and
  2 and its "Not shown" list. Basis as the page labels it, else `not stated`.

## H20: the life-cycle walk (lane H, 2026-11-17)

| Id | Date found | Source | Severity | Claim | Lane | Basis | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H20-F-01 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | Help on the weekly page tells the coordinator to mark Approach, Need info or Not suitable; the page gives the coordinator no mark | C2 | shown | open |
| H20-F-02 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Low (mapped) | The investigator's mark reads "Approach", and the page then says "Approved": two words for one mark | C2 | shown | open |
| H20-F-03 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | Patients are named by an 8-character pseudonym only, and no testers' page says which patient to take | C2 | shown | open |
| H20-F-04 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | A new study warns that Approach is recorded as an override (no IRB date, no consent-form version), and no step of the new-study walk leads to the IRB record | C2 | shown | open |
| H20-F-05 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | The approved patient is on the list "Approved and contacted" before anyone contacted them, and the list link's name runs into its count | C2 | shown | open |
| H20-F-06 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | The five contact outcome buttons are on the weekly page twice for the approved patient | C2 | shown | open |
| H20-F-07 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | The patient panel shows the screening number, but no link leads from it to the participant's page | C2 | shown | open |
| H20-F-08 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | "Participants" and "Study state and identifiers" are not in the More menu, and neither Help nor the coordinator's guide names them | C2 | shown | open |
| H20-F-09 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Low (mapped) | One participant's page is headed with the list's title "Participants", not with the participant | C2 | shown | open |
| H20-F-10 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | On a test-day box only (tools/demo.py --day data, a frozen clock), the steps TrialBox makes carry the real day and the recorded steps the box's day, so the trail shows consent before approach | C2 | shown | open |
| H20-F-11 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | Withdraw without a reason is refused only after the click, and with a reason one click makes the participant final with no confirmation | C2 | shown | open |
| H20-F-12 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Low (mapped) | In English "Withdraw" names both the participant's withdrawal and taking back a mark | C2 | shown | open |
| H20-F-13 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | After the withdrawal and the close, the patient sheet still offers contact outcomes | C2 | shown | open |
| H20-F-14 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | A new study is never opened, so its type for SAE reporting is never asked; with no state recorded it counts as open | C2 | shown | open |
| H20-F-15 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | Closing a study, which is final, is one click with no confirmation page | C2 | shown | open |
| H20-F-16 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | The "kept until" date is counted from the close's UTC day, one day before the site's day | C2 | shown | open |
| H20-F-17 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | The steward's opt-out form asks for the chart number, and no page of the steward shows one | C2 | shown | open |
| H20-F-18 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | After the withdrawal the patient is on no weekly list but the paged "All on the list", and the participant's page has no link to the patient sheet | C2 | shown | open |
| H20-F-19 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Low (mapped) | The opt-out form's note is labelled "Note for the coordinator" on the steward's register | C2 | shown | open |
| H20-F-20 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | High (mapped) | The opt-out worker never ran on the steps-mode box, so none of the erasure registry's clears ran after an opt-out | Int | shown | fixed 09b26e8ca |
| H20-F-21 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | The red opt-out worker check is on the metrics page only; the administrator's Health tab shows no line for it | C2 | shown | open |
| H20-F-22 | 2026-11-17 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium (mapped) | The audit trail shows each run of the opt-out worker with an empty detail, so a steward cannot see on any page that an erase completed | C2 | shown | open |

## H22: the install runbook followed alone (lane H, 2026-11-17)

| Id | Date found | Source | Severity | Claim | Lane | Basis | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H22-no-host-tree | 2026-11-17 | [runbook-install-2026-11-17.md](../plan/measurements/runbook-install-2026-11-17.md) | High (mapped) | The one command runs from /opt/trialbox, but nothing in the runbook puts the release's host tree there, so deploy/install.sh is not found | D | shown | open |
| H22-vendor-key-after-start | 2026-11-17 | [runbook-install-2026-11-17.md](../plan/measurements/runbook-install-2026-11-17.md) | High (mapped) | The installer needs the vendor key in its first step, but section 1 places the key at step 6, after the start | D | shown | open |
| H22-stub-fragment-vs-tier | 2026-11-17 | [runbook-install-2026-11-17.md](../plan/measurements/runbook-install-2026-11-17.md) | Medium (mapped) | "--mode stub installs a box without a GPU", but added to the one command the installer refuses it beside --tier; only its own message says to drop the tier | D | shown | open |
| H22-bundle-sidecar-path | 2026-11-17 | [runbook-install-2026-11-17.md](../plan/measurements/runbook-install-2026-11-17.md) | High (mapped) | The bundle's .sha256 names the vendor's --out path, so the installer's check on the stick fails with a checksum mismatch | D | shown | open |
| H22-stub-production-embedder | 2026-11-17 | [runbook-install-2026-11-17.md](../plan/measurements/runbook-install-2026-11-17.md) | High (mapped) | A PRODUCTION box without a GPU does not become healthy: embed-service refuses with no pinned embedder, and the installer pins models only in GPU mode | D | shown | open |
| H22-unmentioned-questions | 2026-11-17 | [runbook-install-2026-11-17.md](../plan/measurements/runbook-install-2026-11-17.md) | Medium (mapped) | The installer asks questions at a terminal (start now, and answers the file lacks) that section 1 never names | D | hypothesis | open |
| H22-host-packages-unnamed | 2026-11-17 | [runbook-install-2026-11-17.md](../plan/measurements/runbook-install-2026-11-17.md) | Medium (mapped) | Step 1 does not name the compose plugin, python3 with PyYAML, curl and cron that the installer needs | D | hypothesis | open |
| H22-site-folder-place-unstated | 2026-11-17 | [runbook-install-2026-11-17.md](../plan/measurements/runbook-install-2026-11-17.md) | Medium (mapped) | Section 1 does not say where the site's folder (the answers file and the mapping) goes | D | hypothesis | open |
| H22-feed-folder-content-unstated | 2026-11-17 | [runbook-install-2026-11-17.md](../plan/measurements/runbook-install-2026-11-17.md) | Medium (mapped) | Section 1 does not say that the feed folder must hold an export before the one command, nor who puts it there | D | hypothesis | open |
| H22-python-not-python3 | 2026-11-17 | [runbook-install-2026-11-17.md](../plan/measurements/runbook-install-2026-11-17.md) | Medium (mapped) | Step 4 runs python, which Ubuntu 24.04 does not have; the tool also needs the release's Python packages and libs/ on the path, which step 1 does not name | D | hypothesis | open |
| H22-compose-cwd-unstated | 2026-11-17 | [runbook-install-2026-11-17.md](../plan/measurements/runbook-install-2026-11-17.md) | Medium (mapped) | Step 7's docker compose exec finds no project from /opt/trialbox; the working form needs --project-directory deploy | D | hypothesis | open |
| H22-ingest-report-in-volume | 2026-11-17 | [runbook-install-2026-11-17.md](../plan/measurements/runbook-install-2026-11-17.md) | Medium (mapped) | Step 7's ingest report is inside the lake's volume, and section 1 does not say how to read it | D | hypothesis | open |

## H18: launch P2b reviewed offline (lane H, 2026-11-17)

| Id | Date found | Source | Severity | Claim | Lane | Basis | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H18-01 | 2026-11-17 | [p2b-review-2026-11-17.md](../plan/measurements/p2b-review-2026-11-17.md) | High (mapped) | An exclusion compiled to a sex alone ("women with pregnant or lactation") excluded an eligible woman at S1 with no model asked; the same shape excluded two more sigir women, both gold "would consider" | A2 | shown | fixed 0ee24331a |
| H18-02 | 2026-11-17 | [p2b-review-2026-11-17.md](../plan/measurements/p2b-review-2026-11-17.md) | Medium (mapped) | D-958's sentinel quote date rule was not on SCREEN's own judge path, so 3 of 107 protocols failed in screen judging | A2 | shown | fixed f549bfb8b |
| H18-03 | 2026-11-17 | [p2b-review-2026-11-17.md](../plan/measurements/p2b-review-2026-11-17.md) | High (mapped) | "Older than N years" compiles to a minimum age of N+1, which excluded a patient of 15 years and 8 months that the label calls eligible; whether the rule or the label is wrong is open | A2 | hypothesis | open |
| H18-04 | 2026-11-17 | [p2b-review-2026-11-17.md](../plan/measurements/p2b-review-2026-11-17.md) | Medium (mapped) | JMED's two condition lines now compile structured, so with no coded diagnoses S3 judged 0 pairs and each protocol left 263 verdicts unknown; jmed's 0 of 330 is no result | A2 | not stated | open |
| H18-05 | 2026-11-17 | [p2b-review-2026-11-17.md](../plan/measurements/p2b-review-2026-11-17.md) | Medium (mapped) | No tool prints the target-1 figure three ways, with the age-line class apart from D-1064's six conflicted pairs, as the integrator ruled | H | not stated | open |
| H18-06 | 2026-11-17 | [p2b-review-2026-11-17.md](../plan/measurements/p2b-review-2026-11-17.md) | Medium (mapped) | An age line the benchmark key wrote excludes a pair its physicians labelled eligible (sigir-201422 with NCT00236912) | H | shown | open |
| H18-07 | 2026-11-17 | [p2b-review-2026-11-17.md](../plan/measurements/p2b-review-2026-11-17.md) | Medium (mapped) | The replay reads stored judge replies through the gateway judge, not the box's path, so level (b) shows the 3 failed protocols as cause gone | H | shown | open |
| H18-08 | 2026-11-17 | [p2b-review-2026-11-17.md](../plan/measurements/p2b-review-2026-11-17.md) | Medium (mapped) | No stored set records the build day, so the replay found no index day and did not run level (b); the source names lanes H and G (the driver) | H | shown | open |
| H18-09 | 2026-11-17 | [p2b-review-2026-11-17.md](../plan/measurements/p2b-review-2026-11-17.md) | Medium (mapped) | The key may be wrong on sigir-20154 with NCT01701453: the box excluded on the target-lesion line, which no gold row judges, and the physicians labelled the pair eligible | H | hypothesis | open |
| H18-10 | 2026-11-17 | [p2b-review-2026-11-17.md](../plan/measurements/p2b-review-2026-11-17.md) | Medium (mapped) | Two tcga verifier replies (TCGA-AZ-5403, TCGA-RC-A6M4) are no JSON: they run on until cut off, twice, and are the run's 2 judging failures | A2 | shown | open |
| H18-11 | 2026-11-17 | [p2b-review-2026-11-17.md](../plan/measurements/p2b-review-2026-11-17.md) | Medium (mapped) | PoC-1's record keeps counts only, so the 5 pathology reports that moved from 384 to 379 excluded cannot be named; their cause, the pair's run-to-run difference, is a hypothesis | H | shown | open |
| H18-12 | 2026-11-17 | [p2b-review-2026-11-17.md](../plan/measurements/p2b-review-2026-11-17.md) | Medium (mapped) | The product's quote check on tcga is not shown: the 42 verifier quotes not found are the trace's own whitespace-and-case match, against the run's 45 disagreements | H | not_run | open |
| H18-13 | 2026-11-17 | [p2b-review-2026-11-17.md](../plan/measurements/p2b-review-2026-11-17.md) | Medium (mapped) | The stored sets keep no serving settings (the answer's token budget), so what the 2 cut-off tcga verifier replies would have said is not known | H | not_run | open |
| H18-14 | 2026-11-17 | [p2b-review-2026-11-17.md](../plan/measurements/p2b-review-2026-11-17.md) | Medium (mapped) | Level (b) of the 3 failed protocols' SCREEN was not run: it needs the models, and the stored replies cover only the questions asked | H | not_run | open |

## V3: the ASVS Level 2 checklist (lane V, 2026-11-17)

| Id | Date found | Source | Severity | Claim | Lane | Basis | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V3-01 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | Behind Caddy every browser shares one address, so five wrong guesses lock a named person out on every PC. | D | shown | open |
| V3-02 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | The session cookie has no __Host- prefix. | C2 | shown | open |
| V3-03 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | A person cannot see or end their other sessions, and a new sign-in leaves older ones alive. | C2 | hypothesis | open |
| V3-04 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | A break-glass grant opens on the session alone, with no fresh password or code. | C2 | shown | open |
| V3-05 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | A password longer than 256 characters is accepted when chosen and never signs in. | C2 | shown | open |
| V3-06 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | A password history of five is enforced, which ASVS 2.1.10 says not to do. | C2 | shown | open |
| V3-07 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | In PRODUCTION no breached-password check runs unless the operator supplies the list; nothing warns. | D | hypothesis | open |
| V3-08 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | The password fields have no strength meter and no show-password control, and refuse spaces at the ends. | C2 | hypothesis | open |
| V3-09 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | Password hashes have no secret pepper. | C2 | hypothesis | open |
| V3-10 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | Local accounts cannot use a security key; only directory accounts can (through Authelia). | C2 | hypothesis | open |
| V3-11 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | The holder is not told of a replayed code, of their own password change or of a new sign-in. | C2 | hypothesis | open |
| V3-12 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | Sign-out removes the session cookie without the flags it was set with. | C2 | shown | open |
| V3-13 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | Database, mail and KEK passwords are environment variables; the TOTP key is a plain file in the console volume. | D | hypothesis | open |
| V3-14 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | High | A chart number typed in free text reaches the audit in clear, and the audit is never erased. | C2 | shown | open |
| V3-15 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | A service not listed in CALLERS accepts any service's token. | D | hypothesis | open |
| V3-16 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | No threat model is on file. | D | hypothesis | open |
| V3-17 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | A password an administrator resets never expires until it is used. | C2 | hypothesis | open |
| V3-18 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | High | Changes are stored before their audit event is written, so an audit write that fails (AuditFull when the audit volume is low, AuditAnchorBroken when the chain's head does not match) leaves the change done and unaudited. | C2 | shown | open |
| V3-19 | 2026-11-17 | [asvs-l2-checklist-2026-11-17.md](../plan/measurements/asvs-l2-checklist-2026-11-17.md) | Medium | A typed mark note stays in the tab's session storage after sign-out and is put back for the next person who opens that patient in that tab. | C2 | hypothesis | open |
