# D-1358 Every value of a log line is decoded, then scrubbed (H-79)

- **Task:** lane H, card H-79 (high-risk: masking) · **Date:** 2026-11-22
- **Status:** accepted (the integrator's order of 2026-11-22 10:07 UTC; ruling on the pseudonym 12:50 UTC)
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
5. A service's log line keeps the pseudonym and the screening number, so that support can follow one case inside
   the box. Whatever leaves the box (the support bundle) masks them (the integrator's ruling of 2026-11-22
   12:50 UTC). A pseudonym is not an identifier outside the box only if the key that makes it stays in the box.
   `test_ordinary_words_are_kept` is not changed. The bundle's assertion of that masking for every encoding H-76a
   covers belongs to card H-76.

## Links

- Card page: `docs/handover/log-line-decode-then-scrub-2026-11-22.md`.
- Findings: `docs/handover/log-line-decode-then-scrub-2026-11-22/findings.json` (H79-01 to H79-06).
