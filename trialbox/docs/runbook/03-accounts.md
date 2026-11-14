# 3. Accounts

Administrators add accounts on **Users** (`/ops/users`). For a viewer or CRO account the one-time password shows once,
in a read-only field; hand it over in person or by phone (D-133). For a coordinator, investigator, steward, privacy or
administrator account only an enrolment code is shown (D-719): its holder signs in once with it at **First sign-in
with an enrolment code** (`/enrol`), chooses the password and sets up the authenticator; the code is good for
`TB_CONSOLE_ENROL_CODE_HOURS` (default 24). Nobody else sets both factors of such an account within 30 days unless
the holder signed in in between; where a steward or another administrator exists, the opening, a change of studies or
a reset waits for them on **Account requests** (`/ops/accounts/requests`), and the code or password is shown to the
person who confirms. Five failed sign-ins lock an account for 15 minutes; sessions end after 10
minutes idle or 8 hours; local accounts give a TOTP code after the password ([§12](12-identity-and-tls.md)). Roles and the work they do: [User guide](../USER_GUIDE.md). In the POC container:
`docker exec -i trialbox-console-1 python -m console.cli bootstrap-admin|add-user NAME --role ROLE|reset-password
NAME|disable NAME|list-users`.

## Build gate: the data-handling scan (D-203)

Real patient data never enters the repository, CI, a log or a support bundle (TB-SITE-03). `make data-scan` scans
every tracked file (patterns in `tools/data_scan_patterns.yaml`) for chart numbers after their label or in an HL7 PID
segment, Taiwan IDs and マイナンバー with valid check digits, Japanese insurer numbers, Taiwanese and Japanese phone
numbers, and Chinese, Japanese or katakana names beside a date (western, compact, ROC or wareki; on the same line or
up to three lines apart). Full-width characters, invisible characters, other dashes and numbers split by spaces,
dots or hyphens are normalised first; tables (`.csv`, `.tsv`, `.xlsx`, `.parquet`) are also read with each value
labelled by its column header; archives and office files are read member by member, by content as well as by name;
other encodings (UTF-16, Big5, Shift-JIS, EUC-JP, GB18030) are decoded. A binary of an unknown kind is reported as
`unscanned`. A data file type (`.csv`, `.xlsx`, `.ndjson`, `.parquet`, `.duckdb`, `.hl7` ...) outside
`tests/fixtures/`, `eval/`, `catalogue/`, `refdata/` and the reference tables `.gitattributes` names is refused. Exit
2 on a hit; the output gives the file, the line, the pattern and at most two characters at each end, never the value.
The same scan runs on a log (`python -m tools.data_scan --log make-test.log`), on a support bundle or any archive
(`python -m tools.data_scan bundle.tgz`), as the pre-commit hook (`pre-commit install --config
trialbox/.pre-commit-config.yaml`, from the repository root) and as the `data-scan` CI job. A synthetic value that
looks real goes into `tools/data_scan_allow.txt` with its reason; a real one is an incident (TB-SITE-03 §1.7).

## Build gate: the CI jobs (D-206)

`.github/workflows/trialbox-ci.yml` runs on every pull request and every push to master; its first job, `changes`,
skips the others (reported as skipped, which satisfies a required check) when a pull request touches neither
`trialbox/` nor a TrialBox workflow. `make ci` runs the same list locally. Each job has at most 15 minutes; a newer
push to a pull request cancels the older run (pushes to master are never cancelled). The required checks on master
(set by the owner in GitHub): `unit`, `lint`, `contracts`, `goldens`, `data-scan`, `e2e-simple`.

| Job | What it runs | Gates |
| --- | --- | --- |
| `lint` | ruff check and format; actionlint on the TrialBox workflows | yes |
| `types` | mypy strict on libs, services, tools, tests | yes |
| `docs` | `tools/doclint.py`; the decision index; the licence register; the limits lint (`tools/limits_lint.py`: every `timeout=` over 60 s and every `LIMIT`/`limit=` literal in `services/` has a line with its reason in `tools/limits_allow.yaml`; OD-10, T-687, D-471) | yes |
| `contracts` | `make contracts-check` (no hand-edited generated file) | yes |
| `trace` | `tools/gen_traceability.py --check` | yes |
| `unit-shard (i/N)` | `make test PYTEST_N=auto SHARD=i/N`, one job per shard (T-747, D-475: each test file in one shard by a hash of its path) on throwaway clusters from the runner's own PostgreSQL (`tools/pglocal.py`, server and client tools one version), `TB_DATA_DIR` in the runner's temp, then the data scan of its log | through `unit` |
| `unit` | the gate over the shards: every shard passed, `tools.test_shard check` (every collected test ran in exactly one shard), the coverage ratchet on the combined coverage of all shards | yes |
| `cross-card` | `make cross-card`: the tests that fail when two cards meet, first and fast, no coverage (T-747) | yes |
| `e2e-simple` | `make e2e-simple` (D-111) | yes |
| `goldens` | `make goldens-check` (T-006, D-205) | yes |
| `data-scan` | `make data-scan` (D-203) | yes |
| `shell` | shellcheck on every `*.sh` (OPS-076: every warning listed on 2026-11-09 is fixed) | warnings |
| `images` | hadolint on the three Dockerfiles | listed only (2026-11-09: first runs to triage) |

`trialbox-e2e.yml` is the nightly (and on demand): `public_e2e`, the backup drill and the update drill, and the
scale gate `scale-50k` (T-687, D-471: a 50,000-patient synthetic night under the compose memory caps, with a slow
model stand-in; today's failures are expected failures named by card, see [Developing](../DEVELOPING.md)). The
supply-chain gates (lock current, allow-list, pip-audit, licences) are the `lock` job of `trialbox-supply-chain.yml`
(D-185, D-186), not repeated in `trialbox-ci.yml`.
