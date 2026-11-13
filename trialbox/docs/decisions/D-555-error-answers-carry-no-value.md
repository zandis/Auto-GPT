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

1. **The orchestrator answers with an error's text only for the classes whose texts are written here**
   (`ActorError`, `RegistryError`, `Rejected`, `NotRetryable`). Any other caught error (a `ValueError`, a file
   error, the ruleset loader's) is answered with a fixed sentence; what it said goes to the log by its type.
2. **Every text of those classes is a fixed sentence, or names only the box's own words**: a recorded status, a
   role, a job type, a limit, the job that is already running. Not the ruleset id that was sent, not the
   sender's address, not the job id of the path (the caller has all three).
3. **The console never shows a service's own error text.** A page that could not get its data says which service
   and with what status ("orchestrator (500)") or the refusal's code (`console.backend.service_and_status`).
4. **A test reads the code for all three** (`tests/unit/test_error_answers.py`): a new route that answers with
   another error's text, a new text that names something else, or a console page that passes a service's text
   on, fails it.

## What it does not do

- **The errors that carry their own `message` field** (a form's, a REDCap link's, the lifecycle's, the set-up's,
  the sponsor layout's) are not judged here. Their messages are written for the person at the page and many
  name a field or a value on purpose ("ic_date: not a date"). Which of them repeat a value that should not come
  back is a finding by reading, sent to the integrator with this card.
- **What REDCap itself answered** (`rc_bridge.client`: "REDCap returned 400: ...") still reaches the set-up page
  and the read log. It is the text a coordinator needs to mend a link, and it is another lane's module; reported.
- The console's own error classes (a refused form, a team rule) keep their texts: they are the console's words.
- The mail gateway's refusal of a sender names the sender; it answers that sender by mail.

## Reuse check

Nothing is added: the texts are changed where they are written, and the console's helper is six lines beside the
error classes it reads.

## Dropped (D-311)

No sign-off step.
