# D-1249 The site questionnaire fills a site profile through a command that writes and never loads

- **Task:** card 10B-19 of plan 10 (`docs/plan/47-plan-10-2026-11-18.md`, Track B; review card 12-21,
  `docs/reviews/2026-11-root/12-ssi-data.md` section 9)
- **Date:** 2026-11-19
- **Status:** accepted; the number is reserved for this card's pull request (lane J's block D-1220 to D-1319)
- **Builds on:** D-1233 (a hospital is a site-profile folder; one loader; only a version a person loaded is applied),
  D-135 (a local code mapped once), D-367 (the site folder survives updates), D-1220 (one text catalogue)
- **Design:** `docs/data/15-the-site-profile.md`, section "The questionnaire form"

## Context

D-1233 made a hospital's habits one versioned folder, but the folder was hand-written. The plan's row 10B-19 asks
for the site questionnaire as a site-setup form that fills it. The questionnaire is review 12 section 9: 9.1, thirty
questions for the hospital's IT, and 9.2, the sample exports to ask for. (`docs/plan/sites/site-survey.md` is
another survey, TB-SITE-01's, for a site mapping; it is not the one the review means.)

No site-setup page managed the profile: D-1233 left it to commands on the box (`check`, `load --by`, `unload`,
`worklist`). A console page would have been a new route, with a new writer of code tables the night reads once they are
loaded. Under lane J's rule that nothing may widen what a role may do, the card stopped and the lane lead ruled.

## Decision

1. **A command, not a page.** `python -m adapter.site_profile fill --answers <answers.yaml> --out <new folder>`
   (`services/adapter/site_questionnaire.py`). Only the people who can run `load` on the box can run it. There is no
   route, no new role, no permission row and no new reader of existing data. `fill --template --lang <en|ja|zh-TW>`
   prints the answers file to fill, with its questions as comments.
2. **It writes and never loads.** The folder is built beside `--out`, read back by the real loader
   (`tb_common.site_profile.load`), and only then renamed into place. Loading stays D-1233's path, with its
   versions, audit and refusals. The command refuses an existing folder and any folder inside a site mapping folder the
   box reads (`TB_MAPPING_DIR`, the mount, `deploy/site/mapping`) or the image's mapping folder. `--check-only`
   prints the refusals and writes nothing.
3. **Validation by allow-list.** An answer is accepted only when it is recognised:
   - a key of the form;
   - a name from a list: a country, a door, an SS-MIX2 data type or a source table, a standard, a master, a category,
     a kind of result, a UCUM unit of `tb_common.labunit`;
   - a value of a fixed shape: a profile name, a site code, a version, a date, a local code, a YJ code, a standard
     code checked as the loader checks it, a LOINC answer code;
   - a bounded number (a factor above 0 and at most 1000).

   Anything else is refused with a message in en, ja and zh-TW from the console's catalogue
   (`profileform.err.<code>`). The message names the answer and says what is expected. Every refusal is reported at
   once, not only the first.
4. **No free text unescaped, no path or name from an answer.** A name or display is printable text: 1 to 120
   characters, starting with a letter, a digit or a bracket, with no control or format character. It goes to the CSV
   through the csv module. The manifest holds none of it. The tables are always `codes/diagnosis.csv`,
   `codes/drug.csv` and `codes/lab.csv`. A table's `source` is built from the form's own words, a master from the
   list and a checked date. The answers file is read without aliases and without a key written twice, and is at most
   5 MB.
5. **An unchecked mapping stays unchecked.** A row is `verified` only when its answer says exactly `verified`. A row
   with no state is `verify`, as D-1233 stores a row nobody checked. Whether a fact resting on such a row may exclude
   a patient stays the owner's open question (DATA §15). This decision does not touch it.
6. **The mapping of questions to fields** is data (`site_questionnaire.QUESTIONS`): each question names the profile
   field it fills, or says why it fills none. The manifest fields no question fills are asked of the steward in the
   form's header: `format`, `id`, `site_id`, `country`, `version` and `synthetic`.

## Consequences

- The form fills a profile for the repository's synthetic Japanese hospital
  (`tests/fixtures/site_questionnaire/synthetic-jp-ss.answers.yaml`). That profile passes the loader, the mapping
  check and `activate`, and it reads every code to the same standard code as the shipped sample tables, every row
  still `verify` (`tests/unit/test_site_questionnaire.py`).
- A console page for the questionnaire is not built. It would widen what an account may do, and it is with the owner.
- 用法 (10B-4), document types and templates (10B-5, 10B-15), departments (settings) and the character set (settings)
  have no profile field yet. Their questions are listed as filling none until those cards add the field.
