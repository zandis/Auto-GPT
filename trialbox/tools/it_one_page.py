"""The one page for hospital IT, made from the preflight's check list, one per delivered form (10K-18, D-1378).

    python -m tools.it_one_page            # write docs/handover/it-one-page[.it-form].<lang>.md
    python -m tools.it_one_page --check    # exit 1 when a page differs from what the list makes

Review 18 found the page told IT it was asked "only three things" while the IT form asks twelve. The page is now made
from the list the box itself checks (``tb_common.preflight.ITEMS``, D-1361): each item is a line with its label and
the action the box shows when that line is not green, in the page's language, grouped as the list groups them. The
form decides who each item is asked of (:data:`FORMS`):

* ``box``: the box form, the machine its supplier prepares and ships (decision 96, the delivered form): IT is asked
  for the items the site's network and shares answer; the disk, the key protection and the graphics card are the
  supplier's (the box form seals its keys to the TPM or a passphrase the owner sets; Tang is the IT-installed form's).
  Its page keeps the name ``it-one-page.<lang>.md``, which the RUNBOOK and the network sheet link.
* ``it``: the IT form (hospital IT installs the host, RUNBOOK §1): every item is IT's, after RUNBOOK §1's own
  prerequisites (``it-one-page.it-form.<lang>.md``).

Every item of the list is placed in exactly one part of every form (:func:`problems`): a check added to the list and
not placed here fails ``tools/doclint.py``, and so does a page that differs from what the list makes (an edited
label, an edited page). The texts of the items are the list's; only the page's frame is written here.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "libs") not in sys.path:
    sys.path.insert(0, str(ROOT / "libs"))

from tb_common import preflight  # noqa: E402  (the path above: doclint runs this as a plain script's import)

HANDOVER = ROOT / "docs" / "handover"
LANGS = preflight.LANGS
SEP = {"en": ": ", "ja": "：", "zh-TW": "："}  # between an item's label and its action

#: per form, the ids asked of hospital IT and the ids its supplier prepared; together they are the whole list
FORMS: dict[str, dict[str, tuple[str, ...]]] = {
    "box": {
        "it": ("name_cert", "clock", "backup_share", "audit_share", "feed", "mail_relay"),
        "supplier": ("disk", "tpm_tang", "gpu_tier"),
    },
    "it": {
        "it": ("name_cert", "clock", "backup_share", "audit_share", "feed", "mail_relay", "disk", "tpm_tang",
               "gpu_tier"),
        "supplier": (),
    },
}  # fmt: skip

T: dict[str, dict[str, str]] = {
    "title.box": {
        "en": "TrialBox: the one page for hospital IT (a box its supplier prepared)",
        "ja": "TrialBox：病院情報システム部門向けの1ページ（納入業者が準備したボックス）",
        "zh-TW": "TrialBox：給醫院資訊室的一頁說明（由供應商準備好的主機）",
    },
    "title.it": {
        "en": "TrialBox: the one page for hospital IT (a box IT installs)",
        "ja": "TrialBox：病院情報システム部門向けの1ページ（情報システム部門が設置するボックス）",
        "zh-TW": "TrialBox：給醫院資訊室的一頁說明（由資訊室安裝的主機）",
    },
    "reader.box": {
        "en": "**Reader:** hospital IT. The box arrives prepared by its supplier and its owner sets it up from the "
        "console; IT is asked for the {n} things below. The full port table is the [network sheet]({sheet}).",
        "ja": "**Reader:** hospital IT（病院情報システム部門）"
        "。ボックスは納入業者が準備して届き、設定はボックスのオーナーが"
        "コンソールから行います。情報システム部門にお願いするのは以下の{n}点です。ポートの一覧は"
        "[ネットワークシート]({sheet})にあります。",
        "zh-TW": "**Reader:** hospital IT（醫院資訊室）。主機由供應商準備好後送達，由主機負責人（擁有者）在主控台上"
        "設定；需要資訊室協助的是以下 {n} 件事。完整的連接埠表在[網路說明表]({sheet})。",
    },
    "reader.it": {
        "en": "**Reader:** hospital IT. IT installs the host (RUNBOOK §1: the operating system on an encrypted disk, "
        "Docker, the graphics driver); then the box asks IT for the {n} things below. The full port table is the "
        "[network sheet]({sheet}).",
        "ja": "**Reader:** hospital IT（病院情報システム部門）"
        "。情報システム部門がホストを設置します（RUNBOOK §1：暗号化"
        "ディスク上のOS、Docker、GPUドライバー）。その後、ボックスがお願いするのは以下の{n}点です。ポートの一覧は"
        "[ネットワークシート]({sheet})にあります。",
        "zh-TW": "**Reader:** hospital IT（醫院資訊室）。由資訊室安裝主機（RUNBOOK §1：加密磁碟上的作業系統、Docker、"
        "顯示卡驅動程式）；之後主機需要資訊室協助的是以下 {n} 件事。完整的連接埠表在[網路說明表]({sheet})。",
    },
    "made": {
        "en": "Made from the box's own check list (`libs/tb_common/preflight.py`) by `tools/it_one_page.py` "
        "(10K-18, D-1378); do not edit it by hand. The box checks each item itself (`doctor --preflight`, RUNBOOK §1) "
        "and shows it red or amber, with the words below, until it is done.",
        "ja": "ボックス自身の確認項目の一覧（`libs/tb_common/preflight.py`）"
        "から `tools/it_one_page.py` が作成しています"
        "（10K-18, D-1378）。手で編集しないでください。"
        "ボックスは各項目を自分で確認し（`doctor --preflight`、RUNBOOK §1）、"
        "済むまで以下の文とともに赤または黄色で表示します。",
        "zh-TW": "由主機自己的檢查清單（`libs/tb_common/preflight.py`）經 `tools/it_one_page.py` 產生（10K-18, "
        "D-1378）；請勿手動編輯。主機會自行檢查每一項（`doctor --preflight`，RUNBOOK §1），未完成前以紅色或黃色"
        "顯示，並附上下列說明。",
    },
    "asked": {"en": "What IT is asked for", "ja": "情報システム部門へのお願い", "zh-TW": "需要資訊室協助的事項"},
    "supplier": {
        "en": "What the supplier prepared",
        "ja": "納入業者が準備したもの",
        "zh-TW": "供應商已準備的項目",
    },
    "supplier.note": {
        "en": "The box checks these too; nothing is asked of IT. A red line here is the supplier's to fix.",
        "ja": "これらもボックスが確認します。情報システム部門へのお願いはありません。"
        "ここが赤のときは納入業者が対応します。",
        "zh-TW": "主機也會檢查這些項目；不需要資訊室處理。這裡出現紅色時由供應商處理。",
    },
    "firewall": {
        "en": "The address and the firewall line",
        "ja": "アドレスとファイアウォールの設定",
        "zh-TW": "位址與防火牆設定",
    },
    "fw.address": {
        "en": "One fixed address for the box (a reservation in DHCP is enough) and one name for it in the hospital's "
        "DNS: the owner writes it as `TB_TLS_HOSTNAME`, and staff open `https://<that name>`.",
        "ja": "ボックスの固定アドレスを1つ（DHCPの予約で構いません）と、院内DNSの名前を1つ。オーナーはこれを "
        "`TB_TLS_HOSTNAME` に書き、職員はブラウザで `https://<その名前>` を開きます。",
        "zh-TW": "主機的一個固定位址（以 DHCP 保留即可），以及院內 DNS 的一個名稱：擁有者將它填入 "
        "`TB_TLS_HOSTNAME`，同仁以瀏覽器開啟 `https://<該名稱>`。",
    },
    "fw.in": {
        "en": "**In:** TCP 443 to the box, from the clinic PCs' network. Nothing else on the box is reachable.",
        "ja": "**受信：** 診察室のPCのネットワークからボックスへの TCP 443。それ以外にボックスへ届くものはありません。",
        "zh-TW": "**進：** 從診間電腦所在網路到主機的 TCP 443。主機上沒有其他可連入的服務。",
    },
    "fw.out": {
        "en": "**Out:** no internet: updates come on signed media, and the list of trials comes in each update. Only "
        "if the hospital chooses live ClinicalTrials.gov at the install: TCP 443 to `clinicaltrials.gov`.",
        "ja": "**送信：** インターネットは不要です。更新は署名付きの媒体で届き、試験の一覧も更新に含まれます。"
        "インストール時に病院が ClinicalTrials.gov のオンライン利用を"
        "選んだ場合のみ：`clinicaltrials.gov` への TCP 443。",
        "zh-TW": "**出：** 不需要網際網路：更新以簽章媒體送達，試驗清單也隨每次更新提供。只有在安裝時醫院選擇即時"
        "使用 ClinicalTrials.gov 的情況下：到 `clinicaltrials.gov` 的 TCP 443。",
    },
    "fw.hospital": {
        "en": "**Inside the hospital:** UDP 123 to the time server; NFS 2049 or SMB 445 to the backup and audit "
        "shares; the mail relay's port, when one is named.",
        "ja": "**院内：** 時刻サーバーへの UDP 123。バックアップと監査記録の共有フォルダーへの NFS 2049 または "
        "SMB 445。メール中継サーバーを使う場合はそのポート。",
        "zh-TW": "**院內：** 到時間伺服器的 UDP 123；到備份與稽核紀錄共用資料夾的 NFS 2049 或 SMB 445；若指定"
        "郵件轉送伺服器，則為其連接埠。",
    },
    "questions": {
        "en": "Questions about the box go to the box owner first; the owner reaches the box's supplier (RUNBOOK §7).",
        "ja": "ボックスについての質問は、まずオーナーへ。オーナーがボックスの納入業者に連絡します（RUNBOOK §7）。",
        "zh-TW": "關於主機的問題請先洽擁有者；由擁有者聯絡主機供應商（RUNBOOK §7）。",
    },
}


def page_name(form: str, lang: str) -> str:
    """The box form keeps the page's old name (linked from the RUNBOOK and the network sheet)."""
    return f"it-one-page.{lang}.md" if form == "box" else f"it-one-page.{form}-form.{lang}.md"


def _t(key: str, lang: str) -> str:
    return T[key][preflight.lang_of(lang)]


def render(form: str, lang: str, items: Mapping[str, preflight.Item] | None = None) -> str:
    """The page of ``form`` in ``lang``, from the list (``items``: the list's :data:`preflight.BY_ID` by default)."""
    by_id = preflight.BY_ID if items is None else items
    parts = FORMS[form]
    lg = preflight.lang_of(lang)
    asked = [by_id[i] for i in parts["it"] if i in by_id]
    out = [f"# {_t('title.' + form, lg)}", ""]
    out += [_t("reader." + form, lg).format(n=len(asked), sheet=f"network-sheet.{lg}.md"), ""]
    out += [_t("made", lg), "", f"## {_t('asked', lg)}"]
    for group in preflight.GROUPS:
        here = [it for it in asked if it.group == group]
        if not here:
            continue
        out += ["", f"### {preflight.group_label(group, lg)}", ""]
        out += [f"- **{it.label[lg]}**{SEP[lg]}{it.action[lg]}" for it in here]
    supplied = [by_id[i] for i in parts["supplier"] if i in by_id]
    if supplied:
        out += ["", f"## {_t('supplier', lg)}", "", _t("supplier.note", lg), ""]
        out += [f"- {it.label[lg]}" for it in supplied]
    out += ["", f"## {_t('firewall', lg)}", ""]
    out += [f"- {_t(k, lg)}" for k in ("fw.address", "fw.in", "fw.out", "fw.hospital")]
    out += ["", _t("questions", lg)]
    return "\n".join(out) + "\n"


def problems(items: Mapping[str, preflight.Item] | None = None, folder: Path = HANDOVER) -> list[str]:
    """What ``tools/doclint.py`` reports: an item of the list not placed in exactly one part of a form, an id placed
    that the list does not have, a frame text or an item's label or action missing in a language, and a page that
    differs from what the list makes (or is missing). The pages are compared only when the rest is clean."""
    by_id = preflight.BY_ID if items is None else items
    errs: list[str] = []
    for form, parts in FORMS.items():
        placed = [i for ids in parts.values() for i in ids]
        for cid in by_id:
            if placed.count(cid) != 1:
                errs.append(f"tools/it_one_page.py: one-page: the {form} form places check {cid} "
                            f"{placed.count(cid)} times (once: asked of IT or prepared by the supplier)")  # fmt: skip
        errs += [f"tools/it_one_page.py: one-page: the {form} form names {cid}, which the preflight list does not have"
                 for cid in dict.fromkeys(placed) if cid not in by_id]  # fmt: skip
    errs += [f"tools/it_one_page.py: one-page: text {key} has no {lg}" for key, texts in T.items() for lg in LANGS
             if not texts.get(lg, "").strip()]  # fmt: skip
    errs += [f"libs/tb_common/preflight.py: one-page: check {cid} has no {part} in {lg}" for cid, it in by_id.items()
             for part, texts in (("label", it.label), ("action", it.action)) for lg in LANGS
             if not str(texts.get(lg, "")).strip()]  # fmt: skip
    if errs:
        return errs
    for form in FORMS:
        for lg in LANGS:
            page = folder / page_name(form, lg)
            rel = f"docs/handover/{page.name}"
            if not page.is_file():
                errs.append(f"{rel}:1: one-page: missing (python -m tools.it_one_page)")
            elif page.read_text(encoding="utf-8") != render(form, lg, by_id):
                errs.append(f"{rel}:1: one-page: differs from the preflight list (python -m tools.it_one_page)")
    return errs


def write(folder: Path = HANDOVER) -> list[Path]:
    written = []
    for form in FORMS:
        for lg in LANGS:
            p = folder / page_name(form, lg)
            p.write_text(render(form, lg), encoding="utf-8")
            written.append(p)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="compare the pages with the list instead of writing")
    ap.add_argument("--out", type=Path, default=HANDOVER, help="the folder of the pages (docs/handover)")
    a = ap.parse_args(argv)
    if a.check:
        errs = problems(folder=a.out)
        for e in errs:
            print(e)
        print("up to date" if not errs else f"{len(errs)} problem(s)")
        return 1 if errs else 0
    for p in write(a.out):
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
