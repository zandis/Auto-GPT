# Text Embeddings Inference beside our embed service: a one-day parity test

Date: 2026-11-12. Lane D. Decision record: D-577. Asked by the owner after the build-versus-reuse review.

**Question.** Can one pinned image of Hugging Face Text Embeddings Inference (TEI) replace
`services/embed_service/embedder.py` and the torch lock (`deploy/requirements-embed.lock`)?

**Verdict: keep ours** for the run of 2026-12-11 and for go-live. Open the question again after go-live only if
lane G measures that embedding on the CPU is too slow for a site's lake; the last section says what has to be true
then.

## What was tested, and what was not

Tested here, on a CPU, with no network inside the containers and nothing downloaded but the image:

- TEI `cpu-1.9.4`, `ghcr.io/huggingface/text-embeddings-inference@sha256:2538ea1c9640d3763b15af668039d24172d063b42337b0c27796fc2be180c78d`
  (linux/amd64, built 2026-09-15 from the publisher's commit `e80ef225`).
- Our side: `embed_service.embedder.LocalEmbedder` inside `trialbox-embed:1.0.0` (torch 2.15.0+cpu,
  sentence-transformers 6.2.0), the code a box runs.
- Models: three tiny folders with random weights, made on the spot in the publisher's layout. They have the real
  embedder's shape (XLM-RoBERTa, first-token pooling, normalised) with a small tokenizer trained on synthetic
  English, Japanese and Traditional Chinese sentences; one variant pools by mean; one has large weights so that
  the activation function matters.

Not tested, because the real weights may not be downloaded here: the real folder at revision `7b44caba`, the real
tokenizer, 8192 tokens, memory, speed, and anything on a GPU. Those are the "for lane G" lines below.

## Findings

| Point | Result |
| --- | --- |
| Licence of TEI | Apache-2.0. The `LICENSE` file at tag `v1.9.4` was opened: the Apache 2.0 text, 201 lines, sha256 `28216184…afa9db`. The image's label says the same. |
| Licence of what the image carries | **Not only Apache-2.0.** The CPU image holds nine Intel MKL libraries (323 MB, dated 2023-10), copied in as plain files. Their licence is Intel's own, not the one on the label, and no licence text for them was found in the image. Needs a register row and the owner's word before any use. |
| Offline start | Yes. `--model-id /data/model` on a folder mounted read-only, with `--network none`: no call out, "Ready" in under 8 seconds on the tiny folder. |
| Hardening | Runs as root by default (no user in the image). It also runs as `--user 65534 --read-only --cap-drop ALL` with a tmpfs on `/tmp`: tested. |
| Safetensors only | Yes on the CPU image: it looks for `onnx/model.onnx` first, does not find it, and loads `model.safetensors` with its second backend (Candle). The pinned folder holds no ONNX file, so this is the path a box would take. |
| Folder format | Two stops with the folder that today's sentence-transformers writes: `1_Pooling/config.json` must hold `pooling_mode_cls_token` (the older spelling) and `sentence_bert_config.json` must hold `max_seq_length`. With both in the older spelling TEI starts, and our side reads the same folder with identical vectors (difference 0.0). The publisher's folder is from 2024 and should be in the older spelling. **For lane G:** confirm on the real folder. |
| Pooling | Read from `1_Pooling/config.json`: first-token and mean both agree with ours. |
| Normalisation | On by default per request (`"normalize": true`); vector length 1.000000. Ours always normalises. |
| Vector parity, en / ja / zh-TW | 13 texts (3 English, 3 Japanese, 3 Traditional Chinese, full-width and half-width forms, mixed text with an emoji and an unseen word, one character, one text over the limit). Token counts equal for all 13. Cosine 1.000000 for all 13; largest difference of one component 1.2e-07. |
| Activation function | TEI warns that Candle uses an approximation of GELU. With ordinary small random weights it does not show. With large weights the largest difference of one component is 2.1e-04; cosine still 1.000000. The real model has 24 layers, not 2. **For lane G:** cosine on the real weights. |
| Maximum length | TEI takes it from `sentence_bert_config.json` (32 in the test; `/info` shows it). |
| Truncation | On by default (`--auto-truncate true`) and equal to ours: the over-long text (104 tokens, limit 32) gives the same vector. With `--auto-truncate false` TEI answers 422 instead. |
| Batch limits | A request may hold 32 texts by default; our client sends 64. `--max-client-batch-size 64` is needed: 64 pass, 65 answer 422. The body limit is 2 MB (413 above). An empty text answers 400; ours embeds it. |
| CPU speed | Candle on the CPU runs at most 4 texts in one forward pass ("Backend does not support a batch size > 4"). Ours runs 64. **For lane G:** texts per second and peak memory on the real weights, both sides. |
| Image size | 938 MB unpacked (239 MB to pull). Ours is 2.84 GB, of which 1.13 GB is the base image every Python service shares; the embedder's own layer is about 1.7 GB. On the media the saving is about 0.8 GB. |
| Release gates | **Fails as shipped.** Trivy with our gate: 22 findings with a fix available in the image's Debian packages, 4 of them CRITICAL (`libbrotli1`, `perl-base`), and `libssl-dev` is in a runtime image. It would need the same dated, reviewed entries as any third-party image, or our own image around the publisher's binary. |
| SBOM | **Blind.** Syft lists 117 Debian packages and no other component: the server is one 71 MB binary with no package list inside, and the MKL libraries are plain files. Our vulnerability and licence gates would pass on what they cannot see: the inference runtime, the tokenizer, the HTTP stack. In our image every Python package is listed and gated. |
| GPU images (not pulled) | `120-1.9.4` is the linux/amd64 build for compute capability 12.0, the RTX PRO 6000's; 3.16 GB to pull. `121-1.9.4` is linux/arm64, 3.09 GB. `cuda-1.9.4` covers several capabilities, 3.11 GB. **For lane G:** which tag starts on each box, and its memory beside the model pair. |

## What stays ours in front of it

TEI does none of these, so `services/embed_service` stays, as the only door:

1. **Masking.** Every text is masked before it is embedded (`mask_note`, D-337). TEI embeds what it is given.
2. **The pin.** In PRODUCTION the service refuses to start without a pin of `e-embed-1` and without the pinned
   weights (`manifest_sha256` against the site override). TEI starts on any folder.
3. **Refused files.** A folder with pickle weights or code is refused. TEI started with a `pytorch_model.bin`
   beside the weights and said nothing.
4. **Service token and `/healthz`.** Callers present the service token; `/healthz` names the build and the
   weights. TEI has one static key (`--api-key`; 401 without it) and a `/health` that says nothing about the weights.

So TEI would be a second container behind our service, on a network with no other member. Our service would check
the folder, wait for TEI, mask, cut requests to TEI's limits, and pass vectors back. What goes away is
`LocalEmbedder` (about 25 lines), the second lock and three licence entries. What is added: a container, an
image to gate, a start order, and a second place where the weights are read (the manifest check and the load
would no longer be one process reading one folder).

## Why "keep ours"

- The gain is small on a box that embeds on the CPU, which is what every profile does today.
- It weakens a gate as shipped: the SBOM cannot see the server's code. That alone fails the reuse rule
  ("does not weaken a safety rule") until we build the binary ourselves with its package list, which is more work
  than the code it replaces.
- A licence question (Intel MKL) would need the owner's review.
- Three things only the real weights can show (folder format, cosine, speed), and the run of 2026-12-11 should
  not wait on them.

## When to open it again

After go-live, if lane G finds that embedding a site's lake on the CPU takes too long. Then all of these have to
hold: vectors that agree with ours on a fixed set of en / ja / zh-TW texts with the real weights, closely enough
that a lake need not be embedded again (the owner sets that number from lane G's measurement); the folder at `7b44caba` starts unchanged; a build of the server whose
SBOM lists its packages; a licence register row for every library in the image; our service still in front.

## How to repeat (lane G, with the real folder; `MODELS` is the models folder)

    docker run --rm --network none --read-only --user 65534:65534 --cap-drop ALL --tmpfs /tmp \
      -v "$MODELS/embedder":/data/model:ro \
      ghcr.io/huggingface/text-embeddings-inference@sha256:2538ea1c9640d3763b15af668039d24172d063b42337b0c27796fc2be180c78d \
      --model-id /data/model --port 8080 --max-client-batch-size 64

Then send the same texts to `POST /embed` (`{"inputs": [...]}`) and to our service's `POST /embed`
(`{"texts": [...]}`) and take the dot product of each pair of vectors; `POST /tokenize` gives TEI's token counts.
