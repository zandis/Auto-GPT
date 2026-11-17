"""H-10 (lane H, #639): a criterion a person decides is never silent on the patient.

Under the stub, SCREEN listed 4,064 of 4,842 patients as "may meet the criteria" with nothing open, though three
criteria were for a person: the compiler makes a person's criterion with a question and no ``action`` (a line the
model gave no criterion for, D-912, or one whose SQL or CQL would not compile), and the status listed only actions.
Now each open person criterion leaves an item on the patient: its action, else its question, else that a person
decides it. The tier is unchanged (D-478: only criteria a person decides are open, so the patient stays "high").
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from matching import decision
from tb_contracts import CriterionVerdict

POLICY = decision.Policy(threshold=0.75, note_block=False)


def _c(cid: str, action: str | None = None, question: str | None = None) -> Any:
    return SimpleNamespace(id=cid, kind="inclusion", class_="human", action=action, human_question=question)


def _status(*crits: Any) -> decision.Status:
    by_id = {c.id: c for c in crits}
    vs = [CriterionVerdict(id=c.id, verdict="pending_human", basis="person", prov=[]) for c in crits]
    return decision.status_of(by_id, vs, POLICY)


def test_a_person_criterion_without_an_action_leaves_its_question() -> None:
    q = "The model gave no criterion for this line: check it by hand. Able to attend weekly visits"
    st = _status(_c("INC-07", question=q))
    assert st.tier == "high" and st.actions == [q]


def test_one_with_neither_says_a_person_decides_it() -> None:
    assert _status(_c("INC-08")).actions == ["a person decides INC-08"]


def test_an_action_stays_the_one_item() -> None:
    st = _status(_c("INC-06", action="ask about planned surgery", question="Planned surgery?"))
    assert st.actions == ["ask about planned surgery"]


def test_every_open_person_criterion_is_listed_once() -> None:
    st = _status(_c("A", action="ask"), _c("B", question="Q?"), _c("C"), _c("D", action="ask"))
    assert st.tier == "high" and st.actions == ["ask", "Q?", "a person decides C"]


def test_a_note_or_coded_answer_still_lists_only_its_action() -> None:
    note = SimpleNamespace(id="N", kind="inclusion", class_="note", action=None, human_question=None)
    v = CriterionVerdict(id="N", verdict="unknown", basis=None, prov=[])
    st = decision.status_of({"N": note}, [v], POLICY)
    assert st.tier == "review" and st.actions == [] and st.n_unknown == 1  # its unknown is counted, as before
