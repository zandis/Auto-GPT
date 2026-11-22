# D-1354 One scrub for every byte of a support bundle (H-71)

- **Task:** lane H, card H-71 (high-risk: an export) · **Date:** 2026-11-22
- **Status:** accepted (the integrator's ruling of 2026-11-22 04:31 UTC; orders of 2026-11-20 07:10 and 09:41 UTC)
- **Builds on:** D-405 (the support bundle), D-723 (no secret of the box leaves in it), D-747 (the exits' scan
  patterns), D-09 (the pseudonym)

## Decision

1. `tools/bundle_scrub.py` holds the scrub: one pure function, `scrub_text(text)`, and a `Scrubber` that a bundle
   makes once. Gate 5's `prepare_output` can call `scrub_text` later; nothing of draft #1295 is touched.
2. Every name, text, source and left-out line of a bundle goes through the bundle's scrubber as it comes in, again
   after the line removal and the secret passes, and the manifest goes through it too. `_write_tar` is the one
   function that writes into the archive, and it refuses a member the scrub would still change. A test finds every
   archive writer by AST.
3. Patient tokens are masked with their kind and no part of the token: the pseudonym (`PID_HEX_LEN` hex digits read
   from `libs/tb_common/crypto.py`, any case, and the 8-digit short form with `…`) and the screening number (the
   shape `services/console/sitestore.py` makes). A bundle's scrubber adds a five-letter tag from a key made for that
   bundle and never stored: lines of one patient can be read together in one bundle; a tag means nothing outside
   it and cannot be turned back into the token.
4. Secrets are replaced by their form, not only by a name list: query strings and form bodies (also
   percent-encoded inside another URL), URL userinfo, `Authorization`/`Cookie` headers, bearer tokens, PEM blocks,
   `name=value`, `name: value` and JSON (also JSON inside a JSON string), quoted values over several lines, YAML block
   values and commented-out lines. A secret's name is any setting `libs/tb_common/config.py` declares secret, read
   from its source, so a new secret setting is covered with no change to the scrub; any family marked so; and any
   name whose words say secret (`TB_SMTP_LOGIN` among them).
5. The update history keeps each line's own fields (`at`, `bundle`, `box`, `step`, `ok`); any other field, the step's
   detail among them, is stored as its type and length. The ops snapshot's update rows and the builder's own caught
   errors are kept the same way.
6. A log or a command's output that is not UTF-8 text (UTF-16, binary, a control byte) is left out and listed in the
   manifest; it is never copied unscrubbed.

## Links

- Card page: `docs/handover/support-bundle-scrub-2026-11-22.md`.
- Findings: `docs/handover/support-bundle-scrub-2026-11-22/findings.json` (H71-01 to H71-06).
