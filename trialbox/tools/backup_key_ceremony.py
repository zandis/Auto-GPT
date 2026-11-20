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
backup can be made to the key before the event that names it is on disk. Root never writes in the audit folder
(D-1379): one audit helper process is forked in the checks, before the stick is opened and before any key material
exists in this process, and drops to the owner of the audit folder (every descriptor closed but the folder held open,
``O_NOFOLLOW``, and its two pipe ends; no core, not dumpable; ``setgroups([])``, ``setgid``, ``setuid``, checked); it
works in that folder and stays alive for the whole run, doing the once-only read and each append (the event, and its
undoing) on request over a pipe pair, answering with one word of a fixed list (the requests hold only the event's
public fields; nothing of the key crosses). This process writes no core once the key exists, and forks nothing after
it. The files in the folder are made by their owner; afterwards the folder is checked, read only, to hold no file of
root's. A box whose audit folder is root's (and not writable by its group or others) is appended to in this process,
through the folder held open (``fchdir``, relative paths), only after every entry of it was seen, through that same
descriptor, to be a plain file with one name. The ceremony is one failure domain until the
link: a failure at any step after the first file is made removes every file it made, each only when it is still the
file made (same device, inode and size), syncs each folder it removed from, and says which were removed, which are
left, and which removals are not confirmed on disk. When the event is on disk but ``backup.pub`` could not be linked,
``backup.key_ceremony_undone`` is written before the undo, and the once-only check counts that pair as not done; so too
when an interruption before the link ran stops the run (the event's line counts as on disk from the moment the append
ended with its line synced). Whether ``backup.pub`` was visible is decided by looking at it (its
inode against the staged file's), never by where the code stopped. Once ``backup.pub`` is ours or may have been
visible, nothing of the key is removed: a warning, exit 2. Also exit 2: the event's line
synced but its head anchor not confirmed; a file of root's in the audit folder after it; a second interruption while
the run was stopping (only what is known is said, never that nothing was written once a file was made). What is not
covered (D-1379): a power loss or a
kill after the event's line is on disk and before ``backup.pub`` is linked (the audit then refuses a rerun and says
how to go on), and a stick pulled before the undo (the refusal names its files as left).

Refused, before anything is written: not root; the operator or the witness not named, or the same person (compared
after NFKC, with spaces collapsed and case folded); no audit folder; a box that has a backup key already, or whose
audit holds a ceremony already (a ceremony is run once; a new pair is the key's rotation, RUNBOOK §25, not this
command); an audit folder that is a link, or root's and writable by its group or others, or root's and holding an
entry that is not a plain file with one name; no secrets folder to check the stick against; no stick at the folder
named; a folder on the box's disks or
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
import signal
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
    "was run already cannot be told: run python tools/audit_verify.py {audit} and have a person look. A last line cut "
    "off because the audit writer was killed is repaired by that writer's next append; until then this refusal stands",
    "ja": "拒否：監査記録のファイル {path} を最後まで読めません（壊れた行か途中で切れた行があります）。手続きがすでに"
    "行われたかを判断できません。python tools/audit_verify.py {audit} を実行し、担当者が確認してください。監査記録を"
    "書くプロセスが強制終了されて途中で切れた最後の行は、そのプロセスの次の追記で修復されます。それまではこの拒否が"
    "続きます",
    "zh-TW": "已拒絕：無法完整讀取稽核紀錄檔 {path}（有損壞或截斷的行），因此無法判斷儀式是否已執行：請執行 "
    "python tools/audit_verify.py {audit} 並由人員檢查。因寫入稽核紀錄的程序被終止而截斷的最後一行，會在該程序下次"
    "追加時修復；在此之前此拒絕會持續",
}
NO_CEREMONY_FOR_KEY = {
    "en": "The audit holds no backup-key ceremony for this key (one cut short, or a key made by backup-keygen).",
    "ja": "監査記録にはこの鍵のバックアップ鍵の手続きがありません（途中で止まった手続きか、backup-keygen で作った"
    "鍵です）。",
    "zh-TW": "稽核紀錄中沒有此金鑰的備份金鑰儀式（儀式中途中斷，或為 backup-keygen 建立的金鑰）。",
}
AUDITED_NO_KEY = {
    "en": "This box has no backup.pub. The key of that ceremony (fingerprint {fp}) may still be on its stick and "
    "paper sheet, and it is valid, but no command of this box puts its public key back at backup.pub. Keep that "
    "stick and sheet sealed: a backup made while its backup.pub was there opens only with it. Make the new pair as "
    "RUNBOOK §25 says (python -m tools.trialbox backup-keygen) and enter its fingerprint in the ceremony record.",
    "ja": "このボックスには backup.pub がありません。その手続きの鍵（指紋 {fp}）は USB メモリと紙の控えに残って"
    "いる可能性があり、鍵としては有効ですが、その公開鍵を backup.pub に戻すコマンドはこのボックスにはありません。"
    "その USB メモリと紙の控えは封をしたまま保管してください。backup.pub があった間に作られたバックアップは、"
    "その鍵でしか開けません。新しい鍵の組は RUNBOOK §25 のとおりに作り（python -m tools.trialbox backup-keygen）、"
    "その指紋を手続きの記録に記入してください。",
    "zh-TW": "此主機沒有 backup.pub。該儀式的金鑰（指紋 {fp}）可能仍在其隨身碟與紙本上，且仍有效，但此主機沒有任何"
    "指令能將其公開金鑰放回 backup.pub。請將該隨身碟與紙本保持密封：在其 backup.pub 存在期間建立的備份只能用它開啟。"
    "請依 RUNBOOK §25 建立新的金鑰組（python -m tools.trialbox backup-keygen），並將其指紋填入儀式紀錄。",
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
    "en": "refused: a file made on the stick at {path} can be read by others (its mode has a bit for the group or "
    "others, or it is not owned by root), so the key is not written: mount the stick for root only, e.g. mount -o "
    "uid=0,gid=0,umask=077 <device> {path} (a FAT or exFAT stick takes its modes from these options), or use a stick "
    "formatted with ext4",
    "ja": "拒否：{path} の USB メモリに作ったファイルをほかの人が読めます（モードにグループかほかの人の"
    "ビットがあるか、所有者が root ではありません）。鍵は書きません。"
    "USB メモリを root だけが使えるようにマウントしてください。"
    "例：mount -o uid=0,gid=0,umask=077 <device> {path}"
    "（FAT や exFAT の USB メモリのモードはこのオプションで決まります）。"
    "または ext4 でフォーマットした USB メモリを使ってください",
    "zh-TW": "已拒絕：在 {path} 隨身碟上建立的檔案可被他人讀取（其模式含群組或其他人的權限位元，或擁有者不是 "
    "root），因此不寫入金鑰：請以僅 root 可用的方式掛載隨身碟，例如 mount -o uid=0,gid=0,umask=077 <device> {path}"
    "（FAT 或 exFAT 隨身碟的模式由這些選項決定），或改用以 ext4 格式化的隨身碟",
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
    "en": "warning: these files in the audit folder are root's after the ceremony's event, though the ceremony wrote "
    "there only as the folder's owner: {files}: the audit writer cannot add its next event while they are root's: "
    "have a person look (python tools/audit_verify.py {audit}) and give them to the folder's owner ({owner}) with "
    "chown.",
    "ja": "警告：この手続きはフォルダーの所有者としてだけ書きましたが、手続きの記録のあと、監査記録のフォルダーの"
    "これらのファイルが root のものです：{files}。root のものである間、監査記録の書き込みは次の記録を追加できません。"
    "担当者が確認し（python tools/audit_verify.py {audit}）、chown でフォルダーの所有者（{owner}）に戻してください。",
    "zh-TW": "警告：此儀式只以資料夾擁有者的身分寫入，但寫入儀式紀錄後，稽核紀錄資料夾中的這些檔案屬於 root："
    "{files}：在它們屬於 root 期間，稽核紀錄寫入程式無法加入下一筆紀錄：請由人員檢查（python tools/audit_verify.py "
    "{audit}），並以 chown 將它們交還資料夾的擁有者（{owner}）。",
}
PUB_KEPT_WARNING = {
    "en": "warning: the backup key {fp} is kept: its audit event {event} is written and the stick holds {key} and "
    "{paper}, but putting the public key at {pub} did not finish, and a backup may already use it, so nothing was "
    "removed. Run python tools/audit_verify.py {audit} and have a person look. Then run python -m "
    "tools.backup_key_ceremony again with the same options: it is refused before it writes anything and names the key "
    "at {pub} by its fingerprint (or says there is none). If that is not {fp}, the key at {pub} is not this "
    "ceremony's key: keep the stick and the paper sheet sealed and follow RUNBOOK §25. Unmount (eject) the stick "
    "before you pull it out.",
    "ja": "警告：バックアップ鍵 {fp} は残しました。監査記録 {event} は書かれ、USB メモリには {key} と {paper} が"
    "ありますが、公開鍵を {pub} に置く処理が終わっていません。すでにバックアップがそれを使っている可能性があるため、"
    "何も削除していません。python tools/audit_verify.py {audit} を実行し、担当者が確認してください。次に、同じ"
    "オプションで python -m tools.backup_key_ceremony をもう一度実行してください。何も書く前に拒否され、{pub} に"
    "ある鍵をその指紋で示します（ない場合はないと示します）。それが {fp} でなければ、{pub} の鍵はこの手続きの鍵では"
    "ありません。USB メモリと紙の控えは封をしたまま保管し、RUNBOOK §25 に従ってください。USB メモリは抜く前に"
    "アンマウント（取り出し）してください。",
    "zh-TW": "警告：備份金鑰 {fp} 已保留：其稽核紀錄 {event} 已寫入，隨身碟上有 {key} 與 {paper}，但將公開金鑰放到 "
    "{pub} 的步驟未完成，且備份可能已在使用它，因此未刪除任何內容。請執行 python tools/audit_verify.py {audit} "
    "並由人員檢查。接著以相同選項再次執行 python -m tools.backup_key_ceremony：它會在寫入任何內容前被拒絕，並以"
    "指紋指出 {pub} 的金鑰（若沒有則說明沒有）。若不是 {fp}，{pub} 的金鑰就不是此儀式的金鑰：請將隨身碟與紙本"
    "保持密封，並依 RUNBOOK §25 處理。拔出隨身碟前請先卸載（退出）。",
}
PUB_LINKED_WARNING = {
    "en": "warning: the backup key {fp} is in place: its audit event {event} is written, the stick holds {key} and "
    "{paper}, and {pub} is the public key just made, but the run stopped before it finished putting it there (the "
    "folder's sync or the temporary name's removal), so the ceremony is not reported as done; nothing was removed. "
    "Run python tools/audit_verify.py {audit} and have a person look; do not run the ceremony again. Unmount (eject) "
    "the stick before you pull it out.",
    "ja": "警告：バックアップ鍵 {fp} は置かれました。監査記録 {event} は書かれ、USB メモリには {key} と {paper} が"
    "あり、{pub} は作った公開鍵ですが、置く処理の最後（フォルダーの同期か一時ファイル名の削除）の前に実行が止まった"
    "ため、手続きは完了と報告しません。何も削除していません。python tools/audit_verify.py {audit} を実行し、担当者が"
    "確認してください。この手続きを再実行しないでください。USB メモリは抜く前にアンマウント（取り出し）してください。",
    "zh-TW": "警告：備份金鑰 {fp} 已就位：其稽核紀錄 {event} 已寫入，隨身碟上有 {key} 與 {paper}，且 {pub} 是剛建立的"
    "公開金鑰，但執行在放置步驟完成前（資料夾同步或暫存名稱刪除）中止，因此儀式不回報為完成；未刪除任何內容。請執行 "
    "python tools/audit_verify.py {audit} 並由人員檢查；請勿再次執行此儀式。拔出隨身碟前請先卸載（退出）。",
}
AUDIT_NOT_LISTED = {
    "en": "warning: the audit folder {audit} could not be listed after the ceremony's event, so it was not checked "
    "that no file there is root's: the audit writer cannot append after a file of root's; give any there to the "
    "folder's owner ({owner}) with chown.",
    "ja": "警告：手続きの記録のあと、監査記録のフォルダー {audit} を一覧できなかったため、そこに root のファイルが"
    "ないことを確認できませんでした。root のファイルがあると監査記録の書き込みは次を追加できません。あれば chown で"
    "フォルダーの所有者（{owner}）に戻してください。",
    "zh-TW": "警告：寫入儀式紀錄後無法列出稽核紀錄資料夾 {audit}，因此未確認其中沒有屬於 root 的檔案：有屬於 root "
    "的檔案時，稽核紀錄寫入程式無法繼續加入紀錄；若有，請以 chown 交還資料夾的擁有者（{owner}）。",
}
AUDIT_HOLDS = {
    "en": "The audit holds this run's event (fingerprint {fp}), and the event that undoes it is not written: a new "
    "run of this command is refused, and the new pair is made as RUNBOOK §25 says.",
    "ja": "監査記録にはこの実行の記録（指紋 {fp}）があり、それを取り消す記録は書かれていません。このコマンドの"
    "再実行は拒否されるため、新しい鍵の組は RUNBOOK §25 のとおりに作ります。",
    "zh-TW": "稽核紀錄留有此次執行的紀錄（指紋 {fp}），且復原它的紀錄未寫入：再次執行此指令會被拒絕，新的金鑰組"
    "須依 RUNBOOK §25 建立。",
}
UNDONE_UNKNOWN = {
    "en": "The audit holds this run's event (fingerprint {fp}); the event that undoes it is not known to be on disk: "
    "if a new run of this command is refused, the new pair is made as RUNBOOK §25 says.",
    "ja": "監査記録にはこの実行の記録（指紋 {fp}）があります。それを取り消す記録がディスク上にあるかは確認できて"
    "いません。このコマンドの再実行が拒否された場合、新しい鍵の組は RUNBOOK §25 のとおりに作ります。",
    "zh-TW": "稽核紀錄留有此次執行的紀錄（指紋 {fp}）；復原它的紀錄是否已寫入磁碟未能確認：若再次執行此指令被拒絕，"
    "新的金鑰組須依 RUNBOOK §25 建立。",
}
UNDONE_WRITTEN = {
    "en": "The audit holds this run's event (fingerprint {fp}) and the event that undoes it: a new run of this "
    "command is allowed.",
    "ja": "監査記録にはこの実行の記録（指紋 {fp}）とそれを取り消す記録があります。このコマンドは再実行できます。",
    "zh-TW": "稽核紀錄留有此次執行的紀錄（指紋 {fp}）及復原它的紀錄：可以再次執行此指令。",
}
EVENT_WRITTEN = {
    "en": "The audit event {event} (fingerprint {fp}) is written.",
    "ja": "監査記録 {event}（指紋 {fp}）は書かれています。",
    "zh-TW": "稽核紀錄 {event}（指紋 {fp}）已寫入。",
}
EVENT_NOT_WRITTEN = {
    "en": "The audit event was not written.",
    "ja": "監査記録は書いていません。",
    "zh-TW": "稽核紀錄未寫入。",
}
INTERRUPTED_LATE = {
    "en": "refused: the ceremony was interrupted while it was finishing or undoing what it had made, so only this is "
    "known",
    "ja": "拒否：手続きが完了処理か取り消しの途中で中断されたため、わかっているのは次のことだけです",
    "zh-TW": "已拒絕：儀式在收尾或復原已建立內容的過程中被中斷，因此只能確定以下內容",
}
UNEXPECTED_LATE = {
    "en": "refused: the ceremony stopped on an unexpected error ({kind}) while it was finishing or undoing what it had "
    "made, so only this is known",
    "ja": "拒否：手続きが完了処理か取り消しの途中で予期しないエラー（{kind}）で止まったため、わかっているのは次の"
    "ことだけです",
    "zh-TW": "已拒絕：儀式在收尾或復原已建立內容的過程中因非預期的錯誤（{kind}）而中止，因此只能確定以下內容",
}
MAY_REMAIN = {
    "en": "These files may remain (the undo may have been cut short): look at each, remove it by hand if it is there, "
    "and destroy or wipe a stick that held the key: {files}.",
    "ja": "次のファイルが残っている可能性があります（取り消しが途中で止まった可能性があります）。それぞれを確認し、"
    "あれば手で削除し、鍵があった USB メモリは破棄するか消去してください：{files}。",
    "zh-TW": "以下檔案可能仍存在（復原可能中途中止）：請逐一檢查，若存在請手動刪除，並銷毀或抹除曾存放金鑰的隨身碟："
    "{files}。",
}
LATE_PUB = {
    "en": "{pub} may be the public key just made, and a backup may already use it: remove neither it nor the stick's "
    "files; run python tools/audit_verify.py {audit} and have a person look.",
    "ja": "{pub} は作った公開鍵である可能性があり、すでにバックアップがそれを使っている可能性があります。それも "
    "USB メモリのファイルも削除しないでください。python tools/audit_verify.py {audit} を実行し、担当者が確認して"
    "ください。",
    "zh-TW": "{pub} 可能是剛建立的公開金鑰，且備份可能已在使用它：請勿刪除它或隨身碟上的檔案；請執行 "
    "python tools/audit_verify.py {audit} 並由人員檢查。",
}
AUDIT_FOLDER_UNSAFE = {
    "en": "refused: the audit folder {path} is a link, or root's and writable by its group or others: the ceremony "
    "writes its event only in a folder that is not a link and that no other user can put a file in",
    "ja": "拒否：監査記録のフォルダー {path} はリンクか、root のもので、グループかほかの人が書き込めます。"
    "この手続きは、リンクではなく、ほかのユーザーがファイルを置けないフォルダーにだけ記録を書きます",
    "zh-TW": "已拒絕：稽核紀錄資料夾 {path} 是連結，或屬於 root 且群組或其他人可寫入：此儀式只將紀錄寫入不是連結、"
    "且其他使用者無法放入檔案的資料夾",
}
AUDIT_ENTRY_UNSAFE = {
    "en": "refused: {path} in the audit folder, which is root's, is not a plain file with one name (a link, a file "
    "with a second name, or a special file): the ceremony does not write as root through it; have a person look "
    "(python tools/audit_verify.py)",
    "ja": "拒否：root の監査記録のフォルダーにある {path} は、名前が一つの通常のファイルではありません（リンク、"
    "別の名前もあるファイル、または特殊なファイル）。この手続きは root としてそれを通して書きません。担当者が確認"
    "してください（python tools/audit_verify.py）",
    "zh-TW": "已拒絕：屬於 root 的稽核紀錄資料夾中的 {path} 不是只有一個名稱的一般檔案（連結、有第二個名稱的檔案，"
    "或特殊檔案）：此儀式不會以 root 身分經由它寫入；請由人員檢查（python tools/audit_verify.py）",
}
AUDIT_DROP_FAILED = {
    "en": "refused: the audit event was not written to {path}: the ceremony writes it as the audit folder's owner "
    "({owner}), never as root, and could not take that identity: the ceremony is not done",
    "ja": "拒否：監査記録を {path} に書きませんでした。この手続きは root ではなく監査記録のフォルダーの所有者"
    "（{owner}）として書きますが、その所有者に切り替えられませんでした。手続きは完了していません",
    "zh-TW": "已拒絕：未將稽核紀錄寫入 {path}：此儀式以稽核紀錄資料夾的擁有者（{owner}）身分寫入，絕不以 root 寫入，"
    "但無法切換為該身分：儀式未完成",
}
AUDIT_HELPER_LOST = {
    "en": "refused: the audit helper for {path} stopped answering, so what it wrote is not known from it: the "
    "ceremony is not done",
    "ja": "拒否：{path} の監査記録の補助プロセスが応答しなくなったため、何を書いたかはそこからはわかりません。"
    "手続きは完了していません",
    "zh-TW": "已拒絕：{path} 的稽核紀錄輔助程序已停止回應，因此無法從它得知寫入了什麼：儀式未完成",
}
HELPER_SIGNALLED = {
    "en": "The audit helper, a process of the audit folder's owner ({owner}), was stopped or killed by a signal; that "
    "owner can do this.",
    "ja": "監査記録の補助プロセス（監査記録のフォルダーの所有者 {owner} のプロセス）がシグナルで停止または強制終了"
    "されました。この所有者にはそれができます。",
    "zh-TW": "稽核紀錄輔助程序（稽核紀錄資料夾擁有者 {owner} 的程序）被訊號暫停或終止；該擁有者能這樣做。",
}
HELPER_SILENT = {
    "en": "The audit helper, a process of the audit folder's owner ({owner}), ended, did not answer within {limit} "
    "seconds, or answered something that is not an outcome, and was stopped.",
    "ja": "監査記録の補助プロセス（監査記録のフォルダーの所有者 {owner} のプロセス）が終了したか、{limit} 秒以内に"
    "応答しなかったか、結果ではない応答を返したため、止めました。",
    "zh-TW": "稽核紀錄輔助程序（稽核紀錄資料夾擁有者 {owner} 的程序）已結束、未在 {limit} 秒內回應，或回應的不是"
    "結果，已將其停止。",
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
    private = True
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
        if private:  # a probe shown readable by others is said as that, whether or not its removal worked
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
    stick: Path, operator: str | None, witness: str | None, pub: Path, sec: Path, audit_dir: Path | None,
    site: str = "", tz: str | None = None,
) -> tuple[str, str, _Stick, _Audit]:  # fmt: skip
    """Every refusal before anything is written, in the order a person meets them; returns the two names, the
    stick's folder held open (:class:`_Stick`) and the audit's writer (:func:`_audit_for`: for a folder of another
    owner, the audit helper, started here, before the stick is opened and long before any key exists); the caller
    closes both. The once-only read of the audit is the writer's (the helper's, as the folder's owner). The
    removable-media check is made on the folder held open (``/proc/self/fd/<fd>`` leads to that folder, whatever is
    mounted at the path since)."""
    from tools import key_escrow as ke

    if not is_root():
        raise CeremonyError(NOT_ROOT)
    who, wit = person(operator), person(witness)
    if folded(who) == folded(wit):
        raise CeremonyError(SAME_PERSON)
    if audit_dir is None or not audit_dir.is_dir():
        raise CeremonyError(NO_AUDIT)
    dfd, uid, gid = _open_audit(audit_dir)  # a link, a folder others may plant in: refused before anything is written
    try:
        if os.path.lexists(pub):
            fp = _pub_fingerprint(pub)
            err = CeremonyError(ALREADY, fp=fp)
            with contextlib.suppress(CeremonyError):  # an audit that cannot be read says nothing either way
                if not any(_detail(r).get("fingerprint") == fp for r in _ceremonies(audit_dir)):
                    err.more.append((NO_CEREMONY_FOR_KEY, {}))
            raise err
    except BaseException:
        os.close(dfd)
        raise
    audit = _audit_for(audit_dir, dfd, uid, gid, site, tz)  # takes the descriptor
    try:
        if (prev := audit.earlier()) is not None:
            det = _detail(prev)
            err = CeremonyError(AUDITED_ALREADY, at=str(prev.get("ts") or "-"), fp=str(det.get("fingerprint") or "-"))
            err.more.append((AUDITED_NO_KEY, {"fp": str(det.get("fingerprint") or "-")}))  # no backup.pub: D-1379
            raise err
        return (who, wit, _check_stick(stick, sec, ke), audit)
    except BaseException:
        audit.close()
        raise


def _check_stick(stick: Path, sec: Path, ke: Any) -> _Stick:
    """The stick's checks of :func:`check`; the folder held open (:class:`_Stick`)."""
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
    return _Stick(stick, fd, dev)


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
        self.trying: Path | None = None  # a file being made, not yet registered: it may exist

    def forget(self, path: Path) -> None:
        self.files = [m for m in self.files if m.path != path]

    def made(self) -> list[Path]:
        """Every file and folder made so far (and one being made), whatever the undo did to it since: what may
        remain when an undo was cut short."""
        out = [m.path for m in self.files] + list(self.dirs)
        return out + ([self.trying] if self.trying is not None and self.trying not in out else [])

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
    undo.trying = path
    try:
        fd = os.open(path.name, flags, mode, dir_fd=stick.fd) if stick is not None else os.open(path, flags, mode)
    except FileExistsError:  # made since the check (another run on this stick): never this run's to remove
        undo.trying = None
        if stick is None:
            raise
        raise CeremonyError(STICK_HAS_KEY, name=path.name) from None
    except OSError:  # nothing was made
        undo.trying = None
        raise
    try:
        st = os.fstat(fd)
        made = _Made(path, st.st_dev, st.st_ino, secret=stick is not None, dir_fd=stick.fd if stick else None)
        undo.files.append(made)
        undo.trying = None
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


def _pub_state(pub: Path, staged: _Made | None) -> str:
    """What is at ``backup.pub`` now, looked at (``lstat``, never followed): ``ours`` (the staged file's device and
    inode: it is linked), ``absent``, ``other`` (another file) or ``unknown`` (it cannot be looked at)."""
    try:
        st = os.stat(pub, follow_symlinks=False)
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unknown"
    return "ours" if staged is not None and (st.st_dev, st.st_ino) == (staged.dev, staged.ino) else "other"


def _names_of(m: _Made) -> int | None:
    """How many names the staged file has now (1: only its temporary name), or None when it cannot be told."""
    try:
        st = os.stat(m.path, follow_symlinks=False)
    except OSError:
        return None
    return st.st_nlink if (st.st_dev, st.st_ino) == (m.dev, m.ino) else None


@dataclass(frozen=True)
class _AuditFile:
    """An entry of the audit folder as ``lstat`` gave it (a link is not followed)."""

    dev: int
    ino: int
    uid: int
    gid: int
    mode: int
    nlink: int
    regular: bool


def _audit_files(audit_dir: Path, dir_fd: int | None = None) -> dict[str, _AuditFile]:
    """Every entry of the audit folder itself (the audit library makes no subfolder in it), by name. With ``dir_fd``
    the folder held open is listed and each name looked at through it: no path is resolved."""
    fd = os.open(audit_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC) if dir_fd is None else dir_fd
    try:
        out: dict[str, _AuditFile] = {}
        for name in sorted(os.listdir(fd)):
            try:
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            out[name] = _AuditFile(st.st_dev, st.st_ino, st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode), st.st_nlink,
                                   stat.S_ISREG(st.st_mode))  # fmt: skip
        return out
    finally:
        if dir_fd is None:
            os.close(fd)


@dataclass
class _Left:
    """What the read-only check after an append (:func:`_root_left`) found: ``files``, entries of the audit folder
    that are root's though the folder is not; ``unlisted``, the folder could not be opened or listed (not checked)."""

    files: list[Path]
    unlisted: bool = False


#: How an append ended, the only thing the audit helper that wrote it tells this process (:class:`_Helper`): ``ok``
#: (the append returned), ``line-synced`` (the event's line is on disk, its head anchor not confirmed),
#: ``not-written`` (the chain, read whole, has no such event), ``unknown`` (the line may be in the file, not known on
#: disk; also a helper that is gone without a word) and ``drop-failed`` (the helper's first word only: it could not
#: take the folder owner's identity, and wrote nothing).
OUTCOMES = ("ok", "line-synced", "not-written", "unknown", "drop-failed")


def _folder_owner(fd: int) -> tuple[int, int]:
    """The owner and group of the audit folder held open as ``fd`` (``fstat``; the seam the tests inject)."""
    st = os.fstat(fd)
    return st.st_uid, st.st_gid


def _drop_to(uid: int, gid: int) -> None:
    """In the audit helper: become ``uid``/``gid`` for good (no supplementary group, real, effective and saved ids
    all changed), checked; then not dumpable again (a change of identity resets it), so the folder's owner cannot read
    the helper's memory or make it write a core. Raises when any of it does not hold (the seam the tests inject)."""
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    if (os.getresuid() != (uid, uid, uid) or os.getresgid() != (gid, gid, gid) or set(os.getgroups()) - {gid}
            or os.geteuid() != uid):  # fmt: skip
        raise PermissionError(errno.EPERM, "the change of identity did not hold")
    _not_dumpable()


def _open_audit(audit_dir: Path) -> tuple[int, int, int]:
    """The audit folder held open (``O_DIRECTORY|O_NOFOLLOW``) with its owner and group (:func:`_folder_owner`).
    Refused (:data:`AUDIT_FOLDER_UNSAFE`): a link, or a folder of root's that its group or others may write. A folder
    of root's must hold only plain files with one name (:func:`_plain_entries`). The caller closes the descriptor."""
    try:
        fd = os.open(audit_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.ENOTDIR):
            raise CeremonyError(AUDIT_FOLDER_UNSAFE, path=audit_dir) from None
        raise CeremonyError(NO_AUDIT) from None
    try:
        uid, gid = _folder_owner(fd)
        if uid == 0:
            if stat.S_IMODE(os.fstat(fd).st_mode) & 0o022:
                raise CeremonyError(AUDIT_FOLDER_UNSAFE, path=audit_dir)
            _plain_entries(fd, audit_dir)
    except BaseException:
        os.close(fd)
        raise
    return fd, uid, gid


def _plain_entries(dfd: int, audit_dir: Path) -> None:
    """A folder of root's, where root appends in this process: every entry, looked at through the folder held open
    and never followed, must be a regular file with one name (no link, no second name, no special file), or
    :data:`AUDIT_ENTRY_UNSAFE`. What is left: a name planted between this listing and the append, by a process that
    may write a folder of root's that its group and others may not, that is, by root."""
    try:
        entries = _audit_files(audit_dir, dfd)
    except OSError:
        raise CeremonyError(AUDIT_UNREADABLE, path=audit_dir, audit=audit_dir) from None
    for name, f in entries.items():
        if not f.regular or f.nlink != 1:
            raise CeremonyError(AUDIT_ENTRY_UNSAFE, path=audit_dir / name)


def _append_here(where: Path, event: str, detail: Mapping[str, Any], tz: str | None, fp: str) -> tuple[str, bool]:
    """Append ``event`` to the audit at ``where`` in this process: how it ended (:data:`OUTCOMES`; a failure judged by
    :func:`_audit_state`) and whether it was interrupted (Ctrl-C)."""
    from tb_common.audit import AuditLog

    try:
        log = AuditLog(where, tz=tz) if tz else AuditLog(where)
        log.append(event, actor=ACTOR, input_sha="", detail=dict(detail))
        return "ok", False
    except BaseException as e:
        return _audit_state(e, where, event, fp), isinstance(e, KeyboardInterrupt)


#: How long the audit helper may take to answer a request before it is killed (seconds), and how long it is given
#: after Ctrl-C (a second Ctrl-C kills it at once). An append takes milliseconds; a killed helper's append is
#: ``unknown``. ``HELPER_POLL``: how often the wait for an answer looks for Ctrl-C.
CHILD_LIMIT = 120.0
CHILD_GRACE = 10.0
HELPER_POLL = 0.1
#: The audit helper's protocol (:class:`_Helper`): one request a line from this process, ``event <json>``,
#: ``undone <json>`` (the event's fields: names, site, fingerprint, time; never key material), ``earlier?`` (the
#: once-only read) or ``quit``; one answer a line from the helper: a word of :data:`OUTCOMES` for an append; for
#: ``earlier?``, ``none``, ``found <json of the time and fingerprint>``, ``unreadable <json of the file's name>`` or
#: ``unknown``; and once, right after the fork, ``ready`` or ``drop-failed``.
REQUESTS = {"event": EVENT, "undone": UNDONE_EVENT}
REQUEST_MAX = 16384
ANSWER_MAX = 4096


def _new_key() -> Any:
    """A new X25519 private key (the seam the tests spy on: the audit helper must already run, dropped, when it is
    called, and nothing forks after it)."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    return X25519PrivateKey.generate()


def _no_core() -> None:
    """This process writes no core file (``RLIMIT_CORE`` 0, soft and hard): a crash of root's while the key is in
    memory leaves it on no disk."""
    import resource

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _not_dumpable() -> None:
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(4, 0, 0, 0, 0) != 0 or libc.prctl(3, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE 0, PR_GET_DUMPABLE
        raise PermissionError(errno.EPERM, "the process could not be made not dumpable")


def _send(fd: int, data: bytes) -> None:
    """Write ``data`` whole to a pipe (the seam the tests read: nothing this process sends the helper may hold key
    material, a line of the sheet or a path on the stick)."""
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


def _keep_only(*keep: int) -> tuple[int, ...]:
    """In the helper, right after the fork: every descriptor closed but ``keep`` (the audit folder and the two pipe
    ends); 0, 1 and 2 are ``/dev/null`` (nothing it prints reaches a file it holds). Returns ``keep`` (moved above 2
    first when one was below)."""
    import fcntl

    keep = tuple(k if k > 2 else fcntl.fcntl(k, fcntl.F_DUPFD, 3) for k in keep)
    null = os.open("/dev/null", os.O_RDWR)
    for i in (0, 1, 2):
        if null != i:
            os.dup2(null, i)
    lo = 3
    for k in sorted(set(keep)):
        if lo < k:
            os.closerange(lo, k)
        lo = k + 1
    os.closerange(lo, max(int(os.sysconf("SC_OPEN_MAX")), lo + 1))
    return keep


def _reply(fd: int, text: str) -> None:
    _send(fd, (text + "\n").encode("ascii", "replace"))


def _answer(verb: str, body: str, site: str, tz: str | None) -> str:
    """The helper's answer to one request, in the audit folder (its working folder: every path relative)."""
    try:
        if verb in REQUESTS:
            detail = json.loads(body)
            if not isinstance(detail, dict):
                return "unknown"
            fp = str(detail.get("fingerprint") or "")
            return str(_append_here(Path("."), REQUESTS[verb], detail, tz, fp)[0])
        if verb == "earlier?":
            try:
                rec = earlier_ceremony(Path("."), site)
            except CeremonyError as e:
                return "unreadable " + json.dumps({"name": Path(str(e.fill.get("path") or "")).name})
            if rec is None:
                return "none"
            return "found " + json.dumps({"ts": str(rec.get("ts") or "-"),
                                          "fp": str(_detail(rec).get("fingerprint") or "-")})  # fmt: skip
    except BaseException:  # whatever stops it, the helper answers and goes on
        return "unknown"
    return "unknown"


def _serve(req: int, ans: int, site: str, tz: str | None) -> None:
    """The helper's loop: one answer for each request line, until ``quit`` or the end of the request pipe (this
    process gone)."""
    buf = b""
    while True:
        while b"\n" not in buf:
            chunk = os.read(req, 4096)
            if not chunk or len(buf) + len(chunk) > REQUEST_MAX:
                return
            buf += chunk
        line, buf = buf.split(b"\n", 1)
        verb, _, body = line.decode("ascii", "replace").partition(" ")
        if verb == "quit":
            return
        _reply(ans, _answer(verb, body, site, tz))


def _helper_main(dfd: int, uid: int, gid: int, req: int, ans: int, site: str, tz: str | None) -> None:
    """The helper process, from the fork on: closes every descriptor but the audit folder and its two pipe ends,
    writes no core and is not dumpable, drops to ``uid``/``gid`` (:func:`_drop_to`), ``fchdir``s to the folder held
    open and closes it, says ``ready`` (or ``drop-failed``), and serves (:func:`_serve`). Ctrl-C is ignored (this
    process decides); the cyclic collector is off. Every path ends with ``os._exit``: it never returns into the
    program or runs its exit handlers."""
    import gc

    try:
        gc.disable()
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.pthread_sigmask(signal.SIG_SETMASK, set())
        dfd, req, ans = _keep_only(dfd, req, ans)
        try:
            _no_core()
            _not_dumpable()
            _drop_to(uid, gid)
            os.fchdir(dfd)
            os.close(dfd)
        except BaseException:
            _reply(ans, "drop-failed")
            return
        _reply(ans, "ready")
        _serve(req, ans, site, tz)
    except BaseException:
        pass
    finally:
        os._exit(0)


class _Audit:
    """The audit's writer for one run (:func:`_audit_for`): ``earlier`` (the once-only read), ``append`` (an event:
    how it ended, :data:`OUTCOMES`, and whether this process was interrupted), ``outcome`` (an event's word as far as
    it is known, read again after an interruption), ``gone`` (what is said when the helper stopped answering) and
    ``close``."""

    folder: Path

    def earlier(self) -> dict[str, Any] | None:
        raise NotImplementedError

    def append(self, event: str, detail: Mapping[str, Any]) -> tuple[str, bool]:
        raise NotImplementedError

    def outcome(self, event: str) -> str | None:
        raise NotImplementedError

    def gone(self) -> list[tuple[Mapping[str, str], dict[str, Any]]]:
        return []

    def close(self) -> None:
        raise NotImplementedError


class _InPlace(_Audit):
    """A folder of root's (no owner to drop to): this process appends, through the folder held open (``fchdir`` to
    it, relative paths, then back), after its mode and entries were checked through the same descriptor
    (:func:`_plain_entries`); the folder is never opened by its path again."""

    def __init__(self, folder: Path, dfd: int, site: str, tz: str | None) -> None:
        self.folder, self.dfd, self.site, self.tz = folder, dfd, site, tz
        self.words: dict[str, str] = {}
        self.pending: str | None = None

    def earlier(self) -> dict[str, Any] | None:
        here = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fchdir(self.dfd)
            try:
                return earlier_ceremony(Path("."), self.site)
            except CeremonyError as e:  # named under the folder's path as given, as the helper's answer is
                if e.text is not AUDIT_UNREADABLE:
                    raise
                name = Path(str(e.fill.get("path") or "")).name
                raise CeremonyError(AUDIT_UNREADABLE, path=self.folder / name, audit=self.folder) from None
            finally:
                os.fchdir(here)
        finally:
            os.close(here)

    def append(self, event: str, detail: Mapping[str, Any]) -> tuple[str, bool]:
        if stat.S_IMODE(os.fstat(self.dfd).st_mode) & 0o022:
            raise CeremonyError(AUDIT_FOLDER_UNSAFE, path=self.folder)
        _plain_entries(self.dfd, self.folder)
        fp = str(detail.get("fingerprint") or "")
        here = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            self.pending = event
            os.fchdir(self.dfd)
            try:
                word, interrupted = _append_here(Path("."), event, detail, self.tz, fp)
                self.words[event], self.pending = word, None
            finally:
                os.fchdir(here)
        finally:
            os.close(here)
        return word, interrupted

    def outcome(self, event: str) -> str | None:
        if event in self.words:
            return self.words[event]
        return "unknown" if self.pending == event else None

    def close(self) -> None:
        os.close(self.dfd)


class _Helper(_Audit):
    """The audit helper (D-1379): one process, forked (:meth:`start`) before any key material exists in this one and
    dropped to the audit folder's owner, alive for the whole run; it takes requests over a pipe pair
    (:data:`REQUESTS`) and answers with one word. This process always reaps it (:meth:`close`): it is killed when an
    answer takes longer than :data:`CHILD_LIMIT`, or :data:`CHILD_GRACE` after Ctrl-C (at once on a second one). A
    helper that dies, hangs or answers garbage is ``gone``: every later append is ``unknown``."""

    def __init__(self, folder: Path, pid: int, req: int, ans: int, owner: tuple[int, int]) -> None:
        self.folder, self.pid, self.req, self.ans, self.owner = folder, pid, req, ans, owner
        self.buf = b""
        self.words: dict[str, str] = {}
        self.pending: str | None = None
        self.cause: str | None = None  # "signalled" or "silent" once it is gone
        self.reaped = self.closed = False

    @classmethod
    def start(cls, folder: Path, dfd: int, uid: int, gid: int, site: str, tz: str | None) -> _Helper:
        """Fork the helper (the cyclic collector run here first; Ctrl-C blocked across the fork only) and wait for
        its first word (Ctrl-C shortens that wait to :data:`CHILD_GRACE`). ``drop-failed``: :data:`AUDIT_DROP_FAILED`;
        no word: :data:`AUDIT_HELPER_LOST`. Either way, and on Ctrl-C, the helper is reaped before this raises."""
        import gc

        gc.collect()
        req_r, req_w = os.pipe()
        ans_r, ans_w = os.pipe()
        old = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
        try:
            pid = os.fork()
        except OSError:
            signal.pthread_sigmask(signal.SIG_SETMASK, old)
            for fd in (req_r, req_w, ans_r, ans_w):
                os.close(fd)
            raise CeremonyError(AUDIT_DROP_FAILED, path=folder, owner=f"{uid}:{gid}") from None
        if pid == 0:  # the helper: never returns
            os.close(req_w)
            os.close(ans_r)
            _helper_main(dfd, uid, gid, req_r, ans_w, site, tz)
            os._exit(0)
        os.close(req_r)
        os.close(ans_w)
        h = cls(folder, pid, req_w, ans_r, (uid, gid))
        try:
            # the mask as it was, first thing in the block that always reaps: Ctrl-C was blocked across the fork
            # only, so the wait for ``ready`` is interruptible (:data:`CHILD_GRACE`), and a Ctrl-C held meanwhile
            # lands here, where the helper is reaped
            signal.pthread_sigmask(signal.SIG_SETMASK, old)
            h.pending = "start"
            first, interrupted = h._wait()
            if interrupted:
                raise KeyboardInterrupt
            if first == "drop-failed":
                raise CeremonyError(AUDIT_DROP_FAILED, path=folder, owner=f"{uid}:{gid}")
            if first != "ready":
                raise h.lost()
        except BaseException:
            h.close()
            raise
        return h

    def _wait(self) -> tuple[str | None, bool]:
        """The answer to the pending request (one line), or None when the helper is gone (ended, killed, stopped,
        too slow, garbage), and whether Ctrl-C came meanwhile. Ctrl-C only shortens the wait (a flag, never an
        exception here), so an answer already received is always read; the answer is kept before this returns."""
        import select
        import time

        hits = [0]
        try:
            old = signal.signal(signal.SIGINT, lambda *_: hits.__setitem__(0, hits[0] + 1))
        except ValueError:  # not the main thread: Ctrl-C cannot reach this wait as a signal handler
            old = None
        seen, line = 0, None
        deadline = time.monotonic() + CHILD_LIMIT
        try:
            while True:
                if b"\n" in self.buf:
                    raw, self.buf = self.buf.split(b"\n", 1)
                    if self.buf:  # more than one answer: garbage
                        self._lose("silent")
                        break
                    line = raw.decode("ascii", "replace")
                    if self.pending is not None:
                        self.words[self.pending] = line
                    break
                if hits[0] != seen:
                    deadline = min(deadline, time.monotonic() + (CHILD_GRACE if seen == 0 else 0.0))
                    seen = hits[0]
                left = deadline - time.monotonic()
                if left <= 0:
                    self._lose("silent")
                    break
                ready, _, _ = select.select([self.ans], [], [], min(left, HELPER_POLL))
                if not ready:
                    continue
                chunk = os.read(self.ans, 4096)
                if not chunk:
                    self._lose("ended")
                    break
                self.buf += chunk
                if len(self.buf) > ANSWER_MAX:
                    self._lose("silent")
                    break
        finally:
            self.pending = None
            if old is not None:
                signal.signal(signal.SIGINT, old)
        return line, hits[0] > 0

    def _lose(self, how: str) -> None:
        """The helper is gone: say why (stopped or killed by a signal, or silent), kill it if it still runs, reap."""
        import time

        status = 0
        if not self.reaped:
            until = time.monotonic() + (1.0 if how == "ended" else 0.0)
            while True:
                try:
                    wpid, status = os.waitpid(self.pid, os.WNOHANG | os.WUNTRACED)
                except ChildProcessError:
                    wpid, self.reaped = self.pid, True
                    break
                if wpid or time.monotonic() >= until:
                    break
                time.sleep(0.02)
            by_signal = os.WIFSTOPPED(status) or os.WIFSIGNALED(status) if wpid else _stopped(self.pid)
            if by_signal:
                self.cause = "signalled"
            if wpid and not os.WIFSTOPPED(status):
                self.reaped = True
            self._reap(kill=True)
        if self.cause is None:
            self.cause = "silent"

    def _reap(self, kill: bool) -> None:
        if self.reaped:
            return
        if kill:
            with contextlib.suppress(OSError):
                os.kill(self.pid, signal.SIGKILL)
        while True:
            try:
                os.waitpid(self.pid, 0)
                break
            except KeyboardInterrupt:
                continue
            except ChildProcessError:
                break
        self.reaped = True

    def lost(self) -> CeremonyError:
        err = CeremonyError(AUDIT_HELPER_LOST, path=self.folder)
        err.more.extend(self.gone())
        return err

    def gone(self) -> list[tuple[Mapping[str, str], dict[str, Any]]]:
        owner = f"{self.owner[0]}:{self.owner[1]}"
        if self.cause == "signalled":
            return [(HELPER_SIGNALLED, {"owner": owner})]
        if self.cause is not None:
            return [(HELPER_SILENT, {"owner": owner, "limit": int(CHILD_LIMIT)})]
        return []

    def _ask(self, verb: str, payload: Mapping[str, Any] | None = None) -> tuple[str | None, bool]:
        if self.cause is not None or self.closed:
            return None, False
        line = verb if payload is None else f"{verb} {json.dumps(dict(payload), ensure_ascii=True, sort_keys=True)}"
        self.pending = verb
        try:
            _send(self.req, (line + "\n").encode("ascii"))
        except OSError:  # the helper is gone (its end of the pipe closed)
            self.pending = None
            self._lose("ended")
            return None, False
        return self._wait()

    def earlier(self) -> dict[str, Any] | None:
        got, interrupted = self._ask("earlier?")
        if interrupted:
            raise KeyboardInterrupt
        verb, _, body = (got or "").partition(" ")
        try:
            if verb == "none" and not body:
                return None
            if verb == "found":
                d = json.loads(body)
                return {"ts": str(d["ts"]), "detail": {"fingerprint": str(d["fp"])}}
            if verb == "unreadable":
                name = Path(str(json.loads(body)["name"])).name
                raise CeremonyError(AUDIT_UNREADABLE, path=self.folder / name, audit=self.folder)
            if verb == "unknown" and not body:
                raise CeremonyError(AUDIT_UNREADABLE, path=self.folder, audit=self.folder)
        except (ValueError, KeyError, TypeError):
            pass
        if self.cause is None:
            self._lose("silent")
        raise self.lost()

    def append(self, event: str, detail: Mapping[str, Any]) -> tuple[str, bool]:
        verb = next(v for v, e in REQUESTS.items() if e == event)
        got, interrupted = self._ask(verb, detail)
        if got is not None and got not in OUTCOMES[:4]:  # not an append's word ("drop-failed" comes only first)
            self.words[verb] = "unknown"
            self._lose("silent")
            got = None
        return (got or "unknown"), interrupted

    def outcome(self, event: str) -> str | None:
        """The event's word as known now: the answer already read, else, when its request was sent and its answer
        is pending, that answer read now (or ``unknown``), else None (never sent)."""
        verb = next(v for v, e in REQUESTS.items() if e == event)
        if verb in self.words:
            return self.words[verb] if self.words[verb] in OUTCOMES[:4] else "unknown"
        if self.pending == verb and self.cause is None:
            got, _ = self._wait()
            return got if got in OUTCOMES[:4] else "unknown"
        return "unknown" if self.pending == verb else None

    def close(self) -> None:
        """Ask the helper to end (``quit``), close the pipes, and reap it: killed when it has not ended within
        :data:`CHILD_GRACE`. Ctrl-C meanwhile does not stop the reaping."""
        import time

        if self.closed:
            return
        self.closed = True
        old = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
        try:
            if not self.reaped and self.cause is None:
                with contextlib.suppress(OSError):
                    _send(self.req, b"quit\n")
            with contextlib.suppress(OSError):
                os.close(self.req)
            until = time.monotonic() + CHILD_GRACE
            while not self.reaped:
                try:
                    wpid, _ = os.waitpid(self.pid, os.WNOHANG)
                except ChildProcessError:
                    self.reaped = True
                    break
                if wpid:
                    self.reaped = True
                    break
                if time.monotonic() >= until:
                    self._reap(kill=True)
                    break
                time.sleep(0.02)
            with contextlib.suppress(OSError):
                os.close(self.ans)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, old)


def _stopped(pid: int) -> bool:
    """Whether the process ``pid`` is stopped (state ``T`` or ``t`` in ``/proc/<pid>/stat``)."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            return fh.read().rsplit(b")", 1)[1].split()[0] in (b"T", b"t")
    except (OSError, IndexError):
        return False


def _audit_for(folder: Path, dfd: int, uid: int, gid: int, site: str, tz: str | None) -> _Audit:
    """The audit's writer for this run, taking ``dfd`` (the folder held open by :func:`_open_audit`): a folder of
    another owner, the audit helper (:class:`_Helper`, which keeps its own copy of the descriptor; this one is closed
    here); a folder of root's, this process (:class:`_InPlace`)."""
    if uid == 0:
        return _InPlace(folder, dfd, site, tz)
    try:
        return _Helper.start(folder, dfd, uid, gid, site, tz)
    finally:
        os.close(dfd)


def _root_left(audit_dir: Path) -> _Left:
    """Read only, after an append: the entries of the audit folder that are root's though the folder is not (the
    child wrote as the folder's owner, so none should be). Nothing is changed; a folder of root's is not looked at."""
    try:
        dfd = os.open(audit_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return _Left([], unlisted=True)
    try:
        if _folder_owner(dfd)[0] == 0:
            return _Left([])
        return _Left([audit_dir / n for n, f in _audit_files(audit_dir, dfd).items() if f.uid == 0])
    except OSError:
        return _Left([], unlisted=True)
    finally:
        os.close(dfd)


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


def _line_synced(e: BaseException, fp: str, event: str = EVENT) -> bool:
    """Whether ``e`` was raised inside a call that ``AuditLog._write`` makes only after its ``os.fsync`` of the day
    file returned, in the ``_write`` of this ceremony's own ``event`` (its ``body``: this event, this fingerprint), read
    from the traceback (in the process that appended: the child, when a child wrote it). A failure in the write, the
    flush, the fsync or the close of the day file, or in an earlier event's ``_write`` (``audit.anchored``,
    ``audit.repaired``), is not."""
    tb = e.__traceback__
    while tb is not None:
        frame, nxt = tb.tb_frame, tb.tb_next
        if frame.f_code.co_name == "_write" and frame.f_globals.get("__name__") == "tb_common.audit" and nxt:
            body = frame.f_locals.get("body")
            ours = isinstance(body, dict) and body.get("event") == event and _detail(body).get("fingerprint") == fp
            callee = nxt.tb_frame
            same_module = callee.f_globals.get("__name__") == "tb_common.audit"
            if ours and same_module and callee.f_code.co_name in AFTER_LINE_SYNC:
                return True
        tb = nxt
    return False


def _audit_state(e: BaseException, audit_dir: Path, event: str, fp: str) -> str:
    """After a failed append of ``event``: ``line-synced`` when its line is on disk (:func:`_line_synced`, and the
    audit folder, which holds the day file's name, syncs now); ``not-written`` when the chain, read whole, has no such
    event of this fingerprint; else ``unknown`` (the line may be in the file but is not known to be on disk)."""
    try:
        if _line_synced(e, fp, event):
            _sync_dir(audit_dir)
            return "line-synced"
        if any(_detail(r).get("fingerprint") == fp for r in _ceremonies(audit_dir, (event,))):
            return "unknown"
        return "not-written"
    except BaseException:  # whatever stops this check, nothing is known: undo and say "may"
        return "unknown"


_EVENT_STATE = {"ok": "recorded", "line-synced": "recorded", "unknown": "unknown"}  # an append's word: the event


@dataclass
class _Progress:
    """What a run has done so far, kept as each step happens, for the outermost handler (:func:`main`): a second
    interruption (or an error) while a failure is being handled, or after the run finished, is said from this, never
    as "nothing had been written" once a file was made. ``event``: ``absent``, ``recorded`` or ``unknown``;
    ``undone`` (the undoing): ``none`` (not tried), ``written``, ``absent`` or ``unknown``; ``linked``: ``backup.pub``
    may be the key just made."""

    undo: _Undo | None = None
    event: str = "absent"
    undone: str = "none"
    fp: str = ""
    linked: bool = False

    def said(self, pub: Path, audit: Path) -> list[tuple[Mapping[str, str], dict[str, Any]]]:
        out: list[tuple[Mapping[str, str], dict[str, Any]]] = []
        if self.event == "recorded" and self.linked:
            out.append((EVENT_WRITTEN, {"event": EVENT, "fp": self.fp}))
            out.append((LATE_PUB, {"pub": pub, "audit": audit}))
            return out
        if self.event == "recorded":
            text = {"written": UNDONE_WRITTEN, "unknown": UNDONE_UNKNOWN}.get(self.undone, AUDIT_HOLDS)
            out.append((text, {"fp": self.fp}))
        elif self.event == "unknown":
            out.append((AUDIT_MAY_HOLD, {"fp": self.fp}))
        else:
            out.append((EVENT_NOT_WRITTEN, {}))
        made = self.undo.made() if self.undo is not None else []
        if made:
            out.append((MAY_REMAIN, {"files": ", ".join(str(p) for p in made)}))
        return out

    def nothing(self) -> bool:
        return self.event == "absent" and not self.linked and not (self.undo is not None and self.undo.made())


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
    progress: _Progress | None = None,
) -> dict[str, Any]:
    """The ceremony; returns what the audit holds (no key) and ``warnings`` (texts said after the closing text, exit
    :data:`KEPT_EXIT`). :class:`CeremonyError` on a refusal; after the first file is made, every failure (an
    interruption too) undoes what was made and the refusal says what was removed, except once ``backup.pub`` may
    have been visible (:class:`CeremonyKept`: nothing of the key is removed then). ``progress`` is kept up to date as
    each step happens (:class:`_Progress`), for what escapes this (a second interruption)."""
    who, wit, held, audit = check(stick, operator, witness, pub, sec, audit_dir, site, tz)
    try:
        if audit_dir is None:  # check() refused already; said again for the type checker
            raise CeremonyError(NO_AUDIT)
        prog = progress if progress is not None else _Progress()
        return _ceremony(held, who, wit, pub=pub, audit_dir=audit_dir, audit=audit, site=site, now=now, tz=tz,
                         prog=prog)  # fmt: skip
    finally:
        try:
            os.close(held.fd)
        finally:
            audit.close()  # the audit helper ends and is reaped, whatever happened


def _ceremony(
    held: _Stick, who: str, wit: str, *, pub: Path, audit_dir: Path, audit: _Audit, site: str, now: datetime | None,
    tz: str | None, prog: _Progress,
) -> dict[str, Any]:  # fmt: skip
    """The writes, in this order (D-1379): the key file and the paper sheet in the stick's folder held open, the
    folder synced, both read back; the public key as a synced temporary file beside ``backup.pub``; the audit event,
    its line synced, written as the audit folder's owner (by the audit helper, started before this, before any key
    material exists: :func:`check`); and only then ``backup.pub`` linked to its name, so a ``trialbox backup`` can
    find the public key only once the event that names it is on disk. This process writes no core from here on."""
    from zoneinfo import ZoneInfo

    from cryptography.hazmat.primitives import serialization

    from tools.trialbox import backup as bk

    stick = held.path
    key_file, paper_file = stick / KEY_FILE, stick / PAPER_FILE
    undo, step, fp, link = _Undo(), "start", "", "no"
    prog.undo = undo
    detail: dict[str, Any] = {}
    audit_state = "absent"  # "recorded" from the moment the event's line is known to be on disk, whatever comes after
    anchor_unconfirmed = False
    left: list[_Left] = []
    staged: _Made | None = None
    try:
        ZoneInfo(tz or "Asia/Taipei")  # the site's zone, as `restore` writes it: a wrong one refused before the key
        at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
        _no_core()  # root's own crash from here on writes no core holding the key
        sk = _new_key()  # the audit helper runs already, dropped; nothing forks from here on
        raw = sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                               serialization.NoEncryption())  # fmt: skip
        pk = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        fp = prog.fp = bk.fingerprint(pk)
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
        detail = {"at": at, "site": site, "fingerprint": fp, "operator": who, "witness": wit,
                  "forms": ["stick", "paper"], "paper_format": FORMAT}  # fmt: skip
        step = "audit"
        word, interrupted = audit.append(EVENT, detail)  # root never writes in the audit folder
        audit_state = prog.event = _EVENT_STATE.get(word, "absent")
        if audit_state != "recorded":
            if interrupted:
                raise KeyboardInterrupt
            if isinstance(audit, _Helper) and audit.gone():  # the helper stopped answering: said so, with the cause
                raise audit.lost()
            raise OSError(errno.EIO, "the audit append did not write the event")  # said as AUDIT_FAILED
        anchor_unconfirmed = word == "line-synced"  # the line is on disk: go on, and say it (KEPT_WARNING)
        if interrupted:  # Ctrl-C while the helper wrote: the event is on disk, backup.pub not linked: undone
            raise KeyboardInterrupt
        step = "audit-check"
        left.append(_root_left(audit_dir))  # read only: the child wrote as the folder's owner
        step, link = "link", "trying"
        os.link(staged.path, pub)  # no overwrite: FileExistsError when a file of that name appeared meanwhile
        link, prog.linked = "done", True
        os.unlink(staged.path)
        undo.forget(staged.path)
        _sync_dir(pub.parent)
    except BaseException as e:  # one failure domain: nothing of a failed ceremony is kept (D-1379)
        if step == "audit" and audit_state == "absent":  # an interruption around the append: its answer read first
            got = audit.outcome(EVENT)
            if got is not None:
                audit_state = prog.event = _EVENT_STATE.get(got, "absent")
        if audit_state == "recorded":  # the event's line is on disk, whatever failed after it
            raise _after_event(e, step, link, undo, staged, audit, left, detail, held, pub, audit_dir, prog) from None
        err = _cause(e, step, stick, pub, audit_dir)
        err.more = [*err.more, *undo.run(), *_owner_said(left, audit_dir)]
        if step == "audit" and audit_state == "unknown":
            err.more.append((AUDIT_MAY_HOLD, {"fp": fp}))
        raise err from None
    warnings = _owner_said(left, audit_dir)
    if anchor_unconfirmed:  # the chain holds the event on disk, its head anchor unconfirmed: no closing text
        kept = CeremonyKept(KEPT_WARNING, fp=fp, key=key_file.name, paper=paper_file.name, pub=pub, event=EVENT,
                            audit=audit_dir)  # fmt: skip
        kept.more = warnings
        raise kept
    return {**detail, "key_file": key_file.name, "paper_file": paper_file.name, "public": str(pub),
            "warnings": warnings}  # fmt: skip


def _after_event(
    e: BaseException, step: str, link: str, undo: _Undo, staged: _Made | None, audit: _Audit, left: list[_Left],
    detail: Mapping[str, Any], held: _Stick, pub: Path, audit_dir: Path, prog: _Progress,
) -> CeremonyError:  # fmt: skip
    """The refusal or warning for a failure once the event's line is on disk (an interruption while the child wrote
    it, the check after it, the link, the temporary name's removal, the folder's sync). Whether ``backup.pub`` was
    visible is decided by looking at it, not by where the code stopped: at the name, the staged file (same device and
    inode) was visible, so everything is kept (:data:`PUB_LINKED_WARNING`, exit 2). Not visible: the link was never
    tried, the link itself refused (``OSError``), or it was being tried and nothing is at the name while the staged
    file has only its temporary name. Then ``backup.key_ceremony_undone`` is written and everything is undone
    (D-1379). Anything else (another file at the name, a name that cannot be looked at, a name gone after the link
    returned): it may have been visible, so nothing of the key is removed (:data:`PUB_KEPT_WARNING`, exit 2)."""
    fp, stick = str(detail.get("fingerprint") or ""), held.path
    key, paper = (stick / KEY_FILE).name, (stick / PAPER_FILE).name
    state = _pub_state(pub, staged) if step == "link" else "absent"
    never = step != "link" or (
        link == "trying" and state != "ours" and (isinstance(e, OSError) or (
            state == "absent" and staged is not None and _names_of(staged) == 1)))  # fmt: skip
    if not never:
        prog.linked = True  # it may have been visible
        if staged is not None:  # the temporary name only (still the staged file): never backup.pub
            with contextlib.suppress(OSError):
                if _names_of(staged) is not None:
                    os.unlink(staged.path)
        text = PUB_LINKED_WARNING if state == "ours" else PUB_KEPT_WARNING
        kept = CeremonyKept(text, fp=fp, key=key, paper=paper, pub=pub, event=EVENT, audit=audit_dir)
        kept.more = _owner_said(left, audit_dir)
        return kept
    err = _cause(e, "public" if step == "link" else "after-audit", stick, pub, audit_dir)
    undone, more = _write_undone(audit, audit_dir, detail, e)
    prog.undone = undone
    err.more = undo.run() + _owner_said([*left, more], audit_dir)
    if undone != "written":
        err.more.append((UNDONE_UNKNOWN if undone == "unknown" else AUDIT_HOLDS, {"fp": fp}))
        err.more.extend(audit.gone())
    return err


def _owner_said(left: Sequence[_Left], audit_dir: Path) -> list[tuple[Mapping[str, str], dict[str, Any]]]:
    """What the checks after the appends found, said: :data:`AUDIT_OWNER_LEFT` for files of root's (naming the
    folder's owner), :data:`AUDIT_NOT_LISTED` for a folder not listed; nothing when none found anything."""
    files = list(dict.fromkeys(p for g in left for p in g.files))
    unlisted = any(g.unlisted for g in left)
    if not (files or unlisted):
        return []
    try:
        top = os.stat(audit_dir)
        owner = f"{top.st_uid}:{top.st_gid}"
    except OSError:
        owner = "-"
    said: list[tuple[Mapping[str, str], dict[str, Any]]] = []
    if files:
        said.append((AUDIT_OWNER_LEFT, {"files": ", ".join(str(p) for p in files), "owner": owner, "audit": audit_dir}))
    if unlisted:
        said.append((AUDIT_NOT_LISTED, {"audit": audit_dir, "owner": owner}))
    return said


def _write_undone(audit: _Audit, audit_dir: Path, detail: Mapping[str, Any], e: BaseException) -> tuple[str, _Left]:
    """``backup.key_ceremony_undone`` after the ceremony's event, written as the event was (by the same audit helper):
    ``backup.pub`` was never put in place, so no backup was made to the key and its copies can be removed; the
    once-only check counts the pair as not done. Whether it is written (``written``: its line is on disk, its head
    anchor confirmed or not, so a rerun is allowed; ``absent``: not written; ``unknown``: not known), and what the
    check after it found. Nothing here raises."""
    named = {k: detail[k] for k in ("at", "site", "fingerprint", "operator", "witness") if k in detail}
    try:
        word, _ = audit.append(UNDONE_EVENT, {**named, "why": type(e).__name__})
        undone = {"ok": "written", "line-synced": "written", "unknown": "unknown"}.get(word, "absent")
    except CeremonyError:  # the folder refused, or the owner's identity not taken: nothing written
        undone = "absent"
    except BaseException:  # whatever stopped it, the undoing is not known to be written
        undone = "unknown"
    try:
        got = _root_left(audit_dir)
    except BaseException:  # an interruption here too: the undo goes on, and the folder is said as not checked
        got = _Left([], unlisted=True)
    return undone, got


def _refuse(err: CeremonyError, lang: str, *, nothing: bool = False) -> int:
    if nothing:
        err.more = [(KEPT_NOTHING, {})]
    print(err.say(lang), file=sys.stderr)
    return 1


def _refuse_late(e: BaseException, prog: _Progress, pub: Path | None, audit: Path | None, lang: str) -> int:
    """What escaped :func:`run` (a second Ctrl-C while a failure was being handled, or an error there, or after the
    run returned): said from what the run is known to have done (:class:`_Progress`). Nothing made: as before, exit 1.
    Otherwise only what is known (the event written or not, its undoing written or not, what may remain and where),
    exit 2; never that nothing was written."""
    interrupted = isinstance(e, KeyboardInterrupt)
    if prog.nothing() or pub is None or audit is None:
        err = CeremonyError(INTERRUPTED) if interrupted else CeremonyError(UNEXPECTED, kind=type(e).__name__)
        return _refuse(err, lang, nothing=True)
    err = CeremonyError(INTERRUPTED_LATE) if interrupted else CeremonyError(UNEXPECTED_LATE, kind=type(e).__name__)
    err.more = prog.said(pub, audit)
    print(err.say(lang), file=sys.stderr)
    return KEPT_EXIT


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
    prog = _Progress()
    pub: Path | None = None
    audit: Path | None = None
    try:
        from tools import key_ceremony as kc
        from tools.keys import secrets_dir

        deploy = Path(a.deploy)
        pub = Path(a.public) if a.public else kc.default_backup_pub(env, deploy)
        audit = Path(a.audit_dir) if a.audit_dir else Path(env["TB_AUDIT_DIR"]) if env.get("TB_AUDIT_DIR") else None
        rec = run(Path(a.stick), a.operator, a.witness, pub=pub, sec=secrets_dir(a.secrets, env), audit_dir=audit,
                  site=env.get("TB_SITE_ID") or "", tz=env.get("TB_TZ") or None, progress=prog)  # fmt: skip
        print(DONE[lang].format(fp=rec["fingerprint"], key=rec["key_file"], paper=rec["paper_file"],
                                pub=rec["public"], event=EVENT, operator=rec["operator"],
                                witness=rec["witness"]))  # fmt: skip
        if rec["warnings"]:  # done, but the audit writer cannot append after it until a person looks
            lg = lang_of(lang)
            print(" ".join(t[lg].format(**f) for t, f in rec["warnings"]), file=sys.stderr)
            return KEPT_EXIT
        return 0
    except CeremonyKept as e:
        print(e.say(lang), file=sys.stderr)
        return KEPT_EXIT
    except CeremonyError as e:
        return _refuse(e, lang)
    # what is left escaped run(): before the first file is made, or a second interruption (or an error) while a
    # failure was being handled, or after run() returned: said from what is known to have been done
    except (KeyboardInterrupt, Exception) as e:
        return _refuse_late(e, prog, pub, audit, lang)


if __name__ == "__main__":
    raise SystemExit(main())
