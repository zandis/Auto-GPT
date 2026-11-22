# Every value of a log line, decoded then scrubbed (H-79, 2026-11-22)

**Reader:** the people who build TrialBox: lane H, the integrator, and the independent reviewer of this masking
card. Findings for builders, so in one language.

Card H-79 (high-risk: masking), decision D-1358. Findings in the register's `--add-from` form:
`log-line-decode-then-scrub-2026-11-22/findings.json`.

## Pull request body (draft)

The integrator's order of 2026-11-22 10:07 UTC: a secret behind two to four `%` layers or written `password&#61;…`,
and an address written `%40` or `&#64;`, stayed in a service's log line on the box. The review's finding R22-21
(`logging.py:152`): values given through `extra=` that are not text went out as written. Both are fixed on the one
formatter every service uses, `tb_common.logging.JsonFormatter`.

- The decoding moves to `libs/tb_common/decode_scrub.py`, standard library only. The log line
  (`tb_common.logging.redact`) and the support bundle (`Scrubber.decoded` in `tools/bundle_scrub.py`) both call
  `decode_then_scrub`, so there is one source of truth. `libs/` imports nothing from `tools/`. Why not the bundle's
  function itself: it lives in `tools/`, it replaces with `[redacted]` where the logs write `[SECRET]` (asserted by
  the log tests), and it masks pseudonyms, which the logs keep (`test_ordinary_words_are_kept`). The rules stay each
  scrub's own; the decoding is shared.
- Decoded classes: `%XX` in up to eight layers; `\x`, `\u`, `\U` behind any number of backslashes (`repr()` doubles
  them); HTML entities, named or numeric, with or without `;` (a numeric one without `;` is also read short, so
  `&#61` followed by a digit is still `=`); quoted-printable `=3D` and `=40`.
- The log line is decoded before any rule reads it. Found by the fuzz: the chart-number rule matched eight digits
  inside `%25252536…` and broke the encoding before the decoded pass could read it.
- Every value that enters the line is scrubbed: the message and its arguments; the logger, level and service names;
  every `extra=` key and value of any type (mapping, list, tuple, set, dataclass, named tuple, exception, bytes,
  number, any object's text form); the traceback. A value under a secret's name is `[SECRET]`. The walk is bounded:
  depth 8, 1000 values a line, cycles.
- The formatter never raises. A record it cannot render (a broken format string, a tuple as a key, a broken
  `__str__`) gives a line that says the message was withheld, with the logger and the level. A single value that
  cannot be read is withheld alone; the rest of the line is kept.

### Was the review's finding as the review says?

Partly. Confirmed on master 225100f4 with a failing probe:

- Left as written: a dataclass (`Row(name=…, phone=…)`), an exception, an object's text, bytes, a value under a
  secret's name in a dict (`{"password": …}`).
- Raised: a tuple as a dict key raised in the formatter (R22-22).
- Not as the review says: dicts, lists and tuples of text were already scrubbed (`redact_value`, the earlier review's
  HIGH-1).
- The integer case: an integer is scrubbed only when its digits match a rule. With the contract's default chart
  pattern (`^\d{8}$`), an eight-digit integer was left as written and is now `[MRN]`. A phone number as an integer
  has lost its leading `0`, so no phone rule matches it.
- Not verified: "228 of gate 5's 360 sinks". That list is not on master.

### What changes for a box

- A log line that held an encoded secret or address is written decoded and masked (`next=/x?password=[SECRET]`). Its
  other escapes go with it (`%2F` becomes `/`). A line in which decoding finds nothing keeps its escapes.
- `extra=` values that are objects are written as JSON objects of their fields (a dataclass, a named tuple; a
  pydantic model by its `model_dump`, not tested) or as their scrubbed text (any other object, an exception as `Type: text`, bytes as text). A tuple
  key becomes its text. Two keys the scrub makes alike stay apart (`[EMAIL]`, `[EMAIL]~2`).
- A value under a secret's name (`password`, `db_password`, `dbPassword`, `apiKey`, `token`) is `[SECRET]`. Flags,
  nulls and counts of three digits or fewer are kept.
- A number whose text a rule matches is written as the masked text (`"[MRN]"`), not as a number.
- A record the formatter cannot render is one withheld line on stdout. Before, it was a traceback on stderr that held
  the raw arguments.
- `redact()` is also used by `tb_common.fhir` and `model_guard`. They get the decoded pass too (more masked, nothing
  less).
- The support bundle decodes with the same function, under H-76's ordering and keep-encoded rule (merged from
  `a25a5c18`; the rule is passed to `decode_then_scrub` as its `keep` hook). That adds four more `%` layers,
  entities without `;`, `=40` and doubled backslashes, so it masks more. Its tests and H-76's pass unchanged.
  Its timing did not move (in seconds, H-76's head, then merged):

  | Bundle text | H-76 head | merged |
  | --- | ---: | ---: |
  | 1 MB `%2F` run | 0.94 | 0.88 |
  | 1 MB `%25…40` layers | 0.56 | 0.67 |
  | 1 MB hex | 0.34 | 0.37 |
  | 1 MB `&#x2F;` run | 0.89 | 1.07 |
  | 1 MB `\u0041` run | 0.75 | 0.77 |
  | 1 MB of `a.b%40x.org` | 1.23 | 1.23 |
  | 15 MB realistic log | 61.44 | 61.11 |

### The invariant test

`tests/unit/test_log_line_decode_then_scrub.py::test_h79_no_planted_value_in_any_encoding_or_place_reaches_the_emitted_bytes`

- **What is planted:** nine forms the formatter masks. A secret after its name in a query, a header and a URL
  password. A value the process holds. An e-mail address. A Taiwan ID. A chart number.
- **Encodings (24 classes and layer counts):** raw; `%` on the key characters and on every byte, in 1 to 4 layers;
  entities, decimal and hex, with and without `;`; named entities; every character as an entity; an entity encoded
  twice; `\x`, `\u` (every character), `\U`; quoted-printable; a `%`-encoded entity in 1 and 2 layers.
- **Places (20):** the message; `%s`, `%(v)s` and `%r` arguments; the logger name; an extra's key and text; a dict
  value and a dict key; a list, a tuple and a set; nesting five deep; bytes; an exception; a dataclass; a named tuple;
  an object, alone and in a list; a tuple key; `exc_info`.
- **The check:** 3960 records. None may hold a planted value in the emitted bytes, raw or decoded, in any string of
  the JSON.
- **The fuzz:** `test_h79_fuzz_150_cases_each_encoding_class`. Eight classes, 150 cases each, with a fixed seed. The
  values, labels, layers (1 to 4) and noise are random, and the value goes in the message or a nested extra.
- **What it found on the way:**
  - doubled backslashes (`%r`, a tuple key);
  - entities without `;` followed by a digit;
  - the rule that broke an encoding.

  Each class is now closed in `decode_scrub`.

Near-misses that must stay as written (`test_h79_a_near_miss_is_emitted_as_written`, 15 lines): a ULID, a UUID, an
ISO timestamp and a duration, decision and finding ids (`D-1358`, `H79-01`), counts (`restarts=2`, `count=40`), a
32-digit pid, a sha256 with no long digit run, `85%` and `100%`, a query string with `&`, `R&D` and `Q&A`, `&amp;`
and `&lt;` that hide nothing, `%2F` that hides nothing, an escaped CJK character, `token registry loaded`, versions
and ports.

### Cost

Measured in this container. Each case was formatted by master's formatter and by this card's, from 3 to 3000
times. Lines per second; the formatter cuts a line at `TB_LOG_SCRUB_MAX_CHARS` (65536) before it scrubs, so the
100 KB and 1 MB rows scrub 64 KB.

| Line | before /s | after /s | after/before |
| --- | ---: | ---: | ---: |
| short info line (90 chars) | 4183 | 4303 | 1.03 |
| short line and 4 extras | 3006 | 3006 | 1.00 |
| short line with one `%2F` | 3885 | 2041 | 0.53 |
| 2 KB | 473 | 522 | 1.10 |
| 100 KB | 13.7 | 14.0 | 1.02 |
| 1 MB | 13.4 | 13.6 | 1.01 |
| 100 KB, a `%XX` every 50 characters | 9.1 | 6.0 | 0.66 |
| worst: 1 MB run of `%25` | 9.0 | 7.4 | 0.82 |
| worst: 1 MB `%2525…40` (layers) | 11.2 | 5.5 | 0.50 |
| worst: 1 MB of hex | 11.5 | 11.5 | 1.00 |
| worst: 1 MB of `&#61` | 9.2 | 7.6 | 0.83 |
| worst: 1 MB of `@` | 9.4 | 9.6 | 1.02 |
| worst: nested dict, 50 deep | 2756 | 11697 | 4.24 |

- **Fast path:** a line with no encoded character costs one extra regex search (`ENCODED`), so the common line costs
  what it did. A line with an encoded character pays a second pass of the rules over that line (about half the
  rate).
- **Linearity:** no rule is quadratic. `test_h79_a_worst_case_is_linear_without_the_cut` gives each of 11 worst
  cases 256 KB with the cut raised past it (each under 0.8 s here, bound 10 s).
  `test_h79_a_worst_case_line_is_scrubbed_in_bounded_time` runs the same 11 at 1 MB (bound 5 s).
  `test_h79_worst_case_structures_are_rendered_in_bounded_time` covers 100,000-deep nesting, a million-item list,
  1 MB of bytes and 100,000 keys that scrub alike.

### What the scrub does not catch

- **Pseudonyms and screening numbers** in a service's log line. They are kept by design: logs carry pids, and
  `test_ordinary_words_are_kept` asserts it. The card asked for them; a ruling is asked (question in the report).
- **Encodings it does not decode:**
  - a named entity without `;` that is not one of HTML's legacy names (`&commat` with no `;` is left; a browser
    leaves it too);
  - quoted-printable other than `=3D` and `=40` on its own;
  - base64, JSON's `\/`, or any other encoding;
  - more than eight layers.
- **A secret's name the log rule does not know:** `cookie`, `session`, `dsn`, `auth` and others are secret names in
  the bundle, not in the log rule. A bare secret the process does not hold.
- **Free text:** names, addresses and dates typed into a message. Only the note masker's patterns stand there
  (R22-23 is another card).
- **What the formatter does not see:** a frame's locals (the traceback text holds none). `stack_info` is not written
  at all, as before. A handler other than the one `setup_logging` installs (pytest's `caplog`, a `print`).
- **Lost, not leaked:** text past `TB_LOG_SCRUB_MAX_CHARS` is cut, as before. Values past the 1000th of a line, or
  deeper than 8, are withheld.
- **The bundle (H79-04), closed by H-76:** on this card's first head, the bundle's rules read the encoded text
  before its decoded pass. A `%`-encoded entity holding an eight-digit run, with a site chart rule, kept the secret
  in 37 of 150 fuzz cases. H-76 step 0 (`a25a5c18`, merged here) fixes it: the decoded view reads each line before
  the raw rules, and a line keeps its encoded form when the raw rules mask everything in place. On the merged tree
  the same 150 cases a class keep nothing (0 of 150 in all eight classes, with and without the chart rule).

### Open question

- **Pseudonyms and screening numbers in a service's log line.** The card asked for them to be masked. They are
  not: logs keep pseudonyms by the stated design, so that support can follow a case, and
  `test_ordinary_words_are_kept` asserts that a 32-digit pid stays. The lane lead has asked the integrator for a
  ruling. Nothing is built for it in this card.

### What is masked though it may hide nothing

- A line decoded because something was found loses its other escapes (`path=%2Fdata to [EMAIL]` becomes
  `path=/data to [EMAIL]`).
- `=40` before a domain is read as `@` (`user=40example.org` becomes `[EMAIL]`).
- A value under a secret's name, whatever it says (`{"password": "missing"}` becomes `[SECRET]`).
- A number whose text a rule matches becomes a string (an eight-digit count becomes `"[MRN]"` under the default chart
  rule).
- Already so before this card: digit runs inside a hex hash are read as phone numbers (`0123456789` in a sha256).

Tested by `test_h79_what_is_masked_or_changed_though_it_may_hide_nothing`.

### Mutation pass

32 mutants of the diff, run one at a time against this card's tests and the three log-scrubber test files (one
mutant of the bundle's call, against the bundle's tests).

- **Each class decoded:** a layer count of 2, and each `ENCODED` and `decode` branch dropped.
- **The order:** decoding after the rules instead of before.
- **The walk:** each branch of the walk returning the raw value, keys not scrubbed, the secret-name rule off or
  without camelCase.
- **The formatter:** the logger name raw, the formatter's `try` removed.
- **The bounds:** cycle, depth and count bounds off, the surrogate escape off.

28 were caught at first. Three survived: the surrogate check (the formatter's own re-escape hid it), and the
dataclass and named-tuple walks (the scrubbed `repr` hid them). Tests were added for each:
`test_h79_an_escaped_surrogate_decodes_to_a_writable_character` and
`test_h79_a_dataclass_or_named_tuple_is_walked_by_its_fields` (a camelCase `dbPassword` field is not found in the
text form). Now 32 of 32 are caught.

## Checks run

See the train-ready line on #639 for the counts.

## Not verified

- Not run on a box. The cost numbers are from this container only.
- Gate 5's 360-sink list (the review's "228 of 360") is not on master. That count is not checked.
