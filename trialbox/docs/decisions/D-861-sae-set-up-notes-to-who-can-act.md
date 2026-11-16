# D-861 The SAE page's per-study set-up notes go to who can act; no empty deadline line

- **Task:** NEW-DEMO-2, from lane G's walk of 2026-11-16 (the demo image of master 2d354036, zh-TW), handed to lane C2 by the integrator ahead of the sprint list · **Date:** 2026-11-16
- **The finding:** an investigator on `/sae` saw, for every study, "The site has not confirmed these deadlines ... the country's default", "The study has not chosen its SAE rule set" and a deadlines line with nothing in it. D-797 had moved the page's two alerts to the set-up roles; these per-study notes in the rules card (`_sae_rules.html`) had not moved.
- **The rule:** the card's "not confirmed" note and its rule-set problems render only for a role with `study.setup`, the one that chooses and confirms the rule set on the study's set-up page. The confirmation itself (who confirmed it, when) still shows to everyone who sees the card. A deadlines line (the study's, or the follow-up one) renders only when it has a deadline.
- **Unchanged:** the deadlines, the clocks and the reports themselves, and who may see the page.
- **Held by:** `tests/console/test_the_browser_walks_cosmetic_findings.py::test_the_sae_set_up_notes_go_to_who_can_act_and_no_empty_line_is_printed`, which fails on master's template.
