# D-300 Prompts and their output schemas are registry objects, resolved by (id, version)

- **Task:** T-101 (WS-02.3; URS-PI-06, RSK-09; TST-MOD-02)
- **PR:** this branch (`agent/T-101-prompt-registry`)
- **Date:** 2026-11-10
- **Status:** accepted
- **Number:** renumbered from D-201, which master gives to test isolation (TB-PLAN-06 §6.1 rule 3)

## Context

Before this change, prompts were files in five `services/*/prompts/` folders. They were found by globbing, the
newest version was used by default, and nothing noticed an edited text (P-37). The two-model rule
(`tb_common.pair`) and the quote check (`verify_span`) read the judge's answer fields (`verdict`, `quote`,
`quote_date`). A silent change to the judge's text or to its output schema would change what a note exclusion
rests on.

## Decision

1. **The registry.** The fourteen prompt files move, byte for byte, to `libs/tb_llm/prompts/`. Two more prompts
   are registered:
   - `crf_prefill@1` stays at `services/edc/prompts/crf_prefill_v1.md`, because another task owns that folder.
     It is the one entry in the closed list `prompt_registry.EXTERNAL_FILES` and is sha-pinned like the rest.
   - `profile_summary@1` was text in `tools/bench_profile.py`. It is now `profile_summary_v1.md`, which renders
     the same messages; a test holds that.

   `registry.yaml` lists each version with these fields:
   - `id`, `version`, `file`;
   - `sha256`, of the file's bytes;
   - `schema`, the output schema's name;
   - `schema_ref`, `module:attr`, only for a schema defined in code (a pydantic model or a dict);
   - `schema_sha256`, of the canonical self-contained schema;
   - `approved_by`, `date`, `qualification`.

   The YAML loader refuses a duplicate key.

2. **`prompt_registry.get(id, version=None)`** returns the text, the schema and the sha. It refuses:
   - an unknown id or version, and any version that is not `[1-9][0-9]*` (`prompt_unknown`);
   - a file whose sha differs from the registry, in every environment (`prompt_changed`);
   - front matter that names another prompt, or a template with `{% %}` blocks (`registry_invalid`);
   - a schema whose sha differs (`prompt_schema_changed`). File schemas and `schema_ref` schemas are both
     re-hashed at load;
   - a prompt with no schema on a patient route, D2 to D4 (`prompt_schema_missing`);
   - in PRODUCTION, a version whose qualification does not hold (`prompt_unqualified`).

   It also provides `active_set()` (the newest version per id, the data for the admin page) and
   `resolve_ref("judge@4")`, which resolves the version a job recorded, unchanged by later versions.

3. **Qualification.** Two forms are accepted:
   - **Baseline.** `{baseline: <commit>}` holds only for the exact `(id, version, text sha256, schema sha256)`
     tuples frozen in `prompt_registry.BASELINE`. These are the prompts in service when the registry was made:
     `6e11e25` for the moved files, `0cc908b` for `crf_prefill` and `profile_summary`. A change to a text or a
     schema leaves the baseline.
   - **Record** (provisional, until T-012 defines the `trialbox eval qualify` record):
     `{record: libs/tb_llm/prompts/qualification/<x>.json, sha256: <of that file>}`. The JSON must name `prompt`
     (`id@version`), `sha256` and `schema_sha256` equal to the entry's. The folder is in the python image
     (`deploy/docker/python.Dockerfile` copies `libs/`; it does not copy `eval/`).

4. **Loaders.** `tb_common.llm.load_prompt` reads through the registry. One change serves every loader: the
   orchestrator, the cascade judge, the EDC prefill, consent, documents, site set-up, the channel engine, the
   compiler and the document parser. `TB_PROMPT_DIRS` is removed, so no environment variable can point a box at
   other texts.

5. **The gateway** resolves `X-TB-Prompt` (`id@version`) before any route or model, and binds the request to it.
   - A registered id needs a version. The gateway records the canonical `id@version`.
   - Outside DEV and TEST, `X-TB-Prompt-Sha` is required and must equal the registry's. All `tb_llm` callers send
     it.
   - The first two messages must be the system and the user section rendered (`prompt_text_changed`
     otherwise). What is compared: the literal text between the template's `{{ }}` expressions must appear
     exactly and in order, the first literal at the start and the last at the end of the message. What an
     expression renders to (the patient's excerpts, the criterion) is not checked.
   - After those two messages only `tb_common.llm`'s one schema-correction turn may follow: an assistant message,
     then the fixed correction text.
   - The response schema sent must hash to `schema_sha256`.
   - **Unregistered ids.** An id the registry does not list passes only in DEV and TEST (synthetic data, ceiling
     D0) or on a D0 call (the public evaluation suites, whose prompts are written in the tools). Anywhere else it
     is refused (`prompt_unregistered`). There is no other exception.
   - In PRODUCTION the gateway refuses to start if any entry fails.
   - **Records.** The upstream request carries `X-TB-Prompt-Id`, `X-TB-Prompt-Version` and `X-TB-Prompt-Sha`. The
     trace store line carries `tb.prompt` = `prompt_id@version`. The ledger record carries the prompt, its sha and
     the registry version.

6. **Free-form roles are an exception.** A free-form role (`frontdesk_converse`, the front desk) sends no prompt
   header and is not resolved here. It stays governed by its route, its data class and the conversation engine's
   own rules (FR-CONV). Registering the front desk's system text is left to the task that owns the front desk.

7. **The two models of a pair agree only on one text.** `AgreementJudge` turns a verifier answer given on another
   `prompt@version` or sha into a disagreement (unknown, never an exclusion). The verifier's opinion records the
   mismatch. The reason code stays `disagree`, because `tb_common.reasons` is owned elsewhere. `NoteJudge` puts
   both questions with one loaded prompt object, so the same holds by construction.

## Consequences

- **Changing a prompt** takes three steps: a new file `<id>_v<n+1>.md`, a new registry entry with its shas, and a
  qualification record before it can run in PRODUCTION. An edit in place fails `make test`, every load, and every
  gateway call or PRODUCTION start.
- **Changing a schema** needs a new registry entry too, including a schema behind `schema_ref`.
- **Remains:**
  - move `crf_prefill_v1.md` into `libs/tb_llm/prompts/` when `services/edc` is free, and drop it from
    `EXTERNAL_FILES`;
  - wire `active_set()` into the console admin models page;
  - T-012's record schema;
  - CI must fetch `6e11e25` (checkout depth), or the byte-identity test fails;
  - the NCBI TrialGPT builders in `services/matching/registry_match/prompts.py` stay outside (verbatim code for
    the benchmark, drift-checked separately);
  - the inline evaluation prompts of `tools/` (`mlbench_judge`, `trialgpt_criterion`) stay outside (D0, or DEV and
    TEST only).
