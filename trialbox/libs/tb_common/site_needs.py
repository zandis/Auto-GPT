"""U5-1 (card U-5, the owner's ruling relayed on #639): the one list of the site information a box may still need.

The rule: a missing piece of site information never stops the install or the start. The box installs with four
answers (the language, the time zone, the first administrator, and the passphrase only without a TPM), runs, and
collects the rest on one page, "Information still needed". On a PoC box a missing item is a warning and the step goes
on with a stand-in. On a PRODUCTION box the step that needs the item is refused by name until it is given
(``docs/plan/design/install-first-information-after.md`` section 3.3; ``install-questions-cut.md``).

This module is that list, as data. Each :class:`Need` says:

* its stable ``key``;
* ``before``: the steps it is needed before (:data:`STEPS`);
* ``answers``: where a given answer is found. This is a tuple of groups; every group must hold a non-empty value,
  and any one name in a group is enough. A name is ``env:<NAME>`` (``deploy/.env``), ``settings:<dotted.path>``
  (``settings.yaml``) or ``file:<path under deploy/>``;
* ``who``: who usually knows it (:data:`WHO`);
* its title, why it is needed, and how the box runs meanwhile (``stand_in``), each in en, ja and zh-TW.

The installer, ``doctor``, the page and the gates read this one list; a new item is added here, never anywhere
else. The list says whether an answer was given, not whether it is good: whether a share is mounted or a relay
answers stays with ``doctor``'s own checks.

A value can be present and still be a stand-in, such as the first administrator's mail standing in for the trial
office's mailbox (the integrator's ruling on #1417). The caller passes the keys it knows are stand-ins. Where that
mark is kept is part 2's choice (U5-2), not this list's.

Standard library only: the console, the services and the host's ``python3`` all import it.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

LANGS = ("en", "ja", "zh-TW")
STATES = ("missing", "stand_in", "given")

#: the steps an item is needed before, in the order a site meets them
STEPS: dict[str, dict[str, str]] = {
    "staff_use": {
        "en": "Staff use from the clinic PCs",
        "ja": "院内の端末から使う",
        "zh-TW": "院內電腦使用",
    },
    "first_real_night": {
        "en": "The first night on real data",
        "ja": "実データの最初の夜間処理",
        "zh-TW": "真實資料的第一個夜間作業",
    },
    "study_open": {
        "en": "A study opens for real patients",
        "ja": "実患者向けに試験を開始する",
        "zh-TW": "對真實病人開放試驗",
    },
    "sae_notice": {
        "en": "A serious adverse event notice is mailed",
        "ja": "重篤な有害事象の通知をメールで送る",
        "zh-TW": "寄出嚴重不良事件通知",
    },
    "mail_out": {
        "en": "Any mail",
        "ja": "すべてのメール",
        "zh-TW": "任何郵件",
    },
    "request_mail": {
        "en": "Reading request mail",
        "ja": "依頼メールの読み込み",
        "zh-TW": "讀取申請郵件",
    },
}

WHO: dict[str, dict[str, str]] = {
    "it": {"en": "Hospital IT", "ja": "情報システム部門", "zh-TW": "資訊室"},
    "trial_office": {"en": "Trial office", "ja": "治験事務局", "zh-TW": "試驗辦公室"},
    "records": {"en": "Medical records", "ja": "診療情報管理", "zh-TW": "病歷室"},
}

PREFIXES = ("env:", "settings:", "file:")


@dataclass(frozen=True)
class Need:
    key: str
    before: tuple[str, ...]
    answers: tuple[tuple[str, ...], ...]
    who: str
    title: Mapping[str, str]
    why: Mapping[str, str]
    stand_in: Mapping[str, str]


NEEDS: tuple[Need, ...] = (
    Need(
        key="data_source",
        before=("first_real_night",),
        answers=(("settings:data_source.type",), ("env:TB_SOURCE_DIR", "env:TB_SOURCE_DSN")),
        who="it",
        title={
            "en": "Where the hospital's records come from",
            "ja": "病院の診療データの取得元",
            "zh-TW": "醫院病歷資料的來源",
        },
        why={
            "en": "The night reads them.",
            "ja": "夜間処理が読み込みます。",
            "zh-TW": "夜間作業要讀取它。",
        },
        stand_in={
            "en": "A PoC box reads the sample hospital; a live box reads nothing yet.",
            "ja": "PoC の機械は見本の病院を読みます。本番の機械はまだ何も読みません。",
            "zh-TW": "PoC 機器讀取示範醫院；正式機器尚未讀取任何資料。",
        },
    ),
    Need(
        key="chart_number",
        before=("first_real_night",),
        answers=(("env:TB_CHARTNO_RULE",),),
        who="records",
        title={
            "en": "How a chart number is written",
            "ja": "患者 ID（カルテ番号）の書き方",
            "zh-TW": "病歷號的寫法",
        },
        why={
            "en": "One patient is one number, however a sheet writes it.",
            "ja": "どの帳票でも、一人の患者を一つの番号にします。",
            "zh-TW": "不論表單怎麼寫，一位病人對應一個號碼。",
        },
        stand_in={
            "en": "Read from the first records, to confirm here.",
            "ja": "最初のデータから読み取ります。ここで確認してください。",
            "zh-TW": "由最初的資料讀取，請在此確認。",
        },
    ),
    Need(
        key="backup_target",
        before=("first_real_night",),
        answers=(("env:TB_BACKUP_TARGETS",),),
        who="it",
        title={
            "en": "Where backups go, off this machine",
            "ja": "バックアップの保存先（この機械の外）",
            "zh-TW": "備份存放處（本機以外）",
        },
        why={
            "en": "A copy that survives the box.",
            "ja": "機械が壊れても残る複製です。",
            "zh-TW": "機器故障時仍保有副本。",
        },
        stand_in={
            "en": "Backups stay on this machine.",
            "ja": "バックアップはこの機械の中に残ります。",
            "zh-TW": "備份暫存於本機。",
        },
    ),
    Need(
        key="backup_key",
        before=("first_real_night",),
        answers=(("file:secrets/backup.pub",),),
        who="it",
        title={
            "en": "The backup key",
            "ja": "バックアップの鍵",
            "zh-TW": "備份金鑰",
        },
        why={
            "en": "Backups are encrypted to it; its private half is kept off the box.",
            "ja": "バックアップはこの鍵で暗号化します。秘密鍵は機械の外に保管します。",
            "zh-TW": "備份以此金鑰加密，私鑰保存在機器以外。",
        },
        stand_in={
            "en": "No backup is encrypted yet.",
            "ja": "まだ暗号化されたバックアップはありません。",
            "zh-TW": "尚無加密備份。",
        },
    ),
    Need(
        key="backup_alarm",
        before=("first_real_night",),
        answers=(("env:TB_BACKUP_MAILTO", "env:TB_BACKUP_ALERT_WATCHER", "env:TB_BACKUP_ALERT_CMD"),),
        who="it",
        title={
            "en": "Who is told when a backup fails",
            "ja": "バックアップが失敗したときに知らせる人",
            "zh-TW": "備份失敗時通知誰",
        },
        why={
            "en": "A failed backup must reach a person the same day.",
            "ja": "失敗したバックアップは、その日のうちに人に伝わる必要があります。",
            "zh-TW": "備份失敗須在當天讓人知道。",
        },
        stand_in={
            "en": "The first administrator, on the health page.",
            "ja": "最初の管理者に、状態のページで知らせます。",
            "zh-TW": "在健康狀態頁通知第一位管理員。",
        },
    ),
    Need(
        key="audit_share",
        before=("first_real_night",),
        answers=(("env:TB_AUDIT_ANCHOR_TARGETS",),),
        who="it",
        title={
            "en": "The hospital's audit share",
            "ja": "病院の監査用共有フォルダー",
            "zh-TW": "醫院的稽核共用資料夾",
        },
        why={
            "en": "A copy of the audit trail's heads that the box itself cannot change.",
            "ja": "この機械自身が変更できない、監査記録の先頭の写しです。",
            "zh-TW": "本機無法更改的稽核紀錄起點副本。",
        },
        stand_in={
            "en": "The heads are kept on this machine only.",
            "ja": "先頭はこの機械の中にだけ保管します。",
            "zh-TW": "起點僅保存在本機。",
        },
    ),
    Need(
        key="site_name",
        before=("first_real_night", "mail_out"),
        answers=(("settings:site.name",),),
        who="trial_office",
        title={
            "en": "The hospital's name",
            "ja": "病院の名前",
            "zh-TW": "醫院名稱",
        },
        why={
            "en": "It is on reports and mail.",
            "ja": "報告書とメールに表示します。",
            "zh-TW": "顯示於報告與郵件。",
        },
        stand_in={
            "en": "A marked stand-in name.",
            "ja": "目印の付いた仮の名前です。",
            "zh-TW": "標記過的暫定名稱。",
        },
    ),
    Need(
        key="office_mailbox",
        before=("study_open", "sae_notice"),
        answers=(("env:TB_SAE_OFFICE_MAILBOX",),),
        who="trial_office",
        title={
            "en": "The trial office's mailbox",
            "ja": "治験事務局のメールアドレス",
            "zh-TW": "試驗辦公室的信箱",
        },
        why={
            "en": "It is told at once of a serious adverse event.",
            "ja": "重篤な有害事象をすぐに知らせます。",
            "zh-TW": "發生嚴重不良事件時立即通知。",
        },
        stand_in={
            "en": "The first administrator's mail.",
            "ja": "最初の管理者のメールアドレスです。",
            "zh-TW": "第一位管理員的信箱。",
        },
    ),
    Need(
        key="mail_relay",
        before=("mail_out", "sae_notice"),
        answers=(("env:SMTP_HOST",),),
        who="it",
        title={
            "en": "The hospital's mail relay",
            "ja": "病院のメール中継サーバー",
            "zh-TW": "醫院的郵件轉送伺服器",
        },
        why={
            "en": "The morning list and the notices are mailed through it.",
            "ja": "朝の一覧と通知はここを通して送ります。",
            "zh-TW": "晨間名單與通知經由它寄出。",
        },
        stand_in={
            "en": "No mail is sent; everything shows in the console.",
            "ja": "メールは送りません。すべてコンソールに表示します。",
            "zh-TW": "不寄送郵件，所有內容顯示於控制台。",
        },
    ),
    Need(
        key="request_mailbox",
        before=("request_mail",),
        answers=(("env:IMAP_HOST",), ("env:TB_MAIL_AUTHSERV_ID",)),
        who="it",
        title={
            "en": "The mailbox for requests, and how its senders are checked",
            "ja": "依頼を受けるメールボックスと、送信者の確認方法",
            "zh-TW": "接收申請的信箱，以及寄件者的驗證方式",
        },
        why={
            "en": "Only mail from a checked sender is read.",
            "ja": "確認できた送信者のメールだけを読みます。",
            "zh-TW": "只讀取經驗證寄件者的郵件。",
        },
        stand_in={
            "en": "Requests are made in the console only.",
            "ja": "依頼はコンソールからだけ受け付けます。",
            "zh-TW": "申請僅能在控制台提出。",
        },
    ),
    Need(
        key="certificate",
        before=("staff_use",),
        answers=(("env:TB_TLS_HOSTNAME",), ("env:TB_TLS_CERT_FILE", "env:TB_TLS_ROOT_CONFIRMED_BY")),
        who="it",
        title={
            "en": "The console's name and certificate",
            "ja": "コンソールの名前と証明書",
            "zh-TW": "控制台的名稱與憑證",
        },
        why={
            "en": "The clinic PCs' browsers trust the box.",
            "ja": "院内の端末のブラウザーがこの機械を信頼します。",
            "zh-TW": "讓院內電腦的瀏覽器信任這台機器。",
        },
        stand_in={
            "en": "The box's own name and certificate.",
            "ja": "この機械自身の名前と証明書です。",
            "zh-TW": "本機自有的名稱與憑證。",
        },
    ),
)

BY_KEY: dict[str, Need] = {n.key: n for n in NEEDS}


def _value(name: str, env: Mapping[str, str], settings: Mapping[str, Any], files: Collection[str]) -> bool:
    """True when ``name`` (``env:``, ``settings:`` or ``file:``) holds a non-empty value."""
    if name.startswith("env:"):
        return bool(str(env.get(name[4:]) or "").strip())
    if name.startswith("file:"):
        return name[5:] in files
    node: Any = settings
    for part in name[len("settings:") :].split("."):
        if not isinstance(node, Mapping):
            return False
        node = node.get(part)
    return node is not None and bool(str(node).strip())


def state(
    need: Need,
    *,
    env: Mapping[str, str],
    settings: Mapping[str, Any] | None = None,
    files: Collection[str] = (),
    stand_ins: Collection[str] = (),
) -> str:
    """``missing``, ``stand_in`` (a value is there, and the caller marks it a stand-in) or ``given``."""
    present = all(any(_value(n, env, settings or {}, files) for n in group) for group in need.answers)
    if not present:
        return "missing"
    return "stand_in" if need.key in stand_ins else "given"


def still_needed(
    *,
    env: Mapping[str, str],
    settings: Mapping[str, Any] | None = None,
    files: Collection[str] = (),
    stand_ins: Collection[str] = (),
    before: str | None = None,
) -> list[tuple[Need, str]]:
    """Each need that is not given, with its state, in the list's order. With ``before``, only those needed before
    that step: what a gate refuses on in PRODUCTION, and what it warns about on a PoC box."""
    if before is not None and before not in STEPS:
        raise ValueError(f"no such step: {before}")
    out = []
    for n in NEEDS:
        if before is not None and before not in n.before:
            continue
        s = state(n, env=env, settings=settings, files=files, stand_ins=stand_ins)
        if s != "given":
            out.append((n, s))
    return out


def all_texts() -> Iterable[tuple[str, str, str]]:
    """(name, language, text) of every text this list shows, for the text checks."""
    for k, t in STEPS.items():
        for lg in LANGS:
            yield f"step.{k}", lg, t.get(lg, "")
    for k, t in WHO.items():
        for lg in LANGS:
            yield f"who.{k}", lg, t.get(lg, "")
    for n in NEEDS:
        for part in ("title", "why", "stand_in"):
            t = getattr(n, part)
            for lg in LANGS:
                yield f"{n.key}.{part}", lg, t.get(lg, "")
