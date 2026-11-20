"""Strings of the support bundle's tab on the operations pages (card 10K-5, D-1381). Joined into the console's
catalogue when ``console.support_bundle_page`` is imported; every key in all three languages."""

from __future__ import annotations

EN: dict[str, str] = {
    "ops.tab.support": "Support bundle",
    "ops.action.support_bundle": "Make a support bundle",
    "ops.confirm.support_bundle": "Make a support bundle now? The box collects its own state into one file for a "
    "support ticket: the version and update history, its health, the .env file with every secret value replaced, and "
    "what doctor, check_host.sh, docker compose config (secret values replaced), the container list, df and nvidia-smi "
    "print. TrialBox's service logs are left out for now: they can carry patient pseudonyms, so they go into a bundle "
    "only when it is made on the host with the command, which needs root. Patient data, secrets, keys, backups and "
    "the audit trail never go in; every line the data-handling scan flags is removed, and a file that still fails the "
    "scan is not handed out. Making it and every download are recorded in the audit trail.",
    "sbundle.help": 'One file for a support ticket, made on the box by the same tool as the command "trialbox '
    'support-bundle". Nothing is sent from the box: you hand the file to support yourself.',
    "sbundle.in": "What it holds: the version and update history, the box's health and the Operations page's status "
    "(secrets by name and age only), the box's .env file with every secret value replaced, the audit trail's check "
    "result (counts, no event), what doctor and the host check print, docker compose config with every secret value "
    "replaced, the container list and restart counts, and disk and GPU state.",
    "sbundle.never": "What never goes in: patient data or any database, the data folder and the Docker volumes, "
    "secrets, keys and tokens, backups, the audit trail itself, the site's settings.yaml, and the logs of PostgreSQL, "
    "HAPI FHIR and vLLM. TrialBox's own service logs are left out of a bundle made here for now: they can carry "
    'patient pseudonyms, so they go into a bundle only when it is made on the host with the command "trialbox '
    'support-bundle", which needs root.',
    "sbundle.who": "Only the administrator may make or download a bundle, and any administrator may download any "
    "bundle kept on the box. Making it is recorded in the audit trail before the file is released, and each download "
    "when it starts, with who, when, the file's size and its SHA-256, never its contents.",
    "sbundle.kept": "The newest {n} bundles are kept on the box; an older one is removed when a new one is made.",
    "sbundle.list": "Bundles made on this box",
    "sbundle.none": "No support bundle made yet.",
    "sbundle.download": "Download",
    "sbundle.refused": "Not handed out: the finished bundle did not pass the data-handling scan, so nothing was "
    "written. Make it again later, or ask support which file to look at.",
    "sbundle.failed": "The bundle could not be made; the details say why.",
    "sbundle.unaudited": "Not handed out: the making could not be recorded in the audit trail, so the bundle was "
    "removed. Check the audit trail's health, then make it again.",
    "sbundle.folder": "Not made: the box's operations folder is not set up as it must be (a link, or a folder others "
    "may write). Ask the person who runs the box to check it.",
}

JA: dict[str, str] = {
    "ops.tab.support": "サポート用ファイル",
    "ops.action.support_bundle": "サポート用ファイルを作る",
    "ops.confirm.support_bundle": "今すぐサポート用ファイルを作りますか？この機器の状態を、サポートへの問い合わせ用に"
    "1つのファイルにまとめます。内容は、バージョンと更新履歴、機器の状態、秘密の値をすべて置き換えた .env ファイル、"
    "doctor・check_host.sh・docker compose config（秘密の値は置き換え済み）・コンテナの一覧・df・nvidia-smi の出力"
    "です。"
    "TrialBox のサービスログは当面入りません。患者の仮名IDが含まれることがあるため、root 権限が必要なホスト上のコマンド"
    "で作るときだけ入ります。患者データ、秘密情報、鍵、バックアップ、監査記録は入りません。データ取扱いスキャンが検出"
    "した行はすべて削除され、それでもスキャンを通らないファイルは渡されません。作成とダウンロードはすべて監査記録に残"
    "ります。",
    "sbundle.help": "サポートへの問い合わせ用のファイルです。コマンド「trialbox support-bundle」と同じ仕組みで、この機"
    "器の上で作られます。機器からは何も送信されません。ファイルはご自身でサポートに渡してください。",
    "sbundle.in": "含まれるもの：バージョンと更新履歴、機器の状態と運用画面の状態（秘密情報は名前と経過日数のみ）、秘"
    "密の値をすべて置き換えた .env ファイル、監査記録の検証結果（件数のみ、記録そのものは含まない）、doctor とホストの"
    "点検の出力、秘密の値をすべて置き換えた docker compose config、コンテナの一覧と再起動回数、ディスクと GPU の状態。",
    "sbundle.never": "決して含まれないもの：患者データやデータベース、データフォルダと Docker のボリューム、秘密情報・"
    "鍵・トークン、バックアップ、監査記録そのもの、施設の settings.yaml、PostgreSQL・HAPI FHIR・vLLM のログ。TrialBox "
    "自身のサービスログも、ここで作るファイルには当面入りません。患者の仮名IDが含まれることがあるため、root 権限が必要"
    "なホスト上のコマンド「trialbox support-bundle」で作るときだけ入ります。",
    "sbundle.who": "ファイルを作成・ダウンロードできるのは管理者だけで、どの管理者も機器に残っているどのファイルでも"
    "ダウンロードできます。作成はファイルを渡す前に、ダウンロードは開始時に、誰が、いつ、ファイルのサイズと SHA-256 "
    "とともに監査記録に残ります。中身は記録されません。",
    "sbundle.kept": "機器には最新の {n} 個だけが残り、新しく作ると古いものは削除されます。",
    "sbundle.list": "この機器で作ったファイル",
    "sbundle.none": "サポート用ファイルはまだ作られていません。",
    "sbundle.download": "ダウンロード",
    "sbundle.refused": "渡せません：完成したファイルがデータ取扱いスキャンを通らなかったため、何も書き出していません。"
    "時間をおいて作り直すか、どのファイルを見ればよいかサポートに確認してください。",
    "sbundle.failed": "ファイルを作れませんでした。理由は詳細をご覧ください。",
    "sbundle.unaudited": "渡せません：作成を監査記録に残せなかったため、ファイルは削除されました。監査記録の状態を確"
    "認してから、作り直してください。",
    "sbundle.folder": "作れません：機器の運用フォルダが正しく設定されていません（リンク、または他の人が書き込めるフォ"
    "ルダ）。機器を管理する担当者に確認を依頼してください。",
}

ZH: dict[str, str] = {
    "ops.tab.support": "支援檔案",
    "ops.action.support_bundle": "製作支援檔案",
    "ops.confirm.support_bundle": "現在製作支援檔案嗎？本機會把自己的狀態整理成一個檔案，供支援工單使用：版本與更新"
    "紀錄、本機的健康狀態、所有機密值都已取代的 .env 檔，以及 doctor、check_host.sh、docker compose config（機密值已"
    "取代）、容器清單、df 與 nvidia-smi 的輸出。TrialBox 的服務日誌暫時不放入：日誌中可能有病人的假名代碼，因此只有在"
    "主機上以需要 root 權限的指令製作時才會放入。病人資料、機密資訊、金鑰、備份與稽核紀錄都不會放入；資料處理掃描標出"
    "的每一行都會刪除，仍未通過掃描的檔案不會交出。製作與每次下載都會記入稽核紀錄。",
    "sbundle.help": "供支援工單使用的單一檔案，在本機上以與指令「trialbox support-bundle」相同的工具製作。本機不會傳送"
    "任何東西：請您自行把檔案交給支援人員。",
    "sbundle.in": "內容：版本與更新紀錄、本機的健康狀態與營運頁面的狀態（機密資訊只有名稱與天數）、所有機密值都已取代"
    "的 .env 檔、稽核紀錄的驗證結果（只有筆數，不含紀錄本身）、doctor 與主機檢查的輸出、所有機密值都已取代的 docker "
    "compose config、容器清單與重新啟動次數，以及磁碟與 GPU 狀態。",
    "sbundle.never": "絕不放入：病人資料或任何資料庫、資料資料夾與 Docker 磁碟區、機密資訊、金鑰與權杖、備份、稽核紀錄"
    "本身、院方的 settings.yaml，以及 PostgreSQL、HAPI FHIR 與 vLLM 的日誌。在這裡製作的檔案暫時也不放入 TrialBox 自"
    "身的服務日誌：日誌中可能有病人的假名代碼，因此只有在主機上以需要 root 權限的指令「trialbox support-bundle」製作時"
    "才會放入。",
    "sbundle.who": "只有管理者可以製作或下載，且任何管理者都可以下載本機保留的任何檔案。製作會在檔案交出前、每次下載會"
    "在開始時記入稽核紀錄，記下是誰、何時、檔案大小與 SHA-256，絕不記錄內容。",
    "sbundle.kept": "本機只保留最新的 {n} 個檔案；製作新的檔案時，較舊的會被刪除。",
    "sbundle.list": "本機製作的檔案",
    "sbundle.none": "尚未製作支援檔案。",
    "sbundle.download": "下載",
    "sbundle.refused": "未交出：完成的檔案未通過資料處理掃描，因此沒有寫出任何檔案。請稍後再製作，或詢問支援人員該看哪"
    "個檔案。",
    "sbundle.failed": "無法製作檔案；原因請見詳細內容。",
    "sbundle.unaudited": "未交出：製作無法記入稽核紀錄，因此檔案已刪除。請先確認稽核紀錄的狀態，再重新製作。",
    "sbundle.folder": "未製作：本機的營運資料夾設定不正確（是連結，或是其他人可以寫入的資料夾）。請管理本機的人員檢查"
    "。",
}
