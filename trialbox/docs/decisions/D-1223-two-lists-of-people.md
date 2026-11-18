# D-1223 Two lists of people, Candidates and Participants, in place of seven, behind one flag (J-5, review R16)

- **Task:** card J-5 of lane J (the journey review of 2026-11-17, `docs/reviews/2026-11-17-journey-and-simplicity.md`,
  finding D-2 and row 16 of section 10; built on J-2's one state, D-1221) · **Date:** 2026-11-18
- **Decision:**
  - **Two lists.** **Candidates** (people before consent) at `/studies/{rs}/people/candidates` and **Participants**
    (people from consent on) at `/studies/{rs}/people/participants`. Each of the old lists of one study's people is a
    view of one of them (`console.people_lists.VIEWS`):

    | Old list | Old address | Now |
    | --- | --- | --- |
    | This week's patients (with its filters: in clinic, ready, needs information, to review, information, approached, all) | `/studies/{rs}/week` | Candidates, first view "This week"; the filters stay (`?list=`); "contact outcomes" is its filter `?list=approached` |
    | Cohort list (a registry study's new members) | `/studies/{rs}/cohort` | Candidates, view "New members", in place of "This week" for a registry study (whose weekly page already sent there) |
    | Candidates (the treating doctor and the referral) | `/studies/{rs}/candidates` | Candidates, view "Doctors and referrals" (`?show=` kept) |
    | Candidate registry of one study (add by chart number, take over a run, export) | `/pilot/registry/{rs}` | Candidates, view "Add and export" |
    | Screening log (and its pre-screen log) | `/studies/{rs}/screening-log` | Candidates, view "Screening log" |
    | Participants | `/studies/{rs}/subjects` | Participants, first view "Everyone", with a new filter by the one state (`?state=withdrawn`, ...) |
    | Enrolment report (and its withdrawals) | `/studies/{rs}/enrolment` | Participants, view "Enrolment and withdrawals" |

    **A view is the old page**, served by its own route behind the new address: the same guard, the same reads, the
    same audit events, the same forms, links and filters. So no role reads or does anything it did not before, and a
    role refused an old list is refused its view with the same answer. The old pages' templates are not changed; the
    strip is added above them.
  - **Every old address redirects** (GET, 303) to its view with its query kept; a form posts where it posted before;
    a file (`.xlsx`, `.csv`), an action route and a person's own page keep their address. The view is in the path,
    so a page's relative filter links (`?list=`, `?show=`) stay in their view.
  - **One strip** above each view names the two lists and the views of the list shown, each only where the role may
    open it. The strip asks the questions the routes ask (the `phi.view` row and the delegation log; the `screen`
    task; the registry's rule) as a yes or no, with no audit event and no patient read. From the menu: the list's
    first page (one step), a view (the second); every action of an old list is on its view.
  - **The menu** shows Candidates and Participants where it showed "This week's patients" and "Candidate registry"
    (the investigator's and the coordinator's top items; the study's own pages under More). `/people/candidates` and
    `/people/participants` open the study's list, or a choice when the account has several studies.
  - **The flag** `layout.people_lists` (`tb_common.flags.DECLARED`, off/on, default off, no seed variable: changed on
    `/ops/flags` with a reason, audited as every flag). Off: every page, address and the menu as before; a new
    address sends to the old page. Read once per request, as J-3's flag (the value last read; one background read
    when older than 5 seconds).
- **Not changed:** the permission matrix and every guard; J-2's one state (every view reads it as before); the EDC's
  state where a participant row shows it (lane E); the site set-up's patient check (`/site/patients`, a check of the
  criteria during set-up, not a working list) and the registry index of all studies (`/pilot/registry`, the counts an
  account without patient rows reads) keep their addresses.
- **When the flag becomes the default:** the old addresses stay as redirects for one release; the menu's two old
  items and More's per-study "Candidates" link go; the routes keep their code (the views are served by them).
- **Held by:** `tests/console/test_people_lists.py` (the flag and its words; with it off the old pages and menu; with
  it on every redirect with its query; the role walk: every role of the role matrix, every old list, the same answer
  and the same page body, no extra refusal in the audit trail, the strip offering exactly the views the role opens,
  each one step from the list's first page; the menu and the picker; the participants' state filter; three
  languages), `tests/console/data/role_route_matrix.md` (the picker's row).
