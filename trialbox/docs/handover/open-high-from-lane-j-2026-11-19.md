# Two open High findings of lane J, registered by lane H (card H-55, 2026-11-19)

**Reader:** the people who build TrialBox

Lane H keeps the findings register. On PR #639 on 2026-11-19 the integrator ruled that lane H registers these two
findings of lane J, High ("Lane H: register it High with the four numbers"; "Lane H registers it High"). Lane J has
no findings file for either on master, so this page is their source. It quotes only what lane J's pages and the
lines on #639 establish; nothing here was measured by lane H. Both rows are lane J's to fix and are open
([findings.json](open-high-from-lane-j-2026-11-19/findings.json)). All data named here is synthetic.

## H55-01: a negated inclusion can compile as requiring what it forbids

On master an inclusion criterion that negates or forbids something can still compile as requiring it. Forms seen:
不可, 禁止, 不允許, "forbidden", exception forms; the bare 不 and 以外 in zh-TW; a negating prefix in every language
("Non-small cell lung cancer" with small cell coded). A patient can be wrongly listed; the reviewer's sheet (the
person approving the compiled criteria) is the only guard.

Lane J's fix 10A-1b (#1117, D-796) is on master. Its follow-up 10A-1c (#1180) is not: an independent review found five
regressions in it on 2026-11-19 at 11:49 UTC. The four numbers are master's misses as #1180's decision record states
them (D-1246, branch `agent/10A-1c-unnecessary-holds` at commit 65f0753c, not on master), each a count of synthetic
must-hold lines that master ran instead of holding for a person, quoted:

- "round 1, 186 must-hold lines: master missed 60, the head at 227466c3 missed 24";
- "round 2, 57 targeted must-hold lines: master missed 53, 227466c3 missed 49";
- "A second tester wrote 420 new lines, 267 must-hold, wider than negation. At 71e85bbc 72 of 194 and 40 of 73 were
  missed (master 121 and 62)".

So: 60 of 186, 53 of 57, 121 of 194 and 62 of 73 must-hold lines run on master. D-1246 says of its counts: "each
count below is about the lines it was measured on. None of them is a claim about the reader."

## H55-02: the lake can put one patient's record in another's place

Lane J's red of 2026-11-19 12:27 UTC on #639, taken by the integrator at 12:48 UTC as the highest priority and in
rc1's scope ("no tag without it"). On master the lake can attach one patient's order or diagnosis to another patient,
and the first is lost: the ids are not per patient. Lane J's decision record D-1253 (branch
`agent/lake-ids-per-patient` at commit 44973dfc, not on master) states the fault: "`Mapper.row_id` made the id of a
record from an id spec `{hid: <column>}` as `HMAC(site key, "<type>|<number>")`: the patient was not in it", and
"Two patients' order "RX1" were one id: the lake kept one MedicationRequest, under the second patient. The first
patient's was gone, with no error and no count." The fix is lane J's card "lake ids are per patient" (D-1253). All
data so far is synthetic.

## When these close

Lane H does not change these rows by hand. Each closes when its fix is on master and seen closed, by a later
`--add-from` form or a change of the register's tool; see the register's head.
