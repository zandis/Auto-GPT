"""Strings of the support bundle's tab on the operations pages (card 10K-5, D-1381). Joined into the console's
catalogue when ``console.support_bundle_page`` is imported; every key in all three languages."""

from __future__ import annotations

EN: dict[str, str] = {
    "ops.tab.support": "Support bundle",
    "ops.action.support_bundle": "Make a support bundle",
    "ops.confirm.support_bundle": "Make a support bundle now? The box puts part of its state into one file for a "
    "support ticket: the Operations page's status, its health, the release record, the update history (times, steps "
    "and results), the audit trail's check result (counts, no event), and on a site box the container list with its "
    "addresses and ports, the restart counts, df and nvidia-smi. The site's host names, addresses, ports and folder "
    "paths are in it as these print them. Left out of a bundle made here: TrialBox's service logs (they can carry "
    "patient pseudonyms); the .env file and docker compose config (secrets are redacted by the setting's name, "
    "which can miss one); doctor and check_host.sh (doctor prints setting values, among them the backup-alert "
    "watcher's name, who confirmed the TLS root, the serious adverse event office's mail address and service URLs, "
    "and texts read from the database). The error and detail texts of the update history and the Operations status "
    "are replaced by their length and the error's type: they can quote patient-linked values. A credential scan and "
    "a data-handling scan run on the finished file and a file that fails is not handed out; neither scan is proof. "
    "Making it and every download are recorded in the audit trail.",
    "sbundle.help": 'One file for a support ticket, made on the box by the same tool as the command "trialbox '
    'support-bundle". Nothing is sent from the box: you hand the file to support yourself.',
    "sbundle.in": "What it holds: MANIFEST.json (each file, what was changed or left out, and why); "
    "ops-snapshot.json (the Operations page's status: version, updates, rollback points, backups by name, age and "
    "folder path, secrets by name and age only, disks); health.json; release.json; history.jsonl (the last 400 "
    "update steps: time, step, bundle and result); audit-verify.json (the audit trail's check: counts and errors, "
    "no event); and on a site box cmd/compose-ps.txt (the containers, their addresses and ports), cmd/restarts.txt, "
    "cmd/df.txt (disks and mounts) and cmd/nvidia-smi.txt. The site's host names, addresses, ports and folder paths "
    "are in it as these print them.",
    "sbundle.never": "Left out of a bundle made here, and why: TrialBox's service logs (they can carry patient "
    "pseudonyms); the .env file and docker compose config (secrets are redacted by the setting's name, which can "
    "miss one); doctor and check_host.sh (doctor prints setting values, among them the backup-alert watcher's name, "
    "who confirmed the TLS root, the serious adverse event office's mail address and service URLs, and texts read "
    "from the database); the error and detail texts of the update history and the Operations status, each replaced "
    "by its length and the error's type (they can quote patient-linked values). These go into a bundle only when it "
    'is made on the host with the command "trialbox support-bundle", which needs root. Never copied in by either: '
    "the data folder and the Docker volumes, any database table, the secrets folder, keys, backups, the audit trail "
    "itself, the site's settings.yaml, and the logs of PostgreSQL, HAPI FHIR and vLLM. A credential scan and a "
    "data-handling scan run on the finished file, and a file that fails is not handed out; neither scan is proof.",
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
    "sbundle.err.audit": "Not handed out: the download could not be recorded in the audit trail, so no byte of the "
    "file was sent. Check the audit trail's health, then download it again.",
}

JA: dict[str, str] = {
    "ops.tab.support": "サポート用ファイル",
    "ops.action.support_bundle": "サポート用ファイルを作る",
    "ops.confirm.support_bundle": "今すぐサポート用ファイルを作りますか？この機器の状態の一部を、サポートへの問い合"
    "わせ用に1つのファイルにまとめます。内容は、運用画面の状態、機器の状態、リリースの記録、更新履歴（時刻・手順・結"
    "果）、監査記録の検証結果（件数のみ、記録そのものは含まない）、さらにサイトの機器ではコンテナの一覧（アドレスと"
    "ポートを含む）・再起動回数・df・nvidia-smi の出力です。施設のホスト名、アドレス、ポート、フォルダのパスは、これ"
    "らの出力に出るとおり含まれます。ここで作るファイルに入れないもの：TrialBox のサービスログ（患者の仮名IDが含まれ"
    "ることがあるため）、.env ファイルと docker compose config（秘密情報は設定の名前で伏せるため、漏れることがあるた"
    "め）、doctor と check_host.sh（doctor は設定の値を表示し、その中にはバックアップ警告の担当者の名前、TLS ルート"
    "を確認した人、重篤な有害事象の窓口のメールアドレス、サービスの URL が含まれ、データベースから読んだ文も表示する"
    "ため）。更新履歴と運用画面の状態にあるエラーや詳細の文は、長さとエラーの種類に置き換えます。患者に結びつく値を"
    "引用することがあるためです。完成したファイルには認証情報の検査とデータ取扱いスキャンを行い、通らないファイルは"
    "渡しません。ただし、どちらの検査も完全な保証ではありません。作成とダウンロードはすべて監査記録に残ります。",
    "sbundle.help": "サポートへの問い合わせ用のファイルです。コマンド「trialbox support-bundle」と同じ仕組みで、この機"
    "器の上で作られます。機器からは何も送信されません。ファイルはご自身でサポートに渡してください。",
    "sbundle.in": "含まれるもの：MANIFEST.json（各ファイル、変更したものと入れなかったもの、その理由）、ops-snapshot"
    ".json（運用画面の状態：バージョン、更新、切り戻し地点、バックアップの名前・経過時間・フォルダのパス、秘密情報は"
    "名前と経過日数のみ、ディスク）、health.json、release.json、history.jsonl（直近 400 件の更新手順：時刻・手順・バ"
    "ンドル・結果）、audit-verify.json（監査記録の検証：件数とエラーのみ、記録そのものは含まない）、さらにサイトの機"
    "器では cmd/compose-ps.txt（コンテナとそのアドレス・ポート）、cmd/restarts.txt、cmd/df.txt（ディスクとマウント）"
    "、cmd/nvidia-smi.txt。施設のホスト名、アドレス、ポート、フォルダのパスは、これらの出力に出るとおり含まれます。",
    "sbundle.never": "ここで作るファイルに入れないものとその理由：TrialBox のサービスログ（患者の仮名IDが含まれるこ"
    "とがあるため）、.env ファイルと docker compose config（秘密情報は設定の名前で伏せるため、漏れることがあるため）"
    "、doctor と check_host.sh（doctor は設定の値を表示し、その中にはバックアップ警告の担当者の名前、TLS ルートを確"
    "認した人、重篤な有害事象の窓口のメールアドレス、サービスの URL が含まれ、データベースから読んだ文も表示するため"
    "）、更新履歴と運用画面の状態にあるエラーや詳細の文（長さとエラーの種類に置き換えます。患者に結びつく値を引用す"
    "ることがあるため）。これらは、root 権限が必要なホスト上のコマンド「trialbox support-bundle」で作るときだけ入り"
    "ます。どちらの方法でも決して入れないもの：データフォルダと Docker のボリューム、データベースの表、秘密情報のフ"
    "ォルダ、鍵、バックアップ、監査記録そのもの、施設の settings.yaml、PostgreSQL・HAPI FHIR・vLLM のログ。完成した"
    "ファイルには認証情報の検査とデータ取扱いスキャンを行い、通らないファイルは渡しません。ただし、どちらの検査も完"
    "全な保証ではありません。",
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
    "sbundle.err.audit": "渡せません：ダウンロードを監査記録に残せなかったため、ファイルは1バイトも送っていません。"
    "監査記録の状態を確認してから、もう一度ダウンロードしてください。",
}

ZH: dict[str, str] = {
    "ops.tab.support": "支援檔案",
    "ops.action.support_bundle": "製作支援檔案",
    "ops.confirm.support_bundle": "現在製作支援檔案嗎？本機會把自己的部分狀態整理成一個檔案，供支援工單使用：營運頁"
    "面的狀態、本機的健康狀態、版本發行紀錄、更新紀錄（時間、步驟與結果）、稽核紀錄的驗證結果（只有筆數，不含紀錄本"
    "身），以及在院方主機上的容器清單（含位址與連接埠）、重新啟動次數、df 與 nvidia-smi 的輸出。院方的主機名稱、位址"
    "、連接埠與資料夾路徑，會依這些輸出原樣放入。在這裡製作的檔案不放入：TrialBox 的服務日誌（可能有病人的假名代碼）"
    "；.env 檔與 docker compose config（機密資訊是依設定名稱遮蔽，可能漏掉）；doctor 與 check_host.sh（doctor 會印出"
    "設定值，其中有備份警示負責人的姓名、確認 TLS 根憑證的人、嚴重不良事件窗口的電子郵件地址與服務網址，也會印出從資"
    "料庫讀到的文字）。更新紀錄與營運狀態中的錯誤與細節文字會換成其長度與錯誤類型：這些文字可能引用與病人相關的值。"
    "完成的檔案會經過憑證檢查與資料處理掃描，未通過的檔案不會交出；但兩種檢查都不是保證。製作與每次下載都會記入稽核"
    "紀錄。",
    "sbundle.help": "供支援工單使用的單一檔案，在本機上以與指令「trialbox support-bundle」相同的工具製作。本機不會傳送"
    "任何東西：請您自行把檔案交給支援人員。",
    "sbundle.in": "內容：MANIFEST.json（每個檔案、改動或未放入的項目及原因）、ops-snapshot.json（營運頁面的狀態：版"
    "本、更新、回復點、備份的名稱、時間與資料夾路徑、機密資訊只有名稱與天數、磁碟）、health.json、release.json、hist"
    "ory.jsonl（最近 400 個更新步驟：時間、步驟、套件與結果）、audit-verify.json（稽核紀錄的驗證：只有筆數與錯誤，不"
    "含紀錄本身），以及在院方主機上的 cmd/compose-ps.txt（容器及其位址與連接埠）、cmd/restarts.txt、cmd/df.txt（磁碟"
    "與掛載）與 cmd/nvidia-smi.txt。院方的主機名稱、位址、連接埠與資料夾路徑，會依這些輸出原樣放入。",
    "sbundle.never": "在這裡製作的檔案不放入的項目與原因：TrialBox 的服務日誌（可能有病人的假名代碼）；.env 檔與 doc"
    "ker compose config（機密資訊是依設定名稱遮蔽，可能漏掉）；doctor 與 check_host.sh（doctor 會印出設定值，其中有"
    "備份警示負責人的姓名、確認 TLS 根憑證的人、嚴重不良事件窗口的電子郵件地址與服務網址，也會印出從資料庫讀到的文字"
    "）；更新紀錄與營運狀態中的錯誤與細節文字（換成其長度與錯誤類型，因為可能引用與病人相關的值）。這些只有在主機上"
    "以需要 root 權限的指令「trialbox support-bundle」製作時才會放入。兩種方式都絕不放入：資料資料夾與 Docker 磁碟區"
    "、任何資料庫表格、機密資訊資料夾、金鑰、備份、稽核紀錄本身、院方的 settings.yaml，以及 PostgreSQL、HAPI FHIR 與"
    " vLLM 的日誌。完成的檔案會經過憑證檢查與資料處理掃描，未通過的檔案不會交出；但兩種檢查都不是保證。",
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
    "sbundle.err.audit": "未交出：下載無法記入稽核紀錄，因此檔案一個位元組都沒有送出。請先確認稽核紀錄的狀態，再重新"
    "下載。",
}
