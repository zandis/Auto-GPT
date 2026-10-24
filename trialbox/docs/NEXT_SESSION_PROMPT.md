# Starter prompt for the next build session

Copy everything inside the box into a new Claude Code session on the repository `zandis/Auto-GPT`.

Before starting, add `OPENROUTER_API_KEY` as a secret in the cloud environment settings if you want the live
multilingual bake-off. Without it, everything else still runs.

---

```text
You are building TrialBox v4 end to end in the repository zandis/Auto-GPT, folder trialbox/.

Start from the branch origin/claude/trialbox-e2e-build-lcvm9p (or from master, if
https://github.com/zandis/Auto-GPT/pull/2 has been merged). Develop on the branch this session assigns you.

Read these first, in this order, before writing code:
1. trialbox/docs/HANDOFF.md: the state, the build order, the Test Bench design, how to run things, and the traps.
2. trialbox/spec/v4/README.md, then §17.1 (package layout) and §20.8 (MS0 backlog and first sprint) in
   trialbox/spec/v4/16_vv_engineering_operations.md and 19_positioning_plan_appendices.md.
3. The spec sections each task points to (§4 cascade, §5 data platform, §8 LLM gateway, §9 Hermes, §12 deliverables,
   §16 verification).

Goal: a v4 vertical slice that runs end to end on open and synthetic data, plus a test web page to drive and inspect it.
- Every layer on the critical path exists as real, tested code:
  data platform L0–L5 with publish gate and lineage → trial intake → IR v3 → SQL/CQL
  → cascade S0–S5 with the S3 judge through tb-gateway → feasibility pack (figures, PDF, XLSX, small-cell rules)
  → recall certificate → reply through the channel engine → audit chain.
- External systems you cannot reach (HIS, IdP, Teams, LINE, NHI) use the fake transports the spec names.
- The test web is the "TrialBox Test Bench" in tools/testbench/, as designed in HANDOFF.md §5. It is dev and test only,
  loads only D0 or synthetic data, binds to localhost, is excluded from product images, and has Playwright smoke tests.

Work in the phases of HANDOFF.md §4, in order:
Phase 0 baseline → Phase 1 spec sprint 1 → Phase 2 rest of MS0 → Phase 3 cascade and deliverables → Phase 4 Test Bench
→ Phase 5 hardening, docs and PR.
- At the end of each phase: run make lint and make test, plus the phase's own done-when checks. Commit with a clear
  message and push.
- Use parallel subagents for independent tasks, for example S1-02/S1-03 next to S1-06 next to S1-12. Review their diffs
  yourself before committing.
- Keep a progress table in trialbox/docs/PROGRESS.md. For each task: done, partial or not started, with the evidence.
- If something is out of reach, record it in that table with the reason and move on. Examples: the Hermes release
  cannot be fetched, or Docker is not available. Do not stop the whole build for it.

Rules:
- spec/v4 is the contract. §17.1 governs paths. If you must deviate, change the spec in the same commit and say why.
- Build tb-gateway in-house; do not use LiteLLM. Use Eclipse Open Integration Engine, not Mirth.
  Do not use Soda Core v4.
- Use only open or synthetic data. Fetch the MIMIC demo at run time; never commit it.
- The repository is public. Commit no hospital-internal details, pricing, staff names, credentials, IPs or meeting
  details. Never ask me to paste an API key into chat; read OPENROUTER_API_KEY from the environment if it is set.
- No model identifiers in commits, PR text or code comments.
- Tests carry @req markers with spec requirement IDs. Every bug fix gets a test that fails on the old code.

When you are done, open a draft PR. If PR #2 is still open, use its branch as the base. The PR includes:
- a test-plan section with the exact commands and counts;
- the end-to-end funnel numbers for EMPULSE and STARRT-AKI;
- the progress table;
- how to start the Test Bench (make testbench) and a screenshot of each page.

Then give me a short summary: what works end to end, what is stubbed, and what is blocked and on whom.
```

---

## Shorter variant (one phase at a time)

Use this form to run one phase per session instead of the whole build:

```text
Continue the TrialBox v4 build in zandis/Auto-GPT (folder trialbox/). Read trialbox/docs/HANDOFF.md and
trialbox/docs/PROGRESS.md. Do the next phase of HANDOFF.md §4 that is not done yet, following the rules in
HANDOFF.md §8. Commit and push when its done-when checks pass, update PROGRESS.md, and open or update the draft PR.
```
