# D-497 The G-4 probe calls the judge's own model server, outside the gateway

- **Task:** plan v7 section 7.1, test G-4 (lane G; the probe is `tools/g_probes.py`)
- **PR:** lane G batch 6 (`lg/batch6`, draft PR #592)
- **Date:** 2026-11-13 (the entries); written 2026-11-14
- **Status:** accepted (the owner's ruling of 2026-11-13, relayed in `docs/plan/35-handover-2026-11-13.md`: "D-497 is
  lane G's number for its probe's entry in the model-call guard"; lane G takes it, the integrator's word of
  2026-11-14)
- **Builds on:** ENG-04 and LLM-1 (every model call goes through the gateway), D-150 (the rehearsal's stand-ins),
  D-359 (the prompt version an installed box serves)

## Context

`tests/unit/test_no_direct_model_calls.py` fails on any code outside the gateway path that names a model API path
(`/chat/completions`, `/completions`, `/embeddings`), unless the file is on its allowlist with a reason. The G-4
probe (lane G, commit 2b9eec74 of 2026-11-13) posts to the judge server's `/v1/chat/completions` itself: G-4 times
the server with guided decoding on and off (`response_format` with the judge schema, then without), and the gateway
does not switch guided decoding per call, so the measurement cannot go through it. The cross-card set found the
call; lane G listed `tools/g_probes.py` with its reason, and in commit 70087268 the entry took this number and the
probe's unit test, which drives the stand-in on a local port, was listed too.

## Decision

Two files are allowed to name a model API path outside the gateway path, for G-4 only:

1. **`tools/g_probes.py`.** G-4 posts the judge's PRODUCTION prompt (`load_prompt("judge", "PRODUCTION")`) straight
   to the judge's own vLLM server (`server_root(a.judge_url) + "/v1/chat/completions"`), with guided decoding on
   and off, to measure the serving itself: how many answers fall outside the judge schema and how fast each setting
   is. Its inputs are synthetic excerpts only (`synthetic_excerpts`), and the server is the run's own, on the GPU VM
   of a lane G run, reached with that run's key. The probe is a lane G tool: it is not shipped on a box and no box
   service imports it.
2. **`tests/unit/test_g4_g8_probes.py`.** The probe's unit test drives that call against the vLLM stand-in on a
   local port: no model, no network.

The allowlist entries carry this number and their reason. Any other direct call still fails the guard; a new
exception needs its own reason and review.

## What it does not do

- It opens no path for patient data: the probe sends synthetic text only, and a box never runs it.
- It does not let any other lane G tool call a model outside the gateway. The public TREC CT scenario's calls straight
  to the card (`tools/scenarios.py`, through `tools/mlbench.py`, already allowed as the bake-off harness) are not
  covered by this decision.
- It changes nothing in the gateway, which still does not switch guided decoding per call.
