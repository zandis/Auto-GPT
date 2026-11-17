# The answer key of the public accuracy sets, by version (D-1104)

The answer key of a public set is what `tools/public_accuracy` builds for it at run time from the pinned sources:
the gold labels (`built/gold`) and the placed facts they are scored against (birth dates, the age and sex lines
written into a protocol, in `built/site`). It is not committed. `MANIFEST.json` pins what is known of each version:

* **v1**: the key as launch P1b used it (run `box-20261116T074927Z-3b2f5e38`), with the sha256 of each file of its
  stored `built/gold`. `--key v1` still builds it byte for byte; it is never overwritten.
* **v2** (the default): the P1b review's corrections B1 to B3, and the rows of P1b's key they change, by id. It also
  marks a pair `conflicted` (D-1064) when its label is eligible while the same physicians' criterion labels for that
  pair exclude the patient (an inclusion not included, or an exclusion excluded). The pair is never relabelled. The
  rule is read from the gold alone (`key.conflicted`, the scorer's S1 definition). A v2 build writes the marks to
  `gold/conflicted.json`. The target "no eligible patient excluded" is read without them, beside the figure with
  them. Only eligible pairs are marked: "would consider" does not claim every criterion met. On P1b's sigir gold the
  rule marks 6 of the 46 eligible pairs, listed here under `conflicted`; it leaves 10 "would consider" pairs unmarked.

A built folder names its version in `gold/key.json` (none: v1). `python -m tools.public_accuracy key-diff OLD NEW`
lists every row that differs between two built folders, and why. See `tools/public_accuracy/key.py`.

The ids are the public sources' own: SIGIR 2016 (NCBI TrialGPT copy, see `eval/criterion_ml/LICENSE.NCBI`) and
JMED-Personas by Sociocom (NAIST), CC BY 4.0. No note text is kept here.
