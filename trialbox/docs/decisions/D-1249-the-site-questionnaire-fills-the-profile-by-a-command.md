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
2. **It writes and never loads.** The files are built beside `--out` and read back by the real loader
   (`tb_common.site_profile.load`). Only then is `--out` made, and the checked files are written into it as new
   files. If a folder of that name appeared meanwhile, nothing is replaced and the command refuses. Folders are
   `0755` and files `0644`. A disk that refuses, or Ctrl-C, leaves nothing and gives one line, never a traceback.
   Loading stays D-1233's path, with its versions, audit and refusals.

   The command refuses an existing folder, a folder above that is a file or not writable, and any folder inside a
   site mapping folder it knows: those named by `TB_MAPPING_DIR` in the shell that runs it, the mount
   `/etc/trialbox/mapping` (whatever `TB_MAPPING_DIR` says), `deploy/site/mapping`, and the image's mapping folder.
   **Its limit:** a mapping folder mounted elsewhere, and not named by that shell's `TB_MAPPING_DIR`, is not known to
   it. `--check-only` prints the refusals and the summary, and writes nothing.
3. **Every answer is text; validation by allow-list.** The answers file is parsed once, by a YAML reader that builds
   no number, boolean or date. Each typed answer is accepted by one pattern of its own:
   - a factor: a plain decimal above 0 and at most 1000;
   - a version: whole numbers without a leading zero;
   - a date: an ISO day;
   - `synthetic`: exactly `true` or `false`.

   An answer is accepted only when it is recognised:
   - a key of the form;
   - a name from a list: a country, a door, an SS-MIX2 data type or a source table, a standard, a master, a category,
     a kind of result, a UCUM unit of `tb_common.labunit`;
   - a value of a fixed shape: a profile name, a site code, a version, a date, a local code, a YJ code, a standard
     code checked as the loader checks it, a LOINC answer code.

   **Answers must also go together.** One table, `GOES_WITH`, holds the doors, standards and each code table's
   masters, by the source type a country's site reads. The form names no country: it asks the site's set-up
   defaults (`tb_common.site_country.defaults`) for the country's source type, which a country with a layer reads
   from it (10C-25, D-1250: P14 `data_source_type`), by the same call for every country. An answer outside the row
   is refused with both answers named. The form makes profiles for the countries whose source type has a row (`jp`
   and `tw` today) and says why for the others (`us`, `other`). A country whose layer cannot be used is refused
   (`country_layer`) and nothing is assumed, never another country's row. The words left (the standard name
   `jp_core`) are data labels, pinned in the Japan guard's table (`tests/unit/test_japan_profile_layer.py`).

   Every other answer is refused, with a message in en, ja and zh-TW from the console's catalogue
   (`profileform.err.<code>`). The message gives the answer's key, its line and its length, and says what is
   expected. It never repeats what the answer said.

   **Which refusals come at once.** The ones found in the parsed answers come together, also inside a coded result's
   answers. A file that cannot be read as plain YAML (not YAML, an alias, a key written twice, a key that is not
   text, a second document, over 5 MB, nested deeper than 16 levels) is refused alone, because nothing after it can
   be read. The nesting bound is checked while the file is read, from the parser's events, so a 5000-deep file is
   refused as not a form instead of exhausting the stack.
4. **Units are checked, not assumed.** A quantity needs its unit; a coded result has none.
   - Same unit, or no source unit: the factor is 1, as the engine reads such a row.
   - Different units: the factor must be given. Where `tb_common.labunit.conversion` knows the pair, the factor must
     agree with it. Where it does not, the row is `verify` whatever the answer said.
5. **No free text unescaped, no path or name from an answer.** A name or display is printable text: 1 to 120
   characters, starting with a letter, a digit or a bracket, with no control or format character and nothing like a
   web address with a password. It goes to the CSV through the csv module. The manifest holds none of it. The tables
   are always `codes/diagnosis.csv`, `codes/drug.csv` and `codes/lab.csv`. A table's `source` is built from the
   form's own words, a master from the list and a checked date. The template says that no patient data goes in the
   form; the form does not look for it.

   **An unchecked mapping stays unchecked.** A row is `verified` only when its answer says exactly `verified`. A row
   with no state is `verify`, as D-1233 stores a row nobody checked; an empty state is refused. Whether a fact
   resting on such a row may exclude a patient stays the owner's open question (DATA §15). This decision does not
   touch it.

   **Every default is said.** The template and the summary the command prints say what the form decided for an
   answer left out: state, factor, source unit. Version and `synthetic` have no default.
6. **The mapping of questions to fields** is data (`site_questionnaire.QUESTIONS`): each question names the profile
   field it fills, or says why it fills none. The manifest fields no question fills are asked of the steward in the
   form's header: `format`, `id`, `site_id`, `country`, `version` and `synthetic`.

## Consequences

- The form fills a profile for the repository's synthetic Japanese hospital
  (`tests/fixtures/site_questionnaire/synthetic-jp-ss.answers.yaml`). That profile passes the loader, the mapping
  check and `activate`, and it reads every code to the same standard code as the shipped sample tables, every row
  still `verify` (`tests/unit/test_site_questionnaire.py`). Its two joint counts have the unit `1` where the shipped
  table leaves it empty: a quantity needs its unit.
- The lane lead's independent review of the first version found answers that validated and activated but said
  something other than what was written: YAML number forms, a missing factor between two units, and answers that do
  not go together. Points 2 to 5 are the fix, each rule with a test that fails without it.
- A console page for the questionnaire is not built. It would widen what an account may do, and it is with the owner.
- 用法 (10B-4), document types and templates (10B-5, 10B-15), departments (settings) and the character set (settings)
  have no profile field yet. Their questions are listed as filling none until those cards add the field.
