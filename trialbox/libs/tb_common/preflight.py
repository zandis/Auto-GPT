"""The live preflight's check list, as data (plan 10 row 10K-3, review 18 SO-3, D-1361).

One list of the checks a site's IT team needs green before the box takes its first night: the box's name and
certificate, the clock, the backup share, the audit share, the hospital's data feed, the mail relay, the disk, the
key protection (TPM or Tang) and the graphics card against the tier record. Each item has a stable id (the name of
the check that answers it, ``tools/trialbox/preflight.py``; ``clock`` is ``doctor``'s own), a group, and its label and
next action in en, ja and zh-TW. ``doctor --preflight`` prints it, the terminal wizard prints it
(``tools/settings_wizard.py --preflight``) and the console's first-run page shows it (``console.firstrun``) from the
file the box installer writes into the first-run folder (:data:`FILE`). Later cards read this list too (the console's
doctor page, the IT one-page): add an item here and its check there, never a text anywhere else.

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
            "en": "Ask hospital IT for a share off the box where the box may add files but the box's administrator "
            "(root) cannot change or delete them (write-once, or root mapped to nobody).",
            "ja": "病院のIT担当者に、ボックスの外の共有フォルダーで、ボックスはファイルを追加できるが、ボックスの"
            "管理者（root）は変更も削除もできないもの（追記のみ、またはrootを無権限に変換する設定）を用意してもらって"
            "ください。",
            "zh-TW": "請醫院資訊人員準備主機以外的共用資料夾：主機可以新增檔案，但主機的管理者（root）不能修改或刪除"
            "（只能寫入一次，或把 root 對應成無權限的使用者）。",
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
        {"en": "Key protection (TPM or Tang)", "ja": "鍵の保護（TPMまたはTang）", "zh-TW": "金鑰保護（TPM 或 Tang）"},
        {
            "en": "Turn on the TPM 2.0 in the box's firmware settings, or ask hospital IT for a Tang server the box "
            "can reach; call the box's supplier if neither is possible.",
            "ja": "ボックスのファームウェア設定でTPM 2.0を有効にするか、病院のIT担当者にボックスから届くTangサーバーを"
            "用意してもらってください。どちらもできない場合はボックスの納入業者に連絡してください。",
            "zh-TW": "請在主機的韌體設定中啟用 TPM 2.0，或請醫院資訊人員提供主機連得到的 Tang 伺服器；"
            "兩者都不行時請聯絡主機供應商。",
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


def action(check_id: str, lang: str) -> str:
    """The next action for a line that is not green, with "then run the check again"; empty for an unknown id."""
    item = BY_ID.get(check_id)
    if item is None:
        return ""
    lg = lang_of(lang)
    return item.action[lg] + AGAIN[lg]


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
    for ln in doc.get("lines") or ():
        if not isinstance(ln, Mapping):
            continue
        cid = str(ln.get("id", ""))
        status = str(ln.get("status", ""))
        status = status if status in STATUSES else "FAIL"
        item = BY_ID.get(cid)
        shown.append({
            "id": cid,
            "group": group_label(item.group if item else "", lang),
            "label": label(cid, lang),
            "status": status,
            "detail": str(ln.get("detail", ""))[:600],
            "action": action(cid, lang) if status != "PASS" else "",
        })  # fmt: skip
    return shown
