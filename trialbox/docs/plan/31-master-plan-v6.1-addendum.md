# TB-PLAN-06.1 Addendum to master plan v6: the box, the capacity rule and five structural repairs

| Field | Value |
| --- | --- |
| Document ID | TB-PLAN-06.1 |
| Date | 2026-11-12 |
| Owner | Changfu Kuo (Aimedics) |
| Status | **Approved by the owner on 2026-11-12.** It amends `28-master-plan-v6.md` (TB-PLAN-06). Where the two differ, this file wins. §0 of TB-PLAN-06 (D-311, no development gates) is unchanged and still wins over everything. |
| Decision | D-454 (`docs/decisions/D-454-plan-v6-1.md`) |
| Basis | The audit of master of 2026-11-11 (PR #257); the adversarial reviews of the cards merged or built on 2026-11-11 and 11-12 (PRs #259, #262, #263, #264, #275); three cross-module reviews of 2026-11-12 (decision path, identity and trust, the night and data lifecycle); the scale review of another session (PR #279, `docs/reviews/2026-11-11-scale-timeouts.md`); the owner's decisions of 2026-11-12 (§1). |
| Code read | `origin/master` at `90e451eb` |

How to read it. §1 is what the owner decided on 2026-11-12. §2 is what the reviews found and why it is structure,
not a list of bugs. §3 is the new cards. §4 is what changes in the cards of TB-PLAN-06. §5 is the test strategy
delta. §6 is the order of work. §7 is the state of the plan and what the dates now rest on. §8 is the owner's
decisions on the open items.

## 1. Owner decisions of 2026-11-12

| Id | Decision | Effect |
| --- | --- | --- |
| OD-10 | **The product is not sized for a demo. Its capacity limits are the hardware and the model's measured speed, nothing else.** | Every time limit, memory cap and count in the product is derived from the hardware, the model's measured throughput or the size of the data; or it is a declared setting with a reason; or the work is refused at its start with an estimate. No limit cuts a result silently. Enforced by the scale gate (T-687) and its lint. |
| OD-11 | **A site runs TrialBox on a dedicated box**: a GPU workstation or a DGX Spark with our software. People use it at the box, or from their own computers. The hardware form is chosen from measured numbers (T-667, T-734). | The box is the first install form. The shared-host (Kubernetes) and IT-managed forms stay in the tree as a second form, not developed further unless a site asks (§4.4). |
| OD-12 | **The box is owned by a research lead who is the data steward** (at CGMH the owner for the CGRD; in Japan Dr Makoto for his team). Several trials run on one box; each has its own trial PI, sub-investigators and coordinators as users. The owner is not automatically the PI of every trial. | "PI" in this plan means the principal investigator of one trial. The first-run wizard names the box owner. The administrator's duties fall to the owner by default; a site may give them to another person (T-736). |
| OD-13 | **The audience is the box owner and the trial teams, not hospital IT.** Set-up is something the owner can do; IT helps only with the network address and the data connection. Two set-up forms: a box prepared by Aimedics, and one installer for hardware the site bought. | T-729, T-735. The RUNBOOK is rewritten for the owner; IT gets one page. |
| OD-14 | **Data sources are flexible per site**: the hospital's research database (CGRD) by a read connection, a REDCap project, the team's own patient database, an EMR feed for site activation, and spreadsheets a person uploads. | T-731. The hospital feed (HIS export, SS-MIX2) stays as one source among five. |
| OD-15 | **Use from outside the hospital and a phone app are in scope, at a level the hospital or the data steward chooses**: inside the hospital only; notices outside with no patient details; pseudonymous lists outside; everything through the hospital's own VPN. | T-732, T-733. The default on a new box is "inside only". |
| OD-16 | **The box looks after itself**: updates, backups and health checks run without IT; the owner sees one health page and is told when a person is needed; Aimedics helps on request in a supervised session. | T-730. |

## 2. What the reviews found

Twenty cards were built and reviewed on 2026-11-11 and 11-12. Most defects were inside one module and were fixed in
their card. Five kinds came back in card after card, each for one structural reason.

| # | Root cause | How it showed | Review |
| --- | --- | --- | --- |
| S1 | **A verdict has no owner after the engine, and each path gathers its own inputs.** Six paths decide or count patients (SCREEN v1, the cascade, MICROBATCH, NAV, CASE, FEAS/COHORT). Only the snapshot is handed to all of them. | One model's "not met" stored by SCREEN becomes an exclusion in the next MICROBATCH re-tier (confirmed by a run). NAV discards the tier. An amendment's new criteria are left out of a re-tier and the row is re-stamped. Three functions turn a verdict into a status, with four rules that differ. Opt-out is read at about 20 call sites under three rules; FEAS and COHORT read none. Three consent rules. A note with none of the top-5 sentences is not counted as left out, so "not met" on a cut record excludes (cascade: fixed in PR #275; the v1 path still has it). | decision |
| S2 | **The service token is the unit of trust; the person and their right are a claim the console signs, not a fact the callee can see; and reach equals ownership.** | About 40 changing orchestrator routes take the acting person from the request body under any service token (confirmed: `PUT /studies/RS/settings` with `"by": "dr_tanaka"`). A chart number can be turned into a pseudonym by any token holder with no person and no audit. Every service container holds every database role's password. Every writer of a schema is its owner and can drop its append-only triggers; only `audit.journal` is append-only in fact. A break-glass reveal is accepted on the signed word `breakglass`, with no grant. | trust |
| S3 | **A snapshot is a date rebuilt in place, the night is not an object, and derived artefacts are "the newest".** | A hold taken while a rebuild runs does not protect the snapshot: the same pin read 3 patients, then 5 (confirmed). A FHIR-store failure after the gate still promotes the lake (confirmed). A restart re-runs the night's ingest and rewrites the served night under a running job (confirmed). A late re-run of an older night moves the patient twin back (confirmed). The steward cannot accept a held night because "publish" is not a function. | lifecycle |
| S4 | **Erasure is a list a store opts into.** A new store is exempt by default. | After an opt-out the patient is still in every kept lake snapshot, the embedding cache, the FHIR store, OMOP before-images, derived rows, vectors, the twin, job outputs, EDC drafts and backups. A restore silently drops opt-outs typed since the backup. An as-of export brings a withheld patient back. | lifecycle |
| S5 | **Work that grows with the hospital runs in one process, in one request, against fixed limits.** | 36 findings, 3 of them blockers for a 50,000-patient site: site publish against a 330 s limit for an 805 s rebuild; the backup pausing every service; the ingest and the rebuild holding the hospital in memory. A restart re-runs a job of hours from zero. Fixed counts cut results (the newest 500 jobs of the box as "this study's latest job"; a 2,500-token excerpt budget whatever the model's context). | scale (PR #279) |

And one cause in the tests: **tests follow modules, not paths, and several could not fail.** The SCREEN goldens run the
v1 structured filter, not the cascade. The safety properties ran with a judge that ignores the text it is shown. The
monitor page passed against a fake whose reply had another shape than the real service's. Plan §7.5 names `property`
and `differential` gates that no workflow runs. T-652's decision table (`services/matching/verdict.py`) is called by no
engine.

What held, so that it is not redone: the snapshot pin inside a job (D-383, T-305a) is structural and the same on every
path; the pair's combined answer is one function; service tokens and their MAC are sound; the audit hash chain and
signed heads are sound; no job is claimed twice.

## 3. New cards

Rules of TB-PLAN-06 §6.1 apply. Sizes: S ≤ 1 day, M 2 to 4 days, L 1 to 2 weeks of one session. Decision numbers are
taken at start from `REGISTRY.md` (next free at writing: D-459). The scale review named D-448 to D-451 for its own
decisions; those numbers were already used (T-315a, T-203b, T-212d, T-211c), so its four reservations are D-455
(T-691), D-456 (T-689, T-698), D-457 (T-693) and D-458 (T-704).

### 3.1 Wave D: one decision path (closes S1)

| Id | Goal | Acceptance | Size | Depends on |
| --- | --- | --- | --- | --- |
| **T-705** | **Path-independence test.** One small lake, one scripted pair that reads the text it is shown (`tests/judge_kit.py`), every path (SCREEN v1, cascade, MICROBATCH new and re-check, NAV, CASE, FEAS, COHORT): the same patient on the same snapshot gets the same verdict and status; an opted-out patient is in no published bytes. Intended differences are a named table. Today's differences enter as expected failures by finding id. | the test exists and each expected failure names its finding | M | none |
| **T-706** | **Judge-in-the-loop property test.** An oracle pair whose answer depends on the text shown: cutting excerpts, removing a note, a failed verifier, a re-tier, a replay or a batch split never excludes a patient the full record would keep. | fails today on the stored soft fail, NAV's tier and the v1 excerpt cut; passes at the end of the wave | M | none |
| **T-707** | **Pool rows bound to version and basis.** A pool row of another criteria version is screened again, not re-tiered; a single model's answer is never stored as a final fail. | the amendment case and the stored-soft-fail case as tests | S | T-706 |
| **T-708** | **The decision context.** One object, built beside the pinned lake, that every path must use to read anything: the snapshot, the opt-out register (one function, with merged charts), consent (one rule), the ruleset and its pins, whether a note answer may exclude, the run date. | a lint test fails on `opted_out(`, `FROM consent` or the note-block read outside the module; goldens unchanged | M | T-705 |
| **T-709** | **One function where a verdict becomes a status.** `matching/decision.py: status_of`, on T-652's table; the verdict carries its basis (coded, pair, single model, person) and whether it is final. The three tier functions and NAV's own rule move into it. T-216 (missing data) becomes a policy of this function. | T-705 and T-706 pass without expected failures for S1 | M | T-707, T-708 |
| **T-710** | **One excerpt builder** for the cascade, v1 and CASE; "left out" counts every window note not shown; the budget comes from the model's context (OD-10; absorbs T-696). | the v1 excerpt cut is closed; a patient with five long notes gets a decided verdict on a 32k build | M | PR #275, T-709 |
| **T-711** | **Three-engine boundary table.** Ages on the birthday and on 29 February, window ends, the day boundary in the site's zone, units, impossible values and derived scores, across the Python reference, the generated SQL and CQL. This is the `differential` job of §7.5. | a CI job; a disagreement fails it | M | PR #262 |

### 3.2 Wave T: identity and trust (closes S2)

| Id | Goal | Acceptance | Size | Depends on |
| --- | --- | --- | --- | --- |
| **T-712** | Database passwords out of the shared `env_file`: a service container holds its own role's password only. | a test merges the compose files and fails on any foreign `TB_DB_PW_*` | S | PR #276 (T-212d clears most) |
| **T-713** | Callers per route in the orchestrator: the mail gateway may start and read its jobs only; `requested_by: scheduler` is refused over HTTP. | a route walk with the mail gateway's token | S | none |
| **T-714** | A real-box test fixture (`orch_box`: the real app, the token registry, actor keys) replaces the fakes for reveal, export and jobs. | dropping `scope=` from the console's reveal call fails a console test | M | none |
| **T-715** | **Actor assertion v3**: the verified person, role, one study, standing, the action and its target, the grant, the re-authentication time, a hash of the body, a nonce; minted in one place in the console; one dependency on every changing route of the orchestrator, data core and EDC; `by` leaves request bodies. Staged: report mode, then router by router (lifecycle first), then refuse. | a route walk fails on a changing route without the dependency or with a body field `by` | L | T-714 |
| **T-716** | The orchestrator reads the break-glass grant and the delegation log itself and writes the use; the word `breakglass` leaves the role set. | a grant for patient A used for patient B is 403 at the orchestrator | M | T-715 |
| **T-717** | Keys apart: the actor-signing key is not the service token; the EDC re-authentication key is its own; the secrets volume is split so the adapter cannot open the EDC or audit signing keys. | the adapter's container cannot read `edc_sign.key` | M | T-715 |
| **T-718** | Owner, writer and reader roles per schema; migrations run as an install step, not at service start. One schema at a time: `app`, `pidmap`, `edc` first. | a service role cannot drop, alter or disable a trigger | L | T-712 |
| **T-719** | One identifiers module, the only importer of the pid map; chart number to pseudonym only for a person with a right, audited and capped; workbooks stored with pseudonyms and filled at download. | an import lint; the two open routes refuse a bare token | M | PR #259, T-715 |
| **T-720** | Version-1 EDC signatures are accepted only from a signed frozen list (no box holds real ones, so the list is empty); the column default is 2; the console leaves the EDC owner group. | an inserted version-1 row fails `intact()` | S | none |
| **T-721** | The audit says who wrote it: the drain checks an event's prefix against the writing role and its time against the journal's; reveal, export and download events carry a shared id and a hash of the patient list on both sides. | a foreign event is flagged; the audit browser answers "which files held this patient" | S | PR #274 |

### 3.3 Wave G: the night as a generation (closes S3 and S4)

| Id | Goal | Acceptance | Size | Depends on |
| --- | --- | --- | --- | --- |
| **T-722** | The lake: one lock for rebuild and hold; holds checked again at the swap; one rebuild per snapshot at a time. | the confirmed hold race reversed; two rebuilds serialised | S | none |
| **T-723** | **`publish(night)` is one resumable function**: OMOP, FHIR store, lake, promote last; the pid map written after the gate; the data-operations row opened at the start and advanced per step. The steward's accept calls it. | a FHIR-store failure does not promote; a re-run under a held snapshot is refused; accept works | L | T-722 |
| **T-724** | **A generation**: snapshot date plus a sequence number, its cause and the lake's hash. A site publish makes a new generation, never rewrites one; jobs pin a generation; the date stays as an alias. | a job is byte-identical across a site publish | M | T-723 |
| **T-725** | Every derived artefact records the generation it was built from (derived rows, vectors, twins, the FHIR store's night); one function answers "what may a job pinned to generation G read"; an older generation never overwrites a newer one. | a property test over interleavings of the night's steps | M | T-724, PR #262 |
| **T-726** | The night runner: only the ingest and the monthly jobs keep a clock time; every other step starts when the step before it has finished; one run per study and generation; a restart resumes the step it was in. | Monday's jobs never pin last night's snapshot after a slow ingest | M | T-725 |
| **T-727** | **Erasure as an obligation of every store.** Every table of every migration and every lake folder has one of: erased on opt-out, kept with a decision, holds no patient data. A test enumerates the stores from the migrations and fails on one with no entry; a second seeds a patient, opts out, runs the worker and asserts. | both tests; T-206b (PR #278) builds the clears on this registry | M | PR #264 |
| **T-728** | An as-of export keeps opt-out tombstones; a restore reports and audits "opt-outs typed after the backup" and fails, not re-queues, the jobs that were running then. | the two cases as tests | S | T-727 |

### 3.4 Wave C: capacity (closes S5; the cards of PR #279, adopted)

T-687 to T-704 (T-699 is taken) are adopted as written in the scale review and in TB-PLAN-06 §6.2.10, with these
changes.

| Id | What | Change in this plan |
| --- | --- | --- |
| **T-687** | The scale gate: one nightly CI run of ingest, rebuild, screen and backup at 50,000 synthetic patients under the compose memory caps with a slow model stand-in (seconds per call, an outage, a restart); a lint over every `timeout=` above 60 s and every `LIMIT` literal in `services/` against a list with a reason per line. | **First card of the wave.** It is the test of OD-10. |
| T-688 | The cloud run's estimate and heartbeat | for the next G1 attempt |
| T-689 | The screening job survives an outage and a restart; budgets from the population | the replay key includes the generation (T-724); the budget rule is OD-10 |
| T-690 | Rebuild and ingest as polled jobs | after T-722; it uses T-723's state, not its own |
| T-691 | The backup without a pause; limits from size | the backup becomes a step of the night (T-726) |
| T-692, T-693, T-694, T-695, T-697, T-698, T-701, T-702, T-703 | as written | T-694's batches call T-710's excerpt builder per patient |
| T-696 | The excerpt budget from the context; S2b with the pinned embedder | absorbed by T-710 and T-203b |
| T-700 | The console's fixed counts | absorbs the audit's finding on jobs fetched 500 at a time |
| T-704 | The night as a chain | absorbed by T-726; its nightly deltas use "since the last published generation" |

### 3.5 Wave B: the box (OD-11 to OD-16)

| Id | Goal | Acceptance | Size | Depends on |
| --- | --- | --- | --- | --- |
| **T-729** | **The box installer and the first-run wizard.** One installer for a workstation or a Spark, and the same steps as a prepared image. The wizard asks what an owner knows (site name, time zone, language, the owner's account, where backups go, the data source) and nothing an IT department would be asked. No shell, no compose knowledge. | a rehearsal installs a box from the installer with only the wizard's answers, signs in over HTTPS and passes `doctor` | L | T-632 (merged), T-214 (merged) |
| **T-730** | **The box looks after itself.** Signed updates applied in a quiet hour with rollback; backups to a second disk or a share with no IT step; one health page; a message to the owner when a person is needed. The supervised remote session for Aimedics is **not built** (the owner, 2026-11-16, D-967): a hospital box has no remote way in for the pilot; revisit after the pilot with the hospital's IT. | the update, backup and restore drills run from the health page; a failed backup tells the owner | L | T-729, T-691 |
| **T-731** | **Data connectors** (OD-14), each with a mapping step the data steward can do on the box: a REDCap project as a source (read); the team's own database by a read-only connection; spreadsheet and CSV upload; a read connection to a research database for an approved scope; the EMR or hospital feed as built. Every source lands in the same ingest gate and data-operations page. | each connector loads its synthetic twin and the night passes the gate; an upload of a sheet with a name column is refused | L, one PR per connector | T-723 |
| **T-732** | **Use from outside as a site setting** (OD-15): four levels chosen by the hospital or the data steward and audited; "inside only" is the default. Level 2 (notices) needs no path into the hospital; levels 3 and 4 need a decision record on the path out. | at each level a walk shows exactly what leaves the box; a level change is audited | M | T-719, T-715 |
| **T-733** | **The phone app**, notices first: counts, tasks and reminders with no patient details; more only at the level T-732 allows. A decision first on its form (installable web app or native). | a notice reaches the test device and holds no identifier (data scan) | M | T-732 |
| **T-734** | **The capacity statement.** From the measured throughput of the box's hardware and model pair (G1, T-667, T-637): how many patients and studies a night this box can carry. The box shows it, refuses or schedules what does not fit and says so. The hardware note for the Spark against a GPU workstation is written from the same numbers. | the statement for the measured run is within 15 % of the run; a request over capacity is answered with an estimate, not a cut list | M | G1's report, T-687 |
| **T-735** | **Documents for the owner.** The RUNBOOK becomes the owner's handbook (set-up, a normal day, when something is wrong); IT gets one page (the address, the data connection, the firewall line); the shared-host and IT-managed procedures move to an "other install forms" part. | every page names its reader; an owner can follow the set-up page in the rehearsal | M | T-729 |
| **T-736** | **Duties on a box** (OD-12, OD-17): the owner is steward and, by default, administrator; a trial PI is a user. The owner reads patient-level data as any reader does (pseudonymous by default, a chart number with a recorded reason); a second person named at set-up gets a monthly list of the owner's identifier use, or the box keeps it for every audit export. | the role matrix and the wizard follow OD-17; the owner cannot mark their own use reviewed | M | T-729 |

### 3.6 Smaller cards from the audit

| Id | Goal | Size |
| --- | --- | --- |
| **T-737** | The N-12 gate reported on the unadjusted figure in `tools/parity_replay.py`, its JSON and its test (T-649b's acceptance); `hypothesis` in the test lock so the property tests run (T-650's acceptance); the `property` job of §7.5 in CI. | S |
| **T-738** | The forbidden-word check covers `forms.csv`; the zh-TW label of `ae_serious_why` reworded as OD-19, after a native reader confirms. | S |
| **T-739** | The access design before a session reaches the owner's B200 (named in §0.4 and §4 of TB-PLAN-06 as T-630, which has no card row). | S |

## 4. Changes to the cards of TB-PLAN-06

### 4.1 Open pull requests

| PR | Card | What changes |
| --- | --- | --- |
| #262 | T-207 | Lands with its stored-score read behind one flag, off, on every path or none (done). T-725 replaces its "first finished batch" pin with the generation. |
| #275 | T-203b | Lands with the left-out fix on both rankings (done). Its flag is not turned on before T-724. |
| #278 | T-206b | Builds its clears on T-727's registry and enumerating test. |
| #259, #274, #276, #272, #273 | T-103, T-211c, T-212d, T-302c, T-303 | No change; T-719 and T-721 build on #259 and #274. |

### 4.2 Not-started cards

| Card | Change |
| --- | --- |
| T-216 | Becomes the "unknown with a reason" policy of T-709; start after it. |
| T-681, T-682 | After T-715 and T-721: today their rows would take the acting person from the query. |
| T-627 | After T-724 and T-728. |
| T-304a, T-316a | After T-709 (counts and lists must agree). |
| T-213b | Re-scoped to the box: the drills of T-729 and T-730 on a rental workstation and on a Spark. |
| T-624 | Its end-to-end case changes with T-707. |
| T-678 | Stays dated after June 2027. |
| T-301a/b, T-302c, T-304b/c, T-305c, T-306, T-310c, T-311a/b, T-312, T-313, T-314, T-315b/c, T-316c, T-317, T-320a/b, T-625, T-626, T-683, T-686 | Unchanged. |

### 4.3 Merged cards whose acceptance is not met

T-650 (`hypothesis` not in the lock) and T-649b (N-12 printed as a pass on the adjusted figure): T-737. T-212c (the
console is in the EDC owner group; writers are owners): T-718, T-720. T-652 (the decision table is called by no
engine): T-709. T-656 (the audit log still names a zone of its own): with T-708.

### 4.4 The second install form

The shared-host (Kubernetes) form (T-113b, T-633, T-319) and the IT-managed box with disk unlock by Tang (T-634) stay
in the tree and in CI as they are. No new card extends them. The Windows/WSL2 path (T-210a) is not the box's path: a
box is Linux on a workstation or a Spark. A site that wants one of these forms gets a card then.

## 5. Test strategy: changes to §7 of TB-PLAN-06

1. **Tests follow paths.** T-705 (path independence) and T-706 (judge in the loop) are required checks. A card that
   adds a path that decides or counts patients adds it to T-705's table.
2. **A safety property must be able to fail.** A property test uses a judge that reads the text it is shown and
   patients with more than one note. The goldens gain a cascade golden with a recorded pair when G1's recordings exist.
3. **Fakes are made from the real thing.** A fake of a service is built from that service's own router or recorded
   reply (T-714), not written by hand.
4. **The gates of §7.5 exist**: `property` (T-737), `differential` (T-711), `scale` nightly (T-687).
5. **Every store is enumerated** by the record inventory (as today), the erasure registry (T-727) and the role tests
   (T-718): a new table fails all three until it has its rows.
6. **Merging.** A card merges only after its own CI unit job is green. The integrator then merges master into the
   branch, runs the gates and the touched tests on the merged tree, and merges; the next pull request's CI run checks
   the combined master, and a break is fixed at once. Master was broken twice on 2026-11-11 by merges made before the
   card's own unit job had finished; that is the part without exception. The integrator reads each card's unit
   result, not only its fast jobs. This build machine runs as root and has directories CI lacks, which hid two
   failures: CI is the judge. CI's pull-request jobs have no pgvector and no Docker: a card whose SQL needs either
   says where it was run.
7. **Review.** Safety-core cards (matching, the engines, the guard, `authz`, the prefill path, and now the decision
   path, the opt-out path and identifiers) get one automated adversarial review before merge. On 2026-11-11 and 11-12
   each of the six reviews found at least one defect the card's own tests had passed.

## 6. Order of work

1. **Now:** finish the open pull requests (§4.1); keep master green.
2. **First, small and safe (all S):** T-712, T-713, T-720, T-722, T-728, T-737, T-738; and the two tests that make the
   rest measurable: T-705, T-706.
3. **Then the structure, in three lanes that touch different files:** decision (T-707, T-708, T-709, T-710, T-711);
   trust (T-714, T-715, T-716, T-717, T-721, T-719, T-718); night (T-723, T-724, T-725, T-726, T-727).
4. **Capacity:** T-687 first; then the three blockers (T-690, T-691, T-692); then T-689, T-694, T-700 and the rest.
5. **The box, in parallel from step 2** (it touches `deploy/`, `tools/` and the documents): T-729, T-735, T-731,
   T-730, T-736; then T-732, T-733, T-734 when G1's numbers and T-715 are there.
6. **The remaining cards of TB-PLAN-06** as their dependencies of §4.2 allow.

Workers: at most three or four at a time (the owner's allowance), one card each.

## 7. State and what the dates rest on

| | Cards |
| --- | --- |
| TB-PLAN-06 total | 185 |
| Merged on master (2026-11-12, `90e451eb`) | 143 |
| Built, in an open pull request | 8 |
| Not started | 34 (about 10 wait for G1 or the owner's hardware) |
| New in this addendum | 24 structure (§3.1 to §3.3), 17 capacity (§3.4), 8 box (§3.5), 3 small (§3.6): **52** |
| To build from today | about **94** |

- **G1.** The run in progress measures the pair on code that had the left-out defect (S1) and through a cascade whose
  excerpt budget is fixed (T-710). Its accuracy numbers are a first reading. The pair is measured again after T-706,
  T-709 and T-710, and the hardware note (T-667, T-734) is written from that run.
- **The PoC gates** (GP-0 tag by Fri 2026-11-27, GP-1, the sessions of 12-08 to 12-11) are still in TB-PLAN-06, while
  the owner set the PoC aside on 2026-11-11 because it needs a GPU. Their dates are dropped (OD-18): one PoC with real
  models on a box, dated once the decision and trust lanes have landed.
- **G3 (Fri 2027-02-26, feature complete).** At the pace of 2026-11-11 (13 merges in a day, which used a week's
  allowance) 94 cards are about 8 to 10 working weeks at a sustainable 2 to 3 merges a day. That is the whole time to
  G3 with no float. The capacity and box waves are what a real site needs; the dates of the two go-lives rest on them
  more than on the remaining feature cards.

## 8. Owner decisions on the open items (2026-11-12)

| Id | Item | Decision |
| --- | --- | --- |
| OD-17 | What the box owner (data steward) may see, and who reviews the owner (T-736) | The owner sees patient-level data through the same door as every reader: pseudonymous records by default, a chart number only with a recorded reason. A second person named at set-up (a co-investigator or the hospital's research office) receives a monthly list of the owner's identifier use; where a site names nobody, the box keeps the list and includes it in every audit export. The owner never reviews their own use. This replaces "the steward has no patient view" of D-380 for a box. |
| OD-18 | The PoC gates of TB-PLAN-06 (GP-0 of 2026-11-27, GP-1, the sessions of 12-08 to 12-11) | The dates are dropped. One PoC, with real models (the former GP-2), on a box, after the decision and trust lanes of §6 have landed. It is dated then. |
| OD-19 | The zh-TW label of `ae_serious_why` | 「列為嚴重的原因」, to be confirmed by a native reader (Dr Wenn or a coordinator) when T-738 is built. |
| OD-20 | NAV and the opt-out register | NAV follows the register, as built in D-441. |
| OD-21 | Secrets | The owner runs a secret scan of the git history and rotates the keys named in the handover of 2026-11-11, whatever the scan finds. Not a build card. |

Settled earlier the same day: the addendum is approved; PR #279 is merged, with its decision numbers renumbered (§3).

## 9. Change history

| Date | Change |
| --- | --- |
| 2026-11-12 | First draft: OD-10 to OD-16; root causes S1 to S5; cards T-705 to T-739; the cards of PR #279 adopted. |
| 2026-11-12 | Approved by the owner. PR #279 merged; its four decision reservations renumbered D-455 to D-458. |
| 2026-11-12 | The owner's decisions OD-17 to OD-21 on the open items (§8). |
