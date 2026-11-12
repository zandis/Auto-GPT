# D-577 The embedder is served by our own code until go-live; a ready-made embedding server was tested beside it

- **Task:** TEI-PARITY (a side test the owner asked for on 2026-11-12, relayed by the integrator: can one pinned
  image of Hugging Face Text Embeddings Inference replace `services/embed_service/embedder.py` and the torch lock?)
- **PR:** this branch (`agent/TEI-parity-note`)
- **Date:** 2026-11-12
- **Status:** proposed (the owner decides; this record holds lane D's verdict and what it rests on)
- **Builds on:** D-429 (the embedder: safetensors from the publisher, pinned, never the stub in PRODUCTION), D-563
  (the embed image and its second hashed lock), D-337 (every text is masked before it is embedded)

## Context

The embed service does four things: it masks each text, it refuses to start in PRODUCTION without a pin and
without the pinned weights, it refuses pickle weights and code in the folder, and it turns text into vectors. Only
the last is what a ready-made embedding server does. The test asked whether that part can be bought instead of
kept: the image is smaller and it has a GPU build.

## Decision

Verdict: **keep ours** for the run of 2026-12-11 and for go-live. The evidence is in
`docs/reviews/2026-11-12-tei-parity.md`. In short: on synthetic models the vectors agree, and the server starts
offline, as a non-root user, on a read-only folder. It does not pass our release gates as shipped (22 fixable
findings in its base system), our SBOM tool sees none of the code the server is made of, it carries a maths
library under a licence that is not the one on its label, and it does not mask, pin or refuse anything, so our
service has to stay in front of it. What it would remove is about 25 lines and one lock; what it would add is a
second container and three open questions that only the real weights on the real hardware can answer.

The question may be opened again after go-live if lane G measures that embedding on the CPU is too slow for a
site's lake. The note lists what has to be true then.

## Consequences

- No code changes. No dependency is added.
- Three "for lane G" measurements are named in the note; none of them blocks the run.
