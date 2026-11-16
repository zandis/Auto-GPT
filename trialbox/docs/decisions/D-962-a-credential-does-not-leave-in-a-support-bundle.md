# D-962 a credential no setting names does not leave in a support bundle

- **Task:** SUPPORT-SCAN, lane D backlog (#639, 2026-11-16; the owner's ruling to complete everything as soon as possible)
- **PR:** this branch (`agent/SUPPORT-SCAN-detect-secrets-over-a-bundle`)
- **Date:** 2026-11-16
- **Status:** accepted

## Decision

Build-or-reuse §3.4 (wave 1): detect-secrets over a generated support bundle. It found a real gap: a private key or
an AWS key printed into a service log left the box. The bundle's own checks knew the box's secret values (D-723) and
the patient patterns only.

1. `tools/support_bundle.py`: `CREDENTIALS` and `hide_credentials()` (standard library: the host's python3 makes the
   bundle) replace a whole private-key block (to its END, or to the end of a cut log), AWS access key ids, GitHub,
   Slack and JSON web tokens with `[credential removed: <kind>]`, after the line pass and before the manifest. The
   manifest and the output name the kind and the count, never the value.
2. The last look refuses an archive that still holds one; nothing is written.

## Test

`tests/unit/test_support_bundle_detect_secrets.py`: a bundle of a box with every secret set passes detect-secrets;
with a planted key or AWS key in a log it now passes too (before: both failed); each kind replaced, the key's body
with its block; ordinary log text left alone; an archive that would still hold one refused.
