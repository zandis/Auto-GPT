**D-318 The approved ruleset pins its prompts and its terminology release; a newer prompt puts the study in
"approval needed" and SCREEN keeps the pinned prompt until the investigator re-approves.** Task T-101b of TB-PLAN-06
(`docs/plan/28-master-plan-v6.md` §6.2.5), the follow-up to PR #75 (T-101, D-300) and PR #82 (T-105, D-301). Closes
FIT-026 (URS-PI-06) and the pin half of LLM-033. Branch `agent/T-101b-ruleset-pins`. Date: 2026-11-10.

*The problem.* URS-PI-06 says a prompt or terminology change asks for re-approval. D-300 made prompts registry
objects with a sha, and D-301 pinned the terminology release in the manifest. But a ruleset named its judge prompt
only by version (`models.judge_prompt: judge_v4`), or not at all (then the newest version ran), and nothing told the
investigator that the box had moved on from what they approved.

*Decision.*

1. **The pin.** The manifest gains `prompt_pins` (schema `ruleset_manifest`, `PromptPin`): per prompt id the
   registry version, the text sha256 and the output schema sha256. The compiler writes it at approval, for the
   judge prompt, from the registry's current version, and sets `models.judge_prompt` to that version. A draft
   carries no pins; each approval pins again. The terminology pin is D-301's `terminology_release`, unchanged.
2. **SCREEN keeps the old pin.** `orchestrator.scenarios.screen.pinned_judge` resolves the judge through
   `prompt_registry.pinned`: the pinned version, refused (`prompt_pin_changed`, the run stops) unless the registry
   still holds it with the pinned text and schema. A newer registered version does not change what runs. The report's
   prompt line names the pinned version.
3. **Approval needed.** `tb_common.ruleset.approval_state` says `approval_needed` when a pinned prompt has a newer
   version (`newer`), its text or schema changed (`changed`), its id is gone (`unknown`), or the box's terminology
   release is not the pinned one. The console approval page shows the reasons (state only). A FEAS with the same
   protocol now compiles a new draft when the approved version needs approval, so the investigator can re-approve
   without a criteria change.
4. **Old manifests.** A manifest from before this decision has no `prompt_pins`; its `judge_prompt: judge_vN` reads
   as a pin of version N without shas (the registry already refuses an edited text, D-300). A manifest with no judge
   prompt pins nothing and runs the newest judge, as before.
5. **Terminology differs from prompts.** The box holds only its current terminology release, so SCREEN cannot keep
   the old one: D-301's refusal (`RecompileNeeded`) stays. The study shows approval needed, and the run waits for
   the recompile and the re-approval.

*Not done here.* The study list and home pages do not yet show the state (only the approval page). A terminology
change still needs D-301's recompile path before FEAS can draft (`approved_or_none` refuses first). Pins name a
prompt, not a prompt on a model build (LLM-033's second gap, for T-012a). The pins cover the judge prompt only; the
compiler's own prompts (`ir_extract`, `concept_map`) are build-time, not run-time.
