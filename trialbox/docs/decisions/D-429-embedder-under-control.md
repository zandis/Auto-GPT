# D-429 The embedder under control: one mode the wizard and the service share, no hash stub in PRODUCTION, the embedder pinned like a model, safetensors from the publisher

- **Task:** T-607 (`docs/plan/28-master-plan-v6.md` §6.2.5, wave 2; the embedder half of the old T-009)
- **PR:** this branch (`agent/T-607-embedder`)
- **Date:** 2026-11-11
- **Status:** accepted (the rule and the code); the choice of embedder waits for the G1 record (T-004), see Open
- **Closes:** LLM-013 (the wizard wrote a mode the service refused; with no mode the service used the hash stub in
  production), LLM-014 (the embedder had no registry build, no pin and no hash check), DEP-010 (the incumbent ships
  pickle weights only, which `pin_model` refuses)
- **Builds on:** SEC-63 (no pickle, no remote code), T-012b (no trust on first use), T-674 / D-392 (provenance)

## Context

The settings wizard wrote `TB_EMBED_MODE=model` for a GPU box; the embed service accepted only `hash`, `http` and
`bge-m3` and raised on anything else. Without the wizard the compose file set no mode and the service fell back to
the feature-hash stub, also in PRODUCTION, with nothing in `/healthz` to show it. The embedder was outside every
control the two language models have: no registry build (so the `vectors` route could never resolve), no weight pin,
no hash check. The incumbent embedder's publisher ships only pickle weights and ONNX; its safetensors file was
deleted upstream in 2024, so `pin_model` cannot pin the official folder.

## Decision

1. **One mode name, shared.** The embed service's modes are `model` (the local embedder from the offline models
   volume), `hash` (the CI stub) and `http` (the client of the service), in `services/embed_service/embedder.py`
   `MODES`. The wizard writes `model` for a GPU box and `hash` for a stub box (and warns that a PRODUCTION embed
   service refuses the stub). The old mode name `bge-m3` is read as `model`, so an older `.env` still starts.
2. **No hash stub in PRODUCTION.** The embed service (`service_embedder`) refuses `hash` when `TB_ENV` is PRODUCTION
   (PRODUCTION when unset, D-127). An unset mode in PRODUCTION means `model`. The service builds its embedder at start
   in PRODUCTION, so a wrong configuration stops the container instead of failing the first call.
3. **The embedder is a registry build, pinned like a model.** `models/registry.yaml` has one build for the `e-embed`
   alias, `e-embed-1`, served on the routing endpoint `embed`. `tools/pin_model.py --build e-embed-1 --endpoint embed`
   pins it into the site override exactly as it pins the judge: manifest of the visible files, digest, expected
   manifest from the registry, no trust on first use. The embedder's folder must hold safetensors (GGUF is refused
   for it). `--verify-all` re-checks it with the other builds.
4. **The service loads only the pinned weights.** compose gives embed-service the site override
   (`TB_REGISTRY_OVERRIDE`, the site folder read-only) and the folder `/models/embedder`. In PRODUCTION the service
   refuses to start with no pin for `e-embed-1`, or with weights whose manifest digest differs from the pin. In DEV and
   TEST a pin, when there is one, is still checked. In every environment a folder with pickle weights or Python files,
   or without safetensors, is refused, and sentence-transformers is called with `trust_remote_code=False`.
   `/healthz` names the build and the first 12 characters of the weights' digest.
5. **Criterion for the choice: safetensors weights from the publisher.** A candidate embedder qualifies only when its
   publisher ships safetensors weights at a pinned revision. The pickle-only incumbent does not qualify, and it is not
   converted by us: a converted file is our artefact, not the publisher's, and the conversion itself would load the
   pickle. The other criteria stay as T-009 set them: 1024 dimensions fit the `halfvec(1024)` column with no rebuild
   (768 needs the column and index rebuilt), Japanese and Traditional Chinese retrieval on the bench set
   (`tools/bench_embed.py`: needle MRR@10 and recall@10, finding nDCG@10, negation traps), throughput and GPU memory,
   licence, and origin as for the language models. The candidates and their weight formats are in deep review
   `03a-verifier-candidates.md` §7. The measured choice is G1's (T-004).

## Consequences

- A GPU box that the wizard configured starts the embed service once the embedder is pinned; until then a PRODUCTION
  embed service does not start, which is the point: it no longer embeds a production lake with the stub.
- The platform manifests (`deploy/platform/base/site.env`, `apps.yaml`) still name `hash` and the old folder with
  `TB_ENV=PRODUCTION`; their embed service will refuse to start until the platform card moves them (see Open).
- Vectors made with the hash stub are not comparable with the embedder's; a box that ran on the stub re-embeds its
  lake after the pin (the lake records the embed model per row).

## Open (Remains, after G1)

The values below come only from the G1 record (T-004). Nothing here is guessed.

| Value | Where it goes |
| --- | --- |
| The chosen embedder's publisher repository | `models/registry.yaml`, build `e-embed-1`: `repository`, `model_name`, `family` |
| Its full revision (commit id) | the same build: `revision` and `expected.revision`; a `provenance` block (`copy: publisher`, `source`, `revision`, `licence_file`) as D-392 |
| The weight manifest digest of the release (`tools/pin_model.py` format) | the same build: `expected.manifest_sha256`, with `expected.source` naming the G1 record |
| Its licence | `models/registry.yaml` `licence` (`spdx`, `verified: true`, `register`) and a `kind model` row in `docs/licences/register.csv` |
| Its developer and origin | `origin` (`developer`, `country`, `non_prc`) |
| Dimensions if not 1024 | the `halfvec` column and index of the lake, and `DIM` in `services/embed_service/embedder.py` |
| The S2b threshold for the new vectors | refitted from the G1 bench result (the S2b stage of the cascade) |

After the row is filled, the install pins the embedder (`pin_model --build e-embed-1 --model-dir
deploy/models/embedder --served-name e-embed-1 --endpoint embed`), regenerate the model card
(`python -m registry.cards --write`), and add `e-embed-1` to the install's pins (`tools/pin_model.py` `install_pins`)
so `deploy/install.sh` pins it with the GPU pair. Not done here, for other cards: `doctor` checks the embedder name and
digest in `/healthz` (the review's third fix of LLM-013; `tools/trialbox/doctor.py` is not in this card); whether
embeddings go through the gateway, or the exception is written in LLM-1 (LLM-014); the platform manifests (T-113b).
