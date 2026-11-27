"""The console's POST acts in exactly one class each (card 9k-7, D-1388; review 09 §3.5, DS-7).

Every POST route a console page posts to (every POST route outside the machine APIs under ``/api/``, and every route
a template's form names) is in exactly one class. A route whose class depends on the value it is sent (the PI's
mark: ``mark=approach`` and ``mark=need_info`` are different acts) is classed value by value, each value of its
vocabulary in exactly one class. ``tests/console/test_acts_9k7.py`` reads the app's route table and the templates'
forms and fails on a route, a form or a value in no class or in two, and on an entry no route has.

* **CONFIRM_FIRST**: consent entries, SAEs and anything audited as a clinical act, and every other act that records
  something of a patient, a participant, a study's conduct or the site and is not in another class. Nothing is
  recorded until the person's confirming POST. For 14 routes (``SHEETS``) a confirmation page (``confirm.html``,
  ``admin_confirm.html``) comes first and the act is recorded only by its Yes; for the other 75 the act is its one
  POST, from the page that holds the form: there is no separate confirmation, on master as here (consent entry and
  the SAE acts among them). 9k-7 changes none of their timings. An act in this class gets no act-at-once Undo; a
  correction it had before 9k-7 (the life step's "Undo the last step" with its note, a contact outcome's Undo, a site
  fact's Undo, Enable after Disable, Undo after a REDCap Detach; D-178) stays as it was, an act of its own with its own
  audit event.
* **UNDO**: act at once, with Undo: only marks and settings that are not clinical acts. The Undo is offered only to
  the person who acted, for a stated time, restores exactly the state before, is a POST with the CSRF token, runs
  every check of the act it puts back, is refused with what is true when the thing changed since, is done once (a
  second click writes nothing), and leaves the pair of audit events (done, undone): the "done" event is never removed.
* **AWAITING**: inherited from D-133, awaiting the owner's ruling on 9k-7: the PI's Approach and "Not suitable now".
  They record at once and keep D-133's toast Undo, exactly as on master; 9k-7 adds and removes nothing for them.
  An Approach gives a screening number, a screening-log row and the "approached" count, which its Undo does not take
  back; "Not suitable now" records a medical reason.
* **SYSTEM**: a sync or a run a person starts: it records what a source holds or what a run computes (an SAE synced
  from REDCap into the register, a source's rows, a run's list), never a person's decision about a patient.
* **PLAIN**: signing in and out, the language, the acting role, a search, a check or a connection test, one's own
  password, feedback. Nothing of a patient, a participant or a study's conduct is recorded by them.

``UNSURE`` names the acts put on CONFIRM_FIRST because it was not certain whether they are clinical acts (the owner's
ruling of 2026-11-20: when unsure, confirm first). ``SHEETS`` names the CONFIRM_FIRST routes whose first POST shows a
confirmation page; ``tests/console/test_acts_9k7.py`` pins that set against the handlers and proves for each that
nothing is written before its Yes.
"""

from __future__ import annotations

CONFIRM_FIRST: dict[str, str] = {
    # a participant's life: consent, enrolment, visits, final steps, adverse events (clinical acts)
    "/studies/{rs}/subjects/{record}/step": "a participant's next step: consent, enrolment, a final step (sheet)",
    "/studies/{rs}/subjects/{record}/undo": "taking a participant's last step back, with a note (a correction)",
    "/studies/{rs}/subjects/{record}/aes/{event}/ack": "an adverse event acknowledged by the investigator",
    "/studies/{rs}/sae/{record}/{event}/ack": "an SAE acknowledged",
    "/studies/{rs}/sae/{record}/{event}/{what}": "an SAE report closed, sent, followed up, its receipt recorded",
    "/studies/{rs}/schedule": "the study's visit schedule",
    "/studies/{rs}/deviations": "a protocol deviation recorded, confirmed or dismissed",
    "/studies/{rs}/entry": "a form's values entered for a participant",
    "/studies/{rs}/monitor/visits": "a monitor's source data verification of a visit",
    "/studies/{rs}/conflicts/{cid}": "a value conflict decided: keep or take a value (sheet)",
    "/data/conflicts/{cid}/resolve": "a value conflict resolved by the steward",
    "/pilot/consent": "a consent form text recorded for the pilot workspace",
    "/studies/{rs}/irb/icf": "a consent form version recorded with its approval",
    "/studies/{rs}/irb": "the IRB approval recorded",
    "/studies/{rs}/irb-text": "the IRB text's coverage of the identified view",
    # the EDC: values copied, decided, signed and sent
    "/studies/{rs}/edc/copy/{record}/tick": "values ticked as copied into the EDC, or a tick taken back",
    "/studies/{rs}/edc/decide/{draft_id}": "an EDC draft confirmed, edited, kept, rejected or retired",
    "/studies/{rs}/edc/sign": "an EDC form signed",
    "/studies/{rs}/edc/send": "signed EDC forms sent",
    "/studies/{rs}/edc/drafts": "EDC drafts made",
    "/studies/{rs}/edc/import": "an EDC import",
    "/studies/{rs}/edc/switch": "the study's EDC switched",
    "/studies/{rs}/edc/map": "the EDC field map",
    "/studies/{rs}/edc/dictionary": "the EDC data dictionary",
    "/api/edc/tools/{proposal_id}/confirm": "an EDC tool's proposed values confirmed by the person",
    # screening: the decisions about a patient other than the PI's marks
    "/studies/{rs}/patients/{pid}/outcome": "a contact outcome (closing outcomes: sheet; its D-178 Undo stays)",
    "/studies/{rs}/candidates/{pid}/referral": "a referral to the treating doctor; pausing an Approach (sheet)",
    "/studies/{rs}/referrals/{ref_id}/answer": "the treating doctor's answer to a referral",
    "/studies/{rs}/excluded/{pid}/review": "the review of an excluded patient",
    "/studies/{rs}/not-matched/{pid}/review": "the review of a not-matched patient",
    "/studies/{rs}/not-matched/sample/{pid}": "an answer on a sampled not-matched patient",
    "/studies/{rs}/not-matched/check": "a not-matched record checked",
    "/studies/{rs}/committee": "a committee's decision",
    # identity: every reveal of a chart number is audited on both sides (D-438)
    "/studies/{rs}/patients/{pid}/reveal": "a chart number revealed, with a reason",
    "/studies/{rs}/candidates/{pid}/reveal": "a candidate's identity revealed, with a reason",
    "/studies/{rs}/referrals/{ref_id}/print": "a referral printed with its chart number",
    "/pilot/jobs/{job_id}/reveal": "a run's chart numbers revealed, with a reason",
    "/breakglass": "a break-glass grant asked",
    "/breakglass/{gid}/end": "a break-glass grant ended",
    "/breakglass/{gid}/review": "a break-glass grant reviewed",
    "/site/opt-outs": "a patient's opt-out recorded",
    "/site/people/resolve": "a person matched across the site's sources",
    # a study's set-up and its team
    "/studies/{rs}/state": "the study's state; a close is final (sheet)",
    "/studies/{rs}/state/take-back": "the study's last state change taken back",
    "/studies/{rs}/identity": "the study's identifiers",
    "/studies/{rs}/team": "an entry of the delegation log",
    "/studies/{rs}/team/{eid}": "an entry of the delegation log ended or changed",
    "/studies/{rs}/team/check": "the monthly check of the delegation log",
    "/studies/{rs}/setup": "the study's set-up",
    "/studies/{rs}/setup/contact": "the study's contact rule",
    "/studies/{rs}/setup/consent-ages": "the study's consent ages",
    "/studies/{rs}/setup/sae": "the study's SAE settings",
    "/studies/{rs}/setup/scope": "the study's scope",
    "/studies/{rs}/setup/log": "the study's delegation log set-up",
    "/studies/{rs}/setup/study": "the study's first set-up",
    "/studies/{rs}/setup/redcap": "the study's REDCap set-up",
    "/studies/{rs}/profile": "the site's profile for the study",
    "/studies/{rs}/forms/builtin": "the study's built-in forms",
    "/studies/{rs}/forms/dictionary": "the study's form dictionary",
    "/studies/{rs}/sources/redcap": "REDCap attached to the study",
    "/studies/{rs}/sources/redcap/detach": "REDCap detached (sheet; its D-178 Undo stays)",
    "/studies/{rs}/sources/redcap/undo": "the D-178 Undo of a Detach: REDCap attached again",
    # the pilot workspace: approvals and the registry
    "/pilot/jobs/{job_id}/approve": "a run's list approved by the investigator (sheet for Approve all)",
    "/pilot/jobs/{job_id}/approval/tick": "a criterion ticked on the approval page",
    "/pilot/jobs/{job_id}/approval/label": "a criterion's label on the approval page",
    "/pilot/jobs/{job_id}/release": "a run's result released",
    "/pilot/registry/{ruleset}": "the registry's rows of a study",
    "/pilot/registry/{ruleset}/promote": "a registry row promoted",
    "/data-ops/batches/{bid}/decide": "a data-operations batch decided",
    "/data/instruments/{iid}": "an instrument's mapping",
    # the site's records
    "/site/facts/{fid}": "a site fact confirmed, corrected or rejected (reject: sheet; its D-178 Undo stays)",
    "/site/checks/{cid}": "a site check recorded",
    "/site/codes": "the site's code mappings",
    "/site/charts": "the site's chart sources",
    "/site/sheets": "the site's sheets uploaded",
    "/site/staff": "the site's staff directory",
    "/site/practice": "the site's practice set-up",
    "/site/remote": "remote help for the site",
    # accounts, identity and operations (audited security acts)
    "/ops/users": "accounts: add, scope, reset and disable (sheets), enable",
    "/ops/accounts/requests": "a second person's confirmation of an account request",
    "/ops/identity": "sign-in factors: enrolment code, unlock, reset (sheet)",
    "/ops/flags": "a feature switch, with a reason (sheet)",
    "/ops/notices": "the box's notices to people",
    "/settings/notices": "a person's notice settings",
    "/admin/jobs/{job_id}/cancel": "a run cancelled (sheet)",
    "/admin/jobs/{job_id}/retry": "a run retried (sheet)",
    "/admin/ops/{action}": "an operation of the box: backup, update, logs (sheets)",
    "/admin/redcap": "a REDCap connection",
    "/login/first-run/answers": "the box's first set-up: its answers recorded",
}

MARK = "/studies/{rs}/patients/{pid}/mark"
# routes classed value by value: route -> the form field that names the act
BY_VALUE: dict[str, str] = {MARK: "mark"}

UNDO: dict[str, str] = {
    # the PI's marks on the weekly list (D-108) that decide nothing about the patient yet, and the toast's Undo
    # (``mark=undo``, the row it takes back in ``undo``), for UNDO_MINUTES (console.home)
    f"{MARK} mark=need_info": "the PI asks for more information",
    f"{MARK} mark=not_now": "the PI defers the patient to a re-check date",
    f"{MARK} mark=withdraw": "the PI takes the current mark back",
    f"{MARK} mark=undo": "the toast's Undo of a mark; an Undo that takes back or puts back an Approach or a Not "
    "suitable now is D-133's inherited Undo of the AWAITING class, unchanged",
}

AWAITING: dict[str, str] = {
    f"{MARK} mark=approach": "the PI's Approach: a screening number, a screening-log row, the approached count",
    f"{MARK} mark=not_suitable": "the PI's Not suitable now, with a medical reason",
}

SYSTEM: dict[str, str] = {
    "/studies/{rs}/feasibility/refresh": "the feasibility counts read again",
    "/studies/{rs}/redcap-read": "a REDCap read run now: the participants' rows it holds",
    "/studies/{rs}/sources/{name}/sync": "a source synchronised now: the rows it holds",
    "/studies/{rs}/sae/sync": "the SAE register brought up to date now: the SAEs REDCap holds",
    "/admin/models/canary": "the model check run now",
    "/ops/ingest": "an ingest run started: the site's data copied",
    "/pilot/request": "a run requested",
    "/pilot/propose/{pid}/confirm": "the proposed run started",
    "/pilot/case": "a case run started",
    "/pilot/cascade": "a cascade run started",
    "/pilot/protocol": "a protocol sent in for reading",
    "/pilot/mailbox": "the mailbox read now",
}

PLAIN: dict[str, str] = {
    "/login": "signing in",
    "/login/totp": "the sign-in's second factor",
    "/logout": "signing out",
    "/enrol": "the first sign-in with an enrolment code",
    "/login/first-run": "the first-run code that opens the box's first set-up",
    "/login/first-run/answers/keep": "the first set-up's form drawn again in another language or country",
    "/account/password": "one's own password",
    "/lang": "the page language",
    "/role": "the acting role on a test box",
    "/demo/ack": "demo mode's banner acknowledged",
    "/feedback": "feedback about the page on screen",
    "/audit/patients/by-chart": "a search of the audit by chart number",
    "/audit/verify": "a check of the audit chain",
    "/admin/redcap/{ref}/test": "a connection test",
    "/studies/{rs}/setup/redcap/test": "a connection test",
    "/pilot/propose": "a request read into a proposed run",
}

# acts on CONFIRM_FIRST because it was not certain whether they are clinical acts (D-1388: for the owner)
UNSURE: dict[str, str] = {
    "/studies/{rs}/patients/{pid}/outcome": "a contact outcome records the patient's answer to the study (declined, "
    "booked) and moves the registry; the closing outcomes ask first, the others record at once and keep their D-178 "
    "Undo, as before",
    "/studies/{rs}/edc/copy/{record}/tick": "a tick that values were copied into the EDC: a clerical mark, but of "
    "the participant's record; it keeps its untick, as before",
    "/studies/{rs}/candidates/{pid}/reveal": "a reveal is a read, audited on both sides, not a clinical act",
    "/studies/{rs}/patients/{pid}/reveal": "as the candidate's reveal",
    "/site/people/resolve": "matching a person across sources is a data steward's act, not a clinical one",
}

# CONFIRM_FIRST routes whose first POST shows a confirmation page (the values that bring it), held by the test
SHEETS: dict[str, str] = {
    "/admin/jobs/{job_id}/cancel": "always",
    "/admin/jobs/{job_id}/retry": "always",
    "/admin/ops/{action}": "backup, update apply and the other actions that change the box",
    "/ops/users": "action=reset, action=disable",
    "/ops/identity": "action=reset_totp",
    "/ops/flags": "always",
    "/pilot/jobs/{job_id}/approve": "Approve all",
    "/studies/{rs}/conflicts/{cid}": "keep or take a value",
    "/studies/{rs}/patients/{pid}/outcome": "the closing outcomes",
    "/studies/{rs}/subjects/{record}/step": "the final steps (withdrawn, screen failed) with a reason",
    "/site/facts/{fid}": "action=reject",
    "/studies/{rs}/state": "state=closed",
    "/studies/{rs}/candidates/{pid}/referral": "a referral that pauses an Approach",
    "/studies/{rs}/sources/redcap/detach": "always",
}

LISTS: dict[str, dict[str, str]] = {
    "confirm-first": CONFIRM_FIRST,
    "undo": UNDO,
    "awaiting": AWAITING,
    "system": SYSTEM,
    "plain": PLAIN,
}


def route_of_entry(entry: str) -> str:
    """The route an entry names (an entry of a route classed by value is ``"<route> <field>=<value>"``)."""
    return entry.split(" ", 1)[0]


def class_of(route: str) -> list[str]:
    """The classes that name ``route`` itself (exactly one for a route not classed by value; none for one that is)."""
    return [name for name, acts in LISTS.items() if route in acts]


def value_classes(route: str) -> dict[str, list[str]]:
    """For a route classed by value: each value named, with the classes that name it (exactly one when right)."""
    field = BY_VALUE[route]
    out: dict[str, list[str]] = {}
    for name, acts in LISTS.items():
        for entry in acts:
            if route_of_entry(entry) == route and " " in entry:
                key, _, value = entry.split(" ", 1)[1].partition("=")
                if key == field:
                    out.setdefault(value, []).append(name)
    return out
