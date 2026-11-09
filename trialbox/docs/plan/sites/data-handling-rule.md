# Data-handling rule for site data during the build and the pilot (TB-SITE-03)

| Field | Value |
| --- | --- |
| Document ID | TB-SITE-03 |
| Version | 1.0 (2026-11-09) |
| Owner | Changfu Kuo (Aimedics) |
| Applies to | every person and every agent session that works on TrialBox; both pilot sites; every environment (developer machines, cloud build sessions, CI, the acceptance box, the hospital's hardware) |
| Decided by | the owner, 2026-11-09, after the independent plan review: "Pseudonymised samples only, after the DPA is signed and where the IRB allows it. Real data never goes into the repository, CI, logs, screenshots or review documents." |
| Referenced by | TB-PLAN-05 §9.5, WS-13.10, RSK-39, TST-SEC-10; the site survey (TB-SITE-01) §A.1 and question 37; the IT security pack (TB-SITE-02) §A.10; the IRB amendments (TB-SITE-04, TB-SITE-05) |

## 1. The rule

1. **Real patient data stays on the hospital's hardware.** Data of class D3 (pseudonymised patient data) and D4 (identified) is processed only on the site's own appliance, the site's shared GPU server or the site's approved private cloud. It never leaves the hospital. Aimedics never holds it.
2. **No agent session, repository, worktree, CI job, log, ticket, screenshot or review document ever receives real patient data.** Build agents work from synthetic data and from the site's *schema and code lists* (table headers, code masters, the lab table, encodings), which the survey asks for without any data.
3. **A real sample is read only on the site's hardware, by the site's steward or with the steward present, after the DPA (or the short-form data-processing letter for the sample) is signed and only where the IRB approval covers it.** The sample is pseudonymised at the door by the adapter. Only the adapter's report leaves the site: counts, unmapped codes, parse errors, field coverage. No values, no text, no identifiers.
4. **Screenshots and reports** that leave the site come from the synthetic practice site or carry only aggregates. The complete-run screenshots are of synthetic data.
5. **Fixtures and tests** are synthetic or public (the licensed public datasets listed in `docs/DATA.md`). A fixture that looks like a site record is refused at review.
6. **Exports** that leave a study team follow the k = 5 rule and the export ledger; exports that leave the hospital follow the consortium floor (project pseudonyms, date shift, k = 5, no quotes, no vectors) under an IRB approval and a data-sharing agreement.
7. **An incident** (real data found in a repository, a log, a ticket, a screenshot or a session) is reported the same day to the steward and the privacy office under the incident plan, the artefact is removed and its history purged, and the event is recorded in the release record.

## 2. Controls that enforce it

| Control | What it does | Where |
| --- | --- | --- |
| CI identifier scan | every pull request and every nightly build runs a scan of the repository and of the test logs for chart-number patterns, Taiwan ID and マイナンバー check digits, insurer numbers, the sites' code systems (local lab codes, local diagnosis codes once the survey names them), phone numbers and Japanese or Chinese name patterns beside a date of birth; a hit fails the build | TB-PLAN-05 WS-13.10, TST-SEC-10 |
| Pre-commit and `.gitattributes` | the same scan before a commit; data file types (`.csv`, `.xlsx`, `.ndjson`, `.duckdb`, `.parquet`, `.hl7`) outside `tests/fixtures/` and `eval/` are refused | WS-13.10 |
| Agent instructions | every agent brief carries this rule; an agent that is handed anything that looks like real data stops and reports | WS-13.10, `CONTRIBUTING.md` |
| Sample-handling procedure on site | the steward runs `adapter read --report-only` on the site's hardware; the report is checked by the steward for values before it is sent; the sample stays in the site's data folder and is deleted or kept per the retention table | WS-10.2, WS-11.2, §3 below |
| Log scrubbing | the PHI scrubber on every service log; exception text redacted; the trace store 7 days in PRODUCTION | WS-13.3 |
| Support bundle | `trialbox support-bundle` never includes `/data`, HAPI or Postgres logs; it is scanned for identifiers before it leaves | WS-17.4 |
| Audit | every read of site data on the hospital's hardware is in the audit chain, including the steward's sample reads | WS-13.4 |
| Risk and test | RSK-39 "site data reaches a build agent, the repository or a log"; TST-SEC-10 proves the scan catches planted identifiers and fails the build | TB-PLAN-05 §6, §8 |

## 3. Sample-handling procedure (the 10-patient sample and the OQ sample)

1. The DPA, or the short-form data-processing letter for the sample, is signed. The IRB approval or amendment covers the use.
2. The steward selects the sample on the hospital's system (10 patients for mapping; a different 10 to 20 for OQ; 100 charts per site for the accuracy dry run under the PQ protocol).
3. The adapter reads the sample on the site's hardware with `--report-only` (or the full read into the site's own data folder). Pseudonyms are made at the door; identifiers never pass the adapter.
4. The steward reads the report (counts, unmapped codes, parse errors, coverage) and confirms it carries no values or text. Only then is the report sent to Aimedics (by the hospital's mail or shared folder, not by an agent session).
5. Agents work from the report and from the site's schema and code lists. Mapping changes are tested on the synthetic hospital built from the site's schema, then applied on the site's hardware by the steward and re-read.
6. The sample's retention follows the site's retention table; the OQ sample and the dry-run charts are the site's own records and stay on its hardware.

## 4. What this changes in the plan

The W3 "10-patient samples read" line and every "agent (reader)" owner on a site sample are replaced by "steward reads on site; the report leaves". The plan's schedule carries the DPA signature before the first sample. The survey asks for schema and code lists without data (questions 24 to 26, 32) and for the sample date under the agreement (question 37). The IT pack §A.10 states this rule in the answer to "Does patient data leave the hospital?" and discloses that AI agents are used in developing the software and never see hospital data.
