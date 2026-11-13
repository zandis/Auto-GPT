# D-632 A pinned download in an image build is tried three times

- **Task:** DEMO-FETCH (from train 7's `demo-boot` failure, through the integrator, 2026-11-13)
- **PR:** this branch (`agent/DEMO-FETCH-a-bounded-retry`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** T-501 (the demo image fetches the translator's quick jar and the fonts, each against a pinned
  sha256)

## Context

The demo image's build fetches one jar from Maven Central and three font files, each checked against its pinned
sha256. Each was asked for once. On train 7 the mirror answered 404 for the jar; minutes later the same URL
answered 200. One such answer cost a full CI run. The Maven step of CI already tries three times.

## Decision

`tools/fetch_pinned.py` is the one way a build fetches a pinned file: it asks up to three times, waiting 2 and
then 5 seconds, on any failure of the transfer (a refused connection, a timeout, an HTTP error, a short read).
What it wrote is the pinned sha256 or nothing is written. A file whose sha256 is not the pinned one is not
asked for again: that is not the network's fault, and it is refused at once. `demo/Dockerfile` and
`tools/fetch_fonts.py` use it. Standard library only; the CA file of the build (`SSL_CERT_FILE`) is honoured
as before.

Only an `https` address is fetched: the tool's opener has no `file:` or `ftp:` handler, and an answer that
ended at another scheme after a redirect is refused. With that, the static scan has nothing to accept: the
reviewed entry for `tools/fetch_fonts.py` (opening a URL) is removed from `tools/security_scan_ignores.yaml`,
and none is added for the new file.

## Consequences

- One bad answer from a mirror no longer fails the image build; three in a row do, with each try's reason.
- The pin is as strict as before: nothing unpinned is fetched, and nothing is written before its sha256 matched.
