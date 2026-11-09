**D-203 The data-handling scan: no real identifier in the repository, a log or a bundle, enforced by CI and a
pre-commit hook.** Task T-005 of TB-ASSESS-01 (`docs/reviews/2026-11-09-assessment-and-tasks.md`
§3.1; WS-13.10, a G1 gate; URS-ADM-21, URS-PRV-04, RSK-39, TST-SEC-10), branch `wave0-ci`, no pull request yet
(the integrator opens it). 2026-11-09. Built with synthetic data only; no site sample, no cloud.

*Why.* The data-handling rule (TB-SITE-03, D-145) promises the sites that real patient data never reaches the
repository, CI, a log or a support bundle, and names a CI identifier scan, a pre-commit hook and a `.gitattributes`
rule as its controls. None existed (P-55). G1 needs the scan.

*What.* `tools/data_scan.py` with its patterns as data in `tools/data_scan_patterns.yaml`: a chart number after its
label (病歷號, カルテ番号, MRN, chart no.; 6 to 10 digits; a CGMH-specific format is added when the survey states
it), a Taiwan ID or resident certificate with a valid check digit, a マイナンバー with a valid check digit (grouped
4-4-4, or plain after its label), a Japanese insurer number of 8 digits with its Luhn check digit after its label,
Taiwanese phone numbers (`tb_common.phi_guard.PHONE`, imported, not copied), Japanese phone numbers, a Chinese or
Japanese name (`phi_guard`'s surname lists, imported) beside a date, and a katakana name beside a date. Every line
is normalised first: NFKC (full-width digits and letters, half-width katakana), zero-width characters removed, the
dash variants between digits made a hyphen; digits may be split by a space or a hyphen. Archives are read member by
member (`.tar`, `.tgz`, `.zip`, `.gz`, and `.xlsx`/`.docx` as zips), so a `trialbox support-bundle` output is
scanned as it is. A file with the `tb-data` attribute (`.gitattributes`: `.csv`, `.tsv`, `.xlsx`, `.xls`,
`.ndjson`, `.json.gz`, `.hl7`, `.duckdb`, `.parquet` outside `tests/fixtures/`, `eval/`, `catalogue/`, `refdata/`
and the named reference tables) is itself a hit; the card lists five of these types, TB-SITE-03 §2 adds `.duckdb`
and `.parquet`, and both lists are applied. Output: file, line, pattern and the first and last two characters,
never the value. Exit 0 clean, 2 on a hit, 1 on a broken pattern or allowlist file. The allowlist
(`tools/data_scan_allow.txt`) takes a value or a path glob per line and refuses an entry without a reason; the
repository's entries are the synthetic hospital's generated files, the synthetic PHI notes, the planted positives
and 25 textbook placeholders (A123456789, 090-1234-5678, 山田太郎 ...), each with its reason.

*Where it runs.* `make data-scan` (every tracked file, about 20 s on four cores); `python -m tools.data_scan --log
<file>` on a test log (the CI unit job scans its own log); the pre-commit hook `trialbox/.pre-commit-config.yaml`
(installed from the repository root with `pre-commit install --config trialbox/.pre-commit-config.yaml`, because
the root's config is Auto-GPT's); the `data-scan` CI job on every pull request and push (in `trialbox-e2e.yml` with
this card, moved into `trialbox-ci.yml` by D-205). RUNBOOK §3 "Build gate: the data-handling scan".

*Evidence.* `tests/unit/test_data_scan.py`: one test per pattern against its planted file in
`tests/fixtures/data_scan/positives/` (each line must hit; the files are fictional and say so in their first line),
the evasions (a zero-width space inside an ID, full-width digits, a chart number split by a space, a figure dash and
a minus sign in a phone number, a name in katakana), the look-alikes that must stay clean without any allowlist
(`tests/fixtures/data_scan/negatives/clean.txt`: a pseudonym, LOINC codes, a ULID, an ISO date alone, CJK words
beside a date, a wrong check digit, a 12-digit timestamp, decimals, hex ids), the check digits against known values,
the masking, a tarball and an xlsx, a `.csv` under `services/` refused as a data file, the allowlist's reason rule,
the CLI's exit codes on a file and on a log. Checks on this branch: see the pull request (the counts of `make lint`,
`make test`, `make data-scan` and the hook run).

*Not done, and limits.* The required-check setting on `master` is the owner's (GitHub settings). The scan is
line-based: an identifier split across two lines, or written in words, is not found; a name that is not on
`phi_guard`'s surname lists is not found; a bare chart number without its label is not found until the sites state
their formats (survey questions 24 to 26). The synthetic hospital's generated files are allowlisted by path, so a
real row planted inside them would pass; a check that regenerates them and compares (with T-006's goldens or a
follow-up) would close that. The sites' local code systems are not in the patterns yet.
