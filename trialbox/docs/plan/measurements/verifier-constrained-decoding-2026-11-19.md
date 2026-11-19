# The verifier's whitespace loop and constrained decoding, 2026-11-19 (card H-49)

**Reader:** the lane lead and the integrator, who decide which of the options below is taken and by whom

The card: H-40 found 9 wasted verifier calls (`v-verifier`, prompt `judge@5`, tcga, launches P2b and P3); the
integrator ruled them a card for constrained decoding. The question: can the request path ask the serving stack to
forbid the loop, for that prompt only, with no serving change?

**The answer (shown from the repository and the pinned server's source; not run on a GPU).** No. Schema-constrained
decoding is already on for every call, and the loop happens inside what that constraint allows. The only control that
forbids it in the pinned release is a server start-up flag, which changes every answer of that server. Nothing was
changed in code or prompt data on this card; it stops here with the options for the lead.

## What exists today

- **The request path.** Callers (`tb_common.llm`, `tb_llm.client`) send `response_format` `{"type":"json_schema",
  "json_schema":{name, schema, strict}}` with every call except free-form roles; the gateway refuses a call without
  it (LLM-22, `services/gateway/core.py`, step 2), binds the schema to the prompt registry's `schema_sha256`, and
  forwards only the fields in `UPSTREAM_FIELDS` (`messages`, `max_tokens`, `max_completion_tokens`,
  `response_format`, `temperature`, `top_p`, `seed`, `reasoning`, `reasoning_effort`; D-431). No `stop`, no
  `structured_outputs`, no grammar, no repetition or whitespace control is sent for any prompt. Sampling is forced
  (temperature 0, a fixed seed, `models/routing.yaml`). The constraint is per prompt only through its schema; nothing
  differs by model role (judge vs verifier) or tier.
- **The prompt.** `judge@5` (`libs/tb_llm/prompts/registry.yaml`) has the schema `llm_judge_output`
  (`schemas/llm_judge_output.schema.json`): `additionalProperties: false`, `reason` `maxLength` 300, `quote`
  `maxLength` 400. The looping field is already bounded; the bound does not help, because the loop is not in the
  string (below). A prompt version is immutable (a changed file is refused until registered as a new version).
- **The server.** Every GPU tier runs `vllm/vllm-openai:v0.32.0` by digest (D-348; `deploy/docker-compose*.yml`,
  `deploy/images.lock`). No structured-output flag is set: the backend is vLLM's `auto` (the compose comment, the
  serving record `deploy/measured/serving_config.rtxpro6000.json`, `tools/serving_config.py`). Lane G's review
  (`docs/handover/lane-g-2026-11-16/review-textmining-hardware-serving.md`, 3.1) already says guided JSON is on.
- **The stub.** `services/llm_stub` does not read `response_format`; it answers canned JSON.
- **Decisions.** None requires or forbids a whitespace control. D-431 lists the forwarded fields; LLM-22 requires
  the `json_schema` `response_format`. The schema's own description records the same family of fault once before:
  "forced to add reason, padded whitespace until max_tokens", fixed then by ordering the properties.

## The failing shape (corrects H-40)

Read from the 9 flagged answers in the stored traces (P2b and P3 `tcga.tgz`, scratch folder outside the repository;
nothing copied here). In **all 9** the loop starts **outside** any JSON string: a string value (`quote` in 8, `reason`
in 1) closes, then the answer is only carriage returns and spaces (938 to 4,053 characters) with the object still
open and no other character after. The string closed early: at a quotation mark the model wanted to copy from the
note (which, unescaped, ends the JSON string), or after a short fragment of the quote. After a closed string value a
JSON grammar allows only whitespace, `,` or `}`; the model's text did not mean to stop, so it chose whitespace until
`max_tokens`. H-40's page said "inside a JSON string"; that was wrong, and it is corrected there.

Why the constraint does not stop it: xgrammar (the `auto` choice for a JSON schema) compiles the schema with
`any_whitespace=True` unless the server is started with `disable_any_whitespace`; whitespace between tokens is valid
JSON. `maxLength` limits the string, not what follows it.

## What the pinned release offers (read from vLLM v0.32.0's source at its tag)

The repository does not document a whitespace option. The pinned tag's source was read (public files, no model call):

- `StructuredOutputsConfig.disable_any_whitespace` (server: `--structured-outputs-config`), documented "json output
  will always be compact without any whitespace"; its validator refuses it unless `backend` is `xgrammar` or
  `guidance`, so with today's `auto` it cannot be set alone.
- `StructuredOutputsParams.disable_any_whitespace` and `whitespace_pattern` (request: `structured_outputs`) exist,
  but both the xgrammar and guidance backends read `disable_any_whitespace` from the **server** config
  (`vllm/v1/structured_output/backend_xgrammar.py`, `backend_guidance.py`); the request field is accepted and has no
  effect on this release. `whitespace_pattern` is read by neither backend.
- A request `structured_outputs.grammar` is honoured per request, but `response_format` `json_schema` is turned into
  `structured_outputs.json`, and `json` and `grammar` together are refused as mutually exclusive: a grammar means
  dropping `response_format`, which LLM-22 and the gateway's schema binding require.
- The same file carries a note that its xgrammar (0.2.8) still emits a space after a comma with compact separators.

## So: the options (for the lead)

1. **Server flag on the verifier only.** `--structured-outputs-config={"backend":"xgrammar","disable_any_whitespace":true}`
   on every tier's verifier service (`deploy/docker-compose.rtxpro6000.yml`, `rtx5090.yml`, `dgpu48.yml`, `gb10.yml`,
   the base file's `llm-service`, `deploy/platform/components/gpu-pair/llm.yaml`, the GCP launch scripts), the
   serving record re-captured. No gateway, contract or prompt change; the stub is untouched. It changes every
   verifier answer (compact JSON instead of indented; a closed early string must be followed by `,` or `}`), so it is
   a serving change to qualify on a GPU and the recorded-answer gates. It also names the backend, which lane G's
   review asked for. Expected effect on the 9: the JSON closes with a truncated `quote` or `reason`; whether the
   verdict and the quote check then hold is not known (a short fragment of the note may pass a substring check).
2. **The same on both servers.** As 1, for the judge too; more coverage, more to re-qualify; the judge showed no loop.
3. **A gateway field** (`structured_outputs.disable_any_whitespace` per prompt): a no-op on v0.32.0 (above). Only
   worth building with a vLLM release that reads it per request (not verified for any release).
4. **A grammar per prompt** instead of `response_format`: honoured per request, but an LLM-22 and gateway contract
   change (schema binding, `_schema_ok`), and a grammar to keep in step with the schema. Not recommended.
5. **No serving change:** let the existing path handle it (below) and accept the cost.

## What happens to these calls today (no new heuristic)

`tb_common.llm` reads `finish_reason`: `length` means cut, so the same question is asked once more with four times the
room (`tb_llm.budget.retry_max_tokens`), not with a schema-repair message; the 4,200-character answers are those
retries, and the loop fills the larger room too. The second failure ends in `LlmSchemaError` ("violated schema
twice"). H-40's "repair" column counts only repair messages, so these 9 show 0 there.

## What the next launch must show (after option 1 or 2)

From `trialbox/`, on the launch's tcga set:

```
python -m tools.public_accuracy.waste <run>/tcga.tgz --json waste-tcga.json
```

`sets.tcga.by_model.v-verifier`: flagged 0 (cut 0, loop 0, outside the schema 0), against 5 and 4 on P2b and P3; and
the verifier's estimated output tokens against 55,302 (P2b) and 9,489 (P3), of which 3,044 and 2,724 were the loops.
The seconds saved are not in the traces (no per-call time); the gateway ledger's latency per call would show them.

## Not verified

- No GPU run: whether `disable_any_whitespace` removes the loop on these inputs, and what the verifier then answers.
- The vLLM behaviour above is read from source at the `v0.32.0` tag, not run; the image is pinned by digest, and that
  the digest holds exactly that tag's code was not checked.
- Why some first calls were retried and others not (the attempt records are not in the stored sets).
- `make medtxt-gate` and the recorded-answer tests cannot exercise a server flag; they pass unchanged because nothing
  in the request path changed.
