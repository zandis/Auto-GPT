# The model servers start without the prefix cache (2026-11-25)

**Reader:** the people who build TrialBox: lane H, the integrator and the independent reviewer.

Card H-146 (High, ring 0), from the integrator's 7163554019 on #1504. Decision D-1462. No model ran in this card: no
GPU, no model server, nothing that costs money. Compose only rendered the files.

## What changed

- Every GPU overlay's judge and verifier command carries `--${TB_LLM_PREFIX_CACHING:-no-enable}-prefix-caching`:
  `deploy/docker-compose.yml` (llm-service), and both servers of `.gb10`, `.rtx5090`, `.rtxpro6000`, `.dgpu48` and
  `.shared-quota`. Eleven lines in all.
- `TB_LLM_PREFIX_CACHING` is declared in `libs/tb_common/config.py` (default `no-enable`). `tools/prefix_cache.py`
  reads it as compose does (blanks and one pair of quotes dropped, empty is the default). It uses the standard
  library only, because doctor runs it on the host.
- `trialbox doctor` has a new line, `prefix_cache`: PASS "prefix caching off", WARN "prefix caching on ... runs may
  differ", FAIL for another value. With `--compose-config`, it also FAILs a server whose rendered command does not
  carry the flag the setting names.
- The runbook, page 19, last section: how to choose the cache and that runs may then differ.

Why the value is the flag's own first word: compose interpolation can only tell a set variable from an unset one,
so it cannot map `on` to one flag and `off` to the other. An `on`/`off` setting with `${VAR:+...}` would turn the
cache on for a box that wrote `off`. With this form, a wrong value renders an argument the model server refuses, so
the server stops at start and doctor names the value.

## The invariant test and the mutants it catches

`test_the_rendered_servers_start_without_the_prefix_cache` (in `tests/unit/test_no_prefix_cache_h146.py`) renders each GPU
stack the way the product does: `tools.serving_profile.compose_argv` (deploy/.env and its `COMPOSE_FILE`, the `gpu`
profile). There are 7 stacks: base, gb10, rtx5090, rtxpro6000, dgpu48, shared-quota with the platform overlay, and
the two-device spark. The setting is tried absent, empty, `no-enable` and quoted. Every judge and verifier server must
carry `--no-enable-prefix-caching` exactly once, and no `--enable-prefix-caching`.
`test_the_explicit_choice_alone_turns_the_cache_on` checks that `enable` gives exactly the on flag.
`test_the_stacks_cover_every_server_command` fails when a compose file gives a server its command and is in no
checked stack.

Each mutant was run against the card's tests and restored afterwards:

| Mutant | Caught by |
| --- | --- |
| m1: the base file's llm-service line removed | 5 failed (the invariant, the choice) |
| m2: gb10's default made `enable` | 6 failed (the invariant, the declared default) |
| m3: rtxpro6000's two lines hard-coded to `--no-enable-prefix-caching` | 2 failed (the explicit choice) |
| m4: doctor reports PASS for on | 1 failed (the doctor WARN) |
| m5: the helper takes any value | 8 failed (state, doctor FAIL) |
| m6: dgpu48's verifier line alone removed | 5 failed (the invariant on dgpu48) |

On master, before the change, 48 of the card's 60 tests failed (the rendering, the declared setting, doctor). The 12
that passed were the coverage test and the helper's parsing, which uses only the new module.

## Findings

- **H146-01** (High, shown): before this card, no judge or verifier server named the prefix cache, so the model
  server's own default (on) applied on every box. The integrator's bench saw runs differ with it on. Fixed in d2a1187e.
- **H146-02** (Medium, open): the cluster manifests (`deploy/platform/components/gpu-pair/llm.yaml`, another lane's
  files) start both servers with no prefix-cache flag. The same change there needs the `trialbox-serving` config
  map to carry the value. Raised as a question, not changed here.
- **H146-03** (Low, open): the bench-only second engine's overlay (`docker-compose.serving-second.yml`) replaces the
  command with another engine's. Whether that engine caches prefixes, and its flag, is not covered here.
- **H146-04** (Medium, not run): what the cache costs in time is not measured here. The integrator measures it on
  the bench copy (252 s per run off, against 224 to 341 s on, in the bench note). The box changes only when this
  lands through an update.

## Not verified

No model server ran with the new line. That the model server takes `--no-enable-prefix-caching` and
`--enable-prefix-caching` comes from the integrator's bench run, not from this card. That it refuses
`--on-prefix-caching` and similar is the argument parser's usual behaviour, not run here.
