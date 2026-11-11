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
| Investigator (PI, sub-I) | This week's patients | approves criteria (S20, the PI only), marks patients, approves before contact, acknowledges serious AEs, may show a chart number of the study's patients (D-143), keeps the delegation log, asks treating doctors (D-147) | starts runs |
| Coordinator (CRC) | the work list | sets up studies, pastes protocols, starts feasibility and screening, records contact outcomes, consent, visits, AEs | approves criteria |
| Administrator | Admin | accounts, health, runs, data sources, REDCap links, updates | approves or marks |
| CRO specialist | Reports | reads the sponsor copy of feasibility reports for their studies (small counts hidden) | sees lists or patients |
| Viewer | Reports | reads the feasibility reports of its studies (aggregate) | sees patients, runs, the registry, the audit trail or a study's set-up (D-146) |

Every action is in the audit trail. A page your role may not open says so in your language (403).

## 3. The everyday work

**Start a study (CRC, then PI).** Protocol → paste the inclusion and exclusion criteria → the box drafts them → the
PI opens the approval page (S20), ticks each criterion's codes as checked and approves; only the PI ticks and approves
(D-146). The CRC (or the PI) gives each criterion a short label in the site's language; the draft itself stays in the
protocol's own words. Feasibility runs at once: the funnel shows how many patients pass each criterion. Before the
first screening the CRC chooses **Who to screen** on the study's set-up page: the whole hospital, or only some doctors'
patients (a request that names doctors with `pract=` uses those for that run).

A request started on the console is allowed by your role (a coordinator or an administrator starts runs; the
investigator approves), not by your mailbox. Each person may start at most 20 runs of each kind (feasibility,
screening, ...) a day; case questions, consent drafts and approvals are not counted. When a limit is reached the page
says so in your language; the administrator can change the limits (`rate_limits_per_day`, RUNBOOK).

**Work the list (PI).** Each morning the list has two parts: *Ready to decide* (every criterion answered) and *Needs
information* (fewest unknowns first). Open a patient: each criterion shows its answer and, for notes, the quote from
the chart. Mark: Approach, Need info (with a note for the CRC), Ask treating doctor, Not suitable now (a reason is
required), or Not now, re-check (with a date). Undo follows every mark; "Withdraw my mark" takes it back. On a phone
the patient sheet has Back, Next and a mark bar that stays in view.

**Contact (CRC).** After the PI approves, the CRC records the outcome in two taps. The CRC and the study's PI may
show a chart number, for a listed patient, with a reason; each is recorded with the name, under an hourly limit.
Viewer and CRO accounts never see one (D-143).

**Criteria not matched (PI, CRC).** "Criteria not matched" (ja 基準に合致しない患者, zh-TW 未符合條件之病人) lists every
patient whose records did not match a criterion in the latest screening run,
with the criterion, where the answer came from (coded records, a confirmed fact, or the notes with both models
agreeing) and the evidence. Look at a few each week; "This is wrong, send to review" is recorded with your name.

**The study team and the whole hospital (D-147).** The PI keeps the study's *Delegation log* (a copy of the trial
office's signed log, compared with it every month): sub-investigators, with the tasks the PI ticks (see candidates,
mark Approach, ask a treating doctor, enter data) and their GCP training dates. Only the PI approves criteria. Until
the log names a PI, every investigator of the study acts as its PI. *Candidates* lists every patient the study's run
found anywhere in the hospital; a candidate opens with a purpose (recorded, and limited per hour), shows why the
patient fits or not with the quotes, and lets the PI or a sub-investigator ticked "see candidates" show the chart
number (D-143's reveal: a reason, the record, the hourly limit). **Ask treating doctor**: TrialBox only suggests the doctor the data names; confirm it, pick one from the
*Staff directory*, type a name, choose "arranged outside TrialBox" or leave it to the department contact. Nothing is
required. The CRC asks the doctor and records the answer (agrees to introduce, declines with a reason, wants to
discuss) on *Referrals*; Approach waits until the doctor agrees. A missing or expired IRB approval or consent-form
version (*IRB and consent form*) is a warning before Approach, not a block: marking Approach then is recorded as an
override. The research office keeps the *Opt-out register*: an opted-out patient leaves screening, every list and
later exports.

**Morning mail.** At 07:00 the CRC and at 07:30 the PI get a short mail: who is new, who is due, by pseudonym and
screening number, never by name or chart number.

**Record the trial (CRC).** Seven built-in forms: screening log, consent, enrolment, visit, adverse event, deviation,
withdrawal. Each checks types, ranges and required fields and keeps every change (History shows old and new). The
participant moves from candidate to approached, consented, enrolled, on study, then completed, withdrawn or screen
fail. Visits have windows (due, open, overdue). AEs are written as reported; nothing is graded automatically. A
serious AE stays on the PI's and the CRC's home pages and in the PI's mail, whatever its outcome, until the PI taps
Acknowledge. Each serious AE shows its reporting clock (sponsor, IRB, regulator): TrialBox's defaults, which the site
confirms against its IRB rules and the protocol (`TB_SAE_REPORT_DAYS`); an overdue report is on both home pages and in
the CRC's mail.

**SAE register (`/sae`, D-191).** TrialBox's one record of each serious AE: onset, the day the site learned of it, the
due day of every report (sponsor, IRB, regulator), the day each was sent, the receiver's acknowledgement, follow-ups,
the PI's acknowledgement, and a trail of every entry and change (who, when, old and new dates). Overdue reports come
first, under an alert, in Japanese, Chinese and English. Dates are entered once, on the AE form: "Record the report
sent" writes the day to the AE form, so the form, the home pages and the mail show the same date. Deadlines are
calendar days on the site's date (Asia/Tokyo, Asia/Taipei), counted from the day learned (else the onset); weekends
and holidays do not move them. The register flags an SAE with no start day, a day learned before the onset, or a day
learned late, an onset or day learned after today, and a day sent that is after today or before the event (that report
does not count as sent until the AE form is corrected); a report sent after its due day shows as sent late. A fatal or
life-threatening SAE gets a follow-up to the regulator due on day 15 from the day learned (7 + 8 days, ICH E2A;
`TB_SAE_FOLLOWUP_DAYS`), whenever the first report went; add any follow-up a receiver asks for with its due day. An
SAE the AE form no longer calls serious keeps its open reports on the worklist until each is sent or closed. The CRC records; the PI and the
administrator read; viewer and CRO accounts see nothing. No AE term, chart number or name is shown, stored in the
register or written to the audit log; references are letters and digits only. The page names who confirmed the site
rule (`TB_SAE_RULES_CONFIRMED`) or says that nobody has. The trial office's SAE log and SOP still govern: compare the
register with it each month, and use the office log when the box is down.

**REDCap or a spreadsheet.** Attach the study's REDCap project on the study's set-up page (guided). Sync runs at night
and on a button. When TrialBox and REDCap disagree on a field, the Conflicts page lists it; you choose which value
stays. A spreadsheet with a name column imports with that column dropped.

**EDC prefill (CRC, PI; D-160).** TrialBox can draft a subject's eCRF values from the hospital record, so the CRC
does not type them twice. It is **off** for every study until the PI turns it on, on the study's *EDC prefill* page,
with the sponsor's written acknowledgement (letter number and date; for a study the PI sponsors, say so) and the
site's blind re-entry result (at least 30 CRF pages, at least 98 % correct). The PI or an administrator can turn it
off at any time. The CRC then:

1. *Item map*: reads the CRF's data dictionary from REDCap (identifier fields are never read) and checks, per item,
   its CDASH tag and where its value may come from (patient record, lab or vital sign with its unit, diagnosis or
   medicine with the codes you type, a note passage, or none). A suggestion fills the rows; diagnosis and medicine
   codes are never guessed.
2. *Draft*: picks the screening number and the visit date. Each drafted value shows its source: the record row and
   date, a confirmed fact, or the note with the exact quote. A value TrialBox is not sure of stays **unknown** with
   the reason (nothing in the record, two different values, another unit, only in an unconfirmed chart fact). Unknown
   is never sent as "No".
3. *Review*: per value, **Confirm** (only a value with a source), **Change** (a reason is required; when you change
   the value, say where the new value comes from), or **Reject**. Nothing is sent yet.
4. *Sign*: read the meaning of the signature, tick that you read it, and type your password again. You need your own
   active entry on the study's delegation log; the signature records that name, your role, the time and the meaning.
   You sign exactly the values the page showed: if someone changed one since, open the page again. A changed value
   needs a new signature.
5. *Send*: only signed values go to REDCap. A value someone already typed in REDCap is never overwritten; it is listed
   as a conflict for you to settle in REDCap. A screening number on two REDCap records, a visit that is not a REDCap
   event, and a patient who opted out are listed and not sent. Every value sent is read back and compared. For another EDC, download
   the signed values as CDISC ODM 1.3.2 and import them there; TrialBox never types into another system's screens.

*Audit trail* shows, per subject, every draft, decision (old and new value, reason), signature and send. Viewer and
CRO accounts never see these pages. An account that signs in only through the hospital's single sign-on cannot sign
yet; ask the administrator for a local password.

**Set up a new site (CRC).** Readiness shows what is missing. Add charts one by one (text, Word, PDF, pasted EMR
text); facts the box reads from them are *proposed* and count only after you confirm them (one tap). Fix hospital
codes once; answer the "Please check" list.

**Exports.** Screening log (XLSX), the PI's enrolment report, ODM 1.3 and REDCap CSV of the forms, and the signed
prefill values as ODM 1.3.2 (D-160).

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
