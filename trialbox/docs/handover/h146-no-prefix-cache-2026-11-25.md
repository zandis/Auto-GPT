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
- **H146-02** (Medium, card issued #1514): the cluster manifests (`deploy/platform/components/gpu-pair/llm.yaml`)
  started both servers with no prefix-cache flag. By the integrator's go (7165504439), both now carry
  `--$(TB_LLM_PREFIX_CACHING)-prefix-caching`, filled from ConfigMap `trialbox-serving`. Each overlay's `serving.env`
  sets `no-enable`, and a site overlay merges `enable` to choose the cache. A missing key leaves the argument as
  written, which the server refuses.
- **H146-03** (Low, open): the bench-only second engine's overlay (`docker-compose.serving-second.yml`) replaces the
  command with another engine's. Whether that engine caches prefixes, and its flag, is not covered here.
- **H146-04** (Medium, not run): what the cache costs in time is not measured here. The integrator measures it on
  the bench copy (252 s per run off, against 224 to 341 s on, in the bench note). The box changes only when this
  lands through an update.
- **H146-05** (Low, open): on a single box, doctor judges the setting, not the servers its `COMPOSE_FILE` renders;
  a site override that gives a server its command without the line is not caught (review 1514-2).
- **H146-06** (Low, open): nothing refuses another value before a start; `settings_guard.sh` could (review 1514-3).
- **H146-07** (Low, open): spec 04 still says the prefix cache is on; D-1462 names the amendment, the spec has no
  note (review 1514-4).
- **H146-08** (Low, open, lane G): `deploy/gcp/complete-run-vm.sh` and `gpu-pro6000-run.sh` start both servers
  without the flag, so their runs keep the cache on (review 1514-5).

## The cluster manifests (H146-02)

`test_the_cluster_servers_start_without_the_prefix_cache` (in the same file) builds each overlay (shared-quota,
interim-cloud) with `kustomize build`, or the stand-in of `tests/unit/test_platform_manifests.py` when kustomize is
not installed, as here. It then fills `$(VAR)` in each server's args from the ConfigMaps the container reads, as the
kubelet does: an undefined variable stays as written. `enable` merged into `trialbox-serving` gives the on flag, and
a missing key gives an argument the server refuses. On d5105bd2, 6 of the 7 new tests failed (the coverage test
passed). Mutants, each run and restored:

| Mutant | Caught by |
| --- | --- |
| c1: the verifier's line in llm.yaml removed | 6 failed |
| c2: shared-quota's serving.env says `enable` | 1 failed (the invariant) |
| c3: interim-cloud's serving.env without the key | 1 failed (the invariant) |
| c4: llm.yaml hard-coded to the off flag | 4 failed (the choice, the missing key) |

## The review of d5105bd2 (OCR on #1514)

- **1514-1 (Medium), fixed.** doctor read `deploy/.env` through `inputs_from`, which takes neither a leading
  `export` nor a comment after an unquoted value; compose takes both. So `export TB_LLM_PREFIX_CACHING=enable` ran
  the cache on while doctor said PASS "off". doctor now reads the setting with `rehearsal_real.env_file` when it has
  the box's folder (the review's patch), and the caller's environment still wins, as it does for compose. A quoted
  value with a stray blank (`" enable"`, `"no-enable "`) is a FAIL. Failing first: OCR's five cases and the two
  blank cases, 7 failed on the tree before the fix and pass after it.
- **1514-2 (Low), the text fixed.** doctor's PASS now says what it judged: the rendered servers with
  `--compose-config`, else the setting. Reading a single box's `COMPOSE_FILE` files for a server without the line
  is H146-05.
- **1514-3 (Low), the text fixed.** doctor's FAIL says the servers "may refuse to start or run another option" (a
  value with `=` renders another option; `no_enable` reads as off). A check at every start in `settings_guard.sh`
  is H146-06.
- **1514-4 (Low), partly.** D-1462 names what it amends (spec 04, LLM-23). A note in spec 04 itself is H146-07.
- **1514-5 (Low), not here.** The cloud complete-run scripts (`deploy/gcp/`, lane G) start the servers without
  the flag: H146-08.

## Not verified

No model server ran with the new line, and no cluster built these manifests: kustomize is not installed here,
so the stand-in built them. That the model server takes `--no-enable-prefix-caching` and
`--enable-prefix-caching` comes from the integrator's bench run, not from this card. That it refuses
`--on-prefix-caching` and similar is the argument parser's usual behaviour, not run here.
