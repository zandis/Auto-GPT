# TrialBox deep review (Fable, 8 Nov 2026)

Independent review of the BUILT system on branch `realdata-local` (`/home/user/tb-real/trialbox`, head `af3a2bd`), the design set (`SIMPLE-PLAN.md`, `20-build-map.md`, `19a-completeness-table.md`), the real-data report and the raw GPU-run files. I reviewed as a clinical-informatics engineer, a hospital-staff UX reviewer for Japan and Taiwan, and an LLM-safety reviewer. Earlier reviews' scores were not consulted. The owner's rule applies: no regulatory gates during development; the product and the engineering are judged, not paperwork.

What I ran myself, in a copy of the repo (`/tmp/.../scratchpad/fable-copy`): `tests/unit` 897 passed, 10 skipped (252 s); `tests/console` 131 passed; `python -m tools.e2e_simple --lang ja` 48/48 checks PASS in 72.2 s. The suite numbers in the report reproduce.

## Overall score: 3.3 / 5

A real, working pre-screening appliance with a sound safety design (filters first, unknown is kept, a note answer excludes only when two models agree and the quote is verified, single-model boxes never exclude on notes). The clinical pages are role-based and the Japanese and Chinese catalogues read naturally. It is held below 4 by five things: the 32 GB target is not met and the shipped 5090 profile is the one measured not to fit; code silence on a structured inclusion silently excludes (26 real cancer patients dropped in the real run, and the check that should catch it is hard-coded `True`); the orchestrator API, which hands out chart numbers, has no caller authentication; the canary and the two-model rule in the production path are not tested as shipped; and English internal tokens still leak onto Japanese and Chinese clinical pages.

| # | Dimension | Score | One line |
| --- | --- | --- | --- |
| 1 | Clinical correctness and safety | 3 | Unknown handling and the two-model rule are right; code silence = exclusion is the open false-exclusion path. |
| 2 | LLM layer | 3 | Good prompt, schema and quote check; canary and fit are measurements, not product. |
| 3 | Code quality and architecture | 4 | Typed, tested, audited; internal API trust is the gap. |
| 4 | Clinical UX (PI, CRC, admin; JA/zh-TW; phone) | 3 | Right shape and vocabulary; raw tokens, English refusals and an unranked 65-patient list. |
| 5 | Completeness against the plan | 3.5 | All five steps demo; step 5's "done when" (fit, N-12, zh-TW) is partly met. |
| 6 | Deployability | 3 | Installer, signed bundles and demo image exist; the GPU profile that ships is stale against the measurement. |
| 7 | Evidence quality | 3 | Raw files and hashes are there; several headline numbers prove less than they say. |

## Per-dimension reasons

### 1. Clinical correctness and safety: 3

What is right (`services/orchestrator/scenarios/evaluate.py`):
- A null structured value never excludes: `structured_candidate` (l.351–367) keeps an inclusion in {true, null} and drops only an exclusion that is true; `eligibility()` maps null to `unknown`. The SQL does the same: `GZQO-INC-01` is `date_sub('year', birth_date, index_date) >= 18`, so a missing birth date is NULL, and the real run shows "Age ≥18 不明" patients kept (120 of 268).
- A note answer excludes only when (a) the judge and the verifier give the same predicate (l.234–253), (b) the quote is a substring of an excerpt after NFKC and whitespace normalisation (l.275–287), (c) confidence ≥ 0.75 (`tier()`, l.414–419), and (d) a verifier is configured; without one, `effective_note_block` falls back to `never` (l.383–396). The e2e gate asserts (d). The real run reports `may_block: true`, 2 disagreements and 1 failure sent to a person.
- A model outage fails the job instead of producing a silently structured-only list (`check_judge`, l.258–272).

What is not right:
- **Code silence on a structured inclusion is an exclusion.** `v is False and c.class_ == "structured"` → not a candidate (l.363). On the real run the "malignancy" value set was expanded over a 59-code demo terminology; C80.1 (malignant neoplasm, unspecified) and C50.9 (breast) were outside it, so 26 patients with a real cancer diagnosis were counted as *not malignant* and excluded (`public_e2e_real_pair.json` → `terminology_missed`). In a hospital the equivalent is any local code, 保険病名 or ICD-10-CM extension the value set did not expand to. This is the main false-exclusion path and it does not go through the two-model rule.
- **The two-model rule halves what the model layer catches.** From `filter_first_ja.json`: judge alone block recall 0.70 / false-block 1.1 %; pair 0.48 / 0.3 %. Safe, but it means about half of the true note exclusions land in "to review", which is what the real run shows: 65 listed, 0 high, 65 review.
- **The verifier has a systematic bias** (canary: Qwen answers `fail` on 6 of 9 "silent" cases where `unknown` is expected). In the pair this is harmless only because Gemma was right on every silent case; the pair itself was never canaried as a pair.
- `structured_candidate` returns `False` (excluded) when the engine returns no row for a pid (l.355). A patient missing from the lake snapshot should be `unknown`, not excluded.
- The confidence that gates `high` vs `review` is the model's self-reported probability under guided decoding (prompt: "Confidence is your probability that the verdict is correct"); nothing calibrates it.

### 2. LLM layer: 3

- Prompt `judge_v4.md` is tight (answer from excerpts only, suspected ≠ confirmed, resolved = history, exact quote). Schema `llm_judge_output.schema.json` 1.1.0 with `reason` before `confidence` fixed the guided-JSON run-away on the card (commit `fb9d65f`); before it 28 of 281 calls retried.
- `tb_common/llm.py`: one schema-violation retry, a truncation retry with 4× tokens, audit of every call with input and output hashes. Good.
- **Canary is not in the product.** `services/orchestrator/canary/judge_canary.jsonl` (54 cases) is untracked (`git status`: `?? trialbox/services/orchestrator/canary/`) and no code under `services/`, `tools/` or `libs/` reads it; it was run as a one-off on the VM. There is no start-up or post-swap canary, and the numbers are per model, not for the pair the box runs.
- **32 GB fit: not met as a resident pair.** `fit.json`: "pair-tight" (0.20/0.093, 4k, 2 seqs) fails with 0.2 GiB KV cache; the serving record shows 35,810 MiB in use for the pair. The sleep swap (0.27 each, judge awake 29,623 MiB, switch < 1 s) works on the bench, but "there is no orchestrator code yet to sleep and wake around a batch" (report §6), and the fit-script smoke prompts returned empty, so answers after a wake were never checked (`fit.json` is in fact not valid JSON: `"answer": ,`).
- The shipped profile is the configuration that does not fit (see finding 1).
- Fallbacks are sound: verifier error → unknown; quote not found → unknown; > 10 % unanswered → job fails.

### 3. Code quality and architecture: 4

- Strengths: pydantic v2 contracts generated from 26 JSON Schemas; `mypy --strict`; 1,100+ tests across unit, console, integration and the e2e gate; a hash-chained audit log with `verify`; scrypt passwords, server-side sessions, CSRF per session, `script-src 'none'` CSP, `X-Frame-Options: DENY`; REDCap tokens as 0600 files, masked on screen, never logged; byte-identical re-runs asserted in the gate. The step-by-step DECISIONS log is unusually honest about what is not built.
- **No authentication between the console and the orchestrator.** `POST /jobs/{id}/reveal` (`services/orchestrator/app.py:197–224`) returns a chart number for any pseudonym and takes `by` as a free string that becomes the audit actor. `console/backend.py` sends no header or secret. Anything on the compose `internal` network can reveal MRNs under any name. The v4 deviation list says "caller identity by header, not mTLS"; here it is not even a header.
- `TB_CONSOLE_SECURE_COOKIE` defaults to `0` (`console/app.py:150`); nothing refuses to start in PRODUCTION with it off.
- The PHI scrubber (`tb_common/logging.py:13–17`) knows Taiwan IDs, Taiwan phone formats and the site MRN regex only: no Japanese マイナンバー, 保険者番号, Japanese phone forms or names. The lake keeps note text unredacted (D-111 says so).
- `NoteResult.reason = f"judge unavailable: {str(exc)[:120]}"` (`evaluate.py:229`) carries the LLM endpoint's error text, which `LlmError` builds from `resp.text[:500]`, into the candidate JSON and reports.
- Only the cascade's `AgreementJudge` is unit-tested for disagreement (`tests/unit/test_agreement_judge.py`); the v1 `NoteJudge.judge_excerpts` path that SCREEN runs has no test where the verifier disagrees (the only integration test uses one stub that "agrees with itself", `test_case_inproc.py:158`).

### 4. Clinical UX: 3

Seen in `step4-*.png`, `step2-*.png` and 12 of the 428 `real-e2e-shots/` (PI, CRC, admin; JA, zh-TW, EN; desktop and phone).

Good: role homes land on the work list; the six-step bar; the PI patient panel with the one-sentence "why", the four marks in natural Japanese (声をかける / 情報が必要 / 今回は見合わせる / 後日再確認) and Chinese (邀請 / 需要更多資訊 / 暫不邀請 / 稍後再評估); the CRC's "My work" task list with due dates; the chart-number reveal with a reason; the N1 mail is short and pseudonymous; the admin page states "除外しない：モデルは確認待ちに回すだけ" plainly; the zh-TW phone layout stacks cleanly.

Not good:
- **Raw English internal tokens on JA and zh-TW clinical pages**: "no value in the window", "abstained", "human criterion" (`big-pi-ja-desktop-studies_PUB_ONC_patients_….png`), "unknown_kept" (`step2-s5.png`), plus "必要な対応: confirm flare dates with patient · ask injection willingness" (`step4-pi-home-ja.png`). They come from `services/matching/cascade/engine.py:459,697,705,824` and are shown untranslated. About 23 refusals are the English literal `"forbidden"` (`console/app.py:435,441,458,682,1431,1466`, `console/home.py:326,373,388,434,…`).
- "診療記録の文章（2つのモデルの一致が必要）" on the patient page is model talk on a clinical screen, which FR-UI-17 set out to remove.
- Until commit `52ca430` the exclusion rows read "該当" (applies) for *not present*, which a Japanese physician reads as "excluded" or "meets" (`step2-s5.png`, `step4-pi-home-ja.png`); all 428 walk screenshots predate that fix, so the fixed wording has no screenshot.
- The N1 mail's text part is raw Markdown: "## 本日 2026-11-02", "**2026-11-04 (水)**" (`step2-n1-mail.png`). `mail_gateway/outbound.py:78–88` returns the Markdown unchanged when it has no `<`.
- **On real data the PI list is 65 patients, all "to review", in one unpaginated column** (`big-pi-en-desktop-studies_PUB_ONC_week_list_all.png`, 16,744 px tall), every row with the same unknowns. There is no "ready to approach" vs "needs information" split and no sort by fewest unknowns; with the pair's ~0.5 block recall this is what a hospital will see.
- "Dr. A (synthetic) (P12345)" and the banner "合成データのみ (D0)" on public data; the ja CRC phone header clips "その他" with no scroll affordance (`big-crc-ja-phone-home.png`; `static` CSS l.90 hides the overflow in a nav scroller).
- Criterion labels and PI notes stay in the authoring language (English or zh-TW) inside Japanese pages; this is by decision (D-110), but a JP site will notice.

### 5. Function completeness against the plan: 3.5

Against `20-build-map.md` §2:
- Step 1 (paste → S3 funnel on the synthetic hospital, JA): built, `e2e_simple` stage 1 passes, funnel checked against CSV recounts.
- Step 2 (S20 one Approve, S5/S6/S7, N1/N2, cohort list, screening log, FR-REP-09): built; investigator-only approve asserted (403 for a coordinator).
- Step 3 (REDCap simulator R1–R3/R7/R8, S21, S36, read-back): built; candidate → consented → enrolled asserted.
- Step 4 (homes, header field, three languages, phone): built; command set 96/96; 210-check walk.
- Step 5 "done when": `e2e_simple` in CI — yes (`.github/workflows/trialbox-e2e.yml`); N-11 passes EN 4/JA 2/zh-TW 1 on the deployed files — yes, measured on the card; **N-12 not measured** (TREC stopped early; only the offline projection at API precision); **the serving configuration is recorded** with hashes — yes; **the 32 GB fit result** — recorded as "does not fit side by side; sleep swap works on the bench", which is a measurement, not a fit; zh-TW with the QAT judge not run.
- From the completeness table still open: backup/restore, scheduler-sent N1/N2 (today an external timer runs `python -m console.notify` and `console.rc_read`), the canary in the product, JP code systems (JLAC10, YJ, 保険病名; D-106 "not done").

### 6. Deployability: 3

- `deploy/install.sh` (signed bundle, wizard, compose profile, egress rules, first admin), `tools/apply_update.sh` with nine tampering variants rejected, `check_host.sh`, `make demo` / `demo-bundle`, `docs/DEMO_VM.md` with cost: a real handover path.
- **`deploy/docker-compose.rtx5090.yml` is stale against the measurement**: judge 0.60 + verifier 0.28 resident, `--max-num-seqs=8`, image `vllm/vllm-openai:v0.11.0`, `--guided-decoding-backend=outlines`; last touched in `57b4a26` (D-95), before the 6 and 8 Nov runs that used v0.32.0, default guided backend, 0.22/0.105 and still needed 35.8 GB. A hospital running `install.sh --gpu rtx5090` gets the configuration that was measured not to boot.
- The demo image was not built (no Docker in the build container) and the demo VM not started; the first `make demo-bundle` on a real machine is untested.
- A Japanese site needs the JP code mapping before anything structured works on its export; the TW mapping templates exist, the JP ones do not.
- The RUNBOOK is 312 lines and names real commands; the IT handover would still need a one-page network/port/secret sheet (what listens where, what the compose `internal` network trusts).

### 7. Evidence quality: 3

Strong: raw SIGIR answer files per model and language with hashes; a serving record with sha256 of every model file; the public-data `derivation.json` and PROVENANCE; byte-identical re-runs; a results table with a screenshot per row; the report's own §6 lists what is open.

Overclaimed or weaker than stated:
- "94/94 functions pass": one check is `s.check("cancer codes outside the demo terminology are reported, not silently counted", True, …)` (`tools/public_e2e.py:273–277`) — always true; and "malignancy = recount from diagnosis.csv (codes in the value set)" recounts with the same 59-code terminology, so it cannot detect the 26 dropped patients.
- "422/422 browser walk": the checks are status, `html lang`, raw catalogue keys, `None`/`undefined` and no sideways scroll. The walk passed while ~23 English refusals and English evidence tokens were on JA/zh-TW pages, so it does not measure language quality; and it ran before fix 3.
- "Sleep swap works": memory and timing were measured, answers after a wake were not (empty smoke answers; `fit.json` unparsable).
- "N-12 3.6 % (pass)": an offline projection from API-precision runs, not the deployed files.
- Canary "53/54" and "47/54" are single-model results; the pair the box runs was not canaried.
- The SIGIR numbers also show criterion-level accuracy ≈ 0.68 and block recall ≈ 0.49 for the pair; the report states lost pairs (the safety gate) but not plainly that the pair finds about half of the true exclusions.

## Top 10 findings, by severity

| # | Severity | Finding | Where | Fix |
| --- | --- | --- | --- | --- |
| 1 | High | The shipped RTX 5090 profile is the configuration measured not to fit: two resident servers at 0.60 + 0.28, `max-num-seqs 8`, vLLM v0.11.0, outlines. Measured need for the pair: 35,810 MiB; "pair-tight" fails (`fit.json`). No sleep/wake controller exists in the box. | `deploy/docker-compose.rtx5090.yml:33–45`; `gpu-run-2026-11-08/fit.json`, `serving_config_2026-11-08_tb-gpu-sim.json` | Ship the sleep swap: start both servers with `--enable-sleep-mode` at 0.27, and in `NoteJudge` batch all judge calls for a run, `POST /sleep` the judge, `/wake_up` the verifier, run the verifier batch (one swap per run, not per patient). Pin v0.32.0 and the default guided backend. Make `install.sh --gpu rtx5090` refuse until a `serving_config` for that exact profile exists. |
| 2 | High | Code silence on a structured inclusion is an exclusion, outside the two-model rule. Real run: 26 cancer patients coded C80.1/C50.9 excluded as "not malignant"; the check meant to catch it is hard-coded `True`. | `services/orchestrator/scenarios/evaluate.py:363`; `tools/public_e2e.py:257–277`; `public_e2e_real_pair.json` → `terminology_missed` | Fail closed on value-set expansion: when a grouper expands over a terminology, any diagnosis code in the lake with the grouper's prefix but outside the expansion is reported on S3 as "codes not in the value set: n patients" and the patient's verdict is `unknown`, not `false`. Assert `missed == set()` in `public_e2e`. Load full ICD-10 (and 標準病名/ICD-10-CM) in the demo terminology. |
| 3 | High | The orchestrator API has no caller authentication; `POST /jobs/{id}/reveal` returns a chart number for any pseudonym with a free-text `by` that becomes the audit actor. | `services/orchestrator/app.py:197–224`; `services/console/backend.py` (no header or secret) | Shared secret per service in the compose secrets (or mTLS, as the v4 deviation list already plans); the orchestrator records the console's session user from a signed header, not the request body; rate-limit reveals per actor. |
| 4 | Medium-high | The two-model rule in the path SCREEN runs is not tested with a disagreeing verifier; only the cascade's `AgreementJudge` is. The verifier's confidence is ignored; a verifier `quote_not_found` is counted as a disagreement without saying so. | `evaluate.py:215–253`; `tests/unit/test_judge_tier.py`, `tests/integration/test_case_inproc.py:148–166` | Add unit tests: judge `fail` / verifier `pass` → `unknown`, `disagreements == 1`, tier `review`; verifier `LlmError` → `unknown`, `failures += 1`; verifier quote missing → reason names it. Take `min(conf_judge, conf_verifier)` as the confidence. |
| 5 | Medium-high | The canary is not in the product: the 54-case file is untracked, no code runs it, and it was run per model, not as the pair. | `services/orchestrator/canary/judge_canary.jsonl` (untracked); `grep -rn canary services tools libs` → nothing | Commit it; add `tools/canary.py` that runs the cases through `NoteJudge` (judge then verifier) at box start and after any model change, writes the result to the audit, and sets `may_block = false` (review-only) when any "silent → fail" or "yes → fail" case flips. Show the last canary date on the admin Models tile. |
| 6 | Medium | English internal tokens and refusals on Japanese and Chinese clinical pages; model talk on the patient page. | Screenshots `big-pi-ja-desktop-studies_PUB_ONC_patients_….png` ("no value in the window", "abstained", "human criterion"), `step2-s5.png` ("unknown_kept"); `services/matching/cascade/engine.py:459,697,705,824`; `console/app.py:435,441,458,682,1431,1466` and `console/home.py` (`"forbidden"`) | Make `reason` an enum (`data_gap`, `abstained`, `human`, `quote_not_found`, `disagree`) and translate it in the console catalogue; catalogue keys for every refusal; replace "（2つのモデルの一致が必要）" with "記録の文章" and keep the model line on the admin page only. Extend the walk check to flag any ASCII-only evidence cell on a JA/zh-TW page. |
| 7 | Medium | The N1 mail's text part is raw Markdown ("## 本日", "**2026-11-04 (水)**"). | `step2-n1-mail.png`; `services/mail_gateway/outbound.py:78–88` | Render the text part from the Markdown (strip `#`, `**`, list markers; keep links), and add a test that the text part contains no `##` or `**`. |
| 8 | Medium | On real data the PI list is 65 patients, all "to review", none "high", in one unpaginated column; every row shows the same three unknowns. With pair block recall ≈ 0.49 this is the normal case, not the exception. | `big-pi-en-desktop-studies_PUB_ONC_week_list_all.png`; `public_e2e_real_pair.json` → `tiers`; `filter_first_ja.json` | Split the worklist into "ready to approach" (no unknowns) and "needs information"; sort by fewest unknowns then next visit; paginate at 25; on S3 show per-criterion unknown counts ("Age unknown: 120") so the gap is visible before the list is. |
| 9 | Medium | Evidence overclaims: an always-true check; a tautological malignancy recount; a walk that cannot see English on JA pages; `fit.json` not valid JSON and post-wake answers unverified; N-12 only projected; canary single-model. | `tools/public_e2e.py:273–277`; `deploy/gcp/gpu-fit-test.sh:59–64` (`ask` prints an unquoted empty answer); `eval/parity/replay.json` | Fix `ask` to JSON-quote and to fail the case on an empty answer; re-run the walk on `af3a2bd` and replace the screenshots; run TREC on the card (≈ 1 h, ≈ US$3 per `docs/SERVING_CONFIG.md`); state block recall next to lost pairs in the report. |
| 10 | Medium-low | Hospital-handover gaps that are code, not paperwork: secure cookie off by default with no PRODUCTION guard; PHI scrubber has no Japanese patterns; N1/N2 and the REDCap nightly read depend on an external timer; a patient missing from the snapshot is excluded, not unknown; LLM endpoint error text flows into report JSON. | `console/app.py:150`; `tb_common/logging.py:13–17`; D-108/D-109 (timers); `evaluate.py:355`, `:229` | `trialbox doctor` fails in PRODUCTION with `TB_CONSOLE_SECURE_COOKIE=0`; add マイナンバー (12 digits), 保険者番号, JP phone and kanji-name-after-氏名 patterns; move `notify` and `rc_read` into the orchestrator scheduler; `ev is None` → not a candidate but tier `review` with reason `not in snapshot`; truncate `LlmError` to a code in `reason`. |

## What would get this to 4.5

1. Sleep-swap controller in `NoteJudge` (judge batch → swap → verifier batch), the 5090 compose rewritten from the measured values, and one measured boot-to-SCREEN run on the card with answers checked after each wake.
2. Fail-closed value-set expansion (finding 2) with the public e2e asserting zero silently-missed codes, and the per-criterion unknown and "codes outside the value set" counts on S3.
3. Service-to-service authentication on the orchestrator, with the reveal actor taken from a signed console header.
4. The canary as product code, run on the pair, gating `may_block`; plus v1 `NoteJudge` disagreement tests.
5. Zero ASCII-only evidence or refusal strings on JA/zh-TW pages, enforced by the walk; the N1 text part rendered; the PI list split into ready vs needs-information with pagination.
6. Evidence hygiene: remove the always-true check, re-run the walk after the wording fix, TREC on the card, and a report line that states pair block recall (~0.5) alongside lost pairs.
7. Japanese handover: JP PHI patterns in the scrubber, a JP mapping template (JLAC10/YJ/標準病名) alongside the TW one, timers inside the scheduler.
