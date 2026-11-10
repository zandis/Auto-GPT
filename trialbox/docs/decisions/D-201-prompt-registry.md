# D-201 Prompts and their output schemas are registry objects, resolved by (id, version)

- **Task:** T-101 (WS-02.3; URS-PI-06, RSK-09; TST-MOD-02)
- **PR:** this branch (`agent/T-101-prompt-registry`)
- **Date:** 2026-11-09
- **Status:** proposed (awaiting review)

## Context

Prompts were files in five `services/*/prompts/` folders, found by globbing, the newest version used by default,
with nothing that noticed an edited text (P-37). The two-model rule (`tb_common.pair`) and the quote check
(`verify_span`) read the judge's answer fields (`verdict`, `quote`, `quote_date`), so a silent change of the judge's
text or of its output schema changes what a note exclusion rests on.

## Decision

1. The fourteen prompt files move, byte for byte, to `libs/tb_llm/prompts/`. `registry.yaml` lists each version:
   `id`, `version`, `file`, `sha256` (of the file's bytes), `schema` (the output schema's name), `schema_ref` (only
   for a schema that is a pydantic model), `schema_sha256` (of the canonical self-contained schema, the same value
   the gateway computes over the `response_format` a caller sends), `approved_by`, `date`, `qualification`.
2. `libs/tb_llm/prompt_registry.py`: `get(id, version=None)` returns the text, the schema and the sha. It refuses
   an unknown id or version (`prompt_unknown`), a file whose sha differs (`prompt_changed`, every environment), a
   front matter that names another prompt (`registry_invalid`), a file schema whose sha differs
   (`prompt_schema_changed`), a prompt with no schema on a patient route, D2 to D4 (`prompt_schema_missing`), and in
   PRODUCTION a version whose `qualification` is null or does not hold (`prompt_unqualified`). `active_set()` lists
   the newest version per id (the admin page's data). `resolve_ref("judge@4")` resolves a version a job recorded,
   unchanged by later versions.
3. `tb_common.llm.load_prompt` reads through the registry (one change serves every loader: the orchestrator's
   scenarios, the cascade judge, the consent, document and site-setup prompts, the channel engine, the compiler and
   the document parser). `TB_PROMPT_DIRS` is removed, so no environment variable points a box at other texts.
4. The gateway resolves `X-TB-Prompt` (`id@version`) in the registry before any route or model: a registered id
   needs a version; the optional `X-TB-Prompt-Sha` (sent by `tb_llm` callers) must equal the registry's; the
   response schema sent must hash to `schema_sha256`. An id the registry does not list passes only in DEV and TEST
   (synthetic data, ceiling D0) or on a D0 call (the public evaluation suites, whose prompts are written in the
   tools); elsewhere `prompt_unregistered`. In PRODUCTION the gateway refuses to start if any entry fails. The
   upstream request carries `X-TB-Prompt-Id`, `X-TB-Prompt-Version` and `X-TB-Prompt-Sha`; the trace store line
   carries `tb.prompt` = `prompt_id@version`; the ledger record carries the prompt and its sha.
5. The two models of a pair agree only on one text: `AgreementJudge` turns a verifier answer given on another
   `prompt@version` or sha into a disagreement (unknown, never an exclusion). `NoteJudge` puts both questions with
   one loaded prompt object, so the same holds by construction.
6. Qualification reference, **provisional** until T-012 defines the `trialbox eval qualify` record:
   `{record: <path under trialbox/>, sha256: <of that file>}`; the file must exist with that sha in PRODUCTION. The
   fourteen prompts in service at `6e11e25` carry `{baseline: 6e11e25}`; the exact `(id, version, sha256)` triples
   are frozen in `prompt_registry.BASELINE`, so a new entry cannot claim the baseline.

## Consequences

- Changing a prompt is: a new file `<id>_v<n+1>.md`, a new registry entry with its sha, a qualification record
  before it can run in PRODUCTION. An edit in place fails `make test`, every load and a PRODUCTION start.
- A schema change (including a pydantic model behind `schema_ref`) needs a new registry entry too.
- Not covered here: the EDC prefill prompt (PR #56 is not on master; its prompt is registered when it lands), the
  NCBI TrialGPT builders in `services/matching/registry_match/prompts.py` (code kept verbatim for the benchmark,
  drift-checked separately), the inline benchmark prompts of `tools/` (`mlbench_judge`, `trialgpt_criterion`,
  `profile_summary`: D0 or DEV/TEST only), and the console admin page wiring of `active_set()`.
