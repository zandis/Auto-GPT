# D-1221 One state for a person, read the same way by every list and count (J-2, review R10)

- **Task:** card J-2 of lane J, review 2026-11-17 row 10 of section 10 (B-2, D-2, the table "One thing, several
  names"). For GZQO at one moment the coordinator's home card said 2 consented and 1 enrolled, the registry 1 and 1
  with 1 withdrawn, the research office 0 and 0: each list read one or two of the four facts the console holds and
  named what it found in its own words. · **Date:** 2026-11-17
- **Decision:** one function, `console.person_state.state_of`, reads the four facts the console holds about a person
  in a study (the investigator's current mark, the contact outcome in force, the screening log's row in the
  candidate registry, the participant record's last life step) and returns one name of one ordered set: **On the
  list**, **Waiting for information**, **Set aside**, **To contact**, **Contacted**, **Not approached**, **Declined**,
  **Screen failure** (a Candidate's, before consent), **Consented**, **Enrolled**, **On study**, **Completed**,
  **Withdrawn** (a Participant's). Its words are `person.state.<name>` in en, zh-TW and ja (`console.i18n_person`);
  the older key families that named the same states (`life.state.*`, `registry.status.*`) copy those words instead of
  keeping their own, and `wstatus.*` is gone but for "new this week" (freshness, not a state).
  `console.person_state.read(h, rs)` reads one study's people for the reader of the request (the log and the
  participant records signed for that person, D-717); every list and count imports it: the weekly page's rows and
  side panel, Candidates, the patient sheet and the candidate page, the registry and its summary, Participants and
  one participant, the screening log and pre-screen log pages, the coordinator's home card (its counts and its clinic
  list), the procedure step, the research office and the N1 mail line. The home card, the registry and the research
  office count the same people (anyone with a mark, an outcome, a log row or a participant record, less who opted
  out) in the same states; the office counts those whose state began in its year.
- **When the facts disagree** (the written rule): (1) an end state on the participant record (completed, withdrawn,
  screen failure) wins, being the later fact a person recorded; (2) else an end state on the screening log
  (declined, screen failure, withdrawn) wins, as the participant record takes it at its next refresh; (3) else the
  further of the two along the main line (on the list, contacted, consented, enrolled, on study, completed), a tie to
  the participant record; (4) while neither says more than "contacted", the latest contact outcome (the later fact:
  "not approached" and "not reached" leave the log as it was); (5) while nothing says more than "on the list", the
  investigator's mark, a "Not now" whose re-check day has come no longer setting the person aside. The card proposed
  "the participant record always wins"; rule 3 differs where the REDCap read-back has moved the log ahead of a
  record not yet refreshed: the record would then name a step it is about to leave, so the further one is shown.
- **The registry's own status form is gone** (the add-by-chart-number form and each row's status drop-down, both
  `POST /pilot/registry/{ruleset}`). Nothing but the page and its tests used the route (the seeds and tools write the
  registry through the orchestrator or the contact outcome), so the route went with the form. Taking over a SCREEN
  run's candidates and the export stay. A state now follows only the steps that record it. No right changed.
- **Also settled:** walk finding F-05 (the list "Approved and contacted" held patients nobody had called): each row
  now says "To contact" or "Contacted", and the list is named "Approved to contact". F-13 (the patient sheet offered
  contact outcomes after the withdrawal and the close): the contact panel is not offered to a participant or to a
  person the study has finished with; it says the person's state instead.
- **Left:** F-18 (the withdrawn patient is on none of the weekly page's lists but "All") is which list holds whom, not
  how a state is named: J-5 (two lists, Candidates and Participants) takes it. The research office for an account
  that may not read patient-level rows (the administrator, a viewer) shows "–" for the states instead of a false 0;
  whether such counts may be read under the box's own principal is an owner's or lane C2's question (A-L3). The
  enrolment report and the participant's trail are the participant record's own steps: they use the same words but
  count life steps. The POST route that refused a hand-set "consented" (D-399) is gone with the form; the contact
  outcome still refuses without an Approach mark (D-133). The screening log's export keeps the log's own status
  column (machine words for the sponsor's systems); its page and printable sheet use the same words.
- **Held by:** `tests/unit/test_person_state.py` (the rule over a table of cases, every source word mapped, every
  state worded once in each language, a study gathered and counted once); `tests/console/test_one_person_state.py`
  (each list names the same person with the same state in en, zh-TW and ja; the home card, the registry and the
  research office count alike; the registry has no status form and its POST is gone); the registry, role-page,
  lifecycle and office tests that pinned the old labels now pin the new ones.
