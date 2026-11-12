# 2. Roles

| Role | Lands on | Does | Never |
| --- | --- | --- | --- |
| Investigator (PI, sub-I) | This week's patients | approves criteria (S20, the PI only), marks patients, approves before contact, acknowledges serious AEs, may show a chart number of the study's patients (D-143), keeps the delegation log, asks treating doctors (D-147); the study's PI, or a sub-investigator the PI ticked for "run", starts feasibility, screening and case runs | sees a study the delegation log gives no right in; while the log names no PI, nobody is PI (D-380) |
| Coordinator (CRC) | Home (the work list) | sets up studies, pastes protocols, starts feasibility and screening, records contact outcomes, consent, visits, AEs | approves criteria |
| Administrator | Home | accounts, health, runs, data sources and the nights of each (`/data-ops`, read only), REDCap links, updates | approves or marks; sees a patient or a job only under a break-glass grant (below) |
| Data steward | Break-glass | keeps the opt-out register and the staff directory, writes a study's first PI entry from the signed delegation log, resolves clinical conflicts (`/data/conflicts`), rejects (or, once available, accepts) a held night of a data source with a reason (`/data-ops`), reviews every break-glass use | starts runs or marks patients |
| Privacy office | Opt-out register | keeps the opt-out register and the staff directory with the steward, sees pseudonyms in the audit trail | anything else |
| CRO specialist | Reports | reads the sponsor copy of feasibility reports for their studies (small counts hidden); under a monitor grant for a visit, reads the study's enrolled subjects and their source references, read only, and records the visit (below) | sees lists or other patients |
| Viewer | Reports | reads the feasibility reports of its studies (aggregate) | sees patients, runs, the registry, the audit trail or a study's set-up (D-146) |

**Break-glass (D-280, D-430).** An account reads a study's patients by its own rights; outside them, only under a grant
of its own for one patient or one job. The administrator, or an investigator the study's log does not reach, opens
a grant on `/breakglass` with a reason from a list and a written note of at least 10 characters; it ends after 60
minutes (or sooner, by the person), and a new grant ends the one before. Under it that patient's page or that job's page
opens and a chart number may be revealed, on the console's one reveal path. A grant for what the account already reads
is refused. The steward and the study's PI see the grant at once (list and mail); every use is a line on the steward's
review list, and a use not reviewed within 7 days is marked overdue.

**Monitor grant and source-data verification (D-380, D-436).** A CRO account names its studies and sees no patient
until the study's PI (the one the delegation log names) or the data steward gives it a monitor grant: on the study's
delegation log page (`/studies/{rs}/team`) add the account with the role "monitor", a start date, an end date (the
last day of the visit; required) and the monitoring-visit id (in the "Training certificate" field, which says so). The
grant holds only between those dates. Under it the monitor opens **Monitoring** (`/studies/{rs}/monitor`): the study's
enrolled subjects by screening number (never a candidate, a screen failure, a person who consented but never enrolled,
or a patient who opted out) and, per subject, the **source references**: each CRF value a person confirmed or changed,
the record item it was taken from (the citation the value's draft holds: table and row, day, and for a note the quote),
its changes and signatures. Nothing else of the patient's record is shown, and never a chart number or a pseudonym.
The page prints as the subject's source-reference sheet. On the same page the monitor records the visit: its date, the
subjects verified and the findings (the account and the visit id are taken from the grant; a correction is a new
record); the PI and the steward read these records there too. Every view and every record is in the audit trail with
the visit id. The page's text is in English, Japanese and Traditional Chinese, like every console page.

Every action is in the audit trail. A page your role may not open says so in your language (403).
