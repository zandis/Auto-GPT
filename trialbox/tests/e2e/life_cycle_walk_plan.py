"""H-20 (D-1135): the steps of the whole-life-cycle walk, and what the walk found, in one place.

H-10's new study (``tests/e2e/new_study_walk_plan.py``, steps 1 to 11, unchanged: protocol in, PI named, approval,
feasibility, screening, candidates), then the later half of the study's life on the same box in steps mode (D-1062:
demo mode off, the stub model, the synthetic hospital), each step done by the role that owns it in the permission
matrix (``libs/tb_common/authz_matrix.yaml``, row in :data:`OWNER_ROW`):

12. the coordinator opens the weekly page ("This week's patients") of the new study;
13. the investigator (the study's PI) opens the first patient there and marks Approach;
14. the coordinator records the contact outcome "reached, visit booked": the patient gets a screening number;
15. the coordinator takes the participant forward on its page: consent given, enrolled (D-134, D-399);
16. the coordinator records the participant's withdrawal (D-134);
17. the coordinator closes the study (D-386, D-763, D-779);
18. the coordinator reads the patient's chart number on the patient sheet (audited, D-143), for the opt-out;
19. the data steward records the patient's opt-out by that chart number (D-380, D-441);
20. the coordinator looks for the patient on the study's lists after the opt-out;
21. the data steward reads, in the audit trail, the opt-out worker's run after the opt-out: every clear of the erasure
    registry's §1 ran, none failed (D-441, D-465; H-25, D-1124);
22. the administrator reads the worker's health check: green.

Every text is a key of the console's own catalogue. Where the walk must find a thing another way than by a documented
label, the act names the finding (``F-nn``) and the walk records it as a guess; :class:`Stop` is a reasoned stop read
from the product. :data:`FINDINGS` is the findings list by step; ``docs/handover/life-cycle-walk-findings-2026-11-17.md``
holds its table as :func:`render_findings` writes it, and a fast test keeps them equal. The walk asserts what the
product documents and does; it never asserts a finding as correct.

    PYTHONPATH=libs:services:. python -m tests.e2e.life_cycle_walk_plan --plan en        # the browser's plan
    PYTHONPATH=libs:services:. python -m tests.e2e.life_cycle_walk_plan --write          # rewrite the findings table
    PYTHONPATH=libs:services:. python -m tests.e2e.life_cycle_walk_plan --summary LOG..  # runs' logs, summed up
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tb_common.retention import STUDY_YEARS_AFTER_CLOSE

from tests.e2e import new_study_walk_plan as nw
from tests.e2e.new_study_walk_plan import Do, K, Marked, Refuse, See, Step, T

ROOT = nw.ROOT
LANGS = nw.LANGS
VERSION = nw.VERSION
#: the life-cycle walk's own new ruleset ids (never H-10's: the two walks may share one box)
RULESETS = {"en": "LIFEWALK", "zh-TW": "LIFEWALKZH", "ja": "LIFEWALKJA"}
FINDINGS_PAGE = ROOT / "docs" / "handover" / "life-cycle-walk-findings-2026-11-17.md"
BEGIN = "<!-- life-cycle-walk: findings, written by tests/e2e/life_cycle_walk_plan.py; do not edit by hand -->"
END = "<!-- life-cycle-walk: end of findings -->"
SEVERITIES = ("blocks the step", "slows the tester", "cosmetic")
#: the lanes of the hand-over (docs/plan/38-handover-2026-11-15.md) and the integrator (D-1062's driver)
LANES = ("C2", "A2", "B2", "D", "E", "integrator")
#: the matrix row that lets the step's role do the step's action (libs/tb_common/authz_matrix.yaml)
OWNER_ROW = {
    12: "task.screen",
    13: "task.approach",
    14: "request.prepare",
    15: "study.setup",
    16: "study.setup",
    17: "study.state",
    18: "id.reveal",
    19: "optout.keep",
    20: "task.screen",
    21: "audit.browse",
    22: "ops.view",
}
#: H-25 (D-1124): the audit event of one run of the opt-out worker (D-441), and the clears of the erasure registry's
#: §1 that each run names (``docs/validation/erasure-registry.md``, written from ``tb_common.erasure``)
WORKER_EVENT = "optout.worker"
CLEARS = (
    "candidate_pool",
    "candidate_registry",
    "held_mail",
    "omop",
    "owed_tables",
    "pid_pending",
    "profile",
    "screening_log",
    "setup_uploads",
    "vec",
)
#: how long the walk waits for the worker's next run after the opt-out (it runs every minute on a demo box)
WORKER_WAIT_S = 240
#: the reason the coordinator types for the close (any text will do; a close takes one, D-386)
CLOSE_REASON = "end of the life-cycle walk"
#: the withdrawal reason the coordinator chooses: "1", the participant's decision (``life.reason.wd.1``)
WITHDRAW_REASON = "1"
#: the years a closed study's files are kept when the close names none (D-779): the day the close sheet names
CLOSE_YEARS = STUDY_YEARS_AFTER_CLOSE


@dataclass(frozen=True)
class Act:
    """A life-cycle act the H-10 vocabulary has no word for. ``kind``:

    * ``link_start``: a link whose name starts with ``text`` (the worklist's list links end with their count);
    * ``card_link``: the link ``text`` in the card whose heading is ``within`` (the home page's study card);
    * ``first_row_link``: the first row's link of the table ``data-testid=within`` (the tester picks a patient);
    * ``remember``: a value the product shows, kept for later steps as ``{label}``: from the address (``value`` a
      regular expression with one group) or from the element ``within`` (a CSS selector);
    * ``read``: a text the product shows, written to the log only (``within`` a CSS selector, ``label`` its name);
    * ``goto``: an address typed in (``value``).

    ``finding`` names the finding the act stands for: the walk records it as a guess on the step."""

    kind: str
    text: T | None = None
    label: str = ""
    value: str = ""
    within: str = ""
    finding: str = ""
    wait_s: int = 30


@dataclass(frozen=True)
class Stop:
    """A reasoned stop: when the page shows ``see`` (``kind`` and ``value`` as :class:`See`, or ``body``: the
    response's text holds ``value``), the step stops and the walk records ``finding`` with the page's own words.
    Later steps that stand on it (``Life.after``) are recorded as not walked; the walk itself does not fail."""

    kind: str
    value: str
    finding: str


@dataclass(frozen=True)
class LifeStep:
    """A life-cycle step: H-10's :class:`Step` with the life-cycle acts (:class:`Act`, :class:`Stop`) too."""

    n: int
    role: str
    acts: tuple[Do | See | Act | Stop, ...]
    refusals: tuple[Refuse, ...]
    what: dict[str, str]
    expect: dict[str, str]


@dataclass(frozen=True)
class Life:
    step: LifeStep
    lane: str
    after: tuple[int, ...] = ()


@dataclass(frozen=True)
class Finding:
    """One finding: the step and role, the page (path), what the page showed, what was expected and where that
    expectation comes from, the severity (:data:`SEVERITIES`) and the owning lane (:data:`LANES`). ``kind`` is the
    guess kind of the card (label, testid, address, confirmation, way back, required, language, term, other) or
    ``stop`` for a step the box could not complete."""

    id: str
    step: int
    role: str
    path: str
    kind: str
    showed: str
    expected: str
    source: str
    severity: str
    lane: str


def _w(en: str, zh: str, ja: str) -> dict[str, str]:
    return {"en": en, "zh-TW": zh, "ja": ja}


def _refuse(role: str, method: str, path: str, fields: tuple[tuple[str, str], ...], why: dict[str, str]) -> Refuse:
    return Refuse(role, method, path, fields, why)


LIFE: tuple[Life, ...] = (
    Life(
        LifeStep(
            12,
            "coordinator",
            (
                Do("nav", T("nav.week")),
                Do("link", T(None, prefix="{rs}")),
                See("h1", T("wb.title")),
                See("path", value=r"^/studies/[A-Z0-9]+/week$"),
                See("shown", value="worklist"),
                See("says", T("wb.crc_hint")),
            ),
            (
                _refuse(
                    "steward",
                    "GET",
                    "/studies/{rs}/week",
                    (),
                    _w(
                        "the steward cannot open the weekly page",
                        "資料管理員不能開啟本週名單",
                        "データスチュワードは今週のリストを開けない",
                    ),
                ),
            ),
            _w(
                "Open the new study's weekly page.",
                "開啟新試驗的本週病人頁面。",
                "新しい試験の今週の患者ページを開きます。",
            ),
            _w(
                "The worklist the screening made; the investigator decides there.",
                "篩選產生的清單；由主持人在此決定。",
                "スクリーニングで作られたリスト。判断は責任医師が行います。",
            ),
        ),
        "C2",
    ),
    Life(
        LifeStep(
            13,
            "investigator",
            (
                Do("nav", T("nav.week")),
                Do("link", T(None, prefix="{rs}")),
                See("h1", T("wb.title")),
                Act("first_row_link", within="worklist", finding="F-03"),
                Act("remember", label="pid", value=r"[?&]pid=([0-9a-f]{8,64})"),
                Do("button", T("mark.approach")),
                See("says", T("wb.done.approach")),
                Act("read", label="irb warning", within="[data-testid=irb-warning]"),
            ),
            (
                _refuse(
                    "coordinator",
                    "POST",
                    "/studies/{rs}/patients/{pid}/mark",
                    (("mark", "approach"),),
                    _w(
                        "the coordinator cannot mark Approach",
                        "研究協調員不能標記邀請",
                        "治験コーディネーターは「声をかける」を付けられない",
                    ),
                ),
            ),
            _w(
                "As the investigator: open the first patient of the weekly page and mark Approach.",
                "以主持人身分：開啟本週名單的第一位病人並標記「邀請」。",
                "治験責任医師として：今週のリストの最初の患者を開き、「声をかける」を付けます。",
            ),
            _w(
                "The mark is saved; the coordinator gets a task to contact the patient.",
                "標記已儲存；研究協調員收到聯絡病人的任務。",
                "判断が保存され、CRC に連絡タスクが届きます。",
            ),
        ),
        "C2",
    ),
    Life(
        LifeStep(
            14,
            "coordinator",
            (
                Do("nav", T("nav.week")),
                Do("link", T(None, prefix="{rs}")),
                Act("link_start", T("wb.list.approached"), finding="F-05"),
                Do("link", T("week.patient", (("p", "{short}"),))),
                Do("button", T("outcome.reached_booked")),
                See("says", T("wb.done.reached_booked")),
                See("shown", value="screening-no"),
                Act("remember", label="record", within="[data-testid=screening-no] .mono"),
            ),
            (
                _refuse(
                    "investigator",
                    "POST",
                    "/studies/{rs}/patients/{pid}/outcome",
                    (("outcome", "reached_booked"),),
                    _w(
                        "the investigator cannot record a contact outcome",
                        "主持人不能記錄聯絡結果",
                        "治験責任医師は連絡結果を記録できない",
                    ),
                ),
            ),
            _w(
                "Open the list of approved patients, the patient, and record: reached, visit booked.",
                "開啟已核准的清單與該病人，記錄：已聯絡，已預約。",
                "承認済みのリストとその患者を開き、「連絡がつき予約」を記録します。",
            ),
            _w(
                "The outcome is saved and the patient has a screening number.",
                "聯絡結果已儲存，病人取得篩選編號。",
                "連絡結果が保存され、患者にスクリーニング番号が付きます。",
            ),
        ),
        "C2",
        after=(13,),
    ),
    Life(
        LifeStep(
            15,
            "coordinator",
            (
                Do("nav", T("nav.studies")),
                Act("card_link", T("life.to.subjects"), within="{rs}", finding="F-07"),
                See("h1", T("life.subjects.title", prefix="{rs} · ")),
                Do("link", T(None, prefix="{record}")),
                See("h1", T("life.subjects.title", prefix="{record} · ")),
                Do("button", T("life.go.consented")),
                See("says", K("life.step.saved", (("state", "@life.state.consented"),))),
                Do("button", T("life.go.enrolled")),
                See("says", K("life.step.saved", (("state", "@life.state.enrolled"),))),
                Act("read", label="trail days", within="[data-testid=life-trail] tbody td.nowrap"),
            ),
            (
                _refuse(
                    "investigator",
                    "POST",
                    "/studies/{rs}/subjects/{record}/step",
                    (("to", "on_study"),),
                    _w(
                        "the investigator cannot record a participant's step",
                        "主持人不能記錄受試者的階段",
                        "治験責任医師は被験者の段階を記録できない",
                    ),
                ),
            ),
            _w(
                "Open the study's participants, the new one, and record: consent given, then enrolled.",
                "開啟試驗的受試者與新的受試者，記錄：已簽署同意，再記錄已收案。",
                "試験の被験者と新しい被験者を開き、「同意を得た」「登録した」を記録します。",
            ),
            _w("The participant is enrolled.", "受試者已收案。", "被験者が登録されます。"),
        ),
        "C2",
        after=(14,),
    ),
    Life(
        LifeStep(
            16,
            "coordinator",
            (
                Do("button", T("life.go.withdrawn")),
                See("shown", value="life-refused"),
                See("gone", value="confirm"),  # D-1153: without a reason it is refused before any sheet
                See("shown", value="step-reason-required"),
                Do("select", label=Marked("life.step.reason", hint="life.step.reason_required"), value=WITHDRAW_REASON),
                Do("button", T("life.go.withdrawn")),
                # D-1153 (the walk's F-11): the final step is named, with its reason, before it is recorded
                See("h1", T("confirm.title")),
                See(
                    "says",
                    K(
                        "life.confirm.final",
                        (
                            ("step", "@life.state.withdrawn"),
                            ("record", "{record}"),
                            ("reason", f"@life.reason.wd.{WITHDRAW_REASON}"),
                        ),
                    ),
                ),
                Do("button", T("confirm.yes")),
                See("says", K("life.step.saved", (("state", "@life.state.withdrawn"),))),
                See("says", K("life.subject.final", (("state", "@life.state.withdrawn"),))),
            ),
            (
                _refuse(
                    "investigator",
                    "POST",
                    "/studies/{rs}/subjects/{record}/undo",
                    (("note", "taken back by the walk"),),
                    _w(
                        "the investigator cannot undo a participant's step",
                        "主持人不能撤銷受試者的階段",
                        "治験責任医師は被験者の段階を取り消せない",
                    ),
                ),
            ),
            _w(
                "Record the participant's withdrawal (first without a reason, then with: the participant's decision), "
                "and confirm it on the sheet that says it is final.",
                "記錄受試者退出（先不選原因，再選：受試者決定），並在說明此為最終記錄的確認頁面確認。",
                "被験者の中止を記録します（まず理由なしで、次に「参加者の意思」で）。最終の記録だと示す確認画面で確定します。",
            ),
            _w(
                "Without a reason it is refused before any sheet; with one a sheet names the step, the participant and "
                "the reason and says it is final; after Yes the participant has finished: withdrawn.",
                "沒有原因時直接被拒絕，不出現確認頁面；選了原因後確認頁面列出階段、受試者與原因，並說明此為最終記錄；"
                "按「是」後受試者結束：退出。",
                "理由なしでは確認画面の前に拒否されます。理由を選ぶと確認画面に段階・被験者・理由と最終の記録である旨が"
                "表示され、「はい」で被験者は終了（中止）になります。",
            ),
        ),
        "C2",
        after=(15,),
    ),
    Life(
        LifeStep(
            17,
            "coordinator",
            (
                Do("more", T("setup.title", prefix="{rs} · ")),
                Do("link", T("sstate.link")),
                See("h1", T("sstate.title", prefix="{rs} · ")),
                Do("select", label=T("sstate.move"), value="closed"),
                Do("button", T("sstate.save")),
                # D-1153: a close without a reason is refused before any sheet
                See("shown", value="state-error"),
                See("says", T("sstate.need_reason")),
                See("gone", value="confirm"),
                Do("select", label=T("sstate.move"), value="closed"),
                Do("fill", label=Marked("sstate.reason", hint="sstate.reason_required"), value=CLOSE_REASON),
                Do("button", T("sstate.save")),
                Stop("shown", "close-refused", "F-00"),
                # D-1153 (the walk's F-15): the close is named, with the day its files are kept until, before it is made
                See("h1", T("confirm.title")),
                Act("remember", label="kept", value=r"(\d{4}-\d{2}-\d{2})", within="[data-testid=confirm-text]"),
                See("says", K("sstate.confirm.close", (("rs", "{rs}"), ("day", "{kept}")))),
                Do("button", T("confirm.yes")),
                See("says", K("sstate.changed", (("state", "@sstate.closed"),))),
                See("shown", value="state-kept-until"),
                See("says", K("sstate.kept_until", (("day", "{kept}"), ("years", str(CLOSE_YEARS))))),
                # D-1153 (the walk's F-16): kept until is the close's own site day plus the period
                Act("remember", label="since", value=r"(\d{4}-\d{2}-\d{2})", within="[data-testid=state-since]"),
                See("years", value="{since}+" + str(CLOSE_YEARS) + "={kept}"),
                Act("read", label="kept until", within="[data-testid=state-kept-until]"),
                Act("read", label="since", within="[data-testid=state-since]"),
            ),
            (
                _refuse(
                    "steward",
                    "POST",
                    "/studies/{rs}/state",
                    (("state", "closed"), ("reason", CLOSE_REASON)),
                    _w(
                        "the steward cannot close a study",
                        "資料管理員不能結束試驗",
                        "データスチュワードは試験を終了できない",
                    ),
                ),
                _refuse(
                    "operator",
                    "POST",
                    "/studies/{rs}/state",
                    (("state", "closed"), ("reason", CLOSE_REASON)),
                    _w("the administrator cannot close a study", "管理者不能結束試驗", "管理者は試験を終了できない"),
                ),
            ),
            _w(
                "Open the study's set-up, then its state, and close it (first without a reason, then with one), and "
                "confirm it on the sheet that names the day its files are kept until.",
                "開啟試驗設定，再開啟試驗狀態，結束試驗（先不填原因，再填寫原因），並在列出檔案保存期限的確認頁面確認。",
                "試験の設定から状態を開き、試験を終了します（まず理由なしで、次に理由を入れて）。ファイルの保存期限を示す"
                "確認画面で確定します。",
            ),
            _w(
                "Without a reason it is refused before any sheet; with one a sheet says the close is final and names "
                "the day the files are kept until; after Yes the study is closed, kept until that day: the close's "
                "own day plus five years.",
                "沒有原因時直接被拒絕，不出現確認頁面；填寫原因後確認頁面說明結束為最終狀態並列出檔案保存期限；按「是」後"
                "試驗結束，檔案保存至該日：結束當天加五年。",
                "理由なしでは確認画面の前に拒否されます。理由を入れると確認画面に終了が最終である旨とファイルの保存期限が"
                "表示され、「はい」で試験は終了し、その日（終了日から 5 年後）まで保存されます。",
            ),
        ),
        "C2",
        after=(16,),
    ),
    Life(
        LifeStep(
            18,
            "coordinator",
            (
                Do("nav", T("nav.week")),
                Do("link", T(None, prefix="{rs}")),
                Act("goto", value="/studies/{rs}/week?list=all&pid={pid}", finding="F-18"),
                Do("link", T("wb.full")),
                Do("select", label=T("reveal.reason"), value="contact"),
                Do("button", T("patient.reveal.audited")),
                See("shown", value="mrn"),
                Act("remember", label="chart", within="[data-testid=mrn] .mono", finding="F-17"),
            ),
            (),
            _w(
                "The patient asks to opt out: on the patient sheet, show the chart number for the steward.",
                "病人要求拒絕研究使用：在病人頁面顯示病歷號，交給資料管理員。",
                "患者がオプトアウトを申し出た：患者シートでカルテ番号を表示し、データスチュワードに渡します。",
            ),
            _w(
                "The chart number, shown once and recorded with your name.",
                "病歷號，只顯示一次並以您的名字記錄。",
                "カルテ番号（一度だけ表示され、あなたの名前で記録されます）。",
            ),
        ),
        "C2",
        after=(14,),
    ),
    Life(
        LifeStep(
            19,
            "steward",
            (
                Do("nav", T("team.optout.title")),
                See("h1", T("team.optout.title")),
                Do("fill", label=T("team.optout.chart"), value="{chart}"),
                Do("button", T("team.optout.save")),
                See("says", T("team.optout.done.added")),
                Act("remember", label="optouts", within="[data-testid=optout-n]"),
            ),
            (
                _refuse(
                    "coordinator",
                    "POST",
                    "/site/opt-outs",
                    (("pid", "{pid}"), ("source", "office")),
                    _w(
                        "the coordinator cannot record an opt-out",
                        "研究協調員不能登記拒絕研究使用",
                        "治験コーディネーターはオプトアウトを登録できない",
                    ),
                ),
                _refuse(
                    "operator",
                    "GET",
                    "/site/opt-outs",
                    (),
                    _w(
                        "the administrator cannot open the opt-out register",
                        "管理者不能開啟拒絕研究使用登記",
                        "管理者はオプトアウト登録を開けない",
                    ),
                ),
            ),
            _w(
                "As the data steward: record the patient's opt-out by the chart number.",
                "以資料管理員身分：以病歷號登記病人拒絕研究使用。",
                "データスチュワードとして：カルテ番号で患者のオプトアウトを登録します。",
            ),
            _w(
                "Recorded: the patient leaves screening, every list and later exports.",
                "已登記：病人自篩選、所有名單與之後的匯出中移除。",
                "登録され、患者はスクリーニング、すべてのリスト、以後の出力から外れます。",
            ),
        ),
        "C2",
        after=(18,),
    ),
    Life(
        LifeStep(
            20,
            "coordinator",
            (
                Do("nav", T("nav.week")),
                Do("link", T(None, prefix="{rs}")),
                Act("goto", value="/studies/{rs}/week?list=all&pid={pid}", finding="F-18"),
                See("gone", value="row-{short}"),
                Do("link", T("team.cand.title")),
                See("h1", T("team.cand.title", prefix="{rs} · ")),
                See("gone", value="cand-{short}"),
                See("shown", value="optout-count"),
            ),
            (),
            _w(
                "Look for the patient on the study's weekly list and candidate list.",
                "在試驗的本週名單與候選者名單中尋找該病人。",
                "試験の今週のリストと候補者リストで、その患者を探します。",
            ),
            _w(
                "The patient is on neither; the candidate list counts the opt-outs.",
                "兩份名單都沒有該病人；候選者名單顯示拒絕人數。",
                "どちらにもいません。候補者リストにはオプトアウトの数が出ます。",
            ),
        ),
        "C2",
        after=(19,),
    ),
    Life(
        LifeStep(
            21,
            "steward",
            (
                Do("nav", T("nav.audit")),
                See("h1", T("audit.title")),
                Do("select", label=T("audit.filter.event"), value=WORKER_EVENT),
                Do("button", T("audit.filter.go")),
                Act("worker_ran", label="optouts", value=",".join(CLEARS), finding="F-22", wait_s=WORKER_WAIT_S),
            ),
            (
                _refuse(
                    "coordinator",
                    "GET",
                    "/audit",
                    (),
                    _w(
                        "the coordinator cannot read the site's audit trail",
                        "研究協調員不能讀取全院稽核軌跡",
                        "治験コーディネーターは院内の監査証跡を読めない",
                    ),
                ),
            ),
            _w(
                "As the data steward: in the audit trail, read the opt-out worker's run after the opt-out.",
                "以資料管理員身分：在稽核軌跡中查看登記後拒絕研究使用處理的執行。",
                "データスチュワードとして：監査証跡で、登録後の利用拒否処理の実行を確認します。",
            ),
            _w(
                "A run that counts the new opt-out and names every store of the erasure registry, none failed.",
                "一次執行，計入新的拒絕，列出清除登記表的每個儲存區，沒有失敗。",
                "新しいオプトアウトを数え、消去台帳のすべての保存先を挙げ、失敗のない実行。",
            ),
        ),
        "B2",
        after=(19,),
    ),
    Life(
        LifeStep(
            22,
            "operator",
            (
                Act("goto", value="/metrics", finding="F-21"),
                See("body", value='tb_health_check_level{check="optout_worker"} 0'),
            ),
            (
                _refuse(
                    "coordinator",
                    "GET",
                    "/metrics",
                    (),
                    _w(
                        "the coordinator cannot read the box's health figures",
                        "研究協調員不能讀取系統健康指標",
                        "治験コーディネーターはボックスの健全性指標を読めない",
                    ),
                ),
            ),
            _w(
                "As the administrator: read the opt-out worker's health check.",
                "以管理者身分：查看拒絕研究使用處理的健康檢查。",
                "管理者として：利用拒否処理の健全性チェックを確認します。",
            ),
            _w(
                "The check is green (level 0).",
                "檢查為綠色（等級 0）。",
                "チェックは緑（レベル 0）。",
            ),
        ),
        "C2",
        after=(21,),
    ),
)

#: the findings by step. ``F-00`` is the reasoned stop of the close that the product documents (D-763: a study
#: with a participant on study or an open serious AE stays open); it is not a fault and is never in the table.
FINDINGS: tuple[Finding, ...] = (
    Finding(
        "F-01",
        12,
        "coordinator",
        "/studies/{rs}/week",
        "term",
        'Help on the weekly page tells the coordinator to "mark Approach, Need info or Not suitable now"; the '
        "page gives the coordinator no mark (it says the investigator decides there)",
        "help that matches the role reading it",
        "`help.page.week`, `docs/guides/coordinator.en.md` (This week's patients); the matrix row `task.approach`",
        "slows the tester",
        "C2",
    ),
    Finding(
        "F-02",
        13,
        "investigator",
        "/studies/{rs}/week",
        "term",
        'the button reads "Approach" (邀請, 声をかける); after it the page says "Approved. The coordinator has '
        'a task…" (已核准, 承認しました)',
        "one word for the mark",
        "`mark.approach`, `wb.done.approach`, `help.page.week`",
        "cosmetic",
        "C2",
    ),
    Finding(
        "F-03",
        13,
        "investigator",
        "/studies/{rs}/week",
        "label",
        'patients are named by an 8-character pseudonym only ("patient 1a2b3c4d"); a tester told to take "a '
        'patient" must pick one; the walk takes the first row of the list the page opens on',
        "a testers' page that names which patient to take",
        "D-1062 (the testers walk from the first step)",
        "cosmetic",
        "C2",
    ),
    Finding(
        "F-04",
        13,
        "investigator",
        "/studies/{rs}/week",
        "other",
        'a warning on a new study: "Check before approaching: marking Approach now is recorded as an '
        'override" (no IRB approval date, no consent-form version); no step of the new-study walk asks for the '
        "IRB record",
        "the new study's steps lead to the IRB record before the first Approach, or the warning says where",
        "D-147, D-399; `docs/handover/new-study-walk.en.md`",
        "slows the tester",
        "C2",
    ),
    Finding(
        "F-05",
        14,
        "coordinator",
        "/studies/{rs}/week",
        "label",
        'the approved patient is on the list "Approved and contacted" before anyone contacted them; the page '
        'opens on another list, and the list link\'s name ends with its count ("Approved and contacted1"), so '
        "it is found by the start of its name",
        "a list named for what it holds",
        "`wb.list.approached`; `help.role.coordinator` (record contact outcomes)",
        "slows the tester",
        "C2",
    ),
    Finding(
        "F-06",
        14,
        "coordinator",
        "/studies/{rs}/week",
        "other",
        "the five contact outcome buttons are on the page twice for the approved patient (a folded quick form in "
        "the row, and the panel)",
        "one form per action on a page",
        "D-178 (two taps, one place)",
        "cosmetic",
        "C2",
    ),
    Finding(
        "F-07",
        15,
        "coordinator",
        "/studies/{rs}/week",
        "way back",
        "after the outcome the screening number shows on the patient panel, but no link there leads to the "
        'participant; the walk goes back to My studies and the study card\'s "Participants"',
        "a link from the screening number to the participant's page",
        "D-134 (the participant from candidate to the end)",
        "slows the tester",
        "C2",
    ),
    Finding(
        "F-08",
        15,
        "coordinator",
        "/studies/{rs}/subjects",
        "way back",
        '"Participants" and "Study state and identifiers" are not in the More menu, and Help on both pages '
        'says only "Use the command field above, or More, to find any page"; the coordinator\'s guide lists '
        "neither page",
        "each page in the role's guide and Help with its own text",
        "`docs/guides/coordinator.en.md` (Your pages), `help.page.other`, D-104",
        "slows the tester",
        "C2",
    ),
    Finding(
        "F-09",
        15,
        "coordinator",
        "/studies/{rs}/subjects/{record}",
        "term",
        'one participant\'s page is headed "<number> · Participants" (the list\'s title); "Participant {r}" '
        "is only in the browser tab",
        "the heading names one participant",
        "`life.subject.title`",
        "cosmetic",
        "C2",
    ),
    Finding(
        "F-10",
        15,
        "coordinator",
        "/studies/{rs}/subjects/{record}",
        "other",
        "on a box started with `--day data` the steps TrialBox makes itself (candidate, approached) are dated the "
        "real day (2026-11-17) and the steps a person records are dated the box's day (2026-11-02): the trail "
        "shows consent before approach",
        "one day for the box",
        "D-399 (date order), `tools/demo.py` (`--day data` keeps a frozen clock)",
        "cosmetic",
        "C2",
    ),
    Finding(
        "F-12",
        16,
        "coordinator",
        "/studies/{rs}/subjects/{record}",
        "term",
        'in English "Withdraw" is the participant\'s withdrawal here and "Withdraw my mark" (taking back a '
        "mark) on the patient sheet; zh-TW and ja use two words",
        "two words for two actions",
        "`life.go.withdrawn`, `mark.withdraw`",
        "cosmetic",
        "C2",
    ),
    Finding(
        "F-13",
        18,
        "coordinator",
        "/studies/{rs}/patients/{pid}",
        "other",
        'after the withdrawal and the close the patient sheet still offers the contact outcomes "Not '
        'approached (physician)" and "Lost contact" (registry: withdrawn)',
        "no contact step for a finished participant of a closed study",
        "D-763 (nobody goes back on study)",
        "cosmetic",
        "C2",
    ),
    Finding(
        "F-17",
        18,
        "steward",
        "/site/opt-outs",
        "other",
        'the opt-out form asks for the chart number ("Type the chart number"); no page of the steward shows '
        "one, so on a box the tester must get it elsewhere; the walk has the coordinator show it on the patient "
        "sheet (recorded) and carries it over",
        "the testers' page says where the chart number comes from on a box",
        "`team.optout.help`, `help.page.optouts`; D-1062",
        "slows the tester",
        "C2",
    ),
    Finding(
        "F-18",
        18,
        "coordinator",
        "/studies/{rs}/week",
        "address",
        'after the withdrawal the patient is on none of the weekly page\'s lists but "All on the list" (4,000 rows, '
        "paged), and the participant's page has no link to the patient sheet; the walk types `?list=all&pid=...` "
        "here and in step 20",
        "a search by pseudonym or screening number, or a link from the participant to the patient sheet",
        "D-133 (the weekly page)",
        "cosmetic",
        "C2",
    ),
    Finding(
        "F-19",
        19,
        "steward",
        "/site/opt-outs",
        "term",
        "the opt-out form's note is labelled \"Note for the coordinator\" (the PI's mark note) on the steward's "
        "register",
        "a label of the register's own",
        "`mark.note`, `team.optout.help`",
        "cosmetic",
        "C2",
    ),
    Finding(
        "F-21",
        22,
        "operator",
        "/admin?tab=health",
        "address",
        "the red opt-out worker check is on `/metrics` only (typed in); the administrator's Health tab shows no "
        "line for it",
        "the health line turns red on a stale or failed tick, where a person reads it",
        "D-441, T-209a",
        "slows the tester",
        "C2",
    ),
    Finding(
        "F-22",
        21,
        "steward",
        "/audit",
        "other",
        'the audit trail shows each run of the opt-out worker ("Opt-out worker run") with an empty detail: what '
        "it cleared, whether a clear failed and whether a store still holds the patient are recorded in the audit log "
        "but on no page; a steward cannot see that an erase completed",
        "the run's counts on the page: the stores cleared, failed, left (they are counts, never a pseudonym)",
        "D-441 (one `optout.worker` event per run); `services/console/audit_page.py` `SHOWN` (the keys the browser "
        "shows); D-451",
        "slows the tester",
        "C2",
    ),
    Finding(
        "F-23",
        10,
        "coordinator",
        "/pilot/jobs/{job}",
        "language",
        "SCREEN of a study in start-up is taken as a job that fails at its first check; on every page the reason is "
        "the orchestrator's English (\"Study … is startup: lists run only for an open study. The study coordinator "
        "changes the state on the study's set-up page.\"), the state named by its code, not as the page names it "
        '("Start-up", 準備中)',
        "the reason in the page's language, the state by its name",
        "D-386 (lists only for an open study), D-1153; `sstate.startup`; `orchestrator/scheduler.py` (`require_open`)",
        "slows the tester",
        "C2",
    ),
    Finding(
        "F-24",
        10,
        "coordinator",
        "/pilot/jobs/{job}",
        "way back",
        'the failed job sends the coordinator to "the study\'s set-up page" but has no link to it, and the state is '
        'changed one page further, on "Study state and identifiers"; the walk goes Reports, the study\'s report, '
        "More, set-up, state",
        "a link from the reason to the page that opens the study",
        "D-386, D-1153; D-178 (the next step in one place)",
        "slows the tester",
        "C2",
    ),
    Finding(
        "F-25",
        9,
        "coordinator",
        "/studies/{rs}/setup",
        "term",
        "Open is refused until the coordinator chooses \"this study's type for serious adverse event reporting on the "
        'set-up page"; set-up has no field of that name: the section is "SAE reporting rules", its field "Rule set", '
        'its button "Save and confirm"',
        "one name for the field in the refusal and on set-up",
        "`sstate.sae_type`, `sae.setup.title`, `sae.setup.field`; D-415",
        "cosmetic",
        "C2",
    ),
)
#: the findings the walk no longer sees, since the product changed: their ids are not used again (id, step, the
#: decision that changed the product, what the walk sees now and asserts)
FIXED: tuple[tuple[str, int, str, str], ...] = (
    (
        "F-11",
        16,
        "D-1153",
        'the Reason label says "Required to withdraw or to record a screen failure"; without a reason Withdraw is '
        "refused before any sheet; with one a confirmation sheet names the step, the participant and the reason and "
        "says it is final, and only Yes records it",
    ),
    (
        "F-14",
        17,
        "D-1153",
        "the new study is in start-up when its protocol is sent; Open is refused until its type for SAE reporting is "
        "chosen (D-415), and SCREEN fails until it is open (steps 9 and 10)",
    ),
    (
        "F-15",
        17,
        "D-1153",
        "Change state to Closed shows a confirmation sheet that says the close is final and names the day the files "
        "are kept until; only Yes closes the study",
    ),
    (
        "F-16",
        17,
        "D-1153",
        "the day on the sheet and on the state page is the close's own site day plus five years",
    ),
    (
        "F-20",
        21,
        "D-1124",
        "the steps-mode box starts the opt-out worker; the steward reads its run after the opt-out in the audit trail, "
        "and its record in the box's audit log names every clear of the erasure registry, none failed or left",
    ),
)

#: the steps a steps-mode box cannot complete, and what the product needs that the box does not have
NOT_COMPLETED: tuple[tuple[int, str, str], ...] = (
    (
        15,
        "consent recorded on TrialBox's consent form (D-399)",
        "a study set up to record consent in TrialBox (set-up, Consent); the walk's new study keeps the default, "
        '"Not recorded", so "Consent given" is one button and the consent form, its version check and the '
        "re-consent list are not walked",
    ),
    (
        15,
        "on study, visits, completion (D-134)",
        'a visit schedule ("This study has no visit schedule yet"): the walk goes from enrolled to withdrawn',
    ),
    (
        17,
        "the morning mails of a closed study (D-763)",
        "outside mail: the box's mail gateway is in process with no outside mail",
    ),
)


def all_steps() -> tuple[Step | LifeStep, ...]:
    return (*nw.STEPS, *(lf.step for lf in LIFE))


def finding(fid: str) -> Finding:
    return next(f for f in FINDINGS if f.id == fid)


# ---------------------------------------------------------------------------------------------- the browser's plan
def _resolve(lang: str, rs: str, t: T | None) -> str:
    return "" if t is None else t.text(lang, rs)


def plan_json(lang: str, rs: str, accounts: dict[str, str], log: str = "") -> dict[str, Any]:
    """H-10's plan for ``lang`` and ``rs`` (steps 1 to 11, as H-10's walk has them), then the life-cycle steps,
    every text resolved as the product writes it; ``log`` is the JSON file the walk writes (outside the repo)."""
    plan = nw.plan_json(lang, rs, accounts)

    def fill(s: str) -> str:
        return s.replace("{rs}", rs).replace("{v}", VERSION)

    for st in plan["steps"]:
        st.update(key=f"new-study-{st['n']}", lane="C2", after=[], guesses=[])
    for lf in LIFE:
        st = lf.step
        acts: list[dict[str, Any]] = []
        for a in st.acts:
            if isinstance(a, See):
                acts.append({"do": "see", "kind": a.kind, "text": _resolve(lang, rs, a.text), "value": fill(a.value)})
            elif isinstance(a, Stop):
                acts.append(
                    {
                        "do": "stop",
                        "kind": a.kind,
                        "value": a.value,
                        "finding": a.finding,
                        "why": finding(a.finding).showed
                        if a.finding != "F-00"
                        else "the product refuses the close (D-763)",
                    }
                )
            elif isinstance(a, Act):
                acts.append(
                    {
                        "do": a.kind,
                        "text": _resolve(lang, rs, a.text),
                        "label": a.label,
                        "value": fill(a.value),
                        "within": fill(a.within),
                        "finding": a.finding,
                        "guess": finding(a.finding).showed if a.finding else "",
                        "wait_s": a.wait_s,
                    }
                )
            else:
                acts.append(
                    {
                        "do": a.kind,
                        "text": _resolve(lang, rs, a.text),
                        "label": _resolve(lang, rs, a.label),
                        "value": fill(a.value),
                        "within": fill(a.within),
                        "wait_s": a.wait_s,
                    }
                )
        plan["steps"].append(
            {
                "n": st.n,
                "key": f"life-{st.n}",
                "role": st.role,
                "lane": lf.lane,
                "after": list(lf.after),
                "guesses": [{"kind": "language", "detail": g} for g in untranslated(st, lang)],
                "acts": acts,
                "refusals": [
                    {
                        "role": r.role,
                        "method": r.method,
                        "path": fill(r.path),
                        "fields": {k: fill(v) for k, v in r.fields},
                    }
                    for r in st.refusals
                ],
            }
        )
    plan["log"] = log
    return plan


def texts_of(step: Step | LifeStep) -> list[T]:
    out: list[T] = []
    for a in step.acts:
        for t in (getattr(a, "text", None), getattr(a, "label", None)):
            if isinstance(t, T):
                out.append(t)
    if step.refusals:
        out.append(nw.FORBIDDEN_PAGE)
    return out


def untranslated(step: Step | LifeStep, lang: str) -> list[str]:
    """The texts of ``step`` the product has no ``lang`` form of (a zh-TW or ja page shows them in English)."""
    return [f"{t.key}: no {lang} form, shown in English" for t in texts_of(step) if t.key and lang in t.missing()]


# ---------------------------------------------------------------------------------------------- the findings page
def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def render_findings() -> str:
    """The generated part of the findings page: the walk by step (from :data:`SUMMARY`, the runs' logs summed up:
    the page, the clicks from the previous step's page and their texts in en, the median time, the refusals), then
    the findings by step (the role, the page, the clicks, what a tester would have had to guess, what was expected
    and where that comes from, the severity and the owning lane), then the findings the walk no longer sees
    (:data:`FIXED`)."""
    out = [BEGIN, "", "### The walk by step", ""]
    out += ["| Step | Role | Page reached (en) | Clicks | The clicks (en) | Median s | Refused (403) | Guesses |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for lf in LIFE:
        n = lf.step.n
        sm = SUMMARY.get(n, {})
        refused = "; ".join(f"{r.role}: `{r.method} {r.path}`" for r in lf.step.refusals) or "–"
        out.append(
            f"| {n} | {lf.step.role} | `{sm.get('path', '')}` · {_cell(sm.get('heading', ''))} | {sm.get('clicks', '')}"
            f" | {_cell(' → '.join(sm.get('click_texts', [])))} | {sm.get('seconds', '')} | {_cell(refused)} | "
            f"{', '.join(sm.get('guesses', [])) or '–'} |"
        )
    out += ["", "### The findings by step", ""]
    out += ["| Id | Step | Role | Page | Clicks | What a tester would have had to guess | Expected (from) | "
            "Severity | Lane |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for f in sorted(FINDINGS, key=lambda f: (f.step, f.id)):
        clicks = SUMMARY.get(f.step, {}).get("clicks", "")
        out.append(
            f"| {f.id} | {f.step} | {f.role} | `{f.path}` | {clicks} | {_cell(f.showed)} | "
            f"{_cell(f.expected)} ({_cell(f.source)}) | {f.severity} | {f.lane} |"
        )
    out += ["", "### The findings the walk no longer sees", ""]
    out += ["| Id | Step | Changed by | What the walk sees now and asserts |", "| --- | --- | --- | --- |"]
    for fid, step, by, now in FIXED:
        out.append(f"| {fid} | {step} | {by} | {_cell(now)} |")
    out += ["", END]
    return "\n".join(out)


def block_of(page: str) -> str:
    m = re.search(re.escape(BEGIN) + r".*?" + re.escape(END), page, re.S)
    return m.group(0) if m else ""


def write_page() -> bool:
    page = FINDINGS_PAGE.read_text(encoding="utf-8")
    old = block_of(page)
    if not old:
        raise SystemExit(f"{FINDINGS_PAGE}: no marker lines")
    new = page.replace(old, render_findings())
    if new != page:
        FINDINGS_PAGE.write_text(new, encoding="utf-8")
    return new != page


# ---------------------------------------------------------------------------------------------- the runs' logs
#: the committed summary of the walks of 2026-11-17 (three runs x three languages on a 4-core container), written by
#: ``--summary`` from the logs (per life-cycle step: the clicks and their texts in en, the median seconds); steps 16
#: and 17 from H-30's run on lane C2's WALK-1 head (one run x three languages, D-1106)
SUMMARY: dict[int, dict[str, Any]] = {
    12: {
        "path": "/studies/{rs}/week",
        "heading": "This week's patients · {rs}",
        "clicks": 2,
        "click_texts": ["This week's patients", "{rs}"],
        "seconds": 2.6,
        "guesses": [],
    },
    13: {
        "path": "/studies/{rs}/week",
        "heading": "This week's patients · {rs}",
        "clicks": 4,
        "click_texts": ["This week's patients", "{rs}", "patient {short}", "Approach"],
        "seconds": 6.8,
        "guesses": ["F-03"],
    },
    14: {
        "path": "/studies/{rs}/week",
        "heading": "This week's patients · {rs}",
        "clicks": 5,
        "click_texts": [
            "This week's patients",
            "{rs}",
            "Approved and contacted",
            "patient {short}",
            "Reached, visit booked",
        ],
        "seconds": 8.6,
        "guesses": ["F-05"],
    },
    15: {
        "path": "/studies/{rs}/subjects/{rs}-0001",
        "heading": "{rs}-0001 · Participants",
        "clicks": 5,
        "click_texts": ["My studies", "Participants", "{rs}-0001", "Consent given", "Enrolled"],
        "seconds": 4.8,
        "guesses": ["F-07"],
    },
    16: {
        "path": "/studies/{rs}/subjects/{rs}-0001",
        "heading": "{rs}-0001 · Participants",
        "clicks": 3,
        "click_texts": ["Withdraw", "Withdraw", "Yes, do it"],
        "seconds": 1.4,
        "guesses": [],
    },
    17: {
        "path": "/studies/{rs}/state",
        "heading": "{rs} · Study state and identifiers",
        "clicks": 6,
        "click_texts": [
            "More",
            "{rs} · Study set-up",
            "Study state and identifiers",
            "Change state",
            "Change state",
            "Yes, do it",
        ],
        "seconds": 1.6,
        "guesses": [],
    },
    18: {
        "path": "/studies/{rs}/patients/{pid}/reveal",
        "heading": "{rs} · patient {short}",
        "clicks": 5,
        "click_texts": [
            "This week's patients",
            "{rs}",
            "(typed) /studies/{rs}/week?list=all&pid={pid}",
            "Open full chart view",
            "Show chart number (recorded with your name)",
        ],
        "seconds": 5.9,
        "guesses": ["F-17", "F-18"],
    },
    19: {
        "path": "/site/opt-outs",
        "heading": "Opt-out register",
        "clicks": 2,
        "click_texts": ["Opt-out register", "Record the opt-out"],
        "seconds": 0.3,
        "guesses": [],
    },
    20: {
        "path": "/studies/{rs}/candidates",
        "heading": "{rs} · Candidates",
        "clicks": 4,
        "click_texts": ["This week's patients", "{rs}", "(typed) /studies/{rs}/week?list=all&pid={pid}", "Candidates"],
        "seconds": 5.6,
        "guesses": ["F-18"],
    },
    21: {
        "path": "/audit",
        "heading": "Audit trail",
        "clicks": 2,
        "click_texts": ["Audit trail", "Show"],
        "seconds": 12.6,
        "guesses": ["F-22"],
    },
    22: {
        "path": "/metrics",
        "heading": "",
        "clicks": 1,
        "click_texts": ["(typed) /metrics"],
        "seconds": 0.1,
        "guesses": ["F-21"],
    },
}


def summarise(logs: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Per step: the clicks (count, and the texts in en), the median seconds, the guesses, the refusals and the
    stops, over every run and language in ``logs``."""
    by: dict[int, list[dict[str, Any]]] = {}
    for lg in logs:
        for st in lg.get("steps", []):
            by.setdefault(int(st["n"]), []).append(st)
    out: dict[int, dict[str, Any]] = {}
    for n, rows in sorted(by.items()):
        en = [r for r in rows if r.get("lang") == "en"] or rows
        out[n] = {
            "role": rows[0]["role"],
            "path": en[0].get("path", ""),
            "heading": en[0].get("heading", ""),
            "clicks": len(en[0].get("clicks", [])),
            "click_texts": en[0].get("clicks", []),
            "seconds": statistics.median(float(r.get("seconds") or 0) for r in rows),
            "guesses": sorted({g.get("finding") or g.get("detail", "") for r in rows for g in r.get("guesses", [])}),
            "refusals": sorted(
                {f"{x['role']} {x['request']} {x['status']}" for r in rows for x in r.get("refusals", [])}
            ),
            "stopped": sorted({(r.get("stopped") or {}).get("finding", "") for r in rows if r.get("stopped")}),
            "runs": len(rows),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", metavar="LANG", help="print the browser's plan for one language (four seeded accounts)")
    ap.add_argument("--write", action="store_true", help="rewrite the findings table of the findings page")
    ap.add_argument("--summary", nargs="+", metavar="LOG", help="sum up the walk's JSON logs")
    a = ap.parse_args(argv)
    if a.plan:
        print(json.dumps(plan_json(a.plan, RULESETS[a.plan], nw.SEEDED_ACCOUNTS), ensure_ascii=False, indent=1))
    if a.write:
        print("rewritten" if write_page() else "the page is up to date")
    if a.summary:
        logs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in a.summary]
        print(json.dumps(summarise(logs), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
