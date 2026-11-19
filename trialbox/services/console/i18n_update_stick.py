"""Strings of 10K-7 (D-1363, review 18 SO-7): the update stick on the Operations page's update tab, the verification
result, the Japanese release note and change-impact sheet, the apply in the quiet hour, and which release "return to
the previous release" means. Joined after ``console.i18n_ops``; every key in all three languages. The release note
itself is the vendor's Japanese text and is shown as it is in every language."""

from __future__ import annotations

EN: dict[str, str] = {
    "ops.action.update_cancel": "Cancel this update",
    "ops.confirm.update_cancel": "Cancel the update {bundle} that waits for the quiet hour? It will not run; no"
    "thing on the box changes. You can ask for it again.",
    "ops.state.cancelled": "cancelled",
    "ops.stick.cut": "The stick holds more files than are listed here: only the first bundles by name are shown.",
    "ops.stick.refused": "{n} .tar files on the stick are not listed: their names have letters outside A to Z, "
    "digits, _ . - or a control character, which a bundle's name never has.",
    "ops.update.note.too_large": "The release note kept for this bundle is too large to show here. Ask the vendor.",
    "ops.action.update_stick_check": "Verify and copy to the box",
    "ops.action.update_quiet": "Apply in the quiet hour",
    "ops.confirm.update_stick_check": "Copy the bundle {bundle} from the update stick to the box and verify it? Its "
    "signature and every file are checked. The stick is only read; on the box only the copied file is added.",
    "ops.confirm.update_quiet": "Apply the update {bundle} in the box's quiet hour ({at}, for {hours} hours)? It then "
    "runs without anyone at the box, when no job runs: the box is backed up first, the services stop and restart on "
    "the new release, and if any check fails the box rolls back by itself. If no quiet hour with no job running comes "
    "within {wait} hours, it is not run and you ask again.",
    "ops.stick.title": "The update stick",
    "ops.stick.help": "Insert the update stick at the box, as the hospital's media procedure allows. The box only "
    "reads it. Verify a bundle: it is copied to the box and checked, and its Japanese release note and "
    "change-impact sheet appear under the bundles on this box.",
    "ops.stick.unknown": "The stick's state is not known yet: the box's operations service has not run.",
    "ops.stick.none": "No update stick is inserted (nothing is mounted at {path}).",
    "ops.stick.empty": "The stick holds no bundle (.tar).",
    "ops.stick.sidecar": "the vendor's checksum file is beside it",
    "ops.update.checked": "verified",
    "ops.update.check_failed": "verification failed",
    "ops.update.unchecked": "not verified yet",
    "ops.update.note": "Release note (Japanese)",
    "ops.update.note.none": "This bundle carries no Japanese release note or change-impact sheet that could be read "
    "(a bundle built before they were required). Ask the vendor for them before you apply it.",
    "ops.update.note.verify_first": "Verify the bundle to see its release note and change-impact sheet.",
    "ops.update.impact": "Change-impact sheet",
    "ops.update.impact.class": "Change class",
    "ops.update.impact.changed": "Changed",
    "ops.update.impact.what": "What changed (Japanese)",
    "ops.update.impact.downtime": "The box is down for about {n} minutes",
    "ops.update.impact.migration": "Database migration",
    "ops.update.impact.reapproval": "Rulesets to approve again",
    "ops.update.cc.CC1": "Model-affecting",
    "ops.update.cc.CC2": "Data path",
    "ops.update.cc.CC3": "Interface",
    "ops.update.cc.CC4": "UI and text",
    "ops.update.cc.CC5": "Security fix",
    "ops.update.cc.CC6": "Site configuration",
    "ops.update.waiting": "Waiting for the quiet hour",
    "ops.update.quiet.bad": "The quiet-hour setting {name} does not read: an update asked for the quiet hour waits "
    "and then expires. IT mends the setting (RUNBOOK §5).",
    "ops.update.previous": "Return to the previous release",
    "ops.update.previous.release": "The release before this one",
    "ops.update.previous.none": "No earlier update on this box: the release before is the one installed at set-up.",
    "ops.update.previous.staged": "Its bundle is on the box",
    "ops.update.previous.help": "Going back after a good update applies the previous release's bundle as an older "
    "release. This page does not do that yet: hospital IT and the administrator do it at the box, on the vendor's "
    "written instruction, as RUNBOOK §5 (Older releases) says.",
}

JA: dict[str, str] = {
    "ops.action.update_cancel": "この更新を取り消す",
    "ops.confirm.update_cancel": "静かな時間帯を待っている更新 {bundle} を取り消しますか？実行されず、機器では"
    "何も変わりません。あとで改めて依頼できます。",
    "ops.state.cancelled": "取り消し済み",
    "ops.stick.cut": "USBメモリにはここに表示しきれないファイルがあります。名前順で最初のバンドルだけを表示して"
    "います。",
    "ops.stick.refused": "USBメモリ上の .tar ファイル {n} 件は表示していません。名前に A〜Z、数字、_ . - 以外の"
    "文字または制御文字が含まれ、バンドルの名前ではありません。",
    "ops.update.note.too_large": "このバンドルのリリースノートは大きすぎてここに表示できません。ベンダーに問い"
    "合わせてください。",
    "ops.action.update_stick_check": "検証して機器にコピー",
    "ops.action.update_quiet": "静かな時間帯に適用",
    "ops.confirm.update_stick_check": "バンドル {bundle} を更新用USBメモリから機器にコピーして検証しますか？"
    "署名とすべてのファイルを確認します。USBメモリは読み取るだけで、機器にはコピーしたファイルだけが追加"
    "されます。",
    "ops.confirm.update_quiet": "更新 {bundle} を機器の静かな時間帯（{at} から {hours} 時間）に適用しますか？"
    "その時間に、実行中の処理がなければ、誰も立ち会わずに実行されます。最初にバックアップを取り、サービスを"
    "止めて新しいリリースで再起動し、確認に失敗した場合は自動的に元に戻ります。{wait} 時間以内に処理のない"
    "静かな時間帯が来なければ実行されず、改めて依頼していただきます。",
    "ops.stick.title": "更新用USBメモリ",
    "ops.stick.help": "病院の媒体持込手続きに従い、更新用USBメモリを機器に挿してください。機器は読み取るだけです。"
    "バンドルを検証すると機器にコピーして確認し、日本語のリリースノートと変更影響シートを「この機器にあるバンドル」に"
    "表示します。",
    "ops.stick.unknown": "USBメモリの状態はまだわかりません。機器の運用サービスがまだ動いていません。",
    "ops.stick.none": "更新用USBメモリが挿されていません（{path} に何もマウントされていません）。",
    "ops.stick.empty": "USBメモリにバンドル（.tar）がありません。",
    "ops.stick.sidecar": "ベンダーのチェックサムファイルが添付されています",
    "ops.update.checked": "検証済み",
    "ops.update.check_failed": "検証失敗",
    "ops.update.unchecked": "未検証",
    "ops.update.note": "リリースノート（日本語）",
    "ops.update.note.none": "このバンドルには読み取れる日本語のリリースノートまたは変更影響シートがありません（必須に"
    "なる前に作られたバンドルです）。適用する前にベンダーに求めてください。",
    "ops.update.note.verify_first": "バンドルを検証すると、リリースノートと変更影響シートが表示されます。",
    "ops.update.impact": "変更影響シート",
    "ops.update.impact.class": "変更区分",
    "ops.update.impact.changed": "変更",
    "ops.update.impact.what": "変更内容",
    "ops.update.impact.downtime": "機器の停止時間は約 {n} 分です",
    "ops.update.impact.migration": "データベースの移行",
    "ops.update.impact.reapproval": "選択・除外基準の再承認",
    "ops.update.cc.CC1": "モデルに影響する変更",
    "ops.update.cc.CC2": "データ経路の変更",
    "ops.update.cc.CC3": "外部接続の変更",
    "ops.update.cc.CC4": "画面と文言の変更",
    "ops.update.cc.CC5": "セキュリティ修正",
    "ops.update.cc.CC6": "施設の設定",
    "ops.update.waiting": "静かな時間帯を待っている更新",
    "ops.update.quiet.bad": "静かな時間帯の設定 {name} が読み取れません。静かな時間帯に依頼した更新は待ったあと期限切れ"
    "になります。IT担当が設定を直してください（RUNBOOK §5）。",
    "ops.update.previous": "以前のリリースに戻す",
    "ops.update.previous.release": "このリリースの前のリリース",
    "ops.update.previous.none": "この機器ではこれより前の更新がありません。前のリリースは設置時にインストール"
    "されたものです。",
    "ops.update.previous.staged": "そのバンドルは機器にあります",
    "ops.update.previous.help": "正常に終わった更新のあとで戻すには、以前のリリースのバンドルを古いリリース"
    "として適用します。この画面ではまだ行えません。ベンダーの書面による指示に基づき、RUNBOOK §5（古い"
    "リリース）のとおり、病院のIT担当と管理者が機器で行います。",
}

ZH: dict[str, str] = {
    "ops.action.update_cancel": "取消此更新",
    "ops.confirm.update_cancel": "要取消等待安靜時段的更新 {bundle} 嗎？它不會執行，本機不會有任何變更。之後可"
    "以重新申請。",
    "ops.state.cancelled": "已取消",
    "ops.stick.cut": "隨身碟上的檔案比此處列出的多：只依名稱顯示最前面的更新包。",
    "ops.stick.refused": "隨身碟上有 {n} 個 .tar 檔案未列出：其名稱含有 A 到 Z、數字、_ . - 以外的字元或控制字"
    "元，不是更新包的名稱。",
    "ops.update.note.too_large": "此更新包保存的版本說明太大，無法在此顯示。請洽詢供應商。",
    "ops.action.update_stick_check": "驗證並複製到本機",
    "ops.action.update_quiet": "於安靜時段套用",
    "ops.confirm.update_stick_check": "要將更新包 {bundle} 從更新用隨身碟複製到本機並驗證嗎？將檢查其簽章與每個檔案。"
    "隨身碟只會被讀取；本機只會新增複製的檔案。",
    "ops.confirm.update_quiet": "要在本機的安靜時段（{at} 起 {hours} 小時）套用更新 {bundle} 嗎？屆時若沒有作業在執行，"
    "會在無人在場的情況下執行：先備份，接著停止服務並以新版本重新啟動；任何檢查失敗時會自動還原。若 {wait} 小時內"
    "沒有出現無作業執行的安靜時段，就不會執行，請重新申請。",
    "ops.stick.title": "更新用隨身碟",
    "ops.stick.help": "請依醫院的媒體攜入程序，將更新用隨身碟插入本機。本機只會讀取它。驗證更新包時會先複製到本機"
    "再檢查，其日文版本說明與變更影響表會顯示在「本機上的更新包」之下。",
    "ops.stick.unknown": "尚不知道隨身碟的狀態：本機的維運服務尚未執行。",
    "ops.stick.none": "未插入更新用隨身碟（{path} 沒有掛載任何東西）。",
    "ops.stick.empty": "隨身碟上沒有更新包（.tar）。",
    "ops.stick.sidecar": "旁邊附有供應商的校驗檔",
    "ops.update.checked": "已驗證",
    "ops.update.check_failed": "驗證失敗",
    "ops.update.unchecked": "尚未驗證",
    "ops.update.note": "版本說明（日文）",
    "ops.update.note.none": "此更新包沒有可讀取的日文版本說明或變更影響表（在其成為必要之前建立的更新包）。套用前"
    "請向供應商索取。",
    "ops.update.note.verify_first": "驗證更新包後即可看到其版本說明與變更影響表。",
    "ops.update.impact": "變更影響表",
    "ops.update.impact.class": "變更類別",
    "ops.update.impact.changed": "有變更",
    "ops.update.impact.what": "變更內容（日文）",
    "ops.update.impact.downtime": "本機約停機 {n} 分鐘",
    "ops.update.impact.migration": "資料庫遷移",
    "ops.update.impact.reapproval": "需重新核准的納入／排除條件",
    "ops.update.cc.CC1": "影響模型",
    "ops.update.cc.CC2": "資料路徑",
    "ops.update.cc.CC3": "介面",
    "ops.update.cc.CC4": "畫面與文字",
    "ops.update.cc.CC5": "安全性修正",
    "ops.update.cc.CC6": "站點設定",
    "ops.update.waiting": "等待安靜時段的更新",
    "ops.update.quiet.bad": "安靜時段的設定 {name} 無法讀取：申請於安靜時段執行的更新會等待後逾期。請資訊人員修正設定"
    "（RUNBOOK §5）。",
    "ops.update.previous": "回到前一個版本",
    "ops.update.previous.release": "此版本之前的版本",
    "ops.update.previous.none": "本機在此之前沒有更新：前一個版本就是設置時安裝的版本。",
    "ops.update.previous.staged": "其更新包在本機上",
    "ops.update.previous.help": "在一次成功的更新之後要回去，需將前一個版本的更新包作為較舊版本套用。本頁面尚無法執行："
    "依供應商的書面指示，由醫院資訊人員與管理者在本機上依 RUNBOOK §5（較舊版本）執行。",
}
