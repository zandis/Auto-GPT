# Supplement to the IRB amendments filed on 2026-11-10 (TB-SITE-06, draft)

> **Archived 2026-11-10 (D-311).** Not part of the plan and not to be sent. CGMH work is covered by the existing CGRD approval; the Japan amendment is Dr Makoto's own matter, outside this plan. Kept for history only.

| Field | Value |
| --- | --- |
| Document ID | TB-SITE-06 |
| Version | 0.1 draft (2026-11-10), card T-641 |
| For | the CGMH committee (amendment TB-SITE-04) and the Japan site's committee (amendment TB-SITE-05), through each site's PI and research office |
| Send by | Fri 2026-11-20, with the cover note TB-SITE-07, before each committee's first meeting on the amendment |
| Source | the commitments register `docs/validation/commitments.csv`: one row per promise in the two amendments, the hospital IT pack (TB-SITE-02) and the opt-out notice (TB-TMPL-01 §4), each with its code and test, or the card that finishes it, or a correction |
| Status | Draft for the owner and the two PIs. The English text is the source; each site adapts it to the committee's template and language. The Japanese and Chinese texts are prepared from this one and need a native read before they are sent. |

## 1. Why this supplement

The amendments describe TrialBox as it will be at go-live. Some of the controls they describe are still being built. A
supplement sent now, before the committees meet, keeps the approved text and the system the same. It does three things:

1. It marks the controls that are in build. Each is verified at operational qualification (OQ) at the site before any
   patient data is used. If a function is not ready at go-live, its switch stays off and the committee is told in
   writing.
2. It corrects five statements that do not match the system or each other (§3).
3. It adds the administrator's break-glass access, decided by the product owner on the day of filing (§4).

Nothing in this supplement widens the use of patient data beyond the filed text. Two items narrow it: the treating
physician's view (item 6) and the setpoint and gap-rule layers (item 2).

## 2. The amended items and their state

State: **in place** = built and tested; **in build** = verified at OQ before any patient data is used; **later** = not
part of the first release, switched off, and announced to the committee in writing before use.

| Item | Filed text, in short | State | What the committee is told |
| --- | --- | --- | --- |
| 1 Research repository | nightly copy, pseudonym at the door, names, IDs and phones never enter | in place for the structured fields; **in build** for note text | Chart numbers are replaced by pseudonyms at the door with a key the hospital holds, and the chart number is kept only in an encrypted map on the same server. Names, national IDs (Japan: insurer numbers) and phone numbers are not taken from structured fields. In note text they are masked before indexing; this control is in build. |
| 2 Patient profiles | cited one-page profile, second-model check, abstain under 95 %, annotations, setpoint and gap-rule layers | **in build**; setpoint and gap-rule layers **later** | The profile, its check and the annotations are switched off until verified at OQ. The setpoint and gap-rule layers are not part of the first release. Treating physicians who are not study members see no profile. |
| 3 Vector index and similar patients | vectors in the hospital database, "patients like this one" | vectors in place on the hospital server; the page **in build** | Note text is embedded on the hospital's server and the vectors never leave it. The "patients like this one" page stays off until verified at OQ. |
| 4 Whole-hospital pre-screening and cross-department view | purpose, log and rate limit on every view; approach after the treating physician agrees | in place; one reveal path **in build** | No change to the text. |
| 5 Referral | referral through TrialBox; unknown physician handled; every step logged | in place | No change. |
| 6 Clinician role | treating physicians read record, timeline, phenotype and eligibility layers of their own patients | **later** | Corrected, see §3.1. |
| 7 Data steward | named steward reads all note text, audited 10 years | **in build** | Corrected, see §3.2. |
| 8 Opt-out | removal from screening, profiles, vectors and exports within minutes | in place for screening, lists and exports; **in build** for stored vectors and profiles | Corrected, see §3.3. |
| 9 Data-handling rule | hospital hardware only; vendor holds no data; developers never touch real data; k = 5 | in place, except a general k = 5 check on every outbound count (**in build**) | No change to the text. |
| 10 Audit and retention | every view, reveal, export and signature with person, role, reason and time; 10 years; chain signed daily with a copy on the hospital share | hash chain and archive to the share in place; reason on every record and the daily signature **in build** | Every record is written to a hash-chained audit log, archived to the hospital's share and never deleted. A reason with every record and the daily signature of the chain are in build. |
| 11 Non-device statement | does not … alert clinicians or contact patients; written regulatory view before formal use | statement updated | Corrected, see §3.4. |

## 3. Corrections

### 3.1 Item 6, the treating physician's view

Replace item 6 with:

> The treating-physician view is a separate, later function behind its own switch, and it is off at go-live. When the
> hospital asks for it to be switched on, the committee is told in writing first. The view then shows a treating
> physician's own patients' records as received and the names of the studies they may fit: no phenotype, no derived
> score and no per-criterion eligibility, until a written regulatory view on this function is obtained. Every view is
> audited.

Reason: item 2 limits profiles to research staff while item 6 gave non-study physicians the phenotype and eligibility
layers (register DIF-09). A computed phenotype shown for an individual patient outside a study is the weakest point of
the non-device position (review finding REG-016).

### 3.2 Item 7, the data steward

Replace the first sentence of item 7 with:

> The data steward is a role separate from the system administrator. It is held by named members of the hospital's
> staff, acting under the hospital's authority, who may read all note text for code mapping, conflict resolution and
> data quality. Every read is audited and kept for 10 years.

CGMH adds: "For this pilot the hospital names the steward; an independent hospital second reviewer co-signs every
validation and release record." The owner and the CGMH PI decide whether the PI keeps the steward role, since the PI also
has a role at the supplier and item 9 says the supplier never holds patient data (register DIF-02). This is the one open
question in this draft.

### 3.3 Item 8, opt-out timing

Replace the second sentence of item 8 with:

> An opt-out takes effect for screening, every list and every later export from the moment the research office or the
> steward records it, and it is logged. Stored note vectors and profiles of that patient are removed by the next run of
> the opt-out worker. Counts already produced may not be changeable.

Reason: the filed text says "within minutes", the committee's question-and-answer sheet says "from the next night", and
the system takes effect when the opt-out is recorded (register DIF-07). The new wording is what the system will do.

### 3.4 Item 11, the non-device statement

Replace item 11 with the current intended-use statement (TB-IU-01 v0.2):

> TrialBox does not diagnose, treat, decide eligibility or recommend treatment. It gives no clinical alerts and sends
> nothing to patients; it sends study-task reminders, such as safety-report deadlines, to study staff. Every output is
> reviewed by a qualified person. It is not a medical device. A written regulatory view will be requested from a
> consultant in each country by 2027-01-29 and obtained before formal use.

Reason: TrialBox sends safety-report and deadline reminders to investigators, which "does not alert clinicians" did not
allow for, and no request for a regulatory view has been sent yet.

### 3.5 Small-cell suppression

Both amendments say k = 5 for any statistic leaving the study team; the ethics pack says k = 10 for anything leaving the
site (register DIF-08). Add to item 9:

> Counts leaving the study team are suppressed below 5. Counts leaving the hospital follow the hospital's rule, and never
> a threshold below 10.

## 4. Addition: the administrator's access (owner decision of 2026-11-10)

Add a new item 12 to both amendments, and the words "and break-glass for the administrator" to §A.4 / §B.4:

> **12. System administrator.** The system administrator's routine work (accounts, settings, switches, backups,
> updates) shows no patient-level data. If the administrator must see patient data to correct a fault, a break-glass
> step applies: a reason from a fixed list with free text, one patient or one job at a time, access ends by itself after
> 60 minutes, every view is audited with the person, the patient pseudonym, the reason and the time, the steward and the
> PI are told, and the steward reviews every use. This function is in build and is verified at OQ before any patient
> data is used.

Neither filed text mentions the administrator's access (register DIF-05). The hospital IT pack's older wording (a second
person, 24 hours) is replaced by the same rule (register DIF-06).

## 5. The other documents

| Document | Change before it is sent again |
| --- | --- |
| Opt-out notice (TB-TMPL-01 §4) | Add the uses the amendments add (cited summaries for the study team, similar patients, the cross-department view by the study's doctors before the treating doctor is asked); say that names are masked in notes; set "[period]" to all years held; check against the Japanese ethical guidelines in force from 2026-12-01 (cards T-642 and T-641; register OON-02, OON-04, DIF-10). |
| Hospital IT pack (TB-SITE-02) | Each control line marked "in place" or "at IQ" with its test or card, in one table for the three languages (card T-636). The red rows of the register name the lines. |
| Ethics pack question-and-answer (TB-TMPL-01 §7) | Opt-out timing as §3.3. |

## 6. Rule until the committees approve

No design change that widens data use is made after 2026-11-30 unless the site PI has checked it against the filed text
and this supplement (review finding PLAN-008). No patient data is used while a row of the register for a function in use
is red.
