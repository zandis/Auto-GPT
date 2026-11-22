"""The console's words of rc1's refusals (``console.rc1_guard``; the table: ``tb_common.rc1_refusals``).

Each refusal's sentence is the table's own (``rc1_refusals.TEXTS``, the command-line tools' words); a test keeps
them equal. Joined into ``console.i18n`` by ``console.rc1_guard``."""

from __future__ import annotations

EN: dict[str, str] = {
    "rc1.live_patient_lists": (
        "rc1 makes and shows no live patient list on a {environment} box. rc1 is a supervised demonstration on "
        "synthetic or public data. No list was made or shown."
    ),
    "problem.h.rc1.live_patient_lists": "Not available in rc1",
    "rc1.edc_writes_from_screening": (
        "rc1 writes nothing from screening to the EDC on a {environment} box. rc1 is a supervised demonstration on "
        "synthetic or public data. Nothing was written."
    ),
    "problem.h.rc1.edc_writes_from_screening": "Not available in rc1",
    "rc1.patient_mail_and_downloads": (
        "rc1 sends no mail with patient files and gives no patient file to download on a {environment} box. rc1 is a "
        "supervised demonstration on synthetic or public data. Nothing was sent or downloaded."
    ),
    "problem.h.rc1.patient_mail_and_downloads": "Not available in rc1",
    "rc1.support_exports": (
        "rc1 makes no support bundle on a {environment} box. rc1 is a supervised demonstration on synthetic or "
        "public data. Nothing was written."
    ),
    "problem.h.rc1.support_exports": "Not available in rc1",
    "rc1.unattended_updates": (
        "rc1 applies no update in the quiet hour on a {environment} box. rc1 is a supervised demonstration on "
        "synthetic or public data. Nothing was applied; an update a person runs now is still allowed."
    ),
    "problem.h.rc1.unattended_updates": "Not available in rc1",
    "rc1.key_ceremonies": (
        "rc1 holds no backup key ceremony and makes no backup key on a {environment} box. rc1 is a supervised "
        "demonstration on synthetic or public data. Nothing was generated."
    ),
    "problem.h.rc1.key_ceremonies": "Not available in rc1",
}

JA: dict[str, str] = {
    "rc1.live_patient_lists": (
        "rc1 は {environment} のボックスでは実際の患者リストを作成も表示もしません。rc1 は合成データまたは公開データ"
        "を使い、担当者の立ち会いのもとで行うデモンストレーションです。リストは作成も表示もしていません。"
    ),
    "problem.h.rc1.live_patient_lists": "rc1 では利用できません",
    "rc1.edc_writes_from_screening": (
        "rc1 は {environment} のボックスではスクリーニングの結果を EDC に書き込みません。rc1 は合成データまたは公開デ"
        "ータを使い、担当者の立ち会いのもとで行うデモンストレーションです。何も書き込んでいません。"
    ),
    "problem.h.rc1.edc_writes_from_screening": "rc1 では利用できません",
    "rc1.patient_mail_and_downloads": (
        "rc1 は {environment} のボックスでは患者のファイルを付けたメールを送らず、患者のファイルのダウンロードも提供"
        "しません。rc1 は合成データまたは公開データを使い、担当者の立ち会いのもとで行うデモンストレーションです。何も"
        "送信もダウンロードもしていません。"
    ),
    "problem.h.rc1.patient_mail_and_downloads": "rc1 では利用できません",
    "rc1.support_exports": (
        "rc1 は {environment} のボックスではサポート用のバンドルを作りません。rc1 は合成データまたは公開データを使い"
        "、担当者の立ち会いのもとで行うデモンストレーションです。何も書いていません。"
    ),
    "problem.h.rc1.support_exports": "rc1 では利用できません",
    "rc1.unattended_updates": (
        "rc1 は {environment} のボックスでは静かな時間帯に更新を自動で適用しません。rc1 は合成データまたは公開データ"
        "を使い、担当者の立ち会いのもとで行うデモンストレーションです。何も適用していません。担当者がその場で行う更新"
        "は引き続きできます。"
    ),
    "problem.h.rc1.unattended_updates": "rc1 では利用できません",
    "rc1.key_ceremonies": (
        "rc1 は {environment} のボックスではバックアップ鍵の手続きを行わず、バックアップ鍵も作りません。rc1 は合成デ"
        "ータまたは公開データを使い、担当者の立ち会いのもとで行うデモンストレーションです。何も生成していません。"
    ),
    "problem.h.rc1.key_ceremonies": "rc1 では利用できません",
}

ZH: dict[str, str] = {
    "rc1.live_patient_lists": (
        "rc1 在 {environment} 主機上不產生也不顯示真實的病人名單。rc1 是使用合成或公開資料、在人員監督下進行的展示。"
        "未產生或顯示任何名單。"
    ),
    "problem.h.rc1.live_patient_lists": "rc1 不提供此功能",
    "rc1.edc_writes_from_screening": (
        "rc1 在 {environment} 主機上不將篩選結果寫入 EDC。rc1 是使用合成或公開資料、在人員監督下進行的展示。未寫入任"
        "何內容。"
    ),
    "problem.h.rc1.edc_writes_from_screening": "rc1 不提供此功能",
    "rc1.patient_mail_and_downloads": (
        "rc1 在 {environment} 主機上不寄送附有病人檔案的郵件，也不提供病人檔案下載。rc1 是使用合成或公開資料、在人員"
        "監督下進行的展示。未寄送或下載任何內容。"
    ),
    "problem.h.rc1.patient_mail_and_downloads": "rc1 不提供此功能",
    "rc1.support_exports": (
        "rc1 在 {environment} 主機上不產生支援套件。rc1 是使用合成或公開資料、在人員監督下進行的展示。未寫入任何內容。"
    ),
    "problem.h.rc1.support_exports": "rc1 不提供此功能",
    "rc1.unattended_updates": (
        "rc1 在 {environment} 主機上不在離峰時段自動套用更新。rc1 是使用合成或公開資料、在人員監督下進行的展示。未套"
        "用任何更新；由人員當下執行的更新仍可進行。"
    ),
    "problem.h.rc1.unattended_updates": "rc1 不提供此功能",
    "rc1.key_ceremonies": (
        "rc1 在 {environment} 主機上不進行備份金鑰儀式，也不產生備份金鑰。rc1 是使用合成或公開資料、在人員監督下進行"
        "的展示。未產生任何內容。"
    ),
    "problem.h.rc1.key_ceremonies": "rc1 不提供此功能",
}
