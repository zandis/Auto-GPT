# The support bundle's scrub, follow-up: the flake, encodings, base64, the read cut (H-76, 2026-11-22)

**Reader:** the people who build TrialBox: lane H, the integrator, the reviewer of this export, and the author of
card H-79, which may move the scrub's core into `libs/tb_common`. Findings for builders, so in one language.

Card H-76 (high-risk: an export), the follow-up of H-71 (#1314, decision D-1354; no new decision). It covers the
Lows of the second read of #1314 (2026-11-22 08:03 UTC), the two items of 09:52 UTC (base64, the 64 MB read cut), and
a flake of H-71's own test on master. Findings in the register's `--add-from` form:
`support-bundle-scrub-follow-up-2026-11-22/findings.json` (H76-01 to H76-12).

## Pull request body (draft)

The bundle's scrub (`tools/bundle_scrub.py`) gets five changes in the functions H-71 made. `tools/support_bundle.py`
changes in three places: `Bundle.add`, `_logs_part` and `_forms`. The top of `build` is left alone for lane R's
refusal.

- **The flake (H76-01).** `test_the_extended_corpus_still_holds_the_invariant` failed on master about once in 60
  runs. The cause was the scrub, not the test. On the raw line, `%2F` joins its hex digit to the pseudonym, so the
  pseudonym rule passed it. The log scrubber's phone pattern then took digits from its middle. The decoded view ran
  after that and saw only fragments, so 8 to 13 hex digits left.
  - Now each line's decoded view is taken first. The line keeps its own (encoded) form when the raw rules mask,
    where it stands, everything the view masks; otherwise it is written decoded and scrubbed.
  - `Bundle.add` no longer writes the older log-scrubber pass's output, which ran on the raw text the same way. It
    still counts it for the manifest.
  - The log scrubber now runs after the pseudonym rules and before the screening-number rules.
  - Every random value of the bundle's tests is drawn from a seed of the test's node id.
- **Encodings (H76-02 to H76-04).**
  - Up to 16 layers are decoded, an HTML entity with or without `;`, and quoted-printable when a line has `=3D` or
    two `=XX`.
  - A pseudonym straight after any encoding's hex digits is masked on the raw line.
  - Lines joined by a quoted-printable soft break are read as one.
  - Zero-width space, soft hyphen, word joiner and byte order mark are taken out of the view.
  - In a decoded view, a secret pair's value runs to the end of the line: a separator the decoding made inside the
    value cannot cut it.
- **Forms (H76-05, H76-06).**
  - A flag and its value as two list items (`- --password` then `- X`, `["--password", "X"]`).
  - `--password -X`, and `password:` with its value on the next line at the same indent.
  - YAML lines behind a log prefix (`svc | `), and a `'` inside URL userinfo.
  - Screening numbers `Scr.0042`, `S.0042`, `RA 01 0042`, and a prefix in another script glued to the digits.
- **The guard (H76-07).** A test fails on any program started from the builder or the scrub but the reviewed
  `run_cmd`.
- **The box's own values (H76-08).** They are looked for in up to three percent-encoding layers, as HTML writes them,
  and in base64, both alphabets.
- **Base64 (H76-09).** A run of 24 or more base64 characters that decodes to text is scrubbed as text: either
  alphabet, padded or not, inside JSON, and base64 inside base64 once more. When that changes anything, the run is
  written back in its own alphabet.
- **The read cut (H76-10).** A collected log is read up to 64 MiB before the scrub. When it is cut there, its last,
  partial line is dropped, so a token cut in two leaves no fragment, and the manifest says `cut_at_read_limit`.
- **The fuzz test (H76-11).** Six encoding classes (percent 1 to 6 layers, entities, escapes, quoted-printable with
  soft breaks, invisible characters, base64), 150 cases each from a fixed seed. Each case is a pseudonym, a screening
  number or a secret pair, put in a collected log and built with `support_bundle.build`. Every view of the archive
  is read back.

### What changes for a box

- A line with an encoded token is written decoded more often than before: whenever a raw rule would leave a part of
  it.
- A base64 blob that decodes to text holding a token is written back re-encoded, with the token masked inside.
- A collected log over 64 MiB loses its last, partial line.
- Bundles take longer. A 15 MB log of encoded URLs (the worst kind) took 48.5 s to scrub on master and takes 74 s
  now; the writer's check 15.0 s and 18.6 s. A worst-case 1 MB single line takes at most 2.6 s (it was at most 0.72
  s; the new shapes are base64 and quoted-printable).

### What stays uncaught

- Free text: names, addresses, dates of birth and diagnoses typed into a log (H71-06).
- Screening numbers whose prefix is lower case and glued to the digits (`tbx0042`), lower case before a separator
  (`scr.0042`), or all digits (`20260042`) (H71-05).
- A pseudonym glued to other hex digits with no encoding between (`deadbeef` and 32 hex digits).
- Base64 of binary or compressed data (an image, gzip, a zip) and base64 runs shorter than 24 characters. A token
  encoded in base32, base85, hex of its bytes, ROT13 or another cipher.
- Quoted-printable with a single `=XX` on a line and no `=3D`. A soft break inside an escape (`=` then `=\n64`):
  no encoder writes it.
- A hex entity without `;` before a secret's name (`&#x70assword`): the decoder takes the name's letters as hex.
- `mysql -pSECRET`; a list item value that starts with `-` (`- --password` then `- -X`).
- A secret or a PEM block split across two collected day files (the collector's rotation, not the builder's). A PEM
  body with neither its BEGIN nor its END line.
- A secret with no name or form next to it, when it is not one of the box's own values.

### Collisions

- H-79 (`claude/lane-h-79-log-line-decode-then-scrub`) is not on origin yet; there is no diff to compare.
- Every change of this card is inside functions of `tools/bundle_scrub.py` that H-71 made: `Scrubber.text`,
  `decoded`, `_pairs`, `_lines`, `tokens` (now `pseudonyms` plus `screening`), `_decode`, `token_patterns`, plus new
  methods `soft`, `b64`, `_flags`, `_view_rules` and `_batch`. If H-79 moves the core to `libs/tb_common` with a
  re-export, the move is mechanical; a decode-then-scrub of its own in front of the scrub would do the work twice.
- `tools/support_bundle.py` changes in `Bundle.add`, `_logs_part` and `_forms`. The top of `build` is left alone.

## Follow-up (H-76)

| Finding | The class closed | Test (`tests/unit/test_support_bundle_h76.py`) |
| --- | --- | --- |
| H76-01 the flake | A raw rule may not cut a token the decoded view needs whole; deterministic tests | `test_flake_*` (6 fixed pseudonyms, 16 encodings x 150); 20 runs of the bundle files, worksteal, shuffled order |
| H76-02 a twice-encoded secret cut at a decoded separator | A decoded view's pair value runs to the end of the line | `test_h76_02_*` (`&`, space, `"`, `,`, `;`, three layers) |
| H76-03 encodings not decoded | 16 layers; entities without `;`; quoted-printable with two `=XX`; a pseudonym after any encoding's hex digits | `test_h76_03_*` |
| H76-04 a token split by a soft break or an invisible character | Soft breaks joined; invisible characters out of the view | `test_h76_04_*` (10 splits, pseudonyms and secrets) |
| H76-05 forms | List flags, `--password -X`, a value under its key, `svc \|` prefixes, a quote in userinfo | `test_h76_05_*` |
| H76-06 screening prefixes | Mixed case and one letter before `.#/:`, spaced capitals, other scripts glued | `test_h76_06_*` |
| H76-07 a subprocess writer | No program started but `run_cmd` | `test_h76_07_*` |
| H76-08 a box value encoded twice | Three percent layers, HTML, base64 in `_forms` | `test_h76_08_*` |
| H76-09 base64 | Text in base64 runs scrubbed and written back | `test_h76_09_*` |
| H76-10 the read cut | A cut log's partial last line dropped | `test_h76_10_*` (a pseudonym, a screening number and a secret at the cut, through `build`) |
| H76-11 fuzz | Six classes x 150 cases through `build` | `test_h76_11_*` |
| H76-12 speed | Each new rule linear | `test_speed_the_new_rules_are_linear_on_a_long_line` (6 shapes, 1 MB) |

Red before: on the head before these fixes (a25a5c18), 54 of the card's tests failed. Mutation pass: 27 mutants of the H-76 changes, run one at a time: each rule dropped, each layer bound and boundary
narrowed, the old order put back, the keep-form criterion forced, the read cut kept, the box's forms cut back, and a
subprocess writer added. 25 were caught on the first run. The two survivors were second guards: the raw rule behind
the decoded view, and the mark in the leak check. Two direct tests now hold them: 27 of 27.

## Checks run

See the train-ready line on #639. After the last commit, the bundle and scrub test files, guard, cross-card,
data-scan, collect and the ratchets were run again.

## Not verified

- Not run on a box. Synthetic command outputs stand in for `docker compose config`, doctor and journals.
- The 64 MB end-to-end build was not timed. The 15 MB figures above are from this container.
