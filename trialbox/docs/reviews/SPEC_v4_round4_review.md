# Adversarial review, round 4: SPEC v4 (`spec/v4/`, 9 files + README)

Reviewer: lead adversarial reviewer · 17 Oct 2026 · Inputs: `spec/v4/*`, `docs/reviews/SPEC_v3_round3_review.md`, the code at `437ba0a` (`libs/tb_common/recall.py`, `tools/mlbench.py`, `eval/criterion_ml/`, `tests/unit/test_recall_cert.py`, `tools/fetch_open_data.py` untracked). Nothing in the repository was modified. Numbers quoted from `recall.py` were recomputed by running it.

> **Status:** all blockers (B1–B3) and majors in this review were applied to `spec/v4/` in the commit that added this file.

## 1. Verdict

**Yes, with fixes.** v4 is now the right document: the deterministic core is intact, the data platform, LLM control plane, Hermes boundary, deliverable standard, security allocation and rollback plan are each specified to build-contract depth, and every R3 blocker has a real resolution. It is not yet a contract a coding agent can execute without arbitration, because nine writers disagreed on the same facts in parallel. The defects are concentrated where I expected: the recall statistics are described four ways (two of them contradict the shipped code), the S2 zero-hit gate has three different sample rules, the conversation layer's data class is D1-only in §8/§9 and D3 in §3/§10, the package layout in §17.1 does not contain half the paths that §5, §8, §10 and §12 name, and the milestone for patient→trial matching is MS2 in §10 and MS4 in §2/§11/§14/§15/App. A. None of these needs new design; all need one owner to apply the replacements below. Three items are blockers (B1–B3); the rest are majors that would otherwise be rediscovered in sprint 1.

## 2. Blockers

**B1. Recall statistics: four inconsistent descriptions, two contradicting `recall.py`.**
- `10a` §10.14 "Anytime sample sizes … computed with the shipped `ConfidenceSequence`": table gives 288 / 567 / 1,085 / 829 / 56 / 115 / 288. Running `recall.py` gives **296 / 595 / 1,194 / 870 / 56 / 116 / 296**, which is exactly App. F.3 (`19` F.3) and §20.4 ("595 audits"). Replace the §10.14 table with F.3's numbers verbatim.
- `05` §6.7 and `10a` SAFE-12 and `19` F.2 say `certificate()` "currently computes only the single-look `cp_lower`" / "The module accepts 0/1 observations only" / "an anytime-valid version of the cumulative chart-review line is a §10 item". The code already has `known_positive_sequence`, `recall_lower_sequence()` and accepts floats in [0,1] (`test_weighted_observations_and_sequence_recall_line`). Replace SAFE-12's first and third bullets and F.2's last two rows with: "Implemented: real-valued observations in [0,1]; `recall_lower_sequence` for the cumulative chart-review line. Not implemented: per-cell pre-registered α weights in `certificate()` (it splits α/K equally), Horvitz–Thompson rescaling `Y_i = x_i·w_i/w_max`, pooling per canonical criterion, and a log-spaced grid below 0.0005." §1.3 already says this correctly; make it the single statement.
- α allocation: `05` §6.7 example and `19` F.2 say "α/K Bonferroni over K strata"; `10a` §10.14 says "α_c = α·E_c/ΣE pre-registered per cell". Adopt §10.14 (weighted, pre-registered at the first certificate; K fixed for the series) everywhere; change the §6.7 `method` string to `"confidence sequence (WSR 2024 betting); alpha 0.05 allocated per cell in proportion to E_c, pre-registered 2026-04"`.
- Line H (historical enrollees): `05` §6.7 example prints `"method": "Clopper–Pearson, single look"`; `10a` §10.14 says line H uses "the anytime sequence on misses". Because line H is re-issued monthly as enrollees accrue, the single-look figure is the R3-03 error again. Replace the §6.7 example line with `"method": "1 − confidence-sequence upper bound on the miss rate (anytime)"` and DM-16 with "both known-positive lines with sequence-based bounds; the single-look figure for information only".
- Stratum name for the S2b exclusion: `04` §4.5/CAS-10 "`S2b-below`", `05` §6.7 "`S2b-screen_out`", `10a` §10.14 "`S2b-negative`". Use **`S2b-below`** in all three.
- The "9.7 % / 0.3 %" simulation is quoted eight times (README, §1.3, ADR-V4-18, §6.7, §10.14, §16.4, §19.2, F.2) but exists nowhere in the repository; the committed test uses 150 reps and asserts ≤ 5 %. My 300-rep run gives 9.3 % / 1.0 %. Replace every quote with "(reference simulation, `eval/suites/recall_cert/reference.json`, committed at S1-12)" and commit the script and seed before the number is quoted again (C-11).

**B2. S2 zero-hit certification has three different rules.**
- `04` CAS-13: "recall ≥ 0.98 and ≥ 150 judged positives, so at most 3 misses"; `10a` SAFE-9: "≥ 200 judged positive pairs per stratum (≤ 4 misses)"; `16` `lexicon_recall`/VV-24: "one-sided 95 % Clopper–Pearson **lower** bound ≥ 0.98; at zero misses ≥ 149". Only the §16 rule is a bound; 3/150 has a lower bound of ≈ 0.95. Replace CAS-13 and SAFE-9's measurement sentence with: "A stratum is certified only if the one-sided 95 % Clopper–Pearson lower bound of lexicon recall on judged positives is ≥ 0.98 (0 misses needs ≥ 149 positives, 1 miss ≥ 236, 2 ≥ 313, 3 ≥ 386; App. F.1). Strata: criterion type × language (zh-only, en-only, mixed, abbreviation-heavy; ja from MS6), each with ≥ 5 % of the site's sentences (FR-M0-25)."

**B3. Conversation-layer data class: D1-only in §8/§9, D3 in §3/§10.**
- `01` FR-CONV-8 and §3.4.1 step 5: conversation calls "declare D1, or D3 when the text came from a PHI-tolerant channel"; `10a` role table and FR-M4-18, `10b` §10.6: `classify_intent` is "D3 when the thread is bound to a candidate packet". `04` §8.5 routing has `classify_intent`/`frontdesk_converse` only under D1; §8.15 lists both as D1; §9.2 "alias tb-frontdesk, class D1"; §9.6 item 7 "gateway accepts only D1 from Hermes". Under "fail closed, no route → reject" (§8.1 principle 3), every plain-word packet reply is refused. Replace: §8.5 add a row "`classify_intent`, `frontdesk_converse` | D3 (tokenised text from PHI-tolerant channels) | J/F on box only | J/F tenant only | **never** | —"; §8.15 both roles "D1 / D3 (tokenised)"; §9.2 "class D1 or D3 (tokenised), on box/tenant only"; §9.6 #7 "gateway accepts D1 and D3 from Hermes, both routed on box only; never D4". Also delete the `tb-line` Hermes profile's tools (§9.2: `tb.status`, `tb.registry_search`): `01` §3.4.1 and FR-UX-11 say LINE inbound gets only a canned pointer. Replace with "`tb-line` | LINE | none (outbound templates only)".

## 3. Cross-file contradictions (majors) with replacements

**Milestones.**
- M5 patient→trials: `10a` FR-M5-6/7/9/10 **MS2**, §10.5 "brought forward to MS2"; `01` §2.4 stage 7 "MS2 (open), MS4 (registry)"; `10b` §11.2 MatchWorkflow same; `14` §14 milestone table and §14.17 "MS4 patient→trials"; `14` CMP-71 "M5 patient→trials before MS4"; `19` App. A "MS4"; `19` §19.2 #3 "MS1, MS4". Fix: FR-M5-6 (open studies) MS2 **silent-mode only, CRC champion**, live from MS3; FR-M5-7, FR-M5-9, FR-M5-11 (registry) MS4; CMP-71 "open-study matching before MS2 (silent), registry and tumour board before MS4"; App. A row "MS2 / MS4".
- Screening-visit checklist: `01` §2.4 stage 8 "MS4", `19` App. A "MS4", `10b` FR-M7-18 "MS5". Set all to MS5 (it needs M7 SoA, FR-M7-17 MS4, and G6).
- `episode_lot`: `05` DM-05 "MS2" vs `10a` FR-M1-20 "structured regimen derivation MS4". Set DM-05 to MS4.
- Review page: `01` FR-UX-16/17 MS4, `19` §20.7 MS4; fine. Teams: FR-UX-11 MS4 but `19` S1-10 builds "native email and Teams" in sprint 1: label Teams in S1-10 "fake transport only".
- Clinician review of the 1,015-pair translations: `10a` ML-24 "≥ 20 notes per language, before MS2"; `16` VV-32 "all 326 sentences of each rendering, R = MS1"; `19` §20.7 dependency table "needed by MS2"; PLAN-RK-05 "stratified sample before MS2"; `eval/criterion_ml/README.md` "all 326 sentences … before these sets gate anything". MS1's exit (`19` §20.7) gates on "`judge_public` ≥ 0.85 per stratum", i.e. on unreviewed translations. Fix: ML-24 → VV-32 text (full review, MS1); §20.7 dependency row "needed by MS1"; PLAN-RK-05 "full review before MS1".

**Numbers and thresholds.**
- `judge` floors: `16` §16.4 `judge_ml` public "accuracy ≥ 0.82 per non-en language", bake-off floors "≥ 0.85 en, ≥ 0.82 others"; `10a` ML metrics, `19` §19.4, §20.7 MS1 exit "≥ 0.85 in every stratum". Site strata: `16` "sensitivity ≥ 0.90 / specificity ≥ 0.90"; `10a` M4 and ML metrics "sens ≥ 0.95 / spec ≥ 0.90 (MS2)". False-block: `16` "upper ≤ 0.030"; `19` §19.4 "≤ 0.022". Fix (one table, §16.4 owns it, others cite): public accuracy ≥ 0.85 en, ≥ 0.82 zh-TW/ja/mixed until VV-32 completes, then ≥ 0.85 all; site sensitivity ≥ 0.95, specificity ≥ 0.90; false-block upper ≤ 0.030 provisional, ≤ 0.022 target at MS4. PPV of `strong`: `16` `prescreen_patient` "≥ 0.70", elsewhere ≥ 0.75: write "≥ 0.70 in replay, ≥ 0.75 live".
- Importance-sampling floor: `04` LLM-26 "5 % uniform floor"; `10a` SAFE-11 "f = 0.5, replaces AI-15, which §8 MUST retire". Replace LLM-26's clause with "the floor `audit_floor` of SAFE-11 (default 0.5)".
- Line-of-therapy gap: `05` §6.2.2 `new_line_gap_days: 90`, `10a` §10.1 "> 90 d"; `12` §12.3.7 "line-ending gap (default 120 days)". Set §12.3.7 to 90 and cite `lot_rules@tw-onc-1.0.0`.
- Reconciliation tolerance: `05` §5.9.1 "Exact. Any difference is blocking (0.5 % only for non-transactional totals)"; `12` NFR-28 "within 0.5 %"; `10b` §11.6 "over threshold"; `19` §20.7 MS1/MS2 KRIs and §20.9 "≤ 0.5 %". Replace all with "exact for same-transaction totals; ≤ 0.5 % only where the contract documents non-transactional totals (§5.9.1)".
- Clarification turns: `01` FR-CONV-4 "three turns or 48 h"; `10b` FR-AG-8 "up to 5 turns (site parameter)". Set FR-AG-8 to "3 turns or 48 h (FR-CONV-4), site parameter ≤ 5".
- Quiet hours: `10b` FR-AG-10 "22:00–07:00"; `10a` FR-M4-21 "21:00–07:00". Use 22:00–07:00 in both.
- Understanding-email cutoff: `12` NFR-2 "arrives before 15:00 (≤ 150 pages)"; `10a` FR-M1-26 "received by 17:00 … ≤ 40 criteria". Set NFR-2 to "by 17:00, ≤ 40 criteria and ≤ 150 pages".
- Hermes identity assertion life: `04` §9.4 "exp: 10 minutes"; `14` §14.4 "≤ 5 min". Use 5 min in §9.4.
- Hermes→native switch time: `01` §3.8.3 `kill hermes` "≤ 60 s"; `04` HER-31 "within 5 minutes"; `12` §13.5 "≤ 30 min"; `16` §18.5.5/OPS-10 "≤ 15 min". Replace with one rule: "kill switch and automatic health-check fallback: engine switched ≤ 60 s (FR-UX-23); full channel rollback incl. verification ≤ 15 min (§18.5.5)"; delete "5 minutes" and "30 min".
- Night pass 1 start: `12` §13.2 "starts on publish, not a fixed 21:00; the pass table in §4 MUST reflect this" (NFR-25); `04` §4.6 table and `16` §18.2 still say "21:00". Change both to "on publish (≤ 5 min after, NFR-25), 21:15 at the latest".
- HL7 freshness: `05` §5.6.1 "overlay ≤ 5 min p95", `12` NFR-26 "L5 p95 ≤ 15 min"; CDC 10 vs 15 min. §5.6.1 declares §13 normative; set §5.6.1's column to the §13 values.
- ASVS level: `01` FR-SIG-14 and `04` §4.3 "ASVS 5.0 L2" for the signing listener; `14` §14.2.3 "L3 for the signing page and admin console, L2 review page/CDS"; `16` §17.2 "L2 for the four UI surfaces". Adopt §14: L3 signing page and console; L2 review page and CDS card. Edit FR-SIG-14, §4.3 and §17.2.
- G5 approvers: `01` §3.7.1/§3.8.2, `10b` §11.1 "system owner + QA"; `04` §8.16 "Product QA and the research-office delegate". Replace §8.16 "Approvers" with "System owner and QA (§11.1); security also signs for routes, external builds, guard policy and Hermes; the DPO for any class widening".
- G5 fast-track: `04` §8.16 lists "a Hermes or gateway security patch" under two Level A approvals; `01` FR-SIG-15 limits A2 to reverts/narrowings and says widenings are Level B. A patch is a bundle change: route it through §18.4 "Security patch" (expedited bundle, CCB), not A2.
- Egress proxy scope: `04` §4.3 "egress proxy (topology C only)"; `14` SEC-40 "every outbound connection passes `tb-egress`" in all topologies. Fix §4.3 row to "`tb-egress` (all topologies; model endpoints in C only)".
- Key naming: `05` §7.5 `K_pid = HKDF(K_root, "tb/pid/v1")`, rotation via `pid_alias`; `14` §14.5 "`K_site` … rotation only on compromise". Use `K_pid` in §14.5 and reference §7.5's rotation rule.
- SIEM format: `14` §14.9 "CEF … or JSON with ECS names"; `16` §18.3/OPS-05 "mapped to OCSF classes". Pick CEF+ECS (§14 owns the contract); edit OPS-05.
- `summarise_external` class: `04` §8.15 "D1"; `10b` §10.7/§10.8 "D3, on-prem only". Set §8.15 to "D1 (documents) / D3 (forwarded mail about participants); D3 on box only".
- `draft_narrative` class: `04` §8.5/§8.15 "D2 (released aggregates)"; `10a`/`10b` all say "D1 (aggregates)"; `05` §7.1 defines post-accountant aggregates as D1. Set §8 to D1 and add "input must be a `DisclosedDeliverable` (RPT-14)". Leave `summarise_aggregate` the same way.
- Teams class: `01` §3.4.1/FR-UX-9 "Teams is PHI-tolerant inbound (tokenised)"; `04` §4.2 and `05` §7.2 "Teams D1, no patient references". Replace the §7.2 Teams row with "Outbound D1 (cards, counts). Inbound text PHI-tolerant: tokenised at the relay before any model, stored redacted (§3.4.1)".
- Opt-out semantics: `10a` FR-M4-6 "default scope `all_research_use` … (PRIV-8)"; PRIV-8 is retired (`05` §7.16) and the scopes are `research_use`/`contact`/`nhi_secondary_use`/`export_d2` (§6.15). Rewrite FR-M4-6: "Patients with `research_use: deny` are removed at L3; `contact: deny` at S0 and list rendering (§7.13). Site default for patients without a record per DM-22/OD-08."
- Dangling IDs: `10b` FR-M6-5 and `12` §12.3.4 cite **FR-M3-3** (not defined in §10.3); replace with FR-M3-13/14. `14` CMP-14, §15.5, TS-7 cite **PRIV-2/PRIV-7** (superseded): replace with PRIV-20/21/23. `19` §19.2 #14 "§10.12" → §10.11 and ML-12.
- Bulk Data version: `05` §5.6.4/DP-08 "3.0.0, 2.0.0 accepted"; `10a` FR-M0-14 "2.0.0". Set FR-M0-14 to "3.0.0 (2.0.0 servers accepted)".
- Forecast method: `10a` §10.3 (Monte Carlo through five stages with hierarchical Beta-Binomial draws; FR-M3-16 "MUST follow the method above") vs `12` §12.3.4/RPT-25 (moment-match λ to Gamma, Poisson–Gamma predictive). State one: "`libs/tb_analytics/forecast.py`: stage probabilities per §10.3; monthly rate λ moment-matched to Gamma and propagated as the Poisson–Gamma predictive (§12.3.4); 10,000 seeded paths". Edit FR-M3-16 and RPT-25 to cite it.

**Paths (§17.1 is declared normative but omits most of what other sections name).**
- `04` §4.3 `services/converse_native/`, `services/channel_relay/`, `services/model_registry/`; `16` §17.1 and `19` S1-07/S1-10 `services/channels/` (native engine), `services/registry/`. Adopt §17.1; edit §4.3 and §8.4.
- `04` §8.2 "rewritten `libs/tb_common/llm.py`"; §17.1/S1-06 `libs/tb_llm/` with a shim. Edit §8.2.
- `04` LLM-24 `services/matching/calibration/abstain.py`; §17.1, VV-40, S1-12 `services/orchestrator/calibration/`. Edit LLM-24 and the §4.3 matching row.
- `05` §5.19 `dataplat/{l0_landing,…,l5_serving}/`, `connectors/`, `services/hl7_listener/`, `services/vault/`; §17.1/S1-02 `dataplat/{landing,validate,…}/`, `sources/`, `mpi/`. Rewrite §5.19 to §17.1's names (keep `services/vault/` as a separate K15-adjacent service or move it to `dataplat/mpi/`; say which).
- `10a` FR-M0-14 and ML-17 place SS-MIX2/JP Core under `services/adapter/…`, which §5.19 retires at MS1. Use `dataplat/sources/ssmix2.py` and `dataplat/standardise/jp_core/`.
- `12` names `libs/tb_analytics/`, `libs/tb_reports/`; §17.1 names `services/deliverables/` and neither lib. `10b` names `services/{tracking,lifecycle,abstraction,closeout,nhi,network,agent}/`; `10a` `services/feasibility/recruitability/`; `14` `libs/tb_security/`, `services/keys/`, `services/mcp/`, `services/siem_forwarder/`; `04` `services/cds_hooks/` (present) and `deploy/hermes/` vs §17.1 `integrations/hermes/`; profiles `tb-staff/tb-line/tb-admin` (§9.2) vs `tb-internal.yaml` (§17.1, S1-11). Add every one of these to §17.1 (or rename the sections to §17.1's paths) and use `tb-staff`, `tb-line`, `tb-admin`. C-9 ("every MS0/MS1 requirement maps to concrete packages") is not met until this is done.
- Forecast ledger lives in three places (`services/feasibility/recruitability/ledger.py` §10.3, `services/tracking/ledger.py` FR-M6-12, `tb_analytics.forecast` §12). One table `forecast_ledger`, one writer in `services/tracking/ledger.py`, maths in `libs/tb_analytics/forecast.py`.

**Small-cell profiles (§7 vs §12).** Consistent (11 external / 5 internal, base 5, bands); only `12` §12.2.3 `dc.alliance` must say "ε accounted per PRIV-22" and OD-12 must name §12.2.3 profiles. No change needed beyond cross-references.

**Hermes tools.** §3.4.3, §9.3 and S1-09 agree on the eight `tb.*` tools. Two leaks: `10a` FR-M0-28 introduces `tb.atlas.computability` as a "T0 tool" (dot-namespaced like a front-door tool; HER-8 says exactly eight): rename to the internal function `atlas.computability()`. `04` §9.2 `tb-line` profile (see B3).

**Runtime.** `14` K3/SEC-52 "rootless Podman; `policy.json`"; `01` §1.1, `04` §4.8.3, `16` §18.1, `12` NFR-57 "compose". State once (§17.2): "rootless Podman with `podman-compose`; Docker Engine accepted only where the hospital mandates it, recorded as a deviation".

**Restore window.** `14` SEC-97 "full-site restore ≤ 36 h … keeps the hospital inside the Taiwan recovery window"; `12` §13.5 "RTO ≤ 5 working days without a spare unit". Add to NFR-42: "CI-designated hospitals MUST hold a cold-standby unit; without one the 36 h target is not claimed."

**Facts vs code (minor).** `01` §1.1 "`test_recall_cert.py` 4" → 6 test functions. `16` ENG-14 "`docs/OPEN_DATA.md` … not yet written" → it exists untracked, as do `tools/fetch_open_data.py`, `tests/integration/test_open_data_e2e.py`, `services/adapter/mapping/mimic/`; say "untracked at `437ba0a`". `01` §1.2 and `16` §16.3.1 cite `trialgpt/` as a sibling directory; it is not in this worktree, so S1 must include "vendor `trialgpt_local/` into `services/matching/registry_match/`". `12` DL-5 P-T1 adds `screen_fail_risk (calibrated, with band)`; no FR defines it and §15.3 lists "ranking by predicted outcome" as a drift trigger: drop the column or add an FR-M4 row with its calibration evidence.

## 4. Round-3 findings R3-01…R3-44 (Appendix I claims verified)

| ID | Status | Note |
| --- | --- | --- |
| R3-01 | resolved | IR v3 §6.2, library §10.1, per-domain floors §10.1; CIRCE n/a marking is a good addition |
| R3-02 | partly | design resolved (S2b, CAS-12/13, SAFE-9); the certification rule is inconsistent (B2) |
| R3-03 | partly | sequences implemented and specified; sample-size table wrong, line H still single-look in §6.7, HT/α-weights pending (B1) |
| R3-04 | resolved | FR-M1-11/12 agreement with library + gold, V check on drafted/variant/seed |
| R3-05 | resolved | CAS-5 sentence-set key, CAS-6 dirty-set rules |
| R3-06 | resolved | CAS-17, §6.5 tier rules, FR-M4-13/16 |
| R3-07 | partly | engine specified (§10.5); milestone contradiction MS2/MS4 (§3) |
| R3-08 | resolved | CAS-16, DM-13 |
| R3-09 | resolved | L0–L5, OpenLineage, Provenance (§5.3, §5.15) |
| R3-10 | resolved | control totals exact, publish gate (§5.9); NFR/KRI "0.5 %" wording must follow (§3) |
| R3-11 | resolved | MPI, merges, erasure with replay-break policy (§5.14) |
| R3-12 | resolved | HL7 v2 and CDC with Db2/IIDR caveat (§5.6.2/5.6.5) |
| R3-13 | resolved | ADR-V4-10, OD-04 |
| R3-14 | resolved | Z-TRE, DP-07, FR-M0-22 |
| R3-15 | resolved | `tb-terminology` (§5.11) |
| R3-16 | resolved | §7.1–7.2, App. G, enforced in code (PRIV-13/15) |
| R3-17 | resolved | §7.6–7.7 with thresholds and certificate |
| R3-18 | partly | coverage and gate specified (§7.14, PRIV-30); test set is site-built under IRB, so the gate cannot pass before MS2 — add a public synthetic set to S1-08 as the CI floor |
| R3-19 | resolved | `TBResearchConsent` (§6.15, §7.13) |
| R3-20 | resolved | §8.2–8.5, 8.11 |
| R3-21 | resolved | §8.2, S1-06 |
| R3-22 | resolved | `origin_call_id` on cache entries, LLM-42 |
| R3-23 | resolved | §8.6, SEC-73/75 |
| R3-24 | resolved | ADR-V4-14, LLM-45 |
| R3-25 | resolved | `channels.engine`, §9.10, VV-03 |
| R3-26 | resolved | HER-2/3/23/30, FR-SIG-10 |
| R3-27 | resolved | §3.4, App. D; row-handle vs `P0156` alias in examples should be reconciled |
| R3-28 | resolved | FR-UX-11/14; LINE profile contradiction (B3) |
| R3-29 | resolved | §3.8 control plane with simulation and kill switches |
| R3-30 | resolved | FR-UX-29…34, NFR-65 |
| R3-31 | resolved | §14.3, §14.16 allocation, `security_matrix.py` |
| R3-32 | resolved | §14.4 |
| R3-33 | resolved | §14.5 (naming `K_site`/`K_pid`, §3) |
| R3-34 | resolved | SEC-90, SEC-95–97 |
| R3-35 | resolved | §14.9, §14.11–14.12, SEC-75 |
| R3-36 | resolved | TDS §12 |
| R3-37 | resolved | DL-2, DL-3 |
| R3-38 | resolved | §12.10 |
| R3-39 | resolved | §2.4, §10.7, App. A (milestone mismatches, §3) |
| R3-40 | resolved | §16.3, VV-21, S1-13 |
| R3-41 | resolved | §16.6 four-phase programme; VV-41 correctly forbids public thresholds for live acceptance |
| R3-42 | partly | procedure as code specified; `tools/bakeoff.py` and task modules do not exist; no results (correctly not quoted) |
| R3-43 | resolved | §18.5 per class, §20.7, §20.9 |
| R3-44 | resolved | 7 FTE, 96 weeks, p80; honest "no buffer" |

Appendix I is accurate as a mapping; it overstates R3-03 ("implemented") and should mark R3-02/03/07/18/42 "partly" with the items above.

## 5. New findings beyond the contradictions

- **N1 (major, unsafe).** `04` §8.6 step 5: an internal D0–D2 call with a PHI hit is "relabelled D3, routed on box" and continues. A D1 protocol prompt that trips the guard should fail closed and open a ticket, not silently run as D3 (the mislabel is the incident). Replace with "block, alert, and quarantine the step for steward review".
- **N2 (major, statistics).** SAFE-9/CAS-13 certify on the *point estimate*; B2 fixes it. Separately, `10a` SAFE-10 "at least 30 excluded and 30 passed patients per month … blinded" and FR-M4-25 "≤ 10 questions per CRC per week" collide at sites with one CRC (40 items/month < 60 plus active-learning items). Add "per-site minimum 2 reviewing CRCs or a research-nurse annotator; otherwise the blinded quota scales to 0.75 × capacity and the certificate prints the shortfall".
- **N3 (major, buildability).** `05` §5.13 commits L4 to Iceberg v2 via PyIceberg with row-level re-keying on merge (§5.14.2) and rewrite-and-expire purges (§5.14.4). PyIceberg row-level update/delete and DuckDB `iceberg` writes are the least mature pieces of this stack; the fallback exists but the MS0 exit criteria do not test it. Add to §20.7 MS0: "Iceberg writer qualification (merge re-key, purge, rollback-to-snapshot) on Synthea 300k, or the §5.13.1 fallback is declared".
- **N4 (major).** `19` §20.8 "first sprint (weeks 1–3)" contains 16 tasks that are the whole of MS0 (gateway, registry, trace store, MCP server, channels, Hermes hardening, L0–L5 thin path, IR v3 schema, recall ledger, public suites, bake-off, doctor). At 7 FTE this is 8–10 weeks. Retitle "MS0 backlog in dependency order" and mark the actual 3-week slice: S1-01, S1-02, S1-03, S1-05, S1-06 (v0: class check, route refusal, audit), S1-12, S1-15 (schema only).
- **N5 (minor).** `04` §9.3 and §14 SEC-74 pin MCP "2026-07-28 (uncertain)" and ADR-V4-08/§9.5 cite CVE numbers and Hermes versions marked uncertain. Fine as written; keep them out of the trace matrix until verified (§15.6 already does this).
- **N6 (minor).** `19` App. D proposal `row = packet-id "#" 1*3DIGIT` vs `01` §3.4.4 proposals `CONFIRM P0156 P0203`. Both are orchestrator-rendered so neither leaks to Hermes; pick the alias form (it is what FR-M4-5 and the packets print) and delete `row`.
- **N7 (minor).** `01` FR-M0-18 still checks "the WebAuthn/TOTP store"; SEC-20 removes TOTP. Replace with "WebAuthn and OCRA stores".

## 6. First sprint (§20.8) executability

Dependency order is internally consistent (every `Deps` precedes its task; parallel tracks are disjoint). Paths follow §17.1 except S1-12 (`services/orchestrator/calibration/` for the recall ledger, which §10.14 puts in Postgres tables `recall_cell`/`recall_observation`; name the package `services/orchestrator/recall/`). Blocking issues: (a) scope is MS0, not three weeks (N4); (b) S1-04's done-criterion depends on `tools/fetch_open_data.py` and the e2e test, which are untracked—add "commit the open-data fetcher, fixtures and `docs/OPEN_DATA.md` under VV-10/11" as S1-00; (c) S1-11 needs the Hermes release pinned and mirrored (ENG-08) and the `tb_relay_adapter` contract test (HER-7), neither listed; (d) S1-13's `criteria_extract_public` needs the Chia licence confirmed (App. H "uncertain") before the loader ships; (e) S1-14 cannot complete without the key (A7) and should carry `--dry-run` as its done-criterion only. With these, the slice in N4 is executable in order.

## 7. Ten highest-value improvements still missing

1. **One statistics appendix owned by code.** Generate App. F (sample sizes, the 12-look simulation, certificate example) from a committed script with a fixed seed, and have CI diff the spec's numbers against it. Removes B1's class of error permanently.
2. **A certificate-validity test over the *real* ledger design**: simulate pooled cells across studies with changing monthly N, drift in p_t, HT weights with f = 0.5 and per-cell pre-registered α, and assert coverage at every look. `recall_cert` as written covers only the i.i.d. single-cell case.
3. **Define `screen_fail_risk` or drop it**, and add an abstention-aware ranking spec for `potential:uncertain` (QBCB inputs, k when r < 30) so DL-5 column semantics are reproducible.
4. **Promote `tb-egress`, OpenBao (K15) and the trace store into §4.3's container table** with class and `talks_to`, so `deploy/containers.yaml` (NFR-B15) can be generated from the spec.
5. **A single "numbers that must agree" register** (thresholds, windows, timeouts, sample sizes) as `spec/v4/registry.yaml` referenced by ID from every section; the contradictions in §3 are all duplicated literals.
6. **Public PHI-guard test set now**: a synthetic 1,000-item code-mixed set under `eval/suites/deid_synthetic/` (S1-08 mentions ≥ 200) so PRIV-30 has a CI floor before the IRB-built site set exists.
7. **Hermes capability proof as a property test**, not a checklist: enumerate every tool the pinned release exposes (`hermes tools` output snapshot) and assert the include-list ⊆ the eight front-door tools on every upgrade (HER-7/8 depend on names "to confirm").
8. **Expected-count fixtures for the MIMIC e2e** derived by an independent SQL implementation committed beside the pipeline (the spec requires a second engineer's query; commit it so CI reruns it).
9. **Forecast model validation on open data**: back-test the Poisson–Gamma/hierarchical model on published site-accrual series (the PLoS One 2022 datasets) so FR-M3-14's "from day one" has a measured calibration before any site history.
10. **A migration note for v1 installs** (pid alias, ruleset recompilation at next G1, `services/adapter` shims) as a §18 procedure with its own rollback unit; §5.14.1 and ENG-02 imply it but nothing schedules it.

*End of report.*
