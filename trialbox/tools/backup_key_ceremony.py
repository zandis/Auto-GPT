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
The order (D-1379): the two stick files (each created here or not at all, written in full, synced, and on the device
that was checked), the stick's folder synced, both files read back (each must give the public key just made), then
``backup.pub`` put in place without overwriting (a synced temporary file linked to its name), and last the audit
event ``backup.key_ceremony`` (when, the key's fingerprint, the person who ran it and the witness; never the key, a
line of the sheet or a path on the stick). The ceremony is one failure domain: a failure at any step after the first
file is made (an error, an interruption) removes every file it made, on the stick and on the box, and says which were
removed and which, if any, are left and where; so the box never keeps ``backup.pub`` without the audit event.

Refused, before anything is written: not root; the operator or the witness not named, or the same person (compared
after NFKC, with spaces collapsed and case folded); no audit folder; a box that has a backup key already, or whose
audit holds a ceremony already (a ceremony is run once; a new pair is the key's rotation, RUNBOOK §25, not this
command); no secrets folder to check the stick against; no stick at the folder named; a folder on the box's disks or
inside the secrets folder; a stick that cannot be written; a file of either name already on the stick (a link
included). Every text is in en, ja and zh-TW (``--lang``; no setting is read for it).

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
import sys
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FORMAT = "tb-backup-paper/1"
EVENT = "backup.key_ceremony"
ACTOR = "python -m tools.backup_key_ceremony"
KEY_FILE = "trialbox-backup.key"
PAPER_FILE = "trialbox-backup-key-paper.txt"
LINE_CHARS = 16  # four groups of four letters a line
CHECK_CHARS = 4  # 20 bits: a random slip passes about once in a million
NAME_MAX = 100
LANGS = ("en", "ja", "zh-TW")
DEFAULT_DEPLOY = Path(__file__).resolve().parents[1] / "deploy"

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


def writable(folder: Path) -> bool:
    """Whether a file can be made, written and synced in ``folder`` (the probe is removed again)."""
    probe = folder / f".tb-probe-{secrets.token_hex(4)}"
    try:
        fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, b"\0" * 4096)
            os.fsync(fd)
        finally:
            os.close(fd)
        probe.unlink()
        return True
    except OSError:
        probe.unlink(missing_ok=True)
        return False


def _detail(rec: Mapping[str, Any]) -> dict[str, Any]:
    det = rec.get("detail")
    return det if isinstance(det, dict) else {}


def earlier_ceremony(audit_dir: Path, site: str) -> dict[str, Any] | None:
    """The newest ``backup.key_ceremony`` event of this site in the audit chain, or None. Read as the chain's own
    readers read it (``tb_common.audit``: the day files newest first, each from its end); an event or a run with no
    site counts as this site's (one box, one audit folder)."""
    from tb_common.audit import _day_files, lines_backward

    want = f'"{EVENT}"'.encode()
    for path in reversed(_day_files(audit_dir)):
        for line in lines_backward(path):
            if want not in line:
                continue
            try:
                rec = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(rec, dict) or rec.get("event") != EVENT:
                continue
            det = _detail(rec)
            theirs = str(det.get("site") or "")
            if site and theirs and theirs != site:
                continue
            return rec
    return None


def check(
    stick: Path, operator: str | None, witness: str | None, pub: Path, sec: Path, audit_dir: Path | None, site: str = ""
) -> tuple[str, str, int]:
    """Every refusal before anything is written, in the order a person meets them; returns the two names and the
    device of the stick that was checked (each file made on it must be on that device)."""
    from tools import key_escrow as ke

    if not is_root():
        raise CeremonyError(NOT_ROOT)
    who, wit = person(operator), person(witness)
    if folded(who) == folded(wit):
        raise CeremonyError(SAME_PERSON)
    if audit_dir is None or not audit_dir.is_dir():
        raise CeremonyError(NO_AUDIT)
    if os.path.lexists(pub):
        raise CeremonyError(ALREADY, fp=_pub_fingerprint(pub))
    if (prev := earlier_ceremony(audit_dir, site)) is not None:
        det = _detail(prev)
        raise CeremonyError(AUDITED_ALREADY, at=str(prev.get("ts") or "-"), fp=str(det.get("fingerprint") or "-"))
    if not sec.is_dir():
        raise CeremonyError(NO_SECRETS, path=sec)
    if not stick.is_dir():
        raise CeremonyError(NO_STICK, path=stick)
    if ke.media_problem(stick, sec) is not None:
        raise CeremonyError(NOT_A_STICK, path=stick)
    dev = stick.stat().st_dev
    for name in (KEY_FILE, PAPER_FILE):
        if os.path.lexists(stick / name):  # a link, a dangling one too, is a file of that name
            raise CeremonyError(STICK_HAS_KEY, name=name)
    if not writable(stick):
        raise CeremonyError(NOT_WRITABLE, path=stick)
    return who, wit, dev


def _pub_fingerprint(pub: Path) -> str:
    from tools.trialbox import backup as bk

    try:
        return bk.fingerprint(bk.load_public(pub).public_bytes_raw())
    except (OSError, ValueError):
        return "unreadable"


# ------------------------------------------------------------------------------------------------ the ceremony
class _Undo:
    """What the ceremony has made so far, in order; :meth:`run` removes it again, newest first."""

    def __init__(self) -> None:
        self.files: list[Path] = []
        self.dirs: list[Path] = []

    def run(self) -> list[tuple[Mapping[str, str], dict[str, Any]]]:
        """Remove every file and folder made; what to say about it (removed, and any left behind with its path)."""
        removed: list[Path] = []
        left: list[Path] = []
        for p in reversed(self.files):
            try:
                p.unlink(missing_ok=True)
                removed.append(p)
            except OSError:
                left.append(p)
        for d in reversed(self.dirs):
            try:
                d.rmdir()
                removed.append(d)
            except OSError:
                left.append(d)
        for folder in {p.parent for p in removed}:
            with contextlib.suppress(OSError):
                _sync_dir(folder)
        if not removed and not left:
            return [(KEPT_NOTHING, {})]
        said: list[tuple[Mapping[str, str], dict[str, Any]]] = []
        if removed:
            said.append((REMOVED_SOME if left else REMOVED_ALL, {"files": ", ".join(str(p) for p in removed)}))
        if left:
            said.append((LEFT, {"files": ", ".join(str(p) for p in left)}))
        return said


def _write_new(path: Path, data: bytes, undo: _Undo, dev: int | None, mode: int = 0o600) -> None:
    """``data`` to ``path`` (``mode``), created here or not at all (never through a link), written in full and synced.
    The path is in ``undo`` from the moment it exists, so a failed write or sync is removed again. With ``dev``, a
    file that is not on that device (the stick pulled or mounted again since the check) is refused."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    undo.files.append(path)
    try:
        if dev is not None and os.fstat(fd).st_dev != dev:
            raise CeremonyError(STICK_MOVED, name=path.name, path=path.parent)
        view = memoryview(data)
        while view:
            n = os.write(fd, view)
            if n <= 0:
                raise OSError(errno.EIO, f"{path}: nothing written")
            view = view[n:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_dir(folder: Path) -> None:
    """Sync ``folder`` itself, so the names of the files made in it are on the medium too."""
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    except OSError as e:
        if e.errno not in (errno.EINVAL, errno.ENOTSUP):  # a filesystem that does not sync a folder on its own
            raise
    finally:
        os.close(fd)


def _place_pub(pub: Path, text: str, undo: _Undo) -> None:
    """The public key to ``pub``, never over a file there: its folder made if missing, a synced temporary file in
    it, then a hard link to the name (refused when the name exists) and the temporary name removed."""
    missing: list[Path] = []
    d = pub.parent
    while not os.path.lexists(d):
        missing.append(d)
        d = d.parent
    for d in reversed(missing):
        d.mkdir()
        undo.dirs.append(d)
    tmp = pub.parent / f".{pub.name}.{secrets.token_hex(4)}.tmp"
    _write_new(tmp, text.encode(), undo, None, mode=0o644)
    os.link(tmp, pub)  # no overwrite: FileExistsError when a file of that name appeared meanwhile
    undo.files.append(pub)
    tmp.unlink()
    undo.files.remove(tmp)
    _sync_dir(pub.parent)


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


def _recorded(audit_dir: Path, site: str, fp: str) -> bool:
    """Whether the chain holds this ceremony's event (an append can fail after its line is written, e.g. on the head
    anchor); then the ceremony is done and nothing is undone."""
    try:
        rec = earlier_ceremony(audit_dir, site)
    except Exception:
        return False
    return bool(fp) and rec is not None and _detail(rec).get("fingerprint") == fp


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
    """The ceremony; returns what the audit holds (no key). :class:`CeremonyError` on a refusal; after the first file
    is made, every failure (an interruption too) undoes what was made and the refusal says what was removed."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from tb_common.audit import AuditLog

    from tools.trialbox import backup as bk

    who, wit, dev = check(stick, operator, witness, pub, sec, audit_dir, site)
    if audit_dir is None:  # check() refused already; said again for the type checker
        raise CeremonyError(NO_AUDIT)
    key_file, paper_file = stick / KEY_FILE, stick / PAPER_FILE
    undo, step, fp = _Undo(), "start", ""
    detail: dict[str, Any] = {}
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
        _write_new(key_file, f"{head}\n{machine}\nfingerprint {fp}\n{tail}\n".encode(), undo, dev)  # as keygen does
        _write_new(paper_file, paper_sheet(raw, fp, site, at).encode(), undo, dev)
        _sync_dir(stick)
        back_key = bk.load_private(key_file).public_key().public_bytes_raw()
        back_paper = _fingerprint_of(read_paper(paper_file.read_text(encoding="utf-8")))
        if back_key != pk or back_paper != fp:
            raise CeremonyError(READ_BACK)
        del sk, raw, letters, machine
        step = "public"
        _place_pub(pub, base64.b64encode(pk).decode() + "\n", undo)
        step = "audit"
        detail = {"at": at, "site": site, "fingerprint": fp, "operator": who, "witness": wit,
                  "forms": ["stick", "paper"], "paper_format": FORMAT}  # fmt: skip
        log.append(EVENT, actor=ACTOR, input_sha="", detail=detail)
    except BaseException as e:  # one failure domain: nothing of a failed ceremony is kept (D-1379)
        if not (step == "audit" and _recorded(audit_dir, site, fp)):
            err = _cause(e, step, stick, pub, audit_dir)
            err.more = undo.run()
            raise err from None
    return {**detail, "key_file": key_file.name, "paper_file": paper_file.name, "public": str(pub)}


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
    except CeremonyError as e:
        return _refuse(e, lang)
    # what is left is a failure before the first file is made: run() says every later one as a CeremonyError itself
    except KeyboardInterrupt:
        return _refuse(CeremonyError(INTERRUPTED), lang, nothing=True)
    except Exception as e:
        return _refuse(CeremonyError(UNEXPECTED, kind=type(e).__name__), lang, nothing=True)
    print(DONE[lang].format(fp=rec["fingerprint"], key=rec["key_file"], paper=rec["paper_file"], pub=rec["public"],
                            event=EVENT, operator=rec["operator"], witness=rec["witness"]))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
