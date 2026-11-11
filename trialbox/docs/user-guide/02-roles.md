# 2. Roles

| Role | Lands on | Does | Never |
| --- | --- | --- | --- |
| Investigator (PI, sub-I) | This week's patients | approves criteria (S20, the PI only), marks patients, approves before contact, acknowledges serious AEs, may show a chart number of the study's patients (D-143), keeps the delegation log, asks treating doctors (D-147); the study's PI, or a sub-investigator the PI ticked for "run", starts feasibility, screening and case runs | sees a study the delegation log gives no right in; while the log names no PI, nobody is PI (D-380) |
| Coordinator (CRC) | Home (the work list) | sets up studies, pastes protocols, starts feasibility and screening, records contact outcomes, consent, visits, AEs | approves criteria |
| Administrator | Home | accounts, health, runs, data sources and the nights of each (`/data-ops`, read only), REDCap links, updates | approves or marks; sees a patient or a job only under a break-glass grant (below) |
| Data steward | Break-glass | keeps the opt-out register and the staff directory, writes a study's first PI entry from the signed delegation log, resolves clinical conflicts (`/data/conflicts`), rejects (or, once available, accepts) a held night of a data source with a reason (`/data-ops`), reviews every break-glass use | starts runs or marks patients |
| Privacy office | Opt-out register | keeps the opt-out register and the staff directory with the steward, sees pseudonyms in the audit trail | anything else |
| CRO specialist | Reports | reads the sponsor copy of feasibility reports for their studies (small counts hidden); under a monitor grant for a visit, reads the study's enrolled subjects, read only | sees lists or other patients |
| Viewer | Reports | reads the feasibility reports of its studies (aggregate) | sees patients, runs, the registry, the audit trail or a study's set-up (D-146) |

**Break-glass (D-280, D-430).** An account reads a study's patients by its own rights; outside them, only under a grant
of its own for one patient or one job. The administrator, or an investigator the study's log does not reach, opens
a grant on `/breakglass` with a reason from a list and a written note of at least 10 characters; it ends after 60
minutes (or sooner, by the person), and a new grant ends the one before. Under it that patient's page or that job's page
opens and a chart number may be revealed, on the console's one reveal path. A grant for what the account already reads
is refused. The steward and the study's PI see the grant at once (list and mail); every use is a line on the steward's
review list, and a use not reviewed within 7 days is marked overdue.

Every action is in the audit trail. A page your role may not open says so in your language (403).
