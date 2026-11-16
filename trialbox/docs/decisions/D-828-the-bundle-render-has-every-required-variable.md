# D-828 the bundle's compose render has every required variable

- **Task:** BUNDLE-COMPOSE, the integrator's red of 2026-11-15 from lane G's GPU-box bundle build (#639)
- **PR:** this branch (`agent/BUNDLE-COMPOSE-env-renders-every-required-variable`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-176 (the bundle renders compose with its own .env), T-656 (TB_TZ required), D-382 (identity overlay)

## Decision

1. `tools/make_bundle.sh` writes a placeholder into its staged .env for every `${VAR:?...}` / `${VAR?...}` in the
   compose files it renders (today TB_TLS_HOSTNAME and TB_TZ=UTC); only the image list is read.
2. When `docker compose config` fails, the script prints compose's own error and stops (exit 2), instead of
   discarding stderr and saying only "compose listed no trialbox-py image".
3. The Makefile's gate image list (`SC_THIRD_PARTY`) gives TB_TZ a value too (`${TB_TZ:-UTC}`): with a deploy/.env
   that has no TB_TZ it rendered an empty list (checked with compose 5.6.1: 0 images before, 6 after).

## Test

`tests/unit/test_gate_image_list.py`: the gate list has a value for every required variable (before, failed).
`tests/unit/test_release_bundle.py`: the stand-in docker now refuses a required variable with no value, as compose
does. Before: 6 failed (the lane G error). After: 20 passed. The real compose 5.6.1 renders the image list from the
staged .env alone.
