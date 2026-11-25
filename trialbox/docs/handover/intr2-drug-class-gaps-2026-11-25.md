# INT-R2: a drug class's gap reads unknown, never False

**Reader:** the integrator, the independent reviewer, and the people who build TrialBox

The integrator's builder, 2026-11-25, ordered by the owner (ring 0). The deep check on master `6c73db64`, row R2: a
drug class was one to three ATC prefixes, and a member outside them read False. Synthetic data only. Decision number
needed. The owner's decision while it was built: ship what the coding tree proves; what is not certain reads unknown,
never True and never False; the list to confirm does not block the pull request.

## The fault, on master

1. `services/criteria_compiler/terminology/src/synonyms.csv` gave each class listed codes and at most three prefixes.
   A code outside them was not a member (D-113 covers only a code inside a prefix and off the list).
2. A drug matched by its own name (methotrexate, colchicine) lost its class's rows at the mapper's exact-name step.
3. A duration criterion ("methotrexate for six months") read no family at all, in SQL or CQL: RA-BIO-INC-03,
   RA-BIO-INC-04, GZQO-INC-06, RA-JAK-INC-03.
4. A code coarser than a class's node (L04 for a class under L04AB) was not a member.

## Which direction is safe

| Criterion | A wrong False | A wrong True |
| --- | --- | --- |
| an exclusion on a drug (AD-MAB-EXC-01, GZQO-EXC-04, GZQO-EXC-11, ONC-OSI-EXC-01, RA-JAK-EXC-01) | the patient is let through: unsafe | an eligible patient is lost |
| an exclusion on a missing drug (RA-BIO-EXC-02, RA-BIO-EXC-03, RA-JAK-EXC-04) | an eligible patient is lost | says "protected" when not: unsafe |
| an inclusion on a drug | a candidate is silently lost | a wrong candidate is shown |

Either wrong answer is unsafe somewhere, so the only answer safe everywhere is unknown: the patient goes to the
investigator. No member was added (no new True). A code is False only under a branch the class excludes.

## What is built

The existing mechanism, a `family` row (SCR-01) and D-113's unknown. No new verdict, flag or match kind.

- **The definition is written from the other side.** `EXCLUDED` (in the test) is, per class, the branches certain to
  hold no member. The class's `family` rows in `synonyms.csv` are the complement of that over the ATC grammar, so a
  branch nobody placed, one the tree does not have yet included, is unknown by default. A test holds the rows equal to
  the complement. The rows are 1996, short prefixes only: no licensed code list and no names.
- `mapper.py`: a drug's own name keeps its family rows; `open_families` keeps a `family` row from making a Japanese
  ingredient stem a member (`postprocess.py` passes it).
- `compile_sql/generator.py`, `compile_cql/generator.py`: a duration atom reads an off-list family order in the window
  as unknown where the listed orders do not reach the days; an ATC code coarser than a family is inside it. In CQL the
  ATC families are one list.

`EXCLUDED` sits in the test because `synonyms.csv` feeds `tb_term_grouper`, whose `match` allows only `exact`, `prefix`
and `family`.

## The classes

Families count the ValueSet's prefixes (member prefixes and unknown ones). The listed codes of every class are the
same before and after.

| Class | Rule sets | Listed codes | Families before | After | Excluded branches (False) |
| --- | --- | --- | --- | --- | --- |
| anticoagulant | AD-MAB | 5 | 3 | 112 | A B01AC0 B01AC1 B01AC2 B02 B03 B06 C01 C02 C03 C04 C06 C07 C08 C09 C10 D G H J L M N P R S V |
| urate-lowering therapy | GOUT-COH, GZQO | 3 | 2 | 131 | A B C D G H J L M01 M02 M03 M04AC01 M05 M09 N P R S V01 V04 V06 V07 V08 V09 V10 V20 |
| colchicine | GZQO | 1 | 0 | 101 | A B C D G H J L M01 M02 M03 M04AA0 M04AB0 M05 M09 N P R S V |
| glp-1 receptor agonist | GZQO | 4 | 1 | 191 | A01 A02 A03 A04 A05 A06 A07 A09 A10AB0 A10AC0 A10AE0 A10BA0 A10BB0 A10BC0 A10BF0 A10BG0 A10BH0 A10BK0 A11 A12 A13 A14 A15 B C D G H J L M N P R S V |
| egfr tyrosine kinase inhibitor | ONC-OSI | 1 | 1 | 83 | A B C D G H J L01A L01B L01C L01D L02 L03 L04 M N P R S V |
| conventional synthetic dmard other than methotrexate | RA-BIO | 3 | 0 | 340 | A01 A02 A03 A04 A05 A06 A07A A07B A07C A07D A07EA A07EC02 A07F A07X A08 A09 A10 A11 A12 A13 A14 A15 A16 B C D01 D02 D03 D04 D06 D07 D08 D09 D10 D11 G H J01B J01C J01D J01E J01F J01G J01M J01R J01X J02 J04 J05 J06 J07 L01BA01 L01E L01F L02 L04AB L04AC L04AF L04AG L04AJ L04AL L04AX03 M01A M01B M02 M03 M04 M05 M09 N P02 P03 R S V |
| hbv antiviral prophylaxis | RA-BIO | 2 | 0 | 94 | A B C D G H J01 J02 J04 J05AA J05AB J05AC J05AD J05AE J05AG J05AH J05AJ J07 L01 L02 L04 M N P R S V |
| methotrexate | RA-BIO, RA-COH, RA-JAK | 1 | 0 | 191 | A B C D G H J L01A L01BA03 L01BA04 L01BA05 L01C L01D L01E L01F L02 L03 L04AA L04AB L04AC L04AD L04AE L04AF L04AG L04AH L04AJ L04AK L04AL L04AX01 L04AX02 L04AX04 L04AX05 L04AX06 L04AX07 L04AX08 L04AX09 L04AX10 L04AX11 M01A M01B M02 M03 M04 M05 M09 N P R S V |
| tb preventive therapy | RA-BIO, RA-JAK | 2 | 0 | 52 | A B C D G H J01A J01B J01C J01D J01E J01F J01G J01R J01X J02 J05 J06 J07 L M N P R S V |
| ra biologic | RA-COH | 3 | 1 | 294 | A B C01 C02 C03 C04 C05 C07 C08 C09 C10AA C10AB C10AC C10AD C10B D01 D02 D03 D04 D05 D06 D07 D08 D09 D10 G H J01 J02 J04 J05 J07 L01A L01B L01C L01D L01E L02 L04AA13 L04AD L04AE L04AF L04AH L04AK L04AX01 L04AX02 L04AX03 L04AX04 L04AX05 L04AX06 L04AX07 L04AX09 L04AX10 L04AX11 M01 M02 M03 M04 M09 N01 N03 N04 N05 N07 P R01 R02 R05 R06 R07 S02 S03 V |
| biologic dmard or jak inhibitor | RA-JAK | 6 | 2 | 308 | A B C01 C02 C03 C04 C05 C07 C08 C09 C10AA C10AB C10AC C10AD C10B D01 D02 D03 D04 D05 D06 D07 D08 D09 D10 G H J01 J02 J04 J05 J07 L01A L01B L01C L01D L01EA L01EB L01EC L01ED L01EE L01EF L01EG L01EH L01EK L01EL L01EM L01EN L01EP L02 L04AA13 L04AD L04AE L04AH L04AK L04AX01 L04AX02 L04AX03 L04AX04 L04AX05 L04AX06 L04AX07 L04AX09 L04AX10 L04AX11 M01 M02 M03 M04 M09 N01 N03 N04 N05 N07 P R01 R02 R05 R06 R07 S02 S03 V |

The Japanese name of anticoagulant takes the same rows. "jak inhibitor" is in no shipped rule set: unchanged, with its
gap. Sources: group names and codes L04A, L04AA, L04AC, L04AX, A10AE, A10B, A07EC, M01C, M04A, M04AC, L01, L01BA, L01E,
B01A, B01AD, J04A and J05A were read in the public ATC index (atcddd.fhi.no) on 2026-11-25. The other exclusions rest
on the main groups' and subgroups' well-known names, NOT read in the index for this card: confirm them with the list
below.

Two choices were also shaped by the shipped test patients: the statin branches (C10AA to C10AD, C10B) and the JAK group
are excluded one by one for the biologic classes rather than left unknown, so those patients' recorded answers stand.

## To confirm by a pharmacist (after ring 0; does not block)

| Class | Code or branch | Why uncertain | Reads today |
| --- | --- | --- | --- |
| ra biologic; biologic dmard or jak inhibitor | L04AA24, L04AC14, L04AC03 | index: abatacept, sarilumab, anakinra; likely members | unknown |
| the same | L01FA01, L01XC02 | rituximab now and in older releases; codes not read in the index | unknown |
| the same | rest of L04AC, L04AG, L04AJ, L04AL, L04AX08, L03, L01F, L01X | biologics that may not be RA drugs | unknown |
| the same | C10AX, D11, J06, M05, N02, N06, R03, S01 | hold antibodies for other diseases | unknown |
| biologic dmard or jak inhibitor | L01EJ, L01EX | JAK inhibitors for cancer | unknown |
| glp-1 receptor agonist | A10AE54, A10AE56, A10AE57 | insulin combinations (index; 57's name not shown) | unknown |
| glp-1 receptor agonist | A10AD, A10BD, rest of A10BX, A10X, A08, A16 | may hold combinations or newer agonists | unknown |
| urate-lowering therapy | M04AC51 | index: colchicine and probenecid | unknown |
| urate-lowering therapy | M04AX, V03 | enzymes that lower urate; codes not read in the index | unknown |
| colchicine | M04AC51, rest of M04AC, M04AX, combinations in M04AA and M04AB | combinations | unknown |
| methotrexate | L01BA01 | index: methotrexate; another use and dose | unknown |
| methotrexate | M01C, L01X, combinations in L01B and L04AX | not shown to hold none | unknown |
| conventional synthetic dmard | P01, M01C, L04AD, L04AK, L04AE, L04AH, rest of L04AA, rest of L04AX, L01A, L03, D05, J01A | older, regional or newer codes (leflunomide has no L04AA13 in today's index) | unknown |
| tb preventive therapy | J04 other than the two listed codes, J01M | other regimens | unknown |
| hbv antiviral prophylaxis | rest of J05AF, J05AR, J05AP, J05AX, J06, L03 | other antivirals and combinations | unknown |
| egfr tyrosine kinase inhibitor | rest of L01E, L01F, L01X | inhibitors with more than one target, older codes | unknown |
| anticoagulant | B01AB, B01AX, B01AD, B05, C05, combinations in B01AC | heparins and others; the protocol names warfarin and DOACs | unknown |
| every class | the excluded branches of the table above | each is a False | False |

## Tests and proof

`tests/unit/test_drug_class_gaps_intr2.py`: the invariants are `test_no_atc_code_at_all_reads_false_unless_its_branch_is_excluded`
(every string of the ATC grammar) and `test_no_code_of_the_terminology_reads_false_unless_its_branch_is_excluded` (every
level-5 code of the synthetic NHI list, the groupers and the TW Core value set). On master `6c73db64`: 76 failed, 2
passed. On the head: 78 passed. SQL runs on DuckDB. The CQL is generated, translated to ELM and checked as text: no
CQL engine was available here, so **no CQL was executed**.

The deep check's fixture was not available: the misses tested are its two kinds and the same gap elsewhere. The
synthetic NHI list was not extended; the tests name the codes themselves and read the TW Core list too.

## What the owner re-approves

The 15 ValueSets with their SQL, CQL and ELM, and RA-JAK's `terminology_release`, re-pinned to TR-db1c7b0d88ae (as D-906 did).

RA-JAK's criteria hash moves with its ValueSets. `test_study_manifest.py` still holds the old one (69ae60cd...); the
new one is `326a080bf6e9cc5dd04ffdc3f9f7ca76f38714ff1417d2edf60bc0d5a890cf73`. That assertion (and D-1366's copy) is not
changed: it waits for the integrator's ruling, and the test is red until then.

## How this fits with #1439 (V-18b)

It removes the shipped ATC table, adds exact rows and changes the displays of the same ValueSets. The family rows here
are one block away from its lines. The same generated files change: the second to land takes master's copies, then runs
`tools/build_terminology.py`, `python -m tools.build_rulesets --recompile`, and re-pins RA-JAK. Both touch
`mapper.py` (other lines). Its 1439-1 and 1439-2 (V18b-04) are answered here as unknown.

## Found, not fixed

- A medication with no ATC: D-130 turns an inclusion's False into unknown; an exclusion's False stands (unsafe).
- An ATC code in lower case or malformed is outside the grammar and reads False.
- The families make every class's answer unknown for a patient on any drug of an unplaced branch: more review work,
  not measured on real data.
- `refdata.in_set_via_map` reads a `family` row's code as a member; only diagnosis lists reach it.
