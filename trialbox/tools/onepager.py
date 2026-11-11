"""The one-pager "what this system does with charts" (TB-PRV-06; card T-318, D-411).

Renders one Markdown page in English, Japanese or Traditional Chinese from a site's ``settings.yaml`` and the
intended-use statement of ``tb_common.wording``. The site's own values (name, data source, cloud setting, small-cell
threshold, retention, contact) come from the settings, so the page cannot drift from the box. A rendered page names
the site, so a site's copy is kept by the site, not in the repository.

    python -m tools.onepager --settings deploy/settings.yaml --lang ja --out onepager.ja.md
    python -m tools.onepager --settings deploy/settings.example.yaml --lang en      # the synthetic site, to stdout

The page uses none of the verdict words of TB-IU-01 §2 (``tb_common.wording.FORBIDDEN``); the test checks it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "libs") not in sys.path:  # run from the install folder with the host's python3
    sys.path.insert(0, str(ROOT / "libs"))

LANGS = ("en", "ja", "zh-TW")

SOURCE: dict[str, dict[str, str]] = {
    "csv": {
        "en": "an export file that the hospital's IT writes each night",
        "ja": "病院の情報部門が毎晩出力するファイル",
        "zh-TW": "醫院資訊室每晚匯出的檔案",
    },
    "cgrd_sql": {
        "en": "the hospital's research data warehouse, read each night",
        "ja": "病院の研究用データウェアハウス（毎晩読み取り）",
        "zh-TW": "醫院的研究資料倉儲（每晚讀取）",
    },
    "fhir_bulk": {
        "en": "a FHIR bulk export from the hospital's systems, read each night",
        "ja": "病院システムからの FHIR 一括出力（毎晩読み取り）",
        "zh-TW": "醫院系統的 FHIR 批次匯出（每晚讀取）",
    },
    "ssmix2": {
        "en": "the hospital's SS-MIX2 standard storage, read each night",
        "ja": "病院の SS-MIX2 標準化ストレージ（毎晩読み取り）",
        "zh-TW": "醫院的 SS-MIX2 標準化儲存區（每晚讀取）",
    },
}

CLOUD: dict[bool, dict[str, str]] = {
    False: {
        "en": "No cloud service is used. The language model runs on the hospital's own computer.",
        "ja": "クラウドサービスは使いません。言語モデルは病院内のコンピュータで動きます。",
        "zh-TW": "不使用任何雲端服務。語言模型在醫院自己的電腦上運作。",
    },
    True: {
        "en": (
            "Patient data is read only by the language model on the hospital's own computer. A cloud model is "
            "allowed for text with no patient data (for example a public trial registry entry)."
        ),
        "ja": (
            "患者データは病院内のコンピュータ上の言語モデルだけが読みます。患者データを含まない文章（公開の"
            "試験登録情報など）に限り、クラウドのモデルを使うことがあります。"
        ),
        "zh-TW": (
            "病人資料僅由醫院電腦上的語言模型讀取。不含病人資料的文字（例如公開的試驗登錄資訊）才可能使用雲端模型。"
        ),
    },
}

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "title": "What TrialBox does with medical records at {site}",
        "what": "## What it is",
        "read": "## What it reads",
        "read_body": (
            "Records of patients seen at the hospital: age, sex, conditions, prescriptions, test results, "
            "appointments and clinical notes. They come from {source}. Names and chart numbers are replaced by "
            "codes at the door; the link back is encrypted and stays in the hospital."
        ),
        "where": "## Where it works",
        "where_body": "Only on the hospital's own computers, inside the hospital network. {cloud}",
        "who": "## Who sees what",
        "who_body": (
            "Study staff see lists of possible candidates with the record passages they rest on, and decide. A chart "
            "number is shown only to study staff with the right to see it, and every view is recorded. The treating "
            "physician is asked before any patient is contacted."
        ),
        "leaves": "## What leaves the hospital",
        "leaves_body": (
            "Only counts that the investigator releases. A count under {k} is shown as <{k}. No list, no note and "
            "no chart number leaves the hospital. The vendor's support never receives patient data."
        ),
        "keep": "## How long it is kept",
        "keep_body": (
            "- Lists and reports: {outputs} days\n"
            "- Mail attachments: {attachments} days\n"
            "- Service logs (no patient data): {logs} days\n"
            "- Mail log: {mail} days\n"
            "- Copies of the research database: {nightly} nightly and {months} monthly\n"
            "- The record of who saw what: {audit} years"
        ),
        "optout": "## If a patient does not want this",
        "optout_body": (
            "The patient tells the hospital (see the hospital's notice). From the next night the patient's records "
            "are no longer used for counts, lists or summaries. Counts already reported cannot be changed."
        ),
        "ask": "## Questions",
        "ask_body": "{contact}",
        "no_contact": "the hospital's research office",
    },
    "ja": {
        "title": "{site} における TrialBox の診療情報の取り扱い",
        "what": "## TrialBox とは",
        "read": "## 読み取る情報",
        "read_body": (
            "当院を受診された患者さんの診療情報（年齢、性別、病名、処方、検査結果、受診予定、診療記録）です。"
            "{source}から取り込みます。氏名とカルテ番号は取り込み時に記号に置き換え、元に戻すための対応表は暗号化"
            "して院内に保管します。"
        ),
        "where": "## 処理する場所",
        "where_body": "当院内のネットワークにある当院のコンピュータだけで処理します。{cloud}",
        "who": "## 誰が何を見るか",
        "who_body": (
            "研究担当者が、根拠となる記録の該当箇所を添えた候補の可能性がある患者さんの一覧を見て、判断します。"
            "カルテ番号は閲覧の権限を持つ研究担当者にだけ表示され、閲覧はすべて記録されます。患者さんへの連絡の前に"
            "必ず主治医の了承を得ます。"
        ),
        "leaves": "## 院外に出るもの",
        "leaves_body": (
            "研究責任者が公開を認めた人数のみです。{k} 未満の人数は <{k} と表示します。一覧、診療記録、カルテ番号は"
            "院外に出ません。開発会社のサポートが患者データを受け取ることはありません。"
        ),
        "keep": "## 保存期間",
        "keep_body": (
            "- 一覧と報告書：{outputs} 日\n"
            "- メールの添付ファイル：{attachments} 日\n"
            "- サービスのログ（患者データなし）：{logs} 日\n"
            "- メールの記録：{mail} 日\n"
            "- 研究用データベースの複製：毎晩 {nightly} 世代、月末 {months} か月分\n"
            "- 閲覧の記録：{audit} 年"
        ),
        "optout": "## 利用を希望されない場合",
        "optout_body": (
            "患者さんは当院にお申し出ください（当院の掲示をご覧ください）。お申し出の翌晩から、人数の集計、一覧、"
            "要約にその患者さんの情報を使いません。すでに報告した人数は変更できません。"
        ),
        "ask": "## お問い合わせ",
        "ask_body": "{contact}",
        "no_contact": "当院の研究支援部門",
    },
    "zh-TW": {
        "title": "TrialBox 在{site}如何處理病歷資料",
        "what": "## TrialBox 是什麼",
        "read": "## 讀取的資料",
        "read_body": (
            "本院就診病人的病歷資料：年齡、性別、疾病、用藥、檢驗結果、預約門診與病歷紀錄，來源為{source}。"
            "姓名與病歷號在匯入時即以代碼取代，對照表加密並保存在院內。"
        ),
        "where": "## 處理的地點",
        "where_body": "僅在本院網路內、本院自己的電腦上處理。{cloud}",
        "who": "## 誰會看到什麼",
        "who_body": (
            "研究人員查看附有依據紀錄段落的可能候選人名單，並自行判斷。病歷號只顯示給有權限的研究人員，每一次查看"
            "都有紀錄。與任何病人聯絡之前，都會先取得主治醫師同意。"
        ),
        "leaves": "## 離開醫院的資料",
        "leaves_body": (
            "只有計畫主持人同意發布的人數。少於 {k} 的人數顯示為 <{k}。名單、病歷紀錄與病歷號都不會離開醫院。"
            "廠商的技術支援不會收到病人資料。"
        ),
        "keep": "## 保存期間",
        "keep_body": (
            "- 名單與報告：{outputs} 天\n"
            "- 郵件附件：{attachments} 天\n"
            "- 服務紀錄（不含病人資料）：{logs} 天\n"
            "- 郵件紀錄：{mail} 天\n"
            "- 研究資料庫的副本：每晚 {nightly} 份、月底 {months} 個月份\n"
            "- 查看紀錄：{audit} 年"
        ),
        "optout": "## 病人不同意使用時",
        "optout_body": (
            "病人向本院提出（請見本院公告）。自提出後的次日晚上起，該病人的資料不再用於人數統計、名單或摘要。"
            "已報告的人數無法變更。"
        ),
        "ask": "## 聯絡窗口",
        "ask_body": "{contact}",
        "no_contact": "本院研究支援單位",
    },
}


def lang_of(raw: str | None) -> str:
    """One of :data:`LANGS`; raises ``ValueError`` for anything else."""
    if raw is None or raw not in LANGS:
        raise ValueError(f"language must be one of {', '.join(LANGS)}, not {raw!r}")
    return raw


def render(settings: Any, lang: str) -> str:
    """The one-pager for ``settings`` (a validated ``tb_contracts.Settings``) in ``lang``."""
    from tb_common.wording import statement

    lang = lang_of(lang)
    t = TEXT[lang]
    retention = settings.retention
    models = settings.models
    values = {
        "site": settings.site.name,
        "source": SOURCE[settings.data_source.type][lang],
        "cloud": CLOUD[bool(models and models.cloud_enabled)][lang],
        "k": settings.thresholds.small_cell,
        "outputs": retention.outputs_days if retention else 365,
        "attachments": retention.attachments_days if retention else 90,
        "logs": retention.logs_days if retention else 365,
        "mail": retention.mail_log_days if retention else 1825,
        "nightly": retention.nightly_snapshots if retention else 3,
        "months": retention.month_end_snapshots_months if retention else 36,
        "audit": retention.audit_years if retention else 10,
        "contact": settings.site.contact or t["no_contact"],
    }
    parts = [
        "# " + t["title"].format(**values),
        t["what"],
        statement(lang),
        t["read"],
        t["read_body"].format(**values),
        t["where"],
        t["where_body"].format(**values),
        t["who"],
        t["who_body"],
        t["leaves"],
        t["leaves_body"].format(**values),
        t["keep"],
        t["keep_body"].format(**values),
        t["optout"],
        t["optout_body"],
        t["ask"],
        t["ask_body"].format(**values),
    ]
    return "\n\n".join(parts) + "\n"


def render_file(path: Path, lang: str | None = None) -> str:
    """Load and validate ``settings.yaml`` at ``path``, then render; ``lang`` defaults to the site's locale."""
    from tb_common.config import load_settings

    settings = load_settings(path)
    return render(settings, lang or settings.site.locale)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--settings", type=Path, default=ROOT / "deploy" / "settings.yaml")
    ap.add_argument("--lang", choices=LANGS, default=None, help="default: the site's locale")
    ap.add_argument("--out", type=Path, default=None, help="write here instead of stdout")
    args = ap.parse_args(argv)
    page = render_file(args.settings, args.lang)
    if args.out:
        args.out.write_text(page, encoding="utf-8")
    else:
        sys.stdout.write(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
