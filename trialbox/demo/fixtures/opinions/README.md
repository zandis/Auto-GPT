# Recorded opinions for the demo (T-515)

The demo box runs the test model, which never disagrees with itself, so its pages would never show the two-model
check. Every `*.json` file in this folder lays first-check and second-check opinions over the demo's candidate list,
so a clinician sees what an agreement and a disagreement look like. The console reads the folder only on a DEV or
TEST box, from `TB_DEMO_OPINIONS` (the demo sets it to this folder). The shape and the matching rules are in
`services/console/recorded_opinions.py`. Decision: `docs/decisions/D-323-recorded-opinions.md`.

## Files

* `synthetic.json`: made up by hand (`source.kind` `synthetic`). Every quote starts with `[synthetic]` and every
  opinion shows "synthetic example" on the page. No model wrote them.
* `g1-short-run.json` (slot, not here yet): the agree and disagree cases from the G1 short run of the real model
  pair on the synthetic hospital. Drop it in with `source.kind` `recorded` and `source.name` naming the run (for
  example "G1 short run, commit abc1234"). Give each case its `pid` when the run's pseudonyms match the demo seed;
  without one the case goes to the first listed patient with a matching verdict. The page shows "recorded run" with
  the run's name. Keep `synthetic.json` or delete it once the recorded file covers an agreement and a disagreement.

A case lands only on a listed patient whose criterion already has the verdict the case implies: the shared verdict
when the checks agree, unknown when they disagree. A case that finds no such patient is left out.
