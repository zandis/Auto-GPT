# TB-PLAN-03 Optimization plan: documents and build to 4.5

| Field | Value |
| --- | --- |
| Document ID | TB-PLAN-03 |
| Version | 0.3 |
| Date | 2026-11-08 |
| Owner | Changfu Kuo (Aimedics) |
| Author | Claude (Fable), as lead architect and independent reviewer |
| Status | Living (accepted by the owner 2026-11-08 "Go"); replaces the step table of TB-DS-20 §2 |
| Basis | TB-REV review of 2026-11-08 (3.3 / 5, findings 1–10); real-data report of 2026-11-08; code `realdata-local` at `70783e2`; owner's answers of 2026-11-08 |
| Rule | No development gates. Everything below is built and measured on synthetic and public data; hospital gates apply only when real patient data is used. |

## 1. Verdict in one paragraph

The architecture is sound and should be kept: filters first, FHIR R4 inside with a DuckDB lake, a note answer excludes only when two models agree on a verified quote, unknown is kept, one gateway to the models, a hash-chained audit. It is carrying more than it needs: two screening engines, an agent layer (Hermes, MCP front door, relay) that is blocked and that ten users with five commands do not need, three databases, timers outside the scheduler, and a shipped GPU profile that does not match the measurement. The 4.5 path is: fix the five review blockers (in flight), remove what is duplicated, make the hardware profile match what was measured, finish the Japanese data path, add trial conduct on the same list-and-task model, and shrink the paper to eight documents that say exactly what the code does.

## 2. Architecture: keep, simplify, replace

| Part | Decision | One-line reason |
| --- | --- | --- |
| Filter-first cascade, lake SQL as the runtime engine, CQL only in the compile-time equivalence gate | **Keep** | It is correct, deterministic and already what the gate asserts. |
| HAPI FHIR 8.12 as the FHIR store of record, JP Core / TW Core | **Keep** (see §7) | Changing the store now rewrites the adapter and the gate for no screening gain. |
| Two note-judge code paths (`scenarios/evaluate.py` NoteJudge and `matching/cascade/`) | **Simplify to one** | Finding 4 exists because the path SCREEN runs is not the one the tests cover. |
| Hermes agent, frontdoor-mcp, channel relay, fake Teams transport | **Remove from the product**; keep the native command engine (96/96 phrasings) | Blocked for want of a pinned release; the deterministic grammar already does the job with an audit line per command. |
| Orchestrator SQLite + workflow Postgres + HAPI Postgres | **Simplify to one Postgres** (two databases, one server) | One backup, one restore, one thing for site IT to understand. |
| MinIO | **Replace** with the filesystem object store (ADR-16, already decided) | One container fewer; the interface exists. |
| External timers for N1/N2 and REDCap read (D-108/109) | **Move into the orchestrator scheduler** | The box must send its own mail. |
| Console → orchestrator trust | **Replace** with a per-service secret and a signed actor header (finding 3, in flight) | Chart numbers must never be revealed to an unauthenticated caller. |
| Gateway as the only path to a model, PHI guard, audit of every call | **Keep** | It is the control point the hospital will ask about. |

## 3. Models: roles, rules, serving

**Roles.** Judge: Gemma 4 26B-A4B NVFP4 (confirmed best; QAT build is worse alone in Japanese and no better in the pair). Verifier: Qwen3.5-9B AWQ, thinking off. The verifier's job is to **confirm an exclusion**, nothing else; it never promotes.

**Pair rule.** Keep "both must say fail on a verified quote" as the exclusion rule: a false exclusion is the one error nobody can recover, and the measured false-block rate is 0.3 %. Accept that this halves model recall (0.70 → 0.48) and make the half that is lost cheap for a person: a disagreement goes to **needs information** with both quotes side by side, so the PI resolves it in seconds instead of reading the chart. Two measured improvements to try, not to assume: (a) give the verifier the judge's quote and ask "does this quote support this verdict?" (an entailment check sees the evidence the judge found, which is where disagreement comes from); (b) confidence = min(judge, verifier). Both are scored on SIGIR before they ship; the N-11 gate stays.

**Quote check.** Keep (NFKC + whitespace substring). Add one rule: a quote that matches only after the fallback to the full record is still `unknown` for exclusion, `review` for the list.

**Canary.** Becomes product code: the 54 cases run through the real pair at box start and after every model change or swap; any "silent → fail" or "yes → fail" flip sets `may_block = false` and shows on the admin Models tile. Per-model canaries stay as evidence only.

**Serving on 32 GB.** The pair does not fit resident (35.8 GB measured). Ship the measured sleep swap: both vLLM servers at 0.27 with `--enable-sleep-mode`, one awake at a time; per SCREEN run, batch all judge calls → judge `/sleep` level 1 → verifier `/wake_up` → batch all verifier calls → swap back. One swap per run, under 4 s. The sleep endpoints exist only with `VLLM_SERVER_DEV_MODE=1` and "should not be exposed to users" ([vLLM sleep mode](https://docs.vllm.ai/en/latest/features/sleep_mode/)): they stay on `model-net`, reachable only from the gateway. Pin vLLM v0.32.0 and the default guided backend, as measured. `install.sh --gpu rtx5090` refuses until a serving record for that exact profile exists.

### 3.1 Best model per role per tier

| Tier | Hardware | Judge | Verifier | How served | Note |
| --- | --- | --- | --- | --- | --- |
| Small | 1 × RTX 5090, 32 GB | Gemma 4 26B-A4B NVFP4, 8k | Qwen3.5-9B AWQ, 8k | Sleep swap, one awake | Protocol reading (ir_extract, 16–32k) runs on the judge by day. |
| Medium | DGX Spark GB10, 128 GB unified | Same pair, resident, 16k | Same, resident | Both resident, no swap; PHI tagger slot free | 273 GB/s memory, about 1/7 of a 5090: slower per token, fine for an overnight batch. |
| Large | 1 × RTX PRO 6000 Blackwell 96 GB, or 2 × RTX 5090 | Same pair, resident, 32k | Same, resident | Both resident (one card) or judge on GPU 0 / verifier on GPU 1 | For CGMH's 50 studies; the only tier with headroom for a bigger judge later. |

A larger judge (for example gpt-oss-120b MXFP4, in the gb10 compose today) is **not** recommended until it beats Gemma on the N-11/N-12 gate on the deployed files; nothing measured says it does.

## 4. Harness around the models

Good as built: prompt `judge_v4` (excerpts only, suspected ≠ confirmed, exact quote), JSON Schema 1.1.0 with `reason` before `confidence`, one schema retry, one truncation retry, audit with hashes, job fails when > 10 % of checks are unanswered. Changes:

| Change | Why |
| --- | --- |
| `reason` becomes an enum (`data_gap`, `abstained`, `human`, `quote_not_found`, `disagree`, `not_in_snapshot`, `model_down`) translated in the console | Finding 6: English tokens on JA/zh-TW pages; finding 10: endpoint error text in report JSON. |
| A patient missing from the snapshot → `unknown`, tier `review` | Finding 10: today it is excluded. |
| Value-set expansion fails closed: codes with the grouper's prefix outside the expansion → `unknown`, counted on S3 as "codes not in the value set" | Finding 2 (in flight): 26 real cancer patients dropped. |
| Confidence = min of both models; verifier `quote_not_found` named as such | Finding 4. |
| One screening engine, tested with a disagreeing verifier, a failing verifier and a missing quote | Finding 4. |
| Agent layer removed; the header command field and mail grammar are the only "chat" | §2. |

## 5. Integrations, one approach each

| System | Approach | Reason |
| --- | --- | --- |
| REDCap (Japan head hospital) | REDCap API, read **and write**: read consent/enrolment/screen-fail/withdrawal as built; write screening status, screening number and the PI's mark into one TrialBox-owned instrument per project with a per-project token (0600 file, as today). Simulator gains the import call. External Module (PHP panels) stays later. | Two-way without installing anything in REDCap; the module adds a PHP deployment for a panel the list page already is. |
| EMR, CGMH | Read-only DWH/CGRD SQL views through the existing `cgrd_sql` adapter and mapping template; nightly. | Already the CGMH pattern; nothing to install on the EMR. |
| EMR, Japan (SSI, Fujitsu) | SS-MIX2 standardised storage reader: PPR-01 → Condition (標準病名 + ICD-10), OMP-01/02 → MedicationRequest (YJ/HOT), OML-11 → Observation (JLAC10), ADT-12/22/52 → Encounter; notes from extended storage or the vendor DWH CSV. No HL7 MLLP listener. | SS-MIX2 is what every JP vendor exposes; notes are not in standardised storage, so the CSV path stays. The largest Japan gap today (`ssmix2/source.py` raises NotImplementedError). |
| FHIR store | HAPI stays; FHIR bulk `$export` import as built; JP Core and TW Core validation sample at ingest. Medplum decision at the trial-conduct step (§7). | See §7. |
| OMOP | A **tool**, not a service: lake → OMOP CDM 5.4 parquet following the HL7 FHIR-to-OMOP IG; DQD on the export. SNOMED concepts only where the site holds a licence (Japan and Taiwan are not members). | Research offices ask for it; it needs no runtime on the box. |
| Mail / LINE / Teams | One notice abstraction with one rule: PHI only inside the hospital's own mail domain; LINE and Teams carry a **nudge** ("today's list is ready", link) and nothing else. LINE through the egress allowlist as a fourth allowed destination. | LINE is how CRCs in Taiwan and Japan actually talk; the nudge adds no PHI path. |

## 6. UI/UX for the two daily users

The shape is right: role homes land on the work list, six-step bar, the one-sentence "why", four marks in natural Japanese and Chinese, chart number on request with a reason. Change these, all small, all measurable by the browser walk:

1. **PI list** split into *ready to approach* (no unknowns) and *needs information*; sorted by fewest unknowns, then next visit; 25 per page. A disagreement row shows both quotes. On S3, per-criterion unknown counts ("Age unknown: 120") and "codes outside the value set: n" before the list exists.
2. **No model talk and no English tokens** on JA/zh-TW clinical pages: the enum of §4, catalogue keys for every refusal, "記録の文章" instead of "2つのモデルの一致が必要"; the walk fails on any ASCII-only evidence or refusal cell.
3. **CRC "My work"** gains two things for conduct: visit windows (due, open, overdue) from REDCap events, and a two-tap contact outcome (reached / not reached / declined / consented) that writes the screening log.
4. **N1 mail** text part rendered from Markdown; a test asserts no `##` or `**`.
5. **Criterion labels in the reader's language.** The compiler already drafts the ruleset; it drafts the JA and zh-TW labels too, and the investigator approves them on S20 with the criteria. This reverses D-110 and needs the owner's yes (§11).
6. Phone: the clipped "その他" in the CRC header gets a scroll affordance; the banner says "公開データ (D0)" on public data; S5 shows the practitioner from the CSV.

## 7. FHIR platform comparison and pick

Criteria: licence, runtime added to the box, what it gives screening today, what it gives trial conduct, JP/TW profile support, activity.

| Option | Licence | Runtime | Screening value now | Conduct value later | Verdict |
| --- | --- | --- | --- | --- | --- |
| HAPI FHIR JPA 8.12 | Apache-2.0 | Java + Postgres (built) | Store of record, CQL `$evaluate` gate, `$expand`/`$validate-code`, loads JP Core / TW Core | Questionnaire/SDC possible, no auth, no subscriptions worth the name | **Keep now** |
| Medplum 5.2.x | Apache-2.0 for the platform; hosting, support and integrations are paid ([medplum.com/open-source](https://www.medplum.com/open-source), [GitHub](https://github.com/medplum/medplum)) | Node + Postgres + Redis (new) | Nothing the lake does not already do; no CQL engine | OAuth2/OIDC/SMART auth, access policies, subscriptions, bots, Questionnaire forms, on-prem HL7 agent, React components | **Spike at the conduct step**; adopt only if the spike passes on JP Core profiles and the equivalence gate moves to cql-execution |
| Aidbox | Proprietary; free for development only, paid in production | Clojure + Postgres | — | — | **Reject**: licence cost per site |
| LinuxForHealth FHIR (IBM) | Apache-2.0 | Java | — | — | **Reject**: no commits since April 2024 |
| OpenMRS / OpenEMR | MPL-2.0 / GPL-3.0 | Full EMRs | Not a FHIR store; the hospitals already have EMRs | — | **Not applicable** |
| EHRbase | Apache-2.0 | openEHR, not FHIR | Wrong data model for JP Core / TW Core | — | **Not applicable** |

**Pick: HAPI now, Medplum as the one spike that decides the conduct architecture.** Reason: screening gains nothing from a store swap today, and Medplum's real value (forms, auth with hospital SSO, subscriptions) is exactly the trial-conduct work in step 9. Never two FHIR stores in production.

## 8. Hardware tiers

| Tier | Box | Memory | Fits the pair | Approx. cost | Recommendation |
| --- | --- | --- | --- | --- | --- |
| Small (one department, ≤ 10 studies) | x86 workstation, 1 × RTX 5090 | 32 GB GDDR7, ~1.8 TB/s | As a sleep swap (measured: 27–29.6 GB awake, swap < 4 s) | GPU ≈ US$2–2.5k + host | **Yes**, with the swap controller of step 1 |
| Medium (one hospital, unified memory) | NVIDIA DGX Spark GB10 | 128 GB LPDDR5X unified, 273 GB/s ([StorageReview](https://www.storagereview.com/review/nvidia-dgx-spark-review-the-ai-appliance-bringing-datacenter-capabilities-to-desktops)) | Both resident, plus PHI tagger | US$3,999 | **Yes as a second measured profile**: arm64 images exist (`docker-compose.gb10.yml`); pin the driver; measure the night batch, which will be slower per token |
| Medium, AMD | Strix Halo (Ryzen AI Max+ 395) mini-PC | 128 GB unified, ~256 GB/s | Memory yes; vLLM only through community gfx1151 containers, official ROCm support still pending ([Strix Halo KB](https://whylucian.github.io/softab/docs/rocm-support.html); [llama.cpp-only measurements](https://github.com/visorcraft/strix-halo-llm-perf)) | US$2–3k | **Not now** for a clinical appliance; re-check in 2027 |
| Large (CGMH: 50 studies, 500k patients) | 1 × RTX PRO 6000 Blackwell 96 GB, or 2 × RTX 5090 | 96 GB, or 2 × 32 GB | Both resident, 32k context, no swap | PRO 6000 ≈ US$8–9k; 2 × 5090 ≈ US$4–5k ([5090 vs PRO 6000 inference](https://www.cloudrift.ai/blog/benchmarking-rtx-gpus-for-llm-inference)) | **PRO 6000 preferred** (one card, headroom for a larger judge); 2 × 5090 is the budget variant already in TB-DS-02 §6.10 |
| 5090 box + Spark linked | Two hosts | — | Possible: the gateway routes the verifier to any URL, so the Spark can serve the verifier | — | **Not a tier**: two drivers, two architectures, one more network hop; only if a site already owns both |

Throughput sanity (estimate, to be measured in step 1): the real run judged 281 checks in 393 s on a capped card, about 2 s per check with two models. A 50-study site with 200 filter-kept patients and three note criteria per study is about 60,000 model calls a night; batched on a 5090 that is a few hours, inside the night window; the Large tier does it in about an hour.

## 9. The document set: 18 → 8

Today's 18 controlled documents plus seven review records total about 1.7 MB and cross-reference each other 1,500 times; drift, not missing content, is what the audits keep finding. Target: eight documents, IDs kept as aliases in the register so nothing cited breaks.

| # | Target document | Merges | Target | What 4.5 means here |
| --- | --- | --- | --- | --- |
| 1 | Baseline and register | TB-DS-00, 00R | 4.5 | Every number and decision in one place; register rows match files (doclint). |
| 2 | Requirements | TB-DS-01 | 4.5 | Build rows (S0–S5, now steps 0–11) first; H rows in an annex; ≤ 3 / 40 sample defects. |
| 3 | Architecture and interfaces | TB-DS-02, 07, 08, 10 | 4.5 | One C4 set, one port table, one data dictionary, one ICD annex; every "built" cell names a test. |
| 4 | Clinical operations and UI | TB-DS-17, 09, 19, TB-REC-01 | 4.5 | Personas, lists, screens and the walk checks in one file; the screenshots are from the current commit. |
| 5 | Verification, operations and configuration | TB-DS-04, 12, 15 | 4.5 | `e2e_simple`, N-11/N-12, canary, serving record, install/update/backup, IQ/OQ/PQ annex. |
| 6 | Security, privacy and risk (H) | TB-DS-03, 11, 16 | 4.5 | Controls trace to code and tests; retired tags gone. |
| 7 | Build plan (living) | SIMPLE-PLAN, TB-DS-20, 21, this plan | 4.5 | The step table of §10 with done-checks ticked by commit; the synthetic hospital spec as an annex. |
| 8 | Hospital pack (H, frozen) | TB-PLAN-01, TB-TMPL-01, 07 | n/a | Untouched until a hospital asks. |
| — | Reviews TB-REV-006..g and this review | archive folder with one index | n/a | Records, not maintained. |

**How 4.5 is scored** (same yardstick for every document, 1 point each; 4.5 = five points with one minor residue, 5 = none): (1) complete against the standard it claims (29148, 42010, 29119-3, 14971 or "owner's plan"); (2) zero stale cross-references and retired tags, by `tools/doclint.py`; (3) every "built" claim names a test, commit or screenshot from the current head; (4) one owner, one status, one change history; (5) a reader in the named role can act without opening another document. Scored by an independent pass after step 11, not by the author.

## 10. Build steps

Sizes: S ≤ 1 day, M 2–4 days, L 1–2 weeks. Each step is one pull request; "done" is its check passing in CI or on the card.

| Step | Work | Fixes | Done-check | Size |
| --- | --- | --- | --- | --- |
| 0 (in flight) | 5090 profile from the measured sleep swap; missed cancer codes fail closed; console→orchestrator service token; v1 disagreement tests; canary committed | Findings 1–4 | `public_e2e` asserts `missed == set()`; reveal without the token → 401; compose pins v0.32.0 and `--enable-sleep-mode`; new unit tests pass | M |
| 1 | Sleep-swap controller in the gateway: judge batch → sleep → verifier batch, one swap per run; fix the fit script's `ask`; one boot-to-SCREEN run on the card with answers checked after each wake; serving record for the profile | Finding 1, 9 | Serving record exists for `rtx5090`; SIGIR EN re-run after a wake equals the resident result; `fit.json` valid | M + ≈ US$5 GPU |
| 2 | Canary as product: `tools/canary.py` on the pair at start and after swap; gates `may_block`; admin Models tile shows date and result | Finding 5 | Flipping one case in a test sets `may_block=false`; tile shows it | S |
| 3 | One screening engine: retire the duplicate note-judge path; reason enum; min confidence; not-in-snapshot → review; LlmError → code | Findings 4, 6, 10 | `grep` finds one `judge_excerpts`; tests for disagree / verifier down / quote missing; no English in `reason` | M |
| 4 | Language hygiene: catalogue keys for refusals and evidence; N1 text render; walk fails on ASCII-only cells on JA/zh-TW; re-run the walk on head and replace all screenshots | Findings 6, 7, 9 | Walk green with the new check; N1 text test; 0 English refusals | M |
| 5 | PI and CRC lists: ready vs needs-information, sort, paginate, both quotes on disagreement; S3 unknown and value-set counts; CRC two-tap outcome; phone nav; D0 banner and practitioner name | Finding 8; §6 | `e2e_simple` stage asserts the split and the counts; walk screenshots | M |
| 6 | Simplify: remove Hermes/frontdoor/relay and their doctor checks; scheduler owns N1/N2 and REDCap read; MinIO → filesystem; secure-cookie guard in PRODUCTION; JP PHI patterns in the scrubber | §2; finding 10 | `docker compose config` lists no hermes/minio; `trialbox doctor` fails with the cookie off in PRODUCTION; scrubber tests for マイナンバー, 保険者番号, JP phones | M |
| 7 | Japan data path: SS-MIX2 reader, JP mapping template (標準病名/ICD-10, JLAC10, YJ/HOT), full ICD-10 in the demo terminology | §5; finding 2 root cause | A synthetic SS-MIX2 folder gives the same GOUT-COH funnel as the CSV path; no `terminology_missed` | L |
| 8 | REDCap two-way: screening instrument written by API; simulator import; read-back unchanged | §5 | `e2e_simple` stage: mark → instrument row in the simulator → read back next run | M |
| 9 | Trial conduct v1: visit windows from REDCap events/arms, CRC visit list, follow-up tasks, visits in N1/N2; Medplum spike decided here | Scope item 8; §7 | New `e2e_simple` stage: enrolled patient → visit due → overdue → done; spike report with pass/fail | L |
| 10 | Tiers and handover: `install.sh --tier small|medium|large` from measured profiles only; Spark profile measured; one-page network/port/secret sheet; backup and restore with a test restore | §8; finding 10 | Install refuses an unmeasured tier; restore test in CI on the demo image | M |
| 11 | Notices and evidence: LINE/Teams nudge channel under the no-PHI rule; TREC N-12 on the card; report states pair block recall next to lost pairs; documents merged to eight; independent scoring | §5; finding 9; §9 | N-12 measured on deployed files; doclint clean; eight documents each ≥ 4.5 | M + ≈ US$7 GPU |

Order matters only for 0 → 1 → 2 (serving first, because every model number depends on it) and 7 → 9 (conduct needs the Japan feed to be real). Steps 3–6 can run in parallel. Total about 7–9 weeks of one builder.

**Build scoring.** The review's seven dimensions, each ≥ 4 and mean ≥ 4.5, by an independent re-review after step 11 against the same evidence rules as the documents (point 3 above: a claim counts only with a test, record or screenshot from head).

## 11. Owner decisions (2026-11-08 05:30)

1. **Full platform before any formal trial.** Sites are not test beds, so trial conduct and the FHIR platform decision are built and tested now, not after a pilot. The Medplum vs HAPI comparison is no longer a late spike: it runs as a measured head-to-head early (after step 0), and the winner is used for trial conduct (step 9). Steps 0–11 are all built before any site goes live.
2. **Hermes agent layer removed** (step 6). The native command engine stays.
3. **RTX PRO 6000 (96 GB) for both the Japan head hospital and CGMH.** The Large tier is the reference box for both first sites; the 1×5090 Small tier and the Spark Medium tier stay as measured profiles for smaller sites. Translating criterion labels at approval: decided inside step 5.

4. **TrialBox is fully standalone (2026-11-08 12:25).** Every source (REDCap, a PI's patient database or spreadsheet, EMR/SS-MIX2/SSI, FHIR) is imported into TrialBox; TrialBox works on its own data and syncs two-way with each source. TrialBox has its own REDCap-like data capture (forms/CRFs on FHIR Questionnaire in HAPI, REDCap data-dictionary import), because REDCap cannot be bundled. Revised steps: **8** = standalone data core, importers and two-way sync with per-field ownership and listed conflicts, tested with REDCap off and on; **9** = full trial lifecycle in TrialBox (consent, enrolment, visits, follow-up, AE and deviation logs, ODM/REDCap CSV export); **10** and **11** unchanged.

## Change history

| Seq | Version | Date | Author | Change |
| --- | --- | --- | --- | --- |
| 1 | 0.1 | 2026-11-08 | Claude (Fable) for Aimedics | First draft from the 2026-11-08 review and the owner's answers. |
| 2 | 0.2 | 2026-11-08 | Claude for Aimedics | Owner decisions recorded: full platform before formal trial, FHIR comparison moved early, Hermes removed, RTX PRO 6000 for Japan and CGMH. |
| 3 | 0.3 | 2026-11-08 | Claude for Aimedics | Owner decision 4: fully standalone with two-way sync and built-in data capture; steps 8 and 9 re-scoped. |
