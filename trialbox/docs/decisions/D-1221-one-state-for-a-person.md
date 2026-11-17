# D-1221 One state for a person, read the same way by every list and count (J-2, review R10)

- **Task:** card J-2 of lane J, review 2026-11-17 row 10 of section 10 (B-2, D-2, the table "One thing, several
  names"). For GZQO at one moment the coordinator's home card said 2 consented and 1 enrolled, the registry 1 and 1
  with 1 withdrawn, the research office 0 and 0: each list read one or two of the four facts the console holds and
  named what it found in its own words. Amended by the review of J-2 (fix round: time decides, the F-13 gate, the
  functions the registry form held, the counts' meaning, roles without row access, the slim read, fail safe). ·
  **Date:** 2026-11-17
- **Decision:** one function, `console.person_state.state_of`, reads the four facts the console holds about a person
  in a study (the investigator's latest mark event, the contact outcome in force, the screening log's row in the
  candidate registry, the participant record's last step) and returns one name of one ordered set: **On the list**,
  **Waiting for information**, **Set aside**, **To contact**, **Contacted**, **Not approached**, **Declined**,
  **Screen failure** (a Candidate's, before consent), **Consented**, **Enrolled**, **On study**, **Completed**,
  **Withdrawn** (a Participant's), and **State unknown** when the facts could not be read. Its words are
  `person.state.<name>` in en, zh-TW and ja (`console.i18n_person`); `life.state.*` and `registry.status.*` copy them.
  `console.person_state.read(h, rs)` reads one study's people once per page view (a GET; a write reads afresh): the
  screening log and a slim read of the participant records (`GET /studies/{rs}/subjects?slim=1`: record, pseudonym,
  state, since, reason, who and when; no visit or consent view), signed for the reader (D-717). Every list imports it:
  the weekly page's rows and side panel, Candidates, the patient sheet and the candidate page, the registry and its
  summary, Participants and one participant, the screening log page and its printable sheet, the home card's funnel
  and clinic list, the procedure step, the research office and the N1 mail line.
- **When the facts disagree** (the written rule): **time decides, and an older fact never overrides a newer one.**
  (1) The record is the newer of the participant record's last step and the screening log's row ("on the list" on
  either says nothing). From consent on the record is the state: no mark or contact outcome speaks for a
  participant. (2) Before consent, the newest of the record, the contact outcome in force and the investigator's
  latest mark event is the state; a mark taken back, or a "Not now" whose re-check day has come, is a fact too (on the
  list). A contact outcome that wrote the log (reached and booked, declined, lost contact) is older than a later log
  row "on the list" (the step was undone on the participant page). (3) On a tie of times, the later step in the work
  wins: participant record, screening log, contact outcome, mark. (4) Nothing recorded: on the list. The facts could
  not be read for this reader: **unknown**, never on the list and never contactable; its counts show "–", and a mail
  round logs it as an error.
- **The counts keep their meaning.** The home card keeps master's funnel (Found, PI reviewed, Contacted, Consented,
  Enrolled; cumulative), fed by the one state; its layout changes only behind card J-7's flag. The research office
  keeps its eight columns and its export's keys (`listed`, `reviewed`, `approached`, `contacted`, `consented`,
  `enrolled`, `screen_fail`, `declined`), cumulative as before, of the people whose state began in the year. "Reached"
  is written once (`person_state.REACHED`): contacted = contacted, declined, screen failure or any participant state;
  consented = any participant state (consented, enrolled, on study, completed, withdrawn); enrolled = enrolled, on
  study or completed (a withdrawal does not say whether enrolment came first). The registry counts people by state;
  the three reconcile by that definition (`tests/console/test_one_person_state.py`).
- **Roles that may not read patient rows** (administrator, steward, privacy office, viewer, CRO): the console asks
  `actor.may_read` before a read and makes no read that would be refused (no new `console.denied`); the registry index
  and the research office show them the aggregate source as before (the log's own counts by status).
- **The contact panel (F-13):** hidden for a participant (after consent) or in a closed study; a candidate who
  declined, was not approached or screen-failed keeps it, as on master. `POST /studies/{rs}/patients/{pid}/outcome`
  (and `/api/v1`) refuses an outcome for a participant (409, "Contact outcomes are for candidates") and for an
  unknown state. The week row's quick outcomes show only with an Approach mark in force for a candidate (D-133).
- **The registry's own status drop-down is gone; nothing else.** The old page's five actions and where they live now:

  | Action on the old registry page | Now |
  | --- | --- |
  | Add a patient by chart number (with a status) | the same form and signed route, `POST /pilot/registry/{ruleset}`, without the status: the person is added "On the list" with the reason (a status sent is not taken) |
  | Set a status by hand on a row (drop-down) | gone: the state follows the step that records it (the investigator's mark, the contact outcome, the consent form, the participant's steps) |
  | Correct a wrong status on a row | where it was recorded: the contact outcome's Undo, or the participant page (undo the last step, or record the step); a REDCap conflict names those places (`rc.conflict`) |
  | Take over a SCREEN run's candidates | unchanged (`/promote`) |
  | Export the screening log with chart numbers | unchanged (`/export.xlsx`) |

  **A hand correction that no longer exists:** setting a person who has no participant record and no contact
  outcome to contacted, declined or screen failure by hand, or moving a row backwards on the log where no step
  recorded it (for instance a row a past REDCap read-back set). This is a question for the integrator.
- **Also settled:** walk finding F-05 (the list "Approved and contacted" held patients nobody had called): rows say
  "To contact" or "Contacted" beside the investigator's mark, the list is "Approved to contact". F-13 as above.
- **Left:** F-18 (which list holds a withdrawn patient) goes to J-5. The office for a role without row access counts
  the log's own statuses of a study whose log changed in that year (the aggregate source has no per-row year). The
  "elsewhere" pill (the same patient in another study) still reads that study's log status. The screening log export's
  machine sheet keeps the log's status column; its printable sheet and the page use the one state.
- **Held by:** `tests/unit/test_person_state.py` (the rule over a table of timed cases, the review's sequences A, B, C,
  D and S1, every source word mapped, every state worded once, the latest record of a pseudonym kept, the funnel's
  definition); `tests/console/test_one_person_state.py` (each list names the same state in en, zh-TW and ja; the home
  funnel, the registry and the office reconcile; the office export's columns; the add by chart number sets no status;
  the sequences through the pages and the outcome route; no refused read for the administrator through
  `actor.read_headers`; an unreadable participant store makes nobody contactable); the registry, role-page, lifecycle,
  consent, step-3 and actor-box tests that pinned the old labels pin the new ones.
