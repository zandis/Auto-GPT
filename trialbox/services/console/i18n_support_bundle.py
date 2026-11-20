"""Strings of the support bundle's tab on the operations pages (card 10K-5, D-1381). Joined into the console's
catalogue when ``console.support_bundle_page`` is imported; every key in all three languages."""

from __future__ import annotations

EN: dict[str, str] = {
    "ops.tab.support": "Support bundle",
    "ops.action.support_bundle": "Make a support bundle",
    "ops.confirm.support_bundle": "Make a support bundle now? The box puts its state into one file for a support "
    "ticket, field by field from fixed lists, and only values of these kinds: numbers (sizes, counts, ages, "
    "percentages, temperatures), yes or no, times, and values from fixed sets (update steps, health checks and "
    'their levels, service names and states, error types, labels such as "backup" or "bundle-2"). No text, '
    "path, file name, setting, command line, log line or audit event goes in: they stay on the box. The "
    "data-handling scan still runs on the finished file as a second check; it is not what keeps them out. Making it "
    "and every download are recorded in the audit trail.",
    "sbundle.help": 'One file for a support ticket, made on the box by the same tool as the command "trialbox '
    'support-bundle". Nothing is sent from the box: you hand the file to support yourself.',
    "sbundle.in": "What it holds, as numbers, yes or no, times and values from fixed sets only: MANIFEST.json (each "
    "file, and how many fields were left out of it); ops-snapshot.json (the version, updates by step and result, "
    "rollback points, backups by count, age and size, secrets by name and age, disks under fixed labels); "
    "health.json (each check's level and measure); release.json (the version, the release number and hashes); "
    "history.jsonl (each update step's time, step and result, an error only as its type and a length range); "
    "audit-verify.json (whether the audit trail verified, and counts); and on a site box services.json (each "
    'service\'s state, health, restart count and start time), disks.json (sizes under labels such as "system" or '
    '"backup") and gpu.json (memory, load, temperature and driver version).',
    "sbundle.never": "What never goes in: any text a person typed or a program wrote (error messages, notes, "
    "reasons, log lines, audit events), paths and file names (backup folders, USB disks, mount folders), settings "
    "and the .env file, command lines and command output, host names and addresses, the ids of update bundles, "
    "patient data, any database table, secrets, keys, backups and the audit trail itself. A field that is not on a "
    "file's list is dropped and counted in MANIFEST.json. The fuller bundle, with logs and settings, is made only "
    'on the host with the command "trialbox support-bundle", which needs root.',
    "sbundle.who": "Only the administrator may make or download a bundle, and any administrator may download any "
    "bundle kept on the box. Making it is recorded in the audit trail before the file is released, and each download "
    "when it starts, with who, when, the file's size and its SHA-256, never its contents.",
    "sbundle.kept": "The newest {n} bundles are kept on the box, each for at most {days} days; an older one is "
    "removed, and the removal is recorded in the audit trail.",
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
    "sbundle.err.audit": "Not handed out: the download could not be recorded in the audit trail, so no byte of the "
    "file was sent. Check the audit trail's health, then download it again.",
    "sbundle.gone": "Not handed out: that bundle is not on the box as it was made (it was removed, or the file "
    "changed). Make a new one.",
}

JA: dict[str, str] = {
    "ops.tab.support": "サポート用ファイル",
    "ops.action.support_bundle": "サポート用ファイルを作る",
    "ops.confirm.support_bundle": "今すぐサポート用ファイルを作りますか？この機器の状態を、決められた一覧の項目ごと"
    "に、サポートへの問い合わせ用の1つのファイルにまとめます。入るのは次の種類の値だけです：数値（サイズ、件数、経過"
    "時間、割合、温度）、はい・いいえ、時刻、決められた集合の値（更新の手順、状態の点検とその水準、サービス名とその"
    "状態、エラーの種類、「backup」や「bundle-2」のような名札）。文章、パス、ファイル名、設定、コマンドライン、ログ"
    "の行、監査記録の事項は入らず、機器に残ります。完成したファイルには二重の確認としてデータ取扱いスキャンも行いま"
    "すが、それが入らないようにしている仕組みではありません。作成とダウンロードはすべて監査記録に残ります。",
    "sbundle.help": "サポートへの問い合わせ用のファイルです。コマンド「trialbox support-bundle」と同じ仕組みで、この機"
    "器の上で作られます。機器からは何も送信されません。ファイルはご自身でサポートに渡してください。",
    "sbundle.in": "含まれるもの（数値、はい・いいえ、時刻、決められた集合の値のみ）：MANIFEST.json（各ファイルと、そ"
    "こから除いた項目の数）、ops-snapshot.json（バージョン、手順と結果ごとの更新、切り戻し地点、件数・経過時間・サイ"
    "ズごとのバックアップ、名前と経過日数ごとの秘密情報、決められた名札ごとのディスク）、health.json（各点検の水準と"
    "測定値）、release.json（バージョン、リリース番号、ハッシュ）、history.jsonl（各更新手順の時刻・手順・結果。エラ"
    "ーは種類と長さの範囲のみ）、audit-verify.json（監査記録の検証が通ったかと件数）、さらにサイトの機器では service"
    "s.json（各サービスの状態・ヘルス・再起動回数・開始時刻）、disks.json（「system」や「backup」などの名札ごとのサ"
    "イズ）、gpu.json（メモリ、負荷、温度、ドライバのバージョン）。",
    "sbundle.never": "決して含まれないもの：人が入力した、またはプログラムが書いた文章（エラーメッセージ、メモ、理由"
    "、ログの行、監査記録の事項）、パスとファイル名（バックアップのフォルダ、USB ディスク、マウント先のフォルダ）、"
    "設定と .env ファイル、コマンドラインとコマンドの出力、ホスト名とアドレス、更新バンドルの ID、患者データ、データ"
    "ベースの表、秘密情報、鍵、バックアップ、監査記録そのもの。ファイルごとの一覧にない項目は除かれ、その数が MANIFE"
    "ST.json に記されます。ログと設定を含むより詳しいファイルは、root 権限が必要なホスト上のコマンド「trialbox suppo"
    "rt-bundle」でだけ作られます。",
    "sbundle.who": "ファイルを作成・ダウンロードできるのは管理者だけで、どの管理者も機器に残っているどのファイルでも"
    "ダウンロードできます。作成はファイルを渡す前に、ダウンロードは開始時に、誰が、いつ、ファイルのサイズと SHA-256 "
    "とともに監査記録に残ります。中身は記録されません。",
    "sbundle.kept": "機器には最新の {n} 個だけが、それぞれ最長 {days} 日間残ります。それより古いものは削除され、その"
    "削除は監査記録に残ります。",
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
    "sbundle.err.audit": "渡せません：ダウンロードを監査記録に残せなかったため、ファイルは1バイトも送っていません。"
    "監査記録の状態を確認してから、もう一度ダウンロードしてください。",
    "sbundle.gone": "渡せません：そのファイルは、作ったときのままでは機器にありません（削除されたか、ファイルが変わ"
    "りました）。新しく作ってください。",
}

ZH: dict[str, str] = {
    "ops.tab.support": "支援檔案",
    "ops.action.support_bundle": "製作支援檔案",
    "ops.confirm.support_bundle": "現在製作支援檔案嗎？本機會依固定清單逐一取出欄位，把狀態整理成一個檔案供支援工單"
    "使用，且只放入下列種類的值：數字（大小、筆數、時間長度、百分比、溫度）、是或否、時間，以及固定集合中的值（更新"
    "步驟、健康檢查與其等級、服務名稱與狀態、錯誤類型、像「backup」或「bundle-2」這樣的標籤）。文字、路徑、檔名、設"
    "定、指令列、日誌行與稽核紀錄的事項都不會放入，會留在本機。完成的檔案仍會經過資料處理掃描作為第二道檢查，但擋住"
    "這些內容的不是掃描。製作與每次下載都會記入稽核紀錄。",
    "sbundle.help": "供支援工單使用的單一檔案，在本機上以與指令「trialbox support-bundle」相同的工具製作。本機不會傳送"
    "任何東西：請您自行把檔案交給支援人員。",
    "sbundle.in": "內容（只有數字、是或否、時間與固定集合中的值）：MANIFEST.json（每個檔案，以及從中略去的欄位數）、"
    "ops-snapshot.json（版本、依步驟與結果的更新、回復點、依數量、時間與大小的備份、依名稱與天數的機密資訊、依固定標"
    "籤的磁碟）、health.json（每項檢查的等級與量測值）、release.json（版本、發行序號與雜湊值）、history.jsonl（每個"
    "更新步驟的時間、步驟與結果；錯誤只有類型與長度範圍）、audit-verify.json（稽核紀錄是否通過驗證與筆數），以及在院"
    "方主機上的 services.json（每個服務的狀態、健康、重新啟動次數與啟動時間）、disks.json（依「system」或「backup」"
    "等標籤的大小）與 gpu.json（記憶體、負載、溫度與驅動程式版本）。",
    "sbundle.never": "絕不放入：任何人輸入或程式寫出的文字（錯誤訊息、備註、理由、日誌行、稽核紀錄的事項）、路徑與檔"
    "名（備份資料夾、USB 磁碟、掛載資料夾）、設定與 .env 檔、指令列與指令的輸出、主機名稱與位址、更新套件的代號、病"
    "人資料、任何資料庫表格、機密資訊、金鑰、備份，以及稽核紀錄本身。不在檔案清單上的欄位會被略去，數量記在 MANIFEST"
    ".json 中。含日誌與設定的完整檔案，只有在主機上以需要 root 權限的指令「trialbox support-bundle」才會製作。",
    "sbundle.who": "只有管理者可以製作或下載，且任何管理者都可以下載本機保留的任何檔案。製作會在檔案交出前、每次下載會"
    "在開始時記入稽核紀錄，記下是誰、何時、檔案大小與 SHA-256，絕不記錄內容。",
    "sbundle.kept": "本機只保留最新的 {n} 個檔案，每個最多保留 {days} 天；較舊的會被刪除，刪除也會記入稽核紀錄。",
    "sbundle.list": "本機製作的檔案",
    "sbundle.none": "尚未製作支援檔案。",
    "sbundle.download": "下載",
    "sbundle.refused": "未交出：完成的檔案未通過資料處理掃描，因此沒有寫出任何檔案。請稍後再製作，或詢問支援人員該看哪"
    "個檔案。",
    "sbundle.failed": "無法製作檔案；原因請見詳細內容。",
    "sbundle.unaudited": "未交出：製作無法記入稽核紀錄，因此檔案已刪除。請先確認稽核紀錄的狀態，再重新製作。",
    "sbundle.folder": "未製作：本機的營運資料夾設定不正確（是連結，或是其他人可以寫入的資料夾）。請管理本機的人員檢查"
    "。",
    "sbundle.err.audit": "未交出：下載無法記入稽核紀錄，因此檔案一個位元組都沒有送出。請先確認稽核紀錄的狀態，再重新"
    "下載。",
    "sbundle.gone": "未交出：該檔案已不是製作時的樣子（已刪除，或檔案已變動）。請重新製作。",
}
