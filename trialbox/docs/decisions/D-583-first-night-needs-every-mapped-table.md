# D-583 On the first night every table the site's mapping declares must be there with rows

- **Task:** NEW-DIN-8 (finding DIN-008 of the deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/08-data-input.md`; plan v7.2 section 5, lane E, wave 0)
- **PR:** this branch (`agent/NEW-DIN-8-first-night-required-tables`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** T-611 (the completeness gate: a night is compared with the last good night), D-271 (the override of
  one night, with an audited reason)

## Context

The completeness gate holds a night whose table is missing, empty or much smaller than on the last good night. On the
first night there is no last good night. `required_tables` is empty unless a site fills it, and no shipped settings
file does. So `lab.csv` missing on night one passed, moved `CURRENT` and became the baseline; the table was never
asked for again. Go-live night is a first night.

## Decision

1. **On a full night with no last good night, every table the site's mapping declares must be present and have
   rows.** A missing or empty one holds the night, with a message that names the table and the way out.
2. **The way out is `feed_completeness.optional_tables`**: a table this site does not have (no claims extract, no
   registry) is listed there, once, at set-up. A site mapping already declares only the tables the site has; this
   list is for a table that is declared and may be empty.
3. **No setting turns the rule off.** The product's entry (`adapter.cli.build_config`) always sets it. The override
   of one night (D-271: `TB_FEED_OVERRIDE='<night>: <reason>'`, audited) lets a first night through as it lets any
   other incomplete night through.
4. `AdapterConfig.first_night_all_tables` is off by default for the tools and tests that build a night from a
   partial feed of their own making (`tools/bench.py`, `tools/scenarios.py`, the unit tests of one table). They are
   not a site's night.
5. A held first night publishes nothing: `CURRENT` is not written, so the next attempt is again a first night.

## Not in this card

- The first-load path (`adapter.backfill`, lane B's) has its own report and no completeness gate; whether a first
  load must pass this rule before it publishes is sent to the integrator as a finding.
- The site set-up page and the installer asking which tables the site has (lane C, lane D): the setting exists; the
  question at install is theirs.

## Consequences

- A first night with a missing extract is held and says which table. Nothing is loaded with a hole in it.
- A site with fewer tables than its mapping declares must list them under `optional_tables` before its first night.
