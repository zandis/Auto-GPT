"""The live preflight's check list, as data (plan 10 row 10K-3, review 18 SO-3, D-1361).

One list of the checks a site's IT team needs green before the box takes its first night: the box's name and
certificate, the clock, the backup share, the audit share, the hospital's data feed, the mail relay, the disk, the
key protection (the TPM, and Tang where the disk unlock uses it) and the graphics card against the tier record. Each
item has a stable id (the name of the check that answers it, ``tools/trialbox/preflight.py``; ``clock`` is
``doctor``'s own), a group, and its label and next action in en, ja and zh-TW. ``doctor --preflight`` prints it, the
terminal wizard prints it (``tools/settings_wizard.py --preflight``) and the console's first-run page shows it
(``console.firstrun``) from the file the box installer writes into the first-run folder (:data:`FILE`). Later cards
read this list too (the console's doctor page, the IT one-page): add an item here and its check there, never a text
anywhere else. ``tools/text_keys.py`` checks every text here (:func:`all_texts`) as it checks the console's.

Standard library only: the console reads it, and so may the host's ``python3``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

FORMAT = "tb-preflight/1"
FILE = "preflight.json"  # in the first-run folder (tb_common.firstrun), written by deploy/box-install.sh
LANGS = ("en", "ja", "zh-TW")
STATUSES = ("PASS", "WARN", "FAIL")

GROUPS: dict[str, dict[str, str]] = {
    "network": {"en": "Network", "ja": "ネットワーク", "zh-TW": "網路"},
    "storage": {"en": "Storage", "ja": "保存先", "zh-TW": "儲存"},
    "data": {"en": "Hospital data", "ja": "病院データ", "zh-TW": "醫院資料"},
    "hardware": {"en": "Hardware", "ja": "ハードウェア", "zh-TW": "硬體"},
}

AGAIN = {
    "en": " Then run the check again.",
    "ja": "その後、もう一度確認してください。",
    "zh-TW": "然後再檢查一次。",
}
#: a check that did not finish in its time (a share or server that does not answer): its detail starts with this,
#: and the line is red with :data:`TIMED_OUT` as its action, never green
TIMEOUT_PREFIX = "timed out"
TIMED_OUT = {
    "en": "A share or server did not answer in time: ask hospital IT whether it is up and reachable from the box.",
    "ja": "共有フォルダーまたはサーバーが時間内に応答しませんでした。病院のIT担当者に、それが動いていてボックスから"
    "届くかどうかを確認してもらってください。",
    "zh-TW": "共用資料夾或伺服器未在時限內回應：請醫院資訊人員確認它是否正常運作、主機是否連得到。",
}
#: a line whose id this list does not know (a newer or damaged file): shown red with this action
UNKNOWN = {
    "en": "This check is not known to this version of the box: call the box's supplier.",
    "ja": "この確認項目はこのバージョンのボックスでは不明です。ボックスの納入業者に連絡してください。",
    "zh-TW": "此版本的主機不認得這項檢查：請聯絡主機供應商。",
}
#: the last line of the printed list
SUMMARY_PASSED = {"en": "preflight passed", "ja": "事前確認はすべて合格です", "zh-TW": "事前檢查全部通過"}
SUMMARY_FAILED = {"en": "{n} check(s) failed", "ja": "{n} 件の確認が不合格です", "zh-TW": "{n} 項檢查未通過"}


@dataclass(frozen=True)
class Item:
    id: str
    group: str
    label: Mapping[str, str]
    action: Mapping[str, str]  # what to do when the line is not green; AGAIN is added when it is shown


ITEMS: tuple[Item, ...] = (
    Item(
        "name_cert",
        "network",
        {"en": "Box name and certificate", "ja": "ボックスの名前と証明書", "zh-TW": "主機名稱與憑證"},
        {
            "en": "Ask hospital IT to add the box's name to the hospital DNS, pointing at the box's address, and, "
            "for a hospital certificate, to issue one that names it.",
            "ja": "病院のIT担当者に、ボックスの名前を院内DNSに登録し（ボックスのアドレスを指すように）、"
            "病院の証明書を使う場合はその名前を含む証明書を発行するよう依頼してください。",
            "zh-TW": "請醫院資訊人員把主機名稱加入院內 DNS（指向主機的位址）；若使用醫院憑證，請簽發含此名稱的憑證。",
        },
    ),
    Item(
        "clock",
        "network",
        {"en": "Clock and time server", "ja": "時計とタイムサーバー", "zh-TW": "時鐘與校時伺服器"},
        {
            "en": "Ask hospital IT to let the box reach the hospital's time server (NTP) and give its address to the "
            "box's supplier; wait until the clock is synchronised.",
            "ja": "病院のIT担当者に、ボックスから院内のタイムサーバー（NTP）に届くようにしてもらい、そのアドレスを"
            "ボックスの納入業者に伝えてください。時計が同期するまで待ってください。",
            "zh-TW": "請醫院資訊人員讓主機連得到院內校時伺服器（NTP），並把位址告訴主機供應商；等時鐘同步。",
        },
    ),
    Item(
        "backup_share",
        "storage",
        {"en": "Backup share", "ja": "バックアップ先の共有フォルダー", "zh-TW": "備份共用資料夾"},
        {
            "en": "Choose a backup place off the box (a second disk or the hospital's share) and ask hospital IT to "
            "give the box write access to it.",
            "ja": "ボックスの外にバックアップ先（2台目のディスクまたは病院の共有フォルダー）を選び、病院のIT担当者に"
            "ボックスからの書き込み権限を設定してもらってください。",
            "zh-TW": "請選擇主機以外的備份位置（第二顆磁碟或醫院的共用資料夾），並請醫院資訊人員給主機寫入權限。",
        },
    ),
    Item(
        "audit_share",
        "storage",
        {"en": "Audit record share", "ja": "監査記録の保管先", "zh-TW": "稽核紀錄共用資料夾"},
        {
            "en": "Ask hospital IT for a write-once (WORM) share off the box: the box may add a file there, but no one "
            "on the box, its administrator (root) included, may change or delete a file once written.",
            "ja": "病院のIT担当者に、ボックスの外にある追記専用（WORM、一度書いたら変更できない）"
            "共有フォルダーを用意してもらってください。ボックスはファイルを追加できますが、ボックスの管理者（root）を含め、書いた後のファイルを"
            "変更・削除できない設定にします。",
            "zh-TW": "請醫院資訊人員準備主機以外的一次寫入（WORM）共用資料夾：主機可以新增檔案，但檔案寫入後，"
            "包括主機管理者（root）在內，任何人都不能修改或刪除。",
        },
    ),
    Item(
        "feed",
        "data",
        {"en": "Hospital data feed", "ja": "病院データの受け取り", "zh-TW": "醫院資料來源"},
        {
            "en": "Ask hospital IT to put the export in the folder the box reads and to let the box read it; the line "
            "shows how many files the box found.",
            "ja": "病院のIT担当者に、ボックスが読み込むフォルダーにデータの出力を置き、ボックスから読めるように"
            "してもらってください。見つかったファイルの数がこの行に表示されます。",
            "zh-TW": "請醫院資訊人員把匯出資料放到主機讀取的資料夾，並讓主機可以讀取；這一行會顯示找到的檔案數。",
        },
    ),
    Item(
        "mail_relay",
        "network",
        {"en": "Mail relay", "ja": "メール中継サーバー", "zh-TW": "郵件轉送伺服器"},
        {
            "en": "Ask hospital IT for the mail relay's name and port, and to accept mail from the box.",
            "ja": "病院のIT担当者に、メール中継サーバーの名前とポート番号を確認し、ボックスからのメールを受け付ける"
            "よう設定してもらってください。",
            "zh-TW": "請向醫院資訊人員確認郵件轉送伺服器的名稱與連接埠，並請其接受來自主機的郵件。",
        },
    ),
    Item(
        "disk",
        "hardware",
        {"en": "Free disk space", "ja": "ディスクの空き容量", "zh-TW": "磁碟剩餘空間"},
        {
            "en": "Free space on the box's disk, or call the box's supplier for a larger disk.",
            "ja": "ボックスのディスクの空きを増やすか、より大きなディスクについて"
            "ボックスの納入業者に連絡してください。",
            "zh-TW": "請清出主機磁碟空間，或聯絡主機供應商更換更大的磁碟。",
        },
    ),
    Item(
        "tpm_tang",
        "hardware",
        {
            "en": "Key protection (TPM; disk unlock with Tang)",
            "ja": "鍵の保護（TPM、ディスク解錠はTangも使用）",
            "zh-TW": "金鑰保護（TPM；磁碟解鎖另需 Tang）",
        },
        {
            "en": "Turn on the TPM 2.0 in the box's firmware settings: the box seals its keys to it. Where the disk "
            "unlock uses Tang, it needs the TPM and one of the hospital's Tang servers answering: ask hospital IT to "
            "let the box reach one. Without a TPM, call the box's supplier.",
            "ja": "ボックスのファームウェア設定でTPM 2.0を有効にしてください。ボックスは鍵をTPMに封印します。"
            "ディスクの解錠にTangを使う場合は、TPMに加えて病院のTangサーバーのどれか一つが応答する必要があります。"
            "病院のIT担当者に、ボックスから届くようにしてもらってください。TPMがない場合はボックスの納入業者に"
            "連絡してください。",
            "zh-TW": "請在主機的韌體設定中啟用 TPM 2.0：主機把金鑰封存在 TPM。若磁碟解鎖使用 Tang，"
            "除了 TPM 還需要醫院的任一台 Tang 伺服器回應：請醫院資訊人員讓主機連得到。沒有 TPM 時請聯絡主機供應商。",
        },
    ),
    Item(
        "gpu_tier",
        "hardware",
        {
            "en": "Graphics card against the tier record",
            "ja": "GPUと性能区分の記録",
            "zh-TW": "顯示卡與等級紀錄",
        },
        {
            "en": "The graphics card or memory is not what this box's tier record names: call the box's supplier "
            "before you go on.",
            "ja": "GPUまたはメモリーが、このボックスの性能区分の記録と一致しません。先に進む前にボックスの納入業者に"
            "連絡してください。",
            "zh-TW": "顯示卡或記憶體與這台主機的等級紀錄不符：請先聯絡主機供應商再繼續。",
        },
    ),
)

BY_ID: dict[str, Item] = {i.id: i for i in ITEMS}
IDS: tuple[str, ...] = tuple(BY_ID)


def lang_of(lang: str | None) -> str:
    """One of :data:`LANGS` (``ja-JP`` is ``ja``, ``zh`` is ``zh-TW``); English otherwise."""
    raw = (lang or "").strip()
    if raw in LANGS:
        return raw
    low = raw.lower()
    if low.startswith("ja"):
        return "ja"
    if low.startswith("zh"):
        return "zh-TW"
    return "en"


def label(check_id: str, lang: str) -> str:
    item = BY_ID.get(check_id)
    return item.label[lang_of(lang)] if item else check_id


def action(check_id: str, lang: str, detail: str = "") -> str:
    """The next action for a line that is not green, with "then run the check again": the check's own, the
    time-out's for a check that did not finish (:data:`TIMEOUT_PREFIX`), :data:`UNKNOWN`'s for an id not listed."""
    item = BY_ID.get(check_id)
    lg = lang_of(lang)
    if item is None:
        return UNKNOWN[lg]
    if detail.startswith(TIMEOUT_PREFIX):
        return TIMED_OUT[lg] + AGAIN[lg]
    return item.action[lg] + AGAIN[lg]


def summary(fails: int, lang: str) -> str:
    lg = lang_of(lang)
    return SUMMARY_FAILED[lg].format(n=fails) if fails else SUMMARY_PASSED[lg]


def all_texts() -> list[tuple[str, str, str]]:
    """Every text of this list as ``(name, language, text)``: what ``tools/text_keys.py`` checks (each one present
    and non-empty in en, ja and zh-TW). 10K-5 and 10K-18 read the same texts."""
    out: list[tuple[str, str, str]] = []
    named: list[tuple[str, Mapping[str, str]]] = [(f"group.{g}", t) for g, t in GROUPS.items()]
    named += [(f"{i.id}.label", i.label) for i in ITEMS] + [(f"{i.id}.action", i.action) for i in ITEMS]
    named += [("again", AGAIN), ("timed_out", TIMED_OUT), ("unknown", UNKNOWN)]
    named += [("summary.passed", SUMMARY_PASSED), ("summary.failed", SUMMARY_FAILED)]
    for name, texts in named:
        out += [(name, lg, texts.get(lg, "")) for lg in LANGS]
    return out


def group_label(group: str, lang: str) -> str:
    return GROUPS.get(group, {}).get(lang_of(lang), group)


def document(lines: Iterable[Mapping[str, Any]], at: str) -> dict[str, Any]:
    """The file the installer writes (:data:`FILE`): each line's id, group, status and the check's own detail."""
    out = []
    for ln in lines:
        cid = str(ln.get("id", ""))
        item = BY_ID.get(cid)
        status = str(ln.get("status", "FAIL"))
        out.append(
            {"id": cid, "group": item.group if item else "", "status": status, "detail": str(ln.get("detail", ""))}
        )
    return {"format": FORMAT, "at": at, "lines": out}


def page_lines(doc: Mapping[str, Any], lang: str) -> list[dict[str, str]]:
    """The lines of a written file as a page shows them, in ``lang``: label, group, status, the check's detail and,
    for a line that is not green, the next action. A line of an unknown status is shown as FAIL (fail closed)."""
    if doc.get("format") != FORMAT:
        return []
    shown = []
    lines = doc.get("lines")
    for ln in lines if isinstance(lines, list) else ():
        if not isinstance(ln, Mapping):
            continue
        cid = str(ln.get("id", ""))[:64]
        item = BY_ID.get(cid)
        status = str(ln.get("status", ""))
        status = status if status in STATUSES and item is not None else "FAIL"  # an unknown id is never green
        detail = str(ln.get("detail", ""))[:600]
        shown.append({
            "id": cid,
            "group": group_label(item.group if item else "", lang),
            "label": label(cid, lang),
            "status": status,
            "detail": detail,
            "action": action(cid, lang, detail) if status != "PASS" else "",
        })  # fmt: skip
    return shown
