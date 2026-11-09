# TrialBox user guide

*Owner: Product owner. Status: living; changed in the same pull request as the code it describes. History: the git log of this file; the merge into eight documents is D-139.*

For the people who use the console: investigators (PI), coordinators (CRC), administrators, CRO specialists and
viewers. The console speaks Japanese, Traditional Chinese and English; this page is in English and points to the help
in each language. Setting up the box is in the [Runbook](RUNBOOK.md).

## 1. Help in your language

| Where | What | ja | zh-TW | en |
| --- | --- | --- | --- | --- |
| the **?** in every page header (`/help`) | help for the page you are on, your role, examples for the command field, the site contact | yes | yes | yes |
| **Ask TrialBox** (`/ask`) | "what next?" and "why is this patient here?", answered from the box's own data, read only | yes | yes | yes |
| Site set-up, **Templates and practice** (`/site/help`) | templates and a practice site to try things safely | yes | yes | yes |
| the language menu (More → language) | switches every page, mail and export | 日本語 | 繁體中文 | English |
| network, port and secret sheet (for hospital IT) | one printed page | `docs/handover/network-sheet.ja.md` | `docs/handover/network-sheet.zh-TW.md` | `docs/handover/network-sheet.en.md` |

The words are one plain vocabulary per idea, the same on every page (D-133). Some of them:

| English | 日本語 | 繁體中文 |
| --- | --- | --- |
| Ready to decide | 判断できる | 可決定 |
| Needs information | 情報が必要 | 需要資訊 |
| This week's patients | 今週の患者 | 本週病人 |
| Screening log | スクリーニングログ | 篩選紀錄 |
| Runs | 処理 | 作業 |
| Readiness | 準備状況 | 準備狀況 |
| Please check | 確認をお願いします | 請確認 |
| Audit trail | 監査証跡 | 稽核軌跡 |

## 2. Roles

| Role | Lands on | Does | Never |
| --- | --- | --- | --- |
| Investigator (PI, sub-I) | This week's patients | approves criteria (S20), marks patients, approves before contact | sees chart numbers or starts runs |
| Coordinator (CRC) | the work list | sets up studies, pastes protocols, starts feasibility and screening, records contact outcomes, consent, visits, AEs | approves criteria |
| Administrator | Admin | accounts, health, runs, data sources, REDCap links, updates | approves or marks |
| CRO specialist | Reports | reads the sponsor copy of feasibility reports for their studies (small counts hidden) | sees lists or patients |
| Viewer | Reports | reads reports and the audit trail | sees patients |

Every action is in the audit trail. A page your role may not open says so in your language (403).

## 3. The everyday work

**Start a study (CRC, then PI).** Protocol → paste the inclusion and exclusion criteria → the box drafts them → the
PI opens the approval page (S20), checks each criterion, gives it a short label in the site's language and approves.
Feasibility runs at once: the funnel shows how many patients pass each criterion.

**Work the list (PI).** Each morning the list has two parts: *Ready to decide* (every criterion answered) and *Needs
information* (fewest unknowns first). Open a patient: each criterion shows its answer and, for notes, the quote from
the chart. Mark: Approach, Need info (with a note for the CRC), Ask treating doctor, Not suitable now (a reason is
required), or Not now, re-check (with a date). Undo follows every mark; "Withdraw my mark" takes it back. On a phone
the patient sheet has Back, Next and a mark bar that stays in view.

**Contact (CRC).** After the PI approves, the CRC records the outcome in two taps. Only the CRC may reveal a chart
number, for a listed patient, with a reason.

**Morning mail.** At 07:00 the CRC and at 07:30 the PI get a short mail: who is new, who is due, by pseudonym and
screening number, never by name or chart number.

**Record the trial (CRC).** Seven built-in forms: screening log, consent, enrolment, visit, adverse event, deviation,
withdrawal. Each checks types, ranges and required fields and keeps every change (History shows old and new). The
participant moves from candidate to approached, consented, enrolled, on study, then completed, withdrawn or screen
fail. Visits have windows (due, open, overdue). AEs are written as reported; nothing is graded automatically.

**REDCap or a spreadsheet.** Attach the study's REDCap project on the study's set-up page (guided). Sync runs at night
and on a button. When TrialBox and REDCap disagree on a field, the Conflicts page lists it; you choose which value
stays. A spreadsheet with a name column imports with that column dropped.

**Set up a new site (CRC).** Readiness shows what is missing. Add charts one by one (text, Word, PDF, pasted EMR
text); facts the box reads from them are *proposed* and count only after you confirm them (one tap). Fix hospital
codes once; answer the "Please check" list.

**Exports.** Screening log (XLSX), the PI's enrolment report, ODM 1.3 and REDCap CSV of the forms.

## 4. The header command field

Type in the box at the top of any page, in any of the three languages: a study code, a pseudonym, a screening number,
or words such as "this week's list". It only opens pages; nothing runs until you press the button on that page.

## 5. Mail commands

The box also answers mail. The subject is the command; the result comes back by mail. Patient-level files go only to
the study's internal list, as an encrypted 7z, with the password in a second mail.

| Command | Example | Result |
| --- | --- | --- |
| FEAS | `FEAS GZQO lookback=36` (attach the protocol the first time) | feasibility PDF and XLSX |
| SCREEN | `SCREEN GZQO version=1.0.0` | encrypted candidate workbook and a summary PDF |
| CASE | `CASE GZQO mrn=10000001 lang=zh-TW` with the chart attached | eligibility sheet per criterion with quotes |
| CONSENT | `CONSENT GZQO lang=en,ja,zh-TW` with the approved consent form | a draft plain-language guide (§6) |
| RELEASE | `RELEASE <job id> [drop=I03] [keep=I07]` | releases a checked consent guide |
| NAV, SUBMIT | `NAV RA-BIO dept=RHEU`; `SUBMIT ONC-OSI pid=… bundle=<NAV job>` | Taiwan NHI lists, drafts and TWPAS bundles; the claim (dry run by default) |
| COHORT | `COHORT GOUT-COH` | alliance table and report; `COHORT MERGE` at the alliance root |
| FEEDBACK | `FEEDBACK GZQO` with `screen_feedback.csv` | stored for calibration |
| STATUS, CANCEL | `STATUS <job id>` | the job's state, or cancels it |

A console button is the same call as its mail line, with the same permissions and audit.

## 6. The consent explainer

`CONSENT` (or the console's Consent page) drafts a plain-language guide to the IRB-approved consent form: the key
facts by section (purpose, what happens, duration, risks, benefits, other choices, duties, voluntary participation
and withdrawal, privacy, costs, contacts) and three to five teach-back questions, in each language asked for.

- **It is a reading aid**, not the consent form, not a signature and not part of the consent record. Consent is taken
  on the official form in the site's own process. Each page says so, and says the form wins if they differ.
- **Three checks.** Every statement carries a word-for-word quote of the form; a statement whose quote or number is
  not in the form is removed. A second model checks each statement and back-translates it; anything not supported
  is held back. A coordinator or PI releases the guide (`RELEASE`); releasing is not an electronic signature.
- **Files.** A review sheet and DRAFT patient pages for the requester; after release, the patient page with who
  released it and when. Plain HTML, no script, prints on A4.
- **Not in this version:** questions and answers grounded in the form; editing a statement in the console; certified
  human translation review.

## 7. When something goes wrong

- Locked out: the sign-in page shows how long, and who to ask.
- A page shows an error: it says what happened and offers Back, Home and Help.
- "The model is busy, try again in a few minutes" (one-GPU boxes, while screening runs): try again later.
- Anything else: the site contact on the help page, or the administrator.
