"""H-10 (D-1121): the steps of the new-study walk, in one place.

A new study from its first step, on a box in steps mode (D-1062: demo mode off, the stub model, the synthetic
hospital): the coordinator pastes the SITE5B criteria under a new ruleset id, the data steward names the PI on the
study's delegation log, the PI approves, the coordinator runs FEAS and SCREEN and reads the candidate list.

Three readers take their words from here, so they cannot drift apart:

* ``tests/e2e/new_study_walk.js`` clicks these texts in a browser (``plan_json`` resolves them for one language);
* ``docs/handover/new-study-walk.{en,zh-TW,ja}.md`` shows them to a human tester (``render_block`` writes the part
  between the two marker lines; ``tests/e2e/test_new_study_walk.py`` checks the pages hold exactly that);
* every text is a key of the console's own message catalogue (``console.i18n``), never typed here.

    PYTHONPATH=libs:services:. python -m tests.e2e.new_study_walk_plan --write   # rewrite the pages' step blocks
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PAGES = {lang: ROOT / "docs" / "handover" / f"new-study-walk.{lang}.md" for lang in ("en", "zh-TW", "ja")}
LANGS = ("en", "zh-TW", "ja")
BEGIN = "<!-- new-study-walk: steps, written by tests/e2e/new_study_walk_plan.py; do not edit by hand -->"
END = "<!-- new-study-walk: end of steps -->"
#: a new study's first criteria are version 1.0.0 (the compiler's first version of a ruleset id)
VERSION = "1.0.0"
#: the walk's new ruleset id per page language. None is a cassette name of the stub (services/llm_stub/cassettes/
#: ir_extract) or starts with one and a "-", so the stub has not seen the pasted text under this id (the point).
RULESETS = {"en": "WALKNEW", "zh-TW": "WALKNEWZH", "ja": "WALKNEWJA"}
#: what the human tester's page shows where the product shows the tester's own new id
SHOWN_ID = "MYSTUDY"
#: the delegation log's GCP training day the steward types (a past day; the log asks for one, any will do)
TRAINING_DAY = "2025-06-01"
ROLES = ("coordinator", "steward", "investigator", "operator")
#: the console role of each walk role (``console.auth.ROLES``): its name on the page comes from ``role.<role>``
CONSOLE_ROLE = {"coordinator": "coordinator", "steward": "steward", "investigator": "investigator", "operator": "admin"}
#: four-account mode: the steps-mode box's own seeded accounts (tools/demo.py SEEDED)
SEEDED_ACCOUNTS = {"coordinator": "crc", "steward": "stw", "investigator": "pi", "operator": "admin"}


@cache
def catalogue() -> tuple[Any, dict[str, dict[str, str]]]:
    """(translate, CATALOGUES) as the served console has them: a page module adds its keys to the catalogue when it
    is imported (``role.steward`` comes with the break-glass pages), and ``create_app`` imports some of them only when
    it builds the app; so every console module that adds keys is imported here first."""
    import importlib

    for path in sorted((ROOT / "services" / "console").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if path.stem != "__main__" and re.search(r"CATALOGUES\[\w+\]\.update\(|^EN\.update\(", text, re.M):
            importlib.import_module(f"console.{path.stem}")
    from console.i18n import CATALOGUES, translate

    return translate, CATALOGUES


@dataclass(frozen=True)
class T:
    """A text the product shows: a catalogue key, its values (``{rs}`` and ``{v}`` are filled in), and an optional
    prefix the template writes before it (``{rs} · ``). A key of None is the prefix alone (a study id link)."""

    key: str | None
    values: tuple[tuple[str, str], ...] = ()
    prefix: str = ""

    def text(self, lang: str, rs: str) -> str:
        translate, _ = catalogue()

        def fill(s: str) -> str:
            return s.replace("{rs}", rs).replace("{v}", VERSION)

        body = "" if self.key is None else translate(lang, self.key, **{k: fill(v) for k, v in self.values})
        return fill(self.prefix) + body

    def missing(self) -> list[str]:
        """The page languages the product has no own form of this text in (it shows the English one)."""
        _, CATALOGUES = catalogue()  # noqa: N806

        if self.key is None:
            return []
        return [lang for lang in ("zh-TW", "ja") if not CATALOGUES[lang].get(self.key)]


@dataclass(frozen=True)
class Do:
    """One thing a person does. ``kind``: signin, language, nav (top bar), more (the "More" menu), link, row_link
    (a link in the table row that holds ``within``), fill, select, radio, button, open_all (every such link, one by
    one), label_all (the zh-TW and ja pages: a short label for each criterion that has none), form (the form whose
    button is ``text``: choose ``value`` in it, then click), see (an expectation, below)."""

    kind: str
    text: T | None = None
    label: T | None = None
    value: str = ""
    within: str = ""
    wait_s: int = 30


@dataclass(frozen=True)
class See:
    """What the page must show. ``kind``: h1 (the heading holds ``text``), state (the job's state on its page is
    ``value``), shown (the element ``data-testid=value`` is there), gone (it is not), says (the main part holds
    ``text``), path (the address's path matches ``value``)."""

    kind: str
    text: T | None = None
    value: str = ""


@dataclass(frozen=True)
class Refuse:
    """A role boundary: ``role`` sends ``method path`` (with the page's own form token and ``fields``) and the box
    must answer 403 with the product's refusal page (``problem.h.forbidden``)."""

    role: str
    method: str
    path: str
    fields: tuple[tuple[str, str], ...] = ()
    why: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Step:
    n: int
    role: str
    acts: tuple[Do | See, ...]
    refusals: tuple[Refuse, ...]
    what: dict[str, str]
    expect: dict[str, str]


FORBIDDEN_PAGE = T("problem.h.forbidden")


def _criteria() -> str:
    """The SITE5B protocol's criteria, as the build gate pastes them (one text for both)."""
    from tools.e2e_simple import SITE_CRITERIA

    return SITE_CRITERIA


def site_label(lang: str, crit: str, rs: str) -> str:
    """The short label the PI gives a pasted criterion on a zh-TW or ja page: the build gate's SITE5B labels."""
    from tools.e2e_simple import SITE_LABELS

    return SITE_LABELS.get(lang, {}).get("SITE5B" + crit[len(rs) :], crit)


STEPS: tuple[Step, ...] = (
    Step(
        1,
        "coordinator",
        (Do("signin"), Do("language", T("lang.apply"), T("lang.label")), See("h1", T("wb.crc.title"))),
        (),
        {
            "en": "Sign in and choose the page language.",
            "zh-TW": "登入並選擇頁面語言。",
            "ja": "ログインし、画面の言語を選びます。",
        },
        {"en": "Your work page.", "zh-TW": "您的工作頁面。", "ja": "あなたの作業ページ。"},
    ),
    Step(
        2,
        "coordinator",
        (Do("more", T("nav.protocol")), See("h1", T("protocol.title")), See("path", value=r"^/pilot/protocol$")),
        (),
        {"en": "Open the protocol page.", "zh-TW": "開啟計畫書頁面。", "ja": "プロトコルのページを開きます。"},
        {
            "en": "The page to paste a protocol's criteria.",
            "zh-TW": "貼上計畫書收案條件的頁面。",
            "ja": "プロトコルの基準を貼り付けるページ。",
        },
    ),
    Step(
        3,
        "coordinator",
        (
            Do("fill", label=T("protocol.ruleset"), value="{rs}"),
            Do("fill", label=T("protocol.paste"), value="{criteria}"),
            Do("button", T("protocol.submit")),
            See("state", value="awaiting_approval"),
            See("h1", T(None, prefix="FEAS {rs} v{v}")),
        ),
        (),
        {
            "en": "Type a new ruleset id, paste the SITE5B criteria (below), and send them.",
            "zh-TW": "輸入新的條件代碼，貼上 SITE5B 的收案條件（見下方），然後送出。",
            "ja": "新しい基準 ID を入力し、SITE5B の基準（下記）を貼り付けて送ります。",
        },
        {
            "en": "A job page: FEAS for the new id at version 1.0.0, waiting for approval.",
            "zh-TW": "作業頁面：新代碼的 FEAS，版本 1.0.0，等待核准。",
            "ja": "ジョブのページ：新しい ID の FEAS、バージョン 1.0.0、承認待ち。",
        },
    ),
    Step(
        4,
        "coordinator",
        (
            Do("link", T("s20.open")),
            See("h1", T("s20.title", prefix="{rs} v{v} · ")),
            See("says", T("s20.split", (("n", "4"), ("s", "1"), ("m", "0"), ("x", "0"), ("h", "3")))),
            See("says", T("s20.only_pi")),
            See("gone", value="approve"),
        ),
        (
            Refuse(
                "coordinator",
                "POST",
                "/pilot/jobs/{job}/approve",
                (("confirm", "yes"),),
                {
                    "en": "the coordinator cannot approve",
                    "zh-TW": "研究協調員不能核准",
                    "ja": "治験コーディネーターは承認できない",
                },
            ),
            Refuse(
                "coordinator",
                "POST",
                "/studies/{rs}/team",
                (("username", "{investigator}"), ("role", "pi"), ("training_day", TRAINING_DAY)),
                {
                    "en": "the coordinator cannot name the PI",
                    "zh-TW": "研究協調員不能登記主持人",
                    "ja": "治験コーディネーターは責任医師を登録できない",
                },
            ),
        ),
        {
            "en": "Open the approval page. Look, but you cannot approve.",
            "zh-TW": "開啟核准頁面。可以查看，但不能核准。",
            "ja": "承認ページを開きます。見ることはできますが、承認はできません。",
        },
        {
            "en": "Four criteria: one by a fixed filter, three by a person. No approve button.",
            "zh-TW": "四條條件：一條由固定篩選，三條由人員確認。沒有核准按鈕。",
            "ja": "4 件の基準：固定フィルター 1 件、担当者 3 件。承認ボタンはありません。",
        },
    ),
    Step(
        5,
        "investigator",
        (
            Do("signin"),
            Do("language", T("lang.apply"), T("lang.label")),
            Do("nav", T("nav.week")),
            Do("link", T("s20.waiting", (("rs", "{rs}"), ("v", "{v}")))),
            See("h1", T("s20.title", prefix="{rs} v{v} · ")),
            See("shown", value="approve-needs-pi"),
            See("says", T("pi.needed", (("rs", "{rs}"),))),
            See("gone", value="approve"),
        ),
        (
            Refuse(
                "investigator",
                "POST",
                "/pilot/jobs/{job}/approve",
                (("confirm", "yes"),),
                {
                    "en": "nobody approves before the steward names the PI",
                    "zh-TW": "管理員登記主持人之前，沒有人能核准",
                    "ja": "データスチュワードが責任医師を登録するまで誰も承認できない",
                },
            ),
            Refuse(
                "investigator",
                "POST",
                "/pilot/protocol",
                (("ruleset", "{rs}X"), ("criteria", "{criteria}")),
                {
                    "en": "the investigator cannot send a protocol in",
                    "zh-TW": "主持人不能送出計畫書",
                    "ja": "治験責任医師はプロトコルを送れない",
                },
            ),
        ),
        {
            "en": "As the investigator: open the criteria waiting for approval.",
            "zh-TW": "以主持人身分：開啟等待核准的條件。",
            "ja": "治験責任医師として：承認待ちの基準を開きます。",
        },
        {
            "en": "Nobody can approve yet: the delegation log names no PI.",
            "zh-TW": "目前沒有人能核准：授權紀錄表尚未記載主持人。",
            "ja": "まだ誰も承認できません：リストに責任医師がいません。",
        },
    ),
    Step(
        6,
        "steward",
        (
            Do("signin"),
            Do("language", T("lang.apply"), T("lang.label")),
            Do("link", T("pi.task.item", (("rs", "{rs}"),))),
            See("h1", T("team.log.title", prefix="{rs} · ")),
            See("shown", value="no-pi"),
            Do("select", label=T("team.log.account"), value="{investigator}"),
            Do("select", label=T("team.log.role"), value="pi"),
            Do("fill", label=T("team.log.training"), value=TRAINING_DAY),
            Do("button", T("team.log.add.save")),
            See("says", T("team.log.done.add")),
            See("gone", value="task-name-pi-{rs}"),
        ),
        (
            Refuse(
                "steward",
                "POST",
                "/pilot/request",
                (("kind", "FEAS"), ("ruleset", "{rs}")),
                {
                    "en": "the steward cannot start a run",
                    "zh-TW": "資料管理員不能啟動執行",
                    "ja": "データスチュワードは実行を開始できない",
                },
            ),
        ),
        {
            "en": "As the data steward: name the investigator as the study's PI on its delegation log.",
            "zh-TW": "以資料管理員身分：在授權紀錄表上登記主持人為本試驗的試驗主持人。",
            "ja": "データスチュワードとして：リストで治験責任医師を登録します。",
        },
        {
            "en": "The entry is added and signed; the task is gone.",
            "zh-TW": "紀錄已加入並簽署；待辦事項消失。",
            "ja": "記載が追加・署名され、タスクが消えます。",
        },
    ),
    Step(
        7,
        "investigator",
        (
            Do("nav", T("nav.week")),
            Do("link", T("s20.waiting", (("rs", "{rs}"), ("v", "{v}")))),
            See("gone", value="approve-needs-pi"),
            Do("label_all", T("s20.label.save")),
            Do("open_all", T("s20.open_row")),
            Do("button", T("s20.approve_all")),
            See("h1", T("confirm.title")),
            Do("button", T("confirm.yes")),
            See("state", value="done"),
            See("h1", T(None, prefix="APPROVE {rs} v{v}")),
        ),
        (),
        {
            "en": "As the investigator: open each row to check, then approve all.",
            "zh-TW": "以主持人身分：逐列開啟確認，然後全部核准。",
            "ja": "治験責任医師として：各行を開いて確認し、すべて承認します。",
        },
        {
            "en": "A confirmation page, then the APPROVE job, done.",
            "zh-TW": "先出現確認頁面，然後 APPROVE 作業完成。",
            "ja": "確認ページのあと、APPROVE ジョブが完了します。",
        },
    ),
    Step(
        8,
        "coordinator",
        (
            Do("more", T("nav.request")),
            See("h1", T("request.title")),
            Do("form", T("request.start.feas"), value="{rs}"),
            See("state", value="done"),
            See("h1", T(None, prefix="FEAS {rs} v{v}")),
            See("says", T(None, prefix="{rs}-INC-01")),
        ),
        (),
        {"en": "Run FEAS on the new study.", "zh-TW": "對新試驗執行 FEAS。", "ja": "新しい試験で FEAS を実行します。"},
        {
            "en": "The FEAS job, done, with its funnel of the four criteria.",
            "zh-TW": "FEAS 作業完成，附四條條件的篩選漏斗。",
            "ja": "FEAS ジョブが完了し、4 件の基準のファネルが出ます。",
        },
    ),
    Step(
        9,
        "coordinator",
        (
            Do("nav", T("nav.reports")),
            Do("row_link", T("home.open_report"), within="{rs} v{v}"),
            See("h1", T("feas.title", prefix="{rs} · ")),
            Do("more", T("setup.title", prefix="{rs} · ")),
            See("h1", T("setup.title", prefix="{rs} · ")),
            See("says", T("setup.who.unset")),
            Do("radio", label=T("setup.who.hospital")),
            Do("button", T("setup.who.save")),
            See("says", T("setup.who.now.hospital")),
        ),
        (),
        {
            "en": "Open the study's report, then its set-up, and choose the whole hospital under who to screen.",
            "zh-TW": "開啟試驗的報告，再開啟試驗設定，在篩選對象選擇全院。",
            "ja": "試験のレポート、次に試験の設定を開き、スクリーニングの対象で病院全体を選びます。",
        },
        {
            "en": "Who to screen: the whole hospital.",
            "zh-TW": "篩選對象：全院。",
            "ja": "スクリーニングの対象：病院全体。",
        },
    ),
    Step(
        10,
        "coordinator",
        (
            Do("more", T("nav.request")),
            Do("form", T("request.start.screen"), value="{rs}", wait_s=600),
            See("state", value="done"),
            See("h1", T(None, prefix="SCREEN {rs} v{v}")),
        ),
        (),
        {
            "en": "Run SCREEN on the new study. It takes about a minute.",
            "zh-TW": "對新試驗執行 SCREEN，約需一分鐘。",
            "ja": "新しい試験で SCREEN を実行します。1 分ほどかかります。",
        },
        {
            "en": "The SCREEN job, done, with its list.",
            "zh-TW": "SCREEN 作業完成，附名單。",
            "ja": "SCREEN ジョブが完了し、リストが出ます。",
        },
    ),
    Step(
        11,
        "coordinator",
        (
            Do("nav", T("nav.week")),
            Do("link", T(None, prefix="{rs}")),
            Do("link", T("team.cand.title")),
            See("h1", T("team.cand.title", prefix="{rs} · ")),
            See("shown", value="cand-count"),
            See("shown", value="candidates"),
        ),
        (
            Refuse(
                "operator",
                "GET",
                "/studies/{rs}/candidates",
                (),
                {
                    "en": "the administrator cannot open the candidate list",
                    "zh-TW": "管理者不能開啟候選者名單",
                    "ja": "管理者は候補者リストを開けない",
                },
            ),
        ),
        {
            "en": "Read the candidate list of the new study.",
            "zh-TW": "閱讀新試驗的候選者名單。",
            "ja": "新しい試験の候補者リストを読みます。",
        },
        {
            "en": "The candidates in the hospital, with their count.",
            "zh-TW": "全院候選者與人數。",
            "ja": "院内の候補者とその人数。",
        },
    ),
)

#: the words of the page around the product's texts, in the page's language (the page's own, not the product's)
WORDS: dict[str, dict[str, str]] = {
    "en": {
        "step": "Step",
        "as": "as",
        "do": "What you do",
        "text": "Text on the page",
        "see": "You should see",
        "refused": "refused: 403 and the page",
        "none": "(no own form in the product: the English text is shown)",
        "signin": "Sign in with your user name and password",
        "language": "Choose the language, then click",
        "nav": "In the top bar, click",
        "more": "Open the menu, then click",
        "link": "Click",
        "row_link": "On the study's row, click",
        "fill": "Type {value} into",
        "select": "Choose {value} in",
        "radio": "Choose",
        "button": "Click",
        "open_all": "On each row that has it, click",
        "label_all": "zh-TW and ja pages only: give each criterion a short label, then click",
        "form": "In the form of this button, choose {value}, then click",
    },
    "zh-TW": {
        "step": "步驟",
        "as": "身分",
        "do": "操作",
        "text": "頁面上的文字",
        "see": "應看到",
        "refused": "被拒絕：403 與頁面",
        "none": "（產品沒有此語言的文字：顯示英文）",
        "signin": "以您的使用者名稱和密碼登入",
        "language": "選擇語言，然後點選",
        "nav": "在上方列點選",
        "more": "開啟選單，然後點選",
        "link": "點選",
        "row_link": "在該試驗的列點選",
        "fill": "在此欄輸入 {value}",
        "select": "在此欄選擇 {value}",
        "radio": "選擇",
        "button": "點選",
        "open_all": "在每一列點選",
        "label_all": "僅中文與日文頁面：為每條條件加上簡短標籤，然後點選",
        "form": "在此按鈕的表單中選擇 {value}，然後點選",
    },
    "ja": {
        "step": "手順",
        "as": "役割",
        "do": "操作",
        "text": "画面の文言",
        "see": "表示されるもの",
        "refused": "拒否される：403 とページ",
        "none": "（製品にこの言語の文言がない：英語が表示される）",
        "signin": "ユーザー名とパスワードでログイン",
        "language": "言語を選び、次をクリック",
        "nav": "上部のバーでクリック",
        "more": "メニューを開き、次をクリック",
        "link": "クリック",
        "row_link": "その試験の行でクリック",
        "fill": "次の欄に {value} を入力",
        "select": "次の欄で {value} を選択",
        "radio": "選択",
        "button": "クリック",
        "open_all": "各行でクリック",
        "label_all": "中国語と日本語の画面のみ：各基準に短い表示名を付け、次をクリック",
        "form": "このボタンのフォームで {value} を選び、次をクリック",
    },
}


def texts_of(step: Step) -> list[T]:
    """Every product text a step clicks, types into or looks for."""
    out: list[T] = []
    for a in step.acts:
        for t in (a.text, a.label) if isinstance(a, Do) else (a.text,):
            if t is not None:
                out.append(t)
    if step.refusals:
        out.append(FORBIDDEN_PAGE)
    return out


def all_texts() -> list[T]:
    return [t for st in STEPS for t in texts_of(st)] + [T("login.submit"), T("nav.more")]


def findings() -> list[str]:
    """A text the walk uses that the product has in English only (shown in English on a zh-TW or ja page)."""
    seen: dict[str, list[str]] = {}
    for t in all_texts():
        if t.key and t.missing():
            seen[t.key] = t.missing()
    return [f"{k}: no {' or '.join(v)} form in the console's catalogue" for k, v in sorted(seen.items())]


# ---------------------------------------------------------------------------------------------- the browser's plan
def plan_json(lang: str, rs: str, accounts: dict[str, str]) -> dict[str, Any]:
    """The walk for one page language and one new ruleset id, every text resolved as the product writes it."""

    def fill(s: str) -> str:
        out = s.replace("{rs}", rs).replace("{v}", VERSION).replace("{criteria}", _criteria())
        return out.replace("{investigator}", accounts.get("investigator", ""))

    def resolved(t: T | None) -> str:
        return "" if t is None else t.text(lang, rs)

    steps = []
    for st in STEPS:
        acts: list[dict[str, Any]] = []
        for a in st.acts:
            if isinstance(a, See):
                acts.append({"do": "see", "kind": a.kind, "text": resolved(a.text), "value": fill(a.value)})
            else:
                acts.append({"do": a.kind, "text": resolved(a.text), "label": resolved(a.label), "value": fill(a.value),
                             "within": fill(a.within), "wait_s": a.wait_s})  # fmt: skip
        steps.append({
            "n": st.n,
            "role": st.role,
            "acts": acts,
            "refusals": [{"role": r.role, "method": r.method, "path": fill(r.path),
                          "fields": {k: fill(v) for k, v in r.fields}} for r in st.refusals],
        })  # fmt: skip
    labels = {
        f"{rs}-{c}": site_label(lang, f"{rs}-{c}", rs) for c in ("INC-01", "INC-02", "INC-03", "EXC-01")
    }  # the PI's labels on a zh-TW or ja page (D-309)
    return {
        "lang": lang,
        "rs": rs,
        "steps": steps,
        "labels": labels,
        "more": T("nav.more").text(lang, rs),
        "signin": T("login.submit").text(lang, rs),
        "forbidden": FORBIDDEN_PAGE.text(lang, rs),
        "language_label": T("lang.label").text(lang, rs),
        "language_apply": T("lang.apply").text(lang, rs),
        "accounts": accounts,
    }


# ---------------------------------------------------------------------------------------------- the tester's page
def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def render_block(page_lang: str) -> str:
    """The step tables of the tester's page in ``page_lang``: per step the role, what to do, the product's text in
    en, zh-TW and ja (with :data:`SHOWN_ID` for the tester's own id), what to see, and the refusals checked there."""
    translate, _ = catalogue()
    w = WORDS[page_lang]
    out = [BEGIN, ""]
    for st in STEPS:
        role = translate(page_lang, f"role.{CONSOLE_ROLE[st.role]}")
        out += [f"### {w['step']} {st.n} · {role}", "", st.what[page_lang], ""]
        out += [f"| {w['do']} | en | zh-TW | ja |", "| --- | --- | --- | --- |"]
        for a in st.acts:
            if not isinstance(a, Do):
                continue
            how = w[a.kind]
            row = []
            for t in (a.label, a.text) if a.kind in ("language",) else ((a.label or a.text),):
                if t is None:
                    continue
                row.append(t)
            if a.kind == "signin":
                cells = [T("login.submit").text(lg, SHOWN_ID) for lg in LANGS]
            elif not row:
                continue
            elif a.kind == "more":  # the menu's own name, then the item
                cells = [f"{_one(T('nav.more'), lg)} → {_one(row[0], lg)}" for lg in LANGS]
            else:
                cells = [" / ".join(_one(t, lg) for t in row) for lg in LANGS]
            value = a.value.replace("{rs}", SHOWN_ID).replace("{criteria}", "SITE5B")
            value = value.replace("{investigator}", SEEDED_ACCOUNTS["investigator"])
            out.append(
                f"| {_cell(how.replace('{value}', f'`{value}`'))} | " + " | ".join(_cell(c) for c in cells) + " |"
            )
        out += ["", f"{w['see']}: {st.expect[page_lang]}", ""]
        for r in st.refusals:
            role_r = translate(page_lang, f"role.{CONSOLE_ROLE[r.role]}")
            heads = " / ".join(FORBIDDEN_PAGE.text(lg, SHOWN_ID) for lg in LANGS)
            path = r.path.replace("{rs}", SHOWN_ID).replace("{job}", "<job>")
            out.append(f'- {role_r}: {r.why[page_lang]}: `{r.method} {path}` {w["refused"]} "{heads}".')
        if st.refusals:
            out.append("")
    out.append(END)
    return "\n".join(out)


def _one(t: T, lang: str) -> str:
    text = t.text(lang, SHOWN_ID)
    return f"{text} {WORDS[lang]['none']}" if lang in t.missing() else text


def block_of(page: str) -> str:
    """The generated part of a page (between the marker lines, the markers included)."""
    m = re.search(re.escape(BEGIN) + r".*?" + re.escape(END), page, re.S)
    return m.group(0) if m else ""


def write_pages() -> list[str]:
    changed = []
    for lang, path in PAGES.items():
        page = path.read_text(encoding="utf-8")
        old = block_of(page)
        if not old:
            raise SystemExit(f"{path}: no marker lines")
        new = page.replace(old, render_block(lang))
        if new != page:
            path.write_text(new, encoding="utf-8")
            changed.append(str(path.relative_to(ROOT)))
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true", help="rewrite the step blocks of the three pages")
    ap.add_argument("--plan", metavar="LANG", help="print the browser's plan for one language (four seeded accounts)")
    ap.add_argument("--findings", action="store_true", help="print the texts the product has in English only")
    a = ap.parse_args(argv)
    if a.write:
        print("\n".join(write_pages()) or "the pages are up to date")
    if a.plan:
        print(json.dumps(plan_json(a.plan, RULESETS[a.plan], SEEDED_ACCOUNTS), ensure_ascii=False, indent=1))
    if a.findings:
        print("\n".join(findings()) or "every text has its zh-TW and ja form")
    return 0


if __name__ == "__main__":
    sys.exit(main())
