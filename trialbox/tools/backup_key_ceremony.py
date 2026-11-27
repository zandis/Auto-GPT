"""``python -m tools.backup_key_ceremony`` (10K-13, D-1379): the backup-key ceremony on the box's host.

    python -m tools.backup_key_ceremony --stick /media/usb --operator "<name>" --witness "<name>" [--lang ja]

Hospital IT, as root on the box's host, with a witness who is another person, makes the box's backup key. Four steps,
each resumable, none undone, nothing ever deleted (D-1379, the owner's four conditions of 2026-11-20):

1. **the stick**: the key is made in memory and written to the stick named, as ``trialbox-backup.key`` (the format
   ``trialbox backup-keygen`` writes; ``restore --key`` reads it) and ``trialbox-backup-key-paper.txt`` (the sheet to
   print: the key in lines of four-letter groups, each line with four check letters, and the key's fingerprint);
2. **read back**: both files are read again from the stick after a sync (their cached pages dropped first) and must
   give one and the same key;
3. **the journal**: the event ``backup.key_ceremony`` (the fingerprint and both names, never the key) goes through the
   orchestrator's audit journal, as ``trialbox audit-sign`` records its event (root writes nothing in the audit
   folder); the journal must answer with the event's number;
4. **backup.pub**: only then the public key at ``deploy/secrets/backup.pub``, made new (never over a file), last.

"Once" means ``backup.pub`` exists: then the command says the ceremony is done and changes nothing. Before a new key
goes to a stick, its fingerprint and public key are recorded in ``deploy/secrets/backup-ceremony-<fp>.pending``
(never removed). A run cut short is finished by the same command with the same stick: a whole key file on a stick is
taken up again only when that record of it is on the box; any other key file, or a sheet without a key file, is
refused. A key from an abandoned run (the command run again with another, empty stick) stays on its stick, never the
box's key, until IT wipes it; its record stays too. One run at a time (a lock on the folder). The command refuses on a
box whose orchestrator journal does not answer, and the public key's folder is fixed (``deploy/secrets`` of this
checkout) and must be root's alone, as every folder above it. Every file on the stick is opened through the stick's
folder held open, never through a link, and must be a plain file of root's alone, one name, on that folder's
filesystem, which must be one removable block device; each is written under a temporary name and renamed, so a final
name never holds part of a file (a temporary file a run cut short left stays, and is never read again). The journal
is asked through the local Docker socket only, whatever context or host the environment names. The process is made
not dumpable, without a core, and its memory locked (or else no swap may be on) before any key exists; no key byte is
put in an argument, the environment, an exception, a log or the journal.

    python -m tools.backup_key_ceremony --install [--lang ja]
    python -m tools.backup_key_ceremony --install --sealed-stdin      (the passphrase on stdin, one line)

**At install** (E2E P-01, the integrator's ruling Q1 of 2026-11-27: a PRODUCTION box makes its backup key at
install, the key shown once and kept sealed): ``deploy/install.sh`` runs this as root when the box has no
``backup.pub``. The same checks of the public key's folder and the journal, then the key is made in memory and its
record is put on the box (as step 1).

* **On a terminal**: the paper copy and the key file's text are written to the terminal (``/dev/tty``, never the
  standard output, a log or a file) for hospital IT to print or copy and keep sealed. The screen is then cleared
  (also when the step stops half way), and IT types every line of the copy back, unseen, as ``restore --key`` reads
  it; only a copy that gives the key back (each line's check letters, then the key's fingerprint) lets the event go
  through the journal and ``backup.pub`` be made. A copy that does not, or no terminal: nothing is made but the
  record, and the install runs it again for a new key.
* **Unattended** (no terminal; the integrator's ruling (1) of 2026-11-27: the KEK comes from the install
  passphrase): the install hands its KEK passphrase on stdin. The key is sealed under scrypt(passphrase, a new salt)
  (``tb_common.kek``, the passphrase back end's KDF, its parameters recorded beside it) into
  ``deploy/secrets/backup-key-<fp>.sealed`` (root's alone, never a plain key), opened again to check it, and only then
  the event and ``backup.pub``. Hospital IT copies that file off the box; ``--unseal FILE --out KEYFILE`` (the
  passphrase on stdin) gives back the key file ``restore --key`` reads.

``trialbox backup-keygen`` and the stick ceremony stay refused on a PRODUCTION box (rc1's ``key_ceremonies``): this
is the one way a PRODUCTION box gets its key, once.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import errno
import fcntl
import functools
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import termios
import unicodedata
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

EVENT = "backup.key_ceremony"
ACTOR = "trialbox:backup-key-ceremony"
KEY_FILE = "trialbox-backup.key"
PAPER_FILE = "trialbox-backup-key-paper.txt"
PUB_NAME = "backup.pub"
FORMAT = "tb-backup-paper/1"
KEY_HEADER = "TRIALBOX BACKUP PRIVATE KEY"  # tools.trialbox.backup.KEY_HEADER (the test checks they match)
LINE_CHARS, CHECK_CHARS, NAME_MAX = 16, 4, 100
LANGS = ("en", "ja", "zh-TW")
DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
PUB_DIR = DEPLOY / "secrets"  # fixed (owner's condition 4): no option names another folder
SYS = Path("/sys")
MOUNTINFO = Path("/proc/self/mountinfo")
SWAPS = Path("/proc/swaps")
DOCKER_SOCK = "/var/run/docker.sock"  # the local daemon only (H-1 of the integrator's review of 36c97bd1)
JOURNAL_WAIT_S = 120  # one `docker compose exec`: a hung daemon stops the step instead of the run hanging
MAX_FILE = 16384  # a key file or a sheet is far smaller; a planted larger file is refused, never read whole

# ------------------------------------------------------------------------------------------------ texts (en, ja, zh-TW)
NOT_ROOT = {
    "en": "refused: the backup-key ceremony is run on the box's host as root, by hospital IT",
    "ja": "拒否：バックアップ鍵の手続きは、病院の情報システム担当がボックスのホストで root として実行します",
    "zh-TW": "已拒絕：備份金鑰儀式須由醫院資訊人員在主機上以 root 身分執行",
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
ALREADY = {
    "en": "refused: the ceremony is done already: {pub} exists (key {fp}). Nothing was changed. A new key pair is the "
    "backup key's rotation (docs/security/10-key-ceremony-and-escrow.md §6), not this command",
    "ja": "拒否：手続きはすでに完了しています：{pub} があります（鍵 {fp}）。何も変更していません。新しい鍵の組は"
    "鍵の更新（docs/security/10-key-ceremony-and-escrow.md §6）で行い、このコマンドでは行いません",
    "zh-TW": "已拒絕：儀式已完成：{pub} 已存在（金鑰 {fp}）。未變更任何內容。新的金鑰組屬於備份金鑰的輪替"
    "（docs/security/10-key-ceremony-and-escrow.md §6），不使用此指令",
}
PUB_DIR_UNSAFE = {
    "en": "refused: the public key's folder {path} is not there, or it or a folder above it is a link, another "
    "account's, or writable by others: nothing was written",
    "ja": "拒否：公開鍵のフォルダー {path} がないか、それかその上のフォルダーがリンク、ほかのアカウントのもの、または"
    "ほかの人が書き込めるものです。何も書いていません",
    "zh-TW": "已拒絕：公開金鑰的資料夾 {path} 不存在，或它或其上層資料夾是連結、屬於其他帳號，或他人可寫入："
    "未寫入任何內容",
}
PUB_ELSEWHERE = {
    "en": "refused: TB_BACKUP_PUBKEY names {path}, but the ceremony puts the public key only at {pub}: remove the "
    "setting first; nothing was written",
    "ja": "拒否：TB_BACKUP_PUBKEY は {path} を指していますが、この手続きは公開鍵を {pub} にだけ置きます。先にこの設定を"
    "外してください。何も書いていません",
    "zh-TW": "已拒絕：TB_BACKUP_PUBKEY 指向 {path}，但此儀式只將公開金鑰放在 {pub}：請先移除此設定；未寫入任何內容",
}
NO_JOURNAL = {
    "en": "refused: this box has no orchestrator audit journal to record the ceremony in (the orchestrator is not "
    "running, it writes the audit itself, or the journal's database does not answer): nothing was written",
    "ja": "拒否：このボックスには手続きを記録するオーケストレーターの監査ジャーナルがありません（オーケストレーターが"
    "動いていないか、監査記録を自分で書く構成か、ジャーナルのデータベースが応答しません）。何も書いていません",
    "zh-TW": "已拒絕：此主機沒有可記錄儀式的協調器稽核日誌（協調器未執行、由它自行寫入稽核紀錄，或日誌的資料庫無"
    "回應）：未寫入任何內容",
}
NO_STICK = {
    "en": "refused: no stick at {path}: insert the stick and name its mounted folder (it is never made here)",
    "ja": "拒否：{path} に USB メモリがありません。USB メモリを差し込み、マウントされたフォルダーを指定してください"
    "（ここでフォルダーは作りません）",
    "zh-TW": "已拒絕：{path} 沒有隨身碟：請插入隨身碟並指定其掛載的資料夾（此處不會建立資料夾）",
}
NOT_A_STICK = {
    "en": "refused: {path} is not on a removable stick of its own (it is on a disk of the box, on a disk that holds "
    "another mounted folder, or its disk cannot be told): the key goes only to a stick; nothing was written",
    "ja": "拒否：{path} は独立した取り外せる USB メモリの上にありません（ボックスのディスク、ほかにマウントされた"
    "フォルダーがあるディスクの上か、ディスクを判別できません）。鍵は USB メモリにだけ書きます。何も書いていません",
    "zh-TW": "已拒絕：{path} 不在獨立的可移除隨身碟上（位於主機的磁碟、另有其他掛載資料夾的磁碟，或無法判別其磁碟）："
    "金鑰只寫入隨身碟；未寫入任何內容",
}
STICK_UNSAFE = {
    "en": "refused: on the stick at {path}, {name} would not be root's alone (the folder is another account's or "
    "others may write in it, or the file is another account's or others may read it): mount the stick with -o "
    "uid=0,gid=0,umask=077,nodev,nosuid,noexec; nothing of the key is in {name}; then run the same command again with "
    "the same stick",
    "ja": "拒否：{path} の USB メモリでは {name} が root だけのものになりません（フォルダーがほかのアカウントのもの"
    "かほかの人が書き込めるか、ファイルがほかのアカウントのものかほかの人が読めます）。-o "
    "uid=0,gid=0,umask=077,nodev,nosuid,noexec でマウントしてください。{name} に鍵は入っていません。その後、同じ "
    "USB メモリで同じコマンドをもう一度実行してください",
    "zh-TW": "已拒絕：在 {path} 的隨身碟上，{name} 不會僅屬 root（資料夾屬於其他帳號或他人可寫入，或檔案屬於其他帳號或"
    "他人可讀取）：請以 -o uid=0,gid=0,umask=077,nodev,nosuid,noexec 掛載隨身碟；{name} 中沒有金鑰內容；之後請用同一"
    "個隨身碟再次執行同一指令",
}
STICK_BROKEN = {
    "en": "refused: this stick cannot finish a ceremony: {name} on it is not a plain file of one name, or not a whole "
    "key, or the two files do not give one key of this box's site. This run wrote nothing to the stick. A key on it "
    "never became the box's key; it stays there until IT wipes the stick. Run the command with an empty stick",
    "ja": "拒否：この USB メモリでは手続きを完了できません：{name} が名前の一つしかない普通のファイルでないか、完全な"
    "鍵でないか、二つのファイルがこのボックスのサイトの同じ鍵になりません。今回の実行は USB メモリに何も書いていま"
    "せん。この USB メモリの鍵がボックスの鍵になったことはありません。情報システム担当が消去するまで残ります。空の "
    "USB メモリで実行してください",
    "zh-TW": "已拒絕：此隨身碟無法完成儀式：其上的 {name} 不是只有一個名稱的一般檔案，或不是完整的金鑰，或兩個檔案不是"
    "此主機站點的同一把金鑰。本次執行未寫入隨身碟任何內容。其上的金鑰從未成為主機的金鑰；它會留在那裡直到資訊人員"
    "抹除隨身碟。請改用空的隨身碟執行",
}
NO_TMPFILE = {
    "en": "refused: the filesystem of {path} cannot make an unnamed file (O_TMPFILE), which step 4 needs: nothing was "
    "written",
    "ja": "拒否：{path} のファイルシステムは名前のないファイル（O_TMPFILE）を作れません。4 段階目に必要です。何も"
    "書いていません",
    "zh-TW": "已拒絕：{path} 的檔案系統無法建立無名稱檔案（O_TMPFILE），第 4 步需要它：未寫入任何內容",
}
BUSY = {
    "en": "refused: another run of the ceremony is going on on this box: nothing was written; wait for it to end",
    "ja": "拒否：このボックスでは別の手続きが実行中です。何も書いていません。終わるまで待ってください",
    "zh-TW": "已拒絕：此主機上另一個儀式正在執行：未寫入任何內容；請等它結束",
}
KEY_EXPOSED = {
    "en": "refused: on the stick at {path}, {name} holds the key and others on this host may read it (another owner "
    "or a wider mode is shown): unmount the stick now, mount it with -o uid=0,gid=0,umask=077,nodev,nosuid,noexec, "
    "then run the same command again with the same stick",
    "ja": "拒否：{path} の USB メモリの {name} には鍵が入っており、このホストのほかの人が読める状態です（ほかの所有者"
    "か広い権限が表示されています）。今すぐ USB メモリをアンマウントし、-o uid=0,gid=0,umask=077,nodev,nosuid,noexec "
    "でマウントしてから、同じ USB メモリで同じコマンドをもう一度実行してください",
    "zh-TW": "已拒絕：在 {path} 的隨身碟上，{name} 含有金鑰，而此主機上的他人可讀取（顯示為其他擁有者或較寬的權限）："
    "請立即卸載隨身碟，以 -o uid=0,gid=0,umask=077,nodev,nosuid,noexec 掛載後，再用同一個隨身碟執行同一指令",
}
STICK_FOREIGN = {
    "en": "refused: this stick holds {name} of a key this box did not make in a ceremony run (no record of it in "
    "{path}): it is never taken as the box's key. This run wrote nothing to the stick. Run the command with an empty "
    "stick; IT wipes this one",
    "ja": "拒否：この USB メモリには、このボックスが手続きの実行で作っていない鍵の {name} があります（{path} に記録が"
    "ありません）。ボックスの鍵として使うことはありません。今回の実行は USB メモリに何も書いていません。空の USB "
    "メモリで実行してください。この USB メモリは情報システム担当が消去します",
    "zh-TW": "已拒絕：此隨身碟上有此主機並未在儀式中建立的金鑰的 {name}（{path} 中沒有其紀錄）：它絕不會成為主機的"
    "金鑰。本次執行未寫入隨身碟任何內容。請改用空的隨身碟執行；此隨身碟由資訊人員抹除",
}
STICK_FAULTY = {
    "en": "refused: {name} on the stick did not read back as written by this run (a faulty stick, or it was changed "
    "meanwhile). What this run wrote stays on the stick; its key never became the box's key and stays there until IT "
    "wipes the stick. backup.pub was not made. Run the command with an empty stick",
    "ja": "拒否：USB メモリの {name} が今回の実行で書いたとおりに読み直せませんでした（USB メモリの故障か、途中で変更"
    "されました）。今回書いたものは USB メモリに残ります。その鍵がボックスの鍵になったことはなく、情報システム担当が"
    "消去するまで残ります。backup.pub は作っていません。空の USB メモリで実行してください",
    "zh-TW": "已拒絕：隨身碟上的 {name} 讀回的內容與本次執行寫入的不同（隨身碟故障，或期間被變更）。本次寫入的內容留在"
    "隨身碟上；其金鑰從未成為主機的金鑰，會留在那裡直到資訊人員抹除隨身碟。未建立 backup.pub。請改用空的隨身碟執行",
}
PUB_TAKEN = {
    "en": "stopped at step 4 of 4: {pub} appeared while this run went on (key {fp}); it was not made by this run and "
    "was not changed. This run's files on the stick and its journal event stay; its key is not the box's key",
    "ja": "4 段階のうち 4 段階目で止まりました：実行中に {pub} が現れました（鍵 {fp}）。今回の実行で作ったものでは"
    "なく、変更もしていません。今回の USB メモリのファイルとジャーナルの記録は残ります。その鍵はボックスの鍵では"
    "ありません",
    "zh-TW": "於 4 個步驟中的第 4 步停止：執行期間出現了 {pub}（金鑰 {fp}）；它不是本次執行建立的，也未被變更。本次在"
    "隨身碟上的檔案與日誌紀錄都會保留；其金鑰不是主機的金鑰",
}
STEP_FAILED = {
    "en": "stopped at step {n} of 4 ({why}): nothing is undone and nothing is deleted; backup.pub was not made. Run "
    "the same command again with the same stick",
    "ja": "4 段階のうち {n} 段階目で止まりました（{why}）。何も取り消さず、何も削除していません。backup.pub は作って"
    "いません。同じ USB メモリで同じコマンドをもう一度実行してください",
    "zh-TW": "於 4 個步驟中的第 {n} 步停止（{why}）：未復原也未刪除任何內容；未建立 backup.pub。請用同一個隨身碟再次"
    "執行同一指令",
}
JOURNAL_UNSURE = {
    "en": "stopped at step 3 of 4: the orchestrator's journal did not confirm the event (it may hold it or not); "
    "backup.pub was not made; nothing is undone. Run the same command again with the same stick (it records the event "
    "again)",
    "ja": "4 段階のうち 3 段階目で止まりました：オーケストレーターのジャーナルが記録を確認しませんでした（記録されて"
    "いるかどうかは分かりません）。backup.pub は作っていません。何も取り消していません。同じ USB メモリで同じ"
    "コマンドをもう一度実行してください（記録をもう一度書きます）",
    "zh-TW": "於 4 個步驟中的第 3 步停止：協調器的日誌未確認此紀錄（可能已記錄，也可能沒有）；未建立 backup.pub；"
    "未復原任何內容。請用同一個隨身碟再次執行同一指令（會再次寫入紀錄）",
}
PUB_UNSURE = {
    "en": "stopped at step 4 of 4: {pub} was made but is not confirmed on disk ({why}). Run the same command again "
    "with the same stick: it says the ceremony is done if {pub} is there, and finishes it if not",
    "ja": "4 段階のうち 4 段階目で止まりました：{pub} は作りましたが、ディスク上で確認できていません（{why}）。同じ "
    "USB メモリで同じコマンドをもう一度実行してください。{pub} があれば完了と表示し、なければ完了させます",
    "zh-TW": "於 4 個步驟中的第 4 步停止：已建立 {pub}，但未確認已寫入磁碟（{why}）。請用同一個隨身碟再次執行同一"
    "指令：若 {pub} 存在會顯示儀式已完成，否則會完成它",
}
STOPPED = {
    "en": "stopped (interrupted): nothing is undone and nothing is deleted. Run the same command again with the same "
    "stick: it finishes the ceremony, or says it is done",
    "ja": "中断されました。何も取り消さず、何も削除していません。同じ USB メモリで同じコマンドをもう一度実行して"
    "ください。手続きを完了させるか、完了済みと表示します",
    "zh-TW": "已中斷：未復原也未刪除任何內容。請用同一個隨身碟再次執行同一指令：它會完成儀式，或顯示已完成",
}
DONE = {
    "en": "done: backup key {fp}. The stick holds {key} and the paper sheet file {paper}, both read back after a sync "
    "as one key; the orchestrator's journal took the event backup.key_ceremony (journal number {seq}) naming "
    "{operator} and the witness {witness}; the box keeps the public key only, at {pub}. Unmount (eject) the stick, "
    "print the sheet, and seal the stick and the paper in hospital IT's envelope. If an earlier run was cut short on "
    "another stick, the key on that stick never became the box's key: it stays there until IT wipes that stick",
    "ja": "完了：バックアップ鍵 {fp}。USB メモリには {key} と紙の控えのファイル {paper} があり、同期の後に読み直して"
    "どちらも同じ鍵でした。{operator} と立会人 {witness} の名前を記した backup.key_ceremony をオーケストレーターの"
    "ジャーナルが受け付けました（ジャーナル番号 {seq}）。ボックスには公開鍵（{pub}）だけが残ります。USB メモリを"
    "アンマウント（取り出し）し、紙の控えを印刷して、USB メモリと紙を病院の情報システム担当の封筒に封をして保管して"
    "ください。以前の実行が別の USB メモリで途中で止まっていた場合、その USB メモリの鍵がボックスの鍵になったことは"
    "ありません。情報システム担当が消去するまで残ります",
    "zh-TW": "完成：備份金鑰 {fp}。隨身碟上有 {key} 與紙本檔案 {paper}，同步後讀回為同一把金鑰；協調器的日誌已接受記有 "
    "{operator} 與見證人 {witness} 的 backup.key_ceremony（日誌編號 {seq}）；主機只保留公開金鑰，位於 {pub}。請卸載"
    "（退出）隨身碟、列印紙本，並將隨身碟與紙本放入醫院資訊人員的信封密封。若先前的執行在另一個隨身碟上中途停止，"
    "該隨身碟上的金鑰從未成為主機的金鑰：它會留在那裡直到資訊人員抹除該隨身碟",
}
HARDEN_FAILED = {
    "en": "refused: this process could not be made safe to hold the key (not dumpable, no core file, and its memory "
    "locked or no swap in use): nothing was written; turn swap off (swapoff -a) or let root lock memory, then run "
    "again",
    "ja": "拒否：このプロセスを鍵を扱える状態にできませんでした（ダンプ不可、コアファイルなし、メモリのロックまたは"
    "スワップ未使用）。何も書いていません。スワップを止める（swapoff -a）か root がメモリをロックできるようにしてから、"
    "もう一度実行してください",
    "zh-TW": "已拒絕：無法讓此程序處於可安全持有金鑰的狀態（不可傾印、無核心檔，且記憶體已鎖定或未使用置換空間）："
    "未寫入任何內容；請關閉置換空間（swapoff -a）或允許 root 鎖定記憶體，然後再執行",
}
NO_PROJECT = {
    "en": "refused: no running orchestrator of this checkout's deploy folder ({path}) was found on the local Docker "
    "daemon, or more than one project claims it: the event would not be known to go to this box's journal; nothing was "
    "written",
    "ja": "拒否：ローカルの Docker でこのチェックアウトの deploy フォルダー（{path}）のオーケストレーターが動いて"
    "いないか、複数のプロジェクトがそれに当たります。記録がこのボックスのジャーナルに届くとは分かりません。何も"
    "書いていません",
    "zh-TW": "已拒絕：在本機 Docker 上找不到此檢出 deploy 資料夾（{path}）正在執行的協調器，或有多個專案符合：無法確定"
    "紀錄會送到此主機的日誌；未寫入任何內容",
}
STICK_IS_BACKUP = {
    "en": "refused: the stick folder {path} is a backup target, inside one, holds one, or is on a backup target's "
    "filesystem ({target}, TB_BACKUP_TARGETS): the key never goes beside the backups it opens; nothing was written",
    "ja": "拒否：USB メモリのフォルダー {path} はバックアップ先そのものか、その中か、それを含むか、バックアップ先と同じ"
    "ファイルシステムの上にあります（{target}、TB_BACKUP_TARGETS）。鍵は、それで開けるバックアップの隣には置きません。"
    "何も書いていません",
    "zh-TW": "已拒絕：隨身碟資料夾 {path} 就是備份目的地、位於其中、包含它，或與備份目的地在同一檔案系統上（{target}，"
    "TB_BACKUP_TARGETS）：金鑰絕不放在它能開啟的備份旁邊；未寫入任何內容",
}
UNEXPECTED = {
    "en": "stopped on an unexpected error ({kind}): nothing is undone and nothing is deleted. Run the same command "
    "again with the same stick",
    "ja": "予期しないエラー（{kind}）で止まりました。何も取り消さず、何も削除していません。同じ USB メモリで同じ"
    "コマンドをもう一度実行してください",
    "zh-TW": "因非預期的錯誤（{kind}）而停止：未復原也未刪除任何內容。請用同一個隨身碟再次執行同一指令",
}
NO_TERMINAL = {
    "en": "refused: the backup key is shown once on a terminal and never written to a log or a file: run this on the "
    "box's terminal, as root (python3 -m tools.backup_key_ceremony --install). Nothing was made",
    "ja": "拒否：バックアップ鍵は端末に一度だけ表示し、ログやファイルには書きません。ボックスの端末で"
    "root として実行してください（python3 -m tools.backup_key_ceremony --install）。何も作成していません",
    "zh-TW": "已拒絕：備份金鑰只在終端機上顯示一次，不寫入任何日誌或檔案：請在主機的終端機上以 root 執行"
    "（python3 -m tools.backup_key_ceremony --install）。未建立任何內容",
}
CONFIRM = {
    "en": "Print or copy the paper copy above and keep it sealed with hospital IT: it is shown only now. Press Enter "
    "when the copy is made: the screen is cleared, then type the copy back from paper, line by line.",
    "ja": "上の紙の控えを印刷または書き写し、病院の情報システム担当が封をして保管してください。表示は今だけです。"
    "控えができたら Enter を押してください。画面を消したあと、紙の控えを一行ずつ入力し直します。",
    "zh-TW": "請列印或抄寫上方的紙本副本，由醫院資訊人員密封保管：只在此時顯示。副本完成後按 Enter：畫面會被清除，"
    "接著請依紙本逐行輸入。",
}
LINE_ASK = {
    "en": "line {n} of {lines}: the letters between the two bars (not shown): ",
    "ja": "{lines} 行中 {n} 行目：二本の縦線の間の文字（表示されません）：",
    "zh-TW": "第 {n} 行（共 {lines} 行）：兩條直線之間的字母（不會顯示）：",
}
RETYPE = {
    "en": "line {n} does not match its check letters on the copy: type it again ({left} more tries)",
    "ja": "{n} 行目が控えの確認用文字と合いません。もう一度入力してください（あと {left} 回）",
    "zh-TW": "第 {n} 行與副本上的檢查字母不符：請再輸入一次（還可再試 {left} 次）",
}
NOT_CONFIRMED = {
    "en": "refused: the copy typed back does not give the key (line {n}). backup.pub was not made, so no backup "
    "uses this key and nothing of it is kept; run the install again for a new key, shown once",
    "ja": "拒否：入力し直した控えから鍵が得られません（{n} 行目）。backup.pub は作成していないため、この鍵を使う"
    "バックアップはなく、鍵は何も残っていません。もう一度インストールを実行すると、新しい鍵を一度だけ表示します",
    "zh-TW": "已拒絕：輸入的副本無法還原金鑰（第 {n} 行）。未建立 backup.pub，因此沒有備份使用此金鑰，也未保留它的任何"
    "內容；請再次執行安裝，以取得只顯示一次的新金鑰",
}
NO_PASSPHRASE = {
    "en": "refused: --sealed-stdin needs the install's KEK passphrase on stdin (one line, 12 characters or more). "
    "Nothing was made",
    "ja": "拒否：--sealed-stdin には標準入力でインストールの KEK パスフレーズ（一行、12 文字以上）が必要です。何も作成"
    "していません",
    "zh-TW": "已拒絕：--sealed-stdin 需要從標準輸入取得安裝的 KEK 密語（一行，12 個字元以上）。未建立任何內容",
}
INSTALLED_SEALED = {
    "en": "backup key made at install: {pub} (key {fp}); the private key is only in {sealed}, sealed under the "
    "install's KEK passphrase: copy that file off the box with hospital IT (it opens only with that passphrase)",
    "ja": "インストール時にバックアップ鍵を作成しました：{pub}（鍵 {fp}）。秘密鍵はインストールの KEK パスフレーズで"
    "封をした {sealed} にだけあります。病院の情報システム担当とこのファイルをボックスの外にコピーしてください（その"
    "パスフレーズでしか開きません）",
    "zh-TW": "已於安裝時建立備份金鑰：{pub}（金鑰 {fp}）；私鑰只存在於以安裝的 KEK 密語密封的 {sealed}：請與醫院資訊"
    "人員將該檔案複製到主機之外（只有該密語能開啟）",
}
NOT_UNSEALED = {
    "en": "refused: {sealed} does not open with this passphrase, or is not a sealed backup key. Nothing was written",
    "ja": "拒否：{sealed} はこのパスフレーズで開けないか、封をしたバックアップ鍵ではありません。何も書いていません",
    "zh-TW": "已拒絕：{sealed} 無法以此密語開啟，或不是密封的備份金鑰。未寫入任何內容",
}
UNSEALED = {
    "en": "the backup key file is {out} (key {fp}): give it to restore --key, then wipe it",
    "ja": "バックアップ鍵ファイルは {out}（鍵 {fp}）です。restore --key に渡し、そのあと消去してください",
    "zh-TW": "備份金鑰檔案為 {out}（金鑰 {fp}）：交給 restore --key，之後請清除",
}
INSTALLED = {
    "en": "backup key made at install: {pub} (key {fp}); the private key is only on the paper copy hospital IT keeps "
    "sealed",
    "ja": "インストール時にバックアップ鍵を作成しました：{pub}（鍵 {fp}）。秘密鍵は病院の情報システム担当が封をして"
    "保管する紙の控えにだけあります",
    "zh-TW": "已於安裝時建立備份金鑰：{pub}（金鑰 {fp}）；私鑰只存在於醫院資訊人員密封保管的紙本副本上",
}
SHEET_HEAD = {
    "en": "TrialBox backup private key, paper copy. It opens every backup of this box: keep it sealed with hospital "
    "IT. To restore from paper: type only the letters between the two bars of each numbered line, one line per line, "
    "into a file, and give that file to restore --key. The four check letters after the second bar let a typed line "
    "be checked by hand; they are not typed.",
    "ja": "TrialBox バックアップ秘密鍵（紙の控え）。このボックスのすべてのバックアップを開ける鍵です。病院の情報"
    "システム担当が封をして保管してください。紙から復元するには、番号の付いた各行の二本の縦線の間の文字だけを、一行"
    "ずつファイルに入力し、そのファイルを restore --key に渡します。二本目の縦線の後の確認用の 4 文字は、入力した行を"
    "手で確かめるためのもので、入力しません。",
    "zh-TW": "TrialBox 備份私密金鑰（紙本）。它能開啟此主機的所有備份：請由醫院資訊人員密封保管。從紙本還原時：只將每個"
    "編號行兩條直線之間的字母逐行輸入到一個檔案，再把該檔案交給 restore --key。第二條直線後的四個檢查字母用於以人工"
    "核對輸入的行，不需輸入。",
}


def lang_of(lang: str | None) -> str:
    low = (lang or "").strip().lower()
    return "ja" if low.startswith("ja") else "zh-TW" if low.startswith("zh") else "en"


def all_texts() -> list[tuple[str, str, str]]:
    """Every text of this module as ``(name, language, text)``."""
    named = {k: v for k, v in globals().items() if k.isupper() and isinstance(v, dict) and set(v) == set(LANGS)}
    return [(name, lg, str(t[lg])) for name, t in sorted(named.items()) for lg in LANGS]


class Stop(Exception):
    """A refusal or a stop (exit 1): one of the texts above and its fields (never a key byte)."""

    def __init__(self, text: Mapping[str, str], **fill: Any) -> None:
        super().__init__(text["en"].format(**fill))
        self.text, self.fill = text, fill

    def say(self, lang: str) -> str:
        return self.text[lang_of(lang)].format(**self.fill)


# ------------------------------------------------------------------------------------------------ the key's two forms
def _check(n: int, letters: str) -> str:
    return base64.b32encode(hashlib.sha256(f"{FORMAT}|{n}|{letters}".encode()).digest()[:5]).decode()[:CHECK_CHARS]


def fingerprint(pub: bytes) -> str:
    h = hashlib.sha256(pub).hexdigest()[:20]  # tools.trialbox.backup.fingerprint (the test checks they match)
    return "-".join(h[i : i + 4] for i in range(0, 20, 4))


def public_of(raw: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    return X25519PrivateKey.from_private_bytes(raw).public_key().public_bytes_raw()


def key_text(raw: bytes) -> bytes:
    """The key file as ``trialbox backup-keygen`` writes it."""
    words = base64.b32encode(raw).decode().rstrip("=")
    groups = " ".join(words[i : i + 4] for i in range(0, len(words), 4))
    fp = fingerprint(public_of(raw))
    return f"-----BEGIN {KEY_HEADER}-----\n{groups}\nfingerprint {fp}\n-----END {KEY_HEADER}-----\n".encode()


def paper_sheet(raw: bytes, site: str, at: str) -> bytes:
    words = base64.b32encode(raw).decode().rstrip("=")
    lines = []
    for n, i in enumerate(range(0, len(words), LINE_CHARS), start=1):
        part = words[i : i + LINE_CHARS]
        lines.append(f"{n} | {' '.join(part[j : j + 4] for j in range(0, len(part), 4))} | {_check(n, part)}")
    head = [f"TRIALBOX BACKUP KEY PAPER {FORMAT}", "", *(SHEET_HEAD[lg] for lg in LANGS), ""]
    meta = [f"site {site or '-'}", f"made {at}", f"fingerprint {fingerprint(public_of(raw))}", f"lines {len(lines)}"]
    return "\n".join([*head, *meta, "", *lines, "", "end", ""]).encode()


def _decoded(letters: str, fp: str) -> bytes | None:
    """32 key bytes from base32 letters whose public key has fingerprint ``fp``, or None (never an error that could
    carry a letter)."""
    try:
        raw = base64.b32decode(letters + "=" * (-len(letters) % 8))
        ok = len(raw) == 32 and fingerprint(public_of(raw)) == fp
    except ValueError:
        return None
    return raw if ok else None


def read_key(data: bytes) -> bytes | None:
    """The key from a key file's bytes, or None (not whole, not the format, or its fingerprint line differs)."""
    lines = data.decode("ascii", "replace").splitlines()
    if len(lines) != 4 or lines[0] != f"-----BEGIN {KEY_HEADER}-----" or lines[3] != f"-----END {KEY_HEADER}-----":
        return None
    if not lines[2].startswith("fingerprint "):  # restore --key skips only lines that start so
        return None
    fp = lines[2].removeprefix("fingerprint ")
    return _decoded("".join(lines[1].split()), fp) if re.fullmatch(r"[A-Z2-7 ]+", lines[1]) else None


def read_sheet(data: bytes) -> tuple[bytes, str] | None:
    """The key and the site from a sheet's bytes: every line's check letters, the order and the fingerprint hold."""
    text, fp, site, letters, want = data.decode("utf-8", "replace"), "", "", "", 1
    for ln in text.splitlines():
        if ln.startswith("fingerprint "):
            fp = ln.removeprefix("fingerprint ")
        elif ln.startswith("site "):
            site = ln.removeprefix("site ")
        elif m := re.fullmatch(r"(\d+) \| ([A-Z2-7 ]+) \| ([A-Z2-7]{4})", ln):
            part = "".join(m.group(2).split())
            if int(m.group(1)) != want or _check(want, part) != m.group(3):
                return None
            letters, want = letters + part, want + 1
    raw = _decoded(letters, fp)
    return (raw, site) if raw is not None else None


# ------------------------------------------------------------------------------------------------ the checks
def harden() -> None:
    """H1: not dumpable (a piped core handler ignores RLIMIT_CORE) and no core; and the memory locked (mlockall, now
    and later), or else no swap on: before any key exists, so no key byte can reach a core file or the swap."""
    import ctypes
    import resource

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(4, 0, 0, 0, 0) != 0 or libc.prctl(3, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE 0; PR_GET_DUMPABLE is 0
        raise OSError(errno.EPERM, "not dumpable")
    if not _lock_memory() and _swap_on():
        raise OSError(errno.ENOMEM, "memory not locked and swap on")


def _lock_memory() -> bool:
    import ctypes

    return int(ctypes.CDLL(None, use_errno=True).mlockall(3)) == 0  # MCL_CURRENT | MCL_FUTURE


def _swap_on() -> bool:
    """Any swap area in use (an unreadable list counts as swap on)."""
    try:
        return len(SWAPS.read_text(encoding="utf-8").strip().splitlines()) > 1
    except OSError:
        return True


def is_root() -> bool:
    return os.geteuid() == 0


def person(name: str | None) -> str:
    n = (name or "").strip()
    if not n:
        raise Stop(NO_NAMES)
    if len(n) > NAME_MAX or any(unicodedata.category(c).startswith("C") for c in n):
        raise Stop(BAD_NAME)
    return n


def folded(name: str) -> str:
    """Two spellings of one name compare equal: NFKC, white space collapsed, case folded."""
    return " ".join(unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", name).casefold()).split())


def _mounts() -> list[tuple[str, str, str]]:
    """``(major:minor, filesystem type, source)`` of every mount this process sees."""
    out = []
    for line in MOUNTINFO.read_text(encoding="utf-8").splitlines():
        f = line.split()
        if "-" in f[6:]:
            i = f.index("-", 6)
            out.append((f[2], f[i + 1], f[i + 2] if len(f) > i + 2 else ""))
    return out


def _block(dev: int) -> int | None:
    """The block device under a filesystem: itself; for an anonymous device (btrfs, a FUSE block filesystem) the block
    node its mount names, only an absolute /dev path and never a ``fuse.*`` filesystem (whose source its user picks)."""
    if os.major(dev) != 0:
        return dev
    for mm, fstype, src in _mounts():
        if mm == f"0:{os.minor(dev)}":
            if (fstype.startswith("fuse") and fstype != "fuseblk") or not src.startswith("/dev/"):
                return None
            try:
                st = os.stat(src)
            except OSError:
                return None
            return st.st_rdev if stat.S_ISBLK(st.st_mode) else None
    return None


def whole_disks(dev: int) -> set[str]:
    """H2: the whole disks a filesystem lives on (a partition's parent; a mapped device's slaves, down to theirs), by
    /sys/class/block; empty when it cannot be told."""
    blk = _block(dev)
    if blk is None:
        return set()
    try:
        return _disks((SYS / "dev" / "block" / f"{os.major(blk)}:{os.minor(blk)}").resolve(strict=True))
    except OSError:
        return set()


def _disks(node: Path) -> set[str]:
    slaves = sorted((node / "slaves").iterdir()) if (node / "slaves").is_dir() else []
    if slaves:
        return set().union(*(_disks(s.resolve(strict=True)) for s in slaves))
    return {(node.parent if (node / "partition").exists() else node).name}


def _removable(disk: str) -> bool:
    node = SYS / "block" / disk
    try:
        return (node / "removable").read_text().strip() == "1" or "/usb" in str(node.resolve(strict=True))
    except OSError:
        return False


def stick_problem(stick_dev: int, box_devs: Sequence[int]) -> bool:
    """Whether a folder on ``stick_dev`` may not take the key: it must be one block device (a disk or a partition of
    one, neither mapped nor a member of a mapped device), its one whole disk known and removable, holding no other
    mounted filesystem (the box's backup disk on USB is not a stick) and none of the box's folders
    (``box_devs``: the system and the public key's folder)."""
    if os.major(stick_dev) == 0:  # no single block device (btrfs, which may span disks, FUSE, a network share)
        return True
    try:
        node = (SYS / "dev" / "block" / f"{os.major(stick_dev)}:{os.minor(stick_dev)}").resolve(strict=True)
        spans = any((node / d).is_dir() and any((node / d).iterdir()) for d in ("slaves", "holders"))
    except OSError:
        return True
    if spans:  # a mapped device (LVM, LUKS, md) or a member of one: more than one device, or another use of it
        return True
    mine = whole_disks(stick_dev)
    if (
        len(mine) != 1
        or not all(_removable(d) for d in mine)
        or any(not (b := whole_disks(d)) or b & mine for d in box_devs)
    ):
        return True
    others = {os.makedev(int(a), int(b)) for a, b in (mm.split(":") for mm, _, _ in _mounts())} - {stick_dev}
    return any(whole_disks(d) & mine for d in others)


def _root_only(st: os.stat_result) -> bool:
    return st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) & 0o022 == 0


def _root_path(path: Path) -> bool:
    """Every folder from / down to ``path`` is no link and is root's (or this user's); none above it is writable by
    others unless sticky, and ``path`` is not writable by others at all."""
    for p in [*reversed(path.parents), path]:
        st = os.lstat(p)
        shared = stat.S_IMODE(st.st_mode) & 0o022 and (p == path or not st.st_mode & stat.S_ISVTX)
        if stat.S_ISLNK(st.st_mode) or st.st_uid not in (0, os.geteuid()) or shared:
            return False
    return True


def _open_dir(path: Path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)


def _env() -> dict[str, str]:
    from tools.trialbox.logs import env_file

    return {**env_file(DEPLOY), **{k: v for k, v in os.environ.items() if k.startswith(("TB_", "COMPOSE_"))}}


# ------------------------------------------------------------------------------------------------ the journal (step 3)
#: the journal's one way in exists and this role may call it (a database without the audit schema is no journal)
HAS_APPEND = (
    "SELECT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
    "WHERE n.nspname = 'audit' AND p.proname = 'append' AND has_function_privilege(p.oid, 'EXECUTE'))"
)
#: run in the orchestrator's container, as audit_heads records ``audit.head_signed``: refuses a file-mode writer;
#: ``check`` opens one connection to the journal's database; ``record`` prints the journal's number for the event
JOURNAL_CODE = (
    "import json, sys\nfrom tb_common.audit_writer import DbAuditWriter, _psycopg, open_audit\nw = open_audit()\n"
    f"HAS_APPEND = {HAS_APPEND!r}\n"
    "if not isinstance(w, DbAuditWriter):\n    sys.exit(3)\n"
    "if sys.argv[1:2] == ['record']:\n"
    "    rec = w.append(sys.argv[2], actor=sys.argv[3], detail=json.loads(sys.argv[4]))\n"
    "    print('journal', int(rec['journal']['seq']))\n"
    "else:\n    con = _psycopg().connect(w._dsn, connect_timeout=10)\n"
    "    ok = con.execute(HAS_APPEND).fetchone()[0]\n    con.close()\n    print('journal ok' if ok else 'no journal')\n"
)
#: the command that reaches the orchestrator: fixed, never taken from the environment or deploy/.env (tests set it)
COMPOSE: list[str] | None = None


def _docker_env(config: str) -> dict[str, str]:
    """The environment of the call: this process's, without any Docker or Compose setting (a context, a host, TLS, a
    config naming another box), the local daemon's socket named, and an empty Docker config folder."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DOCKER_", "COMPOSE_"))}
    return {**env, "DOCKER_HOST": f"unix://{DOCKER_SOCK}", "DOCKER_CONFIG": config}


def local_compose(project: str) -> list[str]:
    """``docker compose`` of this box's deploy folder and project, on the local daemon's socket."""
    return ["docker", "-H", f"unix://{DOCKER_SOCK}", "compose", "--project-directory", str(DEPLOY), "-p", project]


def project_of(listing: str, deploy: Path) -> str | None:
    """The one compose project whose orchestrator was started from ``deploy`` (``docker ps`` lines of project and
    working folder), or None: none, or more than one. Never a name from the environment."""
    names = {p for p, _, wd in (ln.partition("\t") for ln in listing.splitlines()) if p and wd == str(deploy)}
    return names.pop() if len(names) == 1 else None


def _local_socket() -> bool:
    """The local Docker daemon's socket is there and is root's."""
    try:
        st = os.stat(DOCKER_SOCK)
    except OSError:
        return False
    return stat.S_ISSOCK(st.st_mode) and st.st_uid == 0


def _project() -> str | None:
    """This checkout's compose project, from the local daemon's running orchestrators (H-3 of the second review)."""
    fmt = '{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.project.working_dir"}}'
    argv = ["docker", "-H", f"unix://{DOCKER_SOCK}", "ps", "--filter", "label=com.docker.compose.service=orchestrator",
            "--format", fmt]  # fmt: skip
    try:
        if not _local_socket():
            return None
        with tempfile.TemporaryDirectory(prefix="tb-ceremony-docker-") as config:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=JOURNAL_WAIT_S, check=False,
                               env=_docker_env(config))  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return None
    return project_of(r.stdout, DEPLOY.resolve()) if r.returncode == 0 else None


def _journal(*args: str) -> str:
    """What the orchestrator printed (its last line), or "" when it failed, timed out or could not be started. Only
    the local daemon is asked (its socket root's), never a context or host the environment names."""
    project = None if COMPOSE else _project()
    if COMPOSE is None and project is None:
        return ""
    call = COMPOSE or local_compose(project or "")
    argv = [*call, "exec", "-T", "orchestrator", "python", "-c", JOURNAL_CODE, *args]
    try:
        if COMPOSE is None and not _local_socket():
            return ""
        with tempfile.TemporaryDirectory(prefix="tb-ceremony-docker-") as config:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=JOURNAL_WAIT_S, check=False,
                               env=_docker_env(config))  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return ""
    lines = r.stdout.strip().splitlines()
    return lines[-1] if r.returncode == 0 and lines else ""


def record(detail: Mapping[str, str]) -> int:
    """Step 3: the event through the journal; its number in the journal, which only a stored event has."""
    said = _journal("record", EVENT, ACTOR, json.dumps(dict(detail), ensure_ascii=False))
    if not (m := re.fullmatch(r"journal ([1-9][0-9]*)", said)):
        raise Stop(JOURNAL_UNSURE)
    return int(m.group(1))


# ------------------------------------------------------------------------------------------------ files, by descriptor
def _why(e: OSError) -> str:
    return errno.errorcode.get(e.errno or 0, "OSError")


def _sync_dir(dfd: int, n: int) -> None:
    """M6: a folder's sync that fails, whatever the errno (EINVAL and ENOTSUP included), stops the step."""
    try:
        os.fsync(dfd)
    except OSError as e:
        raise Stop(STEP_FAILED, n=n, why=_why(e)) from None


def _safe(fd: int, dev: int, name: str, path: Path) -> os.stat_result:
    """A stick file is a plain file of one name on the stick's filesystem, root's alone, not larger than a sheet."""
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_dev != dev or st.st_size > MAX_FILE:
        raise Stop(STICK_BROKEN, name=name)
    if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) & 0o077:
        raise Stop(KEY_EXPOSED if st.st_size else STICK_UNSAFE, path=path, name=name)
    return st


def _size(dfd: int, name: str) -> int | None:
    """The size of ``name`` on the stick (None: not there), looked at without following it; not a plain file:
    refused before it is opened."""
    try:
        st = os.stat(name, dir_fd=dfd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode):
        raise Stop(STICK_BROKEN, name=name)
    return st.st_size


def _open_on_stick(dfd: int, name: str, create: bool) -> int:
    if not create:
        _size(dfd, name)
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | (os.O_CREAT | os.O_EXCL if create else 0)
    try:
        return os.open(name, flags, 0o600, dir_fd=dfd)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.ENXIO, errno.EISDIR):
            raise Stop(STICK_BROKEN, name=name) from None
        raise


def _temp(dfd: int, name: str, dev: int, path: Path) -> tuple[int, str]:
    """A new temporary name beside ``name`` (``.<name>.<random>.part``, O_EXCL), checked as :func:`_safe` while it
    is empty; returns its descriptor and the name. A run cut short leaves it: never removed, never read again."""
    tmp = f".{name}.{secrets.token_hex(4)}.part"
    fd = _open_on_stick(dfd, tmp, create=True)
    try:
        _safe(fd, dev, name, path)
    except BaseException:
        os.close(fd)
        raise
    return fd, tmp


def _read(fd: int) -> bytes:
    """The file from the device where the kernel allows: its clean cached pages dropped first (A-M3)."""
    os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    return os.pread(fd, MAX_FILE + 1, 0)


def _write_temp(fd: int, data: bytes, name: str) -> int:
    """``data`` written whole into the temporary file, synced, and read back from the same descriptor; its inode."""
    done = 0
    while done < len(data):
        done += os.write(fd, data[done:])
    os.fsync(fd)
    if _read(fd) != data:  # read back from the same descriptor
        raise Stop(STICK_FAULTY, name=name)
    return os.fstat(fd).st_ino


def _rename_into(dfd: int, tmp: str, name: str) -> None:
    """The temporary file given its final name (one rename in the folder held open; the folder lock keeps the name
    free): a final name never holds a part of a file."""
    os.rename(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)


def _put(dfd: int, name: str, dev: int, path: Path, make: Any) -> tuple[int, bytes | None]:
    """``name`` written as ``make()`` by way of a temporary name, when it is not there; a name already there (a run
    cut short after its rename) is kept as it is, and synced again on this run. Returns the inode and what this run
    wrote."""
    if _size(dfd, name) is None:
        fd, tmp = _temp(dfd, name, dev, path)
        try:
            data = make()
            ino = _write_temp(fd, data, name)
        finally:
            os.close(fd)
        _rename_into(dfd, tmp, name)
        return ino, data
    fd = _open_on_stick(dfd, name, create=False)
    try:
        st = _safe(fd, dev, name, path)
        os.fsync(fd)  # a rerun never trusts the cache of a run cut short
        return st.st_ino, None
    finally:
        os.close(fd)


def _read_back(dfd: int, name: str, dev: int, path: Path, ino: int | None) -> bytes:
    """The file opened again through the stick's folder; with ``ino``, it must be that inode."""
    fd = _open_on_stick(dfd, name, create=False)
    try:
        st = _safe(fd, dev, name, path)
        if ino is not None and st.st_ino != ino:
            raise Stop(STICK_FAULTY, name=name)
        return _read(fd)
    finally:
        os.close(fd)


def _new_file(pfd: int, name: str | None, data: bytes, mode: int = 0o644) -> int:
    """A file of ``data`` in the public key's folder, ``mode`` (0644) whatever the umask, written whole and synced:
    unnamed (O_TMPFILE) when ``name`` is None, else made new under ``name`` (O_EXCL). Returns the open descriptor."""
    if name is None:
        fd = os.open(".", os.O_WRONLY | os.O_TMPFILE | os.O_CLOEXEC, 0o600, dir_fd=pfd)
    else:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=pfd)
    try:
        os.fchmod(fd, mode)
        if os.write(fd, data) != len(data):
            raise OSError(errno.EIO, "short write")
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        raise
    return fd


def pending_name(fp: str) -> str:
    return f"backup-ceremony-{fp}.pending"


def _pending(pfd: int, pub: bytes) -> None:
    """A-H1: before the stick holds a new key, its record on the box (fingerprint and public key; never removed); a
    key file on a stick is taken up again only when its record is here."""
    fp = fingerprint(pub)
    text = f"fingerprint {fp}\npublic {base64.b64encode(pub).decode()}\nmade {datetime.now(UTC).isoformat()}\n"
    os.close(_new_file(pfd, pending_name(fp), text.encode()))
    _sync_dir(pfd, 1)


def _link_pub(pfd: int, pub: bytes) -> None:
    """Step 4: backup.pub made new, never over a name, never seen half written: an unnamed synced file given its name
    by a link, which fails when the name exists, as O_EXCL does. Every error here comes before the name exists."""
    fd = _new_file(pfd, None, (base64.b64encode(pub).decode() + "\n").encode())
    try:
        os.link(f"/proc/self/fd/{fd}", PUB_NAME, dst_dir_fd=pfd, follow_symlinks=True)
    finally:
        os.close(fd)


def _pub_fp(pfd: int) -> str:
    try:
        fd = os.open(PUB_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=pfd)
        try:
            return fingerprint(base64.b64decode(os.read(fd, 4096).strip(), validate=True))
        finally:
            os.close(fd)
    except (OSError, ValueError):
        return "unreadable"


def _exists(dfd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=dfd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def new_key() -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    enc, fmt = serialization.Encoding.Raw, serialization.PrivateFormat.Raw
    return X25519PrivateKey.generate().private_bytes(enc, fmt, serialization.NoEncryption())


def _libs() -> None:
    if str(DEPLOY.parent / "libs") not in sys.path:
        sys.path.insert(0, str(DEPLOY.parent / "libs"))  # the host's python3 (rc1_refusals: standard library)


# ------------------------------------------------------------------------------------------------ the ceremony
def run(stick: Path, operator: str | None, witness: str | None, env: Mapping[str, str]) -> dict[str, str]:
    """The checks (nothing written when one refuses), then the four steps; returns what the journal holds."""
    if not is_root():
        raise Stop(NOT_ROOT)
    _libs()
    from tb_common import rc1_refusals

    try:  # R22-34 (D-1072): rc1 holds no backup key ceremony on a PRODUCTION box; nothing is generated
        rc1_refusals.check("key_ceremonies", rc1_refusals.host_env(DEPLOY, env))  # the stricter of the two
    except rc1_refusals.Rc1Refused as exc:
        raise Stop(rc1_refusals.TEXTS[exc.refusal.key], environment=exc.environment) from None
    who, wit = person(operator), person(witness)
    if folded(who) == folded(wit):
        raise Stop(SAME_PERSON)
    pfd = _open_pub(env)
    try:
        try:
            sfd = _open_dir(stick)
        except OSError:
            raise Stop(NO_STICK, path=stick) from None
        try:
            return _steps(sfd, pfd, stick, who, wit, env)
        finally:
            os.close(sfd)
    finally:
        os.close(pfd)


def _open_pub(env: Mapping[str, str]) -> int:
    """The public key's folder, root's alone, locked for the whole run (A-M1), without ``backup.pub`` ("once" is
    backup.pub, owner's condition 2), able to make an unnamed file, with the journal answering: its open descriptor,
    which the caller closes. Nothing is written here."""
    pub_path = PUB_DIR / PUB_NAME
    if (named := env.get("TB_BACKUP_PUBKEY")) and os.path.abspath(named) != os.path.abspath(pub_path):
        raise Stop(PUB_ELSEWHERE, path=named, pub=pub_path)
    try:
        if not _root_path(PUB_DIR):
            raise OSError(errno.EPERM, "not root's")
        pfd = _open_dir(PUB_DIR)
    except OSError:
        raise Stop(PUB_DIR_UNSAFE, path=PUB_DIR) from None
    try:
        if not _root_only(os.fstat(pfd)):
            raise Stop(PUB_DIR_UNSAFE, path=PUB_DIR)
        try:
            fcntl.flock(pfd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # one run at a time, for the whole run (A-M1)
        except BlockingIOError:
            raise Stop(BUSY) from None
        if _exists(pfd, PUB_NAME):  # "once" is backup.pub (owner's condition 2)
            raise Stop(ALREADY, pub=pub_path, fp=_pub_fp(pfd))
        try:
            os.close(os.open(".", os.O_WRONLY | os.O_TMPFILE | os.O_CLOEXEC, 0o600, dir_fd=pfd))
        except OSError:
            raise Stop(NO_TMPFILE, path=PUB_DIR) from None
        if COMPOSE is None and not _local_socket():
            raise Stop(NO_JOURNAL)
        if COMPOSE is None and _project() is None:
            raise Stop(NO_PROJECT, path=DEPLOY)
        if _journal("check") != "journal ok":
            raise Stop(NO_JOURNAL)
    except BaseException:
        os.close(pfd)
        raise
    return pfd


def _on_stick(sfd: int, pfd: int, dev: int, stick: Path, site: str, step: list[int]) -> bytes:
    """Steps 1 and 2; returns the public key. Step 1: a stick with no key file and no sheet gets a new key, recorded
    on the box first and written by way of a temporary name; a whole key file is taken up again (and synced again)
    only when the box holds its record. Then the sheet from that key, the same way. Step 2: both read back through the
    folder held open: one key, of this box's site."""
    k_wrote: bytes | None = None
    if _size(sfd, KEY_FILE) is None:
        if _size(sfd, PAPER_FILE) is not None:
            raise Stop(STICK_FOREIGN, name=PAPER_FILE, path=PUB_DIR)
        fd, tmp = _temp(sfd, KEY_FILE, dev, stick)  # checked before any key exists
        try:
            key = new_key()
            _pending(pfd, public_of(key))
            text = key_text(key)
            k_ino, k_wrote = _write_temp(fd, text, KEY_FILE), text
        finally:
            os.close(fd)
        _rename_into(sfd, tmp, KEY_FILE)
    else:
        k_ino = _put(sfd, KEY_FILE, dev, stick, None)[0]  # synced again; read below
        found = read_key(_read_back(sfd, KEY_FILE, dev, stick, k_ino))
        if found is None:
            raise Stop(STICK_BROKEN, name=KEY_FILE)
        if not _exists(pfd, pending_name(fingerprint(public_of(found)))):
            raise Stop(STICK_FOREIGN, name=KEY_FILE, path=PUB_DIR)
        key = found
    sheet_of = functools.partial(paper_sheet, key, site, datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"))
    p_ino, p_wrote = _put(sfd, PAPER_FILE, dev, stick, sheet_of)
    _sync_dir(sfd, 1)
    step[0] = 2
    bad = STICK_FAULTY if k_wrote or p_wrote else STICK_BROKEN
    data = _read_back(sfd, KEY_FILE, dev, stick, k_ino)
    if (k_wrote is not None and data != k_wrote) or read_key(data) != key:
        raise Stop(bad, name=KEY_FILE)
    data = _read_back(sfd, PAPER_FILE, dev, stick, p_ino)
    if (p_wrote is not None and data != p_wrote) or read_sheet(data) != (key, site or "-"):
        raise Stop(bad, name=PAPER_FILE)
    return public_of(key)


def backup_target(here: str, sst: os.stat_result, env: Mapping[str, str]) -> str | None:
    """The TB_BACKUP_TARGETS folder the stick's folder is, is inside, holds, or shares a filesystem with (by real
    path and by device), or None (H-2 of the second review)."""
    for raw in (env.get("TB_BACKUP_TARGETS") or "").replace(",", " ").split():
        target = raw.strip("\"'")
        real = os.path.realpath(target)
        try:
            same_fs = os.stat(real).st_dev == sst.st_dev
        except OSError:
            same_fs = False
        if same_fs or os.path.commonpath([here, real]) in (here, real):
            return target
    return None


def _steps(sfd: int, pfd: int, stick: Path, who: str, wit: str, env: Mapping[str, str]) -> dict[str, str]:
    sst = os.fstat(sfd)
    if (target := backup_target(os.path.realpath(f"/proc/self/fd/{sfd}"), sst, env)) is not None:
        raise Stop(STICK_IS_BACKUP, path=stick, target=target)
    if stick_problem(sst.st_dev, [os.stat("/").st_dev, os.fstat(pfd).st_dev]):
        raise Stop(NOT_A_STICK, path=stick)
    if not _root_only(sst):
        raise Stop(STICK_UNSAFE, path=stick, name=KEY_FILE)
    site, step = env.get("TB_SITE_ID") or "", [1]
    try:
        pub = _on_stick(sfd, pfd, sst.st_dev, stick, site, step)  # steps 1 and 2; the private key goes out of scope
    except OSError as e:
        raise Stop(STEP_FAILED, n=step[0], why=_why(e)) from None
    fp = fingerprint(pub)
    detail = {"fingerprint": fp, "operator": who, "witness": wit, "site": site,
              "stick": "key file and sheet file read back after sync"}  # fmt: skip
    seq = record(detail)  # step 3
    _pub_last(pfd, pub)  # step 4
    return {**detail, "pub": str(PUB_DIR / PUB_NAME), "seq": str(seq)}


def _pub_last(pfd: int, pub: bytes) -> None:
    """Step 4: backup.pub made new, synced and read back."""
    try:
        _link_pub(pfd, pub)
    except FileExistsError:
        raise Stop(PUB_TAKEN, pub=PUB_DIR / PUB_NAME, fp=_pub_fp(pfd)) from None
    except OSError as e:
        raise Stop(STEP_FAILED, n=4, why=_why(e)) from None
    try:
        os.fsync(pfd)
        if _pub_fp(pfd) != fingerprint(pub):
            raise OSError(errno.EIO, "read back")
    except OSError as e:
        raise Stop(PUB_UNSURE, pub=PUB_DIR / PUB_NAME, why=_why(e)) from None


CLEAR = "\033[H\033[2J\033[3J"  # the screen and its scroll-back: the key was shown once
TRIES = 3  # a line typed wrong from paper may be typed again; its check letters say so, never the key
SEALED_FORMAT = "tb-backup-key-sealed/1"
PASSPHRASE_MIN = 12  # deploy/install.sh's KEK passphrase rule


@contextlib.contextmanager
def _unseen(tty: TextIO) -> Iterator[None]:
    """The copy typed back is not echoed on a terminal (a stand-in without terminal settings is left as it is)."""
    try:
        fd = tty.fileno()
        old = termios.tcgetattr(fd)
    except (AttributeError, OSError, ValueError, termios.error):
        yield
        return
    new = list(old)
    new[3] &= ~termios.ECHO
    termios.tcsetattr(fd, termios.TCSADRAIN, new)
    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def install(env: Mapping[str, str], ask: TextIO, show: TextIO, lang: str = "en") -> dict[str, str]:
    """The key made at install on a terminal (see the module docstring): shown once on ``show``, the screen cleared,
    then the whole paper copy typed back on ``ask`` (H-01: proof that the copy kept gives the key back, as
    ``restore --key`` reads it), then the journal's event and ``backup.pub``. Returns what the journal holds."""
    if not is_root():
        raise Stop(NOT_ROOT)
    lg = lang_of(lang)
    pfd = _open_pub(env)
    try:
        site = env.get("TB_SITE_ID") or ""
        key = new_key()
        pub = public_of(key)
        fp = fingerprint(pub)
        _pending(pfd, pub)  # as step 1: the box keeps the public half's record, never the key
        sheet = paper_sheet(key, site, datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")).decode()
        checks = re.findall(r"^\d+ \| [A-Z2-7 ]+ \| ([A-Z2-7]{4})$", sheet, re.M)
        try:  # M-01: whatever stops this, the screen and its scroll-back are cleared
            show.write(f"{sheet}\n{key_text(key).decode()}\n")
            del key, sheet  # L-03: from here only the check letters and the fingerprint are held
            show.write(CONFIRM[lg] + "\n")
            show.flush()
            ask.readline()
            show.write(CLEAR)
            show.flush()
            letters = ""
            with _unseen(ask):
                for n, check in enumerate(checks, start=1):
                    for left in range(TRIES - 1, -1, -1):
                        show.write(LINE_ASK[lg].format(n=n, lines=len(checks)))
                        show.flush()
                        part = "".join(ask.readline().split()).upper()
                        show.write("\n")
                        if _check(n, part) == check:
                            break
                        if not left:
                            raise Stop(NOT_CONFIRMED, n=n)
                        show.write(RETYPE[lg].format(n=n, left=left) + "\n")
                    letters += part
            if _decoded(letters, fp) is None:  # every line held its check letters: the key itself must come back
                raise Stop(NOT_CONFIRMED, n=len(checks))
            del letters
        finally:
            show.write(CLEAR)
            show.flush()
        detail = {"fingerprint": fp, "operator": "install", "witness": "none: made at install, shown once",
                  "site": site, "stick": "none: the paper copy was shown once on the install's terminal and typed "
                  "back whole"}  # fmt: skip
        seq = record(detail)
        _pub_last(pfd, pub)
        return {**detail, "pub": str(PUB_DIR / PUB_NAME), "seq": str(seq)}
    finally:
        os.close(pfd)


def sealed_name(fp: str) -> str:
    return f"backup-key-{fp}.sealed"


def unseal(data: bytes, passphrase: str) -> bytes | None:
    """The key of a sealed file's bytes under ``passphrase``, or None (another passphrase, damaged, not the format;
    never an error that could carry a byte of it)."""
    _libs()
    from tb_common import kek

    try:
        doc = json.loads(data)
        if doc.get("format") != SEALED_FORMAT:
            return None
        wrapped = doc["key"]
        raw = kek.unwrap(kek.derive_from_passphrase(passphrase, doc["kdf"]), wrapped, str(wrapped["name"]))
    except (ValueError, KeyError, TypeError, AttributeError, kek.KekError):
        return None
    return raw if len(raw) == 32 and fingerprint(public_of(raw)) == doc.get("fingerprint") else None


def install_sealed(env: Mapping[str, str], passphrase: str) -> dict[str, str]:
    """The key made at an unattended install (see the module docstring): sealed under the install's KEK passphrase
    (scrypt, a new salt, the parameters recorded) into ``backup-key-<fp>.sealed``, opened again, then the journal's
    event and ``backup.pub``. Returns what the journal holds and the sealed file's path."""
    if not is_root():
        raise Stop(NOT_ROOT)
    if len(passphrase) < PASSPHRASE_MIN:
        raise Stop(NO_PASSPHRASE)
    _libs()
    from tb_common import kek

    pfd = _open_pub(env)
    try:
        site = env.get("TB_SITE_ID") or ""
        key = new_key()
        pub = public_of(key)
        fp = fingerprint(pub)
        name = sealed_name(fp)
        _pending(pfd, pub)  # as step 1
        params = kek.passphrase_params()
        doc = {"format": SEALED_FORMAT, "fingerprint": fp, "public": base64.b64encode(pub).decode(),
               "kdf": {"name": "scrypt", **params},
               "key": kek.wrap(kek.derive_from_passphrase(passphrase, params), key, name)}  # fmt: skip
        del key
        try:
            os.close(_new_file(pfd, name, (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode(), 0o600))
            _sync_dir(pfd, 1)
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=pfd)
            try:
                back = _read(fd)
            finally:
                os.close(fd)
        except OSError as e:
            raise Stop(STEP_FAILED, n=1, why=_why(e)) from None
        if (raw := unseal(back, passphrase)) is None or public_of(raw) != pub:  # read back: it opens to this key
            raise Stop(STEP_FAILED, n=1, why="read back")
        del raw
        detail = {"fingerprint": fp, "operator": "install", "witness": "none: made at an unattended install",
                  "site": site, "stick": f"none: sealed under the install's KEK passphrase ({name})"}  # fmt: skip
        seq = record(detail)
        _pub_last(pfd, pub)
        return {**detail, "pub": str(PUB_DIR / PUB_NAME), "seq": str(seq), "sealed": str(PUB_DIR / name)}
    finally:
        os.close(pfd)


def unseal_to(sealed: Path, out: Path, passphrase: str) -> str:
    """``--unseal``: the key file ``restore --key`` reads, made new at ``out`` (0600), from a sealed file and its
    passphrase; the key's fingerprint."""
    try:
        data = sealed.read_bytes()[: MAX_FILE + 1]
    except OSError:
        data = b""
    raw = unseal(data, passphrase) if passphrase else None
    if raw is None:
        raise Stop(NOT_UNSEALED, sealed=sealed)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key_text(raw))
    return fingerprint(public_of(raw))


def main(argv: Sequence[str] | None = None) -> int:
    try:
        harden()  # H1: first, before any key material exists
    except OSError:  # the language is not known yet: all three
        print("\n".join(HARDEN_FAILED[lg] for lg in LANGS), file=sys.stderr)
        return 1
    ap = argparse.ArgumentParser(prog="python -m tools.backup_key_ceremony", description=__doc__.split("\n")[0])
    how = ap.add_mutually_exclusive_group(required=True)
    how.add_argument("--stick", help="the mounted folder of the removable stick")
    how.add_argument("--install", action="store_true", help="at install: the key shown once on this terminal (P-01)")
    how.add_argument("--unseal", help="a backup-key-<fp>.sealed file: the key file for restore --key (with --out)")
    ap.add_argument("--sealed-stdin", action="store_true",
                    help="with --install, unattended: sealed under the KEK passphrase read from stdin")  # fmt: skip
    ap.add_argument("--out", help="with --unseal: the key file to make (new)")
    ap.add_argument("--operator", help="the person who runs the ceremony (hospital IT)")
    ap.add_argument("--witness", help="the witness: another person")
    ap.add_argument("--lang", help="en (the default), ja or zh-TW")
    a = ap.parse_args(argv)
    lang = lang_of(a.lang)
    if a.sealed_stdin and not a.install:
        ap.error("--sealed-stdin goes with --install")
    if a.unseal:
        if not a.out:
            ap.error("--unseal needs --out")
        pp = _stdin_line()
        fp = _guarded(lang, lambda: unseal_to(Path(a.unseal), Path(a.out), pp))
        if fp is None:
            return 1
        print(UNSEALED[lang].format(out=a.out, fp=fp))
        return 0
    if a.install:
        return _install_main(lang, a.sealed_stdin)
    try:
        rec = run(Path(a.stick), a.operator, a.witness, _env())
    except Stop as e:
        print(e.say(lang), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(STOPPED[lang], file=sys.stderr)
        return 1
    except Exception as e:  # the type only: a message could hold anything
        print(UNEXPECTED[lang].format(kind=type(e).__name__), file=sys.stderr)
        return 1
    print(DONE[lang].format(fp=rec["fingerprint"], key=KEY_FILE, paper=PAPER_FILE, operator=rec["operator"],
                            witness=rec["witness"], pub=rec["pub"], seq=rec["seq"]))  # fmt: skip
    return 0


TTY = "/dev/tty"


def _guarded[T](lang: str, call: Callable[[], T]) -> T | None:
    """``call()``, or None once its refusal or stop is said on stderr (an unexpected error by its type only: a
    message could hold anything)."""
    try:
        return call()
    except Stop as e:
        print(e.say(lang), file=sys.stderr)
    except KeyboardInterrupt:
        print(STOPPED[lang], file=sys.stderr)
    except Exception as e:
        print(UNEXPECTED[lang].format(kind=type(e).__name__), file=sys.stderr)
    return None


def _stdin_line() -> str:
    """One line of stdin, its line end taken off (the passphrase: never an argument or the environment)."""
    return sys.stdin.readline().rstrip("\r\n")


def _install_main(lang: str, sealed: bool = False) -> int:
    """``--install``: the terminal is ``/dev/tty``, never the standard output (an install's output may be piped into
    a log), opened once to read and once to write (it cannot be opened ``r+``: not seekable); no terminal, nothing
    is made. ``--sealed-stdin``: no terminal, the passphrase on stdin."""
    if sealed:
        pp = _stdin_line()
        rec = _guarded(lang, lambda: install_sealed(_env(), pp))
        del pp
        if rec is None:
            return 1
        print(INSTALLED_SEALED[lang].format(fp=rec["fingerprint"], pub=rec["pub"], sealed=rec["sealed"]))
        return 0
    try:
        with open(TTY, encoding="utf-8") as ask, open(TTY, "w", encoding="utf-8") as show:
            got = _guarded(lang, lambda: install(_env(), ask, show, lang))
    except OSError:  # no terminal to open: nothing was made
        print(NO_TERMINAL[lang], file=sys.stderr)
        return 1
    if got is None:
        return 1
    print(INSTALLED[lang].format(fp=got["fingerprint"], pub=got["pub"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
