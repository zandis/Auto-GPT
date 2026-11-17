# What a 50-line site list moves on launch P1b's drafted concepts (measured 2026-11-17, D-1128)

**This is a made-up list.** It is no hospital's list, and its figures are a mechanism and a scale estimate, not a
product figure. Its observation, medication and procedure codes are made up and mean nothing.

**What was measured.** Of the 1,273 concepts the compiler drafted from launch P1b's public ClinicalTrials.gov
protocols (not demographic), how many `Terminology.map` resolves without the model, before and after loading the
made-up list `tests/fixtures/terminology/site_list_synthetic.csv` (50 lines) through the real `site-list` command.

**How.** The concepts come from the committed list `tests/fixtures/terminology/p1b_concepts.csv`, derived from
`work/raw-traces.json` of P1b's `sigir.tgz` (sha256 `667d92f5...`, the file `12cd4580...`; not committed, read as
data in an empty scratch folder). From the archive and from the list the tool gives the same 266. The test
`tests/unit/test_h17_nhi_import_and_site_list.py` holds every number below.

```
python -m tools.terminology_install site-list tests/fixtures/terminology/site_list_synthetic.csv --name synthetic --dir <DIR>
python -m tools.terminology_coverage --concepts tests/fixtures/terminology/p1b_concepts.csv [--installed <DIR>] --json
```

| Domain | Concepts | Before (committed data only) | After the 50-line list | Newly mapped | Of them for review | Lines of the list |
| --- | --- | --- | --- | --- | --- | --- |
| condition | 588 | 255 | 302 | 47 | 0 | 20 (ICD-10-CM, real codes) |
| observation | 308 | 5 | 50 | 45 | 45 | 15 (made-up LOINC-shaped) |
| medication | 177 | 6 | 28 | 22 | 22 | 9 (made-up ATC-shaped) |
| procedure | 145 | 0 | 16 | 16 | 16 | 6 (made-up NHI order codes) |
| encounter | 51 | 0 | 0 | 0 | 0 | none (department lists only) |
| claim | 4 | 0 | 0 | 0 | 0 | none |
| **all** | **1,273** | **266 (20.9 %)** | **396 (31.1 %)** | **130** | **83** | **50** |

**Reading it.**

- Every newly mapped concept comes from the list (method `site`, 130). The concepts mapped before keep their answers.
- The 83 for review are the rows whose code no shipped or loaded table holds: a site code nothing can match goes to a
  person (D-1113). A real site's LOINC or ATC codes would be in a loaded table and would not be for review.
- 50 lines map 130 concepts, 2.6 per line, because the list was written over the head of the frequency list, in the
  trial's own words. A hospital's list names its own lab and drug items, which seldom equal a trial's words.

**The long tail, and how long a real list must be.** Lane E measured 944 distinct unresolved names before TERM-1, the
200 most frequent covering 416 of 1,160 occurrences. On master today (with TERM-1):

| The most frequent unmapped names | Occurrences they cover, of 1,007 |
| --- | --- |
| 50 | 132 (13.1 %) |
| 100 | 219 (21.7 %) |
| 200 | 319 (31.7 %) |
| 400 | 519 (51.5 %) |
| all 888 | 1,007 (801 names occur once) |

So a list in the trial's own words would need about 400 lines to map half of what remains on one launch, and a new
launch brings new single names. A site list is the right tool for the hospital's own codes (its local lab and drug
items, its ICD-to-local list), not for trial wording: that long tail needs the synonym and model steps (lane A2) and
the licensed tables loaded at install (LOINC, ATC), whose effect cannot be known until a site loads them.

**The NHI open data, by the same tool.** A made-up extract in NHIA's layout (D-1127) moves 266 to 281 (medication 6
to 13, all for review; procedure 0 to 8, 3 for review), only because some of its made-up names equal words P1b drafted.
What the real lists move is not known until they are fetched and loaded.
