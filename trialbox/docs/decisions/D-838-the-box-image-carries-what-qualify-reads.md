# D-838 the box image carries what qualify reads; the pair gate says it is alive

- **Task:** QUALIFY-FILES, the integrator's red of 2026-11-15 from lane G's GPU box (#639; blocks PoC-1's evidence)
- **PR:** this branch (`agent/QUALIFY-FILES-the-box-image-carries-what-qualify-reads`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-737 (qualify on the box), D-734 (qualify without git)

## Decision

1. deploy/docker/python.Dockerfile copies what `trialbox eval qualify --box` opens: deploy/images.lock,
   tests/fixtures/llm/judge_set.jsonl (synthetic), docs/licences/register.csv, docs/validation/model-change-protocol.md,
   eval/qualification/schema_probes.yaml and eval/injection/. On lane G's box four steps stopped with
   FileNotFoundError; laid out as the image, the stub run also lacked the injection suite and the protocol.
2. A test lays out /app as the COPY lines fill it and runs qualify's stub pair there: any file qualify opens that the
   image lacks fails it.
3. The pair gate prints how many items are answered every 30 s and at the end, whichever item is slow.

## Test

`tests/unit/test_qualify_in_the_image.py`: before, the stub run in the image's layout failed pin, serving_record,
licence, schema and injection with missing files and the pair gate printed nothing; after, all pass.
