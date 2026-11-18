# Root review 19: the first site on a 32 GB consumer card, with the owner's workstation as the head box (lane J, B-21, 2026-11-18)

**Reader:** the owner (a clinician) first, then the builders and whoever revises plan 10.

**The owner's ruling (2026-11-18).** "They want 5090 first due to budget issue, I have a 6000." The advice of reviews
13 and 17 (buy the RTX PRO 6000 for the site; drop the 32 GB tier in Japan; plan 10 decisions 32 and 79) is overruled.
Also ruled: one complete release for the first site; federation by a signed study package (a coordinating box signs,
each site imports and returns counts only); a cap of US$500 for cloud runs counted at spot prices; borrow rather than
buy a unified-memory machine.

**What this review did.** It goes under reviews 05, 08, 13 (tiers), 14 (the study package), 17 (accuracy and models),
18 (set-up) and plan 10 as amended (`origin/agent/B18-plan-10`), and does not repeat them. It reads the code and
configuration that define the 32 GB tier today, the stored measurements (including the superseded folders, read as
history), and the P2b launch traces (`integrator/p2b-artefacts`, read with `git show`). It redoes the 32 GB memory
arithmetic from the stored measurement, designs the two-box division of labour, and writes the runs that decide the
layout, most of them free on the owner's own card. Nothing was run on a GPU, nothing paid, no model downloaded, no
hospital data read. The first site is "the first site (a general hospital in Japan)", about 500 to 600 beds.

**Marks.** **[M n]** measured here (section 11 gives the command); **[R file:line]** read in the repository (paths
from `trialbox/`, master `6be0f8c01`); **[R nn §x]** read in root review nn (13, 14 and 08 on master; 17 on
`origin/agent/B19-root-accuracy-models`; 18 on `origin/agent/B20-root-setup-operation`) or "plan 10" (on
`origin/agent/B18-plan-10`); **[S n]** a public source opened 2026-11-18 (section 12); **[S2 n]** a secondary source
(a retailer, a press page, an aggregator), weaker than a maker's page; **[O]** opinion, with the reasoning. "Not
verified" where a source could not be opened or a claim could not be checked.

**Names.** Inside this document a model is named by its role and size ("the judge": a 26B mixture-of-experts model,
about 4B parameters active a token, NVFP4; "the verifier": a 9B dense model, AWQ 4-bit [R
`models/registry.yaml:108-111`]); a family is named only where a licence or a measured score needs it (section 3).
"The owner's card" is the workstation card the owner holds; the coordinator calls it 48 GB-class; its exact model is
not confirmed (section 10, item 1), and section 4.1 says what changes if it is the 96 GB RTX PRO 6000 instead.

---

## 0. One page for the owner

**What is true today.**

- **The 32 GB profile exists and was never run as a product.** It holds one model awake at a time (the judge by day;
  for a screening run the judge, then the verifier), 8k context, 4 sequences, and swaps with the model server's sleep
  mode [R `deploy/docker-compose.rtx5090.yml:13-20,104-109`]. On a card capped to 32 GB it was measured for **memory
  and swap seconds only** (2026-11-08) [R same, lines 22-27]. No throughput, no accuracy, no Japanese, no screening run
  and no canary after a wake were ever measured with this profile, on any card (section 1.3).
- **Two statements of the earlier reviews are corrected here** (section 1.4). The "1.43 calls a second at 4 in flight
  on the capped stand-in" (review 13) was measured on the uncapped 96 GB card with both models resident, not on the
  stand-in [R `docs/plan/measurements/g3-2026-11-13/README.md:45`]. And the two models side by side on 32 GB do not
  leave "4 to 5 GiB" of cache (review 13) or "~5 GiB" (review 17 with a smaller verifier): by the stored measurement
  they leave **under 1 GiB** with today's builds (section 3.1).
- **The site cannot read protocols today, and does not need to.** Each protocol's compiled criteria already carry the
  question the model asks of the notes (`note_question`) [R `rulesets/GZQO/ir/GZQO-EXC-11.json`], and an approval
  already pins the judge prompt by version and hash [R `services/criteria_compiler/service.py:261-283`]. What is
  missing is the package that carries them from the head box to the site and the import that checks them (section 2).
- **Your head box is not a profile today.** A 48 GB workstation card falls to the `default` profile: one unregistered
  candidate model, no verifier, labelled as a DGX Spark [R `deploy/gpu_profile.sh:38`; `deploy/docker-compose.yml:
  420-426`; `deploy/install.sh:592`]. It needs its own small profile (card 19-4).

**With 3 to 5 studies, the 32 GB card is enough for the night.** Review 13 sized the site for 15 studies. At 600 beds
and 5 studies of typical load, today's swap layout needs about **0.6 h a night** and **3.3 nights** for the first
load; tuned (16 sequences), about **0.2 h** and **under 1 night** [M 1; opinion on the rates]. The night is not the
problem. The open questions are whether the real card holds the tuned layout with headroom, whether its answers in
Japanese equal the 96 GB card's at the same 4-bit weights, and the risks of a consumer card in a hospital.

**The design in one line.** The owner's box reads and compiles protocols, runs the package's tests and signs nothing by
itself (the coordinating investigator's key signs); the site's 32 GB box screens the hospital's own patients nightly
against imported packages; only a signed package goes in and only signed counts come out, on media (section 2).

**The five changes that matter most.**

1. **Ship today's layout tuned, not a new layout** (section 3): the judge awake with 16 sequences, the verifier woken
   once a run, the "both agree" rule unchanged. Side by side does not fit; the CPU verifier fails the first load;
   a single model cannot exclude under the rule D-89 (cards 19-1, 19-15).
2. **Measure on your own card first, honestly** (section 4): a "ballast" holds the card down to a 5090's free memory,
   so the fit is real; speed and arithmetic precision are not a 5090's and are said so. Then **one confirming run on a
   rented real 5090** (about US$4 to US$8), then the record on the delivered machine before it ships (free).
3. **Add to the package what a screen-only site needs** (section 2.3): the verifier's prompt pin (today only the
   judge's is pinned), the weight hashes the package was tested with, note test cases, and the release it needs; the
   import refuses a mismatch (cards 19-6, 19-7).
4. **Give the head box its own profile and mode** (card 19-4): both models resident at 32k on 48 GB, protocol roles
   only, no patient route.
5. **Treat the consumer card's risks as measured conditions** (section 6): GeForce driver terms say "not licensed for
   datacenter deployment" [S 6]; no ECC on the maker's page; board warranties of 1 to 3 years in Japan [S2 8]; stock is
   thin. Each has a test and a fallback, including a 32 GB professional card that already maps to the same profile.

**What it costs.** Code cards are free. Runs on your card: about 12 hours of the machine, free. The rented real-card
run: about **US$4 (VM at US$0.65/h) to US$8 (container at US$1.39/h) for 6 h** [S 9, S 10]; at most about US$15 with a
second session, against the US$500 cap. It replaces plan 10's stand-in rows B-1, B-2, B-4 and the 300 W run D-2
(about US$21 spot with B-3), so the first site's GPU spending falls from about US$34 to US$45 (plan 10, "required for the first
site's tier") to about **US$4 to US$15** [O, section 4.4]. The machine: a 5090 tower in Japan was **¥1.50 to ¥2.13
million** on 2026-11-10, most models sold out [S2 11]; a spare is a second machine (decision 4).

---

## 1. What the 32 GB profile does today, exactly

### 1.1 The profile, line by line

| Item | Today | Where |
| --- | --- | --- |
| Card match | any name containing "5090" or "RTX PRO 4500" → `rtx5090` | [R `deploy/gpu_profile.sh:16,36`] |
| Tier | `small` = `rtx5090`, installs only on a measured record of its own uncapped card; no override | [R `tools/tiers.py:1-15,41-46`] |
| Measurement rule | card name must contain "5090"; a capped card is refused; both servers with sleep mode; context ≥ 8,192 | [R `tools/serving_config.py:241-242,323-335`] |
| Record on file | none for `rtx5090` (only `serving_config.rtxpro6000.json`) | [R `deploy/measured/README.md`] |
| Judge | the 26B MoE, NVFP4, 17.1 GiB weights; `--max-model-len 8192`, `--max-num-seqs 4`, `--enforce-eager`, util 0.81, sleep mode | [R `deploy/docker-compose.rtx5090.yml:28,98-109`] |
| Verifier | the 9B dense, AWQ 4-bit, 7.5 GiB; 8k, 4 sequences, eager, util 0.81, thinking off, sleep mode | [R same, lines 29,124-137] |
| Host memory | 48 GiB cap per model server (holds the sleeping weights); "host RAM: 64 GB or more" | [R same, lines 20,97,127] |
| Start order | judge loads and sleeps; verifier loads and sleeps; judge wakes | [R same, lines 22-23,111-166] |
| Swap | `TB_MODEL_SWAP=sleep`; one swap per run; a run *holds* the card; a call to the sleeping model gets `model_busy` (interactive) or `model_asleep` (batch); a hold lapses after 3,600 s | [R `services/gateway/swap.py:1-21`; `docker-compose.rtx5090.yml:168-174`] |
| Two-phase screening | judge answers first, verifier questions deferred, then answered in one batch; up to 3 rounds; unanswered → `unknown`, never an exclusion | [R `services/orchestrator/twophase.py:1-27,48`] |
| Wake check | six canary cases after each wake; a failed model's answers become errors | [R same, lines 23-25; `docker-compose.rtx5090.yml:18-19`] |
| Concurrency | `TB_SCREEN_LLM_CONCURRENCY` = the judge's sequences (4) | [R `docker-compose.rtx5090.yml:176-179`] |
| Note rule | `TB_NOTE_BLOCK=both_agree`: a note excludes only when both models agree | [R `deploy/install.sh:482-488`] |
| Label | `TB_PROFILE=P-5090` | [R `deploy/install.sh:592`] |
| Image | the same vLLM image digest as every tier; structured output by vLLM's default backend (`auto`) | [R `deploy/images.lock:49-88`] |
| Model builds | the same weights as the other profiles, pinned as `-rtx5090` builds | [R `models/registry.yaml:294-347`] |
| Protocol reading | "needs 16-32k and runs on the cloud route behind the PHI guard or on a larger box" | [R `docker-compose.rtx5090.yml:33-34`] |

### 1.2 What it cannot do, today

| Capability | On the 32 GB profile | Why |
| --- | --- | --- |
| Read or compile a protocol | no | 8k context [R `docker-compose.rtx5090.yml:33-34`]; the external route is disabled (`g5_record: null`) [R `models/routing.yaml:54-60`] |
| Both models at once | no | measured "does not fit (verifier short of KV cache)" [R `docker-compose.rtx5090.yml:24-26`] |
| Chat or a note check while a run holds the card | "busy, try again" within 30 s | [R same, line 20] |
| The verifier as a second opinion for chat or documents during the day | only by waking it (a swap) | [R `swap.py:13-17`] |
| An 8-bit judge (review 17's fix for the measured Japanese loss) | no | about 26 GB of weights [R 17 §5.1] leave no cache in a 26.4 GB budget [O] |
| Exclude on a note with one model | no, by design | a single model sends note "fail" answers to review (`same_model`, `single`) [R `services/orchestrator/canary_gate.py:289-302`; `scenarios/evaluate.py:692-700`] |

### 1.3 What was measured, how, and what never was

| Item | Value | How | Mark |
| --- | --- | --- | --- |
| Judge awake, all memory | 29,623 MiB | a 96 GB RTX PRO 6000 (Server Edition) in a cloud VM, util 0.27, lane G's own script | [R `docs/plan/measurements/gpu-run-2026-11-08/fit.json`, case `sleep-swap`] |
| Judge cache at util 0.27 | 7.34 GiB = 69,836 tokens | vLLM's start-up log | [R same] |
| Judge asleep | 1,289 MiB | same | [R same] |
| Verifier awake, judge asleep | 28,402 MiB in all | same | [R same] |
| Sleep / wake | sleep 0.4 to 3.7 s, wake 0.3 to 0.5 s | same | [R same] |
| Pair side by side, tight | verifier failed to start: 0.2 GiB cache available, 0.23 GiB needed for one 4k sequence | utils 0.20 / 0.093, 4k, 2 sequences | [R same, case `pair-tight`] |
| "Capped" pair record | 35,810 MiB used for budgets of 0.22 + 0.105 of 97,887 MiB | `--capped-to "RTX 5090 (32 GB), by --gpu-memory-utilization"` | [R `docs/plan/measurements/gpu-run-2026-11-08/serving_config_2026-11-08_tb-gpu-sim.json`] |
| Status of that folder | superseded for evidence; `fit.json` "stays a memory reading of the card" | – | [R `docs/plan/measurements/gpu-run-2026-11-08/SUPERSEDED.md`] |

**Never measured with this profile, on any card:** calls a second; a screening run with the swap and two-phase rounds;
the canary answers after a wake ("not captured on that run" [R `docker-compose.rtx5090.yml:30-31`]); any accuracy set;
anything in Japanese; start-up time with both loads; host memory with both models asleep; heat, power or noise on a
real 5090; a real 5090 at all.

**Never measured on any card, and needed here:** the size of a Japanese judge call. The stored Japanese P2b set (jmed)
made **no model call** (its criteria are all coded) [R 13 §14 M 1], so the call sizes every review uses (median 1,290
tokens in, p95 3,152 [R 08 §1.1 via 13 §3]) are English. Whether Japanese notes fit 8k with the same excerpt budget is
unknown (card 19-19).

### 1.4 Corrections to earlier reviews

| Earlier statement | What the stored record says | Consequence |
| --- | --- | --- |
| 13 §3.2: "1.43 calls a second was measured at 4 in flight on the capped stand-in" (from lane G's review) | G-3's 1.435 calls a second at 4 in flight ran on the uncapped card with 62,592 MiB in use, both models resident, and the folder is superseded [R `docs/plan/measurements/g3-2026-11-13/README.md:45`; `SUPERSEDED.md`] | no throughput figure exists for the 32 GB profile; every 32 GB rate in 13 and 17 is opinion |
| 13 §3.2: both resident at 8k leaves "about 4 to 5 GiB for both" | the judge uses about 3.1 GiB outside its vLLM budget and the verifier about 0.7 GiB; with the stored budgets the pair needs about 31.8 GiB before any cache (section 3.1) | the side-by-side option is out with today's builds, not "untried" |
| 17 §5.2: judge plus a 5 GB verifier "≈ 25 GiB, leaving ~5 GiB cache" | with the judge's measured 3.1 GiB outside its budget, about 3 GiB [O, section 3.1]; and the 5 GB verifier named there carries a licence the owner excluded | option (b) needs a different small verifier and a measurement |
| 13 §4, 17 §6: "first load 3 to 10 nights" at 600 beds | that used 15 studies; the owner expects 3 to 5 | 1 to 4 nights today, under 1 to 2 tuned (section 3.4) |

---

## 2. The design for the first site: two boxes, one division of labour

### 2.1 Who does what

| Work | Head box (the owner's 48 GB-class card) | Site box (32 GB card, in the hospital) |
| --- | --- | --- |
| Protocol in (PDF, registry record) | yes: the protocol roles of the routing table — `extract_criteria`, `extract_soa`, `concept_select`, `match_criterion_library`, `answer_protocol`, `map_questionnaire`, `draft_document` [R `models/routing.yaml:89-96,204-211`] | no |
| Compile: IR, value sets, CQL, SQL, labels in ja and en | yes | no |
| Patient texts drafted by a model (consent explainer drafts and their second-model check; class D1) | yes, shipped in the package [O] | no |
| Package tests: coded test patients and note test cases on the site's model pair | yes, before signing (it can stand in for the site box: section 4.1) | again at import (authoritative) |
| Signing the package | the coordinating investigator's key, on a token, at the head box [O; 14 §3.5] | – |
| Local code maps into the package's value sets | no | yes (`propose_mapping`, a D1 role, or by hand) [R `routing.yaml:97,212-218`] |
| Nightly screening, first load, the patient roles (`judge`, `second_opinion`, `abstract_field`, `draft_query_answer`) | **never** (no patient data) | yes [R `routing.yaml:98-103,219-226`] |
| Chat and front desk (staff text is D3) | no | yes, the judge awake by day [R `routing.yaml:182-188`] |
| Counts back | reads and merges signed counts files | writes the weekly signed counts file |

### 2.2 The life cycle, step by step

"Media" means the ruled transport: a signed file on a stick or by internal mail (plan 10 decision 50).

| # | Step | Box | What crosses, how | What the site sees meanwhile | If the head box is unavailable |
| --- | --- | --- | --- | --- | --- |
| 1 | Protocol arrives | head | the protocol PDF or registry number reaches the head box from the sponsor, jRCT or the site's coordinator; no patient data. For an industry study the sponsor must allow the protocol outside the hospital (14 decision OD-2) | the study page: "sent for reading to the coordinating box" (status, not error: 10E-17) | the protocol waits; screening of other studies goes on |
| 2 | Read and compile | head | – | as above | the site may compile locally in a degraded mode (card 19-10): the judge alone at 16k by day, unsigned, single-site only, marked |
| 3 | Review by the coordinating investigator; sign | head | – | as above | waits |
| 4 | Package to site | head → site | the signed package on media | "package v1.0 received, waiting for the steward" | – |
| 5 | Import: signature, release compatibility, weight hashes and prompt pins against the site's serving, the package's tests run on this box | site | – | the import report: each test passed or failed | the import needs no head box |
| 6 | Local adaptation and PI approval of "the package plus these listed differences" (14 §3.3) | site | – | the differences page | – |
| 7 | Coded list | site | – | within minutes of approval; "notes not yet read" (13 §7.2) | – |
| 8 | First load of notes | site, nights | – | "first load: night 1 of N", N from the tier record (10E-1) | – |
| 9 | Nightly delta | site | – | the morning list | none needed |
| 10 | Weekly counts out | site → head | a signed counts file (funnel, reasons, enrolment, package version, "differs at this site", import test result, the box's release and profile) on media; small cells as D-467 (10D-10) | – | the files wait on the site; nothing breaks |
| 11 | Amendment | head → site | an amendment package; the site's PI approves; the effective date is the site's own (14 §3.4) | "amendment v1.1 waiting for approval" | the site keeps screening v1.0 until its own effective date; a PI may pause the study (whether a pause action exists: not verified) |
| 12 | Close | both | the last counts file | – | – |

**What must never cross:** any patient row, pseudonym, note excerpt, model answer about a patient, candidate list or
audit row [O; 14 §2]. The only thing going out is the counts file; the counts are not personal data if no cell
identifies anyone (APPI reading of 14 §2.1; "not verified against the PPC guidelines' text" there).

### 2.3 What the package must carry so the site needs no protocol reading

Review 14 §3.2 lists the sections (header, study definition, criteria, tests, forms, safety, documents, adaptations,
signature). For a screen-only site these items must be inside, each checked at import:

| Item | Today | Must be added | Mark |
| --- | --- | --- | --- |
| Compiled criteria: IR per criterion with `class`, `logic`, `fallback`, `note_question`, `source_ref`, `text` | exists as files | – | [R `rulesets/GZQO/ir/GZQO-EXC-11.json`] |
| The note-question set per language | `note_question` in English only in the sample | the ja wording beside it, reviewed (review 11's clinician readers) | [R same; O] |
| Value sets with the terminology release they were expanded against | value-set files exist | the release id per value set, so the site's coverage report compares like with like | [R 14 §3.1; O] |
| CQL, ELM and the generated SQL with its hash | exist | the hash in the package's list | [R 14 §3.1] |
| The judge prompt pin: id, version, text sha256, schema sha256 | exists (D-318), written by the approval | carried, and refused at import when this box's gateway does not serve that version qualified (the check exists at run time: D-359) | [R `services/criteria_compiler/service.py:261-283`; `services/orchestrator/scenarios/screen.py:247-275`] |
| **The verifier's prompt pin** | **missing**: the approval pins the judge prompt only | the second-opinion prompt pinned the same way | [R `service.py:277-283`] |
| Derived score pins | exist (`derived_pins`) | – | [R `service.py:284-286`] |
| The model pair it was tested with | `models.judge` in the manifest is a stale free name (`qwen3.5-35b-a3b-q4`, not today's judge) | the weight-manifest sha256 of judge and verifier, compared with the site's pinned builds (the `-rtx5090` builds share the weights) | [R `rulesets/RA-JAK/manifest.yaml:53-55`; `models/registry.yaml:108-111`; P2b `summary.json` `weight_manifests`] |
| Coded test patients and expected results | exist (`tests/expected.json`) | – | [R 14 §3.1] |
| **Note test cases**: synthetic notes per note criterion with the expected answer | **missing** | 3 to 10 cases a criterion, in ja; run at import on the site's pair; a mismatch blocks approval | [O] |
| The release it needs (IR schema, compiler version) | missing | a minimum release; the import refuses an older box | [O] |
| Model-written patient texts and their check record | made per site today | carried as D1 documents | [R `routing.yaml:189-196`; O] |
| File hashes, package hash, Ed25519 signature, signer key id, the central approval's reference | the format is a card (10D-3) | – | [R plan 10 10D-3; 14 §3.5] |

**Not in the package:** screening scope, people, routing, site thresholds, the site's local codes (14 §3.3).

### 2.4 What exists of this today, and what is missing

| Piece | State | Evidence |
| --- | --- | --- |
| A protocol as a folder independent of the hospital (IR, value sets, CQL, SQL, tests, labels) | exists | [R 14 §3.1] |
| Rule sets reach a box only inside the vendor's signed bundle | exists (vendor key only) | [R `deploy/install.sh:21,273,280`] |
| Ed25519 sign and verify with a key register, for monthly aggregates | exists | [R `libs/tb_common/opportunity.py:551,568,586`] |
| Count merging that never sums different definitions | exists (alliance cohorts) | [R 14 §1.1] |
| Prompt pins at approval and the run-time refusal of an unqualified pin | exists | [R `service.py:261-283`; `screen.py:257-275`] |
| Manifest split, package format, import with a coordinating-centre key register, weekly counts, coordinating mode | missing: plan 10 cards 10D-2, 10D-3, 10D-4, 10D-10, 10D-13 | [R plan 10 Track D] |
| A head-box profile for a 48 GB card | missing: the card falls to `default` | [R `gpu_profile.sh:38`; `install.sh:216,592,600-604`] |
| A site-box mode that hides protocol reading and says why | missing (10E-1, 10E-17) | [R plan 10] |
| Verifier prompt pin, note test cases, weight-hash check at import, minimum release | missing (cards 19-6, 19-7) | section 2.3 |

**Interim path** [O]: until 10D-3 and 10D-4 exist, the head box's approved rule set can travel inside a vendor-signed
update bundle, which the install already verifies and loads. It works with today's code only if an update bundle may
carry a rule set alone (not verified: `tools/apply_update.sh` was not read for this), and it signs with the vendor's key,
not the coordinating investigator's: acceptable for a dry run, not for the first real study (card 19-9).

### 2.5 The head box itself

**Memory on a 48 GB card** [O, from the stored measurement of section 1.3]: the judge's non-cache memory is about
18,920 MiB inside its budget plus about 3,170 MiB outside it; the verifier's about 9,000 plus 680. That is about
31,770 MiB before any cache. On 49,140 MiB (a 48 GB card's usual total; not verified for the owner's card) about
16 GiB remain: a judge cache of about 9 GiB (about 86k tokens: two full 32k sequences or about 25 p95 screening calls)
and a verifier cache of about 4 GiB, at utils near 0.57 and 0.27, with about 4 GB spare. **Both models resident at
32k fit**, so the head box reads protocols as the 96 GB card does, more slowly.

**Engine on an Ada or Ampere card.** The vLLM image covers compute capability 8.9 and 8.6 [R `deploy/images.lock:
56-64`], so the installer's host check passes [R `deploy/check_host.sh:51-57`]. NVFP4 is native only on Blackwell;
vLLM lists Marlin kernels for "GPTQ/AWQ/FP8/FP4" on Ampere and Ada [S 1]. So the judge runs on a weight-only FP4
path there: **different kernels and different rounding from the site's card**. This review did not verify that this
judge (a mixture-of-experts model) runs on that path in v0.32.0. The verifier's AWQ runs on Ada [S 1].

**Speed** [O]: the RTX 6000 Ada has 960 GB/s [S 3], about 0.54 of a 5090's 1,792 [R 13 §2]; a protocol's 52 s of
model time on the cloud card [R 13 §4] becomes roughly 1.5 to 2 minutes. Three to five protocols and their
amendments are minutes a month.

**Where it sits and whose key signs** is the owner's decision 1: plan 10's recommendation 48 says a coordinating node
runs "at the lead institution, never vendor-hosted" [R plan 10 decision 48]. If the head box stays in the owner's
office, the coordinating investigator's token signs there, and an industry protocol leaves the hospital only with the
sponsor's consent [O].

---

## 3. Fit on 32 GB, by arithmetic and from sources

### 3.1 The memory arithmetic, from the stored measurement

A real 5090 reports 32,607 MiB [R `docker-compose.rtx5090.yml:30`]. From `fit.json` [R; O for the derivation]:

| Quantity | Value | Derivation |
| --- | --- | --- |
| Judge, inside its budget, without cache | 18,920 MiB | util 0.30: 29,366 − 10.19 GiB cache = 18,931; util 0.27: 26,429 − 7.34 GiB = 18,913 |
| Judge, outside its budget | about 3,170 MiB | used 32,519 at util 0.30 (budget 29,366); 29,623 at 0.27 (budget 26,429) |
| Verifier, inside, without cache | 9,000 MiB | util 0.30: 29,366 − 19.88 GiB = 9,009; util 0.27: 26,429 − 17.02 GiB = 9,001 |
| Verifier, outside | about 680 MiB | 30,035 − 29,366; 27,113 − 26,429 |
| **The pair before any cache** | **about 31,770 MiB** | sum |
| Left on a 5090 for both caches | **about 840 MiB**, less the driver's own use | 32,607 − 31,770 |
| One 8k sequence | judge 0.86 GiB, verifier 0.35 GiB | 110 and 45 KiB a token [R 13 §3] |

The "capped" record of the same day agrees: budgets of 31,746 MiB showed 35,810 MiB in use [R
`serving_config_2026-11-08_tb-gpu-sim.json`]. The extra memory outside the judge's budget persisted with the
multimedia inputs switched off (`--limit-mm-per-prompt` was set in that record) [R same]. **The stand-in "cap" by
utilisation is soft**: it does not count about 3.8 GiB that a real card must hold. That is why section 4.1 uses a
ballast.

### 3.2 The options

Throughput is in judge calls a second for screening; "opinion — to be measured" unless marked. The rates of 13
(today 1.0, tuned 3.5 for the 32 GB card) are opinion (section 1.4).

| Option | Memory with cache at the concurrency needed | Throughput | Japanese evidence | Structured output | Risk |
| --- | --- | --- | --- | --- | --- |
| **(e) Today's swap, tuned** (judge awake 16 sequences; verifier woken once a run) | judge awake: budget 26,412 MiB, cache 7.34 GiB = 69,836 tokens [R fit.json]; 16 × p95 3,152 tokens = 50,400: fits with about 19k tokens spare [O] | today ~1.0; tuned ~3.5 (opinion — to be measured) | the same weights as the 96 GB card: MedTxt ja pair stated-absent blocked 10.9 %, present blocked 69.0 %; the judge at NVFP4 82.7 % present vs 90.3 % at full precision [R 17 §2.4, §4.2] | vLLM `json_schema`, backend `auto` [R `deploy/images.lock:83-86`; `libs/tb_llm/client.py:152-153`] | 8k context with Japanese notes unmeasured; chat busy during the verifier pass; the swap path never run in a product run |
| (a) One model only; the verifier's role done by rules and a second pass of the same model | judge alone, as (e) | ~3.5 ÷ (1 + share sent to a second pass), about 2.7 at a share of 0.3 [O] | none for a same-model second pass | as (e) | **under D-89 a note cannot exclude**: the code refuses a pair that is one model (`same_model`) and `TB_SCREEN_JUDGE=single` sends note "fail" to review [R `canary_gate.py:289-302`; `screen.py:240-242`; `evaluate.py:692-700`]. It is "never exclude on notes", a policy change, not a layout |
| (b) Judge and verifier side by side, smaller | today's pair: about 840 MiB for both caches (3.1): **does not fit**. With a ~5 GB Apache-2.0 verifier (only the judge's own family's small sizes are listed as Apache in 17 [R 17 §4.2], which weakens independence): about 3 GiB of cache (opinion — to be measured) | ~2 (opinion — to be measured) | none for any small verifier in the repository's Japanese runs | as (e) | a new verifier is a model change (full protocol [R 13 §5.4]); thin headroom on a card with no ECC |
| (c) Judge on the GPU, verifier on the CPU | GPU as (e), never swapped; the CPU holds the verifier in host memory | GPU ~3.5; verifier on a 16-core desktop CPU ~0.05 to 0.1 calls a second, on a 1-socket server ~0.2 [R 13 §3.1, opinion] | none; a CPU engine and quantisation change the verifier's numerics | vLLM CPU: not verified for structured output or for this hybrid verifier [R 13 §15]; llama.cpp: JSON schema [R 13 §3.1] | **fails the first load** (7 to 28 nights on a desktop CPU, section 3.4); fine for deltas |
| (d) A single newer Apache-2.0 or MIT model as both | Qwen3.6-35B-A3B ~20 GB 4-bit; Qwen3.8-27B ~16 GB dense (no official 4-bit); Gemma 4 31B ~17 GB dense [R 17 §5.1]: each fits with cache alone | MoE ~as (e); a dense 27 to 31B model reads ~15 to 17 GB a token, about 7 times the judge: ~0.4 (opinion) | none in the repository; stage H would measure [R 17 §7.2] | as (e); thinking must be off (10E-25) | as (a): one model cannot exclude under D-89; a model change |
| (f) Not a layout: the same profile on the 32 GB **RTX PRO 4500 Blackwell** | identical to (e): 32 GB, so the same arithmetic | about half of (e) for decode: 896 GB/s [S 4] against 1,792 | as (e) (same weights, same Blackwell FP4 path) | as (e) | already mapped to the `rtx5090` profile but the measurement rule refuses its name (section 5.1) |

**Licence screen** (the owner: Apache-2.0 or MIT only): the judge's family and the verifier's family are Apache-2.0
[R `docs/licences/register.csv:30-31`]; the 5 GB Japanese verifier named in 17 (NVIDIA Nemotron Open Model License)
and the "community" licence builds are out [R 17 §4.3]; Qwen3.6, Qwen3.8-27B, Gemma 4 sizes, LLM-jp-4.1 are Apache-2.0
[R 17 §4.3]; LLM-jp-4.1 is thinking-only and is refused as judge or verifier unless measured (10E-25).

### 3.3 Reading the options

[O] Only (e) keeps both the measured weights and the rule that two different models must agree before a note excludes.
(b) is out with today's verifier by the stored numbers, and in with a smaller one only after a model change. (c)
carries the deltas but not the first load. (a) and (d) are a policy change (notes never exclude), not a cheaper
layout. **Ship (e), tuned; measure (b) once on the stand-in (free) only to close the question; keep (c) for a later
"chat while the night runs" improvement.**

### 3.4 The night for the first site

Formula of 13 §4: model hours = patients in scope × share screened × studies × calls per patient and study ÷ calls a
second ÷ 3,600. Patients in scope 100 a bed (the site's own count replaces it, 13 §13); delta 3 %; calls per patient
and study 0.065 / 0.22 / 0.5 (light, typical, heavy) [R 13 §4]; the share of judge calls that also go to the verifier
0.3 (SIGIR 0.14, TCGA 0.95 [R 13 §3.2]: opinion). Window 5.6 h. [M 1]

| Beds, studies, load | Calls (first load) | (e) today | (e) tuned | (a) | (b) | (c) desktop CPU | (c) server CPU | (d) dense | (f) PRO 4500 tuned |
| --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- |
| 500, 3, typical: delta | 990 | 0.3 h | 0.1 h | 0.1 h | 0.1 h | 1.0 h | 0.4 h | 0.7 h | 0.1 h |
| 500, 3, typical: first load | 33,000 | 9.2 h (1.6 n) | 2.6 h (0.5 n) | 3.4 h | 4.6 h | 34 h (6.1 n) | 14 h (2.5 n) | 24 h (4.3 n) | 4.8 h (0.9 n) |
| 600, 5, typical: delta | 1,980 | 0.6 h | 0.2 h | 0.2 h | 0.3 h | 2.1 h | 0.8 h | 1.4 h | 0.3 h |
| 600, 5, typical: first load | 66,000 | 18.3 h (3.3 n) | 5.2 h (0.9 n) | 6.8 h (1.2 n) | 9.2 h (1.6 n) | 69 h (12.3 n) | 28 h (4.9 n) | 48 h (8.5 n) | 9.6 h (1.7 n) |
| 600, 5, heavy: delta | 4,500 | 1.2 h | 0.4 h | 0.5 h | 0.6 h | 4.7 h | 1.9 h | 3.3 h | 0.7 h |
| 600, 5, heavy: first load | 150,000 | 41.7 h (7.4 n) | 11.9 h (2.1 n) | 15.5 h (2.8 n) | 20.8 h (3.7 n) | 156 h (27.9 n) | 63 h (11.2 n) | 108 h (19.3 n) | 21.9 h (3.9 n) |

"n" = nights of 5.6 h. Rates as in 3.2: (e) 1.0 / 3.5; (a) 2.7; (b) 2.0; (c) GPU 3.5 with the CPU verifier at 0.08
or 0.2; (d) 0.38; (f) 1.9. All opinion except the formula.

**Reading** [O]: every option except (c) and (d) carries the delta night in under 1.5 h even at heavy load. The first
load, the day-one experience, is 1 to 4 nights today and under 1 to 2 tuned, because the site runs 3 to 5 studies, not
15. A protocol imported at 10:00 gives the coded list at once and its notes that night (13 §7.4).

---

## 4. What must be measured, where, and what it costs

### 4.1 On the owner's card: the stand-in, said honestly

**What the stand-in can show** [O]: whether the profile's memory layout fits 32 GB with headroom (with a ballast, a
hard fit); whether the swap, the two-phase rounds, the wake check and the console's "busy" path work end to end; the
pipeline's Japanese call sizes. **What it cannot show:** a 5090's speed (the 48 GB Ada card has 960 GB/s [S 3]
against 1,792; its speed is closer to the RTX PRO 4500's 896 GB/s [S 4] than to a 5090's); a 5090's arithmetic
(the judge's NVFP4 runs through a different kernel path off Blackwell [S 1]); heat, power and noise of a 575 W card.
If the owner's card is a 96 GB RTX PRO 6000 instead, the stand-in is the same architecture as a 5090 (Blackwell, the
same native FP4 path), so its arithmetic is a 5090's; only bandwidth (1,792 on the Workstation Edition) and memory
size differ, and the ballast covers the size.

**The ballast** [O, to be verified on the card]: before the model servers start, a container from the same vLLM image
holds the card's memory down to a 5090's, so vLLM sees what a 5090 would show:

```
TOTAL=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits)   # MiB
BALLAST=$(( (TOTAL - 32607) * 1048576 ))
docker run -d --rm --gpus all --name tb-ballast --entrypoint python3 "$VLLM_IMAGE" -c \
  "import torch,time; t=torch.empty($BALLAST,dtype=torch.uint8,device='cuda'); time.sleep(10**9)"
```

The ballast's own CUDA context (a few hundred MiB) makes the stand-in slightly stricter than a real card, which is the
safe side. vLLM's utilisation is a share of the card's total, so the 5090 profile's 0.81 becomes 26,412 MiB ÷ TOTAL
(0.537 on 49,140 MiB): set `JUDGE_GPU_MEM_UTIL` and `VERIFIER_GPU_MEM_UTIL` to that in `deploy/.env`. The record says
`--capped-to "RTX 5090 (32 GB), by ballast"`, which the measurement rule refuses as a tier record, as it should [R
`tools/serving_config.py:325-326`].

**The runs** (from `trialbox/`; each on a rehearsal box, public or synthetic data only):

| # | What | Command (as far as the harness allows) | Hours | Yields |
| --- | --- | --- | --- | --- |
| O-0 | The card and machine | `nvidia-smi --query-gpu=name,memory.total,compute_cap,driver_version,ecc.mode.current --format=csv`; `nproc`; `free -g` | 0.1 | which case of 4.1 applies |
| O-1 | Fit under ballast | the ballast; `TB_COMPOSE_OVERRIDE= deploy/install.sh <bundle> --gpu rtx5090 --rehearsal` [R `deploy/install.sh:238-268`; `tools/tiers.py:82-91`]; then `python3 tools/serving_config.py capture --container judge=trialbox-llm-service-1 --container verifier=trialbox-llm-verifier-1 --models-dir deploy/models --capped-to "RTX 5090 (32 GB), by ballast" --out <file>` | 1 | memory per state at 4 and 16 judge sequences; free memory at peak; start-up minutes |
| O-2 | Swap and screening path | `python3 -m tools.trialbox selftest`; then a tcga:500 and a jmed run on the box at `JUDGE_MAX_SEQS` 4, 8, 16. The accuracy driver is the cloud one (`deploy/gcp/box-run.sh --mode validation --steps acc`); a local driver for the owner's machine is not in the repository (card 19-15) | 3 | calls a second (Ada speed: a lower bound), swap counts, wake-check results, list identical across settings |
| O-3 | Option (b), once | `TB_MODEL_SWAP=off`, judge util and verifier util split under the ballast (e.g. 0.42 / 0.20 of 49,140), 8k, 2 to 4 sequences | 0.5 | starts or not; cache per model; closes 13's B-2 |
| O-4 | Qualification at the profile | `python -m tools.trialbox eval qualify --profile rtx5090 --gateway-url http://127.0.0.1:8010/v1 --model-dir judge=<weights> --model-dir verifier=<weights> --server-log <log> --operator <name>` [R `tools/qualify.py:1-30,124`] | 2 | canary after wake, schema, longest prompt at 8k, determinism at 16 sequences |
| O-5 | Japanese | `python -m tools.medtxt_eval run --models <served names> --base-url <the box's model endpoint>` then `score` [R `tools/medtxt_eval.py:20-23,296-299`]; the synthetic ja accuracy set (`tools.accuracy_set`) [R 17 §7.1] | 1.5 | MedTxt ja pair figures on this path, against 10.9 % and 69.0 % [R 17 §2.4] |
| O-6 | Japanese call sizes at 8k | the synthetic Japanese hospital's charts through SCREEN; the gateway's per-call tokens and `left_out` counts, at 8k and at 32k (head-box profile) | 1 | the share of Japanese calls the 8k context truncates |
| O-7 | Degraded local compile | the judge alone, `--max-model-len 16384` and 32768, 2 sequences, under the ballast; compile the 104 SIGIR protocols (13's B-4, 17-12) | 1.5 | whether the site box can compile by day when the head box is away |
| O-8 | The head-box profile | without ballast: both resident at 32k (section 2.5's utils); compile the 104 SIGIR protocols | 1.5 | protocol minutes on the head box; its fit |
| O-9 | Option (c), optional | the verifier on the owner's host CPU (vLLM CPU image, AWQ), 4 slots | 1 | CPU verifier calls a second on a workstation CPU |

**Total about 13 hours of the owner's machine, free.** Data: the stored public sets (SIGIR, TCGA-Reports, JMED,
MedTxt: CC BY 4.0 and NCBI terms [R P2b `README.md`]) and synthetic charts only.

### 4.2 A real 5090, rented by the hour, for the one confirming run

Public offers opened 2026-11-18:

| Offer | Price | Docker and Compose? | Mark |
| --- | --- | --- | --- |
| RunPod, Secure Cloud pod | US$1.39 an hour | no: "you cannot spin up your own Docker instance"; no Docker Compose on pods | [S 9; S 12] |
| RunPod, Community Cloud pod | US$0.69 an hour | as above; the host is a third party | [S 9] |
| CloudRift | US$0.65 an hour; a dedicated VM "with root access, your own kernel"; stock varies | root, so Docker can be installed (not stated on the page) | [S 10] |
| Vast.ai | "No current offers" for the 5090 | – | [S 13] |
| A median of US$0.72 across 15 providers (2026-10-24) | – | – | [S2 14], not opened at source |

No spot price exists for these offers; the cap is counted at their listed price [O]. **The box's harness needs Docker
and Compose** (the record is captured from `docker inspect` [R `tools/serving_config.py:36-38`]), so a VM is the right
form; on a container-only offer only the two model servers can run, started by a shell script in the pod with the
profile's flags, and the box (gateway, orchestrator) runs on the owner's machine pointed at them over an encrypted
tunnel (`TB_EP_SERVING_URL`, `TB_EP_VERIFIER_URL` [R `models/routing.yaml:34-48`]) — possible with public data, but its
record would not satisfy `capture` (card 19-3).

**The run R-1** (CloudRift VM or equivalent; public data only; a new vendor, decision 5):

| Step | What | Hours |
| --- | --- | --- |
| 1 | Docker, the NVIDIA container toolkit, the bundle and the weights (about 25 GB) onto the VM | 1.0 |
| 2 | `nvidia-smi -q -d ECC,POWER,TEMPERATURE,CLOCK` (records what the card reports for ECC and power limits) | 0.1 |
| 3 | O-1 without ballast, `--capped-to` left out: the first real-card record | 0.5 |
| 4 | O-4 qualification at 16 judge sequences | 2.0 |
| 5 | tcga:500 and jmed at 4 and 16 sequences; `nvidia-smi dmon -s pucm -d 5` beside it | 1.5 |
| 6 | O-5 MedTxt ja through the box | 0.5 |
| 7 | 500 sleep/wake cycles in a loop through the gateway (`/v1/serving/activate`, `/release`) | 0.4 |
| | **Total** | **about 6 h: US$3.9 at US$0.65; US$8.3 at US$1.39** |

A second session for a failed step: about 4 h more. **Ceiling about US$15** [O].

### 4.3 The record that counts: on the delivered machine, before it ships

The tier rule wants a record "taken on its own, uncapped card"; the site's own record wins over the vendor's [R
`tools/tiers.py:1-7,17-18`; `deploy/install.sh:570-590`]. The repository already describes the path: a rehearsal boot,
`capture`, empty the box, install with `--tier small` [R `tools/tiers.py:82-91`]. So the vendor-prepared machine (ruled
yes) produces the record that installs it, at no cost, during its preparation: the serving record, `qualify --profile
rtx5090`, V1's 50,000-patient night (plan 10 F8) on that card, and a 24-hour burn-in (18's SO-22). R-1 exists only to
decide **before** buying.

### 4.4 Cost against the cap

| Run | Spot (US$) | Replaces in plan 10 §7 |
| --- | ---: | --- |
| O-0 to O-9 (owner's card) | 0 | B-1, B-2 (US$8), B-4 (US$2.7) |
| R-1 (and a retry) | 4 to 15 | B-3 (about US$6) |
| Delivered-machine runs | 0 | D-2 (US$4) is not needed for the first site (no 300 W card) |
| **First site, total** | **about 4 to 15** | plan 10's "required for the first site's tier": US$34 to US$45 |

G-1, G-2 and G-4 with V1 stay in plan 10 for tier D in general and for stage G of review 17, but they are no longer
the first site's [O]. On every reading of plan 10 §7 the cap holds with room.

### 4.5 Acceptance numbers: which option ships

Written before the runs. Each on R-1 unless marked.

| # | Measure | Ship (e) tuned if | Then |
| --- | --- | --- | --- |
| A1 | Memory at 16 judge sequences, p95-size calls | free card memory at peak ≥ 1,024 MiB (nvidia-smi); judge cache ≥ 50,400 tokens | else 8 sequences; if 8 fails, today's 4 |
| A2 | Swap | 500 cycles, 0 failed wakes, wake ≤ 1 s p95, wake check 6 of 6 every time | else the profile is not sold |
| A3 | Throughput (tcga:500) | ≥ 2.0 judge calls a second at the chosen sequences: the 600-bed, 5-study, typical first load ≤ 2 nights | 1.0 to 2.0: sell with the first-load nights printed; < 1.0: section 6.2 condition N1 |
| A4 | Determinism | the candidate list identical at 4 and 16 sequences (the superseded G-3 failed this [R `g3-2026-11-13/README.md:48`]) | else 4 sequences until fixed |
| A5 | Japanese, MedTxt ja pair (O-5) | within 2 points of the stored control on stated-absent blocked (10.9 %) and present blocked (69.0 %), upper bound of stated-absent ≤ 15 % (17 §7.3 rules 1 and 2) | else the card's path differs: investigate before sale |
| A6 | Context (O-6, stand-in) | Japanese calls truncated at 8k ≤ the 32k control + 2 points | else excerpt budget work (17-13) before the first site |
| A7 | Structured output | invalid JSON ≤ 1 % on the canary and schema step | else not sold |
| A8 | Option (b) (O-3) | only if it starts with ≥ 1 GiB free and ≥ 4 p95 judge sequences, **and** a model-change protocol passes | else (b) is closed |
| A9 | The bound of review 17 | not measurable before go-live; the site box must not be the reason a shadow-mode bound fails: A5 is its proxy | the shadow mode (17-4) measures it |

---

## 5. What changes in the product

### 5.1 Profile, installer and records

| Change | Today | Proposed | Card |
| --- | --- | --- | --- |
| Sequences | 4 [R `docker-compose.rtx5090.yml:105,132,178`] | 16 judge, 16 verifier, screen concurrency following, after A1 | 19-1 (= 10E-3) |
| The PRO 4500 | mapped to `rtx5090` [R `gpu_profile.sh:36`] but the rule wants "5090" in the name [R `serving_config.py:242,324`]: it can never be a tier | the rule names both cards; its record taken on its own card | 19-3 |
| The head box | `default`: base `llm-service` with an unregistered candidate, no verifier, `P-GB10` [R `docker-compose.yml:420-426`; `install.sh:592`] | a "coordinating workstation" profile for 48 GB cards (RTX 6000 Ada, RTX A6000, RTX PRO 5000): the pair resident at 32k, protocol roles, no patient route, its own label and record rule | 19-4 |
| Detection | by name only | the head-box profile matched by name and memory; the installer prints the box's role ("site box" or "coordinating box") | 19-4 |
| The tier record (10E-1) for the site box | – | roles on the box: patient and converse groups only; protocol route: "package from the coordinating box"; interactive note check: when no run holds the card; night plan; first-load nights from the measured rate | 19-8 |
| Capability page (18 SO-11) | – | rows: "Protocol reading — not on this box: arrives as a signed package"; "Note exclusion — two models agree (one at a time)"; "Chat during a screening run — busy until about HH:MM"; "Card memory error correction — not available on this card" | 19-16 |
| Power | no setting | a power limit applied at boot (a systemd unit; whether the 5090 accepts a given limit is not verified) after R-1 measures the loss | 19-13 |

### 5.2 Degraded modes on the site box

| Failure | What happens today | What the site sees (proposed) |
| --- | --- | --- |
| A model server down | the breaker opens after 5 failures; the judge's degraded mode is `deterministic_only` [R 13 §5.2; `routing.yaml:98-99`] | coded lists go on; "notes wait: model unavailable" |
| A wake fails its check | that model's answers become errors, so `unknown` [R `twophase.py:23-25`] | "notes not read tonight; the model failed its check" |
| The card fails | – | the prepared spare (decision 4); meanwhile coded screening on any machine restored from the backup (a no-GPU box screens coded criteria [R 13 §3.1]) |
| The head box away | – | imported studies screen as usual; new protocols and amendments wait (section 2.2) |
| A package from an unknown key | – (10D-4) | refused at import, audited |

### 5.3 The validation record for this tier (review 07)

[O, on 13 §5.4]: the 32 GB tier uses the same weights, prompts and engine as the 96 GB card, so its qualification is
the short one: `qualify --profile rtx5090` on the delivered card, the canary after a wake, the pair gate at 16
sequences, V1's night, MedTxt ja through the box. Differences that must be stated in the record: 8k context, one model
awake, two-phase rounds, no ECC. The head box needs no patient validation; its compiles are validated by the package's
tests at each site import.

### 5.4 Buying the machine for the site

| Part | Advice | Mark |
| --- | --- | --- |
| Card | GeForce RTX 5090, from an authorised Japanese distributor (warranty void for parallel imports [S2 8]); listed ¥1.0 to ¥1.29 million, all 12 shown out of stock at one shop; lowest in stock ¥1,239,000 (2026-11-18) | [S2 7; S2 15] |
| Same-tier alternative | RTX PRO 4500 Blackwell: 32 GB GDDR7 **with ECC**, 896 GB/s, 200 W, dual slot [S 4]; ¥843,590 (out of stock) to ¥1,150,979 (2026-11-18) | [S2 16] |
| Power supply | 1,000 W or more (NVIDIA's system figure for the 5090) [R 13 §2]; a 100 V / 15 A outlet carries 1,500 W, about 1,200 W continuous [O]: one outlet for the box alone | |
| Cooling and case | a 575 W card; a large case with front intake; the room's air-conditioning sized for about 0.8 kW of heat [O] | |
| Host | 8 to 16 cores; **128 GB RAM** (the profile wants 64 GB or more; the services' caps sum to about 45 GiB and each sleeping model holds its weights in host memory) [R `docker-compose.rtx5090.yml:20,97,127`; 13 §3.1]; two NVMe drives; TPM 2.0 | |
| UPS | about 1,500 VA, so the box shuts down cleanly [O] | |
| Noise | gaming-class fans under load: a closed room, not a ward office [O]; the dB of any card is not on the makers' pages [R 13 §15] | |
| Whole machine (built) | 5090 towers on 2026-11-10: ¥1,498,000 to ¥2,134,000; most sold out; one in stock at ¥1,777,380 with 1-year warranty (3 years for 10 % more) | [S2 11] |
| Warranty | board makers in Japan: 1 to 3 years by brand; exclusions for parallel imports, used cards, overclocking, mining; nothing found on 24-hour or business use | [S2 8] |
| Workstation makers | whether the large workstation makers sell a 5090 workstation in Japan: not verified; in the United States HP and Lenovo showed none in stock on 2026-11-10 | [S2 11] |

**Self-built or a maker's machine** [O]: buy from a Japanese builder that states a 3-year warranty in writing for this
use and repairs in Japan; a self-built machine leaves the vendor as the only support for every part. Ask the warranty
question in writing before ordering (section 10, item 7).

### 5.5 Vendor-prepared delivery with a consumer card

[O] Everything of 18's prepared delivery applies, plus: the driver installed and held at the version the bundle needs
(R580 or newer [R `deploy/images.lock:83-86`]); the power limit set and recorded; the serving record captured on the
machine (4.3); a 24-hour burn-in at the planned load with temperature, clock and the kernel's GPU error (Xid) lines
logged, and zero errors as the pass mark; the card's serial number in the delivery record; the same preparation for
the spare.

---

## 6. Risks, said plainly

### 6.1 The risks

| Risk | What it means | Evidence | Mitigation |
| --- | --- | --- | --- |
| **Driver licence** | NVIDIA's Linux driver terms: GeForce software "is licensed for use only on GeForce or Titan hardware products you own" and "is not licensed for datacenter deployment"; "datacenter" is not defined | [S 5; S 6] (v. 2025-02-25) | ask counsel or NVIDIA Japan in writing whether a hospital's server room is one; place the box as a workstation; the PRO 4500 is not GeForce (decision 7) |
| No ECC on the card | a memory bit flip in weights or cache goes undetected | not on the 5090's maker page [R 13 §2]; the PRO 4500 and the RTX 6000 Ada list ECC [S 4; S 3] | the canary before each night (exists [R `docker-compose.rtx5090.yml:38-39`]) and after each wake; R-1 step 2 reads what the card reports |
| Warranty for 24-hour use | 1 to 3 years; no clause found either way on continuous or business use | [S2 8] | written confirmation from the seller; a builder's warranty |
| Availability | most cards and built machines sold out; prices rose up to ¥350,000 in a month; a production-end rumour denied by NVIDIA per the press | [S2 11; S2 15] | buy card and spare together; the PRO 4500 as the same-tier fallback |
| Single point of failure | one card, one machine | – | the prepared spare (ruled yes); coded screening on any machine meanwhile (5.2) |
| Power and heat | 575 W card in a 100 V office | [R 13 §2] | a dedicated outlet, a UPS, a power limit if R-1 shows little loss |
| Driver channel | the consumer and workstation cards share one Linux driver package; the box holds a version | [O; R `deploy/images.lock:83-86`] | the driver held and updated only in a signed bundle (as the Spark profile does [R 13 §3.3]) |
| 4-bit only | the 8-bit judge that recovers 7.6 points of Japanese present findings does not fit 32 GB | [R 17 §4.2, §5.2] | rules first (11's JP-11); if the release bound needs the 8-bit judge, condition N5 |
| Different arithmetic at head and site | the head box computes FP4 on another kernel path (Ada) | [S 1] | the package's tests run again at the site's import; only the site's run counts |

### 6.2 When to tell the owner "not this card after all"

Each is a measured condition, not a feeling.

| # | Condition | Measured by |
| --- | --- | --- |
| N1 | On R-1, the tuned layout does not hold 8 judge sequences of p95 calls with ≥ 1 GiB free, or the rate at the best setting is < 1.0 judge call a second (the first load at 600 beds, 5 studies, typical would pass 3 nights) | A1, A3 |
| N2 | Any failed wake in 500 cycles, or the wake check fails once | A2 |
| N3 | MedTxt ja pair on the 5090 worse than the stored control by more than 2 points on either measure (A5) | O-5 on R-1 |
| N4 | Japanese calls truncated at 8k more than 2 points above 32k, and an excerpt fix (17-13) does not close it | O-6 |
| N5 | Release 1.0's bound (17 decision 1) is met on the 96 GB card only with the 8-bit judge | stage G (10E-23, 10E-26) |
| N6 | The 24-hour burn-in on the delivered card logs any GPU error (Xid) line, any canary miss, or sustained clock loss > 10 % at the set power limit | 5.5 |
| N7 | Counsel reads the driver terms as excluding the site's room, and the box cannot be placed as a workstation | decision 7 |
| N8 | No authorised seller offers the card with a written warranty of ≥ 2 years for continuous use | section 10, item 7 |

If N1 to N4 or N6 to N8 fire, the same profile moves to the **RTX PRO 4500** (32 GB, ECC, 200 W, a professional
driver) at about half the decode speed, which the night arithmetic still carries (first load 1.7 nights at 600 beds, 5
studies, typical) [O, section 3.4]. If N5 fires, the site needs a 48 GB or larger card.

---

## 7. Gap table

| What the product does today | What is needed | Evidence |
| --- | --- | --- |
| No measurement of the 32 GB profile beyond memory | stand-in runs O-1 to O-9 and one real-card run | [R fit.json; `docker-compose.rtx5090.yml:30-31`] |
| Stand-in caps by utilisation, missing about 3.8 GiB | a ballast | section 3.1 |
| No record for `rtx5090`; tier `small` cannot install | the delivered machine's record | [R `deploy/measured/README.md`; `tools/tiers.py:94-120`] |
| 4 sequences | 16 after A1 | [R `docker-compose.rtx5090.yml:105`] |
| PRO 4500 mapped but unmeasurable | the rule names it | [R `gpu_profile.sh:36`; `serving_config.py:242`] |
| A 48 GB head box falls to `default` | a coordinating-workstation profile | [R `gpu_profile.sh:38`; `docker-compose.yml:420-426`] |
| Only the judge prompt pinned | the verifier's pin too | [R `service.py:277-283`] |
| `models.judge` a stale free name | weight-manifest hashes in the package | [R `rulesets/RA-JAK/manifest.yaml:53-55`] |
| No note test cases | per note criterion, run at import | section 2.3 |
| Rule sets only through the vendor bundle | the package and its import (10D-3, 10D-4) | [R `install.sh:21,273`] |
| No Japanese judge-call sizes | O-6 | [R 13 §14 M 1] |
| No local driver for accuracy runs on the owner's machine | a local form of the box run | [R `deploy/gcp/box-run.sh:1-6`] |
| Capture needs Docker | a note in the run book; VM offers only | [R `serving_config.py:36-38`] |
| No power limit, no burn-in record | both in the preparation | 5.5 |

---

## 8. Cards for plan 10

| Card | What | Size | Lane (guess) | Waits for | Proof |
| --- | --- | --- | --- | --- | --- |
| 19-1 | The 32 GB profile tuned: 16 judge and 16 verifier sequences, screen concurrency following; the swap kept (takes 10E-3) | S | D | A1 (O-1, R-1) | the real-card record at 16; A1 to A4 met |
| 19-2 | The ballast stand-in: a script that holds a larger card at a 5090's free memory and sets the utilisations; the record says "by ballast" | S | D, Int | – | on a 48 GB card, free memory before the servers start is 32,607 MiB ± 512 |
| 19-3 | The measurement rule names the RTX PRO 4500 beside the 5090; a run-book note that `capture` needs Docker | S | D | – | a record with a PRO 4500 name passes `measured rtx5090`; a capped one still fails |
| 19-4 | The coordinating-workstation profile for 48 GB cards: pair resident at 32k (utils from O-8), protocol and documents roles only, no patient route, its own label and record rule, detection by name and memory | M | D, A2 | O-8; decision 1 | install on the owner's card gives this profile; a patient call is refused on it |
| 19-5 | Coordinating mode on the head box (as 10D-13, no change; listed so the head box is its first user) | – | C2b | 10D-13 | 10D-13's test |
| 19-6 | Package items for screen-only sites: the verifier's prompt pin; the ja note questions; value-set release ids; weight-manifest hashes; minimum release | M | A2 | 10D-2, 10D-3 | a package tested with other weights or an older release is refused at import |
| 19-7 | Note test cases in the package, run on the site's pair at import; the result in the import report and the counts file | M | A2, G | 19-6 | a planted wrong expected answer blocks approval |
| 19-8 | The site box's tier record and wording: no protocol reading, "sent to the coordinating box", first-load nights, busy times | M | C2, A2 | 10E-1 | a home-page and study-page text test on the 32 GB profile |
| 19-9 | Interim: a rule set in a vendor-signed update bundle, for the dry run only | S | D | – | the steps box screens a rule set compiled on another box (and the bundle's scope checked in `tools/apply_update.sh`) |
| 19-10 | Degraded local compile on the site box: the judge alone at 16k by day; the result unsigned, single-site, marked | M | A2, D | O-7 | 104 SIGIR protocols compile with no part given up; a local rule set is never merged into multi-site counts |
| 19-11 | Preparation of a 32 GB box: rehearsal boot, record, `qualify`, V1's night, 24-hour burn-in, Xid and clock log, power limit, serial in the delivery record (with SO-22) | M | D, G | SO-22; decision 2 | one prepared box's record; IQ repeated on site gives the same |
| 19-12 | Health without ECC: the nightly canary result, Xid lines and clock loss shown in `doctor` and the capability page | S | D, C2 | SO-11 | a planted Xid line turns the row red |
| 19-13 | Power limit at boot, from R-1's measured loss | S | D | R-1 | the limit applied after a reboot; the rate within 10 % of uncapped |
| 19-14 | R-1: the real-card run (replaces B-3) | S | Int | decision 5 | the first `rtx5090` record and A1 to A7 |
| 19-15 | O-0 to O-9 on the owner's card, with a local form of the accuracy driver | M | Int, owner, G | 19-2 | the stand-in records filed with "by ballast" |
| 19-16 | Capability rows for the site box and the head box (18's SO-11) | S | C2 | SO-11, 19-8 | a fixture of each box shows its rows |
| 19-17 | The counts file carries the import test result, the box's release and profile | S | A2 | 10D-10 | the merge shows each site's profile |
| 19-18 | Plan 10's text corrected: the 1.43 figure, the side-by-side arithmetic, the 15-study first load, decisions 32 and 79 as ruled | S | Int | – | plan text |
| 19-19 | Japanese judge-call sizes at 8k and 32k on synthetic Japanese charts (O-6) | S | G, A2 | synthetic ja charts (17-5's first ones) | the share truncated per context, filed |
| 19-20 | The spare for a 32 GB site: the same preparation, the site file restore (18's SO-14) timed | M | D | 19-11, SO-14 | the spare restored equals the original by `doctor` and counts |
| 19-21 | The sales sheet: tier B restored in Japan as "the site box of a coordinated group" (amends 10E-18) | S | owner, G | R-1 | the sheet cites the record |
| 19-22 | The driver-terms question to counsel or NVIDIA Japan; the answer in the licence register | S | Int, owner | decision 7 | a register row with the answer |

Counts: S 13 (19-1, 19-2, 19-3, 19-9, 19-12, 19-13, 19-14, 19-16, 19-17, 19-18, 19-19, 19-21, 19-22), M 8 (19-4,
19-6, 19-7, 19-8, 19-10, 19-11, 19-15, 19-20), L 0; 19-5 is a pointer to 10D-13.

**What waits for what:** 19-2 → O-runs (19-15) → 19-1, 19-4, 19-10. Decision 5 → R-1 (19-14) → 19-13, 19-21.
10D-2, 10D-3 → 19-6 → 19-7, 19-17. 10E-1 → 19-8 → 19-16. SO-22 → 19-11 → 19-20.

---

## 9. Decisions only the owner can make

| # | Decision | Recommendation |
| --- | --- | --- |
| 1 | **Where the head box sits and whose key signs.** Plan 10's recommendation 48: the coordinating node at the lead institution, never vendor-hosted | The head box may stay with you as the compile station; the package is signed with the coordinating investigator's token; an industry protocol goes to it only with the sponsor's consent |
| 2 | **The layout on the 32 GB card** | (e), today's swap tuned to 16 sequences, if A1 to A7 pass; no single-model exclusion |
| 3 | **5090 or RTX PRO 4500** for the same profile | 5090 as you ruled; the PRO 4500 automatically if N1 to N4 or N6 to N8 fire. It is the same price or less in Japan today and has ECC and a professional driver |
| 4 | **The spare** (ruled yes): a second prepared machine, or a second card on the shelf | A second prepared machine if the budget allows (a card swap still needs a person on site); otherwise a spare card and coded screening on any machine meanwhile |
| 5 | **A new vendor for one rented run** (a VM with a real 5090, public data only, about US$4 to US$15) | Yes, a VM offer (Docker possible), before the purchase order |
| 6 | **The rule D-89 on the site box** (two models must agree before a note excludes) | Keep it; options (a) and (d) are not cheaper layouts but a change to it |
| 7 | **The driver terms** ("not licensed for datacenter deployment") | Ask counsel or NVIDIA Japan in writing before the order; meanwhile plan the box as a workstation in a closed office |
| 8 | **A power limit on the 5090** | Yes, if R-1 shows under 10 % loss at the chosen limit |
| 9 | **Tier B in Japan** (plan 10 decision 79 recommended dropping it) | Restore it as "the site box of a coordinated group", never as a standalone box that reads protocols |

---

## 10. What the owner must supply

1. **The card and the machine**: the output of `nvidia-smi --query-gpu=name,memory.total,compute_cap,driver_version,
   ecc.mode.current --format=csv`; the machine's maker and model, CPU, RAM, power supply, operating system, Docker
   version; whether a display runs on the card (it takes memory).
2. **Hours**: about 13 hours of the machine for O-0 to O-9, in pieces is fine; whether the integrator may run them
   remotely (the access design of plan 10's T-630 row) or you run them from a written sheet.
3. **Where the head box will sit**, and who holds the signing tokens (decision 1).
4. **The first site's 3 to 5 studies**: registry numbers (jRCT or ClinicalTrials.gov), for the package dry run and the
   calls-per-patient split.
5. **The site's counts** as review 13 §13 lists them (patients seen per year, new patients a day, share with notes).
6. **The room**: server room or office, outlet (100 V / 15 A, shared or not), air-conditioning, noise rules, UPS.
7. **The seller's written warranty** for continuous use of the card and the machine, and the delivery date.
8. **Whether the hospital's procurement or IT rules forbid consumer graphics cards** in a clinical system.

---

## 11. Measurement log

Scripts in `/var/tmp/trialbox-0/b21/` (not committed); run with `python3 -I` on the shared machine.

| # | Command | Result |
| --- | --- | --- |
| 1 | `night.py`: the formula of 13 §4 for 500 and 600 beds, 3 and 5 studies, three loads, delta and first load, over the option rates of section 3.2 | the table of section 3.4 |
| 2 | a read of `fit.json` and `serving_config_2026-11-08_tb-gpu-sim.json` (`json.load`, the fields of section 3.1) | judge awake 29,623 MiB; caches 10.19, 7.34, 19.88, 17.02 GiB; capped pair 35,810 MiB at 0.22 + 0.105 with the multimedia limits set |
| 3 | `git show origin/integrator/p2b-artefacts:trialbox/.p2b-artefacts/summary.json` | weight manifests and served prompts with versions and sha256 are in each run's provenance |

---

## 12. Sources (opened 2026-11-18 unless marked)

| # | What | Link | Terms |
| --- | --- | --- | --- |
| S 1 | vLLM, quantisation: supported hardware ("Marlin (GPTQ/AWQ/FP8/FP4)" on Ampere and Ada; no Blackwell column) | https://docs.vllm.ai/en/latest/features/quantization/ | Apache-2.0 docs |
| S 2 | NVIDIA RTX 6000 Ada Generation product page (48 GB GDDR6, ECC, 300 W) | https://www.nvidia.com/en-us/products/workstations/rtx-6000/ | maker's page |
| S 3 | NVIDIA RTX 6000 Ada datasheet, PNY copy (960 GB/s, 384-bit, ECC yes, 300 W, no NVLink, MIG not listed) | https://www.pny.com/en-eu/File%20Library/Professional/DATASHEET/WORKSTATION/PNY-Proviz-Nvidia-RTX6000ADA-datasheet_v1.0A.pdf | maker's datasheet via a partner |
| S 4 | NVIDIA RTX PRO 4500 Blackwell (32 GB GDDR7 with ECC, 896 GB/s, 200 W); RTX PRO 5000 (48 or 72 GB, 1,344 GB/s, 300 W, MIG up to 2) | https://www.nvidia.com/en-us/products/workstations/professional-desktop-gpus/rtx-pro-4500/ ; …/rtx-pro-5000/ | maker's pages |
| S 5 | NVIDIA Driver License Agreement, Linux, §2.8 and §2.7 (v. 2025-02-25) | https://www.nvidia.com/en-us/drivers/nvidia-license/linux/ | the licence itself |
| S 6 | NVIDIA GeForce software licence, §2.8 (v. 2025-02-25) | https://www.nvidia.com/en-us/drivers/geforce-license/ | the licence itself |
| S2 7 | gazlog GPU daily price chart (5090 lowest in stock ¥1,239,000, Tsukumo, 2026-11-18) | https://gazlog.jp/entry/gpu-daily-charts/ | press |
| S2 8 | gazlog, GPU warranty list in Japan (updated 2026-05-27) | https://gazlog.jp/entry/gpu-warranty-list-2025/ | press |
| S 9 | RunPod pricing (5090 US$0.69 community, US$1.39 secure; RTX 6000 Ada US$0.74 / 1.09) | https://www.runpod.io/pricing | vendor's page |
| S 10 | CloudRift GPU rentals (5090 US$0.65; dedicated VM with root) | https://www.cloudrift.ai/gpu-rentals | vendor's page |
| S2 11 | gaming-st.com, 5090 built PCs in Japan (checked 2026-11-10) | https://gaming-st.com/gpu/rtx5090-bto-prebuilt-shortage-japan-2026-11/ | press |
| S 12 | RunPod docs, pods overview (no Docker, no Compose on pods) | https://docs.runpod.io/pods/overview | vendor's docs |
| S 13 | Vast.ai, RTX 5090 pricing page ("No current offers") | https://vast.ai/pricing/gpu/RTX-5090 | vendor's page |
| S2 14 | getdeploying.com, 5090 median price (2026-10-24), seen in a search result only | https://getdeploying.com/gpus/nvidia-rtx-5090 | not opened |
| S2 15 | Dospara, 5090 cards (12 shown, all out of stock, ¥1,017,800 to ¥1,288,000; one listing at ¥349,800 taken as an error) | https://www.dospara.co.jp/BR31/geforce-rtx5090.html | shop |
| S2 16 | gpuprix, RTX PRO 4500 and RTX PRO 5000 in Japan (updated 2026-11-18; PRO 5000 48 GB ¥1,488,480 and ¥2,443,959) | https://gpuprix.com/ja/japan/gpus/rtx-pro-4500-blackwell?show=listings | aggregator |

---

## 13. Where this review differs from earlier ones

| Earlier | Here | Basis |
| --- | --- | --- |
| 13 decision 5, 17 decision 8, plan 10 decisions 32 and 79: no 5090 for the first site; drop tier B in Japan | the owner overruled; the 5090 is the site box of a two-box design | owner, 2026-11-18 |
| 13 §3.2: 1.43 calls a second on the stand-in | measured on the uncapped card | section 1.4 |
| 13 §3.2, 17 §5.2: side by side leaves 4 to 5 GiB | under 1 GiB with today's builds | section 3.1 |
| 13 §9, 17 §6: first load 3 to 10 nights | 1 to 4 today, under 1 to 2 tuned, at 3 to 5 studies | section 3.4 |
| 13 B-1, B-2, B-4 on a paid cloud stand-in | free on the owner's card with a ballast | section 4.1 |
| 14: the package for partner hospitals | the same package is how the first site gets every protocol | section 2 |

---

## 14. What this document did not verify

- **The owner's card.** "48 GB-class" is the coordinator's reading; the model, its memory total (49,140 MiB assumed)
  and the machine are not confirmed (section 10, item 1).
- **Every throughput figure for a 32 GB card**, including today's 1.0 and the tuned 3.5 of review 13 and all of
  section 3.2: opinion until R-1.
- **That the judge's NVFP4 build runs on Ada or Ampere** through vLLM's Marlin path in v0.32.0; the vLLM table names FP4
  for Marlin in general, not this model.
- **The ballast method**: that vLLM v0.32.0 starts with a utilisation computed on the card's total while another
  process holds memory; to be checked in O-1.
- **The judge's ~3.1 GiB outside its budget** on a real 5090 and with the shipped flags: inferred from two stored runs on
  the cloud card.
- **The 5090's ECC and power-limit range**: not on the maker's page; R-1 step 2 reads them.
- **Whether "datacenter deployment" covers a hospital's server room**: the terms do not define it.
- **Warranty terms for continuous use**: no maker's clause found either way; only a press summary was opened.
- **Whether large workstation makers sell a 5090 workstation in Japan**, and whole-machine prices beyond one press page.
- **Whether a CloudRift VM allows Docker and the NVIDIA container toolkit**; the page says root and own kernel only.
- **Whether `tools/apply_update.sh` accepts a bundle carrying a rule set alone** (card 19-9).
- **Whether a study can be paused by its PI** while an amendment waits.
- **Japanese token counts per call**: no stored Japanese call exists.
- **vLLM CPU support for the hybrid verifier and for structured output** (option (c)).
- **The availability of small Apache-2.0 or MIT verifiers** of another family than the judge, for option (b).
- **The RTX PRO 4500's and 5000's street availability in Japan** beyond one aggregator's listings, most out of stock.
