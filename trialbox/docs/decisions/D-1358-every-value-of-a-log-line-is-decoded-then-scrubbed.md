# D-1358 Every value of a log line is decoded, then scrubbed (H-79)

- **Task:** lane H, card H-79 (high-risk: masking) · **Date:** 2026-11-22
- **Status:** accepted (the integrator's order of 2026-11-22 10:07 UTC)
- **Builds on:** D-450 (every scrubber rule on), D-927 (the log scrubber runs the note masker's rules), D-1354 (the
  support bundle's scrub and its decoded pass)

## Decision

1. The decoding lives in one module, `libs/tb_common/decode_scrub.py` (standard library only).
   `tb_common.logging.redact` and the support bundle's `Scrubber.decoded` (`tools/bundle_scrub.py`) both call its
   `decode_then_scrub`. `libs/` imports nothing from `tools/`. The bundle's own copy of the decoding is gone.
2. A line that holds an encoded character is read decoded too. The encodings: `%XX` in up to eight layers, a
   backslash escape behind any number of backslashes, HTML entities named or numeric with or without `;` (a
   numeric entity without `;` is also read short: `&#61` then a digit is `=` and the digit), and quoted-printable
   `=3D` and `=40`. When the rules find something in the decoded line, the line is written decoded and scrubbed.
   The log line is decoded before any rule reads it: a rule that matched inside an encoding (eight digits of
   `%25252536`) would break it.
3. Every value that enters a log line is scrubbed: the message with its arguments, the logger, level and service
   names, every `extra=` key and value of any type, and the traceback. A mapping, a list, tuple or set, a dataclass
   and a named tuple are walked. An exception is its type and text. Bytes are text. A number stays a number unless
   the scrub changes its text. Any other object is its text form, which may raise and is not trusted. A value under
   a secret's name is `[SECRET]` (flags and counts of three digits or fewer are kept). The walk stops at depth 8,
   at 1000 values a line, and at a cycle.
4. A record the formatter cannot render gives one line that says the message was withheld, with the logger and the
   level. The raw text is never written, and nothing is raised into the logging module, whose error path printed
   the raw arguments.
5. Pseudonyms and screening numbers are not masked in a service's log line. Logs carry pids by design, and
   `test_ordinary_words_are_kept` asserts that a 32-digit hex pid stays. Changing that needs a ruling.

## Links

- Card page: `docs/handover/log-line-decode-then-scrub-2026-11-22.md`.
- Findings: `docs/handover/log-line-decode-then-scrub-2026-11-22/findings.json` (H79-01 to H79-06).
