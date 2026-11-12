# TB-DR2-13 The final build, hardware integration, best tuning and installation

| | |
| --- | --- |
| Document id | TB-DR2-13 |
| Date | 2026-11-12 |
| Tree | `514ae9b` (branch `claude/deep-review-2026-11-12`) |
| Area | Hardware forms, serving profiles, the build that ships, the installation procedure, what must be measured |
| Prefix | `HW` |
| Run here (no GPU, no root, no Docker daemon) | `bash -n` / `sh -n` on 35 scripts (all pass); `deploy/gpu_profile.sh` on 16 card names; `deploy/check_host.sh --gpu-only`; `deploy/install.sh --tier-check` for three tiers with and without a stand-in card; `tools.images_lock host` for 8 host cases and `check-compose`; `docker compose config` of the rtxpro6000, gb10, rtx5090 and shared-quota file sets (rendered in a scratch copy); `tools.box detect` and `tools.box plan` for 6 hardware descriptions; `tools.pin_model --install` on a placeholder folder and `--verify-all`; `pin_model.manifest_sha256_of_files` on the measured record; `embed_service.embedder.service_embedder` in PRODUCTION; `tools.gpu_sizing`; `tools.two_device profile`; `tools.b200_qualify layouts/cgi`; `deploy/hardening/apply.sh --dry-run`; `tools.trialbox doctor` on the example env |
| Only read | `deploy/install.sh`, `deploy/box-install.sh`, `deploy/check_host.sh`, `deploy/check_weights.sh`, `deploy/gcp/*.sh`, `tools/make_bundle.sh`, `tools/b200_qualify.sh`, `tools/spark_e2e.sh`, `tools/qualify.py`, `tools/serving_config.py`, the compose files, `models/registry.yaml`, the measurements, runbooks 01, 06, 08, 10, 11, 16, 17 |
| Not possible here | anything on a GPU, a Spark, a B200, a TPM, LUKS, systemd, or a running Docker daemon |

Memory arithmetic in this file uses one model that reproduces the two measurements to within 60 MiB
(`gpu-run-2026-11-08/fit.json`, `deploy/measured/serving_config.rtxpro6000.json`):
card memory used by a vLLM server = `--gpu-memory-utilization` × card total + a fixed part outside vLLM's budget
(judge 3,153 MiB, verifier 669 MiB); KV cache = the budget − the weights part (judge 18,931 MiB, verifier 9,009 MiB);
KV per token: judge 110 KiB, verifier 45.4 KiB. Check: RTX PRO 6000 at 0.40 + 0.20 predicts 62,554 MiB, measured
62,574 MiB; the 5090 simulation at 0.27 of the 96 GB card predicts 29,582 MiB, measured 29,623 MiB.

## 1. Reading in ten lines

1. **The build that ships has never run on a GPU.** G1 and the serving record ran vLLM by hand (`docker run`, weights
   from a Hugging Face cache, services in a venv, synthetic weight pins). The box rehearsal runs the real installer
   with stand-in model servers. The two never met: signed bundle + compose + model-guard + real weights + a real card.
2. **A PRODUCTION box does not start today.** The embed service refuses the stub and has no chosen embedder, no pin
   step and no Python packages for a model embedder in the image. Only the rehearsal's `hash` override hides it.
3. **A PRODUCTION box routes no note question after install.** Install pins `candidate`; only a qualification record
   makes a `champion`; no record exists, none ships, no install step promotes, and `qualify` needs a development
   checkout and public data sets a site box does not have.
4. Only one hardware form has a number: one RTX PRO 6000 (Server Edition, cloud VM). The DGX Spark, the B200 with MIG
   and the RTX 5090 are designs. The Spark cannot be installed by the product installer at all today.
5. The one measured speed (2.4 to 2.6 h per 50,000 patients per trial) was taken at **one model call at a time**: the
   harness never sets the concurrency the compose files set to 16. No tokens per second were recorded anywhere.
6. At that speed a 500,000-patient site needs 24 to 26 h per trial per night. It does not fit any night. The fix is
   measured batching plus an incremental night, not a bigger card.
7. Memory: the RTX PRO 6000 profile fits with 33 GiB unused. The 5090, the 24 GB path and the small MIG layout fit
   with about 1 GiB to spare, which is no headroom. The Spark arithmetic fits on paper (107 of about 120 GiB).
8. The judge's weights cannot pass both the pin and the licence step of `qualify` (one needs no licence file in the
   folder, the other needs one). The accuracy numbers were taken with another chat template than compose now passes.
9. The installation documents describe two other products (install.sh tiers, Windows with WSL2). Everything before
   `box-install.sh` (firmware, OS, disk encryption, NVIDIA driver, Docker) is unscripted and partly missing from the
   media. The box form has no workable disk-unlock design without a person or a hospital key server.
10. Recommendation: **one product set for both sites**: Ubuntu 24.04 + one RTX PRO 6000 Workstation Edition +
    `docker-compose.yml`, `.secrets.yml`, `.rtxpro6000.yml`, `.identity.yml`, `.box.yml`, installed by
    `box-install.sh`. Keep the B200 as the owner's bench. Park the Spark, the 5090, the 24 GB path, `default`,
    `topology_a` and the WSL2 host until a site orders one.

## 2. Status of the previous review's findings (hardware and serving)

Checked in code or by a run on this tree. "Fixed (design)" means the code is there and tested with stand-ins but has
not run on the hardware.

| Old ID | Severity | Status | Evidence |
| --- | --- | --- | --- |
| LLM-001 real pair never passed a full run through the gateway | Blocker | **Partly** | G1 attempt 2: hospital-ja 19 of 20 stages, pair canary 52/54, no false exclusion (`g1-2026-11-11/README.md`). 21 parts never ran; stage 12 failed; not the product build (HW-001) |
| LLM-007 trust on first use | High | **Fixed** | `models/registry.yaml` `expected.manifest_sha256`; by a run: `pin_model --install rtxpro6000` on a 2-byte folder → "differs from the expected 5e5bef7a61fe ... refused"; the expected values reproduce from the measured record (`manifest_sha256_of_files` → `5e5bef7a…`, `869b5253…`) |
| LLM-008 weights verified at install only | Medium | **Fixed (design)** | `deploy/check_weights.sh`, `trialbox-weights.timer` (01:30 and 10 min after boot), `install.sh:495` |
| LLM-010 vLLM by tag | Medium | **Fixed** | digest in every compose file; `images_lock check-compose` PASS on 6 files (run) |
| LLM-011 no B200 in the model path | High | **Fixed (design)**, unmeasured | `gpu_profile.sh` → `shared-quota` / `b200-no-mig` (run); `PROFILE_PAIRS["shared-quota"]`; `serving_config.MIG_MIN_LEN`. `tools/gpu_sizing.py` still has no B200 (run) |
| LLM-013 wizard writes an embedder mode the service refuses | High | **Partly** | the name is shared now (`model`); the service still cannot start in PRODUCTION (HW-002, by a run) |
| LLM-014 embedder outside every control | Medium | **Partly** | build `e-embed-1` exists with every field `null`; nothing chosen (`registry.yaml:587-601`) |
| LLM-015 prompt budgets ignore the server's context | High | **Fixed (design)** | `services/gateway/core.py:351-365` reads `context_length`; `tb_llm.budget`; not run at 8k or 16k on a card |
| LLM-024 KV cache below 16 × 32k on the PRO 6000 | Low | **Open** | unchanged flags; arithmetic in §4.1 (188k tokens, 5.7 full-context sequences) |
| LLM-025 only one card has a number | High | **Open** | still one card; G1 adds 50,000 patients ja on the same card, at concurrency 1 (HW-006) |
| LLM-026 `gpu_sizing` out of date | Medium | **Open** | by a run: prints gpt-oss-120b on the PRO 6000 and the Spark, no pair row, no B200 |
| LLM-027 / OPS-067 two MIG instances | High | **Fixed (design)**; request to CGMH not evidenced | `docker-compose.shared-quota.yml` (two device ids), `serving_config.measured_for` refuses one device for both |
| LLM-028 platform manifests without key and guard | Medium | **Fixed (design)** | `deploy/platform/components/gpu-pair/llm.yaml`, `base/apps.yaml` name model-guard (read) |
| LLM-029 no `qualify`, champion by install | High | **Partly** | `tools/qualify.py`, `pin_model --promote` exist; no record exists (`eval/qualification/` holds none); no site path to one (HW-003) |
| LLM-042 nothing tells vLLM not to log requests | Medium | **Fixed (design)** | `VLLM_LOGGING_LEVEL: WARNING` in every profile; not read on a server |
| OPS-010 host tree outside the signed bundle | High | **Fixed** | `make_bundle.sh` packs kind `host`; `install.sh:183-198` re-runs from the signed tree |
| OPS-013 no clinic PC can use the box after install | High | **Fixed (design)** | `install.sh:280-291, 369-380, 587-598, 613-634` |
| OPS-015 `check_host` weaker than it reads | Medium | **Fixed** | LUKS under Docker's root, free space, cron, time zone, firewall, WSL2 (read) |
| OPS-017 test mail servers in the bundle | Medium | **Fixed** | `make_bundle.sh:64-72` renders the box files only |
| OPS-018 a gated bundle cannot be built | High | **Partly** | the gate blocks; HAPI, vLLM and the db base pass only through 81 dated allow-list entries that lapse on 2026-12-10 (`known-image-findings.md`). No real bundle with real weights has been built (HW-001) |
| OPS-019 Spark on a community vLLM image | Medium | **Fixed (design)** | `docker-compose.gb10.yml` uses the official image's arm64 manifest; "to be confirmed on a Spark" |
| OPS-024 host patching has no design | High | **Partly** | `deploy/hardening/ospatch.py`, `check_host` reads its state; the NVIDIA driver is still outside every bundle (HW-012) |
| OPS-029 unhealthy container not restarted | Medium | **Fixed (design)** | `trialbox-watchdog.timer`, labels `tb.watchdog` |
| OPS-043 a stolen Linux box unlocks itself | High | **Partly** | `luks_policy.py` FAILs a TPM-only unlock; the box form has no passing unattended alternative (HW-010) |
| OPS-049 egress open after a reboot | High | **Fixed (design)** | `trialbox-egress.service` before Docker; `trialbox.service` re-applies |
| OPS-050 / OPS-066 shared B200 at CGMH, platform kind unknown | Blocker / High | **Open** | still no answer to survey question 51 in the tree; v6.1 makes the box the first form (HW-009) |
| OPS-061 Windows with WSL2 | Blocker | **Moot by plan** | v6.1 §3.6: "the Windows/WSL2 path is not the box's path"; the code and `OFFLINE-MEDIA.md` still carry it (HW-012) |
| OPS-062 three documents name three host systems | High | **Partly** | D-408 and `check_host` name Ubuntu 24.04; `OFFLINE-MEDIA.md` and runbook 01 still say Windows |
| OPS-063 DGX Spark unmeasured, driver hold, no limits | High | **Partly** | limits added and dated hold (`gb10-profile.yaml`); every number `null`; not installable (HW-008) |
| OPS-064 RTX 5090 tier | Medium | **Partly** | `trialbox.service` restarts the stack through compose, so the helpers run; never on a real card; runbook 10 still says "run compose up again" |
| OPS-065 PRO 6000 measured only on a cloud VM | Medium | **Open** | the only record is `NVIDIA RTX PRO 6000 Blackwell Server Edition` on `tb-gpu-sim` (48 vCPU) |
| OPS-068 platform form has no day 2 | High | **Fixed (design)** for Kubernetes | `tools/trialbox/platform_day2.py`, `kind-day2.sh`; the compose form on a shared Docker host has none |
| OPS-070 / OPS-071 noisy neighbours, record transfer | Medium | **Partly** | `tools/trialbox/noisy_neighbour.py`, `doctor --platform host_match` (WARN on a difference); nothing measured |
| OPS-072 no capacity model | Medium | **Open** | T-734 not started; no tokens per second recorded (HW-006, HW-007) |

## 3. Hardware × form

"Measured" means a committed measurement file taken on that card running that profile.

### 3.1 Table

| | RTX PRO 6000 (box) | DGX Spark / GB10 (box) | B200 with MIG (shared) | RTX 5090 (box) | 24 GB card (`rtx4090`) | any other card (`default`) |
| --- | --- | --- | --- | --- | --- | --- |
| Files | `docker-compose.rtxpro6000.yml` | `docker-compose.gb10.yml`, `gb10-profile.yaml` | `docker-compose.shared-quota.yml` + `platform/` | `docker-compose.rtx5090.yml` | the 5090 file, verifier scaled to 0 | base `llm-service` |
| Memory | 97,887 MiB | 128 GB unified, shared with the whole stack | 180 GB card; instance sizes 23, 45, 90 GB | 32,607 MiB | 24,564 MiB | unknown |
| Pair, quantisation | Gemma 4 26B-A4B NVFP4 (17.5 GiB on disk) + Qwen3.5-9B AWQ 4-bit (8.5 GiB), both resident | same pair, resident | same pair, one MIG instance each | same pair, one awake at a time (vLLM sleep mode) | judge alone, note answers never exclude | `qwen3.5-35b-a3b-q4`, a model no bundle carries |
| Flags as committed | 32,768 × 16 seqs, util 0.40 / 0.20, eager | 16,384 × 8, util 0.30 / 0.15, eager | no defaults (compose refuses unset); layouts in `b200-layouts.json` | 8,192 × 4, util 0.81 each, eager, sleep mode | as the 5090 | 32,768 × 64, util 0.85 |
| Card memory used (model above) | 62.6 GiB of 95.6: **33 GiB free** | judge 39.0 + verifier 18.6 = 57.6 GiB, plus 41 GiB of service limits and 8 GiB system = 107 of about 120 GiB (if the device reports 128 GB nominal as about 120 GiB) | small: judge on 2g.45gb at 0.9 = 43.6 of about 45 GiB (**about 1 GiB free**); verifier on 1g.23gb at 0.9 = 21.3 of about 23 GiB. Large: 3g.90gb each, ample | judge awake 28.9 GiB + sleeping verifier about 1 GiB = 29.9 of 31.8 GiB (**under 2 GiB free**; a desktop session on the card takes that) | 22.5 of 24.0 GiB; KV cache 0.94 GiB = 8,980 tokens, **one** 8k sequence, not four | does not start (no such weights) |
| KV cache against context × sequences | judge 188k tokens = 5.7 sequences at 32k (16 configured); verifier 238k = 7.3. Enough for screening prompts (about 3k each) | judge 166k tokens against 8 × 16k = 131k: fits in full | small: judge 210k against 4 × 16k; verifier 275k against 4 × 8k: fits | judge 70k against 4 × 8k = 33k: fits | see above | - |
| Measured? | **Yes**, one edition, one host: `deploy/measured/serving_config.rtxpro6000.json` (2026-11-08), `g1-2026-11-11/gpu_peak.json` (62,592 MiB peak over 5 h) | **No.** `gb10-profile.yaml` `status: unmeasured`, every measured field `null` | **No.** `b200-g1b/G1b.md`: "not run" | **No** on a real card. Simulated on the 96 GB card capped to 32 GB (`gpu-run-2026-11-08/fit.json`, `gpu-run-2026-11-08b/`); the answers after a wake were not captured | No | No |
| Installable by the product installer today | `install.sh --tier large` passes the tier check with a stand-in card (run). `box-install` plans `--mode gpu --gpu rtxpro6000` (run). Then HW-002, HW-003 | **No**: `--tier medium` refused, no record (run); `box-install` plans `--gpu gb10`, which `install.sh:352` then refuses | **No** by design (`install.sh:160-161`, `box plan` refuses, run) | `--tier small` refused, no record (run) | only with `TB_ACCEPT_UNMEASURED_GPU=1` | starts and fails at "the stack did not become healthy" |
| Architecture, images | x86-64; `make images`; lock has the amd64 manifest | aarch64; the vLLM lock entry has an arm64 manifest built for sm_120 (the GB10 is sm_121; `images_lock host` passes 12.1 on the major number, an assumption); `make images PLATFORM=linux/arm64` or a native build. **No way to make an arm64 bundle**: `make_bundle.sh` uses `docker save` of the build host's architecture and has no platform option | x86-64 | x86-64 | x86-64 | x86-64 |
| Driver | lock needs 580.65.06 or newer (CUDA 13.0); measured on 580.178.04 | held at exactly 580.142 (`check_host.sh --gb10` FAILs any other). The claim that later builds break vLLM is not measured in this repository; the x86 record is on a later build | the platform team's; not ours | as the PRO 6000 | as the PRO 6000 | - |

### 3.2 Facts for a hospital room (from the vendors' public data; verify on the unit, none is in the repository)

| | RTX PRO 6000 workstation | DGX Spark | B200 | RTX 5090 workstation |
| --- | --- | --- | --- | --- |
| Power | card up to 600 W (Workstation Edition; the Max-Q edition 300 W; the Server Edition is passively cooled and is **not** a desk card). Whole machine near 900 W at full load: a dedicated 15 A circuit on 100 V (Japan) or 110 V (Taiwan), and a UPS sized for it | about 240 W supply | about 1 kW per card, only inside an 8-card server of 10 kW and more | card up to 575 W |
| Heat and noise | about 3,000 BTU/h during the night batch; audible. A server or equipment room, or a room nobody sits in at night | near silent; small enclosure, sustained-load throttling is the open question (test S-5) | data centre only | as the PRO 6000 |
| Place | tower or 4U rack kit | on a shelf; one internal NVMe, no second disk: backups need an external disk or a share | the hospital's machine room; not a box | tower |
| ECC / errors | ECC memory on the card and (with a workstation board) in the host | no ECC | ECC | no ECC on the card |
| Supply | one card, one supplier; lead times of weeks; order the Japan unit and a spare path early. The measured edition is not the one a site gets (test P-1) | available; the driver hold fights the vendor's own system updates | not purchasable as a box | consumer channel, volatile; not sold as a workstation part |
| MIG | supported on this card; with MIG on, `gpu_profile.sh` prints `shared-quota` and the box installer refuses (run) | no | yes, up to 7 instances | no |

### 3.3 The B200 with MIG: what is needed and what TrialBox cannot control

- **Instances.** Two, one per model server (a device serves one container). The two layouts to qualify:
  `2g.45gb` + `1g.23gb` (three of seven compute slices), or `3g.90gb` + `3g.90gb` (six of seven)
  (`eval/qualification/b200-layouts.json`). The small layout leaves the judge about 1 GiB (HW-014).
- **Isolation.** MIG separates card memory, compute slices and card faults. It does not separate host CPU, host
  memory, storage, the network or the host's administrators. `ipc: host` is set on both vLLM servers
  (`docker-compose.shared-quota.yml`), which on a shared host shares the host's IPC namespace with the container.
- **Who administers it.** The platform team: MIG mode, the instance layout and whether it survives a reboot (the
  layout is not persistent without their own tooling), the driver, CUDA, the kernel, reboots, maintenance windows,
  and who else runs on the other slices. `TB_MIG_JUDGE_DEVICE` / `TB_MIG_VERIFIER_DEVICE` are instance UUIDs: after
  any re-partition they must be read again and compose restarted; nothing in TrialBox does that.
- **What TrialBox cannot control there.** The driver version (so the qualification on the owner's B200 transfers
  only while `doctor --platform host_match` shows no difference), a card reset caused by another tenant, the time of
  day the slices are free, the storage the volumes are on, the backup target.
- **Platform kind.** Still unknown (Kubernetes, plain Docker, Slurm). The compose form has no installer and no day 2;
  the Kubernetes form has both, tested on `kind` only.

## 4. Serving profile per hardware and best tuning

Marks: **M** measured, **D** derived from a measurement by arithmetic, **H** hypothesis to measure (test id in §8).

### 4.1 As committed

| Setting | RTX PRO 6000 | Spark | B200 small / large | 5090 |
| --- | --- | --- | --- | --- |
| Context (judge, verifier) | 32,768 | 16,384 | 16,384 and 8,192 / 32,768 | 8,192 |
| `--max-num-seqs` and `TB_SCREEN_LLM_CONCURRENCY` | 16 | 8 | 4 / 8 | 4 |
| `--gpu-memory-utilization` | 0.40, 0.20 | 0.30, 0.15 | 0.9, 0.9 | 0.81, 0.81 (one awake) |
| `--enforce-eager` | yes | yes | yes | yes |
| Structured output | vLLM default backend `auto`, `response_format: json_schema` | same | same | same |
| Chat template | judge: `--chat-template` developer's file (sha256 `null` in the registry); verifier: its folder's, thinking off | same | same | same |
| Two models | resident, `TB_MODEL_SWAP=off` | resident | resident, own instances | sleep swap, one per run |
| Embedder | CPU (`TB_EMBED_DEVICE` unset) | `TB_EMBED_DEVICE=cuda` but the service has **no GPU device reservation** (rendered config, run): it cannot see the GPU | CPU | CPU |
| Host memory limits of the model servers | 48 GiB each (the 5090's sleep figure) | 42 and 32 GiB | 48 GiB each | 48 GiB each |
| vLLM / CUDA | v0.32.0 by digest, CUDA 13.0.2, driver ≥ 580.65.06 | same image, arm64 manifest | same | same |

Tensor parallel does not apply: every form is one device per server.

### 4.2 Recommendations

| # | Recommendation | Reason | Mark |
| --- | --- | --- | --- |
| R1 | **Keep 4-bit NVFP4 judge + AWQ verifier on every form.** Do not try 8-bit on the 96 GB card before go-live | The pair passed the canary (52/54, no pair-decided-wrong) and G1's exclusion check (464 true, 0 false) with these weights. Any other quantisation is another build and another qualification | M (accuracy), D (cost of change) |
| R2 | **PRO 6000: raise sequences before raising anything else.** Measure 16, 32 and 48 sequences with the screening prompt at utilisation 0.40 / 0.20. Take the highest whose p95 call time keeps one trial of the site inside the window | 16 screening prompts of about 3k tokens use 48k of the judge's 188k KV tokens; the cache is not the limit. The card has 33 GiB unused. The only measured speed is at one call at a time (HW-006) | H (G-3) |
| R3 | **Keep context 32k on the PRO 6000; do not go to 64k.** Screening needs about 3.5k (2,500 excerpt tokens + system + 1,024 answer). 32k serves protocol reading. Sixteen 32k protocol readings at once do not fit (5.7); the gateway's slots cap them | arithmetic from `fit.json` | D |
| R4 | **Prefix caching: keep vLLM's default on, and reorder the judge's user message only as a measured change.** Today the user JSON is `criterion_text`, `note_question`, `index_date`, `excerpts` (`libs/tb_llm/prompts/judge_v5.md:22`). Only the system text (about 400 tokens of about 3,000) repeats between calls. Excerpts first and the criterion last would let one patient's excerpts be reused across criteria when the same excerpts are sent | a prompt change is a new prompt version and needs the canary and the judge property test again; the gain exists only where criteria share an excerpt set | H (G-5) |
| R5 | **Nightly batch: throughput, not latency.** Run the judge pass and the verifier pass at the full sequence count; give interactive calls (chart check, protocol help) the gateway's daytime slots. On the 5090 this is already forced by the swap | a night has no person waiting; `TB_SCREEN_LLM_CONCURRENCY` equals the server's sequences already | D |
| R6 | **Test without `--enforce-eager` on the PRO 6000.** It was set for the first measured runs and kept. Without it vLLM uses CUDA graphs, usually faster for short answers, with a longer start and more memory outside the budget | every record so far has `enforce_eager: true`; the gain on NVFP4 is unknown | H (G-4) |
| R7 | **Guided decoding: measure its cost once, then leave it on.** One schema (`llm_judge_output`) is compiled once per server; the per-token mask is the cost. Record tokens per second with and without `response_format` on 200 calls | never measured; the schema guarantee is worth a few per cent | H (G-4) |
| R8 | **Both resident wherever they fit; the sleep swap only on 32 GB.** The swap costs one run-level hold and blocks chat during the verifier pass | measured: side by side does not fit in 32 GB (`fit.json` pair-tight); swap times 0.3 to 3.7 s | M |
| R9 | **Embedder on the CPU on every form until an embedder is chosen and measured.** Remove `TB_EMBED_DEVICE=cuda` from the Spark file or give the service the device | on unified memory a GPU embedder takes from the same pool as the models; on the PRO 6000 the 33 GiB spare could hold one (about 2.5 GiB) if the nightly increment needs it | D (Spark), H (G-8) |
| R10 | **MIG small layout: judge utilisation 0.85, not 0.9.** | 0.9 of about 45 GiB + 3.15 GiB outside the budget leaves about 1 GiB; 0.85 leaves about 3.5 GiB and still gives the judge 190k KV tokens | D (B-2) |
| R11 | **Spark: keep 16k × 8 as the starting point and measure whether GPU memory is charged to the container's memory limit** before trusting the 42 GiB cap on the judge (39 GiB of card memory + the process) | `gb10-profile.yaml` says this is unmeasured | H (S-2) |
| R12 | **Model-server host memory limit per profile.** 48 GiB is the 5090's figure (a sleeping model's weights in host RAM). On the PRO 6000 nothing sleeps; record the servers' resident memory in G-2 and set the default in the overlay from it | see HW-011 | H (G-2) |
| R13 | **One vLLM uplift before the release, planned.** v0.32.0 carries 29 fixable HIGH or CRITICAL findings, allow-listed to 2026-12-10. Moving the image is a model change: serving record, canary, qualification, G1 again on each card | `known-image-findings.md`; `images.lock` note | D |
| R14 | **Do not rely on the driver hold on the Spark until it is reproduced.** Test the pair on the system's current driver first (S-1) | the hold blocks the vendor's updates; its reason is a reference, not a measurement here | H |

### 4.3 Throughput to the night window

**What was measured.** RTX PRO 6000 (Server Edition), 50,000 synthetic patients, one trial (GZQO), Japanese, pair in
agreement mode (`g1-2026-11-11/hospital-ja.json`): the SCREEN chain 9,263 s (`chain_seconds`) and a second full
SCREEN 8,584 s (stage 15); 1,193 patients reached the note stage; 6,704 model calls in the part. That is
**7.2 to 7.8 s per note-stage patient** and 2.4 to 2.6 h per 50,000 patients per trial. The 2026-11-08 small run gave
6.3 s. **Tokens per second, call latency and GPU utilisation were not recorded in any file**, so the arithmetic below
is in seconds per note-stage patient, not tokens. **The run made one model call at a time**: the harness does not run
compose, and `TB_SCREEN_LLM_CONCURRENCY` is set only in the compose files (`grep` over the tree; default 1 at
`services/orchestrator/scenarios/screen_cascade.py:332`).

**The window.** `schedule.ingest` 02:00 and the morning mail at 07:00: W = 5 h. With the 30 % headroom the Spark
decision gate already uses (`gb10-profile.yaml`, `screening-night`), the usable time is 3.5 h = 12,600 s, less the
ingest and the 04:45 backup, which G1 did not time separately.

| Hardware | Basis | 50,000 patients, one trial | 500,000 patients, one trial | Mark |
| --- | --- | --- | --- | --- |
| RTX PRO 6000, one call at a time | measured | 2.4 to 2.6 h: fits 3.5 h; **one** trial a night (two need 4.8 to 5.1 h) | 24 to 26 h: does not fit. Needs 6.8 to 7.4 times the speed for one trial in 3.5 h | M / D |
| RTX PRO 6000, 16 sequences | not measured | if batching gives 5 to 10 times: 15 to 30 min; 7 to 14 trials a night | 2.4 to 5.2 h per trial: at best one trial; not a full re-screen of several | H (G-3) |
| RTX 5090, 4 sequences, swap | not measured on the card; same generation | about the PRO 6000's single-call time: about 2.5 h | does not fit | H (owner's card if ever) |
| B200 small layout (2 of 7 slices for the judge) | nothing measured | unknown | unknown | H (B-3) |
| DGX Spark, 8 sequences | nothing measured. `tools/gpu_sizing.py`'s own estimate puts a Spark at 0.15 of the PRO 6000 per sequence (33 against 220 tokens per second for the same model) | at that ratio 16 to 17 h one call at a time; inside 3.5 h only if 8 sequences give 4.7 times or more | does not fit | H (S-3) |

Consequences that do not depend on the unmeasured rows:

- A 500,000-patient site cannot re-screen every patient for every trial every night on any single card in the list.
  The night must be incremental (patients whose data changed, plus new or changed trials); the first screen of a new
  trial is a backfill over several nights or a weekend. T-734 has to state this, not hide it.
- At 500,000 patients one trial makes about 33,000 to 67,000 model calls (2.8 to 5.6 per note-stage patient × 11,930).
  `SCREEN_MAX_PAIRS = 20000` (`screen_cascade.py:315`) stops the run before that. It is a fixed limit with no
  derivation (OD-10); the scale review owns it, it is listed here because the hardware sizing depends on it.
- The synthetic note-stage share is 2.4 % (1,193 of 50,000). A real trial with a share of 10 % multiplies every row
  by four. The capacity statement must take the share from the site's own first screen.

## 5. The final build

### 5.1 What ships

| Part | Source | Size | Pinned by | State |
| --- | --- | --- | --- | --- |
| `trialbox-py:1.0.0` | `deploy/docker/python.Dockerfile`, base `python:3.12-slim` by digest, `deploy/requirements.lock` (726 lines, hashed) | not built here | base digest; lock | builds in CI; holds **no** `torch` / `sentence-transformers` (HW-002) |
| `trialbox-jvm:1.0.0` | `jvm.Dockerfile` on `trialbox-py` | not built here | - | - |
| `trialbox-postgres:16-1` | `db.Dockerfile`, base `postgres:16-trixie` by digest, pgvector 0.8.7, PGroonga 4.1.0, pgBackRest 2.60.0 | - | `images.lock` `images.db` (its own `digest: null`) | 29 allow-listed base findings |
| vLLM | `vllm/vllm-openai:v0.32.0@sha256:befccf0e…` | about 9 GB | `images.lock` | 29 allow-listed findings; lapse 2026-12-10 |
| HAPI FHIR | `hapiproject/hapi:v8.12.0-2@sha256:0ff86aac…` | - | `images.lock` | 23 allow-listed findings |
| Caddy, Authelia | `caddy:2.11.9-alpine`, `authelia/authelia:4.39.28`, by digest | small | `images.lock` | - |
| Judge weights | `nvidia/Gemma-4-26B-A4B-NVFP4` @ `a19cfe00…` | 17.5 GiB (18.8 GB), 2 safetensors | `registry.yaml` `expected.manifest_sha256 5e5bef7a…`; licence Apache-2.0 (register row `model-gemma-4-26b-a4b-nvfp4`); no licence file in the source | pin path proven on a placeholder only |
| Verifier weights | `cyankiwi/Qwen3.5-9B-AWQ-4bit` @ `e4d2d39c…` | 8.5 GiB (9.1 GB), 3 safetensors | `expected.manifest_sha256 869b5253…`; Apache-2.0, `LICENSE` sha256 `bbedc3fd…`; origin CN (`non_prc: false`) | a community quantisation; "own copy" question open in the registry |
| Judge chat template | `google/gemma-4-26B-A4B-it` @ `4d7ae4984b7d` (short id), placed by hand at `deploy/models/chat-templates/gemma-4-26b-a4b-it/chat_template.jinja` | 17 kB | `sha256: null` | first use is trusted; never served (HW-005) |
| Embedder | none chosen (`e-embed-1` all `null`) | - | - | missing (HW-002) |
| Host tree | `tools/host_tree.py pack` → `trialbox-host.tar` with `HOST-SHA256SUMS` | < 10 MB | bundle signature | fixed since the last review |
| Release record | `tools/release.py`: `release.json`, per-image SBOM (Syft), the release's `images.lock`, `NOTICE`, `CHANGELOG.md` | - | Ed25519 over the manifest (`tools/sign_bundle.py`) | the vendor key file is still written unencrypted (`sign_bundle.py:44`) |
| Media | `docs/handover/OFFLINE-MEDIA.md`: about 40 GB bundle on a 128 GB disk | - | `SHA256SUMS` + signature | the layout is the Windows one: a Windows NVIDIA driver, WSL, no Linux driver (HW-012) |

Reproducibility: bases, third-party images and Python packages are pinned by digest or hash; fonts and Maven
artefacts are fetched at build (`jvm-deps`, `$(FONTS)`). The bundle is single-architecture. No real bundle (real
weights, gates passed, signed with the vendor key) has been built and installed on a GPU machine.

### 5.2 The one product set

| Site | Hardware | Host | Compose set | Installer |
| --- | --- | --- | --- | --- |
| **Japan** (2027-05-13) | one RTX PRO 6000 Blackwell **Workstation Edition**, 128 GB RAM or more, two NVMe disks (system, data) and a third disk or share for backups, TPM 2.0, UPS | Ubuntu 24.04 LTS | `docker-compose.yml` + `.secrets.yml` + `.rtxpro6000.yml` + `.identity.yml` + `.box.yml`, profile `gpu` (what `install.sh` writes to `COMPOSE_FILE` with `TB_BOX=1`) | `deploy/box-install.sh` |
| **CGMH** (2027-04-28) | the same box | the same | the same | the same |

Name it **P-PRO6000 box**. The CGMH B200 becomes a form only if CGMH requires the shared host in writing and names
its platform; until then the owner's B200 is a bench for G1b. This follows v6.1 OD-11 and §3.6.

### 5.3 What to delete or park (see also §9)

`rtx4090` and `default` paths; `deploy/topology_a/`; the base file's `qwen3.5-35b-a3b-q4` server command;
`deploy/windows/` and the Windows media layout out of the release path; the tier names beside the GPU profile names
(two vocabularies for one choice); `docker-compose.rtx5090.yml` and `deploy/two-device/` moved to a "parked forms"
folder with their tests; `tools/gpu_sizing.py` replaced by the capacity statement.

## 6. The installation procedure, end to end

Status: **S** scripted, **D** documented only, **X** missing. Times are estimates for the P-PRO6000 box; none was
timed on hardware.

| # | Step | How | Status | Time |
| --- | --- | --- | --- | --- |
| 1 | Unbox, seat the card, cable power (dedicated circuit, UPS), network port from the hospital sheet | nothing in the tree | X | 45 min |
| 2 | Firmware: UEFI update, Secure Boot on, TPM 2.0 on, boot order, power-on after power loss | nothing | X | 30 min |
| 3 | Ubuntu 24.04 LTS on LUKS2 (system and data), swap off | runbook 01 step 1 (one line); `docs/SECURITY.md` §1 | D | 40 min |
| 4 | Disk unlock policy | `deploy/hardening/disk-unlock.sh bind --device … [--dry-run]` needs a hospital Tang server; without one only a passphrase at every boot passes `luks_policy.py` (WARN). No box-form design (HW-010) | S for the IT form, X for the box form | 20 min |
| 5 | NVIDIA driver (R580, ≥ 580.65.06), `nvidia-container-toolkit`, Docker Engine 27+ with compose, nftables, cron, python3, clevis: from the media, offline | `OFFLINE-MEDIA.md` lists `linux/debs/` (no NVIDIA Linux driver in the list); no script installs them; no reboot check | D, partly X | 40 min |
| 6 | Network per the hospital sheet: fixed address, DNS name, NTP, mail relay, the feed mount | `docs/handover/network-sheet.*`; set by hand with netplan; `tools.box detect` reads the result | D | 30 min |
| 7 | Copy the release tree and the bundle from the media; check `SHA256SUMS`; place the vendor public key at `deploy/keys/vendor_ed25519.pub` | runbook 01 step 6; `install.sh:174-177` checks the key and the `.sha256` | D | 25 min (40 GB over USB 3) |
| 8 | Host pre-check | `sudo deploy/install.sh --check` → `check_host.sh`; GPU part alone: `sh deploy/check_host.sh --gpu-only --gpu rtxpro6000` | S | 2 min |
| 9 | Install | `sudo deploy/box-install.sh trialbox-<version>.tar` (or `--prepare` at Aimedics before shipping): detect, plan, `install.sh` (verify and load the bundle, re-run from the signed tree, settings, keys, pin and verify weights, serving-record rule, stack up, doctor `--serving`, egress, firewall, systemd units, cron, backup install, reference data) | S; stops today at the stack start (HW-002) | 35 to 50 min (load 40 GB of images and weights, hash 26 GiB twice, two model loads of 1 to 2 min) |
| 10 | Weights check | inside step 9 (`pin_model --install`, `--verify-all`); later `deploy/check_weights.sh`, `make verify-models` | S | 3 min |
| 11 | First-run wizard: the one-time code on the box's screen, `https://<name>/login/first-run`, owner account, site name, time zone, backups, data source | `box-install.sh` step 5 and 6, `tools.box apply` | S (rehearsed with stand-ins) | 20 min |
| 12 | Site settings: mapping in `deploy/site/mapping`, mail, accounts | wizard and the console; `tools/mapping_check.py` | S / D | 1 to 3 h with the site |
| 13 | First ingest | `docker compose --project-directory deploy exec adapter python -m adapter.cli run`, or 02:00 | S | by data size; G1: not timed apart |
| 14 | Serving record of this box | `python3 tools/serving_config.py capture --container judge=trialbox-llm-service-1 --container verifier=trialbox-llm-verifier-1 --models-dir deploy/models --out deploy/site/serving_config.rtxpro6000.json` | S (by hand; the installer does not do it) | 5 min |
| 15 | Canary | `sudo python3 -m tools.trialbox selftest` (`make selftest`); the box also runs it at start and nightly | S | about 5 min (54 cases × 2 models) |
| 16 | Qualification and promotion to `champion` | `python -m tools.trialbox eval qualify --profile rtxpro6000 …` then `pin_model --promote` (runbook 11). Needs a clean checkout, the N-12, `public_e2e` and goldens evidence files, the medtxt data, a TEST gateway. Not possible on a site box (HW-003, HW-004) | S as a tool, X as a site step | - |
| 17 | Capacity check on the site's data: one full SCREEN of one trial, timed against the window | nothing (T-734) | X | one night |
| 18 | Power-cycle and restart drill; planned-power-cut page | rehearsal step `power-cycle` on stand-ins; `docs/runbook/22-planned-power-cut.md` | S on stand-ins, D on hardware | 20 min |
| 19 | Go-live acceptance | `tools/acceptance.py ingest | feas | screen-sample | screen | nav | twpas | reproduce | audit | report` (runbook 06); `make test-egress`; host check output kept | S; no hardware or capacity criterion; `nav` and `twpas` are Taiwan checks, Japan has no line (HW-018) | 1 to 2 weeks elapsed (adjudication of 120 patients) |
| 20 | Backup key with the site; first off-box backup; restore drill | `tools.trialbox backup-keygen`, `backup-install`, runbook 05 and 22 | S | 1 h |
| 21 | Handover: the owner's handbook, the IT one-pager, the network sheet printed, the key envelope | `deploy/site/network-sheet.*` is written by the installer; the handbook is T-735, not written | D / X | 1 h |

### 6.1 Script checks run here

- Syntax: `bash -n` or `sh -n` passes on all 35 scripts under `deploy/`, `deploy/hardening/`, `deploy/gcp/`,
  `deploy/windows/`, `deploy/platform/`, `deploy/docker/` and `tools/*.sh`. `shellcheck` is not installed here.
- `sh deploy/check_host.sh --gpu-only --gpu rtxpro6000` on this machine (no GPU):
  `PASS vLLM image … has a linux/amd64 build`, `FAIL no NVIDIA driver found (nvidia-smi): the vLLM image needs
  580.65.06 or newer`, `WARN compute capability not reported`, exit 1. Correct.
- `bash deploy/install.sh --tier large --tier-check`: "refused: tier large needs one RTX PRO 6000 (96 GB), and this
  machine shows no NVIDIA card", exit 3. With `TB_TIER_TEST_CARD="NVIDIA RTX PRO 6000 Blackwell Server Edition"`:
  "tier large: rtxpro6000 profile, measured record …/serving_config.rtxpro6000.json", exit 0. `medium` and `small`
  with their cards: refused, "has no measured serving record", exit 3, with the capture command in the message.
- `tools.images_lock host`: driver 570.86.16 FAIL; 580.65.06 and 580.178.04 PASS; aarch64 with capability 12.1 PASS
  "covered by the image's build (… 12.0)".
- `tools.box plan --provisional`: PRO 6000 with 125.6 GiB → `--mode gpu --gpu rtxpro6000`, caps at 0.79 of the
  defaults; the same card with 62.5 GiB → "needs at least 79 GiB"; Spark → `--mode gpu --gpu gb10`; B200 with MIG →
  refused; RTX 6000 Ada → `--mode stub` with a note.
- `deploy/hardening/apply.sh --conf <box conf> --dry-run all`: prints the firewall and SSH actions, changes nothing.
- `tools.b200_qualify cgi small` → `2g.45gb,1g.23gb`; `large` → `3g.90gb,3g.90gb`.
- `tools.two_device profile` → `ok`. `tools.pin_model --verify-all deploy/models` → "nothing is pinned", exit 1
  (correct for a checkout).

## 7. Findings

| ID | Severity | Finding | Evidence | Impact | Fix | Card | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HW-001 | Blocker | The product build has never run on a GPU. G1 and the vendor serving record start vLLM with a hand-written `docker run` (model from the Hugging Face cache, `--api-key` on the command line, no `--chat-template`, no model-guard) and run the services from a venv with synthetic weight pins. The box rehearsal runs the real installer with stand-in model servers and the hash embedder. Nothing has run signed bundle + compose + real weights + a card. The record also counts for a card edition and host no site will have (Server Edition, 48 vCPU cloud VM) | `deploy/gcp/complete-run-vm.sh:278-295`; `deploy/gcp/gpu-pro6000-run.sh:63-77`; `g1-2026-11-11/hospital-ja.json` `run.weight_pins: "synthetic"`; `docs/runbook/16-box-install-rehearsal.md` "Not rehearsed"; `serving_config.py:237` (card rule is the substring "RTX PRO 6000") | Every number about the box is about another assembly. The first real install is the first test of: the flat weight folders against the expected manifests, the developer's chat template, the key through `vllm.env`, model-guard in the path, the memory limits, 16 calls in flight, the start order, the systemd units | One run on the cloud GPU: build a real bundle (real weights, gates passed), `box-install.sh` on a clean Ubuntu 24.04 image, capture the record from the compose containers, canary, a 50,000-patient SCREEN. Then the same on the first physical box (tests G-1, G-2, P-1) | NEW-HW-1 "product-on-GPU run: bundle, box-install, record, canary, screen" (L); T-213b covers the drills | Go-live both; PoC |
| HW-002 | Blocker | A PRODUCTION box cannot start the embed service, so `docker compose up --wait` in `install.sh` fails. The service refuses `hash` in PRODUCTION, refuses `model` without a pin for `e-embed-1`, the installer never pins an embedder, the registry build has no repository, revision or manifest, and the image has neither `torch` nor `sentence-transformers` | By a run: `service_embedder({"TB_ENV":"PRODUCTION","TB_EMBED_MODE":"model"})` → "no pin for e-embed-1 … refused"; `…"hash"` → "refused in PRODUCTION"; `find_spec("sentence_transformers")` → None; `grep -i 'torch\|sentence' deploy/requirements.lock` → nothing; `services/embed_service/app.py:42-43` (fails at import); `models/registry.yaml:587-601`; `tools/rehearse_box/standins.yml:35-37` (the rehearsal overrides to `hash`) | No site install completes. The rehearsal is green because it overrides the one setting that fails | Decide now, not "after G1": either (a) the embedder is not part of release 1: the service is not in the box's file set while `vec.s2b` is off, and nothing refuses; or (b) choose the embedder, fill the registry row, build the ML image from a second hashed lock, pin it in `install.sh` with the pair, measure it (G-8). The rehearsal must run with the product's setting | T-607 remainder + T-DEP-4 (`trialbox-ml`); else NEW-HW-2 "embed service optional in the box file set" (S) | Go-live both; PoC |
| HW-003 | Blocker | No path makes the pair `champion` on a site box, so a PRODUCTION box screens no note. `install.sh` pins `candidate`; the gateway refuses it; `pin_model --promote` needs a passing qualification record; no record exists in the tree, none ships in the bundle, neither installer promotes, and `eval qualify` needs a clean development checkout, three evidence files at the same commit, public data sets and a TEST gateway | `deploy/install.sh:313-333`; `ls eval/qualification/` → README, layouts, probes only; `docs/runbook/11-qualify.md` "Before the run"; `tools/trialbox/doctor.py:353-354` and `judge_route` (FAIL in PRODUCTION); `box-install.sh` has no promote step (`grep promote`) | The installer ends with a FAIL list and a stack that answers only structured criteria. A field engineer has no documented way forward | The vendor qualifies each (profile, weight manifest, vLLM digest, prompt set) once on the same card type and ships the record in the bundle's host tree. `install.sh` promotes when the pinned manifests equal the record's and the on-box canary passes. A different driver or card edition is a WARN that asks for a capture, as `host_match` does on the platform | T-012 / T-114 add; NEW-HW-3 "ship the qualification record; install promotes on manifest match + canary" (M) | Go-live both; PoC |
| HW-004 | High | The judge's weights cannot pass both the pin and the licence step. `qualify` fails a build whose weight folder has no licence file. The judge's source has none (`licence_file: none-in-source`), and its expected manifest is the digest of every visible file of that source. Adding the licence text (which the register row's obligation asks for) changes the manifest, and `pin_model` then refuses the folder | `tools/qualify.py:138, 470-479`; `models/registry.yaml:124-133`; `tools/pin_model.py:107-125` (`weight_manifest` hashes all visible files); `docs/licences/register.csv` row `model-gemma-4-26b-a4b-nvfp4` ("keep the licence text and any NOTICE with the weights") | The first real qualification fails on step `licence` for the judge, after the GPU hours are spent | In `step_licence`, a build whose registry `provenance.licence_file` is `none-in-source` is checked against the register row's text (row must be `cleared` and hold the URL and revision), not against a file in the folder. Ship the licence text beside the folder, outside the manifest (as the chat template is) | NEW-HW-4 (S) | PoC |
| HW-005 | High | The judge's accuracy evidence was taken with another chat template than the product starts. The measured record and G1 used the template inside the NVFP4 folder (sha256 `94899c0f…`). Compose now passes `--chat-template` with the developer's file, whose sha256 in the registry is `null` (trusted at first use), which is placed by hand and is in no manifest | `deploy/measured/serving_config.rtxpro6000.json` (`extra_args` have no `--chat-template`; file list holds `chat_template.jinja 94899c0f…`); `deploy/docker-compose.rtxpro6000.yml:66`; `models/registry.yaml:134-138` | The canary result (53/54 judge) and G1's "no false exclusion" may not hold for the template the box serves; a wrong or missing file stops the judge at start | Fetch the developer's template once, write its sha256 in the registry, compare it with the folder's. If identical, drop the flag. If not, re-run the canary and one G1 hospital part with it before anything else is measured (G-1) | T-674 remainder; NEW-HW-5 (S) | PoC |
| HW-006 | High | The only measured throughput is at one model call at a time, and no run records tokens per second, call latency or GPU utilisation. The G1 harness does not run compose and never sets `TB_SCREEN_LLM_CONCURRENCY`; the default is 1. The product's path, 16 calls in flight with guided decoding on both servers, has not run on a GPU | `grep -rn SCREEN_LLM_CONCURRENCY` (compose files, `config.py`, `screen_cascade.py:332`, tests only); `hospital-ja.json` holds seconds and `model_calls` only; `gpu_peak.json` holds memory only | T-734's capacity statement has no basis; the hardware choice "from measured numbers" (OD-11) cannot be made; the box may be several times faster than G1 says, or the batch path may fail | The harness sets the concurrency from the serving record's `max_num_seqs`; every GPU run scrapes vLLM's `/metrics` (prompt and generation tokens, time to first token, queue time, running and waiting requests) and `nvidia-smi` utilisation every 10 s into the run folder (G-3) | T-734 / T-667 add; NEW-HW-6 (S) | PoC |
| HW-007 | High | A 500,000-patient site does not fit a night on any single card in the list if the night re-screens everyone: 24 to 26 h per trial at the measured speed, and at best 2.4 h per trial if batching gives ten times. The fixed call budget of 20,000 per run stops a 500,000-patient screen (33,000 to 67,000 calls) before the hardware does | §4.3; `screen_cascade.py:315` | A large site gets a cut list or a night that ends after the morning mail | The night is incremental by design (changed patients, new or changed trials); a new trial is a scheduled backfill; the budget is derived from the measured calls per hour and the window; the capacity statement says how many patients and trials a night this box carries | T-734, T-687; the scale review owns the limit | Go-live both |
| HW-008 | High | The DGX Spark is not a product form today. (a) No measurement: every field of `gb10-profile.yaml` is `null`. (b) `box-install.sh` plans `--gpu gb10`, and `install.sh` then stops: no serving record, and nothing in the box path sets the trial-boot switch. (c) No arm64 bundle can be made: `make_bundle.sh` saves the build host's architecture. (d) `TB_EMBED_DEVICE=cuda` is set but the embed service has no GPU reservation. (e) The stack's start wait is 900 s while the two servers start one after the other with start periods of 600 s and 900 s. (f) Whether card memory counts against the 42 GiB container limit is unknown. (g) The driver rule (exactly 580.142) is unverified and blocks the vendor's updates. (h) `check_host` needs LUKS under Docker's root; no procedure says how on the Spark's system | (a) `deploy/gb10-profile.yaml:12-14`; (b) run: `box plan` → `install-args: --mode gpu --gpu gb10`, `install.sh:349-353`; (c) `tools/make_bundle.sh:114` (`docker save`, no platform argument anywhere in the script); (d) rendered config: no `deploy.resources` on `embed-service`; (e) `deploy/systemd/trialbox.service`, `docker-compose.gb10.yml` health checks, `install.sh:454`; (f) `gb10-profile.yaml:35-37`; (g) `check_host.sh:247`; (h) `check_host.sh:119-135` | Japan cannot be promised a Spark. A Spark bought now is a bench unit | Say so in the plan: the Spark is not a go-live form. If the owner wants the comparison (T-734's hardware note), buy one bench Spark and run S-1 to S-6; the arm64 bundle and the eight points above are then one card | T-214 (existing, re-opened); NEW-HW-7 "arm64 bundle and the Spark install path" (M) | Later (Go-live JP only if a Spark is chosen) |
| HW-009 | High | The CGMH B200 form is still undefined and unmeasured: the platform kind is unknown, the compose form has no installer, no backup, no update and no restart after a re-partition, G1b has not run, and the plan (v6.1) no longer extends this form. Two plans are alive for one site | `docs/plan/measurements/b200-g1b/G1b.md` ("not run"); `install.sh:160-161`; `docker-compose.shared-quota.yml:8-9`; v6.1 §3.6 | Work continues on two forms; CGMH's go-live date has no hardware decision behind it | Decide: CGMH gets the P-PRO6000 box. Keep the owner's B200 for G1b as a bench (it also gives the only second-card number). Re-open the shared host only on CGMH's written requirement with the platform named | T-739, T-114 (bench only); plan change | Go-live TW |
| HW-010 | High | The box form has no disk-unlock design that both passes the host check and restarts without a person. The check FAILs a disk the TPM alone opens; it passes a Tang binding (a hospital key server the box form does not have: `TANG_URLS=""` in the box's `hardening.conf`) or a passphrase or PIN at every boot (WARN). `box-install.sh` neither sets up nor checks encryption before it installs; the result appears only in the final host check | `deploy/hardening/luks_policy.py:6-14`; run: `box plan` writes `TANG_URLS=""`, `KEK_BACKEND=tpm`; `box-install.sh` (no LUKS step); `check_host.sh:119-141` | After a power cut or an unattended update with a reboot the box waits at a prompt and sends no morning mail and no alert; or the site binds the disk to the TPM alone and fails the check it was told to pass. OD-16 ("the box looks after itself") does not hold | A decision record with one of: (a) a person types a PIN after every restart, said plainly in the handbook, with a UPS and the reboot of an update moved to a time the owner chooses; (b) a small key server on a second device in the same room (the backup disk's host); (c) TPM-only unlock accepted for the box form with the data volume's keys sealed under the owner's passphrase. Then make `box plan`, `check_host` and the handbook say the same, and check encryption in `box-install` step 1 | NEW-HW-8 "disk unlock for the box form: decision and check" (M) | Go-live both |
| HW-011 | Medium | On the product box the memory plan shrinks every service because it counts 96 GiB of model-server limits that this profile never uses. With 125.6 GiB the plan sets the caps to 0.79 of the defaults: database 3,251 MiB, FHIR store 4,064 MiB with a 3 GiB heap, lake 6,502 MiB. A 64 GB workstation is refused ("needs at least 79 GiB"), and runbook 10 says 64 GB is enough for the 5090 | By a run of `tools.box plan` (§6.1); `tools/box/plan.py:214-256`; `docker-compose.rtxpro6000.yml:60,75` (48 GiB each, the sleeping-model figure); `docker-compose.yml:128-131` | The JVM can be killed at its limit under load on the very box we sell; the database gets less memory on a 128 GB machine than on the default | The model servers' limit per profile comes from their measured resident memory (G-2) and is taken off the top; services are never shrunk below their defaults while RAM allows; a JVM limit is never set below heap + a measured margin | NEW-HW-9 (S), after G-2 | Go-live both |
| HW-012 | High | The installation cannot be followed from the documents. Runbook 01 describes `install.sh` with tiers and Windows; `OFFLINE-MEDIA.md` is the Windows/WSL2 layout with a Windows NVIDIA driver and no Linux driver; `box-install.sh` (the v6.1 form) appears in neither. Steps 1 to 7 of §6 (firmware, OS, encryption, driver, Docker, network, media copy) have no script, and the NVIDIA driver is outside every bundle and every update | `docs/runbook/01-install-a-new-site.md:1-45`; `docs/handover/OFFLINE-MEDIA.md:3-22`; `grep box-install docs/runbook` (only 16 mentions the rehearsal) | Two site installs in April and May 2027 depend on steps nobody has written or rehearsed on hardware | T-735 as planned, plus one `deploy/box-prepare.sh` that installs the media's packages (driver, toolkit, Docker, nftables, clevis, cron), holds the driver, checks Secure Boot, TPM, LUKS and the time source, and prints what remains; a Linux media layout; one rehearsal on a rental workstation from a wiped disk | T-735; NEW-HW-10 "box-prepare.sh and the Linux media layout" (M); T-213b | Go-live both |
| HW-013 | High | A runbook tells the site that the default pair has no PRC-origin model, and it has one. Runbook 08: "A `public_agency: true` site needs non-PRC builds for every role; the default pair qualifies." The verifier is `origin: {developer: Alibaba Qwen, country: CN, non_prc: false}`. No code reads `public_agency` or `non_prc` (they only print on the model card). The embedder first in line (bge-m3) is also of PRC origin | `docs/runbook/08-dgx-spark-end-to-end.md:49`; `models/registry.yaml:172`; `grep -rn "non_prc\|public_agency" services tools libs` → `registry.py:501,519` only; `docs/licences/register.csv` row `model-bge-m3` | A false statement in a document handed to a Taiwanese hospital; if the site's security office asks, the verifier has no qualified replacement | Correct the sentence today. Ask each site the origin question in the survey. Keep one non-PRC verifier candidate measured on the card (the bake-off slot S4 of the GPU ledger) so that a "no" does not move the go-live | NEW-HW-11 (S doc) + GPU ledger S4 | Go-live TW |
| HW-014 | Medium | Three profiles fit with no real headroom, by the memory model that reproduces both measurements: the 5090 (under 2 GiB free with the sleeper), the 24 GB path (KV cache for one 8k sequence where four are configured) and the small MIG layout (judge about 1 GiB free at 0.9). None is measured on its card | §3.1; `fit.json`; `b200-layouts.json` | A desktop session on the card, a vLLM release with a larger fixed part, or a slightly smaller MIG instance than assumed stops the server at start | Judge utilisation 0.85 on `2g.45gb`; the 5090 and 24 GB paths parked; the serving record gains `used_mib` per server so the fixed part is tracked across vLLM releases | T-114 (layout file); NEW-HW-12 (S) | Go-live TW if the B200 is used; else Later |
| HW-015 | Medium | Start and wait limits are fixed numbers, not derived from the hardware: `--wait-timeout 900` and `TimeoutStartSec=1200` in `trialbox.service`, `TB_INSTALL_UP_TIMEOUT` 900, health start periods 300 / 600 / 900 s. Measured readiness on the PRO 6000 is 62 to 117 s per model; nothing is measured on the Spark, where two serial loads can pass 900 s | `deploy/systemd/trialbox.service`; `install.sh:454`; compose health checks; `fit.json` `seconds_to_ready` | On a slow-loading form the box fails its own boot and the egress re-apply step after it never runs | Record `seconds_to_ready` per server in the serving record and write the waits from it with a stated factor (OD-10: a setting with a reason) | NEW-HW-13 (S) | Later (Spark); cheap for both |
| HW-016 | Medium | Dead and marginal installer paths. Any NVIDIA card that is not on the list becomes `default`: the base server command names `qwen3.5-35b-a3b-q4`, which no bundle carries and no pair pins, so the install loads everything and then fails at the stack start. Any aarch64 host becomes `gb10`. `rtx4090` reuses the 5090 file with the start helpers that depend on a verifier scaled to zero. `install.sh:356` writes `TB_PROFILE=P-GB10` for `default` and for stub boxes | run: `gpu_profile.sh` → `default` for RTX 6000 Ada, RTX PRO 5000, H100, A6000; `gb10` for "NVIDIA Thor"; `docker-compose.yml:366-370`; `install.sh:356, 409` | A field engineer with a near-miss card loses an hour to a failure with no message about the card | `install.sh` treats an unlisted card as `box plan` already does: `--mode stub` with one clear line. Delete `default` and `rtx4090` | NEW-HW-14 (S) | Later |
| HW-017 | Medium | The vLLM image is frozen with 29 fixable HIGH or CRITICAL findings, accepted through dated entries that lapse on 2026-12-10, and moving it is a model change that needs a new record, canary, qualification and G1 on every card. The plan has no slot for one uplift before the release, and the GPU ledger's S6 (G1 re-run on the release) is on 2027-03-01 | `deploy/security/known-image-findings.md`; `images.lock` `checked`; `docs/plan/gpu-ledger.md` | Either the gate blocks every bundle after 12-10 until someone re-dates 81 entries, or the release ships a known-vulnerable image, or an unplanned uplift lands late | One planned uplift in January with the measurement set of §8 (a); the allow-list re-dated once with that date as the reason | T-677 follow-up; GPU ledger row | Go-live both |
| HW-018 | Medium | Go-live acceptance has no hardware or capacity criterion and no Japan line: `tools/acceptance.py` checks ingest, feasibility, screening agreement, NAV, TWPAS, reproduction and the audit. Nothing checks that the site's night fits the window on the site's data, that the box comes back after a power cut, or that the card holds a night at temperature | `tools/acceptance.py --help` (run); `docs/runbook/06-go-live-acceptance.md` | A box can pass acceptance and miss its first morning mail | Add `capacity` (reads the night's job times against `schedule` and the mail time) and `powercycle` (reads the watchdog and start records) to the acceptance tool; mark `nav` and `twpas` as Taiwan criteria and name Japan's | NEW-HW-15 (S); T-734 | Go-live both |
| HW-019 | Low | `tools/b200_qualify.sh` turns MIG on for GPU 0, deletes every compute and GPU instance on it and creates its own, after one question; it does not check a pending MIG mode (a card that needs a reset) or what else is on the machine's other cards, and capture and qualify failures are swallowed (`|| true`) until the record step | `tools/b200_qualify.sh:109-112, 124, 135` | On the owner's machine only; a failed partition stops the script under `set -e` with MIG half set | Check `mig.mode.pending`; print what runs on GPU 0 before the question; fail a layout when the capture fails | T-114 | Later |
| HW-020 | Low | Stale hardware statements. `deploy/settings.example.yaml:29` names `qwen3.5-35b-a3b-q4`, `gpt-oss-120b-mxfp4`, `bge-m3`. `tools/gpu_sizing.py` prints gpt-oss-120b for the PRO 6000 and the Spark and "nothing measured on a device". Runbook 08 asks for amd64 emulation for MailHog, which is gone. Runbook 10 says "after a host reboot run compose up again", which the systemd unit now does. `services/gateway/load.py:25` `SLOTS = 16` is the PRO 6000's figure used for every profile without a record. `tools/spark_e2e.sh:59-61` starts a file set that is not the product's (no secrets, identity or box file) | files named | Wrong expectations at a site; a Spark test that passes on another assembly | Fix with the documents of T-735; replace `gpu_sizing` with the capacity statement | T-735; LLM-026 | Later |

### 7.1 Details

**HW-001.** Differences between what was measured and what ships, each read from the files:

| | Measured (G1, the record) | Ships |
| --- | --- | --- |
| vLLM start | `docker run … --model nvidia/Gemma-4-26B-A4B-NVFP4` from `/models/hub/…/snapshots/<rev>` | compose, `--model=/models/gemma-4-26b-a4b-it-4bit` (a flat folder) |
| Chat template | the NVFP4 folder's | `--chat-template=/models/chat-templates/…` |
| Key | `--api-key` on the command line; nginx adds the header | `VLLM_API_KEY` from `secrets/model/vllm.env`; model-guard in front |
| Services | a venv on the VM, one process tree | containers with memory and pid limits, read-only root, per-service database roles |
| Model calls in flight | 1 | 16 |
| Weight pins | synthetic | the release's manifests, `candidate` until promoted |
| Host | 48 vCPU, about 180 GB RAM, Server Edition card, driver 580.178.04 | a workstation, 128 GB, Workstation Edition card |

**HW-003.** A possible objection is that a site should qualify its own box. It cannot: the evidence steps need the
TREC and MedTxt data, a development checkout at a clean commit and hours of GPU time before the box may answer its
first note question. What differs between the vendor's card and the site's (driver build, card edition, host) is what
the serving record and the canary already compare.

**HW-010.** The KEK for the site keys is sealed to the TPM (`KEK_BACKEND=tpm`), which also opens by itself on the
same board. So with a TPM-only disk the whole chain opens with no person; with a passphrase disk the KEK's TPM seal
adds nothing a thief with the running box lacks. The decision should treat the disk and the KEK as one question.

## 8. What must be measured on real hardware

Thresholds come from the window W (site `schedule.ingest` to the morning mail, 5 h in the example settings) and the
usable part U = 0.7 × W less the measured ingest and backup time. No other limit is proposed.

### 8.1 (a) The cloud GPU VM (one RTX PRO 6000; for the cloud-run session)

Run in this order; each needs the one before it.

| # | Test | Command and inputs | Record | Pass |
| --- | --- | --- | --- | --- |
| G-1 | Chat template identity | fetch `google/gemma-4-26B-A4B-it` `chat_template.jinja` at the registry's revision; `sha256sum` it and the NVFP4 folder's; render one judge prompt with each (`vllm` `/tokenize` or the tokenizer) | both sha256, token ids equal or not | identical → drop `--chat-template`; different → every later test uses the developer's file and the canary is re-run first |
| G-2 | The product on the card | build a real bundle (`make release-bundle` with `--models deploy/models`); on a clean Ubuntu 24.04 image: `sudo deploy/box-install.sh <bundle> --yes`; then `python3 tools/serving_config.py capture --container judge=trialbox-llm-service-1 --container verifier=trialbox-llm-verifier-1 --models-dir deploy/models --out deploy/site/serving_config.rtxpro6000.json`; `docker stats --no-stream` | install wall time per step; `seconds_to_ready` per server; card memory per server; **host resident memory of each vLLM container**; every FAIL line | the installer exits 0 after HW-002 to HW-004 are fixed; `serving_config measured rtxpro6000` passes on the captured record; card memory within 1 GiB of 62.6 GiB |
| G-3 | Throughput against sequences | the 5,000-patient synthetic hospital, one trial, SCREEN through the box's gateway with `JUDGE_MAX_SEQS` = `VERIFIER_MAX_SEQS` = 1, 8, 16, 32, 48 (restart the servers each time); scrape `http://llm-service-vllm:8000/metrics` and `nvidia-smi --query-gpu=utilization.gpu,memory.used,temperature.gpu,power.draw` every 10 s | per setting: wall seconds of the SCREEN, note-stage patients, model calls, prompt and generation tokens per second per server, p50 and p95 call time, queue time, GPU utilisation, the candidate list's hash | the candidate list is identical at every setting; choose the highest setting whose throughput still rises; state calls per hour = the capacity figure |
| G-4 | Eager and guided decoding | at the chosen setting: 200 judge calls from the canary set, four ways: with and without `--enforce-eager`, with and without `response_format` | tokens per second, p95, card memory outside the budget, schema-valid rate | answers equal (same verdicts); keep a change only if throughput rises by more than the run-to-run spread of three repeats |
| G-5 | Prefix cache | 50 note-stage patients × all criteria, judge only, as today and with the excerpts first (a scratch prompt version, DEV) | vLLM's prefix-cache hit counters, prompt tokens per second, verdict agreement between the two orders | report only; a prompt change goes through the prompt registry |
| G-6 | The 50,000-patient night on the product | G1's hospital-ja and hospital-zh-TW parts against the installed box at the chosen setting | SCREEN wall time, ingest wall time, backup wall time, calls, tokens per second, peak card and host memory | ingest + one trial's SCREEN + backup ≤ U; report trials per night = floor((U − ingest − backup) / SCREEN) |
| G-7 | Protocol reading under load | 6 protocol extractions (32k context) started together while a SCREEN runs | each call's time, any 400 or timeout, KV cache usage | none refused; SCREEN's time rises by no more than the extraction's own share (report it) |
| G-8 | Embedder (only if kept, HW-002) | the chosen embedder on the CPU and on the card; the 50,000-patient lake's note chunks | chunks per second, card memory, the nightly increment's time | the increment fits U beside G-6 |
| G-9 | Power cycle | `sudo systemctl reboot` and a hard stop of the VM during a SCREEN | time from boot to both servers healthy, the canary after start, the job's state after restart | the box returns without a person; the interrupted job is failed or resumed, never silently done |
| G-10 | 24 GB of evidence per night | 3 consecutive nights of G-6 with the nightly canary | canary flips per night, any weights-changed flag, log volume per night | no unrecovered failure; log volume × retention fits the disk |

### 8.2 (b) The owner's hardware

**RTX PRO 6000 box (the product, the first physical unit).**

| # | Test | Command | Record | Pass |
| --- | --- | --- | --- | --- |
| P-1 | Install from a wiped disk, by the written procedure, by someone who did not write it | §6 steps 1 to 15 with a stopwatch | time per step, every deviation | no step needs a command that is not in the document |
| P-2 | Serving record on this edition and host | the capture command of G-2 | card name, driver, memory per server | within 1 GiB of the cloud record; differences listed |
| P-3 | Throughput | G-3 at the chosen setting and one below | as G-3 | within the spread of G-3, else this box's figure replaces it in the capacity statement |
| P-4 | Thermal and power soak | G-6 twice back to back with the case closed in the room it will live in; `nvidia-smi --query-gpu=temperature.gpu,power.draw,clocks_throttle_reasons.active --format=csv -l 10`; a power meter on the plug | peak temperature, any throttle reason, wall watts, tokens per second in the last hour against the first | no throttle; last-hour throughput equal to the first within the spread; wall power below 80 % of the circuit |
| P-5 | Power cut | pull the plug during a SCREEN and at idle; with the UPS: the shutdown path | as G-9, plus the disk-unlock step's behaviour (HW-010) | as the decision record of HW-010 says |
| P-6 | Noise | a phone meter at 1 m during P-4 | dBA | reported to the site for the room choice |

**DGX Spark (bench, only if bought).**

| # | Test | Command | Record | Pass |
| --- | --- | --- | --- | --- |
| S-1 | The image runs | on the system's shipped driver: `sh deploy/check_host.sh --gpu-only --gb10` (expect the driver FAIL), then start the judge alone with the profile's flags | starts or the error; the driver build | decides whether the hold stays |
| S-2 | Memory accounting | both servers up; `docker stats`, `nvidia-smi`, `/proc/meminfo`, each container's `memory.current` | whether card memory is charged to the container; `unified_memory_measured_gib`; each `measured_peak_gib` | every service under its limit with the pair loaded; fills `gb10-profile.yaml` |
| S-3 | Throughput | G-3 with 1, 4, 8 sequences | as G-3 | the 50,000-patient figure: ingest + SCREEN + backup ≤ U, else the Spark is a "small site" form with the measured patient count |
| S-4 | Load time and boot | cold boot, time to both healthy | seconds per server | feeds HW-015 |
| S-5 | Sustained load | S-3's SCREEN looped for 5 h | throughput per hour, temperature, throttle | last hour equals the first within the spread |
| S-6 | Context | G1 scenarios at 16k against the 32k record | candidate sets | identical (the profile's own gate `context`) |

**The owner's B200 with MIG (bench; CGMH only if required).**

| # | Test | Command | Record | Pass |
| --- | --- | --- | --- | --- |
| B-1 | Instance sizes | `nvidia-smi mig -lgip`; after `-cgi 2g.45gb,1g.23gb -C`: `nvidia-smi -L`, `nvidia-smi --query-gpu=memory.total` per instance | the exact MiB of each profile | feeds B-2 |
| B-2 | Fit | `sudo tools/b200_qualify.sh --bundle … --operator …` with the judge at 0.85 and at 0.9 on `2g.45gb` | starts or not; memory per instance; KV tokens from the server log | starts with at least the fixed part (3.2 GiB) free |
| B-3 | Throughput per layout | G-3 with the layout's sequences, both layouts | as G-3, per layout | calls per hour per slice; the CGMH request names the layout whose 50,000-patient night fits U |
| B-4 | Neighbour | `python -m tools.trialbox.noisy_neighbour --url … --model judge --out noisy-neighbour.json` (T-319) with a load on the other slices | throughput with and without the neighbour | report the loss; the capacity statement uses the loaded figure |
| B-5 | Re-partition and reboot | reboot the host; re-create the instances | whether the instance UUIDs are the same; what the stack does | the restart procedure is written from what happened |

## 9. What to drop or simplify

| Item | Why | Do |
| --- | --- | --- |
| `rtx4090` profile and the `default` profile | unmeasured, marginal or dead; no site uses them (HW-014, HW-016) | delete; unknown card → stub with a message |
| `deploy/topology_a/podman-compose.yml` | referenced by nothing in the Makefile, tools or tests | delete |
| The base file's `llm-service` command (`qwen3.5-35b-a3b-q4`, 64 sequences, 0.85) | a model no build pins | make the base server carry no command; a profile file is required |
| Tiers (`small`, `medium`, `large`) beside GPU profiles | two names for one choice; `box-install` does not use tiers | keep the profile names only |
| `deploy/windows/`, `WINDOWS-INSTALL-CHECKLIST.md`, the Windows media layout | v6.1: not the box's path | move out of the release path; keep in a parked folder |
| `docker-compose.rtx5090.yml`, sleep swap, `judge-sleep-init` and friends, `services/gateway/swap.py` in the product path | no site uses it; the answers after a wake were never captured; it adds a hold, a busy state and three helper containers | park until a site orders a 32 GB box; the product sets `TB_MODEL_SWAP=off` |
| `deploy/two-device/` and `tools/two_device.py` (650 lines) | a form for a device that is not measured as one device yet | park with the Spark |
| `docker-compose.shared-quota.yml` (the compose form on a shared host) | no installer, no day 2; the Kubernetes form has both | keep only as the bench file of `b200_qualify.sh`, say so in its header |
| `tools/gpu_sizing.py` | estimates for models we do not ship | replace by the capacity statement from G-3 and G-6 |
| `--chat-template` | if G-1 shows the files are identical | drop the flag and the hand-placed file |

## 10. What the plan must change (inputs to plan v7)

| # | Task | Size | Depends on | Order |
| --- | --- | --- | --- | --- |
| 1 | Decide the hardware: P-PRO6000 box for both sites; Spark and B200 are bench; record it as a decision and remove the tier table from the runbook | S | none | first |
| 2 | Embedder in or out of release 1 (HW-002); if in: choice, registry row, ML image, pin step | S (out) / L (in) | 1 | first |
| 3 | G-1 chat template identity, then fix the registry `sha256` (HW-005) | S | cloud GPU, minutes | before any other GPU run |
| 4 | Licence step for `none-in-source` builds (HW-004) | S | none | before the first qualification |
| 5 | Harness concurrency and metrics capture (HW-006) | S | none | before G-3 |
| 6 | Product-on-GPU run G-2 (HW-001): needs a real bundle, so the release gates must pass on real images once | L | 2, 3, 4 | December, replaces GPU ledger row S2a as the next G1 attempt |
| 7 | Vendor qualification record shipped and promoted at install (HW-003) | M | 4, 6 | with 6 |
| 8 | G-3 to G-7: the capacity figure; T-734 written from it; the incremental night stated (HW-007) | M + the GPU hours (about 12) | 5, 6 | after 6 |
| 9 | Disk-unlock decision for the box form and its check (HW-010) | M | 1 | before the hardware order |
| 10 | `box-prepare.sh`, the Linux media layout, the owner's handbook (HW-012, T-735) | M | 1, 9 | before the rental-workstation rehearsal |
| 11 | Order one P-PRO6000 workstation now (lead time); P-1 to P-6 on it | hardware + M | 1 | tests in January and February |
| 12 | Memory plan from measured resident memory (HW-011); start waits from the record (HW-015) | S + S | 6 | after 6 |
| 13 | One vLLM uplift with the full measurement set (HW-017) | M + GPU hours | 6, 8 | January; then freeze to go-live |
| 14 | Acceptance: `capacity` and `powercycle` criteria; Japan's lines (HW-018) | S | 8 | before G3 |
| 15 | Origin statement corrected; a non-PRC verifier candidate measured in ledger slot S4 (HW-013) | S + GPU hours | none | December |
| 16 | G1b on the owner's B200 with the 0.85 judge layout (B-1 to B-5), as a bench result, not a go-live dependency | M | 4, 7 | when the owner has time |

Remove from the critical path: T-214 (Spark), the shared-host cards for CGMH, the Windows cards.

## 11. Needs GCP / owner hardware

The exact tests are §8: G-1 to G-10 on the cloud GPU VM (start with G-1, G-2, G-3); P-1 to P-6 on the first
RTX PRO 6000 box; S-1 to S-6 on a bench Spark if one is bought; B-1 to B-5 on the owner's B200. Each row names the
command, the inputs, what to record and the pass rule derived from the night window.

## 12. Small certain fixes (High or worse)

| Finding | File:line | Change | Test that fails first |
| --- | --- | --- | --- |
| HW-004 | `tools/qualify.py:470-479` | when the build's registry `provenance.licence_file == "none-in-source"`, do not require a file in the folder: require the register row (`reg`) to exist, be `cleared` and name a source URL and revision; set `row["file"] = "none in source (register row)"` | a new case in the qualify unit tests: a judge build with `none-in-source` and a folder without a licence file must pass step `licence`; today it returns "no licence file in the weight folder" |
| HW-006 | `tools/complete_run.py` (where the hospital part builds its environment) | set `TB_SCREEN_LLM_CONCURRENCY` from the serving record's `max_num_seqs` (fall back to 16, the record's value, with the source in the report); print it in the report header | a unit test that the part's environment holds the variable; today `llm_concurrency(os.environ)` is 1 in the harness |
| HW-013 | `docs/runbook/08-dgx-spark-end-to-end.md:49` | replace the sentence by: "The default verifier is of PRC origin (`models/registry.yaml`, `non_prc: false`). A site that may not run such a build needs another verifier, qualified on its card; none is qualified yet." | `tools/doclint.py` has no rule; add one line to the registry test: a document may not say "the default pair qualifies" while any deployed build has `non_prc: false` |
| HW-008 (d) | `deploy/docker-compose.gb10.yml:130-134` | remove `TB_EMBED_DEVICE: ${TB_EMBED_DEVICE:-cuda}` (the service has no GPU device), or add the same `deploy.resources.reservations.devices` block the model servers have | `tests/unit/test_two_device_config.py` style check: a service with `TB_EMBED_DEVICE=cuda` in the rendered config must have a GPU reservation |
| HW-002 (rehearsal) | `tools/rehearse_box/standins.yml:35-37` | remove the `TB_EMBED_MODE: hash` override once the product decision is made, so the rehearsal fails the way a site would | `make rehearse-box` step `install` |

## 13. What is good

- The weight chain is real now: expected manifests in the registry, refusal of other files (proved by a run), a
  nightly re-hash with a flag the gateway obeys, one digest list for images, and a host check of the driver and the
  card against the image before anything is loaded.
- The installer is careful: signed bundle verified before anything changes, the install continues from the signed
  tree, nothing is pulled, the tier and serving-record rules refuse an unmeasured card with a message that says how
  to get a record.
- The shared-quota file has no default for any serving value; compose refuses to start until each is measured.
- `gb10-profile.yaml` is honest: every unmeasured number is `null` and a test keeps it so.
- The memory model from two small measurements predicts both to within 60 MiB; the RTX PRO 6000 profile has real
  room (33 GiB).
- All 35 shell scripts parse; the dry-run and check modes that exist behave as their headers say.

## 14. What was not checked

- Nothing ran on a GPU, a Spark, a B200, a TPM, LUKS or systemd. The Docker daemon is not running here: no image was
  built, no bundle was made, `make rehearse-box` was not run, image sizes are the documents' figures.
- The power, noise, ECC and supply facts of §3.2 are from public vendor data as remembered, not from a document in
  the tree; verify each on the unit.
- Whether `compose up --wait` exits non-zero for the embed service was concluded from the service's import-time
  refusal and the compose file, not from a run.
- Whether vLLM v0.32.0's arm64 image works on the GB10, and whether the driver rule is right, cannot be told here.
- The MIG instance sizes in MiB for a B200 are assumed from the profile names (23, 45, 90 GB).
- `tools/qualify.py` was read for the licence step only; the other steps, the prompts and the gateway are the LLM
  reviewer's. Backup, update and restore are the operations reviewer's.
- The Kubernetes manifests under `deploy/platform/` were not rendered or applied.
- `shellcheck` is not installed; only syntax was checked.
