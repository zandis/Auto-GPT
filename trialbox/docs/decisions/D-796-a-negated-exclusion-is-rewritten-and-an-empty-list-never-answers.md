# D-796 A negated exclusion is rewritten, and a list with no code never answers

- **Task:** red of lane G's accuracy run on the real pair (#639, 2026-11-15, jmed); **Date:** 2026-11-15; **Status:** reserved
- **Decision:** (1) the compiler's post-process rewrites an exclusion whose whole logic is negated (an atom with quantifier `none`, or `not(x)`) to the positive form and flags it `negated_logic_rewritten` and `needs_review`; the review page shows the negated form beside it. A negation inside the logic and every inclusion are left alone. (2) A value set with no code and no code family (a concept the terminology could not map) cannot answer: the runtime reads the answer it would give as unknown, reason `code_system_not_carried` (D-795), on the cascade and the SQL engine.
- **Why:** jmed's "history of diabetes" compiled as "none of diabetes" over an empty list: TRUE for every patient, so every patient was excluded.
- **Test:** `tests/unit/test_negated_exclusion_and_empty_lists.py`.

## A negated inclusion with presence logic goes to a person (card 10A-1, 2026-11-18)

Review 15 (finding 2.3.1): "PRIOR CONCURRENT THERAPY: No prior chemotherapy or radiotherapy", an inclusion, compiled
to "any of chemotherapy", which the patients it should exclude meet; item (1) leaves inclusions alone and nothing else
compared a coded inclusion with its line. An inclusion (structured or mixed) whose logic asks the presence of a
concept is flagged `negated_inclusion_presence` and `needs_review` and goes to a person (not rewritten: a rewrite
could be wrong too) when its line carries any negation cue that is not explained. The rule fails safe: a cue is
explained only when it is shown to be about something else (a bound such as "no more than 2", "超えない", "無…大於";
a word the cue negates instead, "not responded", "増悪が認められない"; another concept the line names). The scope
reading (ConText's) only lets a line run; it never decides that a negated line is safe. An atom that compares a
value, counts or takes the latest result asks a measure, not a presence, and is never held.

An approved inclusion an incremental compile reuses gets the same check and flag, with a warning. An approved line
on `main` keeps running until a person recompiles and approves: `make negated-inclusion-scan`
(`criteria_compiler.negated_inclusions`) and the doctor's `negated_inclusions` (a WARN) list such lines by ruleset,
version and criterion, and change nothing; the offline install of a ruleset reports its hits. Cue lists:
`services/criteria_compiler/ir_extract/negation_scope.py` (English adapted from medspaCy's ConText rules, MIT).
Test: `tests/unit/test_negated_inclusion_never_compiles_as_presence.py` over `tests/fixtures/negated_inclusion/`.

## More negation words held; a cue over a list holds every concept in it (card 10A-1b, 2026-11-19)

Found on master: 10A-1 as merged did not know some negation words, so these inclusions ran as presence: "forbidden",
"contraindicated", "not to be given", "must be avoided", "other than X is allowed", "except X"; 不可, 禁止, 禁忌,
許可しない, Xを除き, X以外; 不允許, 不准, 禁止, 除X外 (8 of 91 lines in the lane J coordinator's independent set).
"No negated inclusion still runs" was true only of the phrasings measured then. And a cue over a list ran when the
other item was a concept candidate: "No prior chemotherapy or radiotherapy" with radiotherapy coded and chemotherapy
a candidate (12 of card 10A-1b's 40 new negated lines).

Now: (1) the words above, with their siblings, are cues in the three languages; a negated prohibition or a word that
only contains one ("not contraindicated", 禁止されていない, 禁忌なし, 不可欠, 不可或缺, 切除) is not. (2) Another
concept explains a cue only when it is not listed with the coded one under that cue (or, and, a comma, 、, 及び, 或,
";" and ":" before a cue after the list). (3) A cue in another clause (split by ";", a sentence end, "but", が、, て、,
但, 且; with the cue's clause first, only an adversative) is about something else only when its clause names another
extracted concept and the coded concept's clause carries no cue and is more than the concept alone. An object the
extractor did not name never releases a cue: it may be the coded concept by another name ("cytotoxic treatment",
化療). Every rule that lets a cue go is listed, with its shape, in `negation_scope.py` (R0 to R7), and is safe by
construction: none applies unless the line names the coded concept; where a cue reaches the coded concept (a list
goes on across commas and 、) nothing between them may be a list mark or another cue, and only a word the cue negates
joined by a link word ("no response to X") or, in Chinese, a verbal negator closing a 的 / 之 modifier ("未經治療的
肺癌") lets it go: "no poorly controlled X", "無控制不良的X", "無未控制之X、Y或Z", "コントロール不良のXがない" are held
(the lane J lead's independent measurement found the Chinese list form running at the previous head). (4) The
reused approved path reads the ruleset's ValueSet titles (each a candidate's name) as the line's other
concepts. (5) "No. 17" is a number. Measured, missed and held unnecessarily, before and after: card 10A-1's table
0/116 and 8/69, unchanged; the lines unseen at design 0/21 and 20/23, unchanged; card 10A-1b's 80 lines 12/40 and
18/40 to 0/40 and 17/40; the coordinator's 44 lines 22/36 and 5/8 to 0/36 and 0/8; P2b's stored `ir_extract` replies
(377 coded inclusions) 14 held, 6 unnecessarily, to 14 and 6 ("No. 17" runs; a line whose coded name is
written in another word order is held by R0). Exclusions are byte for byte the same with the rule on
and off. Lines: `tests/fixtures/negated_inclusion/card_10a1b.json`, `review_10a1b.json`.
