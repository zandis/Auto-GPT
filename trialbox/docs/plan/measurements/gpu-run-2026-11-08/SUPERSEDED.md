# SUPERSEDED on 2026-11-14

This folder is **superseded** and **must not be quoted as evidence of the shipped product** (lane G's validation
reset: [validation-reset-2026-11-14.md](../validation-reset-2026-11-14.md)). It is kept as history.

| | |
| --- | --- |
| Date of the run | 2026-11-08 |
| Commit | not recorded (folder committed in 0dc8dc7b, before lane G existed) |
| What it measured | the card fit test, the pair canary (54 cases), filter-first on SIGIR pairs and `public_e2e --lang en` with the pair |
| Verdict at the time | mixed; written by hand |
| Still quoted by | `docs/VALIDATION.md` section 3 (canary 54/54, `public_e2e` 98/98 in 1,303 s; the folder copy under `eval/parity/gpu-run-2026-11-08-pro6000/`); `tools/complete_run.py` `PUBLIC_SECONDS` (cost estimate only). `fit.json` stays a memory reading of the card (the compose files cite it for KV sizing). |

Why it is superseded:

1. **Not the shipped serving.** The model servers were started by lane G's own VM script, not by the shipped compose (`deploy/docker-compose.rtxpro6000.yml`): no `--chat-template` (the shipped judge uses the developer's template, D-392), the vLLM image by tag (the shipped one is pinned by digest), weights from a Hugging Face cache with no revision check, nginx instead of model-guard, no memory caps. The box itself ran in one Python process per part (in-process gateway, orchestrator and lake), with the hash embedder, not the installed containers and not the embed service.
2. **An old commit.** It lacks every one of these later changes to screening, masking, the compiler, the embedder
   and the gateway: train 15: #567 (C44/C4A malignancy), #570 (undated labs), #576 (a poisoned call gives up), #578 (budget of asks), #582 (NEW-LLM-2: a note criterion with no retrieval is "not evaluated"); train 16: #586 (B14), #572 (chart-fact negation), #573 (chart-fact family history), #591 (English synthetic site); train 17: #596 (SVC-EMBED), #598 (D-744: English phone numbers masked), #599 (D-745: birth dates, addresses, chart labels masked), #595 (GW-SIGNALS).
3. Filter-first used `tools/mlbench.py`'s own prompt sent straight to vLLM (no gateway, no product judge prompt, no cascade). The servers came from `deploy/gcp/gpu-pro6000-run.sh` (one-boot script).

What replaces it: the stages of the reset plan, run on the installed box from the signed bundle of a pushed
integration head, each result naming its commit, bundle, image digests, weight manifests, chat template hash and
served prompt versions.
