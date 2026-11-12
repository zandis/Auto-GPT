# D-563 The embedder is in an image of its own, pinned, and a PRODUCTION box starts with it

- **Task:** ENG-003 (with HW-002; deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/03-code-quality-se.md`
  and `13-final-build-hardware-install.md`; plan TB-PLAN-07 v7.2, wave 1, lane D; the owner's answer Q3 of D-494:
  the embedder is in release 1)
- **PR:** this branch (`agent/ENG-003-embedder-image`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-429 (T-607: the stub embedder is refused in PRODUCTION; the service loads only pinned weights),
  D-185 (one hashed lock), D-204 and D-348 (the pinned images), D-142 (the install pins the pair), D-392
  (provenance of a build's weights)

## Why

In PRODUCTION the embed service refuses the stub, and its real mode imports `sentence-transformers`, which no image
the build makes contains. The registry row `e-embed-1` named no embedder. So a box started in PRODUCTION never came
up healthy, and the box rehearsal was green only because it overrode the one setting that fails.

## Decision

1. **The embedder is BGE-M3** (`BAAI/bge-m3`, MIT, 1024 dimensions, the revision of the licence register's row
   `model-bge-m3`). The registry row `e-embed-1` names the repository, the revision, the licence and the origin.
   **Open, for the owner:** that revision of the publisher's repository holds pickle weights only and no
   safetensors file, and D-429 refuses pickle weights. Which safetensors folder ships (a publisher revision that
   has one, or a recorded conversion) is not decided here; the row says so (`provenance.copy: undecided`) and names
   no manifest. Nothing is trusted on first use: until the manifest is written the install reports the embedder as
   not pinned and a PRODUCTION embed service refuses to start.
2. **An image of its own, `trialbox-embed`.** It is the Python service image plus the `embed` extra of `uv.lock`,
   installed from a second hashed export, `deploy/requirements-embed.lock` (`make lock` writes it, `make lock-check`
   holds it). The other services do not carry the library.
3. **CPU wheels.** The embedder runs on the CPU (the card's memory is the model pair's). `torch` is locked from the
   publisher's CPU wheel index for Linux, so the image carries no CUDA libraries (about 3 GB less in the bundle
   and on a CI runner). A profile that gives the embedder a card is a later decision with its own lock.
4. **Compose runs the embed service from that image** (`TB_EMBED_IMAGE`, default `trialbox-embed:1.0.0`, built
   from its own file), with the weights folder `deploy/models/embedder` mounted read-only. The stacks that run the
   hash embedder (the test stack, the PoC, the box rehearsal's stand-ins) keep the service image. No overlay asks
   the CPU image for a GPU (the GB10 overlay did).
5. **The install pins the embedder with the pair** (`pin_model --install` also pins `e-embed-1` from
   `deploy/models/embedder`). A missing folder, or a registry that names no manifest yet, is reported and leaves
   the command's result the pair's; a folder that is there and is not the expected weights fails it. The embed
   service is not a model server: `doctor --serving` and the gateway's start check do not ask it for a model list
   (its own `/healthz` names the pinned weights).
6. **A PRODUCTION start test.** A test builds a tiny model in the publisher's format on the spot (random weights,
   no download), pins it, starts the embed service from the image with `TB_ENV=PRODUCTION`, and embeds one sentence.
   It runs in CI where the image is built. The box rehearsal no longer overrides the embedder to the stub (OPS-004
   takes that line).

## Consequences

- A PRODUCTION box whose `deploy/models/embedder` holds the weights starts its embed service.
- The bundle gains one image. The release gates scan it like the others.
- For lane G: hash the real folder once (`pin_model`), write the manifest into the registry row, and measure start
  time, memory against `TB_MEM_EMBED` and the time to index 5,000 patients' notes.

## Not done here

- The platform form (Kubernetes manifests, `tools/trialbox/platform.py`) still runs the embed service from the
  service image: that form is frozen (plan v7.2 section 3.2).
- `pip-audit`, the lock's SBOM and the allow-list read the first lock only; the image itself is scanned by the
  release gates.
- The box rehearsal bundles and runs the service image for the embed service (hash embedder): OPS-004 changes that.

- The S2b threshold for the new vectors (D-429 "Remains"): from lane G's bench.
- The embed service merged into the data process (plan v7.2 section 3.1).
