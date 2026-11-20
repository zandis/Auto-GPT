"""``python -m tools.backup_key_ceremony`` (10K-13, D-1379): the backup-key ceremony on the box's host.

    python -m tools.backup_key_ceremony --stick /media/usb --operator "<name>" --witness "<name>" [--lang ja]

Hospital IT, as root on the box's host, with a witness who is another person, makes the box's backup key. Four steps,
each resumable, none undone, nothing ever deleted (D-1379, the owner's four conditions of 2026-11-20):

1. **the stick**: the key is made in memory and written to the stick named, as ``trialbox-backup.key`` (the format
   ``trialbox backup-keygen`` writes; ``restore --key`` reads it) and ``trialbox-backup-key-paper.txt`` (the sheet to
   print: the key in lines of four-letter groups, each line with four check letters, and the key's fingerprint);
2. **read back**: both files are read again from the stick and must give one and the same key;
3. **the journal**: the event ``backup.key_ceremony`` (the fingerprint and both names, never the key) goes through the
   orchestrator's audit journal, as ``trialbox audit-sign`` records its event (root writes nothing in the audit
   folder);
4. **backup.pub**: only then the public key at ``deploy/secrets/backup.pub``, made new (never over a file), last.

"Once" means ``backup.pub`` exists: then the command says the ceremony is done and changes nothing. A run cut short
is finished by the same command with the same stick: a stick that holds a whole key file goes on from step 2 with that
key. A key from an abandoned run (the command run again with another, empty stick) stays on its stick, never the
box's key, until IT wipes it. The command refuses on a box with no orchestrator journal, and the public key's folder
is fixed (``deploy/secrets`` of this checkout) and must be root's alone. Every file on the stick is opened through
the stick's folder held open, never through a link, and must be a plain file of root's alone, one name, on that
folder's filesystem. The process is made not dumpable and without a core before any key exists; no key byte is put in
an argument, the environment, an exception, a log or the journal.
"""

from __future__ import annotations

import argparse
import base64
import errno
import functools
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
JOURNAL_WAIT_S = 120  # one `docker compose exec`: a hung daemon stops the step instead of the run hanging
RERUN = "rerun"

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
    "backup key's rotation (RUNBOOK §25), not this command",
    "ja": "拒否：手続きはすでに完了しています：{pub} があります（鍵 {fp}）。何も変更していません。新しい鍵の組は"
    "鍵の更新（RUNBOOK §25）で行い、このコマンドでは行いません",
    "zh-TW": "已拒絕：儀式已完成：{pub} 已存在（金鑰 {fp}）。未變更任何內容。新的金鑰組屬於備份金鑰的輪替"
    "（RUNBOOK §25），不使用此指令",
}
PUB_DIR_UNSAFE = {
    "en": "refused: the public key's folder {path} is not there, or not root's alone (owned by root, written by no "
    "one else): nothing was written",
    "ja": "拒否：公開鍵のフォルダー {path} がないか、root だけのものではありません（所有者が root で、ほかの誰も書き"
    "込めないこと）。何も書いていません",
    "zh-TW": "已拒絕：公開金鑰的資料夾 {path} 不存在，或不是僅屬 root（須由 root 擁有且他人不可寫入）：未寫入任何內容",
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
    "running, or it writes the audit itself): nothing was written",
    "ja": "拒否：このボックスには手続きを記録するオーケストレーターの監査ジャーナルがありません（オーケストレーターが"
    "動いていないか、監査記録を自分で書く構成です）。何も書いていません",
    "zh-TW": "已拒絕：此主機沒有可記錄儀式的協調器稽核日誌（協調器未執行，或由它自行寫入稽核紀錄）：未寫入任何內容",
}
NO_STICK = {
    "en": "refused: no stick at {path}: insert the stick and name its mounted folder (it is never made here)",
    "ja": "拒否：{path} に USB メモリがありません。USB メモリを差し込み、マウントされたフォルダーを指定してください"
    "（ここでフォルダーは作りません）",
    "zh-TW": "已拒絕：{path} 沒有隨身碟：請插入隨身碟並指定其掛載的資料夾（此處不會建立資料夾）",
}
NOT_A_STICK = {
    "en": "refused: {path} is not on a removable stick of its own (it is on a disk of the box, or its disk cannot be "
    "told): the key goes only to a stick; nothing was written",
    "ja": "拒否：{path} は独立した取り外せる USB メモリの上にありません（ボックスのディスクの上か、ディスクを判別できま"
    "せん）。鍵は USB メモリにだけ書きます。何も書いていません",
    "zh-TW": "已拒絕：{path} 不在獨立的可移除隨身碟上（位於主機的磁碟，或無法判別其磁碟）：金鑰只寫入隨身碟；"
    "未寫入任何內容",
}
STICK_UNSAFE = {
    "en": "refused: on the stick at {path}, {name} would not be root's alone (the folder or the file is another "
    "account's, or others may read it): mount the stick with -o uid=0,gid=0,umask=077,nodev,nosuid,noexec; nothing "
    "of the key was written; then run the same command again with the same stick",
    "ja": "拒否：{path} の USB メモリでは {name} が root だけのものになりません（フォルダーかファイルがほかのアカウント"
    "のものか、ほかの人が読めます）。-o uid=0,gid=0,umask=077,nodev,nosuid,noexec でマウントしてください。鍵は何も"
    "書いていません。その後、同じ USB メモリで同じコマンドをもう一度実行してください",
    "zh-TW": "已拒絕：在 {path} 的隨身碟上，{name} 不會僅屬 root（資料夾或檔案屬於其他帳號，或他人可讀取）：請以 "
    "-o uid=0,gid=0,umask=077,nodev,nosuid,noexec 掛載隨身碟；未寫入任何金鑰內容；之後請用同一個隨身碟再次執行同一指令",
}
STICK_BROKEN = {
    "en": "refused: this stick cannot finish a ceremony: {name} on it is not a plain file of one name, or not a whole "
    "key of this box, or the two files do not give one key. Nothing was changed. A key on this stick never became the "
    "box's key; it stays there until IT wipes the stick. Run the command with an empty stick",
    "ja": "拒否：この USB メモリでは手続きを完了できません：{name} が名前の一つしかない普通のファイルでないか、この"
    "ボックスの完全な鍵でないか、二つのファイルが同じ鍵になりません。何も変更していません。この USB メモリの鍵が"
    "ボックスの鍵になったことはありません。情報システム担当が消去するまで残ります。空の USB メモリで実行してください",
    "zh-TW": "已拒絕：此隨身碟無法完成儀式：其上的 {name} 不是只有一個名稱的一般檔案，或不是此主機完整的金鑰，或兩個"
    "檔案不是同一把金鑰。未變更任何內容。此隨身碟上的金鑰從未成為主機的金鑰；它會留在那裡直到資訊人員抹除隨身碟。"
    "請改用空的隨身碟執行",
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
    "en": "done: backup key {fp}. The stick holds {key} and the paper sheet {paper}, both read back as one key; the "
    "event backup.key_ceremony naming {operator} and the witness {witness} went through the orchestrator's journal; "
    "the box keeps the public key only, at {pub}. Unmount (eject) the stick, print the sheet, and seal the stick and "
    "the paper in hospital IT's envelope. If an earlier run was cut short on another stick, the key on that stick "
    "never became the box's key: it stays there until IT wipes that stick",
    "ja": "完了：バックアップ鍵 {fp}。USB メモリには {key} と紙の控え {paper} があり、どちらも読み直して同じ鍵でした。"
    "{operator} と立会人 {witness} の名前を記した backup.key_ceremony をオーケストレーターのジャーナルに記録しました。"
    "ボックスには公開鍵（{pub}）だけが残ります。USB メモリをアンマウント（取り出し）し、紙の控えを印刷して、USB "
    "メモリと紙を病院の情報システム担当の封筒に封をして保管してください。以前の実行が別の USB メモリで途中で止まって"
    "いた場合、その USB メモリの鍵がボックスの鍵になったことはありません。情報システム担当が消去するまで残ります",
    "zh-TW": "完成：備份金鑰 {fp}。隨身碟上有 {key} 與紙本 {paper}，兩者讀回後為同一把金鑰；記有 {operator} 與見證人 "
    "{witness} 的 backup.key_ceremony 已寫入協調器的日誌；主機只保留公開金鑰，位於 {pub}。請卸載（退出）隨身碟、"
    "列印紙本，並將隨身碟與紙本放入醫院資訊人員的信封密封。若先前的執行在另一個隨身碟上中途停止，該隨身碟上的金鑰"
    "從未成為主機的金鑰：它會留在那裡直到資訊人員抹除該隨身碟",
}
UNEXPECTED = {
    "en": "stopped on an unexpected error ({kind}): nothing is undone and nothing is deleted. Run the same command "
    "again with the same stick",
    "ja": "予期しないエラー（{kind}）で止まりました。何も取り消さず、何も削除していません。同じ USB メモリで同じ"
    "コマンドをもう一度実行してください",
    "zh-TW": "因非預期的錯誤（{kind}）而停止：未復原也未刪除任何內容。請用同一個隨身碟再次執行同一指令",
}
SHEET_HEAD = {
    "en": "TrialBox backup private key, paper copy. It opens every backup of this box: keep it sealed with hospital "
    "IT. Each line ends with four check letters, so that a typed copy can be checked line by line.",
    "ja": "TrialBox バックアップ秘密鍵（紙の控え）。このボックスのすべてのバックアップを開ける鍵です。病院の情報"
    "システム担当が封をして保管してください。各行の最後の 4 文字は確認用で、入力した写しを行ごとに確かめる"
    "ためのものです。",
    "zh-TW": "TrialBox 備份私密金鑰（紙本）。它能開啟此主機的所有備份：請由醫院資訊人員密封保管。每行最後四個字母為"
    "檢查碼，可逐行核對輸入的副本。",
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
    """H1: not dumpable (a piped core handler ignores RLIMIT_CORE) and no core, before any key exists."""
    import ctypes
    import resource

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(4, 0, 0, 0, 0) != 0 or libc.prctl(3, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE 0; PR_GET_DUMPABLE is 0
        raise OSError(errno.EPERM, "not dumpable")


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
    """Two spellings of one person compare equal: NFKC, white space collapsed, case folded."""
    return " ".join(unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", name).casefold()).split())


def _block(dev: int) -> int | None:
    """The block device under a filesystem: itself, or (btrfs and other anonymous devices) its mount's source."""
    if os.major(dev) != 0:
        return dev
    for line in MOUNTINFO.read_text(encoding="utf-8").splitlines():
        f = line.split()
        if f[2] == f"0:{os.minor(dev)}" and "-" in f:
            try:
                st = os.stat(f[f.index("-") + 2])
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
    """Whether a folder on ``stick_dev`` may not take the key: its whole disks must be known, removable, and none of
    the whole disks of the box's folders (``box_devs``: the system and the public key's folder)."""
    mine, box = whole_disks(stick_dev), [whole_disks(d) for d in box_devs]
    return not mine or any(not b or b & mine for b in box) or not all(_removable(d) for d in mine)


def _root_only(st: os.stat_result) -> bool:
    return st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) & 0o022 == 0


def _open_dir(path: Path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)


def _env() -> dict[str, str]:
    from tools.trialbox.logs import env_file

    return {**env_file(DEPLOY), **{k: v for k, v in os.environ.items() if k.startswith(("TB_", "COMPOSE_"))}}


# ------------------------------------------------------------------------------------------------ the journal (step 3)
#: run in the orchestrator's container, as audit_heads records ``audit.head_signed``; refuses a file-mode writer
JOURNAL_CODE = (
    "import json, sys\nfrom tb_common.audit_writer import DbAuditWriter, open_audit\nw = open_audit()\n"
    "if not isinstance(w, DbAuditWriter):\n    sys.exit(3)\n"
    "if sys.argv[1:2] == ['record']:\n    w.append(sys.argv[2], actor=sys.argv[3], detail=json.loads(sys.argv[4]))\n"
)


def _journal(env: Mapping[str, str], *args: str) -> int:
    compose = shlex.split(env.get("TB_COMPOSE") or f"docker compose --project-directory {shlex.quote(str(DEPLOY))}")
    argv = [*compose, "exec", "-T", "orchestrator", "python", "-c", JOURNAL_CODE, *args]
    try:
        return subprocess.run(argv, capture_output=True, timeout=JOURNAL_WAIT_S, check=False).returncode
    except (OSError, subprocess.TimeoutExpired):
        return -1


def record(env: Mapping[str, str], detail: Mapping[str, str]) -> None:
    if _journal(env, "record", EVENT, ACTOR, json.dumps(dict(detail), ensure_ascii=False)) != 0:
        raise Stop(JOURNAL_UNSURE)


# ------------------------------------------------------------------------------------------------ files, by descriptor
def _sync_dir(dfd: int, n: int) -> None:
    """M6: a folder's sync that fails, whatever the errno (EINVAL and ENOTSUP included), stops the step."""
    try:
        os.fsync(dfd)
    except OSError as e:
        raise Stop(STEP_FAILED, n=n, why=errno.errorcode.get(e.errno or 0, "OSError")) from None


def _safe(fd: int, dev: int, name: str, path: Path) -> os.stat_result:
    """A stick file is a plain file of one name on the stick's filesystem, root's alone; else refused."""
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_dev != dev:
        raise Stop(STICK_BROKEN, name=name)
    if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) & 0o077:
        raise Stop(STICK_UNSAFE, path=path, name=name)
    return st


def _open_on_stick(dfd: int, name: str, create: bool) -> int:
    """A name on the stick opened through its folder, never through a link; a name that is there and is not a plain
    file (a link, a folder, a device, a pipe) is refused before it is opened."""
    if not create and not stat.S_ISREG(os.stat(name, dir_fd=dfd, follow_symlinks=False).st_mode):
        raise Stop(STICK_BROKEN, name=name)
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | (os.O_CREAT | os.O_EXCL if create else 0)
    try:
        return os.open(name, flags, 0o600, dir_fd=dfd)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.ENXIO, errno.EISDIR):
            raise Stop(STICK_BROKEN, name=name) from None
        raise


def _read_all(fd: int, size: int) -> bytes:
    return os.pread(fd, size + 1, 0)


def _put(dfd: int, name: str, dev: int, path: Path, make: Any) -> tuple[int, bytes | None]:
    """Make ``name`` new on the stick and write ``make()`` into it; a name already there (a run cut short) is kept
    as it is and read in step 2, unless it is empty (then it is written now). Returns the inode and what was written."""
    try:
        fd, new = _open_on_stick(dfd, name, create=True), True
    except FileExistsError:
        fd, new = _open_on_stick(dfd, name, create=False), False
    try:
        st = _safe(fd, dev, name, path)
        if not new and st.st_size > 0:
            return st.st_ino, None
        data, done = make(), 0
        while done < len(data):
            done += os.write(fd, data[done:])
        os.fsync(fd)
        if _read_all(fd, len(data)) != data:  # read back from the same descriptor
            raise Stop(STICK_BROKEN, name=name)
        return st.st_ino, data
    finally:
        os.close(fd)


def _read_back(dfd: int, name: str, dev: int, path: Path, ino: int, wrote: bytes | None) -> bytes:
    """Step 2: the file opened again through the stick's folder: the same inode, and the bytes written, if any."""
    fd = _open_on_stick(dfd, name, create=False)
    try:
        st = _safe(fd, dev, name, path)
        data = _read_all(fd, max(st.st_size, 1 << 16))
        if st.st_ino != ino or (wrote is not None and data != wrote):
            raise Stop(STICK_BROKEN, name=name)
        return data
    finally:
        os.close(fd)


def _link_pub(pfd: int, pub: bytes) -> None:
    """Step 4: backup.pub made new, never over a name, and never seen half written: written whole and synced in an
    unnamed file of the folder (O_TMPFILE), then given its name by a link, which fails when the name exists, as
    O_EXCL does. Every error here comes before the name exists."""
    data = (base64.b64encode(pub).decode() + "\n").encode()
    fd = os.open(".", os.O_WRONLY | os.O_TMPFILE | os.O_CLOEXEC, 0o644, dir_fd=pfd)
    try:
        if os.write(fd, data) != len(data):
            raise OSError(errno.EIO, "short write")
        os.fsync(fd)
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


# ------------------------------------------------------------------------------------------------ the ceremony
def run(stick: Path, operator: str | None, witness: str | None, env: Mapping[str, str]) -> dict[str, str]:
    """The checks (nothing written when one refuses), then the four steps; returns what the journal holds."""
    if not is_root():
        raise Stop(NOT_ROOT)
    who, wit = person(operator), person(witness)
    if folded(who) == folded(wit):
        raise Stop(SAME_PERSON)
    pub_path = PUB_DIR / PUB_NAME
    if (named := env.get("TB_BACKUP_PUBKEY")) and os.path.abspath(named) != os.path.abspath(pub_path):
        raise Stop(PUB_ELSEWHERE, path=named, pub=pub_path)
    try:
        pfd = _open_dir(PUB_DIR)
    except OSError:
        raise Stop(PUB_DIR_UNSAFE, path=PUB_DIR) from None
    try:
        if not _root_only(os.fstat(pfd)):
            raise Stop(PUB_DIR_UNSAFE, path=PUB_DIR)
        if _exists(pfd, PUB_NAME):  # "once" is backup.pub (owner's condition 2)
            raise Stop(ALREADY, pub=pub_path, fp=_pub_fp(pfd))
        if _journal(env, "check") != 0:
            raise Stop(NO_JOURNAL)
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


def _on_stick(sfd: int, dev: int, stick: Path, site: str, step: list[int]) -> bytes:
    """Steps 1 and 2; returns the public key. Step 1: the key file (the key made now, or the whole key file a run cut
    short left), then the sheet from that key. Step 2: both read back through the folder held open: one key, and the
    sheet of this box's site."""
    made: list[bytes] = []

    def make_key() -> bytes:
        made.append(new_key())
        return key_text(made[0])

    k_ino, k_wrote = _put(sfd, KEY_FILE, dev, stick, make_key)
    key = made[0] if made else read_key(_read_back(sfd, KEY_FILE, dev, stick, k_ino, None))
    if key is None:
        raise Stop(STICK_BROKEN, name=KEY_FILE)
    sheet_of = functools.partial(paper_sheet, key, site, datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"))
    p_ino, p_wrote = _put(sfd, PAPER_FILE, dev, stick, sheet_of)
    _sync_dir(sfd, 1)
    step[0] = 2
    if read_key(_read_back(sfd, KEY_FILE, dev, stick, k_ino, k_wrote)) != key:
        raise Stop(STICK_BROKEN, name=KEY_FILE)
    if read_sheet(_read_back(sfd, PAPER_FILE, dev, stick, p_ino, p_wrote)) != (key, site or "-"):
        raise Stop(STICK_BROKEN, name=PAPER_FILE)
    return public_of(key)


def _steps(sfd: int, pfd: int, stick: Path, who: str, wit: str, env: Mapping[str, str]) -> dict[str, str]:
    sst = os.fstat(sfd)
    if stick_problem(sst.st_dev, [os.stat("/").st_dev, os.fstat(pfd).st_dev]):
        raise Stop(NOT_A_STICK, path=stick)
    if not _root_only(sst):
        raise Stop(STICK_UNSAFE, path=stick, name=KEY_FILE)
    site, step = env.get("TB_SITE_ID") or "", [1]
    try:
        pub = _on_stick(sfd, sst.st_dev, stick, site, step)  # steps 1 and 2; the private key goes out of scope
    except OSError as e:
        raise Stop(STEP_FAILED, n=step[0], why=errno.errorcode.get(e.errno or 0, "OSError")) from None
    fp = fingerprint(pub)
    detail = {"fingerprint": fp, "operator": who, "witness": wit, "site": site, "stick": "key file and sheet read back"}
    record(env, detail)  # step 3
    try:  # step 4
        _link_pub(pfd, pub)
    except FileExistsError:
        raise Stop(ALREADY, pub=PUB_DIR / PUB_NAME, fp=_pub_fp(pfd)) from None
    except OSError as e:
        raise Stop(STEP_FAILED, n=4, why=errno.errorcode.get(e.errno or 0, "OSError")) from None
    try:
        os.fsync(pfd)
        if _pub_fp(pfd) != fp:
            raise OSError(errno.EIO, "read back")
    except OSError as e:
        raise Stop(PUB_UNSURE, pub=PUB_DIR / PUB_NAME, why=errno.errorcode.get(e.errno or 0, "OSError")) from None
    return {**detail, "pub": str(PUB_DIR / PUB_NAME)}


def main(argv: Sequence[str] | None = None) -> int:
    try:
        harden()  # H1: first, before any key material exists
    except OSError:
        print(UNEXPECTED["en"].format(kind="prctl"), file=sys.stderr)
        return 1
    ap = argparse.ArgumentParser(prog="python -m tools.backup_key_ceremony", description=__doc__.split("\n")[0])
    ap.add_argument("--stick", required=True, help="the mounted folder of the removable stick")
    ap.add_argument("--operator", help="the person who runs the ceremony (hospital IT)")
    ap.add_argument("--witness", help="the witness: another person")
    ap.add_argument("--lang", help="en (the default), ja or zh-TW")
    a = ap.parse_args(argv)
    lang = lang_of(a.lang)
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
                            witness=rec["witness"], pub=rec["pub"]))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
