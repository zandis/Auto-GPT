# D-595 The chart-number rule a box runs under is recorded beside the site key, and another is refused

- **Task:** a patient-identity card from the integrator (2026-11-12), found by lane D's work on #387 (the installer
  asks the chart-number rule); follows D-591
- **PR:** this branch (`agent/DIN-chartno-rule-recorded`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** T-612 (the site key's fingerprint is recorded the first time and another key is refused), D-301
  (`TB_CHARTNO_RULE`), D-591

## Context

A pseudonym is the keyed hash of the chart number written the site's way. Two things decide it: the site key and
the chart-number rule. The key is guarded: its fingerprint is stored the first time and a night under another key
is refused. The rule was not. A box whose `.env` was removed while its data volumes were kept looks fresh to the
settings wizard, which can then write another rule: every patient gets a second pseudonym, opt-outs registered
under the first no longer match, and the only sign was the key check's message about a wrong site key, when the
pid map happened to hold a row the new rule changes.

## Decision

1. **The pid map records the rule** (`site_key.chartno_rule`, the rule's canonical text, `asis` for none) with the
   site key's fingerprint, the first time.
2. **A night under another rule is refused**, by the same check that refuses another key
   (`PidMap.site_key_problem`), with a message that names both rules and the setting. The rule's text holds no
   patient data.
3. **A box from before this card** has no recorded rule. Its first night adopts the rule in force, and only when
   the key and that rule give back **every** pseudonym the map holds, the staged nights' too (one full read of
   the map, once). The existing five-row probe is not enough: a rule that drops leading zeros changes only the
   patients who have them. What is adopted is the rule in force that agrees with the whole map; where every
   stored chart number is already written the new rule's way, that may be a rule set after the first night, and
   it changes nobody the box holds. Where the check fails, the message says the rule may be what changed, and
   nothing is recorded.
4. **Changing the rule on purpose** is a re-key of every patient and is not offered: it needs the same care as a
   new site key (a new box, or a planned migration), and no command does it silently.

## What this guard does not cover (said so nobody reads it as the whole repair)

- **A box with no trial database**: the rule is recorded in the pid map only. The lake's `site_key.json` holds the
  fingerprint alone (lane B's file), so there a night under another rule is not refused.
- **Other makers of pseudonyms** run under their own process's `TB_CHARTNO_RULE` and do not ask the pid map: the
  orchestrator's `/setup/pseudonym` (site set-up, the opt-out desk), the candidates and scenario paths, the data
  core API, `tools/keys.py`. An orchestrator container with another rule than the adapter is not noticed.
  `trialbox doctor` compares the key's fingerprint only. Sent to the integrator: the smallest step is a doctor
  check of the recorded rule against the rule in force, in every container.
- The text of a rule (`digits:8`, `hex:8:lower`) is now a stored format; a test pins it.

## Not in this card

- The lake's own `site_key.json` and the settings wizard (lanes B and D): the wizard can read the recorded rule
  through the adapter before it offers the question.
