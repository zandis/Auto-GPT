# The first real-model accuracy run on a VALIDATION box (lane G, 2026-11-15)

Branch `claude/lane-g-box-accuracy` (not pushed; head `633067ce`). It holds train 17 (head `5c515685`), the validation reset and
public accuracy tools (#621, #628), lane G's box-run commits (#614, without batch 6), and the new validation mode and
accuracy group. Nothing was started or paid for.

## 1. The run in one table

| Item | Value |
| --- | --- |
| What | Run A of the public accuracy plan, on the shipped box installed from a bundle, in VALIDATION mode, with the real model pair. Eight public sets: JMED-Personas 300, TCGA 500, SIGIR physician labels (105 pairs, 1,015 criteria), TREC 2023 500 pairs, TREC 2021+2022 1,225 pairs, Taiwan FDA 100 trials (compile only), jRCT 50 (compile only), Chia 100 (compile only). 1,615 protocols. |
| Can it run today? | **No.** Two product rules on train 17 stop a VALIDATION box from routing the run's model calls (section 4). The driver checks this for free and refuses to launch until it passes. |
| Launch (two launches) | 1. Build: `deploy/gcp/box-run.sh --mode validation --steps build --release-id val-<commit12> --release-seq 1 --commit <sha> --no-wait`  2. Start and run: `deploy/gcp/box-run.sh --mode validation --steps start,acc --release-id val-<commit12> --no-wait`, then `deploy/gcp/box-run.sh --collect <run id> --follow` |
| Time, run (start + acc) | **3.3 h low, 18.5 h high** for the parts with a figure; the install and some steps have no measurement (bounded by the cap) |
| US$ at spot US$2.74/h | **US$9.01 low, US$50.80 high** for the run; cap 28 h = US$76.72 |
| Build launch | 0.65 h known (US$1.79); cap 2 h = US$5.48 |
| Both launches at their caps | 30 h = **US$82.20** spot |
| Signing | A throwaway key made on the build VM. Not the vendor key. **The bundle is not a release**; every result says so. |
| Free checks first | `deploy/gcp/box-run.sh --estimate --mode validation --steps start,acc`; `python -m tools.box_run validation-check`; `tests/rehearsal/box-run/rehearse-box-run.sh` (19 cases, US$0) |

How the time is derived: the plan's own rule (`tools/public_accuracy/plan.py`): compile calls one at a time at 0.403
calls a second, screen calls at 4.502 a second with 16 in flight, 4.1 s of box time a protocol, plus the VM start
(0.25 h) and the measured model loads (199 s) and canary (124 s). The low bound is one compile call a protocol and no
screen call; the high bound is a compile call per line and both models on every line of every pair. The rates are
lane G's measurements of 2026-11-13 on its own serving setup, which the validation reset marked superseded: an order
of magnitude only. The installed box's own rates are not known. Steps with no figure: fetching and installing the
bundle, the first install, pinning, qualify, promote, the data download and one ingest. The cap bounds them.

## 2. What must be true before launch

| # | Precondition | State | Who |
| --- | --- | --- | --- |
| 1 | A VALIDATION box routes the judge and verifier. Today it routes them only as "champion", and champion needs a qualification record that `qualify` cannot make on the box | **Not met** | Lane D (product) |
| 2 | A VALIDATION box can both compile protocols and screen notes. Today screening calls are class D3, VALIDATION allows up to D2, and one `TB_DATA_CLASS` setting serves the compiler and the screen alike | **Not met** | Lane D (product), lane A2 (classes) |
| 3 | The tripwire has a setting the run can turn off | **Not met** (no declared setting on train 17). The run still goes; each refusal is counted per protocol. | Integrator (asked) |
| 4 | Daily limits off for the run | **Met by site settings** the driver writes and records: `rate_limits_per_day` FEAS 0, SCREEN 0; `TB_MAIL_PER_RECIPIENT_PER_DAY=0` | Lane G (done) |
| 5 | #589 merged (SCREEN uses the embed service) | **Not met** on train 17. The run records which embedder SCREEN used. | Lane A2 |
| 6 | v5 prompts served | **Met in VALIDATION by design** (newest version served). The run records what was actually served. | - |
| 7 | The vLLM waiver (CVE-2026-128089), so the build's release gates pass in enforcing mode | **Not met** (CI run 43602503189) | Lane D, owner's yes |
| 8 | The bundle built from a pushed integration head that holds #589 and the fixes for 1 and 2 | **Not met** | Integrator |
| 9 | tb-gpu-sim has a vTPM (the installer seals the site keys under it on a VALIDATION box) | **Not known**. Free check: `gcloud compute instances describe tb-gpu-sim --zone asia-east1-a --format='value(shieldedInstanceConfig)'` | Lead |
| 10 | Disk on tb-gpu-sim for the bundle twice, images and the public data (about 95 MB kept) | **Not known** (R2 plan P9) | Lead |
| 11 | jRCT: 50 records fetched one by one is allowed for single records; bulk needs the helpdesk's permission | Owner's choice (drop jRCT with `--only` if not) | Owner |
| 12 | TREC (NIST) states no licence; internal validation with a risk note | Owner's choice | Owner |
| 13 | Owner's yes for the spend | Not asked yet | Owner |

## 3. What the result will and will not prove

It will prove, on the shipped box installed by the real installer, with the real model pair: how many eligible
patients are lost and how many wrong exclusions are made on real English notes against NIST and physician labels;
criterion-level answers with the deciding sentence (SIGIR); real pathology text (TCGA); the family-history trap in
Japanese (JMED, synthetic text); whether the compiler reads the same trial the same way in Chinese, Japanese and
English. Every result names the commit, bundle, image digests, weight manifests, chat template, the prompt versions
served, the embedder, and whether the tripwire and limits were on.

It will not prove: anything about real Taiwanese chart text (none is public); negation on clinical text (BioScope
blocked); production behaviour (it is a VALIDATION box with a bundle that is not a release); the installed box's
capacity. Protocols the tripwire refuses are counted, not scored. Until #589 lands, the semantic retrieval stage is
not measured.

## 4. The answer: can a VALIDATION box with the real pair be installed and run today?

**Installed: yes. Run the accuracy set: no.** File and line on the merged tree:

1. **A signature is always required, by any key the box trusts.** The installer stops without a public key at
   `deploy/keys/vendor_ed25519.pub` (`deploy/install.sh:99,192`) and verifies the bundle (`install.sh:233`,
   `tools/verify_update.py:239`). Nothing depends on the environment. So a throwaway key made on the runner, with its
   public half placed on the box, is accepted. A fresh box has no installed release, so release seq 1 is enough.
2. **VALIDATION is as strict as PRODUCTION on the bundle.** It refuses a bundle built from a dirty tree or with
   `--rehearsal` (`tools/trialbox/update.py:92`, D-633, D-726). So the bundle must come from a clean commit.
3. **`--rehearsal` gives a TEST box**, with stand-in models unless `TB_COMPOSE_OVERRIDE=` is set empty
   (`install.sh:220,323`). It is refused on a VALIDATION box. It is not VALIDATION.
4. **How a box becomes VALIDATION.** `install.sh` writes PRODUCTION only when `deploy/.env` names no `TB_ENV`
   (`install.sh:327`). The settings wizard copies any declared `TB_*` from the answers' `env_extra` into `.env`
   (`tools/settings_wizard.py:427,545`), and `TB_ENV` is declared (`libs/tb_common/config.py:562`; its help text
   omits VALIDATION). So `deploy/install.sh --answers` with `env_extra: {TB_ENV: VALIDATION}` makes a VALIDATION box.
   The box form (`deploy/box-install.sh` and the first-run page) cannot: its answers come from `tools/box/plan.py`,
   which never sets `TB_ENV` (`plan.py:484`). Wired: the driver uses `install.sh` with the committed synthetic site
   `deploy/gcp/validation-site-answers.yaml` (checked by the real wizard in a unit test).
5. **VALIDATION vs PRODUCTION.**
   - **Prompts:** VALIDATION serves the newest registered version, so v5; PRODUCTION only qualified ones, so the
     v4 baseline today (`libs/tb_llm/prompt_registry.py:386`).
   - **Models:** both route the judge and verifier only as champion (`services/registry/registry.py:189`). PRODUCTION
     also checks the record covers these weights (`registry.py:263`).
   - **Data class:** VALIDATION allows up to D2 (`libs/tb_common/policy/classes.py:42`). Its patient route takes
     D2-L only (`models/routing.yaml:226`). PRODUCTION takes D3 (`routing.yaml:219`).
   - **Study approval (D-640):** both are site boxes. No example rulesets are seeded
     (`libs/tb_common/ruleset.py:43`). An approval must name who gave it. The run's APPROVE mail from the box's named
     synthetic reviewer is such an approval.
   - **Limits:** same code in both. They are site settings (`libs/tb_common/authz.py:267`,
     `services/orchestrator/core.py:313`, `services/mail_gateway/intake.py:169`; 0 = none,
     `deploy/settings.example.yaml:26`).
   - **Tripwire:** same in both. It runs on every call of class D0 to D2 (`services/gateway/core.py:513-518`), and
     there is no setting.
6. **Why it cannot run (the two defects for lane D):**
   - (a) **Champion only, and no way to make one on the box.** The pair ships as "candidate". Promoting needs a
     passing qualification record (`tools/pin_model.py:645`). `qualify` sends its calls as D0
     (`tools/qualify.py:171`), and neither VALIDATION nor PRODUCTION has a D0 route for the judge. So the record
     cannot be made on an installed box. This is the same blocker the plan already names for PRODUCTION.
   - (b) **Screening is refused in VALIDATION.** The screen's judge prompt is labelled D3 (`libs/tb_llm/client.py:403`),
     which is above VALIDATION's D2 ceiling. Setting `TB_DATA_CLASS=D2-L` would let the screen route, but
     `TB_DATA_CLASS` is one value passed to the compiler, the doc parser and the orchestrator alike
     (`deploy/docker-compose.yml:201,216,281`). At D2-L the compile's `extract_criteria` and `concept_select` calls
     have no route. And at D2-L the tripwire would run on every note.
   `python -m tools.box_run validation-check` reports both, free, on any tree. It exits 0 the day both are fixed.
7. **Not built, an option for the owner:** a TEST box (`--rehearsal` with `TB_COMPOSE_OVERRIDE=` empty) with
   `TB_DATA_CLASS=D0`, `TB_GATEWAY_MODEL=j-workhorse` and `TB_GATEWAY_VERIFIER_MODEL=v-verifier` may route the real
   pair today. TEST takes any model status, serves the newest prompts, and its `dev-stub` route uses the on-box
   build when the caller names it (`routing.yaml:283-291`). This is **not verified**. The box would be TEST, not
   VALIDATION, and the tripwire would run on every call.

## 5. Defects for other lanes

| What | Where | Lane |
| --- | --- | --- |
| VALIDATION routes the pair only as champion, and `qualify` cannot make the record on an installed box (its calls are D0; no D0 judge route in VALIDATION or PRODUCTION) | `services/registry/registry.py:189`, `tools/qualify.py:171`, `models/routing.yaml` | D |
| A VALIDATION box cannot screen (D3 above the D2 ceiling), and one `TB_DATA_CLASS` cannot serve both compile and screen | `libs/tb_llm/client.py:403`, `deploy/docker-compose.yml:201,216,281`, `models/routing.yaml:226` | D, A2 |
| The box form cannot install a VALIDATION box (no `TB_ENV` in the planned answers) | `tools/box/plan.py:484` | D |
| `TB_ENV`'s declared help says "DEV, TEST or PRODUCTION": VALIDATION is missing | `libs/tb_common/config.py:562` | D |
| No tripwire setting; the tripwire refuses public protocols (dry run: 2 of 16 TFDA/CT.gov) | `services/gateway/core.py:513-518` | Integrator (asked), A |
| A box made by the wizard has no mail (`mta_authserv_id` empty): every mailed request is refused, and the SCREEN/FEAS product path is mail. The run sets `TB_MAIL_AUTHSERV_ID` as a site setting | `tools/box/plan.py` (`mta_authserv_id: ""`) | D, C2 |
| `TB_ENV` changed after an install is not checked by doctor (D-633's open item) | `tools/trialbox/doctor` | D |
| Carried from the dry run: FEAS report PDF crash on long protocols; English `note.csv` quarantined; SCREEN refuses a ruleset with no structured criterion | see public-accuracy-run-plan.md section 5 | B/E, E, A |
