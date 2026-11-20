"""Strings of the support bundle's tab on the operations pages (card 10K-5, D-1381). Joined into the console's
catalogue when ``console.support_bundle_page`` is imported; every key in all three languages."""

from __future__ import annotations

EN: dict[str, str] = {
    "ops.tab.support": "Support bundle",
    "ops.action.support_bundle": "Make a support bundle",
    "ops.confirm.support_bundle": "Make a support bundle now? The box collects its own diagnostics into one file for a"
    " support ticket. Patient data, secrets, keys, backups and the audit trail never go in; every line the data-handli"
    "ng scan flags is removed, and a file that still fails the scan is not handed out. Making it and every download ar"
    "e recorded in the audit trail.",
    "sbundle.help": 'One file for a support ticket, made on the box by the same tool as the command "trialbox support-'
    'bundle". Nothing is sent from the box: you hand the file to support yourself.',
    "sbundle.in": "What it holds: the version and update history, the box's health and the Operations page's status (s"
    "ecrets by name and age only), the box's .env file with every secret value replaced, the audit trail's check resul"
    "t (counts, no event), the checks of doctor and of the host, the container list and restart counts, disk and GPU s"
    "tate, and the last three collected days of TrialBox's own service logs, scrubbed.",
    "sbundle.never": "What never goes in: patient data or any database, the data folder and the Docker volumes, secret"
    "s, keys and tokens, backups, the audit trail itself, the site's settings.yaml, and the logs of PostgreSQL, HAPI F"
    "HIR and vLLM.",
    "sbundle.who": "Only the administrator may make or download a bundle. Each download is recorded in the audit trail"
    " with who, when, the file's size and its SHA-256, never its contents.",
    "sbundle.kept": "The newest {n} bundles are kept on the box; an older one is removed when a new one is made.",
    "sbundle.list": "Bundles made on this box",
    "sbundle.none": "No support bundle made yet.",
    "sbundle.download": "Download",
    "sbundle.refused": "Not handed out: the finished bundle did not pass the data-handling scan, so nothing was writte"
    "n. Make it again later, or ask support which file to look at.",
    "sbundle.failed": "The bundle could not be made; the details say why.",
}

JA: dict[str, str] = {
    "ops.tab.support": "サポート用ファイル",
    "ops.action.support_bundle": "サポート用ファイルを作る",
    "ops.confirm.support_bundle": "今すぐサポート用ファイルを作りますか？この機器の診断情報を、サポートへの問い合わせ"
    "用に1つのファイルにまとめます。患者データ、秘密情報、鍵、バックアップ、監査記録は入りません。データ取扱いスキャン"
    "が検出した行はすべて削除され、それでもスキャンを通らないファイルは渡されません。作成とダウンロードはすべて監査記"
    "録に残ります。",
    "sbundle.help": "サポートへの問い合わせ用のファイルです。コマンド「trialbox support-bundle」と同じ仕組みで、この機"
    "器の上で作られます。機器からは何も送信されません。ファイルはご自身でサポートに渡してください。",
    "sbundle.in": "含まれるもの：バージョンと更新履歴、機器の状態と運用画面の状態（秘密情報は名前と経過日数のみ）、秘"
    "密の値をすべて置き換えた .env ファイル、監査記録の検証結果（件数のみ、記録そのものは含まない）、doctor とホストの"
    "点検結果、コンテナの一覧と再起動回数、ディスクと GPU の状態、TrialBox 自身のサービスログ（直近 3 日分、個人情報を"
    "除去済み）。",
    "sbundle.never": "決して含まれないもの：患者データやデータベース、データフォルダと Docker のボリューム、秘密情報・"
    "鍵・トークン、バックアップ、監査記録そのもの、施設の settings.yaml、PostgreSQL・HAPI FHIR・vLLM のログ。",
    "sbundle.who": "ファイルを作成・ダウンロードできるのは管理者だけです。ダウンロードのたびに、誰が、いつ、ファイルの"
    "サイズと SHA-256 が監査記録に残ります。中身は記録されません。",
    "sbundle.kept": "機器には最新の {n} 個だけが残り、新しく作ると古いものは削除されます。",
    "sbundle.list": "この機器で作ったファイル",
    "sbundle.none": "サポート用ファイルはまだ作られていません。",
    "sbundle.download": "ダウンロード",
    "sbundle.refused": "渡せません：完成したファイルがデータ取扱いスキャンを通らなかったため、何も書き出していません。"
    "時間をおいて作り直すか、どのファイルを見ればよいかサポートに確認してください。",
    "sbundle.failed": "ファイルを作れませんでした。理由は詳細をご覧ください。",
}

ZH: dict[str, str] = {
    "ops.tab.support": "支援檔案",
    "ops.action.support_bundle": "製作支援檔案",
    "ops.confirm.support_bundle": "現在製作支援檔案嗎？本機會把自己的診斷資訊整理成一個檔案，供支援工單使用。病人資料"
    "、機密資訊、金鑰、備份與稽核紀錄都不會放入；資料處理掃描標出的每一行都會刪除，仍未通過掃描的檔案不會交出。製作與"
    "每次下載都會記入稽核紀錄。",
    "sbundle.help": "供支援工單使用的單一檔案，在本機上以與指令「trialbox support-bundle」相同的工具製作。本機不會傳送"
    "任何東西：請您自行把檔案交給支援人員。",
    "sbundle.in": "內容：版本與更新紀錄、本機的健康狀態與營運頁面的狀態（機密資訊只有名稱與天數）、所有機密值都已取代"
    "的 .env 檔、稽核紀錄的驗證結果（只有筆數，不含紀錄本身）、doctor 與主機的檢查結果、容器清單與重新啟動次數、磁碟與"
    " GPU 狀態，以及 TrialBox 自身服務最近三天已收集並清除個資的日誌。",
    "sbundle.never": "絕不放入：病人資料或任何資料庫、資料資料夾與 Docker 磁碟區、機密資訊、金鑰與權杖、備份、稽核紀錄"
    "本身、院方的 settings.yaml，以及 PostgreSQL、HAPI FHIR 與 vLLM 的日誌。",
    "sbundle.who": "只有管理者可以製作或下載。每次下載都會在稽核紀錄中記下是誰、何時、檔案大小與 SHA-256，絕不記錄內容"
    "。",
    "sbundle.kept": "本機只保留最新的 {n} 個檔案；製作新的檔案時，較舊的會被刪除。",
    "sbundle.list": "本機製作的檔案",
    "sbundle.none": "尚未製作支援檔案。",
    "sbundle.download": "下載",
    "sbundle.refused": "未交出：完成的檔案未通過資料處理掃描，因此沒有寫出任何檔案。請稍後再製作，或詢問支援人員該看哪"
    "個檔案。",
    "sbundle.failed": "無法製作檔案；原因請見詳細內容。",
}
