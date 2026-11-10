# PoC forms

Four forms: the session record (the facilitator fills it during a session), the finding form (one per finding), the
questionnaire (the tester fills it after session B) and the debrief notes. Copy them outside the repository for each
session: a filled form holds a tester's own words and stays in the project's private files. Only the triaged
findings, under a tester code, come back to the repository (gp-findings.md in this folder, written at the exit review).

Never write a patient's details on any form. The patients are synthetic; refer to one by the pseudonym the console
shows (for example "patient 92ab1972").

## 1. Session record (facilitator)

Header: tester code (T1 Japan site, T2 Taiwan site); session (A or B); date and start time (site time); account used
(PI, sub-investigator or CRC); language of the console; device (PC or phone, browser); recording agreed (yes or no);
tag the host runs (for example `poc-1`).

One row per task of the script ([scripts/jp.en.md](scripts/jp.en.md), [scripts/tw.en.md](scripts/tw.en.md)):

| Task id | Done? (yes / with help / no) | Time (min) | Ease 1 to 7 (tester) | Where the tester stopped or hesitated | Said aloud (short quote) | Finding ids |
| --- | --- | --- | --- | --- | --- | --- |
| JP-PI-01 | | | | | | |

Ease: 1 is very hard, 7 is very easy. Ask "How easy was this?" after each task and write the number the tester
gives. Each request for help is a finding.

Footer: incidents (demo down, real data entered: what was done, without the content); the facilitator's three main
observations.

## 2. Finding form (one per finding)

| Field | Value |
| --- | --- |
| Finding id | PoC-<tester code>-<number>, for example PoC-T1-07 |
| Task id | the script task, or "free use" |
| Page | the address shown in the browser, without any query part that names a patient |
| Study, role, language | for example AD-MAB, PI, ja |
| Kind | wrong result / confusing / wording / missing / slow / other |
| Tester's rating | would cause a wrong patient decision / blocks my task / slows me down / cosmetic ([severity.md](severity.md)) |
| What happened | in the tester's words, or the facilitator's |
| What was expected | the script's expected result, or what the tester expected |
| Known gap? | yes (the script's "known gap" names it) / no |
| Triage severity and outcome | filled at the exit review: Blocker to Low; before G2 / before G3 / after go-live / not doing |

## 3. Questionnaire (tester, after session B)

**Part 1: the System Usability Scale (ten items).** Brooke's scale, as published, answered 1 (strongly disagree) to
5 (strongly agree). Give the tester a published Japanese or Traditional Chinese translation of the ten items; this
pack does not make its own translation, so the scores stay comparable with other studies. The English items:

1. I think that I would like to use this system frequently.
2. I found the system unnecessarily complex.
3. I thought the system was easy to use.
4. I think that I would need the support of a technical person to be able to use this system.
5. I found the various functions in this system were well integrated.
6. I thought there was too much inconsistency in this system.
7. I would imagine that most people would learn to use this system very quickly.
8. I found the system very cumbersome to use.
9. I felt very confident using the system.
10. I needed to learn a lot of things before I could get going with this system.

Score: odd items give (answer − 1), even items give (5 − answer); the sum times 2.5 gives 0 to 100.

**Part 2: five open questions** (`docs/plan/27-poc-plan.md` §6.3), in the tester's language:

| # | English | 日本語 | 繁體中文 |
| --- | --- | --- | --- |
| 1 | Which screen would you not trust for a real patient, and why? | 実在の患者さんに使うとしたら信頼できない画面はどれですか。その理由は。 | 若用於真實病人，您不信任哪個畫面？為什麼？ |
| 2 | What did you look for and not find? | 探したのに見つからなかったものは何ですか。 | 您找過卻沒找到的是什麼？ |
| 3 | Which words would a colleague at your hospital misunderstand? | 同じ病院の同僚が誤解しそうな言葉はどれですか。 | 貴院同事可能會誤解哪些用語？ |
| 4 | What in your own trials does this flow not cover? | ご自身の治験で、この流れでは扱えないことは何ですか。 | 您自己的試驗中，有哪些是這個流程沒有涵蓋的？ |
| 5 | If you could change one thing before your hospital uses this, what would it be? | 病院で使う前に一つだけ変えられるとしたら、何を変えますか。 | 若在貴院使用前只能改一件事，您會改什麼？ |

## 4. Debrief notes (facilitator, end of session B)

Ask, and write the answers in the tester's words: the three worst things; the three best things; what is missing for
your own trials. Read the notes back to the tester before the call ends. Afterwards ask, without obligation, for a
mail that the notes are a fair record.
