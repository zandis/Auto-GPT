# The support bundle's scrub: one function for every byte (H-71, 2026-11-22)

**Reader:** the people who build TrialBox: lane H, the integrator, the independent reviewer of this export, and the
author of gate 5's `prepare_output`. Findings for builders, so in one language.

Card H-71 (high-risk: an export), decision D-1354. Findings in the register's `--add-from` form:
`support-bundle-scrub-2026-11-22/findings.json`.

## Pull request body (draft)

The support bundle (`tools/support_bundle.py`, D-405) let through pseudonyms and screening numbers in log lines, and
secrets that the name-based pass did not know: `?password=`, `TB_SMTP_LOGIN`, the second line of a quoted value, a
YAML block value, a commented-out line. Its update history and the ops snapshot's update rows carried each step's
detail as text. This card does what the integrator ordered on 2026-11-20 (07:10 and 09:41 UTC) and ruled on
2026-11-22 (04:31 UTC): the bundle's scrub is built as a function of its own, `tools/bundle_scrub.py`, and every byte
of text that enters a bundle goes through it.

- `scrub_text(text)` is pure. It reads only the declarations of `libs/tb_common/config.py` and `PID_HEX_LEN` of
  `libs/tb_common/crypto.py`, parsed and not imported, so the host's python3 can run it. Gate 5's `prepare_output`
  can call it. No file of draft #1295 is touched.
- `Bundle.add` and `Bundle.leave_out` scrub each name, text, source and left-out line as it comes in. `Bundle.seal`
  scrubs every member again after the line removal and the secret passes, and the manifest is scrubbed too.
  `_write_tar` is the one writer into the archive: it refuses, before writing anything, a member whose name or text
  the scrub would still change.
- The update history: each line's own fields (`at`, `bundle`, `box`, `step`, `ok`) are kept. Every other field
  (`detail`) becomes `{"type", "length"}`, and a line that is not JSON becomes its length. The ops snapshot's update
  rows and the builder's own caught errors (a failed snapshot, a failed chain verification) are kept the same way.
- A log or a command's output that is not UTF-8 text (UTF-16, binary, a NUL or other control byte) is left out and
  listed in the manifest.
- `.env` and `docker compose config` are scrubbed before the old name pass, which reads one line at a time.

### What changes for a box

- A bundle shows `[pseudonym #kqztv]` and `[screening-no #bdfgh]` where it showed tokens. The five letters come from
  a key made for that bundle and never kept. One patient has the same tag throughout one bundle; another bundle gives
  that patient other letters. A tag cannot be turned back into a token or compared across bundles.
- More is `[redacted]`: query and form values of secret names, URL userinfo (also a user with no password), header
  values, bearer tokens, every PEM block (certificates too), the whole of a multi-line secret.
- `history.jsonl` no longer says why a step failed, only the error's type (`CalledProcessError`, else `text`) and
  how long the text was. Support reads the reason on the box (`trialbox ops`), not in the bundle.
- A UTF-16 or binary log is no longer in the bundle. Its name and why are in `MANIFEST.json` `left_out`.
- A line with an encoded character (`%2F`, `\u0022`, `&quot;`) that held a token or a secret is kept decoded and
  scrubbed: its escapes are gone, so it reads as plain text (review round 1, H1).
- `-u user:password`, `--password X`, `<password>` elements and a value under `password:` are `[redacted]` too.
- A bundle takes longer to make: about 50 s for each 15 MB log in this container.
- Some ordinary words are masked as well (the over-masks below). A bundle is a little harder to read. It does not
  get bigger.
- Nothing changes for the operator's command line. A scrub that cannot read its declarations refuses the bundle:
  nothing is written.

### The paths by which text enters a bundle, each through the scrub

| Path | Member | Test |
| --- | --- | --- |
| `deploy/.env` (also commented-out lines) | `env.redacted` | planted corpus |
| update history | `history.jsonl` (type and length) | planted corpus; `test_the_update_history_keeps_an_errors_type_and_length_only` |
| ops snapshot (update rows, secret FILE names, backups) | `ops-snapshot.json` | planted corpus (a secret file named by a pseudonym) |
| host health | `health.json` | planted corpus (JSON member) |
| `installed.json`, `release.json` | `release.json` | planted corpus |
| audit verification's messages | `audit-verify.json` | planted corpus |
| every command (doctor, check_host, compose config, ps, restarts, df, nvidia-smi) | `cmd/*` | planted corpus; binary output left out |
| collected service logs | `logs/<day>/<svc>.log` | planted corpus; a UTF-16 log left out |
| `--add` file, its name and its folder | `added/<name>`, manifest `from` | planted corpus |
| builder's own caught errors | `ops-snapshot.json`, `audit-verify.json` | `test_the_builders_own_errors_leave_as_type_and_length` |
| a pass that writes a member in place | any | `test_a_member_put_in_past_add_is_scrubbed_before_it_is_written` |
| member names | archive names | planted corpus (names checked) |
| the manifest | `MANIFEST.json` | planted corpus |
| the refusal printed by `main` | stderr (not the bundle) | scrubbed with `scrub_text` |
| any new archive writer | — | `test_every_function_that_writes_into_the_archive_goes_through_the_scrub` |

The planted corpus test builds a real bundle. Every source above holds every kind: pseudonyms in lower case, upper
case and the short form, three screening-number shapes, every declared secret setting and `TB_SMTP_LOGIN`, query,
form and percent-encoded secrets, userinfo, bearer, cookie, header, a PEM block, JSON and escaped JSON, a multi-line
value, a YAML block. The test then reads the archive's bytes and names for each value raw, URL-encoded (both ways),
JSON-escaped, base64 (both alphabets), lower and upper case.

### What the scrub does not catch

Corrected after review round 1.

- Free text: names, addresses, dates of birth and diagnoses typed into a log message. Only the data-handling scan's
  line removal (D-747) and the log scrubber's fixed patterns stand there. A name in a script the scan does not know
  leaves (H71-06).
- Screening numbers in three shapes leave (H71-05). The site prefixes are in the console's database, which the
  host's bundle does not read.
  - A lower-case prefix glued to the digits (`tbx0042`).
  - An all-digit prefix (`20260042`).
  - A lower-case prefix before `.`, `#`, `/`, `:` or a space (`scr.0042`).

  Caught: a prefix in any script ending in `-` or `_`, capitals and digits before `.`, `#`, `/`, `:` or a space, and a
  capital then letters glued to the digits (`Scr0042`).
- A pseudonym glued to other hex digits (`deadbeef` and 32 hex digits make one run of 40). Its first 8 digits shown
  bare (without `…`) when they are all decimal (about 2 in 100 pseudonyms). Any other cut of a pseudonym (`pid[:12]`). A 64-digit sha256 and
  a 40-digit commit are kept on purpose.
- A secret with no name or form next to it (a bare value in prose) when it is not a value of the box. The box's own
  values are still found by value (D-723).
- A secret in base64 or another encoding not listed under H1 below (Basic headers are caught). A PIN of three digits
  or fewer next to a secret's name: those digits are kept as a count. `mysql -pSECRET` (the value glued to the flag).
- A secret whose `KEY="...` or `key: |` line was cut off before the member starts: a rotated log, a day's boundary,
  or the first 64 MB read limit of a log. A PEM body is the exception: it goes with its END line. A cut that the
  builder makes is after the scrub (H2).
- Opt-out pids of another shape (`[A-Za-z0-9_-]{8,64}`, `tb_common.optout`) that are not minted pseudonyms.

### Review round 1 (#1314, head f944d626: fix first; fixes in db6e109d and the commit after it)

Every test below was red on f944d626 and is green after the fix. The class each finding belongs to was closed, not
only the instance shown. Tests are in `tests/unit/test_support_bundle_review1.py` unless named otherwise.

| Finding | The class closed | Test |
| --- | --- | --- |
| H1 a pseudonym after `%2F`/`%22` | A line holding any encoded character is decoded (percent, twice- and three-times-percent, `\u`/`\x`/`\U`, HTML entities, `=3D`) and scrubbed. Covers pseudonyms, screening numbers, secret keys and values. | `test_h1_*` (16 encodings x 2 token kinds, 6 secret forms), build level `test_h1_the_reviewers_lines_leave_no_pseudonym_in_a_built_bundle` |
| H2 a PEM block cut by the 16 MB truncation | Every cut of text before the scrub now comes after it: `Bundle.add` and the container list's 200 characters. The other cuts (history lines, list items, the 64 MB read) cut whole items or the end. A PEM body without its BEGIN line goes with its END line. | build level `test_h2_a_pem_block_cut_by_the_size_limit_leaves_no_body`, `test_h2_a_yaml_block_secret_cut_by_the_size_limit_leaves_no_line`, `test_h2_every_cut_is_after_the_scrub`, `test_h2_a_pem_body_with_no_begin_line_is_masked` |
| M1 secret forms | `--flag=value` and `--flag value`, `-u`/`--user` user:password, XML elements, `key = value` with spaces, a YAML value or list below its key, a JSON value on the next line (also commented out), userinfo up to the last `@` (a `/` or `@` in the password), an encoded key | `test_m1_secret_forms_are_replaced` (21 forms), build level `test_m1_the_reviewers_forms_leave_nothing_in_a_built_bundle` |
| M2 screening prefixes | Any script; `.`, `#`, `/`, `:`, a space; a capital and letters glued (`Scr0042`); the docstring says what the console takes | `test_m2_*` |
| M3 the ops snapshot's update rows | (test only) | `test_m3_the_ops_snapshots_update_rows_keep_type_and_length`: red with the reviewer's mutant M5 |
| M4 the writer guard | Every write call of the two modules (`add`, `addfile`, `make_archive`, `GzipFile`, `ZipFile`, `write_bytes`, any open for writing, module level too) must be on a reviewed list. Only the command dispatcher imports the builder. | `test_m4_*` (the finder tried on 6 probes) |
| Speed: userinfo quadratic | The scheme starts where no scheme character stands before it, and the userinfo is at most 256 characters. Every rule was tried on a 1 MB or 256 KB worst-case line (20 shapes). | `test_speed_every_rule_is_linear_on_a_long_line`: before, one 1 MB hex line was killed at 120 s; after, at most 0.72 s each |
| L1 bare 8-hex short form | `pid[:8]` bare when it holds a hex letter; with `…` always | `test_l1_*`, `test_l1_the_short_form_with_its_ellipsis_is_masked_even_all_decimal` |
| L2 names that collide after the scrub | The second gets `~2` before its extension | `test_l2_*` (build level) |
| L3 a trailing invalid byte | Dropped only when the caller cut the bytes (`as_text(..., cut=True)`, the log read limit) | `test_l3_*`; the card's own round-1 assertion in `test_support_bundle_scrub.py` was made stricter to match |

The planted corpus (`test_support_bundle_planted.py`) carries every new form, and the whole bundle is checked again.

Mutation pass after the fixes. 31 mutants of the scrub and the builder, one at a time: each rule dropped, each
boundary loosened, each path skipped, a side writer, a `tar.add` helper. 30 were caught on the first run. The
survivor cut a member before the scrub; the orphan-PEM rule hid it. `test_h2_a_yaml_block_secret_cut_by_the_size_limit_leaves_no_line`
now catches it: 31 of 31.

Measured on this container: scrubbing a realistic 15 MB log takes 39 s and the writer's check 12 s. A bundle of
several large logs takes minutes.

### Near-misses kept, and over-masks owned

Kept (`test_a_near_miss_is_left_alone`): 64- and 40-digit hashes, 31- and 33-digit hex runs, UUIDs, ISO dates and
timestamps, container names and counts (`restarts=2`), the review's JSON (`authserv`, `512m`, `rtxpro6000`), ULIDs,
ids of three digits or fewer (`OPS-047`), `_FILE`/`_PATH` settings, `TB_GPU_KEY`, `"key"`, `monkey`, `bypass`,
`passed`, counts next to a secret's name, flags (`=true`), versions and ports, `iso-8859-1`. Why: a pseudonym is
exactly `PID_HEX_LEN` hex digits with no hex digit beside it; a screening number has at least four digits after a
prefix; "key" alone, and a word that only contains a secret's word, is not a secret's name.

Masked though it may not be a token (`test_what_is_masked_on_purpose_though_it_may_not_be_a_token`): a decision number
of four digits (`D-1354`), a W3C trace id (32 hex digits), `RFC3339`/`ISO8601`, a day-month-year date
(`22-11-2026`), a word joined to a screening number in a file name (`report-RA01-0042`), the value of any setting
whose words say secret (`TB_CONSOLE_SECURE_COOKIE=…` other than a flag). The scrub masks too much rather than too
little.

## Checks run

See the train-ready line on #639 for the counts. Every test file that names the bundle or the scrub was run after the
last commit.

## Not verified

- Not run on a box. Real `docker compose config`, doctor and journal output were not used: synthetic outputs stand
  in for them.
- Measured only in this container (see Review round 1), not on a box's disk and CPU.
- Review round 1 asked for "fix first". This round's fixes wait for the integrator's re-check of the two Highs.
