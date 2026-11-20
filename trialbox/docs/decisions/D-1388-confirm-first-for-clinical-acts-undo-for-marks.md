# D-1388 Confirm first for clinical acts, Undo for marks: every POST form in one of three lists (9k-7)

- **Task:** card 9k-7 (DS-7) of plan 9 rev 2 §3.5, carried by plan 10 track F (`docs/plan/47-plan-10-2026-11-18.md`),
  from review 09 (`docs/reviews/2026-11-root/09-ux.md` §3.5 and DS-7), lane K. Waits for 9k-5 (D-1380, on master).
  **Date:** 2026-11-20
- **What the card asks** ("Confirm with consequence, and Undo; typed confirmation only for irreversible acts | S |
  proved by a test per act"; review 09: "a list of acts with their fate (undo or confirm), checked by a test per
  act"):
  1. a confirmation that names the consequence before an act;
  2. Undo over confirm for acts reversible for a while: "marks, contact outcomes, visit records, consent entry until
     day end: the act happens at once; a `done` banner with Undo stays until the next act";
  3. typed confirmation only for irreversible acts (account disable, break-glass, erase on opt-out);
  4. the list of acts with their fate, held by a test per act.
- **The owner's ruling (2026-11-20, about 16:00 UTC)**, which this card follows exactly:
  - **Confirm first** stays for consent entries, SAEs and anything audited as a clinical act: nothing is recorded
    until the person confirms. The card may make those confirmation pages uniform (one confirm pattern, the page
    header, one primary button, a clear "nothing has been recorded yet" line) but must not change when they take
    effect.
  - **Act at once with Undo** only for marks and settings that are not clinical acts, and whose Undo leaves an audit
    pair (done, undone). Undo is offered only to the person who acted, only for a short stated time, restores exactly
    the prior state, is a POST with CSRF, and never removes the "done" audit event.
  - **The list:** every POST form of the console in exactly one of three classes: confirm-first, act-at-once with
    Undo, or plain (neither: sign-in, search, language), pinned by a test that fails when a POST form is in no list
    or in two. When unsure whether an act is clinical, it is confirm-first and named for the owner.
- **Decision:**
  - **The three lists** are `services/console/act_classes.py`, keyed by the route a form posts to (every POST route
    of the console outside the machine APIs under `/api/`, and every route a template's form names, the two a profile
    or a flag registers included: 118):
    - **CONFIRM_FIRST (89):** consent and the participant's steps, adverse events and SAEs, visits, entries,
      deviations, the EDC, the other screening decisions (contact outcomes, referrals, reviews, committee), every reveal
      of a chart number and break-glass, opt-outs, a study's and the site's set-up and records, accounts, sign-in
      factors, switches and the box's operations, the box's first set-up answers. Nothing is recorded until the person's
      confirming POST: the POST of the page that states what will be recorded, and where the step is final or names a
      consequence a confirmation page first (`SHEETS`, 14 routes: a job's cancel and retry, the box's operations, an
      account's reset and disable, an authenticator's reset, a switch, Approve all, a conflict's keep or take, a closing
      contact outcome, a final participant step, a site fact's reject, a study's close, a referral that pauses an
      Approach, Detach REDCap). No timing changed.
    - **UNDO (1):** the PI's mark on a candidate (`/studies/{rs}/patients/{pid}/mark`: Approach, Need info, Not
      suitable now, Not now, Withdraw, and its Undo).
    - **PLAIN (28):** signing in and out, the first sign-in, the first-run code and its form drawn again, one's own
      password, the language, the acting role, demo mode's banner, feedback, an audit search and the chain check,
      connection tests, counts read again, syncs and reads run now, the model check, an ingest, run requests and
      proposals, case and cascade runs, a protocol sent in, the mailbox read now.
  - **The one confirm pattern:** `templates/confirm.html` and `templates/admin_confirm.html` use the page header
    (`page_header(page_title)`: one `h1`, equal to the `<title>`), state the consequence, say "Nothing has been
    recorded yet." (`confirm.nothing_yet`, en, ja, zh-TW), and carry one primary button and the way back as a
    secondary link. The confirm step itself is unchanged (the first POST shows the page, its Yes posts the same form
    with `confirm=yes`).
  - **The Undo of a mark keeps every rule of the ruling.** The state is the store's, never the page's: `pi_marks`
    rows are the trail; an Undo is a new row that names the row it takes back (`undoes`, unique), written with its
    audit event in one transaction under the patient's lock. The toast offers Undo only from the store's answer
    (`undo_offer`: this person's latest mark of the patient, not itself an Undo, inside `UNDO_MINUTES` = 15 minutes,
    no contact outcome after it) and says until when ("You can undo this until 14:35."); the form names the row
    (`undo=<id>`) and the POST checks everything again: the CSRF token; the act's role check (the right to mark; an
    Undo that takes back or puts back an Approach needs the right to Approach); the row is this person's (else "Only
    drsato, who made this mark, can undo it."); it is the patient's latest row (else "This patient's mark has changed
    since: drkato recorded a newer one at 14:31."); its time is not over (else "The time to undo this mark ended at
    14:35."); no contact outcome followed it; an Approach to put back was made on the list shown now. It restores the
    mark, reason, note, list and version of the row before (or no mark). It is done once: a second click, the back
    button or a second tab finds the Undo row and answers the same "Undone" page with nothing written (a race
    between two is settled by the unique index and answers the same). The done event (`console.pi_mark`) stays; the
    undone event is a `console.pi_mark` naming `undo` (the mark taken back) and `undoes` (its row), written before
    the page says so. `/api/v1` keeps its Undo without a row id: it takes back the latest row under the same rules.
  - **Migration:** `site` schema version 8, `ALTER TABLE pi_marks ADD COLUMN IF NOT EXISTS undoes BIGINT` and a
    partial unique index `IF NOT EXISTS`: idempotent, additive, rows before it have none. No table is added. The
    column holds the id of another `pi_marks` row, no patient data of its own; the row's patient linkage is the
    row's `pid`, as before, and the erasure inventory's row for `site.pi_marks` (screening_log, D-875) covers it
    unchanged. SQL is constant statements with bound parameters (`tools/sql_from_strings.json` unchanged).
- **Held by** (the two tests the ruling names, and the rest):
  - `tests/console/test_acts_9k7.py::test_every_post_form_and_route_is_in_exactly_one_list`, **the invariant**:
    every POST route of the app and every POST form of the templates (read by `tools.form_fields.scan`, each form
    taken to the routes its `action` can reach) is in exactly one list; a list entry with no route fails too.
  - `test_nothing_is_written_before_the_confirming_post` (in `tests/console/test_acts_9k7.py` and
    `tests/console/test_acts_9k7_life.py`): **for every confirm-first act, nothing is written to the database or the
    audit trail before the confirming POST.** Each of the 14 confirmation pages is reached by the existing test that
    walks its act, run under a guard that compares every table of the test's database and every file of its folder
    (the audit trail) before and after each POST that answers with the page; `test_every_confirmation_page_is_walked`
    holds that every route of `SHEETS` is walked. `test_opening_a_page_records_no_act` walks the GET of every page of
    the console (where every one-step confirm-first act's form is) as five roles: nothing but the records of reads
    changes and no act's audit event is written.
  - The Undo: `test_a_mark_is_undone_once_and_the_state_before_comes_back_with_both_events`,
    `test_only_the_person_who_marked_may_undo_and_only_while_nothing_changed`,
    `test_the_undo_ends_at_the_time_it_states`; the confirm pattern: `test_the_confirmation_page_is_one_pattern` (en,
    ja, zh-TW).
- **Not built (outside the ruling), each a sentence of the card or the review:**
  - "Undo over confirm for ... **consent entry until day end**" and "**visit records**": a consent entry and a visit
    record are clinical acts; they stay confirm-first, recorded on the person's POST, with no act-at-once Undo.
  - "Undo over confirm for ... **contact outcomes**": not certain to be a non-clinical act (below); it stays as it
    was, its timing unchanged.
  - "**Typed confirmation** only for irreversible acts (account disable, break-glass, erase on opt-out)": not built.
    The typed confirmations of today (administration and accounts) are left as they are; adding or removing one
    would change when an audited act takes effect, which the ruling keeps for confirm-first acts.
  - "A `done` banner with Undo **stays until the next act**": the Undo is offered for a stated 15 minutes instead, as
    the ruling asks for a short stated time.
- **For the owner (classed confirm-first because it was not certain they are not clinical acts, `UNSURE`):**
  - a **contact outcome** (`/studies/{rs}/patients/{pid}/outcome`): it records the patient's answer to the study
    and moves the registry; its closing outcomes ask first, the others record at once, and its D-178 Undo (this
    person's latest outcome, no time limit) stays as it was;
  - a **tick that values were copied into the EDC** (`/studies/{rs}/edc/copy/{record}/tick`), with its untick;
  - a **reveal** of a chart number (the patient's and the candidate's): an audited read;
  - **matching a person across the site's sources** (`/site/people/resolve`).
  The corrections that acts on CONFIRM_FIRST had before this card stay as they were, each a deliberate act with its
  own audit event and none brought under the rules above: the life step's "Undo the last step" (with a note), the
  contact outcome's Undo, a site fact's Undo, Enable after Disable, Undo after Detach REDCap (D-178). Bringing a
  setting's Undo (Detach, a site fact) under the rules above, or ruling it a correction, is the owner's.
- **Not verified:** the screening number an Approach gave stays when the Approach is undone (the screening log never
  loses a number, FR-STUDY-08, D-875); the mark itself is restored exactly. The rendered pages were not looked at in
  a browser at 390 px.
