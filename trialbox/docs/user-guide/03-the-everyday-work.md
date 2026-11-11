# 3. The everyday work

**Start a study (CRC, then PI).** Protocol → paste the inclusion and exclusion criteria → the box drafts them → the
PI opens the approval page (S20), ticks each criterion's codes as checked and approves; only the PI ticks and approves
(D-146). The CRC (or the PI) gives each criterion a short label in the site's language; the draft itself stays in the
protocol's own words. Feasibility runs at once: the funnel shows how many patients pass each criterion. Before the
first screening the CRC chooses **Who to screen** on the study's set-up page: the whole hospital, or only some doctors'
patients (a request that names doctors with `pract=` uses those for that run).

A request started on the console is allowed by your role (a coordinator or an administrator starts runs; the
study's PI, or a sub-investigator the PI ticked for "run", starts feasibility, screening and case runs; the investigator
approves), not by your mailbox. Each person may start at most 20 runs of each kind (feasibility,
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
agreeing) and the evidence. "This is wrong, send to review" is recorded with your name, and the patient is on the
study's weekly list again, marked "sent back", until the PI marks them (D-446).

**The weekly sample (PI).** Every week TrialBox draws ten of these patients for the study's PI (a sub-investigator
with the "see candidates" tick may answer too): *This week's sample of ten*, linked from the list. Answer each one:
"Records do not match, as the run said" or "Send back to my weekly list". The page counts the week's answers and the
study's samples so far. An opted-out patient is never in the sample. At a site reading real data (VALIDATION,
PRODUCTION) the list and its sample stay closed until the data steward records that the site's check of the study
(the dry run) passed, on *Site check of criteria not matched* (`/studies/{rs}/not-matched/check`).

**The study team and the whole hospital (D-147).** The PI keeps the study's *Delegation log* (a copy of the trial
office's signed log, compared with it every month): sub-investigators, with the tasks the PI ticks (see candidates,
mark Approach, ask a treating doctor, enter data) and their GCP training dates. Only the PI approves criteria. While
the log names no PI, nobody acts as PI: no investigator has a right in the study until the data steward writes the PI's
entry from the signed log (D-380). *Candidates* lists every patient the study's run
found anywhere in the hospital; a candidate opens with a purpose (recorded, and limited per hour), shows why the
patient fits or not with the quotes, and lets the PI or a sub-investigator ticked "see candidates" show the chart
number (D-143's reveal: a reason, the record, the hourly limit). On a site's box a candidate's page opens only after
the study's PI records, under *Study state and identifiers* in the study's set-up, that the approved IRB text covers
"identified pre-screening across departments by the investigator before referral", with the approval number (D-395);
until then the page says so and refuses. **Ask treating doctor**: TrialBox only suggests the doctor the data names; confirm it, pick one from the
*Staff directory*, type a name, choose "arranged outside TrialBox" or leave it to the department contact. Nothing is
required. The CRC asks the doctor and records the answer (agrees to introduce, declines with a reason, wants to
discuss) on *Referrals*; Approach waits until the doctor agrees. A missing or expired IRB approval or consent-form
version (*IRB and consent form*) is a warning before Approach, not a block: marking Approach then is recorded as an
override. The data steward and the privacy office keep the *Opt-out register*: an opted-out patient leaves screening, every list and
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

**Consent (D-399).** Consent is recorded one way: *Record consent* on the participant page opens the consent form
(the registry's status list no longer offers "consented"). *IRB and consent form* keeps the study's approved
consent-form versions, each with its IRB approval date and first day of use; every change stays in its history. On
save, a version that is not on the list, not yet approved or in use on the consent date, or already replaced shows a
warning; the form is saved as entered and the warning is logged. An enrolment or a visit dated before the consent is
flagged on the participant page, with a link to record a deviation. When a new version asks for re-consent, the
*Re-consent list* shows every participant on study still on an older version; *Record the re-consent* opens the
consent form again on its own event (`rc1`, `rc2` ...).

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
SAE the AE form no longer calls serious keeps its open reports on the worklist until each is sent or closed. The CRC records; the PI reads and
acknowledges; the administrator, viewer and CRO accounts see nothing. No AE term, chart number or name is shown, stored in the
register or written to the audit log; references are letters and digits only. The page names the rule set of the study and who confirmed it on the study's set-up
page ("Save and confirm"), or says that nobody has. The trial office's SAE log and SOP still govern: compare the
register with it each month, and use the office log when the box is down.

**REDCap or a spreadsheet.** Attach the study's REDCap project on the study's set-up page (guided). Sync runs at night
and on a button. When TrialBox and REDCap disagree on a field, the study's *Trial-record differences* page lists it (one
row per field, TrialBox's value against the source's); you choose which value stays. The data steward has a separate page,
`/data/conflicts`, for the clinical conflicts of the whole database (two sources giving different values for one patient
item; the item stays unknown until the steward keeps one value or keeps it unknown, with a reason). The steward's `/data-ops` page lists every night of every data source; a held night (the box still shows the night before) is rejected there with a reason (DATA §10). A spreadsheet with a name column imports with that column dropped.

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
