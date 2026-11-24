# The gpu suites' key to the local model servers (2026-11-24)

**Reader:** the people who build TrialBox: lane H, the integrator, the walk and the independent reviewer.

Card H-113 (the integrator's comments 7121989208 item 4 and 7122032636 on #639): the model-quality suites read the
local model servers' key from `TB_LLM_EVAL_KEY` and send it as a Bearer credential to the local endpoint only. It is
never logged or printed, a test shows it never appears in any output, and the suites skip nothing when it is set.

## What was there

- **The gpu stage** is `tools/full_set.py`'s stage `gpu`: `pytest -m llm tests/llm tests/unit/test_judge_tier.py`
  with `TB_INTEGRATION=1`. `make full-set` runs it as the last stage of each run. No workflow on master runs it
  yet; the bench workflow proposed on lane H's card H-105 branch (not merged) runs it through `make full-set`.
- **The endpoints.** `tests/llm/test_llm_layer.py` reads `TB_LLM_EVAL_URL` and `TB_LLM_EVAL_MODEL`, which
  `--llm-url` and `--llm-model` set. `test_judge_tier.py`'s real-model test reads `TB_JUDGE_LLM_URL` and
  `TB_JUDGE_MODEL`, which the stage never set: it was skipped in every gpu stage (H113-02).
- **Why the key.** The box's model servers sit behind model-guard (D-177), which wants `Authorization: Bearer <key>`
  on every call; the gateway sends the model key from its compose secret (D-437). The suites call the endpoint
  directly with a plain client and sent no key: every call is a 401, so the tests fail (they do not skip; the only
  skips were a missing URL). No suite read a key under any name before this card.

## What this card does

- `libs/tb_testkit/eval_key.py`: `eval_client(url, model)` is the one way both suites build their client.
  Unset or empty `TB_LLM_EVAL_KEY`: the plain client of before, byte for byte. Set: the key goes on a request only
  when its host is the endpoint's own host and that host is **local**, checked on every request. A set key with an
  endpoint that is not local is refused before any call.
- **Local** is exactly: a loopback name or address (`localhost`, `*.localhost`, `127.0.0.0/8`, `::1`); the box's
  model service names (`model-guard`, `llm-service`, `llm-verifier`, `llm-service-vllm`, `llm-verifier-vllm`); a
  private or link-local address written as an address (`10/8`, `172.16/12`, `192.168/16`, `169.254/16`, `fc00::/7`,
  `fe80::/10`). Any other name, dotted or not, and any public address is not local.
- The key lives only in the request header: its holder's repr is `<redacted>`, and no URL, log line or exception
  text carries it.
- `tools/full_set.py`: the gpu stage sets `TB_JUDGE_LLM_URL` and `TB_JUDGE_MODEL` from `--llm-url` and
  `--llm-model` too, so the judge suite's real-model test runs. The key comes from the operator's environment.

## The walk: the key's lines

Run on the bench host. `KEYFILE` is a path outside the repository and outside any folder that is backed up or
logged, in a parent folder only the walk user can write (mode 0700); no `set -x`. Nothing prints the key, and it is
never on a command line.

```
sudo install -m 0600 -o "$(id -un)" -g "$(id -gn)" /dev/null "$KEYFILE"     # root makes it: the walk user's, 0600
sudo cat "<the box's install>/deploy/secrets/model/llm.key" > "$KEYFILE"      # the one copy; the shell writes it
read -r TB_LLM_EVAL_KEY < "$KEYFILE"; export TB_LLM_EVAL_KEY                 # then: make full-set ... --llm-url <local>
rm -f -- "$KEYFILE"; unset TB_LLM_EVAL_KEY                                    # after the gpu stage: the box keeps the original
```

The first three lines come before the run, the fourth after it. Copy again after a key rotation (an old copy makes
every call a 401). A key with a stray space, CR or control byte (a key file with CRLF line ends) is refused before
any call, by a message without the key.

The `--llm-url` must name the endpoint by a local host as defined above (loopback, a private address or the
service name), or the suites refuse the key. The check is on the name, and the connection goes wherever the name
resolves: on the bench host name the endpoint by a loopback or private address; use the service names only from
inside the compose network (review 1460-6).

## Tests

`tests/unit/test_eval_key_h113.py`, all on the loopback, a made-up key:

- **The invariant:** `test_gpu_stage_with_the_key_skips_nothing_and_never_shows_it`: the gpu stage's own pytest
  command against the strict stand-in (`tools/vllm_standin.py`, which wants the key) with `-l --tb=long` and a
  DEBUG log file: no skipped test (by the junit skip elements and their reasons), all three suites ran, the stand-in
  answered with no 401, and the planted key is in no file the run wrote (stdout, stderr, junit, log) nor in the
  parent's captured output.
- `test_gpu_stage_without_the_key_is_refused_by_the_stand_in`: the contrast: no key, only 401s.
- `test_a_host_that_is_not_local_never_gets_the_key`: a public endpoint is refused without the key in the message; a
  redirect to a public host, another host and another local host get no header.
- `test_unset_or_empty_key_sends_todays_requests_byte_for_byte`: the bytes on the wire are the plain client's; set,
  the one `Authorization` line is the only difference.
- `test_no_object_shows_the_key`, `test_is_local_is_exactly_the_documented_set` (25 hosts),
  `test_full_set_gpu_stage_passes_the_key_through_and_names_both_endpoints`.
- `test_the_key_is_a_secret_setting_the_support_bundle_scrubs_and_no_service_holds`: the support bundle's
  secret list and its scrub's declarations name it; the secrets overlay clears it for every service.

## Review round (the external review of #1460 at 967d535e: fix first)

| Review | Severity | What | Test (fails at 967d535e) | State |
| --- | --- | --- | --- | --- |
| 1460-1 | High | the two gpu-stage tests failed in the pure run (no database) and after any database test (the child took the parent's cluster) | the reviewer's reproductions: pure selection 2 failed, then 37 passed; `test_judge_tier.py` with this file under a test root 2 failed, then 45 passed; with two workers 2 failed, then 51 passed | fixed: the pure tests alone are `nodb`; the child gets its own test root, without the parent's worker or database settings |
| 1460-2 | Medium | every stage, not only gpu, got the judge's endpoint, so the unit stage's stub judge test called the real model | `test_only_the_gpu_stage_names_the_judge_endpoint` | fixed |
| 1460-3 | Medium | a key with a stray space, CR, tab or NUL came back whole in the HTTP layer's error text | `test_a_malformed_key_is_refused_before_any_call_and_never_shown` (5 cases) | fixed: refused before any call |
| 1460-4 | Low | every stage of the set held the key | `test_only_the_gpu_stage_gets_the_key` | fixed |
| 1460-5 | Low | the invariant copied the gpu stage's command and environment | the invariant now runs `full_set`'s gpu command with `full_set._env` | fixed |
| 1460-6 | Low | a local name resolves through the host's resolver | the walk section | page |
| 1460-7 | Low | the page named a bench workflow not on master | the first section | page |
| 1460-8 | Low | the key's copy outlived the run; no step after a rotation | the walk section: a fourth line | page |

Also from the lead: `TB_LLM_EVAL_KEY` is a secret setting: `tools/support_bundle.py`'s `SECRET_SETTINGS` and the
secrets overlay's `x-tokens` block (`test_the_key_is_a_secret_setting_the_support_bundle_scrubs_and_no_service_holds`;
`tests/unit/test_support_bundle_no_secret.py` and `tests/unit/test_compose_secret_reach.py` failed without it).

## Mutation pass

Review round, four more, each caught: no check of the key's form; the judge's names in every stage; the key in every
stage; the child session on the parent's test root and worker.

First round, seven mutants, each caught: every host local; any local host gets the key; an empty key still sends a header; the
holder's repr shows the key; the client logs the header; the suite keeps its plain client; the refusal names the key.

## Findings

| Id | Severity | Claim | Basis | State |
| --- | --- | --- | --- | --- |
| H113-01 | High | the gpu suites sent no key to the guarded model servers: every model-quality call was a 401 | shown | fixed 4ada51f4 |
| H113-02 | Medium | the judge suite's real-model test was always skipped in the gpu stage: it read a URL the stage never set | shown | fixed 4ada51f4 |
| H113-03 | Low | an endpoint named by a dotted host name (a LAN name) is not local here: the walk names it by address or service name | shown | open |

## Not run

No GPU, no model: the stand-in only. The gpu stage on the bench host against its real model servers is the walk's
run once this is on master. The real model-guard was not in the loop here (its own tests cover its key check).

## Files outside the card

`tests/llm/test_llm_layer.py` and `tests/unit/test_judge_tier.py` (the suites' owners): one call each, the client
from `eval_client`; no interface changed. `libs/tb_common/config.py`: three declared settings.
`tools/support_bundle.py`: `TB_LLM_EVAL_KEY` in `SECRET_SETTINGS`, so a bundle redacts it by name and value.
`deploy/docker-compose.secrets.yml`: cleared in the `x-tokens` block with the other host tools' keys, so no service
holds it (`tests/unit/test_compose_secret_reach.py`, `tests/unit/test_support_bundle_no_secret.py`).
