"""``python -m tools.backup_key_ceremony`` (10K-13, D-1379): the backup-key ceremony on the box's host.

    python -m tools.backup_key_ceremony --stick /media/usb --operator "<name>" --witness "<name>" [--lang ja]

Hospital IT, as root on the box's host, with a witness who is another person (TB-SOP-03 §2), makes the box's backup
key pair once. The private key leaves the box in two forms and no other:

* **the stick**: ``trialbox-backup.key`` in the format ``trialbox backup-keygen`` writes (``backup.load_private``
  reads it; ``restore --key`` and ``restore-drill --key`` take it as they are);
* **the paper sheet**: ``trialbox-backup-key-paper.txt`` on the same stick, to be printed. The key is four lines of
  base32 letters in groups of four; each line ends with four check letters (the line's number and letters hashed),
  and the sheet carries the key's fingerprint. :func:`read_paper` checks a sheet's text (each line's check letters,
  the order, the count, the fingerprint), naming the line and never its letters; the ceremony runs it on the file it
  has just written. No command reads a sheet typed back by a person yet (D-1379).

The key is made in memory and written only to the stick: never to the box's disks, the screen, a log or the audit.
The stick's folder is opened once, before the removable-media check, and held open: the check is made on that open
folder, and both files are made in it (``dir_fd``), each on the device checked; no path on the stick is resolved
again after the check. On the stick a file must be the key's alone (no bit for the group or others, owned by root):
a stick whose filesystem cannot keep that (a FAT or exFAT stick mounted with a wide mask) is refused before a byte of
the key is written, saying how to mount it (``uid=0,gid=0,umask=077``).

The order (D-1379): the two stick files (each created here or not at all, written in full, synced), the stick's
folder synced, both files read back through the open folder (each must give the public key just made), the public
key as a synced temporary file beside ``backup.pub``, the audit event ``backup.key_ceremony`` (when, the key's
fingerprint, the person who ran it and the witness; never the key, a line of the sheet or a path on the stick), and
only then ``backup.pub`` linked to its name without overwriting: ``trialbox backup`` reads ``backup.pub``, so no
backup can be made to the key before the event that names it is on disk. What the run made or replaced as root in the
audit folder is given back to the folder's owner (D-724) and checked. The ceremony is one failure domain until the
link: a failure at any step after the first file is made removes every file it made, each only when it is still the
file made (same device, inode and size), syncs each folder it removed from, and says which were removed, which are
left, and which removals are not confirmed on disk. When the event is on disk but ``backup.pub`` could not be linked,
``backup.key_ceremony_undone`` is written before the undo, and the once-only check counts that pair as not done. Once
``backup.pub`` may have been visible, nothing of the key is removed: a warning, exit 2. Also exit 2: the event's line
synced but its head anchor not confirmed; an audit file left root's. What is not covered (D-1379): a power loss or a
kill after the event's line is on disk and before ``backup.pub`` is linked (the audit then refuses a rerun and says
how to go on), and a stick pulled before the undo (the refusal names its files as left).

Refused, before anything is written: not root; the operator or the witness not named, or the same person (compared
after NFKC, with spaces collapsed and case folded); no audit folder; a box that has a backup key already, or whose
audit holds a ceremony already (a ceremony is run once; a new pair is the key's rotation, RUNBOOK §25, not this
command); no secrets folder to check the stick against; no stick at the folder named; a folder on the box's disks or
inside the secrets folder; a stick that cannot be written; a file of either name already on the stick (a link
included); an audit whose day files cannot be read whole (a damaged or cut-off line). Every text is in en, ja and
zh-TW (``--lang``; no setting is read for it).

Not here (D-1379): reading the paper sheet into a restore (``restore --key`` takes the stick's file), a console page,
a printer.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import errno
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FORMAT = "tb-backup-paper/1"
EVENT = "backup.key_ceremony"
UNDONE_EVENT = "backup.key_ceremony_undone"  # written when the event is on disk but backup.pub was never put in place
ACTOR = "python -m tools.backup_key_ceremony"
KEY_FILE = "trialbox-backup.key"
PAPER_FILE = "trialbox-backup-key-paper.txt"
LINE_CHARS = 16  # four groups of four letters a line
CHECK_CHARS = 4  # 20 bits: a random slip passes about once in a million
NAME_MAX = 100
LANGS = ("en", "ja", "zh-TW")
DEFAULT_DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
KEPT_EXIT = 2  # the key is kept and its audit line is on disk, but something after it is not confirmed: a warning

# ------------------------------------------------------------------------------------------------ texts (en, ja, zh-TW)
NOT_ROOT = {
    "en": "refused: the backup-key ceremony is run on the box's host as root, by hospital IT (TB-SOP-03 §2)",
    "ja": "拒否：バックアップ鍵の手続きは、病院の情報システム担当がボックスのホストで root として"
    "実行します（TB-SOP-03 §2）",
    "zh-TW": "已拒絕：備份金鑰儀式須由醫院資訊人員在主機上以 root 身分執行（TB-SOP-03 §2）",
}
NO_NAMES = {
    "en": "refused: two people: name the person who runs the ceremony (--operator) and the witness (--witness)",
    "ja": "拒否：二人で行います。実行する人（--operator）と立会人（--witness）の名前を指定してください",
    "zh-TW": "已拒絕：須兩人在場：請指定執行儀式的人（--operator）與見證人（--witness）",
}
BAD_NAME = {
    "en": "refused: a name is one printable line of at most 100 characters",
    "ja": "拒否：名前は 100 文字以内の印字できる 1 行です",
    "zh-TW": "已拒絕：姓名須為一行可列印的文字，最多 100 個字元",
}
SAME_PERSON = {
    "en": "refused: the witness is another person than the one who runs the ceremony",
    "ja": "拒否：立会人は実行する人とは別の人です",
    "zh-TW": "已拒絕：見證人必須是執行儀式者以外的另一人",
}
NO_AUDIT = {
    "en": "refused: no audit folder (--audit-dir, TB_AUDIT_DIR): the ceremony is an audit event",
    "ja": "拒否：監査記録のフォルダーがありません（--audit-dir、TB_AUDIT_DIR）。この手続きは監査記録に残します",
    "zh-TW": "已拒絕：沒有稽核紀錄資料夾（--audit-dir、TB_AUDIT_DIR）：此儀式必須寫入稽核紀錄",
}
ALREADY = {
    "en": "refused: this box has a backup key already (fingerprint {fp}): the ceremony is run once; a new key pair "
    "is the backup key's rotation (RUNBOOK §25), not this command",
    "ja": "拒否：このボックスにはすでにバックアップ鍵があります（指紋 {fp}）。この手続きは 1 回だけです。"
    "新しい鍵の組は鍵の更新（RUNBOOK §25）で行い、このコマンドでは行いません",
    "zh-TW": "已拒絕：此主機已有備份金鑰（指紋 {fp}）：此儀式只執行一次；新的金鑰組屬於備份金鑰的輪替"
    "（RUNBOOK §25），不使用此指令",
}
NO_SECRETS = {
    "en": "refused: the secrets folder {path} is not here (--secrets, TB_SECRETS_DIR): the stick is checked against it",
    "ja": "拒否：秘密情報のフォルダー {path} がありません（--secrets、TB_SECRETS_DIR）。"
    "USB メモリはこれと比べて確認します",
    "zh-TW": "已拒絕：找不到機密資料夾 {path}（--secrets、TB_SECRETS_DIR）：須以它核對隨身碟",
}
NO_STICK = {
    "en": "refused: no stick at {path}: insert the stick and name its mounted folder (it is never made here)",
    "ja": "拒否：{path} に USB メモリがありません。USB メモリを差し込み、マウントされたフォルダーを指定してください"
    "（ここでフォルダーは作りません）",
    "zh-TW": "已拒絕：{path} 沒有隨身碟：請插入隨身碟並指定其掛載的資料夾（此處不會建立資料夾）",
}
NOT_A_STICK = {
    "en": "refused: {path} is not a removable stick (it is on the box's disks or in its secrets folder): the key "
    "goes only to a stick",
    "ja": "拒否：{path} は取り外せる USB メモリではありません（ボックスのディスクか秘密情報のフォルダーです）。"
    "鍵は USB メモリにだけ書きます",
    "zh-TW": "已拒絕：{path} 不是可移除的隨身碟（位於主機的磁碟或機密資料夾內）：金鑰只寫入隨身碟",
}
NOT_WRITABLE = {
    "en": "refused: the stick at {path} cannot be written (read-only or full): use another stick",
    "ja": "拒否：{path} の USB メモリに書き込めません（書き込み禁止か空きがありません）。"
    "別の USB メモリを使ってください",
    "zh-TW": "已拒絕：{path} 的隨身碟無法寫入（唯讀或已滿）：請改用另一個隨身碟",
}
STICK_HAS_KEY = {
    "en": "refused: a file named {name} is already on the stick (a key, a link or anything else): a key is never "
    "written over it or through it; use an empty stick",
    "ja": "拒否：USB メモリにはすでに {name} という名前のファイル（鍵、リンクなど）があります。鍵はその上にも、"
    "その先にも書きません。空の USB メモリを使ってください",
    "zh-TW": "已拒絕：隨身碟上已有名為 {name} 的檔案（金鑰、連結或其他）：金鑰絕不覆寫它，也不經由它寫入；"
    "請改用空的隨身碟",
}
AUDITED_ALREADY = {
    "en": "refused: the audit already holds this box's backup-key ceremony of {at} (fingerprint {fp}): the ceremony "
    "is run once; a new key pair is the backup key's rotation (RUNBOOK §25), not this command",
    "ja": "拒否：監査記録にはすでにこのボックスのバックアップ鍵の手続き（{at}、指紋 {fp}）があります。"
    "この手続きは 1 回だけです。新しい鍵の組は鍵の更新（RUNBOOK §25）で行い、このコマンドでは行いません",
    "zh-TW": "已拒絕：稽核紀錄已有此主機的備份金鑰儀式（{at}，指紋 {fp}）：此儀式只執行一次；新的金鑰組屬於"
    "備份金鑰的輪替（RUNBOOK §25），不使用此指令",
}
STICK_MOVED = {
    "en": "refused: {name} was not made on the stick checked at {path} (another device: the stick was pulled or "
    "mounted again)",
    "ja": "拒否：{name} は確認した {path} の USB メモリの上に作られませんでした（別の装置です。USB メモリが抜かれたか、"
    "マウントし直されました）",
    "zh-TW": "已拒絕：{name} 並非建立在先前核對的 {path} 隨身碟上（為另一個裝置：隨身碟已被拔出或重新掛載）",
}
READ_BACK = {
    "en": "refused: the stick's copy did not read back as the key just made: use another stick",
    "ja": "拒否：USB メモリから読み直した鍵が作った鍵と一致しません。別の USB メモリを使ってください",
    "zh-TW": "已拒絕：從隨身碟讀回的金鑰與剛建立的不一致：請改用另一個隨身碟",
}
PUB_FAILED = {
    "en": "refused: the box's public key could not be put at {path}: the ceremony is not done",
    "ja": "拒否：ボックスの公開鍵を {path} に置けませんでした。手続きは完了していません",
    "zh-TW": "已拒絕：無法將主機的公開金鑰放到 {path}：儀式未完成",
}
AUDIT_FAILED = {
    "en": "refused: the audit event could not be written to {path} (full, or a broken chain): the ceremony is not done",
    "ja": "拒否：監査記録を {path} に書けませんでした（空きがないか、チェーンが壊れています）。"
    "手続きは完了していません",
    "zh-TW": "已拒絕：無法將稽核紀錄寫入 {path}（空間已滿或稽核鏈損壞）：儀式未完成",
}
INTERRUPTED = {
    "en": "refused: the ceremony was interrupted: it is not done",
    "ja": "拒否：手続きが中断されました。完了していません",
    "zh-TW": "已拒絕：儀式被中斷：未完成",
}
UNEXPECTED = {
    "en": "refused: the ceremony stopped on an unexpected error ({kind}): it is not done",
    "ja": "拒否：予期しないエラー（{kind}）で手続きが止まりました。完了していません",
    "zh-TW": "已拒絕：儀式因非預期的錯誤（{kind}）而中止：未完成",
}
KEPT_NOTHING = {
    "en": "Nothing had been written.",
    "ja": "まだ何も書いていませんでした。",
    "zh-TW": "尚未寫入任何內容。",
}
REMOVED_ALL = {
    "en": "Removed again: {files}; nothing of the key is kept.",
    "ja": "書いたものは削除しました：{files}。鍵は何も残っていません。",
    "zh-TW": "已寫入的已刪除：{files}；金鑰未留下任何內容。",
}
REMOVED_SOME = {
    "en": "Removed again: {files}.",
    "ja": "書いたものは削除しました：{files}。",
    "zh-TW": "已寫入的已刪除：{files}。",
}
LEFT = {
    "en": "NOT removed, remove by hand now: {files}.",
    "ja": "削除できませんでした。今すぐ手で削除してください：{files}。",
    "zh-TW": "無法刪除，請立即手動刪除：{files}。",
}
DONE = {
    "en": "backup key {fp} made. The stick holds {key} and the paper sheet {paper}; both were read back. Unmount "
    "(eject) the stick before you pull it out. Print the sheet; the stick and the paper go into hospital IT's sealed "
    "envelope. The box keeps the public key only ({pub}); the audit event {event} names {operator} and the witness "
    "{witness}.",
    "ja": "バックアップ鍵 {fp} を作りました。USB メモリには {key} と紙の控え {paper} があり、どちらも読み直して確認"
    "しました。USB メモリは抜く前にアンマウント（取り出し）してください。紙の控えを印刷し、USB メモリと紙は病院の情報"
    "システム担当の封筒に封をして保管します。ボックスには公開鍵（{pub}）だけが残ります。監査記録 {event} には "
    "{operator} と立会人 {witness} の名前があります。",
    "zh-TW": "已建立備份金鑰 {fp}。隨身碟上有 {key} 與紙本 {paper}，兩者都已讀回確認。拔出隨身碟前請先卸載（退出）。"
    "請列印紙本；隨身碟與紙本放入醫院資訊人員的密封信封。主機只保留公開金鑰（{pub}）；稽核紀錄 {event} 記有 "
    "{operator} 與見證人 {witness}。",
}
PAPER_CHECK = {
    "en": "paper key line {n}: the check letters do not match: a letter of this line is mistyped",
    "ja": "紙の鍵の {n} 行目：確認用の文字が一致しません。この行の文字が打ち間違っています",
    "zh-TW": "紙本金鑰第 {n} 行：檢查碼不符：此行有字母輸入錯誤",
}
PAPER_SHAPE = {
    "en": "paper key line {n}: not a line of the sheet, out of order or missing: type each line as printed",
    "ja": "紙の鍵の {n} 行目：控えの行の形でないか、順番が違うか、抜けています。印刷どおりに各行を入力してください",
    "zh-TW": "紙本金鑰第 {n} 行：格式不符、順序錯誤或缺漏：請依列印內容逐行輸入",
}
PAPER_FP = {
    "en": "paper key: the lines do not give the fingerprint printed on the sheet: check the fingerprint line",
    "ja": "紙の鍵：各行から求めた指紋が控えの指紋と一致しません。指紋の行を確認してください",
    "zh-TW": "紙本金鑰：各行算出的指紋與紙本上的指紋不符：請檢查指紋那一行",
}
AUDIT_UNREADABLE = {
    "en": "refused: the audit file {path} cannot be read whole (a damaged or cut-off line), so whether the ceremony "
    "was run already cannot be told: run python tools/audit_verify.py {audit} and have a person look",
    "ja": "拒否：監査記録のファイル {path} を最後まで読めません（壊れた行か途中で切れた行があります）。手続きがすでに"
    "行われたかを判断できません。python tools/audit_verify.py {audit} を実行し、担当者が確認してください",
    "zh-TW": "已拒絕：無法完整讀取稽核紀錄檔 {path}（有損壞或截斷的行），因此無法判斷儀式是否已執行：請執行 "
    "python tools/audit_verify.py {audit} 並由人員檢查",
}
NO_CEREMONY_FOR_KEY = {
    "en": "The audit holds no backup-key ceremony for this key (one cut short, or a key made by backup-keygen).",
    "ja": "監査記録にはこの鍵のバックアップ鍵の手続きがありません（途中で止まった手続きか、backup-keygen で作った"
    "鍵です）。",
    "zh-TW": "稽核紀錄中沒有此金鑰的備份金鑰儀式（儀式中途中斷，或為 backup-keygen 建立的金鑰）。",
}
AUDITED_NO_KEY = {
    "en": "This box has no backup.pub: if that ceremony was undone (its run said so) or its public key was removed, "
    "make the new pair as RUNBOOK §25 says (python -m tools.trialbox backup-keygen) and enter its fingerprint in the "
    "ceremony record.",
    "ja": "このボックスには backup.pub がありません。その手続きが取り消された（実行時にそう表示された）か公開鍵が"
    "削除された場合は、RUNBOOK §25 のとおりに新しい鍵の組を作り（python -m tools.trialbox backup-keygen）、"
    "その指紋を手続きの記録に記入してください。",
    "zh-TW": "此主機沒有 backup.pub：若該儀式已被復原（執行時已如此顯示）或其公開金鑰已被刪除，請依 RUNBOOK §25 "
    "建立新的金鑰組（python -m tools.trialbox backup-keygen），並將其指紋填入儀式紀錄。",
}
AUDIT_MAY_HOLD = {
    "en": "The audit may still hold this run's event (fingerprint {fp}): if it does, a new run of this command is "
    "refused, and the new pair is made as RUNBOOK §25 says.",
    "ja": "監査記録にはこの実行の記録（指紋 {fp}）が残っている可能性があります。残っている場合、このコマンドの"
    "再実行は拒否されるため、新しい鍵の組は RUNBOOK §25 のとおりに作ります。",
    "zh-TW": "稽核紀錄可能仍留有此次執行的紀錄（指紋 {fp}）：若是如此，再次執行此指令會被拒絕，新的金鑰組須依 "
    "RUNBOOK §25 建立。",
}
LEFT_GONE = {
    "en": "NOT found where it was made, so NOT removed: {files}: the stick that was pulled may hold it: destroy or "
    "wipe that stick.",
    "ja": "作った場所に見つからないため削除していません：{files}。抜かれた USB メモリに残っている可能性があります。"
    "その USB メモリを破棄するか消去してください。",
    "zh-TW": "在建立的位置找不到，因此未刪除：{files}：被拔出的隨身碟可能仍留有它：請銷毀或抹除該隨身碟。",
}
LEFT_OTHER = {
    "en": "NOT removed: the file now at {files} is not verifiably the one this run made, so it is left as it is; the "
    "stick that was pulled may hold the key: destroy or wipe that stick.",
    "ja": "削除していません：{files} にあるファイルはこの実行で作ったものと確認できないため、そのままにしています。"
    "抜かれた USB メモリに鍵が残っている可能性があります。その USB メモリを破棄するか消去してください。",
    "zh-TW": "未刪除：{files} 現有的檔案無法確認是此次執行建立的，因此保持原狀；被拔出的隨身碟可能仍留有金鑰："
    "請銷毀或抹除該隨身碟。",
}
KEPT_WARNING = {
    "en": "warning: the backup key {fp} is in place (the stick holds {key} and {paper}; the box keeps {pub}) and its "
    "audit line {event} is written, but its head anchor is not confirmed on disk, so the ceremony is not reported as "
    "done. Run python tools/audit_verify.py {audit} now and have a person look; do not run the ceremony again. "
    "Unmount (eject) the stick before you pull it out.",
    "ja": "警告：バックアップ鍵 {fp} は置かれました（USB メモリに {key} と {paper}、ボックスに {pub}）。監査記録 "
    "{event} の行は書かれましたが、その先頭アンカーがディスク上で確認できないため、手続きは完了と報告しません。"
    "今すぐ python tools/audit_verify.py {audit} を実行し、担当者が確認してください。"
    "この手続きを再実行しないでください。USB メモリは抜く前にアンマウント（取り出し）してください。",
    "zh-TW": "警告：備份金鑰 {fp} 已就位（隨身碟上有 {key} 與 {paper}；主機保留 {pub}），其稽核紀錄 {event} 已寫入，"
    "但其頭端錨點未確認寫入磁碟，因此儀式不回報為完成。請立即執行 python tools/audit_verify.py {audit} "
    "並由人員檢查；請勿再次執行此儀式。拔出隨身碟前請先卸載（退出）。",
}
STICK_NOT_PRIVATE = {
    "en": "refused: a file made on the stick at {path} can be read by others (it is not mode 0600 owned by root), so "
    "the key is not written: mount the stick for root only, e.g. mount -o uid=0,gid=0,umask=077 <device> {path} (a "
    "FAT or exFAT stick takes its modes from these options), or use a stick formatted with ext4",
    "ja": "拒否：{path} の USB メモリに作ったファイルをほかの人が読めます（root だけが読める"
    "モード 0600 になりません）。鍵は書きません。USB メモリを root だけが使えるようにマウントしてください。"
    "例：mount -o uid=0,gid=0,umask=077 <device> {path}"
    "（FAT や exFAT の USB メモリのモードはこのオプションで決まります）。"
    "または ext4 でフォーマットした USB メモリを使ってください",
    "zh-TW": "已拒絕：在 {path} 隨身碟上建立的檔案可被他人讀取（不是僅 root 可讀的模式 0600），因此不寫入金鑰：請以僅 "
    "root 可用的方式掛載隨身碟，例如 mount -o uid=0,gid=0,umask=077 <device> {path}（FAT 或 exFAT 隨身碟的模式由"
    "這些選項決定），或改用以 ext4 格式化的隨身碟",
}
REMOVED_NOT_DURABLE = {
    "en": "Removed, but the removal is not confirmed on disk (the folder {folder} did not sync): {files}: after a "
    "power loss they may come back: look in {folder} again, and destroy or wipe a stick that held them.",
    "ja": "削除しましたが、削除がディスク上で確認できません（フォルダー {folder} を同期できませんでした）：{files}。"
    "電源が切れると戻る可能性があります。{folder} をもう一度確認し、それがあった USB メモリは破棄するか消去して"
    "ください。",
    "zh-TW": "已刪除，但刪除未確認寫入磁碟（資料夾 {folder} 無法同步）：{files}：斷電後可能再度出現：請再次檢查 "
    "{folder}，並銷毀或抹除曾存放它們的隨身碟。",
}
AUDIT_OWNER_LEFT = {
    "en": "warning: these files in the audit folder are still root's after the ceremony's event: {files}: the audit "
    "writer cannot add its next event until they are given to the folder's owner ({owner}, with chown).",
    "ja": "警告：手続きの記録のあとも、監査記録のフォルダーのこれらのファイルが root のままです：{files}。"
    "フォルダーの所有者（{owner}、chown で）に戻すまで、監査記録の書き込みは次の記録を追加できません。",
    "zh-TW": "警告：寫入儀式紀錄後，稽核紀錄資料夾中的這些檔案仍屬於 root：{files}：在將它們交還資料夾的擁有者"
    "（{owner}，使用 chown）之前，稽核紀錄寫入程式無法加入下一筆紀錄。",
}
PUB_KEPT_WARNING = {
    "en": "warning: the backup key {fp} is kept: its audit event {event} is written and the stick holds {key} and "
    "{paper}, but putting the public key at {pub} did not finish, and a backup may already use it, so nothing was "
    "removed. Check that {pub} is there and gives the fingerprint {fp}, run python tools/audit_verify.py {audit} and "
    "have a person look; do not run the ceremony again. Unmount (eject) the stick before you pull it out.",
    "ja": "警告：バックアップ鍵 {fp} は残しました。監査記録 {event} は書かれ、USB メモリには {key} と {paper} が"
    "ありますが、公開鍵を {pub} に置く処理が終わっていません。すでにバックアップがそれを使っている可能性があるため、"
    "何も削除していません。{pub} があり、指紋が {fp} であることを確認し、python tools/audit_verify.py {audit} を"
    "実行して担当者が確認してください。この手続きを再実行しないでください。USB メモリは抜く前にアンマウント"
    "（取り出し）してください。",
    "zh-TW": "警告：備份金鑰 {fp} 已保留：其稽核紀錄 {event} 已寫入，隨身碟上有 {key} 與 {paper}，但將公開金鑰放到 "
    "{pub} 的步驟未完成，且備份可能已在使用它，因此未刪除任何內容。請確認 {pub} 存在且指紋為 {fp}，執行 "
    "python tools/audit_verify.py {audit} 並由人員檢查；請勿再次執行此儀式。拔出隨身碟前請先卸載（退出）。",
}
AUDIT_HOLDS = {
    "en": "The audit holds this run's event (fingerprint {fp}), and the event that undoes it could not be written: a "
    "new run of this command is refused, and the new pair is made as RUNBOOK §25 says.",
    "ja": "監査記録にはこの実行の記録（指紋 {fp}）があり、それを取り消す記録を書けませんでした。このコマンドの"
    "再実行は拒否されるため、新しい鍵の組は RUNBOOK §25 のとおりに作ります。",
    "zh-TW": "稽核紀錄留有此次執行的紀錄（指紋 {fp}），且無法寫入復原它的紀錄：再次執行此指令會被拒絕，新的金鑰組"
    "須依 RUNBOOK §25 建立。",
}
SHEET_HEAD = {
    "en": "TrialBox backup private key, paper copy. It opens every backup of this box: keep it sealed with hospital "
    "IT. Each line ends with four check letters, so that a typed copy can be checked line by line.",
    "ja": "TrialBox バックアップ秘密鍵（紙の控え）。このボックスのすべてのバックアップを開ける鍵です。"
    "病院の情報システム担当が封をして保管してください。各行の最後の 4 文字は確認用で、"
    "入力した写しを行ごとに確かめるためのものです。",
    "zh-TW": "TrialBox 備份私密金鑰（紙本）。它能開啟此主機的所有備份：請由醫院資訊人員密封保管。每行最後四個字母為"
    "檢查碼，可逐行核對輸入的副本。",
}


def lang_of(lang: str | None) -> str:
    raw = (lang or "").strip()
    if raw in LANGS:
        return raw
    low = raw.lower()
    return "ja" if low.startswith("ja") else "zh-TW" if low.startswith("zh") else "en"


def all_texts() -> list[tuple[str, str, str]]:
    """Every text of this module as ``(name, language, text)`` (the test checks each in en, ja and zh-TW)."""
    named = {k: v for k, v in globals().items() if k.isupper() and isinstance(v, dict) and set(v) == set(LANGS)}
    return [(name, lg, str(t[lg])) for name, t in sorted(named.items()) for lg in LANGS]


class CeremonyError(RuntimeError):
    """A refusal: ``text`` is one of this module's three-language texts, ``args`` fill it (never a key). ``more``
    holds what a failed ceremony undid (:class:`_Undo`), said after it on the same line."""

    def __init__(self, text: Mapping[str, str], **fill: Any) -> None:
        super().__init__(text["en"].format(**fill))
        self.text, self.fill = text, fill
        self.more: list[tuple[Mapping[str, str], dict[str, Any]]] = []

    def say(self, lang: str) -> str:
        lg = lang_of(lang)
        first = self.text[lg].format(**self.fill)
        if not self.more:
            return first
        return first + (". " if lg == "en" else "。") + " ".join(t[lg].format(**f) for t, f in self.more)


class PaperError(CeremonyError):
    pass


class CeremonyKept(CeremonyError):
    """Not a refusal: the key is in place and the audit's line is on disk, but the append failed after it (the head
    anchor); said as :data:`KEPT_WARNING`, exit :data:`KEPT_EXIT`, never the closing text."""


# ------------------------------------------------------------------------------------------------ the paper form
_B32 = re.compile(r"^[A-Z2-7]+$")
_LINE = re.compile(r"^\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([A-Za-z0-9]{" + str(CHECK_CHARS) + r"})\s*$")
_FP = re.compile(r"^\s*fingerprint\s+([0-9a-f]{4}(?:-[0-9a-f]{4}){4})\s*$", re.IGNORECASE)


def _check(n: int, letters: str) -> str:
    digest = hashlib.sha256(f"{FORMAT}|{n}|{letters}".encode()).digest()
    return base64.b32encode(digest[:5]).decode()[:CHECK_CHARS]


def _letters(raw: bytes) -> str:
    return base64.b32encode(raw).decode().rstrip("=")


def paper_lines(raw: bytes) -> list[str]:
    """The key's lines as the sheet prints them: ``n | ABCD EFGH IJKL MNOP | CHCK``."""
    text = _letters(raw)
    out = []
    for n, i in enumerate(range(0, len(text), LINE_CHARS), start=1):
        part = text[i : i + LINE_CHARS]
        groups = " ".join(part[j : j + 4] for j in range(0, len(part), 4))
        out.append(f"{n} | {groups} | {_check(n, part)}")
    return out


def paper_sheet(raw: bytes, fp: str, site: str, at: str) -> str:
    """The sheet to print: the head in three languages, the site, the date, the fingerprint and the lines."""
    head = [f"TRIALBOX BACKUP KEY PAPER {FORMAT}", "", *(SHEET_HEAD[lg] for lg in LANGS), ""]
    meta = [f"site {site or '-'}", f"made {at}", f"fingerprint {fp}", f"lines {len(paper_lines(raw))}", ""]
    return "\n".join([*head, *meta, *paper_lines(raw), "", "end", ""])


def read_paper(text: str) -> bytes:
    """The private key from a sheet (printed or typed back), or :class:`PaperError` naming the line; each line's
    check letters, the order, the count and the fingerprint are checked. The error never holds a letter of the key."""
    fp, rows = "", []
    for ln in text.splitlines():
        if m := _FP.match(ln):
            fp = m.group(1).lower()
        elif m := _LINE.match(ln):
            rows.append((int(m.group(1)), m.group(2), m.group(3).upper()))
    if not rows:
        raise PaperError(PAPER_SHAPE, n=1)
    letters = ""
    for want, (n, groups, check) in enumerate(rows, start=1):
        part = "".join(groups.split()).upper()
        if n != want or len(part) > LINE_CHARS:
            raise PaperError(PAPER_SHAPE, n=want)
        if not _B32.match(part) or _check(n, part) != check:
            raise PaperError(PAPER_CHECK, n=n)
        letters += part
    padded = letters + "=" * (-len(letters) % 8)
    try:
        raw = base64.b32decode(padded)
    except ValueError as e:
        raise PaperError(PAPER_SHAPE, n=len(rows)) from e
    if len(raw) != 32:  # a line left out at the end, or one too many
        raise PaperError(PAPER_SHAPE, n=len(rows))
    if not fp or _fingerprint_of(raw) != fp:
        raise PaperError(PAPER_FP)
    return raw


def _fingerprint_of(raw: bytes) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    from tools.trialbox import backup as bk

    pub = X25519PrivateKey.from_private_bytes(raw).public_key()
    return bk.fingerprint(pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


# ------------------------------------------------------------------------------------------------ the checks
def is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def person(name: str | None) -> str:
    """A person's name as the audit keeps it: one printable line, at most :data:`NAME_MAX` characters."""
    n = (name or "").strip()
    if not n:
        raise CeremonyError(NO_NAMES)
    if len(n) > NAME_MAX or n.splitlines() != [n] or any(unicodedata.category(c).startswith("C") for c in n):
        raise CeremonyError(BAD_NAME)
    return n


def folded(name: str) -> str:
    """A name as two spellings of one person compare: NFKC (full-width letters, the ideographic space), every run of
    white space one space, case folded."""
    once = " ".join(unicodedata.normalize("NFKC", name).split())
    return " ".join(unicodedata.normalize("NFKC", once.casefold()).split())


def _private(st: os.stat_result) -> bool:
    """Whether a file on the stick is the key's alone: no bit for the group or others, owned by this user (root)."""
    return stat.S_IMODE(st.st_mode) & 0o077 == 0 and st.st_uid == os.geteuid()


def writable(folder: Path, dir_fd: int | None = None) -> bool:
    """Whether a file can be made, written and synced in ``folder`` (with ``dir_fd``: the folder held open, no path
    resolved); the probe is removed again. A probe the filesystem shows readable by others (:func:`_private`: a FAT
    stick mounted with a wide mask) is :data:`STICK_NOT_PRIVATE`."""
    name = f".tb-probe-{secrets.token_hex(4)}"
    where: str | Path = name if dir_fd is not None else folder / name
    try:
        fd = os.open(where, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
    except OSError:
        return False
    try:
        try:
            private = _private(os.fstat(fd))
            if private:
                os.write(fd, b"\0" * 4096)
                os.fsync(fd)
        finally:
            os.close(fd)
        os.unlink(where, dir_fd=dir_fd)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(where, dir_fd=dir_fd)
        return False
    if not private:
        raise CeremonyError(STICK_NOT_PRIVATE, path=folder)
    return True


def _detail(rec: Mapping[str, Any]) -> dict[str, Any]:
    det = rec.get("detail")
    return det if isinstance(det, dict) else {}


def _ceremonies(audit_dir: Path, events: tuple[str, ...] = (EVENT,)) -> Iterator[dict[str, Any]]:
    """Every event named in ``events`` (``backup.key_ceremony`` alone by default) of the audit chain, newest first,
    read as the chain's own readers read it (``tb_common.audit``: the day files newest first, each from its end).
    Every line must be one JSON object: a damaged, empty or cut-off line, the last one included, is
    :data:`AUDIT_UNREADABLE`, as ``verify`` fails it (the library tolerates a torn last line only by repairing it at
    its next write, never on reading)."""
    from tb_common.audit import _day_files, lines_backward

    for path in reversed(_day_files(audit_dir)):
        try:
            for line in lines_backward(path):
                try:
                    rec = json.loads(line.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    rec = None
                if not isinstance(rec, dict):
                    raise CeremonyError(AUDIT_UNREADABLE, path=path, audit=audit_dir)
                if rec.get("event") in events:
                    yield rec
        except OSError:
            raise CeremonyError(AUDIT_UNREADABLE, path=path, audit=audit_dir) from None


def earlier_ceremony(audit_dir: Path, site: str) -> dict[str, Any] | None:
    """The newest ``backup.key_ceremony`` event of this site in the audit chain that no later
    ``backup.key_ceremony_undone`` of this command undoes (same fingerprint), or None (:func:`_ceremonies`; an audit
    that cannot be read whole is refused). An event or a run with no site counts as this site's (one box, one audit
    folder)."""
    undone: set[str] = set()
    for rec in _ceremonies(audit_dir, (EVENT, UNDONE_EVENT)):
        det = _detail(rec)
        theirs = str(det.get("site") or "")
        if site and theirs and theirs != site:
            continue
        fp = str(det.get("fingerprint") or "")
        if rec.get("event") == UNDONE_EVENT:
            if rec.get("actor") == ACTOR and fp:
                undone.add(fp)  # newest first: an undoing is met before the ceremony it undoes
            continue
        if fp and fp in undone:
            continue
        return rec
    return None


@dataclass
class _Stick:
    """The stick's folder as it was checked: held open (``fd``) from before the removable-media check, so every file
    is made in that folder (``dir_fd``) and no path is resolved again after the check; ``dev`` its device."""

    path: Path
    fd: int
    dev: int


def check(
    stick: Path, operator: str | None, witness: str | None, pub: Path, sec: Path, audit_dir: Path | None, site: str = ""
) -> tuple[str, str, _Stick]:
    """Every refusal before anything is written, in the order a person meets them; returns the two names and the
    stick's folder held open (:class:`_Stick`; the caller closes it). The removable-media check is made on the
    folder held open (``/proc/self/fd/<fd>`` leads to that folder, whatever is mounted at the path since)."""
    from tools import key_escrow as ke

    if not is_root():
        raise CeremonyError(NOT_ROOT)
    who, wit = person(operator), person(witness)
    if folded(who) == folded(wit):
        raise CeremonyError(SAME_PERSON)
    if audit_dir is None or not audit_dir.is_dir():
        raise CeremonyError(NO_AUDIT)
    if os.path.lexists(pub):
        fp = _pub_fingerprint(pub)
        err = CeremonyError(ALREADY, fp=fp)
        with contextlib.suppress(CeremonyError):  # an audit that cannot be read says nothing either way
            if not any(_detail(r).get("fingerprint") == fp for r in _ceremonies(audit_dir)):
                err.more.append((NO_CEREMONY_FOR_KEY, {}))
        raise err
    if (prev := earlier_ceremony(audit_dir, site)) is not None:
        det = _detail(prev)
        err = CeremonyError(AUDITED_ALREADY, at=str(prev.get("ts") or "-"), fp=str(det.get("fingerprint") or "-"))
        err.more.append((AUDITED_NO_KEY, {}))  # here backup.pub is not there: how to go on (D-1379)
        raise err
    if not sec.is_dir():
        raise CeremonyError(NO_SECRETS, path=sec)
    try:
        fd = os.open(stick, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        raise CeremonyError(NO_STICK, path=stick) from None
    try:
        if ke.media_problem(Path(f"/proc/self/fd/{fd}"), sec) is not None:
            raise CeremonyError(NOT_A_STICK, path=stick)
        dev = os.fstat(fd).st_dev  # the device the media check saw: the same open folder
        for name in (KEY_FILE, PAPER_FILE):
            try:
                os.stat(name, dir_fd=fd, follow_symlinks=False)  # a link, a dangling one too, is a file of that name
            except FileNotFoundError:
                continue
            except OSError:
                raise CeremonyError(NOT_WRITABLE, path=stick) from None
            raise CeremonyError(STICK_HAS_KEY, name=name)
        if not writable(stick, fd):
            raise CeremonyError(NOT_WRITABLE, path=stick)
    except BaseException:
        os.close(fd)
        raise
    return who, wit, _Stick(stick, fd, dev)


def _pub_fingerprint(pub: Path) -> str:
    from tools.trialbox import backup as bk

    try:
        return bk.fingerprint(bk.load_public(pub).public_bytes_raw())
    except (OSError, ValueError):
        return "unreadable"


# ------------------------------------------------------------------------------------------------ the ceremony
@dataclass
class _Made:
    """A file the ceremony made, as ``fstat`` gave it when it was made (``size`` once it is written in full).
    ``secret``: a form of the private key on the stick. ``dir_fd``: the stick's folder held open (:class:`_Stick`),
    where the file was made and is removed again; None for a file on the box (its folder is opened by path)."""

    path: Path
    dev: int
    ino: int
    secret: bool
    size: int | None = None
    dir_fd: int | None = None


_DEVICE_GONE = (errno.EIO, errno.ENODEV, errno.ENXIO)  # the stick held open was pulled


def _remove_made(m: _Made) -> str:
    """Remove ``m`` only if it is still the file made: its folder on ``m``'s device, the name the same device and
    inode (and size, once written). ``removed``, ``gone`` (not there, the stick pulled, or another device mounted at
    the folder), ``other`` (another file at the name: left as it is) or ``failed``."""
    if m.dir_fd is not None:
        dfd = m.dir_fd
    else:
        try:
            dfd = os.open(m.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        except OSError:
            return "gone"
    try:
        if os.fstat(dfd).st_dev != m.dev:
            return "gone"  # the stick was pulled: the folder is the box's disk, or another stick is mounted there
        try:
            st = os.stat(m.path.name, dir_fd=dfd, follow_symlinks=False)
        except FileNotFoundError:
            return "gone"
        except OSError as e:
            return "gone" if e.errno in _DEVICE_GONE else "failed"
        if (st.st_dev, st.st_ino) != (m.dev, m.ino) or (m.size is not None and st.st_size != m.size):
            return "other"
        try:
            os.unlink(m.path.name, dir_fd=dfd)
        except FileNotFoundError:
            return "gone"
        except OSError:
            return "failed"
        return "removed"
    finally:
        if m.dir_fd is None:
            os.close(dfd)


def _sync_strict(folder: Path, dir_fd: int | None) -> bool:
    """Whether ``folder`` (or the folder held open as ``dir_fd``) syncs: every failure counts, a filesystem that does
    not sync a folder included, since the removal of a key is then not known to be on the medium."""
    try:
        if dir_fd is not None:
            os.fsync(dir_fd)
            return True
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return True
    except OSError:
        return False


class _Undo:
    """What the ceremony has made so far, in order; :meth:`run` removes it again, newest first."""

    def __init__(self) -> None:
        self.files: list[_Made] = []
        self.dirs: list[Path] = []

    def forget(self, path: Path) -> None:
        self.files = [m for m in self.files if m.path != path]

    def run(self) -> list[tuple[Mapping[str, str], dict[str, Any]]]:
        """Remove every file and folder made, each only if it is still the one made (:func:`_remove_made`), then
        sync each folder something was removed from (:func:`_sync_strict`); what to say about it. A removal whose
        folder does not sync is said as not confirmed on disk, naming the files and the folder. A key file not
        found, or another file at its name, is left and said (the stick that was pulled may hold the key). "Nothing
        of the key is kept" is said only when every file made was removed and every such folder synced. A
        public-key file not found or not ours is not the key and is passed over."""
        removed: list[tuple[Path, Path, int | None]] = []  # (what, its folder, the folder held open)
        left: list[Path] = []
        gone: list[Path] = []
        other: list[Path] = []
        for m in reversed(self.files):
            what = _remove_made(m)
            if what == "removed":
                removed.append((m.path, m.path.parent, m.dir_fd))
            elif what == "failed":
                left.append(m.path)
            elif m.secret:
                (gone if what == "gone" else other).append(m.path)
        for d in reversed(self.dirs):
            try:
                d.rmdir()
                removed.append((d, d.parent, None))
            except FileNotFoundError:
                pass
            except OSError as e:
                if e.errno not in (errno.ENOTEMPTY, errno.EEXIST):  # a folder holding a file not ours stays
                    left.append(d)
        gone_dirs = {p for p, _, _ in removed if p in self.dirs}

        def synced_in(folder: Path) -> Path:  # a folder removed too: its parent's sync holds its removal
            while folder in gone_dirs:
                folder = folder.parent
            return folder

        synced: dict[Path, bool] = {}
        for _, folder, dfd in removed:
            where = synced_in(folder)
            if where not in synced:
                synced[where] = _sync_strict(where, dfd if where == folder else None)
        durable = [p for p, folder, _ in removed if synced[synced_in(folder)]]
        if not removed and not left and not gone and not other:
            return [(KEPT_NOTHING, {})]
        said: list[tuple[Mapping[str, str], dict[str, Any]]] = []
        if durable:
            some = left or gone or other or len(durable) < len(removed)
            said.append((REMOVED_SOME if some else REMOVED_ALL, {"files": ", ".join(str(p) for p in durable)}))
        for where, ok in synced.items():
            if not ok:
                files = ", ".join(str(p) for p, f, _ in removed if synced_in(f) == where)
                said.append((REMOVED_NOT_DURABLE, {"files": files, "folder": where}))
        for text, paths in ((LEFT, left), (LEFT_GONE, gone), (LEFT_OTHER, other)):
            if paths:
                said.append((text, {"files": ", ".join(str(p) for p in paths)}))
        return said


def _write_new(path: Path, data: bytes, undo: _Undo, stick: _Stick | None, mode: int = 0o600) -> _Made:
    """``data`` to ``path`` (``mode``), created here or not at all (never through a link), written in full and synced.
    The file is in ``undo`` from the moment it exists, with its device and inode, so a failed write or sync removes
    it again (and only it). With ``stick`` (a form of the key): the file is made in the stick's folder held open
    (``dir_fd``, no path resolved), and before a byte is written it is refused when it is not on the device checked
    (:data:`STICK_MOVED`) or the filesystem shows it readable by others (:data:`STICK_NOT_PRIVATE`)."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if stick is not None:
        fd = os.open(path.name, flags, mode, dir_fd=stick.fd)
    else:
        fd = os.open(path, flags, mode)
    try:
        st = os.fstat(fd)
        made = _Made(path, st.st_dev, st.st_ino, secret=stick is not None, dir_fd=stick.fd if stick else None)
        undo.files.append(made)
        if stick is not None and st.st_dev != stick.dev:
            raise CeremonyError(STICK_MOVED, name=path.name, path=path.parent)
        if stick is not None and not _private(st):
            raise CeremonyError(STICK_NOT_PRIVATE, path=path.parent)
        view = memoryview(data)
        while view:
            n = os.write(fd, view)
            if n <= 0:
                raise OSError(errno.EIO, f"{path}: nothing written")
            view = view[n:]
        os.fsync(fd)
        made.size = os.fstat(fd).st_size
    finally:
        os.close(fd)
    return made


def _sync_fd(fd: int) -> None:
    """Sync the folder held open as ``fd``, so the names of the files made in it are on the medium too."""
    try:
        os.fsync(fd)
    except OSError as e:
        if e.errno not in (errno.EINVAL, errno.ENOTSUP):  # a filesystem that does not sync a folder on its own
            raise


def _sync_dir(folder: Path) -> None:
    """Sync ``folder`` itself (:func:`_sync_fd`)."""
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        _sync_fd(fd)
    finally:
        os.close(fd)


def _read_made(stick: _Stick, m: _Made) -> int:
    """The file ``m`` opened again for its read-back, in the stick's folder held open; refused (:data:`READ_BACK`)
    when the name holds another file now."""
    fd = os.open(m.path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=stick.fd)
    st = os.fstat(fd)
    if (st.st_dev, st.st_ino) != (m.dev, m.ino):
        os.close(fd)
        raise CeremonyError(READ_BACK)
    return fd


def _stage_pub(pub: Path, text: str, undo: _Undo) -> _Made:
    """The public key as a synced temporary file beside ``pub`` (its folder made if missing), not yet at its name:
    nothing reads it there (``trialbox backup`` reads ``backup.pub`` only)."""
    missing: list[Path] = []
    d = pub.parent
    while not os.path.lexists(d):
        missing.append(d)
        d = d.parent
    for d in reversed(missing):
        d.mkdir()
        undo.dirs.append(d)
    tmp = pub.parent / f".{pub.name}.{secrets.token_hex(4)}.tmp"
    return _write_new(tmp, text.encode(), undo, None, mode=0o644)


def _is_file(path: Path, m: _Made) -> bool:
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return (st.st_dev, st.st_ino) == (m.dev, m.ino)


def _audit_files(audit_dir: Path) -> dict[str, tuple[int, int, int, int]]:
    """Every regular file of the audit folder: its inode, owner, group and mode."""
    out: dict[str, tuple[int, int, int, int]] = {}
    for p in audit_dir.rglob("*"):
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            out[str(p.relative_to(audit_dir))] = (st.st_ino, st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode))
    return out


def _give_back(audit_dir: Path, before: Mapping[str, tuple[int, int, int, int]]) -> list[Path]:
    """D-724, as ``trialbox backup`` and ``restore`` do it: what this run wrote as root in the audit folder is given
    back, so the audit writer (another user) can append after it. A file that was there with another owner and is
    root's now (the head anchor, replaced) gets its owner, group and mode again; a file that is new (the lock, a new
    day file, a torn line's evidence) gets the folder's owner and group and the mode of the newest day file that was
    there. Files root had before are left as they are. Returns every file still root's after this (checked)."""
    try:
        top = os.stat(audit_dir)
    except OSError:
        return []
    me = os.geteuid()
    if top.st_uid == me:
        return []
    days = sorted(k for k in before if k.endswith(".jsonl") and "/" not in k)
    like = before[days[-1]][3] if days else None
    left: list[Path] = []
    for rel, (_ino, uid, _gid, mode) in sorted(_audit_files(audit_dir).items()):
        if uid != me:
            continue
        was = before.get(rel)
        if was is not None and was[1] == me:
            continue  # root's before this run: not this run's to give
        want = (was[1], was[2], was[3]) if was is not None else (top.st_uid, top.st_gid, like if like else mode)
        p = audit_dir / rel
        with contextlib.suppress(OSError):
            os.chown(p, want[0], want[1], follow_symlinks=False)
            os.chmod(p, want[2])
        try:
            st = os.lstat(p)
            ok = (st.st_uid, st.st_gid) == (want[0], want[1])
        except FileNotFoundError:
            ok = True
        except OSError:
            ok = False
        if not ok:
            left.append(p)
    return left


def _cause(e: BaseException, step: str, stick: Path, pub: Path, audit_dir: Path) -> CeremonyError:
    """The refusal a failure at ``step`` is said as."""
    from tools.trialbox import backup as bk

    if isinstance(e, PaperError):
        return CeremonyError(READ_BACK)
    if isinstance(e, CeremonyError):
        return e
    if isinstance(e, KeyboardInterrupt):
        return CeremonyError(INTERRUPTED)
    if step == "stick" and isinstance(e, OSError):
        return CeremonyError(NOT_WRITABLE, path=stick)
    if step == "stick" and isinstance(e, ValueError | bk.BackupError):
        return CeremonyError(READ_BACK)
    if step == "public" and isinstance(e, OSError):
        return CeremonyError(PUB_FAILED, path=pub)
    if step == "audit" and isinstance(e, OSError):
        return CeremonyError(AUDIT_FAILED, path=audit_dir)
    return CeremonyError(UNEXPECTED, kind=type(e).__name__)


#: In ``tb_common.audit.AuditLog._write``, the calls made only after the day file's ``os.fsync`` returned (the test
#: ``test_the_audit_writer_syncs_the_line_before_these_calls`` holds the library to it).
AFTER_LINE_SYNC = ("write_head", "_day_files")


def _line_synced(e: BaseException, fp: str) -> bool:
    """Whether ``e`` was raised inside a call that ``AuditLog._write`` makes only after its ``os.fsync`` of the day
    file returned, in the ``_write`` of this ceremony's own event (its ``body``: this event, this fingerprint), read
    from the traceback. A failure in the write, the flush, the fsync or the close of the day file, or in an earlier
    event's ``_write`` (``audit.anchored``, ``audit.repaired``), is not."""
    tb = e.__traceback__
    while tb is not None:
        frame, nxt = tb.tb_frame, tb.tb_next
        if frame.f_code.co_name == "_write" and frame.f_globals.get("__name__") == "tb_common.audit" and nxt:
            body = frame.f_locals.get("body")
            ours = isinstance(body, dict) and body.get("event") == EVENT and _detail(body).get("fingerprint") == fp
            callee = nxt.tb_frame
            same_module = callee.f_globals.get("__name__") == "tb_common.audit"
            if ours and same_module and callee.f_code.co_name in AFTER_LINE_SYNC:
                return True
        tb = nxt
    return False


def _audit_state(e: BaseException, audit_dir: Path, fp: str) -> str:
    """After a failed append: ``recorded`` when the event's line is on disk (:func:`_line_synced`, and the audit
    folder, which holds the day file's name, syncs now); ``absent`` when the chain, read whole, has no event of this
    fingerprint; else ``unknown`` (the line may be in the file but is not known to be on disk)."""
    try:
        if _line_synced(e, fp):
            _sync_dir(audit_dir)
            return "recorded"
        if any(_detail(r).get("fingerprint") == fp for r in _ceremonies(audit_dir)):
            return "unknown"
        return "absent"
    except BaseException:  # whatever stops this check, nothing is known: undo and say "may"
        return "unknown"


def run(
    stick: Path,
    operator: str | None,
    witness: str | None,
    *,
    pub: Path,
    sec: Path,
    audit_dir: Path | None,
    site: str = "",
    now: datetime | None = None,
    tz: str | None = None,
) -> dict[str, Any]:
    """The ceremony; returns what the audit holds (no key) and ``warnings`` (texts said after the closing text, exit
    :data:`KEPT_EXIT`). :class:`CeremonyError` on a refusal; after the first file is made, every failure (an
    interruption too) undoes what was made and the refusal says what was removed, except once ``backup.pub`` may
    have been visible (:class:`CeremonyKept`: nothing of the key is removed then)."""
    who, wit, held = check(stick, operator, witness, pub, sec, audit_dir, site)
    try:
        if audit_dir is None:  # check() refused already; said again for the type checker
            raise CeremonyError(NO_AUDIT)
        return _ceremony(held, who, wit, pub=pub, audit_dir=audit_dir, site=site, now=now, tz=tz)
    finally:
        os.close(held.fd)


def _ceremony(
    held: _Stick, who: str, wit: str, *, pub: Path, audit_dir: Path, site: str, now: datetime | None, tz: str | None
) -> dict[str, Any]:
    """The writes, in this order (D-1379): the key file and the paper sheet in the stick's folder held open, the
    folder synced, both read back; the public key as a synced temporary file beside ``backup.pub``; the audit event,
    its line synced; and only then ``backup.pub`` linked to its name, so a ``trialbox backup`` can find the public
    key only once the event that names it is on disk."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from tb_common.audit import AuditLog

    from tools.trialbox import backup as bk

    stick = held.path
    key_file, paper_file = stick / KEY_FILE, stick / PAPER_FILE
    undo, step, fp, link = _Undo(), "start", "", "no"
    detail: dict[str, Any] = {}
    audit_state = "absent"
    anchor_unconfirmed = False
    owners_left: list[Path] = []
    staged: _Made | None = None
    try:
        log = AuditLog(audit_dir, tz=tz) if tz else AuditLog(audit_dir)  # the site's zone, as `restore` writes it
        at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
        sk = X25519PrivateKey.generate()
        raw = sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                               serialization.NoEncryption())  # fmt: skip
        pk = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        fp = bk.fingerprint(pk)
        letters = _letters(raw)
        machine = " ".join(letters[i : i + 4] for i in range(0, len(letters), 4))
        head, tail = f"-----BEGIN {bk.KEY_HEADER}-----", f"-----END {bk.KEY_HEADER}-----"
        step = "stick"
        made_key = _write_new(key_file, f"{head}\n{machine}\nfingerprint {fp}\n{tail}\n".encode(), undo, held)
        made_paper = _write_new(paper_file, paper_sheet(raw, fp, site, at).encode(), undo, held)
        _sync_fd(held.fd)
        rfd = _read_made(held, made_key)
        try:
            back_key = bk.load_private(Path(f"/proc/self/fd/{rfd}")).public_key().public_bytes_raw()
        finally:
            os.close(rfd)
        rfd = _read_made(held, made_paper)
        try:
            with os.fdopen(os.dup(rfd), "r", encoding="utf-8") as fh:
                sheet = fh.read()
        finally:
            os.close(rfd)
        back_paper = _fingerprint_of(read_paper(sheet))
        if back_key != pk or back_paper != fp:
            raise CeremonyError(READ_BACK)
        del sk, raw, letters, machine, sheet
        step = "public"
        staged = _stage_pub(pub, base64.b64encode(pk).decode() + "\n", undo)
        if os.path.lexists(pub):  # a key put there meanwhile: refused before the audit, never overwritten
            raise FileExistsError(errno.EEXIST, "File exists", str(pub))
        step = "audit"
        detail = {"at": at, "site": site, "fingerprint": fp, "operator": who, "witness": wit,
                  "forms": ["stick", "paper"], "paper_format": FORMAT}  # fmt: skip
        before = _audit_files(audit_dir)
        try:
            log.append(EVENT, actor=ACTOR, input_sha="", detail=detail)
        except BaseException as e:
            audit_state = _audit_state(e, audit_dir, fp)
            if audit_state != "recorded":
                raise
            anchor_unconfirmed = True  # the line is on disk: go on, and say it (KEPT_WARNING)
        finally:
            owners_left = _give_back(audit_dir, before)
        step, link = "link", "trying"
        os.link(staged.path, pub)  # no overwrite: FileExistsError when a file of that name appeared meanwhile
        link = "done"
        os.unlink(staged.path)
        undo.forget(staged.path)
        _sync_dir(pub.parent)
    except BaseException as e:  # one failure domain: nothing of a failed ceremony is kept (D-1379)
        if step == "link":
            visible = link == "done" or (link == "trying" and not isinstance(e, OSError))
            visible = visible or (staged is not None and _is_file(pub, staged))
            if visible:  # a backup may have read backup.pub: the private copies are never removed after this
                if staged is not None:  # the temporary name only: backup.pub is another link to it
                    with contextlib.suppress(OSError):
                        if _is_file(staged.path, staged):
                            os.unlink(staged.path)
                kept = CeremonyKept(PUB_KEPT_WARNING, fp=fp, key=key_file.name, paper=paper_file.name, pub=pub,
                                    event=EVENT, audit=audit_dir)  # fmt: skip
                kept.more = _owner_said(owners_left, audit_dir)
                raise kept from None
            err = _cause(e, "public", stick, pub, audit_dir)
            undone, owners_more = _write_undone(log, audit_dir, detail, e)
            err.more = undo.run() + _owner_said(owners_left + owners_more, audit_dir)
            if not undone:
                err.more.append((AUDIT_HOLDS, {"fp": fp}))
            raise err from None
        err = _cause(e, step, stick, pub, audit_dir)
        err.more = undo.run() + _owner_said(owners_left, audit_dir)
        if step == "audit" and audit_state == "unknown":
            err.more.append((AUDIT_MAY_HOLD, {"fp": fp}))
        raise err from None
    warnings = _owner_said(owners_left, audit_dir)
    if anchor_unconfirmed:  # the chain holds the event on disk, its head anchor unconfirmed: no closing text
        kept = CeremonyKept(KEPT_WARNING, fp=fp, key=key_file.name, paper=paper_file.name, pub=pub, event=EVENT,
                            audit=audit_dir)  # fmt: skip
        kept.more = warnings
        raise kept
    return {**detail, "key_file": key_file.name, "paper_file": paper_file.name, "public": str(pub),
            "warnings": warnings}  # fmt: skip


def _owner_said(left: Sequence[Path], audit_dir: Path) -> list[tuple[Mapping[str, str], dict[str, Any]]]:
    """:data:`AUDIT_OWNER_LEFT` for the audit files still root's, naming the folder's owner; nothing when none."""
    if not left:
        return []
    try:
        top = os.stat(audit_dir)
        owner = f"{top.st_uid}:{top.st_gid}"
    except OSError:
        owner = "-"
    return [(AUDIT_OWNER_LEFT, {"files": ", ".join(str(p) for p in dict.fromkeys(left)), "owner": owner})]


def _write_undone(log: Any, audit_dir: Path, detail: Mapping[str, Any], e: BaseException) -> tuple[bool, list[Path]]:
    """``backup.key_ceremony_undone`` after the ceremony's event: ``backup.pub`` was never put in place, so no backup
    was made to the key and its copies can be removed; the once-only check counts the pair as not done. Whether it
    was written (its line synced), and the audit files still root's after it."""
    before = _audit_files(audit_dir)
    try:
        named = {k: detail[k] for k in ("at", "site", "fingerprint", "operator", "witness") if k in detail}
        log.append(UNDONE_EVENT, actor=ACTOR, input_sha="", detail={**named, "why": type(e).__name__})
        ok = True
    except BaseException:  # whatever stopped it, the undoing is not known to be written
        ok = False
    finally:
        left = _give_back(audit_dir, before)
    return ok, left


def _refuse(err: CeremonyError, lang: str, *, nothing: bool = False) -> int:
    if nothing:
        err.more = [(KEPT_NOTHING, {})]
    print(err.say(lang), file=sys.stderr)
    return 1


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(prog="python -m tools.backup_key_ceremony", description=__doc__.split("\n")[0])
    ap.add_argument("--stick", required=True, help="the mounted folder of the removable stick")
    ap.add_argument("--operator", help="the person who runs the ceremony (hospital IT)")
    ap.add_argument("--witness", help="the witness: another person")
    ap.add_argument("--deploy", default=str(DEFAULT_DEPLOY), help="the box's deploy folder")
    ap.add_argument("--public", help="where the box keeps the public key (TB_BACKUP_PUBKEY; deploy/secrets/backup.pub)")
    ap.add_argument("--secrets", help="the secrets folder (TB_SECRETS_DIR): the stick may not be on its disk")
    ap.add_argument("--audit-dir", help="the audit folder (TB_AUDIT_DIR)")
    ap.add_argument("--lang", help="en (the default), ja or zh-TW")
    a = ap.parse_args(argv)
    lang = lang_of(a.lang)
    try:
        from tools import key_ceremony as kc
        from tools.keys import secrets_dir

        deploy = Path(a.deploy)
        pub = Path(a.public) if a.public else kc.default_backup_pub(env, deploy)
        audit = Path(a.audit_dir) if a.audit_dir else Path(env["TB_AUDIT_DIR"]) if env.get("TB_AUDIT_DIR") else None
        rec = run(Path(a.stick), a.operator, a.witness, pub=pub, sec=secrets_dir(a.secrets, env), audit_dir=audit,
                  site=env.get("TB_SITE_ID") or "", tz=env.get("TB_TZ") or None)  # fmt: skip
    except CeremonyKept as e:
        print(e.say(lang), file=sys.stderr)
        return KEPT_EXIT
    except CeremonyError as e:
        return _refuse(e, lang)
    # what is left is a failure before the first file is made: run() says every later one as a CeremonyError itself
    except KeyboardInterrupt:
        return _refuse(CeremonyError(INTERRUPTED), lang, nothing=True)
    except Exception as e:
        return _refuse(CeremonyError(UNEXPECTED, kind=type(e).__name__), lang, nothing=True)
    print(DONE[lang].format(fp=rec["fingerprint"], key=rec["key_file"], paper=rec["paper_file"], pub=rec["public"],
                            event=EVENT, operator=rec["operator"], witness=rec["witness"]))  # fmt: skip
    if rec["warnings"]:  # done, but the audit writer cannot append after it until a person gives its files back
        lg = lang_of(lang)
        print(" ".join(t[lg].format(**f) for t, f in rec["warnings"]), file=sys.stderr)
        return KEPT_EXIT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
