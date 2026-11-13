# D-555 An error answer built from an error's own text carries no value of the request

- **Task:** NEW-TRUST-3 (a finding of the review of NEW-TRUST-2, #467; the integrator's word of 2026-11-13)
- **PR:** this branch (`agent/NEW-TRUST-3-error-answers-carry-no-value`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-551 (a 422 carries no value of the request), D-147 / D-273 (a chart number is never kept,
  logged or given back)

## The problem

D-551 closed the framework's own answer. The services' own answers had the same fault in a second form: an error
is caught and its text is put into the answer (`HTTPException(detail=str(exc))`). Where that text is written
with what was sent, the answer repeats it:

- the registry answered a ruleset id that is not one with the id (`invalid ruleset id 'A1234567'`): whatever
  was typed in the path came back, and the console showed it on the page;
- a request refused for its sender answered with the sender's address;
- a ruleset with no approved version answered with the error of the loader, which names a folder of the box;
- the console's "a service did not answer" page showed the first 200 characters of what the service had said
  (`orchestrator returned 500: ...`), which is whatever that answer held.

## The decision

1. **In the orchestrator, a caught error's text is used only for the classes whose texts are written here**
   (`ActorError`, `RegistryError`, `Rejected`, `NotRetryable`), in an answer, a returned value or a stored note.
   Any other caught error is answered with a fixed sentence or with its type; what it said goes to the log. The
   few other places that take an error's text (a failed job's own error record, the self-test's report, the
   migration tool) are listed one by one in the test, each with what it is; none can join the list unseen.
2. **Every text of those classes, wherever it is raised, is a fixed sentence or names only the box's own words**:
   a recorded status, a role, a job type, a limit, the job that is already running. Not the ruleset id that was
   sent, not the sender's address, not the job id of the path (the caller has all three).
3. **The console's `Unavailable` never holds the text a service answered with.** It is built from the service's
   name and its status ("orchestrator returned 500", `console.backend.failed`; the study API's answers likewise
   in `problem_of`). That error is what pages and `/api/v1` answers show when a service fails, so every place
   that shows it is covered at once. A refusal is named by its code when the code has the shape of one.
4. **A test reads the code for all three** (`tests/unit/test_error_answers.py`).

A refusal's text that the console passes on (`Refused`, a `Problem`'s message) is the orchestrator's own and is
held by rules 1 and 2, not by the console.

## What it does not do

- **The errors that carry their own `message` field** (a form's, a REDCap link's, the lifecycle's, the set-up's,
  the sponsor layout's) are not judged here. Their messages are written for the person at the page and many
  name a field or a value on purpose ("ic_date: not a date"). Which of them repeat a value that should not come
  back is a finding by reading, sent to the integrator with this card.
- **What REDCap itself answered** (`rc_bridge.client`: "REDCap returned 400: ...") still reaches the set-up page
  and the read log. It is the text a coordinator needs to mend a link, and it is another lane's module; reported.
- **An error handed whole to a helper** (`_fail(exc)`) is not seen by the test.
- **Other answers that name what was sent**, found by reading and sent to the integrator: a notice refused for an
  outside address names the address (`app.py`, "notices go to hospital addresses only, not ..."); "no source
  <name>" names a path value; a failed job's error record keeps 300 characters of any error's text.
- The console's own error classes (a refused form, a team rule) keep their texts: they are the console's words.
- The mail gateway's refusal of a sender names the sender; it answers that sender by mail.

## What the adversarial review changed

One review by a fresh reviewer, with mutations of the code and of a scratch copy. Verdict: fix first.

- **The console's helper never said "orchestrator (500)" on the paths it was put on**: those errors were built
  from the raw body, not from "service returned status". And six other places (two pages, the three `/api/v1`
  refusal helpers, the readiness page) still showed the text. Fixed at the source instead of at each place: the
  error itself no longer holds a service's text (rule 3 above), tested through `problem_of` and `failed`.
- **The first test saw one spelling** (`raise HTTPException(... str(exc))` with the name `exc`). It now takes the
  handler's own name and sees `str`, `repr`, an f-string, `.args` and `.format`, in a raise, a return or an
  assignment. That found three real places where any error's text went into an answer: the two screening-log
  notes of the lifecycle's step routes (a validation error prints its input) and the lifecycle note of the
  REDCap read, which is also stored in the read log. They carry the error's type now; the registry's own words
  are kept.
- Rule 2 reads every file of the orchestrator and the two library files that raise `ActorError`, by the class's
  last name, raised at once or kept in a name first.
- A refusal's code is shown only when it has the shape of a code; the token-name check of the dictionary route has
  its own `try`, so another `ValueError` of that call is not answered with the token-name sentence; the sentence
  is written once (`studystore.TOKEN_NAME`); the ruleset route's new 404 has a test.
- **Checked and sound:** every value a listed text may name is closed before the raise (a contract's literal, a
  stored status, a signed role, a setting, a stored job id); the console's match on "is not permitted to run"
  still holds.

## Reuse check

Nothing is added: the texts are changed where they are written, and the console's helper is six lines beside the
error classes it reads.

## Dropped (D-311)

No sign-off step.
