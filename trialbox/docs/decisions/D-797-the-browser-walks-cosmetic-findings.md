# D-797 Lane G's browser walk: four cosmetic findings fixed

- **Task:** NEW-DEMO-1, the cosmetic findings of lane G's demo walk (#639, 2026-11-15 05:52), handed to lane C2 by the integrator ahead of the sprint list · **Date:** 2026-11-15
- **1, 3:** a run scope that names neither the whole hospital nor any doctor prints nothing (`_run_scope.html`), not an empty list. An SAE with no reporting clock is listed on the home page as "no deadline yet" with where to choose the rule set (`life.reports.row_noclock`), not "due" with no date.
- **6:** in demo mode the footer names the environment "DEMO".
- **7:** on `/sae` the rules-to-check alert goes to roles with `study.setup`, and the missing trial office mailbox to roles with `study.setup` or `site.setup`. These are the people who can act on them; an investigator no longer sees either.
- **Held by:** `tests/console/test_the_browser_walks_cosmetic_findings.py`. Finding 2 (the stale-data banner) has no bug on this side; lane B2 makes the seed's dates relative to today.
