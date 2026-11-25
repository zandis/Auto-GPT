# INT-S-E: the evaluation tool reads a judge reply like the product and counts what it sets aside

**Reader:** the people who build TrialBox: the integrator and the lane that owns the judge. Findings for builders, so
in one language.

- **Card:** INT-S-E (Ring 0, a measurement tool; no product behaviour changes)
- **Date:** 2026-11-25
- **Tests:** `tests/unit/test_judge_eval_counts_ints_e.py`

## What was wrong

`tools/judge_eval.py` validated a reply without the product's date normalisation and mapped any reply outside the
schema to `unknown` with confidence 0, with no count (`GatewayEval.chat_json`, lines 69-71 on master). So a reply with
a sentinel quote date (`0000-01-01`) was a "reply outside the schema" here and a valid `unknown` on the product path
(`libs/tb_common/llm.py`, `no_sentinel_date`, D-958), and the report never said how many there were.

## What changes

- The reply is read in the product's order, calling the product's own `no_sentinel_date` (not a copy): null for
  absent, sentinel date, then the schema.
- The summary JSON (printed and in `--out`) adds `schema_invalid` (replies outside the schema, with `schema_invalid_rules`
  by path and rule), `placeholder` (an `unknown` with a quote, a sentinel date or a confidence, with
  `placeholder_kinds`), and `per_criterion_counts`. Scoring is unchanged (an invalid reply still scores `unknown`), so
  the agreement and the exit code are unchanged.
- `--out FILE` writes the summary plus, per call, the finish reason and the token counts the gateway returned (`null`
  where there is none, as on the stub).
- On a TEST stack, `--gateway-url` runs only with `--model` set to the build's alias on the route (route `dev-stub` in
  `models/routing.yaml`, or an id listed by `GET <gateway>/v1/models`). With none, the gateway answers `502
  upstream_down` (the route's first build is a stub that is not running); with the served name, `403
  class_route_mismatch`. The tool's help says so, and each refusal ends in one plain line on stderr and exit code 2.
  Any other refusal is raised as before. The gateway is not changed.

## Not done here

The product's own placeholder handling (an `unknown` carrying no confidence or quote) is the separate normalisation
card; this tool only counts it.
