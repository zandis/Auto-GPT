# PoC severity scale

Every PoC finding gets two ratings. The tester gives the first, in the session or in the feedback; the owner and the
integrator give the second at the triage of the exit review (`docs/plan/27-poc-plan.md` §6.4). The second uses the
deep review's scale, Blocker to Low, so PoC findings sit beside the review's findings in one list.

## The tester's rating: how much it matters

| Rating | Means | Example |
| --- | --- | --- |
| Would cause a wrong patient decision | If this were real, a patient could be approached, kept off a study or recorded wrongly. | A criterion row says "not present" when the note says the condition is there. |
| Blocks my task | I could not finish the task without help. | The coordinator cannot find the task the PI sent. |
| Slows me down | I finished, but it took longer or more steps than it should. | The referral page needs three clicks to reach the doctor's answer. |
| Cosmetic | Wording, layout or look; the task was not affected. | A Japanese label is in English. |

## The triage rating

| Severity | Definition | What happens |
| --- | --- | --- |
| Blocker | A wrong answer, data loss or a security fault on the path the PoC uses; or real patient data could get in. | A fix card the same day; the PoC pauses if the fault is live. |
| Critical | A wrong answer is possible elsewhere, or a role can do what its delegation forbids, or a task cannot be done at all. | A fix card before the design freeze (G2). |
| High | A task can be done only with help or a workaround; a clinical word is misleading. | A card before G2, or before G3 with a reason. |
| Medium | The task is done but slowly, or the screen lacks something a clinician looks for. | A card before G3 or after go-live. |
| Low | Cosmetic; a wording fault that misleads nobody. | Batched into a wording card, or "not doing" with the reason. |

## Rules

1. Anything a tester rated "would cause a wrong patient decision" becomes a card the same day, whatever its triage
   outcome.
2. Each item gets one of four outcomes: **before G2** (a card in wave 2), **before G3** (wave 3), **after go-live**
   (dated), **not doing** (with the reason).
3. A wording fault in Japanese or Traditional Chinese is a finding like any other (D-311 B12: no signed native read).
4. A release is blocked only by an open wrong-answer, data-loss or security fault (D-311 S5), never by a count of
   findings.
5. Duplicates are linked, not merged, so the count stays honest.
6. A "known gap" in a script that a tester meets is still logged, with the tester's rating, so its priority is set by
   the testers and not by the plan.
