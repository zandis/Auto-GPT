# D-1391 Your role in each study on the home page (9f-1, home half)

- **Task:** plan 9 card 9f-1, home half, from review 02 (`docs/reviews/2026-11-root/02-journeys.md` §1.3, J-1).
  Lane K. · **Date:** 2026-11-21
- **What the card asks for** (plan 45, line 374): *"Your role in each study" on home and account (PI here, sub-I there,
  with the ticked tasks)*; the test it names is a page test per role. Three things: a line per study with the person's
  role in it; the ticked tasks beside a sub-investigator's role; on two pages, the home and the account page.
- **What D-1382 already built:** the account page (section `account-roles`): one line per delegation-log entry in force
  today, in a study the account sees, with the role, the ticked tasks, the dates and, within 14 days of the last day,
  the warning (9f-4 a). It is read by `my_roles`, a function inside `register` of `services/console/step4.py`, with
  `TeamStore.entries_for(username)`: the person's own rows only. D-1382 left the home page unchanged and named this half
  as open.
- **What this half builds:**
  - `services/console/own_roles.py`: `my_roles` moves out of the route's closure into one function,
    `own_roles(team, username, day, seen)`, with the body it had. `step4.py` calls it for the account page and
    `home.py` for the home page. What it returns for any account did not change (the proof is below).
  - `templates/_roles.html`: one macro for the line (`role_items`, the markup the account page had inline, byte for byte
    with the dates and warning on) and one card for the home (`home_roles_card`).
  - The home: a card titled "Your role in each study" (the account page's words, `team.mine.title`; no new text) with one
    line per role in force: the study, the role and the ticked tasks of a sub-investigator, CRC or other entry ("all
    study tasks" for the PI). It stands on both templates the home renders (`home_crc.html`, the coordinator's and the
    administrator's study view; `home_today.html`, the investigator's, the CRO's and the viewer's with the flag
    `layout.home_today` on), after "Needs you today" where that block is, with the flag off and on. One line in each
    template, one helper (`home_roles`) and one keyword in `home.py`.
- **What it shows and to whom (the hard limit):** the card names only studies the page already names to that account
  (the same list of approved trials the page's own cards or "Next" lines walk: `trials(sess)`), so a role in a rule set
  that is not a trial the home shows, or in one the account does not see, is on the account page only. It carries no
  link, no number, no date, no warning and no patient-linked value, and no new text. It reads the person's own rows (as
  D-1382), makes no other read, opens no route and changes no right. A role whose `/home` is not a page on master
  (the investigator, CRO, viewer with the flag off go on to their own page; the steward and the privacy office go to theirs)
  has no card: the redirect is unchanged.
- **Left out, and why:**
  - The dates and the warning before an entry ends stay on the account page (and the log page): the card names role
    and tasks only, which keeps the home's numbers what master showed.
  - No cover roles (9f-3) and no link to the account page beyond the one the menu already has.
  - A person named in no log gets no sentence on the home (the account page keeps its one sentence): nothing is added to a
    page for someone with nothing to show.
  - A native reader has not read the ja and zh-TW lines (they are D-1382's words, not new ones).
- **The invariant and its test:** for every role, the set of studies, links (hrefs), counts and patient-linked values on
  the home is a subset of what that role's home showed on origin/master, with the flag `layout.home_today` off and on,
  in en, ja and zh-TW: `tests/console/test_home_roles_9f1.py::test_the_home_shows_no_study_link_count_or_value_that_master_s_home_did_not`.
  "Every role" is every column of the role walk (the seven roles of the matrix, the log's PI, sub-investigator and
  monitor, the SMO and CRO accounts in and out of scope) on the walk's seeded synthetic box. What master showed is data
  (`tests/console/home_roles_9f1_master.json`), captured by the same file from a clean `git archive` of origin/master
  (the file's header says how to capture it again when another card changes the home page).
- **`my_roles` before and after:** the same capture holds the account page's roles section (rule set, role, ticked tasks,
  dates, days left) of every column, flag and language on a box with an ended entry, one not yet started, one ending in
  ten days and entries in rule sets the account does not see as trials; the test
  `test_my_roles_gives_every_column_what_it_gave_on_master` compares it with master's, byte for byte.
- **The proof:** `tests/console/test_home_roles_9f1.py` (the invariant, the page test per role, the card's carrying no
  link or number, `my_roles` unchanged, one reader for both pages).
- **Held by:** that file. Other open cards that touch the same files (a covering PI on the home, the support session,
  confirm and Undo, the draft of lane J) are merged after this one with the card's one line kept; the invariant's data is
  captured again from the master they make.
