# D-328 PoC demonstration mode behind the audited flag `demo.mode`

- **Task:** T-502 (wave P of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.3)
- **PR:** this branch (`agent/T-502-demo-guard`)
- **Date:** 2026-11-10
- **Status:** accepted
- **Closes:** REG-014 (Critical), PLAN-019 (Critical), OPS-004, REG-015 (the acknowledgement half); with the owner's
  rule of D-311: CR-032 (the PoC control only); DATA-015 (non-device line) only in part, see Consequences

## Context

The hosted PoC (`docs/plan/27-poc-plan.md` §3) gives two clinicians accounts on a console in a public cloud. The
console has a chart paste box and eight upload forms. Nothing technical stopped a tester from pasting or uploading a
real chart (REG-014, PLAN-019, OPS-004), and no acknowledgement was asked or stored (REG-015). D-311 §0.4 keeps this
control (K4).

## Decision

1. **One audited flag.** `demo.mode` (`off`, `on`; default `off`) is declared in `tb_common.flags`. It is seeded once
   from `TB_DEMO_MODE` at the console's first start and changed on `/ops/flags` with a reason; each change is a
   `flag.set` audit event (D-207). The console reads it per request through the five-second flag cache. A flag store
   that cannot be read means off: the demo boots with the flag seeded on, and a production box never has it.
2. **Refusals, before the body is read.** With the flag on, `console.demo_guard` refuses every
   `multipart/form-data` post (every upload form is one) and every route of its `GUARDED` list (the chart paste box
   `/site/charts` and its API, the protocol, consent, chart and mail uploads, the data dictionary and its API), with
   the console's refusal page in the reader's language (403 `demo.refused`), or JSON on `/api/`. Each refusal is an
   audit event `demo.refused` with the account, the method and the path, never the content. The upload routes in
   `console/app.py` and `console/site_pages.py` also call `demo_guard.guard` themselves, so a route stays closed if
   the middleware is ever bypassed. Free-text fields (notes, comments, feedback) stay open: the PoC scripts need them.
   The scan of point 5 covers them.
3. **Banner and footer line.** `templates/_demo_banner.html`, included by `base.html` at the top and at the foot,
   shows on every page, signed in or not, in the page's language: synthetic data only, not for clinical use, not a
   medical device, do not enter patient information. The foot repeats "not a medical device".
4. **The acknowledgement.** The text of 27-poc-plan §9.3 on `/demo/ack`, in the account's language. A signed-in
   account reaches no other page and no `/api/v1` call until it has ticked the five required statements. Sign-in,
   the second factor, the password change, the language and sign-out stay open, so task A0 runs in its order.
   Accepting writes one audit event `demo.ack` (actor, role, language, the statement's version, the two optional
   answers). The audit chain is the one store: no new table, and an acknowledgement cannot be edited. A second visit
   writes nothing.
5. **The scan of stored input.** `python -m console.demo_guard scan --db <data folders>` runs `tools/data_scan` (its
   patterns and allowlist) over the folders and over every text and JSON column of the trial database. A database hit
   is placed by schema, table, column and a short hash of the value, and the value is masked. `--write-baseline` after
   seeding records what the synthetic seed itself holds; `--baseline` after a session reports only what is new.

## Consequences

- The facilitator runs the scan after each session (27-poc-plan §10). A new hit triggers the purge of §8.2.
- The demo deployment must set `TB_DEMO_MODE=on` before the console's first start, or the owner switches the flag on
  `/ops/flags`. The hosting cards (T-501, T-509) carry that line.
- The non-device line on exported files (DATA-015, B6 of the scripts) is not in this change. Stamping a file after it
  is written would break the sha256 its `flow.export` row records; the stamp belongs in each export writer, before
  the ledger row: card T-682 (export watermark and ledger) takes it with its stamp.
- An upload made by the administrator (an update bundle, a sheet) is refused too while the flag is on.
