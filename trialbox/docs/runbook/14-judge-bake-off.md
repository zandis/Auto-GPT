# 14. Judge bake-off: the current judge against Gemma 4 31B (D-181)

`tools/judge_bakeoff.py` runs a labelled set through any OpenAI-compatible endpoint with the box's own judge prompt
and parser, and gates on wrong exclusions. It needs a GPU only for the real model; a dry run uses its stub:
`python -m tools.judge_bakeoff --stub --sources synthetic --require-sources synthetic --out /tmp/jb-stub` (no
network, about 10 s).

**Before the GPU** (on any machine):

1. Fetch the public sets: `python -m tools.medtxt_eval fetch` and `python -m tools.trec_ct_eval fetch` (they stay in
   `.cache`, never committed).
2. Freeze one item set for both models: `python -m tools.judge_bakeoff --write-set /tmp/jb-set.jsonl`. It prints the
   item count and the SHA-256; check that no source was skipped. Copy the file to the VM, never into the repository
   (it holds MedTxt and TREC text). Both runs pass `--set /tmp/jb-set.jsonl --expect-set-sha <sha>`.

**On the GPU VM** (owner's OK first, section 11 rules: a cap, stopped and `TERMINATED` after). One model at a time on
the same VM, same set, same `--workers`; every run also takes `--max-upper-ci 0.05` (Study A's bound):

1. The current judge, as the box serves it (the PRO 6000 run serves `nvidia/Gemma-4-26B-A4B-NVFP4` as
   `local/gemma-4-26b-a4b-nvfp4`):
   `python -m tools.judge_bakeoff --base-url http://127.0.0.1:8000/v1 --served-name local/gemma-4-26b-a4b-nvfp4
   --expect-root nvidia/Gemma-4-26B-A4B-NVFP4 --revision <commit> --model-dir <weights folder>
   --set /tmp/jb-set.jsonl --expect-set-sha <sha> --max-upper-ci 0.05 --out /tmp/jb-current`
2. The candidate, **official weights only**: the `google/gemma-4-31B-it` repository on Hugging Face, no community
   quantisation or fine-tune. The registry build for this run is `gemma-4-31b-it-qat-challenger` (D-392): Google's own
   4-bit QAT checkpoint `google/gemma-4-31B-it-qat-w4a16-ct`; write its commit into the build's `provenance` when you
   download it. The run is row S4 of `docs/plan/gpu-ledger.md`. Download it at a fixed commit into a folder, serve
   that folder with
   `vllm serve <folder> --served-model-name gemma-4-31b-it --max-model-len 32768` (the full-record path sends up to
   28,000 tokens; bf16 weights are about 62 GB, so it fits on the 96 GB card alone), then the same command with
   `--served-name gemma-4-31b-it --expect-root <folder> --revision <commit> --model-dir <folder>
   --out /tmp/jb-gemma31`. A run that dies (preempted VM) continues with `--resume` and the same `--out`.
3. Side by side: `python -m tools.judge_bakeoff --compare /tmp/jb-current /tmp/jb-gemma31` (exit 1 when the sets or
   prompt versions differ). Copy the two result folders off the VM before it stops.

**Served-name pinning, and what it does not prove.** `--expect-root` is required for a real endpoint. Before the
first item and again after the last, the tool reads `/v1/models`: the `--served-name` must be listed with `root`
equal to `--expect-root` (else exit 3, nothing sent), and the entry must be the same at the end (a restart or a swap
during the run fails the gate). `root` is only the name vLLM was started with. What identifies the weights is the
manifest hash `--model-dir` writes into `metrics.json` (`tools/pin_model.py` format), with the commit from
`--revision`; `--expect-manifest <sha>` refuses a folder with other weights. vLLM copies the requested name into each
answer, so the per-answer name check only catches a proxy that renames. Run nothing else on the port during the run.
A key, if the endpoint needs one, goes in `TB_BAKEOFF_API_KEY` (or `--key-env`): sent only to `--base-url`, over
https or to loopback, never printed or written.

**How to read the gate** (`metrics.md`, first lines; exit 0 passed, 1 failed). Each gated set (synthetic hospital,
MedTxt) is checked on its own, so the larger set cannot hide a failure on the other:

* **wrong exclusions <= 2 %** per set: of the judge's exclusions, the share the label does not exclude (Study A's
  measure), compared without rounding; the 95 % intervals are beside it, and `--max-upper-ci 0.05` gates the pooled
  upper bound;
* **at least 20 exclusions and 50 answers per set, at most 10 % unanswered**: a judge that never decides, or a model
  that fails on the long records, fails instead of passing on 0 of 0;
* both sets present, the pin held at the start and the end;
* `product:unknown_never_excludes` is a check of the product, not of the model: if it fails, stop and report a bug.

Not in the gate, but compare them: precision of "fits", gold-unknown excluded and abstained (a judge that never
abstains excludes on silence), quote found and dated right (an invalid quote turns the answer into unknown, so a low
rate costs recall, not safety), latency per call and per item and tokens per call (night window and cost), and TREC
CT eligible pairs lost (pair labels, about 40 % of the misses are label noise: compare models, do not gate). The
synthetic set has 300 items, 39 of them without a note in the window (not put to the model), and at most 62 correct
exclusions, so its upper bound alone cannot reach 5 %: that is why the bound is gated on the pooled sets.

A candidate replaces the judge only if it passes the gate on the same frozen set and is no worse than the current
judge on wrong exclusions; the change then goes through the full qualify command as a CC1 model change.
