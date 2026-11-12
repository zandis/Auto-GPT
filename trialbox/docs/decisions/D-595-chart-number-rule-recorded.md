# D-595 The chart-number rule a box's pseudonyms were made with is recorded beside the site key, and another is refused

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
3. **A box from before this card** has no recorded rule. Its first night records the rule in force, after the
   existing check that the key and rule in hand give back the pseudonyms the map holds; where that check fails
   the message now says that the rule may be what changed.
4. **Changing the rule on purpose** is a re-key of every patient and is not offered: it needs the same care as a
   new site key (a new box, or a planned migration), and no command does it silently.

## Not in this card

- The lake's own `site_key.json` and the settings wizard (lanes B and D): the wizard can read the recorded rule
  through the adapter before it offers the question.
