"""Header command field (step 4, FR-UI-01, FR-CHAT-01..06, FR-PLAT-14, D-110).

One text box in the header of every page. :func:`interpret` turns what the user typed into one :class:`Action`:

* a **grammar line** (the mail command grammar, ``channels.grammar``) such as ``FEAS GZQO`` or ``STATUS RA-BIO``;
* a **phrase** in Japanese, Traditional Chinese or English ("今週のリスト", "GZQO 的篩選紀錄", "my account");
* a **search** for a study code, a patient pseudonym (8+ characters) or a screening number (``GZQO-0001``).

The field only ever *opens a page*. It never starts a job, approves, marks or sends anything: an action that changes
something (``SCREEN GZQO``, ``FEAS NEW``) opens the page where the user confirms it, pre-filled. Approval lines
(``APPROVE``, ``REJECTGATE``) are refused here; approval happens on the one-page S20 only (FR-AUTH-13). Text that is
not understood is never guessed at: the user gets the help panel with examples ("not understood" is not "wrong").

The interpreter is pure (no I/O): the caller passes the studies the user may see and the role, so the result is the
same in tests as in the console. Phrasings are written by the builder (F6-26); a site adds its own at install (H).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

from channels.grammar import GrammarError, Line, parse_line
from tb_common.authz import permit

# what each role may open; the target page checks again (defence in depth, the field is only a shortcut)
ROLE_TARGETS: dict[str, frozenset[str]] = {
    "admin": frozenset(
        {
            "home",
            "admin",
            "jobs",
            "health",
            "sources",
            "users",
            "audit",
            "redcap",
            "account",
            "help",
            "notices",
            "notice_settings",
            "reports",
            "office",
            "feasibility",
            "new_feas",
            "request",
            "setup",
            "log",
            "cohort",
            "week",
            "registry",
            "patient",
            "status",
            "search",
            "approvals",
        }
    ),
    "coordinator": frozenset(
        {
            "home",
            "account",
            "help",
            "notices",
            "notice_settings",
            "reports",
            "office",
            "feasibility",
            "new_feas",
            "request",
            "setup",
            "log",
            "cohort",
            "week",
            "registry",
            "patient",
            "status",
            "search",
            "approvals",
        }
    ),
    "investigator": frozenset(
        {
            "home",
            "account",
            "help",
            "notices",
            "notice_settings",
            "reports",
            "feasibility",
            "setup",
            "log",
            "cohort",
            "week",
            "registry",
            "patient",
            "status",
            "search",
            "approvals",
        }
    ),
    "viewer": frozenset(
        {
            "home",
            "account",
            "help",
            "notices",
            "notice_settings",
            "reports",
            "office",
            "feasibility",
            "audit",
            "redcap",
            "status",
            "search",
            "jobs",
        }
    ),
    "cro": frozenset({"home", "account", "help", "reports", "feasibility", "search"}),
}

# intents that need a study; without one the user's only study is used, else the home page lists them
NEEDS_STUDY = frozenset({"feasibility", "setup", "log", "cohort", "request"})

# phrase table: (intent, words). A word matches as a substring of the normalised text (case-folded, NFKC). Longer
# words are tried first, so "通知設定" wins over "通知" and "new feasibility" over "feasibility".
PHRASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("notice_settings", ("notice settings", "notification settings", "通知設定", "通知の設定", "通知設置")),
    (
        "new_feas",
        (
            "new feasibility",
            "feas new",
            "新しい実施可能性",
            "新規の実施可能性",
            "実施可能性を新しく",
            "新的可行性",
            "新增可行性",
            "paste criteria",
            "基準を貼",
            "貼上條件",
        ),
    ),
    (
        "office",
        ("research office", "治験事務局", "臨床試驗中心", "研究室年報", "yearly counts", "年次件数", "年度統計"),
    ),
    ("redcap", ("redcap connection", "redcap 接続", "redcap接続", "redcap 連線", "redcap連線")),
    ("setup", ("study setup", "study set-up", "試験設定", "試験の設定", "試驗設定", "研究設定")),
    ("log", ("screening log", "スクリーニングログ", "スクリーニング記録", "篩選紀錄", "篩選記錄", "篩檢紀錄")),
    ("cohort", ("cohort list", "cohort", "コホート", "世代名單", "世代列表", "隊列")),
    ("feasibility", ("feasibility report", "feasibility", "実施可能性", "フィージビリティ", "可行性報告", "可行性")),
    (
        "request",
        (
            "run screening",
            "start screening",
            "screen patients",
            "スクリーニング実行",
            "スクリーニングを開始",
            "執行篩選",
            "開始篩選",
        ),
    ),
    (
        "week",
        (
            "this week",
            "weekly list",
            "patient list",
            "my list",
            "clinic list",
            "今週",
            "患者リスト",
            "リスト",
            "本週",
            "病人名單",
            "名單",
            "清單",
        ),
    ),
    ("approvals", ("approve", "approval", "承認", "核准")),
    ("registry", ("registry", "candidate registry", "候補登録", "登録簿", "候選登錄", "登錄")),
    ("health", ("system health", "health", "稼働状況", "システム状態", "系統狀態", "健康狀態")),
    ("sources", ("data sources", "data source", "ingest", "データソース", "取り込み", "資料來源", "資料匯入")),
    ("jobs", ("jobs", "job list", "ジョブ", "工作", "作業")),
    ("users", ("users", "accounts", "user accounts", "アカウント管理", "ユーザー", "使用者", "帳號管理")),
    ("audit", ("audit", "audit trail", "監査", "監査証跡", "稽核")),
    ("notices", ("notices received", "my notices", "notices", "notifications", "受信した通知", "通知", "收到的通知")),
    (
        "account",
        (
            "my account",
            "account",
            "password",
            "change password",
            "language",
            "マイアカウント",
            "パスワード",
            "言語",
            "我的帳號",
            "密碼",
            "語言",
        ),
    ),
    ("reports", ("reports", "report", "レポート", "報告書", "報告")),
    ("help", ("help", "how do i", "what can i type", "ヘルプ", "使い方", "説明", "說明", "幫助", "怎麼用")),
    ("home", ("home", "start page", "ホーム", "トップ", "首頁", "主頁")),
)
_PHRASES_BY_LENGTH = sorted(((w, intent) for intent, ws in PHRASES for w in ws), key=lambda p: -len(p[0]))

# commands also accepted in lower case ("feas gzqo"): the short v4 ones whose word is not also a phrase ("cohort")
LENIENT = frozenset({"FEAS", "SCREEN", "STATUS", "APPROVE", "REJECTGATE"})
_PID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_HEX = re.compile(r"^[0-9a-fA-F]{8,64}$")
_SCREEN_NO = re.compile(r"^([A-Z0-9][A-Z0-9_-]{0,31})-(\d{1,6})$")
_STUDY_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{1,31}")


@dataclass(frozen=True)
class Action:
    """What the field does: open ``intent`` (for ``study``/``target``), or explain why not."""

    intent: str  # an intent of ROLE_TARGETS, or "unknown" / "refused" / "forbidden" / "pick_study"
    study: str | None = None
    target: str | None = None  # a pseudonym, a screening number or a search text
    command: str | None = None  # the grammar command when the text was a grammar line
    reason: str = ""  # i18n key suffix for refused / unknown
    params: dict[str, str] = field(default_factory=dict)

    @property
    def opens_page(self) -> bool:
        return self.intent not in ("unknown", "refused", "forbidden", "pick_study")


def normalise(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).replace("　", " ").split())


def _find_study(text: str, studies: Iterable[str]) -> str | None:
    known = {s.upper(): s.upper() for s in studies}
    for tok in _STUDY_TOKEN.findall(text):
        if tok.upper() in known:
            return known[tok.upper()]
    return None


def _lenient(t: str, studies: list[str]) -> Line | None:
    """``feas gzqo``, ``Status GZQO``: a short grammar line typed in lower case. Only the command word and a known
    study code are upper-cased; anything that still does not parse falls through to the phrases."""
    toks = t.split()
    if not toks or len(toks) > 3 or toks[0].upper() not in LENIENT or toks[0] == toks[0].upper():
        return None
    rest = [tok.upper() if tok.upper() in studies or tok.upper() == "NEW" else tok for tok in toks[1:]]
    try:
        return parse_line(" ".join([toks[0].upper(), *rest]))
    except GrammarError:
        return None


def _from_grammar(line: Line) -> Action:
    cmd, study = line.command, line.study
    if line.approval:
        return Action("refused", study, command=cmd, reason="approval")
    if cmd == "FEAS":
        return Action(
            "new_feas" if study in (None, "NEW") else "feasibility", None if study == "NEW" else study, command=cmd
        )
    if cmd in ("SCREEN", "MICROBATCH", "NAV", "COHORT"):
        return Action("request", study, command=cmd, params={"kind": "SCREEN"})
    if cmd == "STATUS":
        if line.args:  # a job id
            return Action("jobs", target=line.args[0], command=cmd)
        return Action("status", study, command=cmd)
    if cmd == "HELP":
        return Action("help", command=cmd)
    if cmd in ("CONFIRM", "REJECT", "DEFER", "STATE"):  # mail aliases: marks and outcomes are made on the patient page
        return Action("refused", study, command=cmd, reason="patient_page")
    if cmd == "DIGEST":
        return Action("notice_settings", command=cmd)
    if cmd in (
        "CONSENT",
        "RELEASE",
        "CASE",
        "ASK",
        "WHATIF",
        "QFILL",
        "MONITOR",
        "ATLAS",
        "STUDY",
        "CANCEL",
        "ANSWERS",
        "OK",
        "SUBMIT",
        "FEEDBACK",
    ):
        return Action("refused", study, command=cmd, reason="mail_only")
    return Action("refused", study, command=cmd, reason="never")


def interpret(text: str, studies: Iterable[str], role: str) -> Action:
    """The one action for ``text``; ``studies`` are the study codes this account may see."""
    studies = [s.upper() for s in studies]
    t = normalise(text)
    if not t:
        return Action("help")
    act: Action | None = None
    try:
        line = parse_line(t)
    except GrammarError as exc:
        return Action("unknown", reason="grammar", target=str(exc)[:120])
    if line is None:
        line = _lenient(t, studies)
    if line is not None:
        act = _from_grammar(line)
    if act is None:
        low = t.casefold()
        m = _SCREEN_NO.match(t.upper())
        if m:  # a screening number: the site's prefix may differ from the study code (S21)
            act = Action("patient", m.group(1) if m.group(1) in studies else None, target=t.upper())
        else:
            for word, intent in _PHRASES_BY_LENGTH:
                if word.casefold() in low:
                    act = Action(intent, _find_study(t, studies))
                    break
    if act is None:
        study = _find_study(t, studies)
        if study and normalise(t).upper() == study:
            act = Action("status", study)
        elif _PID.match(t) and (_HEX.match(t) or not t.isalpha()):  # a pseudonym (hex) or a coded id
            act = Action("search", target=t)
        elif study:
            act = Action("status", study)
        else:
            return Action("unknown", reason="phrase", target=t[:120])
    if not act.opens_page:
        return act
    if act.intent not in ROLE_TARGETS.get(role, frozenset()):
        return Action("forbidden", act.study, act.target, act.command)
    if act.intent in NEEDS_STUDY and act.study is None:
        if len(studies) == 1:
            return Action(act.intent, studies[0], act.target, act.command, params=act.params)
        return Action("pick_study", None, act.intent, act.command)
    return act


def url_of(act: Action, role: str) -> str | None:
    """The page an action opens (None for actions that show a message instead)."""
    rs, intent = act.study, act.intent
    simple = {
        "home": "/home",
        "admin": "/admin",
        "health": "/admin?tab=health",
        "sources": "/admin?tab=sources",
        "users": "/ops/users",
        "audit": "/audit",
        "redcap": "/admin/redcap",
        "account": "/account",
        "help": "/help",
        "notices": "/notices/received",
        "notice_settings": "/settings/notices",
        "reports": "/reports",
        "office": "/reports/research-office",
        "new_feas": "/pilot/protocol",
        "registry": f"/pilot/registry/{rs}" if rs else "/pilot/registry",
        "approvals": "/home",
    }
    if intent in simple:
        return simple[intent]
    if intent == "jobs":
        if act.target:
            return f"/pilot/jobs/{act.target}"
        return "/admin?tab=jobs" if permit(role, "ops.view") else "/jobs"
    if intent == "feasibility":
        return f"/studies/{rs}/feasibility"
    if intent == "setup":
        return f"/studies/{rs}/setup"
    if intent == "log":
        return f"/studies/{rs}/screening-log"
    if intent == "cohort":
        return f"/studies/{rs}/cohort"
    if intent == "request":
        return f"/pilot/request?ruleset={rs}&kind={act.params.get('kind', 'SCREEN')}"
    if intent == "week":
        sponsor = permit(role, "report.sponsor_form").allowed  # T-102c (D-425): the matrix rows, not role names
        return f"/studies/{rs}/week" if rs and not sponsor else ("/week" if not sponsor else "/reports")
    if intent == "status":
        if permit(role, "report.aggregate_only"):
            return f"/studies/{rs}/feasibility" if rs else "/reports"
        if permit(role, "list.mark"):
            return f"/studies/{rs}/week" if rs else "/week"
        return f"/home#study-{rs}" if rs else "/home"
    return None  # patient / search: resolved by the caller against the registry
