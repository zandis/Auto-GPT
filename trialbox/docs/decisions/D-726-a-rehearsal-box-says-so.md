# D-726 A rehearsal box says so

- **Task:** REHEARSAL (the Windows P-0 rehearsal, stage B: a signed bundle with placeholder models on a PC that is
  not a site box). The owner's yes, typed in lane D's session on 2026-11-13, on five conditions.
- **PR:** this branch (`agent/REHEARSAL-a-test-box-that-says-so`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-176 (the box rehearsal's model stand-ins), D-633 (a PRODUCTION box takes only a release from a
  commit), D-127 (TB_ENV, PRODUCTION when unset)

## Context

Stage B needs the model stand-ins and an unmeasured card's trial boot on a box that is plainly not a site's. Today
both are switched on by environment settings (`TB_COMPOSE_OVERRIDE`, `TB_ACCEPT_UNMEASURED_GPU=1`) that a box of
any environment honours, and nothing on the box or in the bundle says "rehearsal".

## The owner's five conditions

1. One explicit installer argument (`--rehearsal`).
2. The box is TEST before anything loads; refused on a PRODUCTION or VALIDATION box, or a box with site data.
3. The stand-ins and the unmeasured card are honoured only on TEST.
4. Console and doctor say "rehearsal box".
5. A rehearsal bundle is marked, and a PRODUCTION box refuses it.

## Decision

1. **One argument.** `deploy/install.sh --rehearsal`; `deploy/box-install.sh --rehearsal` hands it on to install.sh.
   `tools/rehearse_box/box.sh` (the box rehearsal) installs with it.
2. **TEST before anything loads.** The installer's first rehearsal block, before the bundle loads, refuses a box
   whose deploy/.env says PRODUCTION or VALIDATION and, unless the box is already marked, a box with Docker volumes
   of the compose project (data from no rehearsal). It writes the mark `deploy/site/rehearsal.json`. The update path
   judges the bundle's release record while it loads, before deploy/.env exists: `ComposeBox.environment()` reads
   TEST from the mark when deploy/.env names no `TB_ENV`; what deploy/.env says wins, so a mark never loosens a site
   box. After the settings the second block refuses answers that make the box PRODUCTION or VALIDATION and writes
   `TB_ENV=TEST` and `TB_REHEARSAL=1`.
3. **The stand-ins and an unmeasured card only on TEST.** `rehearsal_only` refuses `TB_ACCEPT_UNMEASURED_GPU=1` and
   the override `tools/rehearse_box/standins.yml` on a box that is not TEST (DEV too). A rehearsal takes both by
   default; `TB_COMPOSE_OVERRIDE=` set empty keeps the real model servers, which an unmeasured card's trial boot
   needs to be measured. The trial boot of RUNBOOK §1 and the tier refusal's advice are therefore a rehearsal box,
   emptied before the site's install (RUNBOOK §16).
4. **Doctor says so.** `check_rehearsal`: WARN "rehearsal box" on TEST; FAIL when `TB_REHEARSAL=1` or the mark is on
   any other environment. The console's banner is lane C2's (its pages); asked through the integrator.
5. **A rehearsal bundle is marked.** `tools/make_bundle.sh --rehearsal` → `tools.release build --rehearsal` →
   release.json `"rehearsal": true` (schema 1.2.0, optional). `Updater._from_a_commit` refuses it on PRODUCTION and
   VALIDATION, at install (`apply_update.sh`) and at update, before the box is touched.

**Not covered:** the blocks run on a real box only in the box rehearsal (`make rehearse-box`, Docker): not run in
this card's session. The console banner (C2). An older box (before this card) validates release.json against schema
1.1.0, which has no `rehearsal` field, and refuses a rehearsal bundle as malformed: refused either way.
