# R-22-34: the rc1 refusals

**Reader:** the people who build TrialBox: the integrator, the lane leads and the reviewer of the card. Findings for
builders, so in one language.

- **Card:** the rc1 refusals (lane R; review finding R22-34, high risk)
- **Date:** 2026-11-22
- **Rulings:** the owner's ruling of 2026-11-20 and D-1072; the integrator's go, comments 7078088793, 7079138866,
  7080384411 and 7080612399
- **Findings:** [`rc1-refusals-2026-11-22/findings.json`](rc1-refusals-2026-11-22/findings.json) (R2234-01 to
  R2234-17)
- **The table:** `libs/tb_common/rc1_refusals.py`; the console's guard `services/console/rc1_guard.py`
- **Tests:** `tests/unit/test_rc1_refusals_table.py`, `tests/unit/test_rc1_refusal_sites.py`,
  `tests/console/test_rc1_guard.py`, `tests/console/test_rc1_orch_box.py`, `tests/unit/test_rc1_production_branches.py`

Synthetic data only. No model, no network and no GPU were used.

## 1. What is refused, and where

rc1 is a supervised demonstration on synthetic or public data. On a PRODUCTION box (an unset `TB_ENV`, and a name
that is not a known environment, are refused too) the product refuses six things. DEV, TEST and VALIDATION allow
them; that set is one constant, `ALLOWED`. Each row of the table names its call sites, its message key (en, ja and
zh-TW), its test and the audit event that records a refusal.

| Refusal | Sites | Audit |
| --- | --- | --- |
| live patient lists | the first step of every list job; the orchestrator's reveal; the console's list pages | `console.denied`, `screen.reveal_refused` |
| EDC writes from screening | the data core's push, as the REDCap bridge's error | none |
| patient mail and downloads | the mail gateway (held at once); the orchestrator's registry export; the console's downloads | `mail.failed`, `registry.export_refused`, `console.denied` |
| support exports | `trialbox support-bundle` | none |
| unattended updates | an update left to the quiet hour | `console.ops` |
| key ceremonies | the backup key ceremony, `trialbox backup-keygen`, `tools.keys` rotate-kek, ceremony-record and escrow-shares | none |

A host tool asks with the stricter of the box's `deploy/.env` and its caller's own `TB_ENV`. A `.env` that is a
folder or cannot be read is PRODUCTION; a missing one gives the caller's alone, for now (§5).

**The console's guard: fail-closed by construction: a route the list does not know is refused; the deny-list was
dropped because two reviews found routes it missed.** On a refused box the console serves only sign-in and sign-out,
health, the ops and admin pages, aggregate counts and static files (`ALLOWED` in `services/console/rc1_guard.py`), as
its outermost middleware, before any rewrite of an address (J-5's people lists included). A test walks the whole
route table. It is a plain ASGI layer, so a websocket meets it too; it matches the route's path without a proxy's
root path, and it refuses the audit page filtered to one patient (`/audit?pid=`). The morning mails carry no
candidate row on a refused box (`console.notify._collect`), whoever sends them: the timer or the administrator's
"Send notices now".

## 2. Not refused, and why

- `services/edc/service.py` `send_redcap`: a person's own EDC data entry. The integrator confirmed it is out of
  scope (R2234-09).
- `tools.keys init`: a box's first keys, which every box needs.
- The scheduled backup and its restore: no step of them asks the table (the MVP walk's test holds it).

## 3. The follow-up for lane H, before rc1

One card (R2234-08): the VALIDATION label (`rc1: "validation"` in the audit record of an allowed act) is written
nowhere yet, because no site within this card's go writes an audit record for an allowed act. And the producers that
refuse write no audit event: the list job's first step, the EDC push, the support bundle, the key ceremony and its
commands. Both wait for lane H's audit writer.

## 4. The fixture

`tests/orch_box.py` runs as VALIDATION, with no assertion changed, because PRODUCTION makes no list.
`tests/console/test_rc1_orch_box.py` holds the same box as PRODUCTION refused its SCREEN list. The four
PRODUCTION-only branches the fixture no longer reaches each have a test on a bare PRODUCTION box
(`tests/unit/test_rc1_production_branches.py`).

## 5. Waiting for a ruling

- The N1 morning mail is held where its rows are put in, `console.notify._collect` (go 7084254835): the mail gateway
  cannot tell an N1 mail from the health mail. Whether the gateway should hold it as well is still open (R2234-11).
- A missing `deploy/.env` read as PRODUCTION (item 4). It refuses every host tool run from a checkout with no
  `.env`: about 90 existing tests of the key ceremony, `tools.keys` and the backup key fail, for set-up alone.

