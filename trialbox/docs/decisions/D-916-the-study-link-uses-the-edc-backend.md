# D-916 The study link uses the EDC backend when it is on

- **Task:** TrialBox's side of the internal EDC contract (section 20)
- **Date:** 2026-11-16
- **Status:** proposed
- **Builds on:** D-915

## Decision

1. When `TB_EDC_BACKEND` is set, the study-link page and the 03:00 read open their client through `edc_backend`
   and accept REDCap majors 13 through 17. When it is unset, S36 and `check_version` (14 through 17) are unchanged.
2. Arms, events, the form-event map and repeating instruments can be created on an empty project.
3. `POST /api/edc/events/v1` checks an HMAC, treats a repeated id as one event, and re-reads the mapped study
   for a record save, a completed form or a reported adverse event. `content=user` is not called.
4. An administrator saves the study, site and subject map. Tool calls use a separate token, run only when the
   capabilities document lists the `trialbox` module, and a write waits for confirmation on `/admin/edc`.
5. `TB_EDC_OIDC=1` turns on a small OIDC issuer for the EDC. It is off otherwise, and it does not replace the
   console's sign-in.
