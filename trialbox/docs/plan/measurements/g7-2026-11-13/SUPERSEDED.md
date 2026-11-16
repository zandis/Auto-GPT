# SUPERSEDED on 2026-11-14

This folder is **superseded** and **must not be quoted as evidence of the shipped product** (lane G's validation
reset: [validation-reset-2026-11-14.md](../validation-reset-2026-11-14.md)). It is kept as history.

| | |
| --- | --- |
| Date of the run | 2026-11-13 |
| Commit | c25cea6b (636 commits behind train 17 at 0c8e1211) |
| What it measured | G-7 (clipped against whole note, 2 synthetic notes) and G-4 (guided decoding) |
| Verdict at the time | FAILED |
| Still quoted by | lane G's findings note (P1, P3). |

Why it is superseded:

1. **Not the shipped serving.** The model servers were started by lane G's own VM script, not by the shipped compose (`deploy/docker-compose.rtxpro6000.yml`): no `--chat-template` (the shipped judge uses the developer's template, D-392), the vLLM image by tag (the shipped one is pinned by digest), weights from a Hugging Face cache with no revision check, nginx instead of model-guard, no memory caps. The box itself ran in one Python process per part (in-process gateway, orchestrator and lake), with the hash embedder, not the installed containers and not the embed service.
2. **An old commit.** It lacks every one of these later changes to screening, masking, the compiler, the embedder
   and the gateway: train 15: #567 (C44/C4A malignancy), #570 (undated labs), #576 (a poisoned call gives up), #578 (budget of asks), #582 (NEW-LLM-2: a note criterion with no retrieval is "not evaluated"); train 16: #586 (B14), #572 (chart-fact negation), #573 (chart-fact family history), #591 (English synthetic site); train 17: #596 (SVC-EMBED), #598 (D-744: English phone numbers masked), #599 (D-745: birth dates, addresses, chart labels masked), #595 (GW-SIGNALS).
3. G-7 used lane G's own lexicon and verdict mapping, not the product's decision function.

What replaces it: the stages of the reset plan, run on the installed box from the signed bundle of a pushed
integration head, each result naming its commit, bundle, image digests, weight manifests, chat template hash and
served prompt versions.
