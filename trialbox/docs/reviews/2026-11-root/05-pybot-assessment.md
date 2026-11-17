# Root review 05: can the outside project "PyBot" become part of TrialBox? (lane J side review, 2026-11-17)

**Reader:** the owner (a clinician) first, then the builders and whoever writes plan 9.

**The question, in the owner's words:** "If this is feasible, probably we can use this to become part of patient
finding, even reduce the need for llm ... deep review whether this can add to our system in all possible ways,
incorporate to plan 9."

**The answer in five lines.**

1. The address is real and is what it says: `https://github.com/huggingface/pybot` is an English everyday-life
   chatbot written entirely as Python rules by a swarm of agents. It has no model and no weights.
2. **It cannot become part of patient finding.** It holds no code for eligibility, clinical notes, code systems,
   Chinese or Japanese. Its medical content is consumer advice for the United Kingdom ("see your GP"). Nothing in it
   can be pointed at a patient record.
3. **Do not ship it in the box, in any role.** Verdict per use: adopt nowhere; learn from it in three places; ignore
   it in the rest.
4. **The owner's real aim, fewer decisions that need the large model, is sound and is reachable without this
   project.** TrialBox already decides most of screening by rules. The largest remaining saving is one switch that
   the product keeps closed today on purpose: every note question with no keyword hit goes to the large model
   (section 3).
5. Seven sized cards for plan 9 are in section 5. The first one is a measurement, and nothing else should start
   before it.

**How every claim is marked.**

| Mark | Meaning |
| --- | --- |
| **[measured]** | A command was run in this session; the command is given |
| **[code]** | Read in code; file and line given. TrialBox paths are relative to `trialbox/`, at master `15108f46` |
| **[source]** | From a document or a web page; the link or the file is given |
| **[opinion]** | This reviewer's judgement |

Paths that begin `bot/` or `pybot.py` are inside the outside project at its commit `7d63c7fb`, not inside TrialBox.

**What this review did not do.** It did not run PyBot (section 6 says why). It downloaded no model, installed
nothing into the repository, changed no product code, and used no hospital data.

---

## 1. What the project is

### 1a. Verified facts

| Fact | Value | Mark |
| --- | --- | --- |
| Address | <https://github.com/huggingface/pybot>, public, under the Hugging Face organisation | [source] the page loaded on 2026-11-17 |
| Its own description | "PyBot: a chatbot written in plain Python by a swarm of agents. No weights, no training, just rules." | [code] `pyproject.toml`, `description` |
| Purpose | A research demonstration: how far can a rule-based chatbot go if over 1,000 agents write the rules. It answers everyday questions (cooking, the house, money, family, health worries) in a chat | [source] its `README.md` |
| Licence | Apache License 2.0. The repository has a `LICENSE` file and no `NOTICE` file | [code] `LICENSE`, `pyproject.toml`; [measured] `ls` of the clone |
| Age and activity | First commit 2026-11-12, last commit 2026-11-16: five days old on the day of this review. 21 commits. No release, no tag, no open issue | [measured] `git log --format='%H %ad %an %s' --date=iso`; [source] the issues page |
| Who maintains it | Three people at Hugging Face and an automated "Agent Manager" account appear in the history. No maintenance statement, no roadmap, no security policy, no contribution guide | [measured] `git log --format='%an' \| sort \| uniq -c`; [source] the repository page |
| Popularity | 558 stars, 48 forks | [source] the repository page, 2026-11-17 |
| Size | 528 Python files and 636,549 lines under `bot/`; the clone is 61 MB | [measured] `find bot -name '*.py' \| wc -l`; `find bot -name '*.py' -print0 \| xargs -0 cat \| wc -l`; `du -sh .` |
| Dependencies | None. `dependencies = []`; Python 3.8 or newer. The import statements name only the standard library (`re`, `random`, `string`, `datetime`, `copy`, `unicodedata`, `importlib`, `pkgutil`, `math`, `hashlib`, `ast`, `difflib` and a few more) | [code] `pyproject.toml`; [measured] `grep -rhoE '^(import\|from) [a-zA-Z_.]+' bot pybot.py \| awk '{print $2}' \| cut -d. -f1 \| sort \| uniq -c` |
| Model weights | None. Nothing to download | [code] `pyproject.toml`; [source] `README.md` |
| Network | The README says it needs "nothing else". No networking module is imported | [source] `README.md`; [measured] the import scan above. A full audit of 636,549 lines for hidden calls was not done |
| Speed, by its own account | "a few seconds to start ... and about a second to reply" on a CPU | [source] `README.md`; not measured here |
| Its tests | The README speaks of 550,000 lines of tests written by the agents. They are **not in the repository**: `tests/` holds one file of 161 lines that tests the command line only, and says "the bot's own tests live in the swarm's repository" | [measured] `find tests -name '*.py' -print0 \| xargs -0 cat \| wc -l`; [code] `tests/test_cli.py:1-6` |
| Where the code comes from | `bot/` is a copy of a commit of another repository that is not public ("The commit that `bot/` was copied from", `SOURCE_COMMIT`). One history entry reads "Remove the source repository's name from pybot.py" | [code] `pybot.py:20-21`; [measured] the `git log` above |

### 1b. How it works

- **One fixed loop.** Every module in `bot/modules/` may propose a reply to the line the user typed; one module, the
  arbiter, picks one. A module that raises an error is skipped, and "a turn never fails". [code] `bot/runtime.py:1-17`,
  `:84-120`.
- **The rules are patterns and tables.** 10,179 calls of `re.compile` and about 6,400 knowledge entries. An entry
  is a set of key words, a list of words to avoid, and a ready-made English answer. [measured]
  `grep -rc 're\.compile(' bot`, `grep -rcE '(^|[^_a-z])entry\(' bot/knowledge`, each summed; [code]
  `bot/knowledge/lookup.py:1-27`.
- **The matcher is strict on purpose.** A line needs two signals to be answered (a score of 4), a word may match a
  key word through one typing slip only when that reading is unique, and an "avoid" list stops a wrong card ("my
  chicken pox" does not get the roast-chicken answer). [code] `bot/knowledge/lookup.py:12-27`.
- **Errors are swallowed.** `except Exception` appears 475 times. This is by design for a chat that must always
  answer; it is the opposite of what a clinical system needs, where a failed step must be seen. [measured]
  `grep -rc 'except Exception' bot`, summed; [opinion] on the fit.
- **It is English only.** In all of `bot/` there are 52 Chinese or Japanese characters, all in one file about
  school study. [measured] a Python scan of `bot/**/*.py` for the ranges U+3040 to U+30FF and U+4E00 to U+9FFF.
- **Its health content is consumer advice for the United Kingdom.** For example the entry for gallstones tells the
  reader to go "to A&E the same day if it lasts more than about five hours". There are about 28,000 lines of safety
  and crisis handling. [code] `bot/knowledge/conditions.py:61-74`; [measured] `wc -l bot/modules/safety*.py`.
- **It knows nothing of trials.** A search of `bot/` for "clinical trial", "inclusion criteria", "SNOMED", "ICD-10"
  and "LOINC" finds nothing. [measured] `grep -rhoiE 'clinical trial|inclusion criteri\w+|snomed|icd-?10|loinc' bot`.

### 1c. How good it is, by its makers' own measure

- The benchmark is SmolTalkBench: 1,000 single-turn everyday chat prompts in English, with reference answers written
  by a large model. A judge model compares each reply with the reference. [source]
  <https://huggingface.co/datasets/HuggingFaceSwarms/SmolTalkBench>
- PyBot's "win rate" rose from 0 % to **26 %**, which its makers put "on par with" a 360-million-parameter model.
  [source] `README.md`. Read plainly: on everyday English chat, the thing it was built for, its reply is judged
  worse than the reference about three times in four. [opinion] on the reading.
- The makers warn that the small models it is compared with were trained on the benchmark's source, so their
  scores are inflated. [source] the same benchmark page.

**What this means.** PyBot is an honest and interesting experiment. Its lesson is about a **method** (many agents,
one fixed benchmark, thousands of small rule changes), not about a component that others can reuse. [opinion]

### 1d. The licence, and shipping it inside a signed offline box

- Apache-2.0 is permissive and passes TrialBox's licence gate, which flags only GPL, LGPL, AGPL, unknown and
  dual licences. [code] `tools/supply_chain/licences.py:1-17`.
- Running offline, on a CPU, with no weights, would suit the box. [source] `README.md`.
- **The obstacles are not legal; they are about assurance.** [opinion], resting on the facts below.
  - *It is not a package.* It is on no package index, so it cannot enter through `uv.lock` and the SBOM
    (`Makefile:588-616` [code]). It would have to be copied in as 636,549 lines of source.
  - *Nobody can review it.* TrialBox's own review counted its code as a figure to manage
    (`docs/reviews/2026-11-17-full-review.md`, area L [source]); this would add more lines than TrialBox has, written
    by agents, with its tests withheld and its origin repository private.
  - *It cannot be validated.* A clinical system must show what each part does and that it was tested. A part
    with 10,179 patterns, no shipped tests and errors swallowed by design gives no such record.
  - *It gives medical advice to the reader.* A hospital system that carries text telling a person when to go to
    A&E has a different intended use from a tool that lists trial candidates for an investigator.
  - *Copyright of agent-written code* is an open legal question in several countries. The Apache grant from Hugging
    Face is clear; what lies under it is not. This reviewer is not a lawyer.
  - *It is five days old* with no release and no stated maintenance.

---

## 2. Every place in TrialBox it could serve

For each use: what TrialBox does today, what PyBot would replace or add, the gain and how to measure it, the cost
and risk, and the verdict.

### 2a. Patient finding

**How TrialBox finds patients today** [code] `services/matching/cascade/engine.py:1-24`:

| Stage | What decides | Tier |
| --- | --- | --- |
| S0 scope and consent | SQL | Rules |
| S1 coded criteria | SQL generated from the approved criteria, three-valued (`services/criteria_compiler/compile_sql/generator.py:1-3`) | Rules, with terminology |
| S2 keyword pre-filter on note sentences | An approved lexicon and a table of English terms with their zh-TW and ja forms (`services/orchestrator/scenarios/terms.py:11-44`, 32 entries) | Terminology |
| S2b semantic screen | The embedder, threshold 0.12 (`services/matching/cascade/s2b_semantic.py:33-35`) | Small model |
| S3 note judge | The large model answers met, not met or unknown with a verbatim quote and date (`services/orchestrator/scenarios/evaluate.py:242`, `:446-476`) | Large model |
| S4 second opinion | A second, smaller model; any disagreement gives unknown (`libs/tb_common/pair.py:66-81`) | Second model |
| S5 a person | The review queue | Person |

**Cohort pre-filter.**
- Today: S0 and S1, pure SQL on the lake. On the 50,000-patient Japanese synthetic hospital, 30,369 patients were in
  scope and 1,193 passed the coded criteria. [source] `docs/plan/measurements/g1-2026-11-11/README.md:26`.
- PyBot adds: nothing. It has no notion of a record or a query.
- Verdict: **ignore.**

**Criteria matching (the compiler).**
- Today: the large model reads a protocol's criteria once per protocol (`ir_extract`,
  `services/criteria_compiler/service.py:565-567`); rules then check and repair its output for negation, active or
  past conditions, age units and polarity (`services/criteria_compiler/ir_extract/postprocess.py:1-17`); unchanged
  lines of an approved version are reused without the model (`service.py:884-888`); an investigator approves every
  rule set. [code]
- PyBot adds: nothing usable. Its patterns read lines such as "how long do I roast a chicken", not "eGFR below 30
  mL/min/1.73 m² within 28 days".
- Verdict: **ignore.** A deterministic first pass for simple criteria is worth a card of its own (section 3, D),
  with no link to PyBot.

**Note reading (the judge).**
- Today: S3 and S4 above. Rules already surround the model: sentence and section splitting for English, Chinese and
  Japanese (`services/matching/excerpts.py:59-95`, `:132-148`); a rule that a quote which is negated, about a
  relative, a risk or a "rule out" does not state the condition, in three languages
  (`services/matching/inferred.py:103-114`); the quote must be found in the note and dated inside the criterion's
  window (`services/matching/cascade/judge.py:317-341`). [code]
- PyBot adds: nothing direct. Its "understanding engine" (`bot/understanding/`, 25,026 lines [measured]) is about
  chat lines: typos, chat-speak, what "it" refers to. Its handling of negation reads sentences such as "can't you
  come earlier" (`bot/understanding/kinds.py:17-20` [code]), not "denies chest pain" or 「胸痛なし」.
- One idea is worth taking: its **two-signal rule and avoid lists** (`bot/knowledge/lookup.py:12-27` [code]).
  TrialBox's S2 is a plain substring hit (`services/matching/cascade/engine.py:843-845` [code]). An avoid context
  per term ("family history of", 家族歴) decided before the judge is the same idea, and TrialBox already holds the
  patterns in `matching/inferred.py`.
- Verdict: **learn from** (the matcher's design). **Do not adopt** the code.

**Retrieval of note excerpts.**
- Today: BM25 and embeddings, fused; Chinese and Japanese are indexed as character pairs
  (`services/lake/store.py:1682-1723`, `services/lake/textproc.py:8-25`). [code]
- PyBot adds: nothing; it has no retrieval over documents.
- Verdict: **ignore.**

**How to measure anything in this group** (for the cards of section 5, not for PyBot):

```
python -m tools.synth_hospital --profile ci --out "$TB_SCRATCH/synth"      # 5,000 patients, JP + TW sites, gold files
make e2e-cascade                                                           # the cascade on the fixture, stub model, no GPU
```

[code] `tools/synth_hospital/__init__.py:8-12`, `Makefile:469-470`. The stage log gives patients and pairs entering
and leaving each stage; the generator's `gold/notes.jsonl` gives the truth for note findings.

### 2b. Feasibility counts

- Today: one SQL query built from the approved criteria; no model at all (`model=NO_MODEL`,
  `services/orchestrator/scenarios/feas.py:105`; `services/orchestrator/scenarios/feas_compute.py:3-11`). [code]
- PyBot adds: nothing.
- Verdict: **ignore.** This use already sits on the lowest rung.

### 2c. Terminology mapping

- Today: a ladder of its own. Site lists, exact name, curated synonyms, a dictionary, ICD-10-CM blocks, the code
  systems loaded at install, and only last the large model choosing among the top 20 candidates, always flagged for
  review (`services/criteria_compiler/terminology/mapper.py:16-19`, `:456-536`). The candidate list is built by
  word overlap (`mapper.py:879-892`). [code]
- PyBot adds: no vocabulary of use (no SNOMED, ICD, LOINC, NHI or YJ codes [measured] the search of 1b). One idea:
  its **single-slip typo reader**, which accepts a misspelt word only when exactly one key word is one edit away
  (`bot/knowledge/lookup.py:19-27` [code]). TrialBox's word-overlap matcher finds nothing for "methotrexat".
  The standard library's `difflib` does the same job in a few lines.
- Gain: fewer names that reach the model step or come back unmapped. Measure: count the criteria concepts of the
  public rule sets under `tests/fixtures/open_data/rulesets/` that reach `concept_map` before and after (a short
  script over `Mapper.map`; no model needed).
- Risk: a wrong "nearest" drug or diagnosis name. Keep the result flagged for review, as the model step is.
- Verdict: **learn from** (one small idea). **Do not adopt.**

### 2d. De-identification

- Today: patterns, dictionaries and check digits, no model; Taiwanese and Japanese identifiers, names, phones and
  addresses (`libs/tb_common/phi_guard.py:1-5`, `:375`, `:847`; `services/guard/recognisers.py:1-9`). Notes are
  masked before they are indexed (`services/lake/store.py:1463`). [code]
- PyBot adds: nothing. It has no code that finds names or identifiers in a document.
- Verdict: **ignore.**

### 2e. Data connectors

- Today: declarative mappings for CSV, FHIR, SS-MIX2 and HL7; no model
  (`services/adapter/mapping/engine.py:1-4`). [code]
- PyBot adds: nothing.
- Verdict: **ignore.**

### 2f. User assistance

This is the one place where PyBot's kind of thing, a chat answered by rules, matches a TrialBox feature.

- Today, "Ask": the console writes the answer itself from rules and the site's readiness data; the model is asked
  only to re-phrase that draft, and on any error the draft is shown as it is
  (`services/console/site_pages.py:250-252`, `services/orchestrator/setup_api.py:521-543`). [code]
- Today, the command field: a line in the exact grammar runs with no model; free text goes to the model to be
  classified, and the user confirms (`services/channels/native/engine.py:52`). [code]
- PyBot adds: nothing as code. It is English only and knows nothing of TrialBox's pages. As a **design** it
  confirms what "Ask" already is: a help function can be rules alone.
- The useful question it raises: does "Ask" need the model at all? The draft is already the answer. Removing the
  re-phrasing step takes one model use off the governance list (`docs/reviews/2026-11-17-full-review.md`, area M,
  the table "Where a model is used" [source]), in three languages, at no clinical risk.
- A possible defect, **not confirmed**: the mapping reader reported that the prompt name `assist` has no row in
  `libs/tb_llm/v1_roles.yaml`, so that in production the call may always fail into the draft. This review confirmed
  only that `grep -n assist libs/tb_llm/v1_roles.yaml` prints nothing [measured]; it did not run the path.
- Verdict: **learn from.** Card J5-5.

### 2g. The EDC pre-fill

- Today: coded items are filled from lake rows by rules, each with a citation; only items whose source is a note go
  to the model, and a quote not found in the note is dropped; a person confirms and signs
  (`services/edc/prefill.py:6-20`, `:460-465`). [code]
- PyBot adds: nothing.
- Verdict: **ignore.** The rule extractors of card J5-3 would serve note items here too.

### 2h. Tests and evaluation

- Today: public suites and a synthetic hospital with gold files (`tools/trialbox/eval.py:1-15`,
  `tools/synth_hospital/__init__.py:1-15`, `eval/DATASETS.yaml`). [code]
- PyBot as a tool adds nothing. Its **method** is relevant, with two cautions.
  - The method: fix one benchmark, let many agents propose small rule changes, keep a change only if the score
    rises. [source] `README.md`. TrialBox has places where rules are data and a gold file exists: the S2 lexicon,
    the negation and family-history patterns, the PHI patterns, the terminology synonyms.
  - Caution one: the score climbed for 5,000 versions and stopped at 26 %, at a cost of 636,549 lines. Rules written
    to raise a score grow without limit. [source] `README.md`; [measured] the line count.
  - Caution two: rules tuned against a synthetic generator learn the generator. Any such loop needs a held-out set
    it never sees, and TrialBox's own records say no figure has yet been measured on what ships
    (`docs/plan/measurements/validation-reset-2026-11-14.md` [source]).
- Verdict: **learn from**, under the guard of card J5-7.

---

## 3. The straight answer on "reduce the need for the LLM"

**PyBot does not reduce it. The aim is right, and TrialBox is already most of the way there.**

### 3a. Where the ladder stands today

| Decision | Rules | Terminology | Small model | Large model |
| --- | --- | --- | --- | --- |
| Feasibility counts | all | code lists | – | – |
| Screening, coded criteria (S0, S1) | all | code lists | – | – |
| Screening, note criteria | pre- and post-checks only | S2 keywords route, they do not decide | S2b routes, it does not decide | **decides** (S3), checked by a second model (S4) |
| Compiling a protocol | repairs and checks | six steps before the model | – | **reads every new line**, once per protocol |
| Terminology mapping | – | six steps | – | last resort, always reviewed |
| De-identification, connectors | all | – | – | – |
| EDC pre-fill | coded items | code lists | – | note items only |
| "Ask", the command field | the draft; exact grammar | – | – | re-phrasing; free text |

[code] the files cited in section 2.

**How much is left for the model, in the one large run on record** (synthetic, Japanese, 50,000 patients) [source]
`docs/plan/measurements/g1-2026-11-11/README.md:21-26`; `docs/reviews/2026-11-17-full-review.md`, "What scales":

- 30,369 patients in scope; rules alone removed all but **1,193** (3.9 %).
- All 1,193 went on to the judge: S1 1,193, S3 1,193. The keyword stage removed nobody.
- 6,704 model calls in 8,584 seconds: about 1.3 seconds a call, 2.4 hours for the study.

So the model already sees about one patient in twenty-five. What remains is concentrated in one place.

### 3b. The decisions that could move down, in order of gain

**A. Note questions with no keyword hit (large model → terminology). The largest saving.**
- Today, in screening, every such pair is sent to the judge on purpose: "Screening spends its tokens: every zero-hit
  pair goes to the judge" (`services/orchestrator/scenarios/screen_cascade.py:613-615`, `absence_semantics=False`
  at `:639`). The list of criteria certified to skip the judge "is empty in screening"
  (`services/matching/cascade/engine.py:856`). [code]
- The machinery to move them exists: a criterion certified under rule CAS-13 takes "zero hits" as its answer
  directly after S2 (`engine.py:860-866`), and the recall certificate measures what such a rule misses
  (`eval/suites/recall_cert/`, `tools/recall_sim.py:1-12`). [code]
- What is missing is the evidence, per criterion and per language, that a complete term list misses no patient.
  The table of translated terms has 32 entries (`services/orchestrator/scenarios/terms.py:11-44` [code]).
- Clinical safety: this is the risky direction. A silent "no mention, so not present" is exactly how an eligible
  patient is lost. It must stay off for any criterion without a certificate, and inclusion criteria deserve a
  stricter bar than exclusions. [opinion]
- With PyBot or without: **without.**

**B. Facts that notes state in a fixed form (large model → rules).**
- Scores and numbers written the same way every time: ECOG, NYHA class, ejection fraction, smoking status,
  pregnancy. A Taiwanese hospital reports 99.98 % for rule-based numeric extraction from mixed Chinese and English
  reports. [source] `docs/research/2026-10_literature_competitors.md`, section 1.5 (E-Da cardiac CT).
- A rule extractor answers with the same quote and date the judge must give, so the existing quote and window
  checks apply unchanged. Where the rule finds nothing, the question goes to the judge as today: the rule can only
  save a call, never hide a patient.
- With PyBot or without: **without.**

**C. A small-model rung between the embedder and the judge (large model → small model).**
- A sentence-pair classifier, or the second model asked first, answers the clear cases; the large model sees the
  unclear ones. The literature file says no published study yet isolates such a cascade for screening
  (`docs/research/2026-10_literature_competitors.md`, section 1.3 [source]), so this is an experiment, not a
  known gain.
- It needs weights and a GPU, so it is written as a run, not done here (card J5-6).
- With PyBot or without: **without.**

**D. Simple criteria at compile time (large model → rules).**
- "Age 18 to 75", "female", "HbA1c 7.0 to 10.0 %" can be parsed by patterns before the model is asked.
- The saving in model calls is small, since a protocol is compiled once and unchanged lines are already reused.
  The real gain is that the same line always compiles the same way, and criteria extraction is the use the full
  review rates **High** risk (`docs/reviews/2026-11-17-full-review.md`, area M [source]).
- With PyBot or without: **without.**

**E. "Ask" (large model → rules).** Section 2f. The smallest saving in calls and the easiest to take.

**F. What should not move down.** [opinion]
- Free-text judgement in notes: "no evidence of active disease", a history told across three visits, a mixed
  Chinese and English sentence. This is what the large model is for, and the product already guards it with a quote,
  a second model and a person.
- Reading a full protocol's criteria. Rules can take the simple lines; the rest needs the model and the
  investigator's approval.
- A rule-only chatbot is the far end of this ladder. PyBot shows what that end costs: 636,549 lines for a 26 % score
  in one language.

### 3c. What a saving is worth

- **Time and hardware.** 2.4 hours for one study of 50,000 patients is within a night; the estimate for 500,000
  patients is 20 to 70 hours (`docs/reviews/2026-11-17-full-review.md`, "What scales" [source]). On the small tier,
  where one GPU swaps two models (`tools/tiers.py:9-15` [code]), each call avoided matters more.
- **Verification.** A decision made by a rule can be tested exhaustively and does not change when a model build
  changes. Each decision moved down is one less thing to re-run at every model update. This is the stronger reason.
  [opinion]
- **The price.** Each rule is code that someone must write in three languages, test and keep. Rules that exclude
  need the recall certificate. The saving is real only if card J5-1 shows where the calls go.

---

## 4. Verdict

| Use | Verdict | Why, in one line |
| --- | --- | --- |
| Cohort pre-filter | **Ignore** | Already SQL; PyBot has nothing here |
| Criteria matching | **Ignore** | No clinical or trial content |
| Note reading | **Learn from** | The two-signal and avoid-list matcher; not the code |
| Retrieval | **Ignore** | No document retrieval in it |
| Feasibility counts | **Ignore** | Already no model |
| Terminology mapping | **Learn from** | The single-slip typo rule; not the code |
| De-identification | **Ignore** | Nothing there |
| Data connectors | **Ignore** | Nothing there |
| User assistance | **Learn from** | Confirms "Ask" can be rules alone; English-only code is no use |
| EDC pre-fill | **Ignore** | Nothing there |
| Tests and evaluation | **Learn from** | The method, with a size budget and a held-out set |
| **Any use** | **Adopt: none** | English only, unreviewable size, no tests shipped, five days old, consumer medical advice |

**Overall recommendation.** Do not bring PyBot into TrialBox, as code or as a dependency. Take the owner's aim as
its own line in plan 9: "move decisions down the ladder, with evidence", starting with the measurement of card
J5-1 and then the zero-hit certificate of card J5-2. Record the decision in the reuse survey so the question is not
asked twice. [opinion]

---

## 5. Cards for plan 9

Sizes: S is days, M is one to two weeks, L is longer. Lanes are those of plan 8, section 8b. Every card runs on
synthetic or public data only.

| Card | What | Size | Lane | What must be measured first | Done when |
| --- | --- | --- | --- | --- | --- |
| **J5-1** | **The ladder report.** One command that prints, for a screening run, how many decisions each rung made: rules (S0, S1), terminology (S2 hits and zero hits), small model (S2b above and below), large model (S3 pairs, calls, tokens, seconds), second model (S4), person (S5); by criterion and by note language. It reads the stage log and metrics the cascade already writes (`services/matching/cascade/model.py:128-135`, `engine.py:1507-1508`) | S | H, with A2 | Nothing; this is the first measurement | The report exists for `make e2e-cascade` (stub, no GPU) and for the stored G1 and P2b runs; plan 9 quotes its figures instead of this review's |
| **J5-2** | **Zero-hit certificates.** For three to five note criteria of the house rule sets, build the complete term list in en, zh-TW and ja; measure on the synthetic hospital's gold what "zero hits, so absent" would miss; where the recall certificate passes, certify the criterion under CAS-13 so its zero-hit pairs skip the judge. Exclusions first; inclusions only under a stricter bound | M | A2, with H and E | J5-1 shows zero-hit pairs are a large share of S3. Then, per criterion and language: missed patients against `gold/notes.jsonl` (`python -m tools.synth_hospital --profile ci --out ...`), and the certificate's upper bound | A certified list is no longer "empty in screening"; the ladder report shows the calls saved; no certified criterion misses a gold patient; the owner has ruled on the bound |
| **J5-3** | **Rule extractors for fixed-form note facts**: ECOG, NYHA, ejection fraction, smoking status, pregnancy, in three languages. Each returns the judge's own shape (answer, verbatim quote, date), so the existing quote and window checks apply. No match means "ask the judge", never "absent" | M | A2 | Agreement with the stored judge replies of the public launch (offline, no GPU: `python -m tools.public_accuracy.replay ...` as in `docs/plan/measurements/p2b-review-2026-11-17.md`) and with the synthetic gold; share of S3 pairs these facts make up (J5-1) | Agreement is reported per fact and language; a fact goes live only above a threshold the owner sets; the EDC pre-fill's note items use the same extractors |
| **J5-4** | **S2 terms and contexts.** Grow the 32-entry term table from the display names of the code systems loaded at install (D-1028, D-1029); add an avoid context per term (negated, family, risk) taken from `services/matching/inferred.py`; accept one typing slip only when the reading is unique | S | A2, with E | S2 hit recall and precision per language on the synthetic gold, before and after | The table is generated, not typed; the before and after figures are in the ladder report |
| **J5-5** | **"Ask" without the model.** Confirm whether `/assist` reaches a model in production (the prompt name has no row in `libs/tb_llm/v1_roles.yaml`). Then either remove the re-phrasing step and show the rule-written draft, or add the row and a test. This reviewer recommends removing it | S | C2a | One request to `/assist` behind the gateway on the demo; read the `model` flag of the reply | The governance table lists one model use fewer, or the path has a test that proves the model answers |
| **J5-6** | **A small-model rung, as an experiment.** Ask the second model first, or a sentence-pair classifier, for S3 pairs; send to the large model only below a confidence bound. Offline replay on stored judged pairs first; a GPU run only if the replay shows a saving | M | H, with A2 | Replay on the stored pairs of G1 and P2b: share answered by the small rung, and its disagreement with the pair's final answer. If a GPU run follows: one part on the large tier, about 3 to 5 GPU hours; the whole G1 run cost about US$31.5 (`docs/plan/measurements/g1-2026-11-11/README.md:16`), so this is a fraction of that. Needs the owner's word before any weights are fetched or money is spent | A written result: calls saved against answers changed, per language. No product change in this card |
| **J5-7** | **A guard for rules written by agents.** Any rule table grown by an automated loop lands with: a gold test per language; a held-out set the loop never saw; a size budget per table; no error swallowed. Record in `docs/plan/design/05-open-source-reuse.md` that PyBot was assessed and not adopted, with a link to this page | S | R, with the integrator | Nothing | The guard is in the developing guide; the reuse survey has the row |

**Order.** J5-1 first and alone. J5-5 and J5-7 may run beside it; they depend on nothing. J5-2, J5-3 and J5-4 wait
for J5-1's figures, and J5-4 feeds J5-2. J5-6 is last and optional.

**A caution for plan 9.** These cards are additions to release 1.0's scope. Plan 8's rule is that verification
comes before new building. J5-1, J5-5 and J5-7 are small and help verification. J5-2, J5-3, J5-4 and J5-6 change how
screening decides, so they belong after the first qualification record, or among the candidates the owner may leave
out of 1.0. [opinion]

---

## 6. What could not be verified

1. **PyBot was not run.** The session's safety controls declined the command that would have executed the outside
   code, and this review did not work around that. Its behaviour on clinical text, in Chinese or Japanese, its start
   time and its memory use are therefore **read from code and its README, not measured**. The run, for whoever
   wants the figure, on a machine with no hospital data and no network:

   ```
   git clone https://github.com/huggingface/pybot && cd pybot && git checkout 7d63c7fb
   printf '%s\n' \
     'The note says: "Patient denies chest pain. No history of myocardial infarction." Has the patient had a myocardial infarction?' \
     'Inclusion criterion: age 18 to 75 years. The patient is 81. Does the patient meet the criterion?' \
     '患者有第二型糖尿病，糖化血色素 9.2%。是否符合 HbA1c 7.0% 到 10.0% 的收案條件？' \
     '患者は胸痛を否定している。心筋梗塞の既往はあるか？' \
     | /usr/bin/time -v python -m pybot -s 1 -v
   ```

   Estimate: under five minutes on any laptop, no GPU, no cost. Expected, from the code: general or fallback
   replies, none of them an eligibility answer. That expectation is an opinion until the run is done.
2. **No full security audit of PyBot.** The import scan found only standard-library modules; 636,549 lines were not
   read line by line for dynamic imports or file access.
3. **The swarm's process, its private source repository and its 550,000 lines of tests** were not available.
4. **The benchmark figures** (26 %, the comparison with small models) are the makers' own and were not reproduced.
5. **Stars, forks and issue counts** are as shown on 2026-11-17 and change daily.
6. **The `/assist` defect** in section 2f is a reading of code by a helper, confirmed here only by a `grep`; the path
   was not executed.
7. **Line numbers in sections 2 and 3** were gathered by two read-only helpers and spot-checked by this reviewer
   against master `15108f46` (about forty of them, including every quoted threshold and every line quoted in
   section 3). Lines not spot-checked may be off by a few.
8. **The G1 figures** (30,369, 1,193, 6,704 calls, 8,584 seconds) are quoted from the repository's own record of a
   synthetic run with a model pair that has no qualification record. They show proportions, not performance.
9. **The gains of cards J5-2 to J5-6 are not known.** No measurement of them was made here; that is what J5-1 is
   for.
10. **Copyright in agent-written code** was noted, not researched.
