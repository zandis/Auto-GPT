# Root review 10: architecture and engineering quality, and whether plan 9's product is good enough (lane J, job B-10, 2026-11-17)

**Reader:** the owner first (the one-page summary), then the builders (sections 2 to 6), then plan 9's next revision
(the cards of section 7 and the decisions of section 8).

**The owner's questions.** "From a software-engineering point of view, how to optimize architecture and overall
quality." "Not loose function connection but a good integrated system." "For plan 9, is it good enough at the present
version as a product? Anything can be hardened?"

**What was analysed:** master `8778394f0` (train 79): `services/*`, `libs/*`, `tools/*`, `deploy/` (compose files,
installer, bundle, update, backup), the eight workflows in `.github/workflows/`, `Makefile`, `pyproject.toml`, the
test tree, `docs/decisions/`, `docs/runbook/`. Small scripts of this session read the code (section 1); nothing was
installed, no suite was run, no image was built. Public and synthetic data only.

**What this page adds.** Root review 01 (sections 4, 5 and 7) listed the coupling and quality findings, plan 9 (band
4d and 4g) turned them into cards. This page does not repeat them: it cites 01's ids (B1-C1, B1-Q1, ...) and plan
9's cards (9d-1, 9g-13, ...) and adds the measurements behind a target architecture, a quality system, a hardening
list and a verdict on the product.

**How every claim is marked.**

| Mark | Meaning |
| --- | --- |
| **[M n]** | Measured: row n of section 1 gives the command and the number |
| **[R]** | Read: the file and line follow in backticks |
| **[S]** | Source: a public link follows |
| **[O]** | Opinion: the analyst's judgement, to be argued with |
| **not verified** | Could not be checked here; section 9 lists each |

---

## Summary (one page, plain words)

**The parts are well made; the system is one tangle with many careful rules around it.** [O] Twenty-seven folders
under `services/` look like twenty-seven services, but only eleven of them run as a process of their own; the rest
are libraries that the console and the orchestrator load into themselves [M 5]. Fifteen of those folders import one
another in a single loop: from any one of them, Python can reach twenty others [M 1]. That is why a narrow test run
misses what the full suite catches (lane J saw it twice today), why each change needs two or three rounds of review,
and why "switch a module off" is not possible without a refactor. [O]

**What is good enough today** [O, from the marked rows below]: strict typing everywhere, no TODO left in the code,
high line coverage (88 to 98 % per service, held by a ratchet), a careful audit chain with one writer, a signed
offline bundle with supply-chain gates, update and backup drills every night, a one-place permission matrix, and a
three-language text checker that J-1 landed. Those are better than most hospital software ships with. [O]

**What is not** [O]: the evidence that screening is accurate (no launch meets a target yet, 43 % of criteria end as
"a person decides"), the validation record (no qualification record on master since plan 8), and the EDC module (its
floor is not merged). Those three, not the code quality, decide whether a first hospital can start.

**The five changes that matter most.**

1. **Make the rules executable before adding anything.** One architecture test (which folder may import which), one
   size-and-complexity ratchet, one "no clock and no environment read outside their module" ratchet. Each lists
   today's exceptions and only lets the list shrink. Three small cards; nothing gets worse from then on. (AQ-1,
   AQ-2, AQ-8, AQ-12.)
2. **Cut the loop where it points upward.** 22 imports point against any sensible layering [M 3]; most sit in six
   groups: the orchestrator imports the console; matching, the site set-up and the deliverables import the
   orchestrator; the console imports the developer tools; the EDC and the data core import each other's private
   names. Cutting those, plus plan 9's own deletions (the `vec` store, the OMOP lake source, the v1 engine), turns
   the loop into layers. (AQ-3 to AQ-6.)
3. **One of each thing that exists twice**: one clock (102 places in the code read the time, and eight of them take the
   container's own date), one list of a person's states (five copies, two vocabularies), one list of a study's states
   (three), one job system (three schedulers and four timers), one internal client with one actor claim. (Section 2.)
4. **Run the full unit suite on every card that touches product code** until the loop is gone; then choose tests
   from the import graph. (AQ-23.)
5. **Harden the ten cheap things** of section 6.2: the legacy token, the identifier guard, the stand-in embedder,
   the eight server dates, the EDC check that differs between console and orchestrator, read-only containers, schema
   rights, migration and restore from the previous release, reconciliation counts, the health page.

**What it costs.** 34 cards: 22 S, 11 M, 1 L (section 7). Most are a day. Against that, plan 9 can wait on every one
of its six L cards and about twenty M cards until after the first hospital (section 6.3); that frees more than this
page asks. The money cost is none: no GPU, no licence, no service. [O]

---

## 1. Measurements

All commands ran from `trialbox/` of this worktree, with the system `python3` (standard library and `yaml`) or the
main checkout's `ruff`. Script sources are in the session's scratch folder; each is under 100 lines and reads only.

| # | What | Command (abridged) | Number |
| --- | --- | --- | --- |
| 1 | Import graph between packages (AST, every `import` incl. inside functions) | `graph.py .` | 27 service packages; **74** service-to-service edges; **one cycle of 15 packages** (adapter, console, criteria_compiler, datacore, edc, edc_backend, embed_service, lake, matching, omop, orchestrator, rc_bridge, rc_sim, sitesetup, vec); orchestrator imports **17** services; **16** packages reach **20** others transitively; no lib imports a service |
| 2 | Cross-service import lines | `grep -rhE "^\s*(from\|import) (svc)\b"` per package | **280**, of which **141** inside a function (lazy, hidden from a reader); ruff's `PLC0415` is ignored (`pyproject.toml` `ignore`) |
| 3 | Edges against a layering (libs < leaf < model/mail < lake/omop/vec < adapter < compiler/matching < edc/datacore < setup/deliverables < orchestrator < console) | `layers.py graph.txt` | **22** edges, **66** of the 280 statements |
| 4 | Private names imported across services | `grep "import .*\b_[a-z]"` | **7**: `lake.client._object`, `_key`; `orchestrator.scenarios.feas_compute._months_shown`; `orchestrator.reports.common._mpl_font`; `datacore.export._sub`, `_texts`; `adapter.ndjson._memory_cap` |
| 5 | Processes vs packages | compose `command:` lines | **12** Python processes (10 `uvicorn` apps, the audit drain, `model-guard`); **11** of the 27 service packages have a process; 15 compose services in `deploy/docker-compose.yml` |
| 6 | Schema rights | `access` map, `deploy/docker/db-init/30-service-roles.sh:72-84` | **28** schemas; **22** granted to two or more service roles (`app` 7, `refdata` 5, `terminology` 5, `omop` 4, `derived` 4); orchestrator 23, console 21 |
| 7 | Volumes written by several services | compose volumes parsed | `objects-data` rw by **5**; `lake-data` rw by 2 (adapter, lake); `tb-secrets` rw by 2 (adapter, orchestrator) |
| 8 | Container hardening in the main compose | `compose.py deploy` | all 15 services have memory limits and health checks; **1 of 15** `read_only`, **1** `cap_drop`, **1** `no-new-privileges` (model-guard); Python images run as uid 10001 (`deploy/docker/python.Dockerfile:17,55`) |
| 9 | Function and module size (services and libs, tests and generated excluded) | `sizes.py .` | 7,118 functions: median 8 lines, p90 30, p99 115, max 2,020; **33** over 200, **13** over 400; 522 modules: median 195, **24** over 1,000, max 2,511 (`services/console/app.py`) |
| 10 | Cyclomatic complexity | `ruff check services libs --select C901` at 10 and 30 | **276** functions over 10; **43** over 30; top: `console/app.py:492 create_app` 325, `console/home.py:287 register` 241, `console/team.py:245 register` 195, `adapter/pipeline.py:502 _run_ingest` 93. Complexity rules `PLR0912`/`PLR0915` are ignored and `C901` is not selected |
| 11 | Duplicated code (functions of 8+ lines with equal AST after names and constants are blanked) | `sizes.py .` | **12** groups, **127** lines; 6 groups span two packages (e.g. `orchestrator/i18n.py:44 detect_lang` = `tb_common/wording.py:176 text_lang`) |
| 12 | Markers | grep | TODO/FIXME/XXX/HACK **0**; `xfail` 27; skip marks 43; `pytest.skip(`/`importorskip` 98; `type: ignore` 64 in product code; `noqa` 139 |
| 13 | Test shape | `def test_` per folder | 1,006 test files, **8,977** test functions: unit 7,679, console 1,055, integration 121, e2e 42, platform 32, testbench 27, property 17, perf 2, llm 2. **39** test files time something with `perf_counter`/`time.time`/`monotonic`; 41 sleep; 63 mention PostgreSQL |
| 14 | Clock reads in product code | grep | `datetime.now(...)`/`date.today()`: **71** (`now(UTC)` 38, a zone 25, **`date.today()` 8**); `time.time()` 31; `tb_common.timeutil` used at 21 places; `today()` defined in at least 4 classes |
| 15 | Configuration reads | grep | `os.environ`/`os.getenv` outside `tb_common/config.py`: **302** in **138** files; **518** distinct `"TB_..."` names in product code |
| 16 | Schedulers and timers | grep `apscheduler`, `deploy/systemd/*.timer` | **3** APScheduler instances (`orchestrator/scheduler.py`, `datacore/optout_worker.py`, `console/timers.py`); **4** systemd timers (ops 1 min, watchdog 1 min, weights daily, egress 2 min); 202-and-poll jobs in lake, adapter and orchestrator data-ops |
| 17 | Person and study states | grep `STATES`/`STATUSES` | person: **5** definitions, 2 vocabularies (`orchestrator/candidates.py:27` = `rc_bridge/writeback.py:30`, 7 states with "contacted"; `datacore/lifecycle.py:48` = `console/lifecycle_pages.py:56`, 8 with "approached"; `console/home.py:79` maps between them); study: **3** (`channels/grammar.py:49`, `console/sitestore.py:239`, `console/notify.py:63`) |
| 18 | Authorisation | `authz_matrix.yaml`, grep | **89** actions, 7 roles, one `permit()`; **132** calls to `permit` or its wrappers; no action has a module; console routes: **0** `APIRouter`, **333** `@app.<verb>` inside `register()` functions |
| 19 | Text | `ls services/console/i18n*.py` | **44** catalogue modules, 13,903 lines, checked by `tools/text_keys.py` (D-1220); plus `tb_common/wording.py`, `verdict_word.py`, `orchestrator/i18n.py` outside it |
| 20 | Code and documents | `wc -l` | services 131,466 lines; libs 25,071; **tools 102,745**; tests 211,046; 134 templates. Docs: 1,143 Markdown files, 124,710 lines; **736** decision files + the frozen log (D-01 to D-270, 4,465 lines); highest number D-1224; 35 runbook pages |
| 21 | Correlation across services | grep `traceparent\|X-Request-Id\|request_id\|correlation` | **none** in services and libs (one form field of the same name) |
| 22 | Build reproducibility | grep `SOURCE_DATE_EPOCH` in tools, deploy, Makefile | **none** |

Coverage (**not measured** here; the committed baseline is read [R `tools/coverage_baseline.json`]): line 84 to 98 %
per service (console 88.5, orchestrator 92.2, adapter 89.8, mail gateway 84.4, embed service 76.0), branch 57 to 93 %;
`tools` 66.8 % line. Slowest tests: **not measured** (no stored `--durations` report; CI's comments give shard times
only).

---

## 2. The architecture as it is, and the target

### 2.1 As it is: by process, data store and trust boundary

```
 hospital network ── hospital TLS proxy ──► 127.0.0.1:8090 (the only published port)
┌─ one host, compose project "trialbox" ─────────────────────────────────────────────────────────────────────────────┐
│ console-net ── [console]  loads: datacore, edc_backend, channels, registry, guard, patient_profile, orchestrator.*,│
│                  │        tools.* ; APScheduler #3 (N1, N2, REDCap); 333 routes in one app                         │
│                  │ HTTP, per-service token + actor claim v1 / v2 / v3 (+ legacy shared token, warned)              │
│ trialbox-net ── [orchestrator] loads: matching, datacore, edc, rc_bridge, rc_sim(demo), sitesetup, omop, lake      │
│                  │             client, deliverables, console.* (grants) ; APScheduler #1 jobs, #2 opt-out tick     │
│                [criteria-compiler] [doc-parser] [adapter]──flock──[lake]──[embed-service] [mail-gateway]           │
│                [audit-writer: the one chain writer]                                                                │
│ model-net ──── [gateway: registry, guard, tracestore] ── [model-guard] ── model-backend-net ── [llm | llm-stub]    │
│ egress-net ─── mail-gateway, gateway, criteria-compiler, orchestrator (nftables on the host)                       │
│ PostgreSQL trialbox_wf: 28 schemas, 22 written by two or more roles │ hapi (FHIR store, optional)                  │
│ volumes: lake-data (adapter, lake rw) · objects-data (5 rw) · rulesets · audit (drain rw, 6 ro) · traces · mail   │
│ host: systemd timers (ops, watchdog, weights, egress) · `trialbox` CLI and tools/ (102,745 lines, in the bundle)    │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

[R `deploy/docker-compose.yml`, `docs/ARCHITECTURE.md:21-68`; M 1, M 5, M 6, M 7, M 16] The network boundaries are
good: only the gateway reaches a model, only four services reach the egress network, only the console is published
[R `docs/ARCHITECTURE.md:56-68`]. The process boundaries are not where the code's boundaries are: the console and
the orchestrator each carry most of the code base in memory and talk to the same schemas directly [M 1, M 6]. [O]

### 2.2 Every "one X" that exists in two or more copies today

| One … | Copies today (evidence) | Target owner | Card |
| --- | --- | --- | --- |
| **Clock** | `tb_common.timeutil.now/today` (site zone) [R `libs/tb_common/timeutil.py:10-19`]; the console's `clock()` UTC plus `local_today` [R `services/console/auth.py:466`, `home.py:237`]; the orchestrator's `today()` [R `services/orchestrator/core.py:169,291`]; `tracestore.utcnow` [R `services/tracestore/store.py:41`]; `date.today()` in the mapper, the ingest and OMOP [R `services/adapter/mapping/engine.py:983,1128,1133`; `services/omop/load.py:568,1590,1735`; `services/omop/dqd.py:153`; `services/criteria_compiler/terminology/mapper.py:694`]; 31 `time.time()` [M 14]. Lane J's three clock bugs of one day (the demo's frozen clock, UTC against site time in the registry, zones compared as text) [R: the commission; J-4's commit "an orchestrator stand-in without a clock keeps the wall clock"] | `tb_common.clock`: `now_utc()`, `site_today()`, `site_zone()`, injected; `TB_TODAY` pins it for tests | AQ-7, AQ-8 |
| **Configuration source** | `settings.yaml` checked against `schemas/settings.schema.json` [R `libs/tb_common/config.py:1-5`]; the `DECLARED` registry of environment variables [R `config.py:368`, tested by `tests/unit/test_config_declared.py`] read directly in 138 files [M 15]; `site_params.yaml` with no reader (full review I-M1) | typed `Settings` plus `declared()` as the only readers | AQ-12 |
| **Place for flags** | the audited flag table, 7 flags [R `libs/tb_common/flags.py:96-157`]; 10 `TB_*_MODE`/`_ENABLED` switches in the environment (`TB_SCREEN_PIPELINE`, `TB_EMBED_MODE`, `TB_MATCH_LLM_MODE`, ...) [R `config.py`] | the flag table for behaviour, settings for site facts | AQ-13 |
| **Job system** | orchestrator jobs with leases [R `services/orchestrator/db.py:245-279`]; three APScheduler instances; four systemd timers; 202-and-poll in lake, adapter, data-ops [R `libs/tb_common/jobpoll.py:1-12`]; threads in five apps [M 16] | one job table and one runner process (the orchestrator's worker); timers on the host only for the host | AQ-11 |
| **Internal API and authentication** | JSON over HTTP everywhere (good), but three actor claims (`X-TB-Actor` v1, v2, v3) and a legacy shared token [R `libs/tb_common/service_auth.py:1-40`]; per-seam `*Http`/`*Local` twins (`LakeHttp`/`LakeLocal`, `HttpEmbedder`/`LocalEmbedder`, `ParserHttp`, `CompilerHttp`, `MailHttp`, `AdapterHttp`, `HttpBackend`) [R `services/lake/client.py:106,303`; `services/orchestrator/clients.py:105-156`]; an `inproc://` scheme for the simulator [R `services/rc_bridge/client.py:24`]; no request id [M 21] | one client base: token, v3 assertion, request id, timeout budget; contract tests from `schemas/` | AQ-14, AQ-15, 9g-13 |
| **Schema owner** | 22 of 28 schemas written by two or more roles [M 6]; 01's B1-C3 counts 17 console/orchestrator shares | one writer role per schema; readers get `SELECT` on views | 9d-8, AQ-16 |
| **Audit writer** | **one already** (the drain, D-394) [R `libs/tb_common/audit_writer.py:1-25`]; beside it, domain histories that are not audit: `datacore.history`, `edc` events, `candidate_events`, `flag_event` [R `services/datacore/store.py:34`; `services/edc/store.py:48,54,127`; `services/orchestrator/db.py:84`]. The EDC module will bring its own trail (9a-3 joins its heads) | keep; write in ARCHITECTURE that histories are not the audit | – |
| **Text catalogue** | the console's 44 modules, now checked (D-1220) [M 19]; the orchestrator's mail texts and `tb_common.wording` outside the check; `detect_lang` twice [M 11] | `tools.text_keys` reads every catalogue, mail texts included | AQ-30 (generated list), J-1 follow-on |
| **Person-state function** | five definitions, two vocabularies [M 17]; J-2 (D-1221) not yet on master | J-2's function; the copies import it | AQ-9 |
| **Study-state list** | `recruiting/follow_up/closed/declined`, `startup/open/paused/closed`, `open/paused/closed` [M 17] | the console's `sitestore.STUDY_STATES`, exported | AQ-10 |
| **Authorisation point in the EDC path** | the console checks the study standing, `permit(role, "edc.x", grant)` [R `services/console/edc_pages.py:331`]; the orchestrator checks only the most the role could do in any study, `edc_role_may` [R `libs/tb_common/authz.py:255-260`; `services/orchestrator/edc_api.py:24-25`]; the EDC rules again in `services/edc` [R `edc_api.py:2`]; mail commands by sender and `settings.permissions` [R `authz.py:47`] | the orchestrator checks the same study standing from the signed actor and the delegation log | AQ-19 |
| **Screening engine, chunker, vector store, lake source** | 01 section 4.1 | plan 9 deletes the second copies | 9d-2, 9d-4, 9d-6, 9d-7 |

### 2.3 The target

```
 hospital TLS proxy ──► [web: console]  modules as routers (Feasibility, Screening, Conduct, EDC, Monitoring,
                          │              Stewardship, Admin); no patient schema written; reads views
                          │ one internal client: service token + v3 actor assertion + request id + budget
 ┌──────────────────────── core ───────────────────────────────────────────────────────────────────────────┐
 │ [orchestrator API]  owns orch, study, site, team, datacore, edc, recall, optout …; one authorisation   │
 │                     point (permit with the study standing) for every changing call                      │
 │ [orchestrator worker] the one job runner: scheduled, asked and mailed jobs; leases; idempotency keys    │
 └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
 data plane:  [adapter] ─► [lake] (one source, one note index, one chunker)    [criteria-compiler] [doc-parser]
 model plane: [gateway] ─► [model-guard] ─► [model]                             mail: [mail-gateway]
 platform (libs, no process): clock · config/declared · flags · audit journal · http client · authz · text ·
                              person and study states · logging with request id
 stores: each schema one owner role; others SELECT on views; volumes written by one service each
 test-only (not in the product image): rc_sim, llm_stub, tb_testkit; tools/ never imported by a service
```

**Merges** [O]: `vec` goes (9d-2); `guard`, `registry`, `tracestore`, `patient_profile` and `channels` are libraries
today (no process) and move under `libs/` so that "a folder under services is a process" becomes true (AQ-34);
`rc_sim` and `llm_stub` leave the product image (AQ-33). **Splits** [O]: the orchestrator's job runner becomes its
own process from the same image (the three schedulers join it; a long night no longer shares the API's event loop);
the console is split by module into routers, not processes. **Nothing new is added**: no message broker, no service
mesh, no second database. On one box a job table with leases is the right queue. [O]

### 2.4 The order, without a rewrite (each step ships on its own)

| Step | What | Shippable because | Cards |
| --- | --- | --- | --- |
| 1 | **Freeze.** The architecture test with today's 22 upward edges as KNOWN; the size and complexity ratchet; the clock and environment ratchets | nothing changes at run time; only growth is refused | AQ-1, AQ-2, AQ-8 (lint half), AQ-12 |
| 2 | **Delete the second copies** plan 9 already names | each is its own card with its goldens | 9d-2, 9d-4, 9d-6, 9d-7 |
| 3 | **Cut the back edges**: tools out of the console; the orchestrator off the console's stores; shared vocabularies out of the orchestrator; one direction between edc and datacore | each edge leaves KNOWN; the test proves the loop is gone when the last one goes. The smaller edges (adapter→datacore, omop→adapter, embed_service→lake, matching↔criteria_compiler, rc_sim→edc) go as chores in their lanes' next cards | AQ-3 to AQ-6 |
| 4 | **One clock, one person state, one study state** | the eight server dates first (a bug fix), then the injection | AQ-7 to AQ-10 |
| 5 | **One internal client**, v3 only in PRODUCTION, request id | the Http/Local twins keep their protocol | AQ-14, AQ-15, 9g-13 |
| 6 | **One owner per schema**: read-only first where a service only reads, then writes moved behind routes one store at a time | each store is a card; the database refuses the old path | 9d-8, AQ-16 |
| 7 | **One job runner** | jobs move one family at a time (opt-out tick, then console timers) | AQ-11 |
| 8 | **Modules** (section 3) | all on by default; no box changes until a site switches one off | AQ-20 to AQ-22 |

---

## 3. Module boundaries for a product a site switches on by module

The modules are the journey review's six [R `docs/reviews/2026-11-17-journey-and-simplicity.md:520-527`] plus
Admin and Core (always on). Study types are not modules (02 section 4; 9e-1): a type picks forms, steps and SAE
rules inside Conduct.

| Module | Package (target) | Console router prefix | Matrix actions (today's prefixes) | Jobs | Compose profile |
| --- | --- | --- | --- | --- | --- |
| Core | `libs/tb_common`, `services/orchestrator/core` | `/`, `/account`, `/help` | `account.*`, `profile.*` | health, ops | always |
| Feasibility | `services/feasibility` (from `orchestrator/scenarios/feas*`, `deliverables`, `criteria_compiler`, `doc_parser`) | `/feasibility` | `request`, `criteria`, `report.*`, `command.FEAS` | FEAS | `feasibility`: compiler, doc-parser |
| Screening | `services/screening` (from `matching`, `scenarios/screen*`, `microbatch`, `cohort`, `notmatched`) | `/screening` | `list`, `phi`, `id`, `referral`, `notmatched.*`, `command.SCREEN` … | SCREEN, MICROBATCH, COHORT | `screening`: lake, embed, gateway, model |
| Conduct | `services/conduct` (from `datacore`, lifecycle, SAE, team, IRB) | `/study`, `/participants` | `task.*`, `study.*`, `delegation.*`, `sae.*`, `irb` | visit reminders, N1/N2 mails | always with Screening or EDC |
| EDC | `services/edc`, `edc_backend`, `rc_bridge` | `/edc` | `edc.*` (11), `redcap` | REDCap sync | `edc` (9a-4) |
| Monitoring | in Conduct's package, own router | `/monitor` | `monitor.*` (3), `audit.*` | – | – |
| Data stewardship | `services/stewardship` (from `datacore/dataops`, `sitesetup`, items, opt-out) | `/data` | `dataops.*`, `items`, `conflicts`, `optout`, `staff`, `restore` | ingest, opt-out tick | `ingest`: adapter |
| Admin | `services/console/admin` | `/ops` | `ops.*`, `account.*`, `breakglass.*` | backup, update | always |

The matrix rows by module are counted from the 89 actions [M 18]; the package column is a target, not a move to do
first [O]. **The rule** (02's): a link shows only if its module is on and the role may use it; a switched-off
module's address answers "This site does not use …" [R `journey-and-simplicity.md:531-533`].

**What the two module cards should do first.** Plan 9 does not say which lane J id holds which area-0 row
[R `docs/plan/45-plan-9-2026-11-17.md:633-634`]; this page reads the module work as the rows R40 (`modules:` in
settings, the menu, the home and one route guard) and R42 (routers per module, a module field on every permission
row, compose profiles, the scheduler by module) [R `docs/plan/44-plan-8-2026-11-17.md:136,141`], whichever J ids
carry them (**not verified**). [O]

- **R40 first: one table, not one flag per page.** A `tb_common.modules` registry (module → route prefixes, matrix
  actions, job types, compose profile) and a test that every route, every action and every job type belongs to
  exactly one module (AQ-20). The menu, the home, the route guard and the scheduler read that table. Without the
  test, 333 routes get a module by hand and drift. [O]
- **R42 waits for step 3 of 2.4.** A router per module is cheap only when a module's code does not import the
  others': today the console imports the orchestrator and the orchestrator the console [M 1]. Do AQ-4 before R42,
  and move one module first (Monitoring: 3 actions, a few pages) to set the pattern. [O]
- **Do not build compose profiles per module before a feasibility-only site exists** (journey review F-M3 says the
  same). [O]

---

## 4. A quality system that holds without heroics

### 4.1 The gates, by tier

Today's tiers are named in the workflow [R `.github/workflows/trialbox-ci.yml:87-90`]: a card's pull request runs the
fast tier unless a path is on the full-tier list or it carries `ci:full` [R `tools/ci_tier.py:12-17`].

| Tier | Budget | What runs (today) | Add | What it catches |
| --- | --- | --- | --- | --- |
| **Fast** (every push) | under 10 min; `checks` measured 3 min 8 s [R `trialbox-ci.yml:121`] | ruff, format, actionlint, mypy strict, doclint, decision numbers, findings and licence registers, limits lint, contracts check, rulesets check, text keys, guard tests, data scan, cross-card, differential (no CQL) | **architecture test** (AQ-1); **size and complexity ratchet** (AQ-2); **clock and environment ratchets** (AQ-8, AQ-12); **contract tests** of every internal route from `schemas/` (AQ-14); the authorisation matrix test exists (`tests/unit/test_authz_matrix.py`) | a new loop or private import; a function growing past its baseline; a new `date.today()`; a route that breaks its caller |
| **Card PR touching `services/` or `libs/`** | the six unit shards, about 25 min wall time (slowest shard's median 24.8 min [R `trialbox-ci.yml:301-304`]) | today: fast tier unless on the full-tier list | **the unit shards always** (AQ-23) until the import graph has no loop; then the shards that hold a test importing a changed module | the defects the coordinator's full run caught after narrow runs |
| **Train / master** | as today | unit shards, unit, property, goldens, e2e-simple, demo-boot, security, standards, images | – | – |
| **Nightly** | each job under 90 min (D-537) | compose walk (37.5 min [R `trialbox-e2e.yml:231`]), random order, scale 50k, backup and update drills, perf-5k; mutation of the safety core (floor 60 %, target 90 %, first 66.6 % [R `tools/mutation.toml:5-9`]); branch coverage in 12 shards | the connector suite (V21), the ladder report (V22), **migration and restore from release N-1** (AQ-27), **reconciliation** on the seeded box (AQ-26), pip-audit daily (weekly today [R `trialbox-supply-chain.yml:27`]), performance as a trend file, not an assert | regressions that need data, time or a whole box |
| **Release** | by command | release gates (Trivy, SBOM, licence) [R `tools/make_bundle.sh:13-17`], signed bundle, rehearse-box | the qualification record and the validation pack generated by one command (traceability, gates, SBOM, record); **a second build compared by digest** (AQ-29) | a release that cannot be reproduced or handed over |

### 4.2 Definition of done for a card (AQ-32)

A card is done when [O]: its tests sit at the lowest layer that can show the behaviour; the full unit suite is green
on the card's own pull request (4.1); no ratchet's KNOWN list grew; a schema change carries its migration and passes
the N-1 test; a new flag carries its owner and its removal condition; a new job is in the job table and on the health
page; a new page is in a walk and in a module; generated documents are regenerated (4.8); the decision file is
written. A PR template lists these; a checker reads what it can (ratchets, decision number, generated files).

### 4.3 Review rules

Each lane J card needed two to three adversarial review rounds, and the coordinator's full-suite run caught two
defects that the authors' narrower runs missed [R: the commission]. Two readings follow [O]:

1. **The narrow run is not a sample of the full run when everything reaches everything** [M 1: 16 packages reach 20
   others]. Choosing tests by what a card touched is unsound until the loop is cut. So card PRs that touch product
   code run the full shards (AQ-23); the cost is runner time, not money on a public repository's standard runners
   (**not verified** for this account).
2. **Review rounds should go to behaviour, not to mechanics.** Whatever a reviewer found twice becomes a ratchet or
   a test (as J-1 did for text keys). The reviewer then reads the decision, the tests' claims and the walk.

### 4.4 Flaky tests

Two tests failed under load today: `tests/unit/test_encoding_linear.py` asserts a timing ratio and a 60-second
ceiling [R `:17-34`]; `tests/unit/test_gateway_under_load.py` waits on `time.monotonic()` windows and counts threads
[R `:123-170`]. Thirty-nine test files time something [M 13]. Policy [O] (AQ-24):

- **No wall-clock assertion in the unit tier.** Count operations (calls, bytes, iterations) or inject a fake clock;
  a real timing belongs in `tests/perf`, nightly, written to a trend file.
- **Quarantine within the day**: a test that failed and passed on re-run gets `@pytest.mark.quarantine(card=…, owner=…)`,
  leaves the PR tiers, runs nightly; at most ten quarantined at once; each has a card.
- **Random order** runs nightly already [R `trialbox-e2e.yml:116`]; PRs run with `-p no:randomly`
  [R `pyproject.toml:178`]: keep, so a PR failure is reproducible.

### 4.5 Error budgets [O]

| Budget | Measure | When spent |
| --- | --- | --- |
| Fast tier | p95 under 10 min | the slowest step moves to the full tier or gets faster |
| Unit shard | p95 under 30 min | re-split (D-564's rule) |
| Nightly | 6 green nights of 7 | the lane that owns the red job takes a fix card next |
| Quarantine | at most 10 tests | no new quarantine until one leaves |

"When spent" orders work; it stops nobody (no development gates, `docs/plan/38-handover-2026-11-15.md:24`).

### 4.6 Observability inside an offline box

Present [R]: JSON logs with a PHI and secret scrubber in every service (`libs/tb_common/logging.py:1-8`); `/metrics`
on the console and the orchestrator; seven health checks (canary, backup, verified backup, disks, certificate,
opt-out worker, desktop GPU) shown in the morning mail, a daily health mail and `/metrics`
(`libs/tb_common/metrics.py:12-38`); the gateway's redacted trace store. Missing: a request id across services
[M 21], per-call duration and tokens (9g-8). Traces [O]: on one box, a request id and a job id in every log line and
in the gateway trace give what a tracing collector would, without another process (AQ-15).

**The administrator's health page should show** [O] (AQ-25), beside today's seven: the last good ingest and its gate
(rows in, rows held); jobs waiting and the oldest; the audit drain's lag (journal rows not yet in the chain); each
store's schema version against the release; clock offset (the check exists on the host, `deploy/check_host.sh:276`,
not on the page); the model's p95 latency over the last night; days of disk left at the last week's growth;
reconciliation counts (AQ-26).

### 4.7 Migrations and flags

**Migrations** today: every service migrates its stores at start, a one-off step runs them before the services start
(D-921) [R `libs/tb_common/start_migrations.py:1-12`]; applied versions are checksummed (D-204)
[R `libs/tb_common/migration_baseline.py:1-9`]; the update drill tests one synthetic migration, a bad migration and
the rollback [R `tools/update_drill.py:11-20`]. Missing [O]: a test that takes release N-1's schemas, seeded with
synthetic rows, and migrates them to N (AQ-27); a written expand-then-contract rule (add, back-fill, switch readers,
drop in a later release).

**Flags** today: seven, audited, five-second cache, seeded once [R `libs/tb_common/flags.py:1-25`]. Missing [O]: an
owner, the decision that made it and the event that removes it (no dates, by the owner's rule) on each flag and each
`TB_*_MODE` switch; `doctor` lists flags whose removal event has happened (AQ-13). `TB_SCREEN_PIPELINE` goes with 9d-6.

### 4.8 Documents: generated against written

| Generated by command and checked in CI | Written by people |
| --- | --- |
| contracts (exists), traceability (exists), role rights from the matrix (exists); **new** (AQ-30): the service and process table of `docs/ARCHITECTURE.md` from compose, the schema-owner table from the role script, routes by module, the settings reference from `DECLARED`, the flag list, the import layers | intent, decisions, runbook judgement steps, user guides |

A newcomer faces nine core documents [R `tools/doclint.py:58-67`], 35 runbook pages and about a thousand decisions
[M 20]. A generated page of the decisions that still bind (front matter `binding: yes`, about thirty) makes the rest
history (AQ-31). [O]

---

## 5. Robustness and operations hardening

### 5.1 Failure modes by component

| Failure | What happens today (evidence) | Hardening |
| --- | --- | --- |
| Model down | gateway budget and one retry [R `tests/unit/test_gateway_under_load.py:6`]; canary turns health red [R `metrics.py:15`]; a configuration refusal was retried for 30 min (I-2, 01 M 16) | 9d-9; the health page's model latency (AQ-25) |
| Database down | services wait for it at start (`depends_on: service_healthy`) [R `deploy/docker-compose.yml:35-36`]; a job that was running is queued again and replays its model answers (D-456) [R `docs/ARCHITECTURE.md:203-205`]; behaviour mid-request **not verified** | a drill: stop the database during a SCREEN, start it, the job ends once (AQ-27's harness) |
| Disk full | health warn at 70 %, red at 85 % [R `metrics.py:22-23`]; the update and the restore drill refuse when short [R `tools/update_drill.py:19`; `tools/trialbox/restore_drill.py:84`]; a torn audit line is repaired [R `libs/tb_common/audit.py`]; the review machine filled twice today [R: the commission] | every writer that grows with the data (ingest, lake build, backup, model traces) checks free space first and refuses with the bytes needed; scratch cleaned on exit (AQ-28) |
| Partial ingest | one gate record per night, row quarantine, a held night is never merged (D-271) [R `docs/ARCHITECTURE.md:49-51`; `tools/trialbox/backup.py:611`] | reconciliation counts between pidmap, lake and MPI (AQ-26) |
| Clock skew or a wrong zone | the host check warns when NTP is not synchronised [R `deploy/check_host.sh:276-277`]; `TB_CLOCK_MAX_SKEW_S` is declared [R `config.py:456`]; eight `date.today()` take the container's date [M 14] | AQ-7 (a bug fix now), AQ-8, the offset on the health page |
| Restore onto a newer release | the restore reads every older layout [R `tools/trialbox/backup.py:39`]; a restore of release N-1's data followed by N's migrations is **not tested** [O, from the test names read] | AQ-27 |
| Update killed half-way | the drill kills each of eight steps; `update status` names the step; rollback works [R `tools/update_drill.py:20-22`] | – (good) |
| Mail server down | the outbox keys make a mail leave once (D-401) [R `docs/ARCHITECTURE.md:203`] | – |
| EDC down | V14 covers it (plan 9) | – |

### 5.2 Jobs: back-pressure and idempotency

Present [R]: job leases (`services/orchestrator/db.py:231-279`); `max_instances: 1`, `coalesce`, a six-hour misfire
grace (`config.py:305`); a per-sender daily cap on heavy jobs (`authz.py`, `HEAVY_JOBS`); MICROBATCH's night budget
(`scheduler.py:1-6`); the poll protocol that never times work that grows with the data (`jobpoll.py:1-12`). Missing
[O]: one limit across the three schedulers (each keeps its own `max_instances`, so the opt-out tick, a console timer
and a night job can all hold the database at once: **not verified** under load); an idempotency key on every job that
mails or writes outside the box. AQ-11 brings both.

### 5.3 Integrity, backup, upgrade, secrets, privilege, limits

- **Reconciliation** (AQ-26) [O]: nightly counts that must agree: pseudonyms in `pidmap` = patients in the lake =
  MPI rows; candidates "enrolled" in `orch` = participants in `datacore`; EDC values sent = read back (9a-1); every
  opted-out patient absent from every store the erasure registry names. A mismatch is a red health line.
- **Backup and restore** [R]: two systems (full `.tbbak` and restic), drills nightly in CI and on the box, a verified
  restore within 100 days or red (`metrics.py:17-21`); 9d-10 writes which restores what. Good. [O]
- **Upgrade and rollback** [R `tools/trialbox/update.py:1-30`]: backup first, rollback point, apply, migrate, check,
  roll back on any failure; release sequence refuses a downgrade. Good; add AQ-27. [O]
- **Secrets**: one token per service, the actor key only in the orchestrator [R `service_auth.py:8-13,36-40`]; every
  role's database password reaches every Python service through `env_file: .env` and is blanked per service by a
  list, held by a test [R `deploy/docker-compose.yml:22-31,53-63`]. [O] Files only (`*_FILE`) would make a new
  variable safe by default; the list pattern is safe only while the test is. Keep, and add the legacy-token refusal
  (9g-13).
- **Least privilege between services**: networks are tight [R `docs/ARCHITECTURE.md:56-66`]; schemas are not
  [M 6]; volumes partly [M 7]; containers run as a non-root user but not read-only and without `cap_drop` [M 8].
  AQ-16, AQ-17, AQ-18.
- **Rate limits**: per-sender heavy-job caps, per-person reveal cap, failed sign-in throttling [R `authz.py`,
  `service_auth.py:27-30`]; a per-session limit on the console's JSON API is **not verified**.
- **Resource limits**: every service in the main compose has a memory limit (2 GB for Python) and `pids_limit` 512
  [R `deploy/docker-compose.yml:22-26`; M 8]. Good. [O]

---

## 6. Is plan 9's product good enough, and what hardens it

### 6.1 The verdict by area

| Area | Verdict | Evidence | What it waits for |
| --- | --- | --- | --- |
| **Screening accuracy evidence** | **not ready** | "No figure on this page meets a target"; 4 of 420 eligible patients wrongly excluded (all in sigir) without the six conflicted pairs [R `docs/plan/measurements/p2b-review-2026-11-17.md:25-41`]; 676 code choices asked of the model, 43 % of criteria "a person decides", the small-model filter filtered nothing [R 01 summary 3, 4] | code systems at install (9c-2), the ladder report (9c-1), one identifier detector (9c-11), then a confirming launch (V2, V23) |
| **Data in** | **ready after named cards** for a Taiwan or Japan site reading CSV or SS-MIX2; **not ready** for Oracle or SQL Server or a US site | four readers, SS-MIX2 strongest; no driver for Oracle or SQL Server [R 01 summary 1, 2] | 9b-1, 9b-9 to 9b-13, 9b-16 (a vendor sample); 9b-2, 9b-3 if the site's replica is not PostgreSQL |
| **The journey** | **ready after named cards** | roles modelled right; four accessibility defects; one person in many studies works [R 02 summary 1, 7] | J-2 (one status), R40 (modules), 9g-17 to 9g-21, 9f-1 |
| **The EDC module** | **not ready** (module); **ready after named cards** for a REDCap-linked site | the floor's five blockers and decisions 1 to 3 are open; "nothing of the module enters the bundle before all three" [R `45-plan-9:78-82`]; REDCap 13.7 and 17 stay tested (V14) | the floor, 9a-1 to 9a-6, V26; or REDCap-linked first (decision 2 below) |
| **Install and upkeep** | **ready after named cards** | signed bundle, update, backup and restore drills nightly, rehearse-box on PRs [R `tools/make_bundle.sh`, `tools/update_drill.py`, `trialbox-rehearse-box.yml`]; P2b ran from a tree (`bundle_id: null`) [R 01 section 5.2]; no install on real hardware since plan 8 [R `45-plan-9:46-50`] | V10 on hardware from a signed bundle; AQ-27, AQ-28, AQ-18 |
| **Security** | **ready after named cards** | per-service tokens, egress control, audit with one writer, matrix authorisation [R section 2]; a legacy token accepted with a warning; identifier guard misses full-width IDs and US SSNs [R 01 summary 6]; the EDC check differs between console and orchestrator [R section 2.2] | 9g-13, 9c-11, 9g-11, 9g-12, 9g-16, AQ-19, AQ-18 |
| **Validation** | **not ready** | no qualification record on master since plan 8; V1 and V2 not run [R `45-plan-9:46-50`; `eval/qualification/` holds sets and schemas, no record (M: file listing)] | V1, V2, the release record generated by command |
| **Architecture and maintainability** | **ready to run; not ready to extend by module** | section 1 and 2 | sections 2.4 and 3 |

**In one line** [O]: the box can be installed, updated and kept, and it is secure after a handful of S cards; it
cannot yet be shown to screen accurately or be handed over as validated, and the EDC module is not built. A first
hospital that starts with Feasibility and Screening and a REDCap link waits on accuracy and validation, not on code.

### 6.2 The ten hardening changes with the best ratio

| # | Change | Risk removed | Size | Card |
| --- | --- | --- | --- | --- |
| 1 | Refuse the v1 actor header and the legacy shared token in PRODUCTION | a token holder naming any user | S | 9g-13 |
| 2 | The eight `date.today()` read the site's day | wrong-day screening and age in Taipei and Tokyo between midnight and 08:00 or 09:00 local, where the container's date is UTC [O; the image sets no `TZ`, R `deploy/docker/python.Dockerfile`] | S | AQ-7 |
| 3 | The orchestrator checks the EDC action against the study standing | a role that may sign in one study signing in another through the API | S | AQ-19 |
| 4 | Refuse the hash embedder on VALIDATION and PRODUCTION | silent bad screening | S | 9d-3 |
| 5 | A configuration refusal fails in seconds | half-hour hangs read as model outages | S | 9d-9 |
| 6 | `read_only`, `cap_drop: [ALL]`, `no-new-privileges` on the Python services | a parser exploit writing to its image | S | AQ-18 |
| 7 | One identifier detector with Unicode normalisation | identifiers reaching a model or a log | M | 9c-11 |
| 8 | One owner per schema, read-only elsewhere | a bug in one service writing another's rows | M | 9d-8, AQ-16 |
| 9 | Migrate and restore from release N-1 in the nightly | the first update at a hospital failing on real data | M | AQ-27 |
| 10 | Reconciliation counts and the health page additions | silent loss between stores; a full disk found by a crash | M + S | AQ-26, AQ-25 |

### 6.3 What to postpone from plan 9 until after the first hospital

Plan 9 holds 98 cards here and 44 in the EDC's repository [R `45-plan-9:71-74`]. All six of its L cards here can
wait until a first hospital runs, and most of band 4b beyond what that hospital feeds [O]:

| Postpone | Cards | Size | Why it can wait [O] |
| --- | --- | --- | --- |
| Connectors the first site does not use | 9b-4, 9b-8, 9b-18, 9b-19, 9b-20, 9b-21, 9b-22, 9b-23, 9b-25 | 1 L, 8 M | the site's feed is known before install; the conformance suite (9b-1) makes each later one routine. **D-1067 ruled every connector into 1.0**: this is decision 1 below |
| Rungs that wait for the ladder report | 9c-4, 9c-5, 9c-8 | 2 L, 1 M | plan 9 itself says nothing else should start before 9c-1 (05 J5-1) |
| Study types beyond the first site's | 9e-1 to 9e-7 | 3 L, 3 M, 1 S | the first site runs one type; keep 9e-9 (the reimbursement fence) |
| Comfort features | 9f-10 (passkeys), 9f-12, 9f-13, 9f-14 | 2 M, 2 S | the password re-authentication exists |
| Speed-ups without a measured need | 9g-5 | M | the stub gate shows minutes, not hours [R 01 section 6] |
| The EDC module beyond its floor and V14/V26 | the 44, minus the floor and 9a-1 to 9a-6 | – | only if the first site uses the module, not REDCap |

About 21 cards here (6 L, 14 M) and part of the EDC's 44. **Never postpone** [O]: 9c-1, 9c-2, 9c-11, 9d-3, 9d-8, 9d-9,
9g-11, 9g-13, 9g-16, V1, V2, V10.

One conflict to settle in plan 9's next revision [O]: 9b-20 ("OMOP CDM as an input source") must enter through the
adapter and the one lake, or it re-grows the second lake source 9d-4 deletes.

---

## 7. Cards

Sizes: S a day or less, M a few days, L a week or more. Lane guesses as plan 9 names lanes.

| Card | What | Lane | Size | Waits for | Proved by |
| --- | --- | --- | --- | --- | --- |
| AQ-1 | `tests/unit/test_architecture.py`: the layer table of section 1 row 3; every cross-service import read from the AST; today's 22 upward edges and 7 private-name imports as KNOWN, which may only shrink (the pattern of `tools/boundary_check.py`'s KNOWN); `tools` never imported by `services` or `libs` (KNOWN 5) | Int | S | – | a planted `from console import x` in `matching` fails; removing a KNOWN edge without its line fails |
| AQ-2 | Size and complexity ratchet: per-file baseline of functions over 200 lines and of C901 over 30 (43 today); fails on growth or a new one | Int | S | – | a planted 201-line function fails; `_run_ingest`'s split (9d-5) lowers the baseline |
| AQ-3 | The console stops importing `tools` (`data_scan`, `trialbox.ops`, `cascade_e2e`, `pin_provider`): what the product runs moves under `libs` or the console | C2b | S | AQ-1 | KNOWN `console→tools` reaches 0 |
| AQ-4 | The orchestrator stops importing the console (`grants.py` reads `BreakGlassStore`, `TeamStore`): the two reads move to a shared library or an orchestrator-owned view | C2b | M | AQ-1 | edge gone; break-glass and team tests green |
| AQ-5 | Shared pieces leave the orchestrator: `scenarios.terms`, `recall.ledger`, `reports.common`, `feas_compute`, `decision_context`, `scenarios.evaluate.SqlEngine` into the packages that use them | A2 | M | AQ-1 | `matching`, `sitesetup`, `deliverables` → orchestrator edges at 0; goldens equal |
| AQ-6 | One direction between `edc` and `datacore`; `datacore.export`'s helpers public; `lake.client._object/_key` and `adapter.ndjson._memory_cap` public or moved | E | S | AQ-1 | private-name KNOWN at 0 |
| AQ-7 | The eight `date.today()` read the site's day (`timeutil.today()`) | B2 | S | – | tests with `TB_TZ=Asia/Tokyo` at 23:30 UTC: the mapper's age and OMOP's dates are the Tokyo day |
| AQ-8 | One clock: `tb_common.clock` (`now_utc`, `site_today`, `site_zone`), injected where classes keep a `clock()` today; a ratchet on `datetime.now`, `date.today`, `time.time` outside it (KNOWN today: 102) | J | M | AQ-7 | KNOWN shrinks per card; the three bug classes of the commission have a test each |
| AQ-9 | The five person-state lists import J-2's function and words | J | S | J-2 on master | a test that no module defines a tuple of these states |
| AQ-10 | One study-state list exported by `sitestore`; `channels.grammar` and `notify` map to it | C2a | S | – | one definition; mail grammar tests green |
| AQ-11 | One job runner: the opt-out tick and the console timers become job types of the orchestrator's scheduler, run by an orchestrator worker process (same image); one concurrency limit; an idempotency key on jobs that mail or write outside | A2 | M | – | `kill -9` of the worker in each job: each job ends once, each mail leaves once; APScheduler instances: 1 |
| AQ-12 | Environment reads only through `tb_common.config` (`declared()`), a ratchet with today's 302 reads as KNOWN | Int | S | – | a planted `os.environ["TB_X"]` fails |
| AQ-13 | Each flag and each `TB_*_MODE` switch gets owner, decision and removal event; `doctor` lists those whose event happened; `TB_SCREEN_PIPELINE` removed with 9d-6 | D | S | – | `doctor` test |
| AQ-14 | One internal client base (token, v3 assertion, request id, timeout budget) used by every `*Http` class; console-to-orchestrator routes described in `schemas/`; contract tests per route in the fast tier | C2b | M | 9g-13 | a changed response field fails the caller's contract test |
| AQ-15 | A request id made at the console and the mail gateway, carried in a header, in every log line and the gateway trace | D | S | AQ-14 | one id found in four services' logs for one SCREEN |
| AQ-16 | One writer role per schema beyond the console: `app`, `refdata`, `terminology`, `omop`, `derived`, `mpi`, `pidmap`; readers get `SELECT` | B2 | M | 9d-8 | a write from a non-owner is refused by PostgreSQL |
| AQ-17 | Volumes: `objects-data` split by writer or mounted read-only where a service only reads; `tb-secrets` read-only for the adapter, or the reason written | D | S | – | compose test of mounts |
| AQ-18 | `read_only: true` (with `tmpfs` where needed), `cap_drop: [ALL]`, `no-new-privileges` for the Python services | D | S | – | compose test; the e2e walk green |
| AQ-19 | The orchestrator's EDC check uses the study standing from the signed actor and the delegation log (`edc_allowed`), not `edc_role_may`; one test table shared with the console | E | S | – | a coordinator with `enter_data` in study A refused a draft in study B through the API |
| AQ-20 | `tb_common.modules`: module → route prefixes, matrix actions, job types, compose profile; every route, action and job in exactly one module (with R40) | C2a | M | – | the test lists any orphan |
| AQ-21 | A `module` field on each of the 89 matrix actions; role descriptions grouped by module | C2b | S | AQ-20 | `test_authz_matrix.py` extended |
| AQ-22 | Routers per module (R42), Monitoring first, then the rest one module per card | C2a | L | AQ-4, AQ-20 | a site with Monitoring off answers its addresses with the plain page |
| AQ-23 | Card PRs touching `services/` or `libs/` run the unit shards; when AQ-1 shows no loop, the shards holding a test that imports a changed module | Int | S | – | `tests/unit/test_ci_tiers.py` cases |
| AQ-24 | Flaky policy: `quarantine` marker with card and owner, nightly-only, cap 10; the two named tests count operations or use a fake clock | Int | S | – | the two tests pass with the CPU saturated (`stress` of four workers) ten times |
| AQ-25 | Health page additions of 4.6 | D | S | AQ-15 | each line has a red case in a test |
| AQ-26 | Reconciliation counts of 5.3, nightly on the seeded box and in `doctor` | B2 | M | – | a planted orphan participant turns the line red |
| AQ-27 | Release N-1's schemas, seeded synthetic, migrated to N; N-1's backup restored onto N; nightly | D | M | – | the job fails on a migration that drops a column N-1 wrote |
| AQ-28 | Free-space check before every writer that grows with the data; scratch removed on exit | D | S | – | a filled tmpfs: ingest, lake build and backup refuse with the bytes needed |
| AQ-29 | Build the Python image twice in the release gates and compare digests; `SOURCE_DATE_EPOCH` set | D | S | – | the two digests equal, or the differing layer named |
| AQ-30 | Generated architecture tables (processes, schema owners, routes by module, settings, flags, layers), checked like `contracts-check` | Int | M | AQ-20 | an edited compose file without the regenerated table fails |
| AQ-31 | `binding: yes` front matter and a generated "decisions that still bind" page | Int | S | – | the page lists each marked file |
| AQ-32 | The definition of done of 4.2 as a PR template and a checker for its readable lines | Int | S | AQ-1, AQ-2 | a PR without its decision number is named |
| AQ-33 | `rc_sim` and `llm_stub` out of the product image (test profile image only); `opportunity_hub` fenced as 1.1 (D-1067) | D | S | 9a-6 | the product image holds neither; the demo still boots |
| AQ-34 | Packages without a process (`guard`, `registry`, `tracestore`, `patient_profile`, `channels`) move under `libs/` (a move, no behaviour) | Int | M | AQ-1 | `services/` folders = compose processes |

**Count:** 34 cards: **22 S, 11 M, 1 L.** By lane: Int 9, D 9, C2b 4, C2a 3, A2 2, B2 3, E 2, J 2.

---

## 8. Decisions only the owner can make

1. **First hospital before every connector.** D-1067 put every data connector in 1.0. *Question:* may the
   connectors the first hospital does not feed (section 6.3, about nine cards) land after it starts, with 1.0's
   interoperability statement naming only what V21 proves? *Recommendation:* yes; it is an order, not a cut, and it
   removes one L and eight M from the path to the first patient list. [O]
2. **The first hospital's modules and EDC path.** *Recommendation:* Feasibility, Screening and Conduct with the
   REDCap link; the EDC module after its floor and V26. [O]
3. **Full unit suite on every card PR that touches product code.** It costs runner time (about 25 minutes of wall
   time per push, six runners), not money on standard runners of a public repository (**not verified** for this
   account). *Recommendation:* yes, until the architecture test shows no loop. [O]
4. **A rule that freezes the shape.** No new service folder, schema, scheduler, flag system, actor claim or second
   copy of anything in section 2.2 without a decision; the architecture test enforces the code half.
   *Recommendation:* yes; plan 9's "Stop" list already says it for screening paths and stores (C-12). [O]
5. **`tools/` in the product.** 102,745 lines ship in the host tree at 66.8 % line coverage, and the console imports
   five of them. *Recommendation:* what the box runs moves under the product's gates; the rest stays a developer
   tree outside the bundle. [O]
6. **Error budgets that order work** (4.5). *Recommendation:* adopt; they order a lane's next card and stop nobody. [O]

---

## 9. What this document did not verify

- **J-10 and J-11 by id**: plan 9 does not map lane J ids to area-0 rows; section 3 reads the module cards as R40 and
  R42. Root review 02's own J-10 and J-11 are passkeys and the no-service-worker rule (9f-10, 9f-11).
- **Coverage, slowest tests, flaky rates**: no suite was run; coverage is the committed baseline; no stored
  `--durations` report was found.
- **Image sizes and the bundle's size**: no image was built; only the embedder's weights (about 2.3 GB) are written
  down [R `docs/runbook/01-install-a-new-site.md:48`].
- **Whether the Python containers run in UTC**: the image sets no `TZ` and compose passes only `TB_TZ`; the
  container's actual zone was not observed. The `date.today()` finding depends on it.
- **The three clock bugs and the two defects caught by the full run** are taken from the commission; the J-4
  commits on master confirm the clock work, not each bug.
- **Database loss mid-request**, cross-scheduler contention and a per-session API rate limit: not exercised.
- **CI minutes cost** for this account and repository.
- **The EDC module's code** (D-1060: its repository is not read); its audit trail and authorisation are not
  assessed.
- **Dead code**: no dead-code tool is installed; candidates are named only where reading found them (01 section 5.2).
- **The import measurement counts statements, not use**: a lazy import inside a rarely called function weighs the
  same as a module-level one; the cycle is real for Python's loader, not necessarily for every request path.
