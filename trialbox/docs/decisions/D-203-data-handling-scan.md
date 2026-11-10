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

*Where it runs.* `make data-scan` (every tracked file, about 80 s on four cores); `python -m tools.data_scan --log
<file>` on a test log (the CI unit job scans its own log); the pre-commit hook `trialbox/.pre-commit-config.yaml`
(installed from the repository root with `pre-commit install --config trialbox/.pre-commit-config.yaml`, because
the root's config is Auto-GPT's); the `data-scan` CI job on every pull request and push (in `trialbox-e2e.yml` with
this card, moved into `trialbox-ci.yml` by D-206). RUNBOOK §3 "Build gate: the data-handling scan".

*Evidence.* `tests/unit/test_data_scan.py`: one test per pattern against its planted file in
`tests/fixtures/data_scan/positives/` (each line must hit; the files are fictional and say so in their first line),
the evasions (a zero-width space inside an ID, full-width digits, a chart number split by a space, a figure dash and
a minus sign in a phone number, a name in katakana), the look-alikes that must stay clean without any allowlist
(`tests/fixtures/data_scan/negatives/clean.txt`: a pseudonym, LOINC codes, a ULID, an ISO date alone, CJK words
beside a date, a wrong check digit, a 12-digit timestamp, decimals, hex ids), the check digits against known values,
the masking, a tarball and an xlsx, a `.csv` under `services/` refused as a data file, the allowlist's reason rule,
the CLI's exit codes on a file and on a log. Checks on this branch: see the pull request (the counts of `make lint`,
`make test`, `make data-scan` and the hook run).

*After the adversarial review* (a fresh Fable session, 2026-11-10, on the diff; its High findings on the scan,
H1 to H5, are answered here). Structured data: the chart-number labels accept quotes, underscores and `為`/`は`
between label and value (`"mrn": "…"`, `patient_mrn:`, `chart_no=`, `病歴番号`, `病历号`), 5 to 12 digits; an HL7 PID
segment's PID-3 is its own pattern (`hl7_pid`); tables (`.csv`, `.tsv`, `.xlsx`, `.parquet`) are also read with each
value labelled by its column header; a name and a date up to three lines apart count (pretty-printed JSON). Names:
an anchor word (姓名, 氏名, 患者, 病人 …) may stand directly before the surname, an honorific or 男/女 directly after,
Japanese given names take up to three characters (multi-character surnames only), and the dates include the compact
`19600504`, `04/05/1960`, ROC `民國49年` and wareki `昭和35年` / `S35.5.4`; katakana names may be joined by a comma,
tab or 、 or written solid after フリガナ/カナ/氏名. Encodings: BOMs first, UTF-16 by NUL parity, UTF-8, else every one
of cp932, cp950, EUC-JP and GB18030 that decodes (Latin-1 is gone); a binary of an unknown kind is an `unscanned` hit,
known kinds (images, fonts, PDF, compiled code) are skipped. Archives: by magic bytes as well as by name (a renamed
or nested zip in a gzip is opened), workbooks through openpyxl (cells by row, dates as ISO), documents through
python-docx (paragraphs and table rows), Parquet through pyarrow, decompression bounded at 32 MB, and any unreadable
archive (encrypted, corrupt) an `unscanned` hit rather than a crash. Normalisation drops every format character and
variation selector and more dash kinds; numbers may be split by dots, slashes and tabs too (not inside an unlabelled
ID, where a dot matched drawing coordinates); `+819024681357`, `886912345678` and labelled `tel0912…` numbers are
found (`tw_phone_intl` is new); a 12-digit マイナンバー alone in a delimited cell is found; 6-digit insurer numbers too.
False positives the review proved are closed: a phone number after a hyphen (`TB-08-2026-0001`), a 4-4-4 group
outside a field, the review's place and word examples. The hook's repository-root paths were already right (the
review asked to confirm: `tests/unit/test_data_scan.py` now runs `main()` from the root with root-relative names).
The scan of the tree takes about 80 s on four cores.

*Not done, and limits.* The required-check setting on `master` is the owner's (GitHub settings). Still not found: a
name that is not on `phi_guard`'s surname lists; a FHIR name split into `family` and `given` far from its
`birthDate`; a bare chart number in prose without its label until the sites state their formats (survey questions 24
to 26); an old-format resident certificate (two letters); identifiers inside `.duckdb`, `.xls` or `.sqlite` files
(reported `unscanned`, a hit, unless allowlisted with a reason). The scan reads the pull request's tree, not every
commit of its history, and a pull request can change the patterns, the allowlist and `.gitattributes` it is checked
against (review M13): T-002's CODEOWNERS should name these three files. The synthetic hospital's generated files are
allowlisted by path, so a real row planted inside them would pass; a check that regenerates them and compares (with
T-006's goldens or a follow-up) would close that. The sites' local code systems are not in the patterns yet. A
4-4-4 digit group alone in a field, or a 12-digit number alone in a cell, passes the マイナンバー check one time in ten:
such a false positive is allowlisted with its reason.
