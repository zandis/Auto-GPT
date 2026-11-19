"""``python -m tools.backup_key_ceremony`` (10K-13, D-1379): the backup-key ceremony on the box's host.

    python -m tools.backup_key_ceremony --stick /media/usb --operator "<name>" --witness "<name>" [--lang ja]

Hospital IT, as root on the box's host, with a witness who is another person (TB-SOP-03 §2), makes the box's backup
key pair once. The private key leaves the box in two forms and no other:

* **the stick**: ``trialbox-backup.key`` in the format ``trialbox backup-keygen`` writes (``backup.load_private``
  reads it; ``restore --key`` and ``restore-drill --key`` take it as they are);
* **the paper sheet**: ``trialbox-backup-key-paper.txt`` on the same stick, to be printed. The key is four lines of
  base32 letters in groups of four; each line ends with four check letters (the line's number and letters hashed),
  and the sheet carries the key's fingerprint, so a mistyped letter, a line left out or two lines swapped is caught
  where the sheet is read back (:func:`read_paper`), naming the line and never its letters.

The key is made in memory and written only to the stick: never to the box's disks, the screen, a log or the audit.
Both files are read back from the stick and must give the same public key before the box keeps the public half
(``deploy/secrets/backup.pub``, where ``trialbox backup`` reads it). The ceremony is the audit event
``backup.key_ceremony``: when, the key's fingerprint, the person who ran it and the witness. Never the key, a line of
the sheet or a path on the stick.

Refused, before anything is written: not root; the operator or the witness not named, or the same person; no audit
folder; a box that has a backup key already (a ceremony is run once; a new pair is the key's rotation, RUNBOOK §25,
not this command); no secrets folder to check the stick against; no stick at the folder named; a folder on the box's
disks or inside the secrets folder; a stick that cannot be written; a stick that already holds a backup key. A stick
that fails while written or read back keeps nothing. Every text is in en, ja and zh-TW (``--lang``, else
``TB_LANG``).

Not here (D-1379): reading the paper sheet into a restore (``restore --key`` takes the stick's file), a console page,
a printer.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
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
    "en": "refused: the stick already holds a backup key file ({name}): a key is never overwritten; use an empty stick",
    "ja": "拒否：USB メモリにはすでにバックアップ鍵のファイル（{name}）があります。鍵は上書きしません。"
    "空の USB メモリを使ってください",
    "zh-TW": "已拒絕：隨身碟上已有備份金鑰檔案（{name}）：金鑰絕不覆寫；請改用空的隨身碟",
}
READ_BACK = {
    "en": "refused: the stick's copy did not read back as the key just made: nothing was kept; use another stick",
    "ja": "拒否：USB メモリから読み直した鍵が作った鍵と一致しません。何も残していません。"
    "別の USB メモリを使ってください",
    "zh-TW": "已拒絕：從隨身碟讀回的金鑰與剛建立的不一致：未保留任何內容；請改用另一個隨身碟",
}
DONE = {
    "en": "backup key {fp} made. The stick holds {key} and the paper sheet {paper}; both were read back. Print the "
    "sheet; the stick and the paper go into hospital IT's sealed envelope. The box keeps the public key only "
    "({pub}); the audit event {event} names {operator} and the witness {witness}.",
    "ja": "バックアップ鍵 {fp} を作りました。USB メモリには {key} と紙の控え {paper} があり、どちらも読み直して確認"
    "しました。紙の控えを印刷し、USB メモリと紙は病院の情報システム担当の封筒に封をして保管します。ボックスには公開鍵"
    "（{pub}）だけが残ります。監査記録 {event} には {operator} と立会人 {witness} の名前があります。",
    "zh-TW": "已建立備份金鑰 {fp}。隨身碟上有 {key} 與紙本 {paper}，兩者都已讀回確認。請列印紙本；隨身碟與紙本放入醫院"
    "資訊人員的密封信封。主機只保留公開金鑰（{pub}）；稽核紀錄 {event} 記有 {operator} 與見證人 {witness}。",
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
    "IT. Each line ends with four check letters; a mistyped letter is caught when the sheet is read back.",
    "ja": "TrialBox バックアップ秘密鍵（紙の控え）。このボックスのすべてのバックアップを開ける鍵です。"
    "病院の情報システム担当が封をして保管してください。各行の最後の 4 文字は確認用で、"
    "打ち間違いは読み直すときに見つかります。",
    "zh-TW": "TrialBox 備份私密金鑰（紙本）。它能開啟此主機的所有備份：請由醫院資訊人員密封保管。每行最後四個字母為"
    "檢查碼；輸入錯誤會在讀回時被發現。",
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
    """A refusal: ``text`` is one of this module's three-language texts, ``args`` fill it (never a key)."""

    def __init__(self, text: Mapping[str, str], **fill: Any) -> None:
        super().__init__(text["en"].format(**fill))
        self.text, self.fill = text, fill

    def say(self, lang: str) -> str:
        return self.text[lang_of(lang)].format(**self.fill)


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


def check(
    stick: Path, operator: str | None, witness: str | None, pub: Path, sec: Path, audit_dir: Path | None
) -> tuple[str, str]:
    """Every refusal before anything is written, in the order a person meets them; returns the two names."""
    from tools import key_escrow as ke

    if not is_root():
        raise CeremonyError(NOT_ROOT)
    who, wit = person(operator), person(witness)
    if who.casefold() == wit.casefold():
        raise CeremonyError(SAME_PERSON)
    if audit_dir is None or not audit_dir.is_dir():
        raise CeremonyError(NO_AUDIT)
    if pub.exists():
        raise CeremonyError(ALREADY, fp=_pub_fingerprint(pub))
    if not sec.is_dir():
        raise CeremonyError(NO_SECRETS, path=sec)
    if not stick.is_dir():
        raise CeremonyError(NO_STICK, path=stick)
    if ke.media_problem(stick, sec) is not None:
        raise CeremonyError(NOT_A_STICK, path=stick)
    for name in (KEY_FILE, PAPER_FILE):
        if (stick / name).exists():
            raise CeremonyError(STICK_HAS_KEY, name=name)
    if not writable(stick):
        raise CeremonyError(NOT_WRITABLE, path=stick)
    return who, wit


def _pub_fingerprint(pub: Path) -> str:
    from tools.trialbox import backup as bk

    try:
        return bk.fingerprint(bk.load_public(pub).public_bytes_raw())
    except (OSError, ValueError):
        return "unreadable"


# ------------------------------------------------------------------------------------------------ the ceremony
def _write_new(path: Path, text: str) -> None:
    """``text`` to ``path`` (0600), created here or not at all, synced to the stick."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, text.encode())
        os.fsync(fd)
    finally:
        os.close(fd)


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
) -> dict[str, Any]:
    """The ceremony; returns what the audit holds (no key). :class:`CeremonyError` on a refusal, with nothing kept."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    from tools.trialbox import backup as bk

    who, wit = check(stick, operator, witness, pub, sec, audit_dir)
    if audit_dir is None:  # check() refused already; said again for the type checker
        raise CeremonyError(NO_AUDIT)
    at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    sk = X25519PrivateKey.generate()
    raw = sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pk = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    fp = bk.fingerprint(pk)
    letters = _letters(raw)
    machine = " ".join(letters[i : i + 4] for i in range(0, len(letters), 4))
    key_file, paper_file = stick / KEY_FILE, stick / PAPER_FILE
    made: list[Path] = []
    try:
        head, tail = f"-----BEGIN {bk.KEY_HEADER}-----", f"-----END {bk.KEY_HEADER}-----"
        _write_new(key_file, f"{head}\n{machine}\nfingerprint {fp}\n{tail}\n")  # as backup.keygen writes it
        made.append(key_file)
        _write_new(paper_file, paper_sheet(raw, fp, site, at))
        made.append(paper_file)
        back_key = bk.load_private(key_file).public_key().public_bytes_raw()
        back_paper = _fingerprint_of(read_paper(paper_file.read_text(encoding="utf-8")))
        if back_key != pk or back_paper != fp:
            raise CeremonyError(READ_BACK)
    except (OSError, ValueError, bk.BackupError, CeremonyError) as e:  # nothing of a failed ceremony is kept
        for p in made:
            p.unlink(missing_ok=True)
        raise CeremonyError(NOT_WRITABLE if isinstance(e, OSError) else READ_BACK, path=stick) from None
    del sk, raw, letters, machine
    pub.parent.mkdir(parents=True, exist_ok=True)
    pub.write_text(base64.b64encode(pk).decode() + "\n", encoding="utf-8")
    detail = {"at": at, "site": site, "fingerprint": fp, "operator": who, "witness": wit,
              "forms": ["stick", "paper"], "paper_format": FORMAT}  # fmt: skip
    from tb_common.audit import AuditLog

    AuditLog(audit_dir).append(EVENT, actor=ACTOR, input_sha="", detail=detail)
    return {**detail, "key_file": key_file.name, "paper_file": paper_file.name, "public": str(pub)}


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
    ap.add_argument("--lang", help="en, ja or zh-TW (TB_LANG)")
    a = ap.parse_args(argv)
    from tools import key_ceremony as kc
    from tools.keys import secrets_dir

    lang = lang_of(a.lang or env.get("TB_LANG"))
    deploy = Path(a.deploy)
    pub = Path(a.public) if a.public else kc.default_backup_pub(env, deploy)
    audit = Path(a.audit_dir) if a.audit_dir else Path(env["TB_AUDIT_DIR"]) if env.get("TB_AUDIT_DIR") else None
    try:
        rec = run(Path(a.stick), a.operator, a.witness, pub=pub, sec=secrets_dir(a.secrets, env), audit_dir=audit,
                  site=env.get("TB_SITE_ID") or "")  # fmt: skip
    except CeremonyError as e:
        print(e.say(lang), file=sys.stderr)
        return 1
    print(DONE[lang].format(fp=rec["fingerprint"], key=rec["key_file"], paper=rec["paper_file"], pub=rec["public"],
                            event=EVENT, operator=rec["operator"], witness=rec["witness"]))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
