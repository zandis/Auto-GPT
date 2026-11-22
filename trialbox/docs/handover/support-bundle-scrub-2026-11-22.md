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

- Free text: names, addresses, dates of birth, diagnoses typed into a log message. Only the data-handling scan's line
  removal (D-747) and the log scrubber's fixed patterns stand there. A name in a script the scan does not know leaves.
- A screening number whose site prefix is lower-case letters glued to the digits (`tbx0042`), or all digits
  (`20260042`). The site prefixes are in the console's database, which the host's bundle does not read. A prefix that
  ends in `-` or `_`, any ruleset id with `-`, and capital letters before the digits are caught (H71-05).
- A pseudonym glued to other hex digits (`deadbeef` and 32 hex digits make one run of 40) or cut short other than the
  8-digit `…` form. A 64-digit sha256 and a 40-digit commit are kept on purpose.
- A secret with no name or form next to it (a bare value in prose) when it is not a value of the box. The box's own
  values are still found by value (D-723).
- A secret in base64 or another encoding other than a Basic header, a secret split by a line wrap the line rules do
  not know, and a PIN of three digits or fewer next to a secret's name. Those digits are kept as a count.
- Opt-out pids of another shape (`[A-Za-z0-9_-]{8,64}`, `tb_common.optout`) that are not minted pseudonyms.

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
- Not measured: how long the scrub takes on a 16 MB log. Each member is scrubbed at least three times (add, seal,
  the writer's check).
- No review yet. The card waits for one independent review before it rides.
