"""Strings of 10K-7 (D-1363, review 18 SO-7): the update stick on the Operations page's update tab, the verification
result, the Japanese release note and change-impact sheet, the apply in the quiet hour, and which release "return to
the previous release" means. Joined after ``console.i18n_ops``; every key in all three languages. The release note
itself is the vendor's Japanese text and is shown as it is in every language."""

from __future__ import annotations

EN: dict[str, str] = {
    "ops.action.update_cancel": "Cancel this update",
    "ops.confirm.update_cancel": "Cancel the update {bundle} that waits for the quiet hour? It will not run; no"
    "thing on the box changes. A cancel is taken until the moment the update starts, even while a backup runs before "
    "it; once it has started it runs to its end or rolls back by itself. You can ask for it again.",
    "ops.state.cancelled": "cancelled",
    "ops.result.why.unverified": "The box did not apply this update: the request does not name a bundle this box "
    "verified (a request from before this version, or a file verified again since). Verify the bundle and ask again.",
    "ops.stick.cut": "The stick holds more files than are listed here: only the first bundles by name are shown.",
    "ops.stick.refused": "{n} .tar files on the stick are not listed: their names have letters outside A to Z, "
    "digits, _ . - or a control character, which a bundle's name never has.",
    "ops.update.note.too_large": "The release note kept for this bundle is too large to show here. Ask the vendor.",
    "ops.action.update_stick_check": "Verify and copy to the box",
    "ops.action.update_quiet": "Apply in the quiet hour",
    "ops.confirm.update_stick_check": "Copy the bundle {bundle} from the update stick to the box and verify it? Its "
    "signature and every file are checked. The stick is only read; on the box only the copied file is added.",
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
    "ops.status.unreadable": "Status unreadable: the box's operations status file is too large or damaged, so nothing "
    "of it is shown. It is written again within a minute; if this stays, see RUNBOOK §5.",
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
    "ops.update.previous.release": "The release that ran before this one",
    "ops.update.previous.none": "No earlier release is recorded on this box: the release installed at set-up is not "
    "recorded here.",
    "ops.update.previous.staged": "Its bundle is on the box",
    "ops.update.previous.help": "Going back after a good update applies the previous release's bundle as an older "
    "release. This page does not do that yet: hospital IT and the administrator do it at the box, on the vendor's "
    "written instruction, as RUNBOOK §5 (Older releases) says.",
    # the third review of PR #1213 (D-1363)
    "ops.action.update_stick_list": "Look at the update stick",
    "ops.confirm.update_stick_list": "Look at the update stick? The box lists the bundles on it; nothing is copied "
    "or opened. If the stick does not answer within 10 seconds the listing stops and says so.",
    "ops.stick.unlisted": "The stick has not been looked at yet: the box reads it only when you ask.",
    "ops.stick.hung": "The stick did not answer: pull it out and try another stick or port.",
    "ops.stick.listed": "Looked at",
    "ops.update.release": "Signed release",
    "ops.update.release.differs": "The file's name does not carry this signed release: check that it is the release "
    "you expect before you apply it.",
    "ops.update.refuse.installed": "This release is already installed: the installer would refuse it.",
    "ops.update.refuse.older": "This release is older than the installed one: the installer would refuse it.",
    "ops.update.refuse.trust": "The box's trusted vendor keys changed since this check: verify the bundle again.",
    "ops.update.incoming.cut": "More bundles are on the box than are listed here: only the newest are shown.",
    "ops.cancel.recorded": "The cancel is recorded: the update will not run. The box writes its result on its next "
    "pass.",
    "ops.cancelled_by": "cancelled by",
    "ops.confirm.update_apply.signed": "Apply the update {bundle}, signed release {release}? The box is backed up "
    "first, then the services stop and restart on the new release (about 10 to 30 minutes, nobody can work "
    "meanwhile). If any check fails, the box rolls back to the release it runs now by itself.",
    "ops.confirm.update_quiet": "Apply the update {bundle}, signed release {release}, in the box's quiet hour ({at}, "
    "for {hours} hours)? It then runs without anyone at the box, when no job runs: the box is backed up first, the "
    "services stop and restart on the new release, and if any check fails the box rolls back by itself. If no quiet "
    "hour with no job running comes within {wait} hours, it is not run and you ask again.",
}

JA: dict[str, str] = {
    "ops.action.update_cancel": "この更新を取り消す",
    "ops.confirm.update_cancel": "静かな時間帯を待っている更新 {bundle} を取り消しますか？実行されず、機器では"
    "何も変わりません。取り消しは、その前にバックアップが実行中であっても、更新が始まる瞬間まで受け付けます。始まった"
    "あとは最後まで実行されるか、自動的に元に戻ります。あとで改めて依頼できます。",
    "ops.state.cancelled": "取り消し済み",
    "ops.result.why.unverified": "この更新は適用されませんでした。依頼が、この機器で検証済みの"
    "バンドルを指していません（この版より前の依頼か、その後に検証し直したファイルです）。"
    "バンドルを検証してから、もう一度依頼してください。",
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
    "ops.status.unreadable": "状態を読み取れません。機器の運用状態ファイルが大きすぎるか壊れているため、"
    "何も表示しません。1分以内に書き直されます。この表示が続く場合は RUNBOOK §5 を参照してください。",
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
    "ops.update.previous.none": "この機器にはこれより前のリリースの記録がありません。設置時にインストールされた"
    "リリースはここには記録されていません。",
    "ops.update.previous.staged": "そのバンドルは機器にあります",
    "ops.update.previous.help": "正常に終わった更新のあとで戻すには、以前のリリースのバンドルを古いリリース"
    "として適用します。この画面ではまだ行えません。ベンダーの書面による指示に基づき、RUNBOOK §5（古い"
    "リリース）のとおり、病院のIT担当と管理者が機器で行います。",
    # the third review of PR #1213 (D-1363)
    "ops.action.update_stick_list": "更新用USBメモリの中を見る",
    "ops.confirm.update_stick_list": "更新用USBメモリの中を見ますか？機器はその中のバンドルを一覧にするだけで、"
    "コピーも開くこともしません。10 秒以内に応答がなければ一覧を中止し、その旨を表示します。",
    "ops.stick.unlisted": "USBメモリの中はまだ見ていません。機器は依頼されたときだけ読み取ります。",
    "ops.stick.hung": "USBメモリが応答しませんでした。抜いて、別のUSBメモリか別の差込口で試してください。",
    "ops.stick.listed": "確認日時",
    "ops.update.release": "署名されたリリース",
    "ops.update.release.differs": "ファイル名にこの署名されたリリースが含まれていません。適用する前に、期待"
    "どおりのリリースか確認してください。",
    "ops.update.refuse.installed": "このリリースはすでにインストールされています。インストーラーは拒否します。",
    "ops.update.refuse.older": "このリリースはインストール済みのものより古いため、インストーラーは拒否します。",
    "ops.update.refuse.trust": "この確認のあとで機器が信頼するベンダー鍵が変わりました。バンドルをもう一度検証"
    "してください。",
    "ops.update.incoming.cut": "機器にはここに表示しきれないバンドルがあります。新しいものだけを表示しています。",
    "ops.cancel.recorded": "取り消しを記録しました。この更新は実行されません。機器は次の巡回でその結果を書きます。",
    "ops.cancelled_by": "取り消した人",
    "ops.confirm.update_apply.signed": "更新 {bundle}（署名されたリリース {release}）を適用しますか？最初にバック"
    "アップを取り、その後サービスを止めて新しいリリースで再起動します（約10〜30分。その間は誰も作業できません）。確認に"
    "失敗した場合は、自動的に現在のリリースへ戻ります。",
    "ops.confirm.update_quiet": "更新 {bundle}（署名されたリリース {release}）を機器の静かな時間帯（{at} から "
    "{hours} 時間）に適用しますか？その時間に、実行中の処理がなければ、誰も立ち会わずに実行されます。最初に"
    "バックアップを取り、サービスを止めて新しいリリースで再起動し、確認に失敗した場合は自動的に元に戻ります。"
    "{wait} 時間以内に処理のない静かな時間帯が来なければ実行されず、改めて依頼していただきます。",
}

ZH: dict[str, str] = {
    "ops.action.update_cancel": "取消此更新",
    "ops.confirm.update_cancel": "要取消等待安靜時段的更新 {bundle} 嗎？它不會執行，本機不會有任何變更。在更新開"
    "始的那一刻之前都可以取消，即使在它之前正在備份；一旦開始，就會執行到結束，或自動還原。之後可以重新申請。",
    "ops.state.cancelled": "已取消",
    "ops.result.why.unverified": "本機未套用此更新：此請求所指的不是本機已驗證的更新包"
    "（此版本之前的請求，或之後重新驗證過的檔案）。請先驗證更新包，再重新請求。",
    "ops.stick.cut": "隨身碟上的檔案比此處列出的多：只依名稱顯示最前面的更新包。",
    "ops.stick.refused": "隨身碟上有 {n} 個 .tar 檔案未列出：其名稱含有 A 到 Z、數字、_ . - 以外的字元或控制字"
    "元，不是更新包的名稱。",
    "ops.update.note.too_large": "此更新包保存的版本說明太大，無法在此顯示。請洽詢供應商。",
    "ops.action.update_stick_check": "驗證並複製到本機",
    "ops.action.update_quiet": "於安靜時段套用",
    "ops.confirm.update_stick_check": "要將更新包 {bundle} 從更新用隨身碟複製到本機並驗證嗎？將檢查其簽章與每個檔案。"
    "隨身碟只會被讀取；本機只會新增複製的檔案。",
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
    "ops.status.unreadable": "無法讀取狀態：本機的維運狀態檔過大或已損壞，因此不顯示其內容。一分鐘內會重新寫入；"
    "若持續出現，請參閱 RUNBOOK §5。",
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
    "ops.update.previous.none": "本機沒有更早版本的紀錄：設置時安裝的版本未記錄於此。",
    "ops.update.previous.staged": "其更新包在本機上",
    "ops.update.previous.help": "在一次成功的更新之後要回去，需將前一個版本的更新包作為較舊版本套用。本頁面尚無法執行："
    "依供應商的書面指示，由醫院資訊人員與管理者在本機上依 RUNBOOK §5（較舊版本）執行。",
    # the third review of PR #1213 (D-1363)
    "ops.action.update_stick_list": "查看更新用隨身碟",
    "ops.confirm.update_stick_list": "要查看更新用隨身碟嗎？本機只會列出其中的更新包，不會複製或開啟任何檔案。"
    "若隨身碟在 10 秒內沒有回應，列出會停止並顯示原因。",
    "ops.stick.unlisted": "尚未查看隨身碟：本機只在您要求時才讀取它。",
    "ops.stick.hung": "隨身碟沒有回應：請拔出，改用另一個隨身碟或插槽再試。",
    "ops.stick.listed": "查看時間",
    "ops.update.release": "已簽章的版本",
    "ops.update.release.differs": "檔案名稱不含此已簽章的版本：套用前請確認這是您預期的版本。",
    "ops.update.refuse.installed": "此版本已安裝：安裝程式會拒絕它。",
    "ops.update.refuse.older": "此版本比已安裝的版本舊：安裝程式會拒絕它。",
    "ops.update.refuse.trust": "此次驗證之後，本機信任的供應商金鑰已變更：請重新驗證更新包。",
    "ops.update.incoming.cut": "本機上的更新包比此處列出的多：只顯示最新的。",
    "ops.cancel.recorded": "已記錄取消：此更新不會執行。本機會在下一輪寫入其結果。",
    "ops.cancelled_by": "取消者",
    "ops.confirm.update_apply.signed": "要套用更新 {bundle}（已簽章的版本 {release}）嗎？會先備份，接著停止服務並以"
    "新版本重新啟動（約 10 至 30 分鐘，期間無法作業）。若任何檢查失敗，本機會自動還原為目前的版本。",
    "ops.confirm.update_quiet": "要在本機的安靜時段（{at} 起 {hours} 小時）套用更新 {bundle}（已簽章的版本 {release}）"
    "嗎？屆時若沒有作業在執行，會在無人在場的情況下執行：先備份，接著停止服務並以新版本重新啟動；任何檢查失敗時會"
    "自動還原。若 {wait} 小時內沒有出現無作業執行的安靜時段，就不會執行，請重新申請。",
}
