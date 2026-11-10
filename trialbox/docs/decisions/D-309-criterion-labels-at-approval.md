**D-309 A ruleset ships its criterion labels, text and to-dos in the site's languages; a short label in the page
language is a required step before Approve all; answers read from notes by the test model say so.** Card T-507 of
TB-PLAN-06 (`docs/plan/28-master-plan-v6.md` §6.2.3, wave P; `docs/plan/27-poc-plan.md` §3 and §7 item 10). Closes
UX-009 (criterion labels, criterion text and to-dos) and LIFE-004; helps LLM-045 (the label half; the stub's ja and
en note answers wait for fix group D-276). Branch `agent/T-507-criterion-labels`. Date: 2026-11-10. Changes D-120
(labels were optional at approval).

*The problem.* A Japanese or Chinese clinician read the PoC study's criteria in English on every list and patient
page: the short labels, the protocol text and the to-do lines. D-120 let the site give a label at approval, but
nothing asked for one and no demo gave any. The demo's note answers come from the test model with fixed answers,
and no page said so (RSK-56: the PoC must not mislead about accuracy).

*Decisions.*

* **Shipped words.** A ruleset may carry `rulesets/<id>/labels.yaml`: per criterion the protocol's own text
  (`source`), its to-do (`todo_source`, the IR's `action`) and, per language, a short `label`, the `text` and the
  `todo`. A translation is used only while the approved criterion still has exactly the `source` text (whitespace
  aside); an amended criterion shows the protocol's words until someone labels it again. The file is not part of
  the ruleset the engines load and changes no result. `console.ruleset_labels` reads the box's copy first, then the
  rulesets that ship with the product. The PoC rulesets on master carry one: GZQO (ja, zh-TW), GOUT-COH and RA-COH
  (ja, en). Every shipped translation needs a native read before the PoC.
* **On the page.** The label the site gave at approval (D-120) wins, then the shipped label, then the study's own.
  Whatever replaces the study's words keeps them beside it: the label in brackets, the text under "As written in
  the protocol" one tap away, both marked `data-original` and `lang="en"` (D-133). To-do lines show in the page
  language where the ruleset ships them.
* **The label step.** On a Japanese or Chinese approval page, **Approve all** is offered only when every criterion
  has a short label in that language: the site's own or the shipped one for exactly this text. A row without one is
  marked, the editor field is required, and `POST /approve` answers 409 until the labels are given. An English page
  asks for none. The step does not ask again for a site label given to an earlier text of the same criterion
  (left for a later card).
* **The test model.** With `TB_LLM_MODE=stub`, or with no `TB_LLM_MODE` on a DEV or TEST box (the demo and the tests
  run the in-process stub), every criterion answered from notes carries a "test model" label on the patient,
  candidate and week pages, with the reason in its title. A box with a real model shows none.

*The check.* `tests/console/test_criterion_labels.py`: every PoC criterion has its label, text and to-do in the
site languages and no verdict word (T-506's list); the walk over the investigator's and the coordinator's clinical
pages in ja and zh-TW finds no English word outside the allow-list (the study's words beside a translation, record
quotes, codes, units and abbreviations); without the shipped file the walk finds the English labels; Approve all
waits for a label; DEV pages label the test model and a real-model box does not.
