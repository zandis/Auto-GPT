"""The words the CLI verbs say when they cannot start (TOL-CLI; TOL-1 §2.4): what is needed and the command to type,
in en, ja and zh-TW. The language is ``TB_LANG``, else ``LC_ALL`` / ``LANG`` (English otherwise). Standard library and
``tb_common.preflight.lang_of`` only: the host's python runs these verbs."""

from __future__ import annotations

import os

TEXTS: dict[str, dict[str, str]] = {
    "backup_no_pub": {
        "en": "backup: the box's public key {path} is not there, so nothing was backed up. Make it once with: "
        "trialbox backup-keygen --private <file for the sealed envelope> --public {path} (or give --public <file>)",
        "ja": "backup: ボックスの公開鍵 {path} が見つからないため、バックアップは行われませんでした。"
        "次のコマンドで一度だけ作成してください: trialbox backup-keygen --private <封筒に入れるファイル> "
        "--public {path} (または --public <ファイル> を指定)",
        "zh-TW": "backup: 找不到本機的公開金鑰 {path}，因此未進行備份。請先執行一次: "
        "trialbox backup-keygen --private <放入密封信封的檔案> --public {path} (或以 --public <檔案> 指定)",
    },
    "restore_no_source": {
        "en": "restore: name the backup file or the folder it is in, or --last; and give --key <the private key file>. "
        "Example: trialbox restore /mnt/backups --key /media/usb/backup.key. Nothing was changed",
        "ja": "restore: バックアップのファイルまたはそのフォルダ、もしくは --last を指定し、"
        "--key <秘密鍵ファイル> も指定してください。例: trialbox restore /mnt/backups --key /media/usb/backup.key。"
        "何も変更していません",
        "zh-TW": "restore: 請指定備份檔或其所在資料夾 (或 --last)，並以 --key <私密金鑰檔> 提供金鑰。"
        "範例: trialbox restore /mnt/backups --key /media/usb/backup.key。未變更任何資料",
    },
    "restore_both": {
        "en": "restore: name the backup file, or --last (not both). Nothing was changed",
        "ja": "restore: バックアップのファイル、または --last のどちらか一方を指定してください。何も変更していません",
        "zh-TW": "restore: 請指定備份檔，或使用 --last (擇一)。未變更任何資料",
    },
    "restore_no_key": {
        "en": "restore: --key <the private key file> is needed (the file from hospital IT's sealed envelope). "
        "Nothing was changed",
        "ja": "restore: --key <秘密鍵ファイル> が必要です (病院IT部門の封筒にあるファイル)。何も変更していません",
        "zh-TW": "restore: 需要 --key <私密金鑰檔> (醫院資訊室密封信封中的檔案)。未變更任何資料",
    },
    "restore_empty_folder": {
        "en": "{verb}: there is no backup (*.tbbak) in {folder}: name the folder that holds them or the file itself. "
        "Nothing was changed",
        "ja": "{verb}: {folder} にバックアップ (*.tbbak) がありません。バックアップのあるフォルダまたはファイルを"
        "指定してください。何も変更していません",
        "zh-TW": "{verb}: {folder} 中沒有備份 (*.tbbak)，請指定存放備份的資料夾或檔案本身。未變更任何資料",
    },
    "restore_picked": {
        "en": "{verb}: using {name}, the newest backup in {folder}",
        "ja": "{verb}: {folder} の最新のバックアップ {name} を使用します",
        "zh-TW": "{verb}: 使用 {folder} 中最新的備份 {name}",
    },
    "restore_way_back": {
        "en": "restore: replaces this box's data with {name}. Data the box holds is first kept as an encrypted copy in "
        "{keep}; to undo, run: trialbox restore <that copy> --key <the private key file>",
        "ja": "restore: このボックスのデータを {name} で置き換えます。現在のデータは先に暗号化したコピーとして "
        "{keep} に保存されます。元に戻すには: trialbox restore <そのコピー> --key <秘密鍵ファイル>",
        "zh-TW": "restore: 將以 {name} 取代本機資料。本機現有資料會先加密備份至 {keep}；"
        "如需還原，請執行: trialbox restore <該備份> --key <私密金鑰檔>",
    },
    "restore_no_copy": {
        "en": "restore: --no-copy keeps no copy of the box before the restore: if the restore and then its putting "
        "back both fail, nothing is left to go back to. Add --yes-really to go on without it; nothing was changed",
        "ja": "restore: --no-copy は復元前のコピーを残しません。復元とその巻き戻しの両方が失敗すると戻す先が"
        "ありません。コピーなしで続けるには --yes-really を追加してください。何も変更していません",
        "zh-TW": "restore: --no-copy 不會在還原前保留本機資料的複本；若還原及其復原都失敗，將無從回復。"
        "若仍要繼續，請加上 --yes-really。未變更任何資料",
    },
    "drill_needs": {
        "en": "restore-drill: needs the backup file (or the folder it is in) and --key <the private key file>. "
        "Example: trialbox restore-drill /mnt/backups --key /media/usb/backup.key. Nothing was started",
        "ja": "restore-drill: バックアップのファイル (またはそのフォルダ) と --key <秘密鍵ファイル> が必要です。"
        "例: trialbox restore-drill /mnt/backups --key /media/usb/backup.key。何も開始していません",
        "zh-TW": "restore-drill: 需要備份檔 (或其所在資料夾) 與 --key <私密金鑰檔>。"
        "範例: trialbox restore-drill /mnt/backups --key /media/usb/backup.key。未開始任何作業",
    },
    "mail_no_gateway": {
        "en": "mail: this machine has no mail settings and cannot reach the box's mail gateway ({why}). Run "
        "`trialbox mail status` on the installed box itself (its own command, where Docker and the box's settings "
        "are); the queued mail is untouched",
        "ja": "mail: このマシンにはメール設定がなく、ボックスのメールゲートウェイに接続できません ({why})。"
        "設置済みのボックス上で `trialbox mail status` を実行してください (Dockerとボックスの設定がある場所)。"
        "送信待ちのメールはそのままです",
        "zh-TW": "mail: 此機器沒有郵件設定，也無法連到本機的郵件閘道 ({why})。請在已安裝的主機上直接執行 "
        "`trialbox mail status` (該處有 Docker 與本機設定)；待寄郵件未受影響",
    },
}


def lang() -> str:
    from tb_common.preflight import lang_of

    return lang_of(os.environ.get("TB_LANG") or os.environ.get("LC_ALL") or os.environ.get("LANG"))


def say(key: str, **values: object) -> str:
    return TEXTS[key][lang()].format(**values)
