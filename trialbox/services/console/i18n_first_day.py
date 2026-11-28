"""Lane H, PoC item 2: the words of "Your first day" (``console.first_day``): a page per role and seven one-page
procedures. A button or page a step names is written as ``{name}`` and filled from the console's own catalogue
(``first_day.LABELS``), so it is the label the screen shows, in the reader's language. Joined into ``console.i18n`` by
``console.i18n_home``. Each language has the same keys and the same placeholders."""

from __future__ import annotations

EN: dict[str, str] = {
    "fd.title": "Your first day",
    "fd.link": "Your first day: short steps for your first tasks",
    "fd.intro": (
        "Short steps for your first tasks. Each button and page is named as it is on the screen. Open a "
        "procedure when you reach that task."
    ),
    "fd.procs": "Your procedures",
    "fd.rules": "Four things to know",
    "fd.steps": "Steps",
    "fd.use": "Use it when",
    "fd.note": "Remember",
    "fd.back": "Back to your first day",
    "fd.open": "Open",
    "fd.today.investigator": "You decide which patients the study approaches and you approve the study's criteria.",
    "fd.today.coordinator": (
        "You prepare the study, call the patients the investigator marks to approach, and record consent and "
        "the visits."
    ),
    "fd.today.steward": "You look after the hospital's nightly data and decide what is held.",
    "fd.today.admin": (
        "You keep the box running: the installation, the nightly feed, the backups and the information the "
        "study still needs."
    ),
    "fd.rule.1": (
        "Only two things stop TrialBox: a software update whose signature does not match, and test data "
        "entering a box that holds real patients. Everything else shows a warning or fixes itself."
    ),
    "fd.rule.2": (
        "A note never takes a patient off the list, and no patient leaves the list. Where a note may speak "
        "against a criterion, the list says so and asks a person to check."
    ),
    "fd.rule.3": "A study cannot open without a backup key. A first night without one shows a warning and goes on.",
    "fd.rule.4": "Consent by a representative (proxy consent) is on by default for a Japanese site and off elsewhere.",
    "fd.proc.install-check.title": "Install check",
    "fd.proc.install-check.use": "The first time you open TrialBox on a device.",
    "fd.proc.install-check.step.1": "{install}",
    "fd.proc.install-check.step.2": (
        "Open the console in the browser and sign in with the account your administrator gave you."
    ),
    "fd.proc.install-check.step.3": "Open {home}. It should open without a certificate warning.",
    "fd.proc.install-check.step.4": (
        "If the browser warns about the certificate, stop and ask hospital IT: the device must trust the "
        "hospital's certificate authority."
    ),
    "fd.proc.install-check.step.5": (
        "Open {help}, then {help_guide}, and read the page for your role. Print it if you like."
    ),
    "fd.proc.install-check.note": "This check changes no data.",
    "fd.proc.first-night.title": "The first night",
    "fd.proc.first-night.use": (
        "After the box is installed and the hospital's feed is connected. For the administrator and the data steward."
    ),
    "fd.proc.first-night.step.1": (
        "The box reads the hospital's SS-MIX2 storage every night. Nothing needs to be clicked for the night to run."
    ),
    "fd.proc.first-night.step.2": (
        "The next morning the administrator opens {data_step}. It shows the newest night in counts only. "
        "Done means the rows went in."
    ),
    "fd.proc.first-night.step.3": (
        "If it says Not done, the night failed or was held. A held night is not lost: the box keeps serving "
        "the night before. The data steward decides it; see “{proc_held}”."
    ),
    "fd.proc.first-night.step.4": (
        "The administrator also opens {still_needed}. If “{backup_key}” is listed, the first night shows a "
        "warning there and goes on. Ask hospital IT to make the key; see “{proc_backup}”."
    ),
    "fd.proc.first-night.step.5": (
        "The data steward opens {data_ops} and checks that the first night's row says it went in."
    ),
    "fd.proc.first-night.note": (
        "Test data must never go into a box that holds real patients. That is one of the two things that stop TrialBox."
    ),
    "fd.proc.approve-study.title": "Approve a study",
    "fd.proc.approve-study.use": (
        "When the study's criteria are ready. The investigator approves; the coordinator prepares."
    ),
    "fd.proc.approve-study.step.1": "Open {home}. A line says criteria wait for your approval. Click {open_approval}.",
    "fd.proc.approve-study.step.2": (
        "Each line is one criterion as the box will check it. Open every amber line with {open_row} and tick "
        "{read_row}."
    ),
    "fd.proc.approve-study.step.3": (
        "The investigator ticks {tick} for each criterion whose codes were checked. The coordinator can "
        "prepare the draft and give each criterion a short label, then click {save_labels}."
    ),
    "fd.proc.approve-study.step.4": "The investigator clicks {approve_all}. The box records who approved and when.",
    "fd.proc.approve-study.step.5": (
        "To open the study: on the study's pages open {state_link}, choose {open_state} under {move_to}, "
        "then click {change_state}."
    ),
    "fd.proc.approve-study.step.6": (
        "If the study does not open because the box has no backup key, ask the administrator to fill in "
        "“{backup_key}” on {still_needed}. A study cannot open without it."
    ),
    "fd.proc.approve-study.note": (
        "Your approval is the study team's check, not a regulated electronic signature. Only the "
        "investigator ticks and approves."
    ),
    "fd.proc.review-list.title": "Review the list",
    "fd.proc.review-list.use": "Each week, and whenever a mail says patients are waiting.",
    "fd.proc.review-list.step.1": "Open {week}. It lists the patients who may fit the study, with their next visit.",
    "fd.proc.review-list.step.2": "Open a patient to see each criterion and the evidence behind it.",
    "fd.proc.review-list.step.3": (
        "A line that says a note may speak against a criterion asks you to check. The patient stays on the list."
    ),
    "fd.proc.review-list.step.4": (
        "The investigator chooses a mark: {approach}, {need_info}, {not_suitable} (it needs a reason), "
        "{not_now} or {ask_doctor}. {undo} takes a mark back."
    ),
    "fd.proc.review-list.step.5": (
        "The coordinator does not mark. You get a task when the investigator marks {approach} or asks for "
        "information. Then go to “{proc_contact}”."
    ),
    "fd.proc.review-list.note": (
        "A mark records a decision. It never removes a patient from the list, and a note never takes one off it."
    ),
    "fd.proc.contact-consent.title": "Contact and consent",
    "fd.proc.contact-consent.use": (
        "After the investigator marks a patient {approach}. The coordinator records; the investigator reads."
    ),
    "fd.proc.contact-consent.step.1": (
        "Open {week}, then the patient. Until the investigator marks {approach}, the page says it is waiting "
        "and records no call."
    ),
    "fd.proc.contact-consent.step.2": (
        "After you call, click {record_call} and choose the outcome: {booked}, {declined}, {not_reached}, "
        "{not_approached} or {lost}. A note is optional."
    ),
    "fd.proc.contact-consent.step.3": (
        "The study may limit the number of attempts and ask for days between them. At the limit, the "
        "investigator decides what follows."
    ),
    "fd.proc.contact-consent.step.4": (
        "When the patient agrees, click {record_consent} and fill in the form. Consent is still taken on the "
        "official form, in your usual process."
    ),
    "fd.proc.contact-consent.step.5": (
        "After consent the person is a participant. Record the next steps (enrolled, a visit, withdrawn) on "
        "the participant's page."
    ),
    "fd.proc.contact-consent.note": (
        "When proxy consent is on, the form also asks for the age at consent, the representative's relation "
        "and the assent. A missing answer shows a warning and does not stop the save. A declined assent "
        "holds the participant until a person goes on with a reason."
    ),
    "fd.proc.backup-restore.title": "Backup and restore",
    "fd.proc.backup-restore.use": (
        "For the administrator, with hospital IT. Before any study opens, and whenever a backup looks wrong."
    ),
    "fd.proc.backup-restore.step.1": (
        "Open {ops}, then the tab {backups_tab}. It lists each backup target and the age of the newest "
        "backup. It turns red after 36 hours without a backup."
    ),
    "fd.proc.backup-restore.step.2": "Click {backup_now} and confirm. The services keep running.",
    "fd.proc.backup-restore.step.3": (
        "Click {backup_check}. It finds a cut or half-written file. Only the private key in IT's sealed "
        "envelope proves the content."
    ),
    "fd.proc.backup-restore.step.4": (
        "If the page says there is no backup key, make one with hospital IT (RUNBOOK §5). The private half "
        "stays off the box. A study cannot open without the backup key."
    ),
    "fd.proc.backup-restore.step.5": (
        "Hospital IT restores a backup from the host with the key from the envelope (RUNBOOK §5). This "
        "console does not restore a backup."
    ),
    "fd.proc.backup-restore.step.6": (
        "After a restore that is not complete, the box holds the patient lists. Open {restore_hold} in the "
        "menu (the page is {flags}), enter again the events recorded after the backup (opt-outs, erasures, "
        "consent changes), then set it to released with a reason."
    ),
    "fd.proc.backup-restore.note": (
        "A backup is encrypted to the hospital's key. Keep the envelope with the private key sealed and off the box."
    ),
    "fd.proc.when-held.title": "What to do when something is held",
    "fd.proc.when-held.use": "When a page says something is held, waiting or kept back.",
    "fd.proc.when-held.step.1": (
        "Read the line. It says what is held and why. Nothing is lost: the box keeps what it showed before."
    ),
    "fd.proc.when-held.step.2": (
        "A night of hospital data (data steward): open {data_ops}, find the night under {held_nights}, "
        "choose {accept} or {reject}, write the {reason} and click {decide}. {reject} keeps the night "
        "before. If {accept} is not offered, reject the night, fix the source and run the night again."
    ),
    "fd.proc.when-held.step.3": (
        "A list held until the site's check is recorded (data steward): the steward records the check. Until "
        "then nobody is listed there."
    ),
    "fd.proc.when-held.step.4": "Lists held after a restore (administrator): see the last step of “{proc_backup}”.",
    "fd.proc.when-held.step.5": (
        "Approach waiting for the treating doctor (coordinator): record the doctor's answer on {referrals}. "
        "Call the patient after the doctor agrees."
    ),
    "fd.proc.when-held.step.6": "Anything else: ask your site's TrialBox administrator. {help} gives the address.",
    "fd.proc.when-held.note": "A held item waits for a person. It does not stop the box.",
}

JA: dict[str, str] = {
    "fd.title": "はじめの一日",
    "fd.link": "はじめの一日：最初の作業の短い手順",
    "fd.intro": (
        "最初の作業の短い手順です。ボタンとページの名前は画面の表示どおりです。その作業になったら、手順を開い"
        "てください。"
    ),
    "fd.procs": "あなたの手順",
    "fd.rules": "知っておくこと（四つ）",
    "fd.steps": "手順",
    "fd.use": "使う場面",
    "fd.note": "覚えておくこと",
    "fd.back": "はじめの一日に戻る",
    "fd.open": "開く",
    "fd.today.investigator": "試験が声をかける患者を決め、試験の基準を承認します。",
    "fd.today.coordinator": "試験の準備をし、責任医師が「声をかける」とした患者に連絡し、同意と来院を記録します。",
    "fd.today.steward": "病院の夜間データを管理し、保留されたものを判断します。",
    "fd.today.admin": (
        "機器の稼働を保ちます。設置、夜間のデータ受信、バックアップ、試験がまだ必要とする情報を扱います。"
    ),
    "fd.rule.1": (
        "TrialBox が止まるのは二つだけです。署名が一致しないソフトウェア更新と、実際の患者を扱う機器にテストデ"
        "ータが入るときです。それ以外は警告を表示するか、自動で直ります。"
    ),
    "fd.rule.2": (
        "ノートが患者をリストから外すことはなく、患者がリストから消えることもありません。ノートが基準に反する"
        "かもしれないときは、リストにそう表示され、人による確認を求めます。"
    ),
    "fd.rule.3": "バックアップ鍵がないと試験は開始できません。鍵がない状態の最初の夜は、警告を表示して続行します。",
    "fd.rule.4": "代諾者による同意（代諾）の記録は、日本の施設では初期設定で有効、それ以外では無効です。",
    "fd.proc.install-check.title": "設置の確認",
    "fd.proc.install-check.use": "端末で初めて TrialBox を開くとき。",
    "fd.proc.install-check.step.1": "{install}",
    "fd.proc.install-check.step.2": "ブラウザーでコンソールを開き、管理者から渡されたアカウントでサインインします。",
    "fd.proc.install-check.step.3": "「{home}」を開きます。証明書の警告なしに開くはずです。",
    "fd.proc.install-check.step.4": (
        "ブラウザーが証明書について警告したら、そこで止めて病院のIT担当に連絡してください。端末が病院の認証局"
        "を信頼している必要があります。"
    ),
    "fd.proc.install-check.step.5": (
        "「{help}」を開き、「{help_guide}」で自分の役割のページを読みます。必要なら印刷します。"
    ),
    "fd.proc.install-check.note": "この確認でデータが変わることはありません。",
    "fd.proc.first-night.title": "最初の夜",
    "fd.proc.first-night.use": "機器の設置と病院のデータ連携の接続が終わったあと。管理者とデータ管理責任者向けです。",
    "fd.proc.first-night.step.1": (
        "機器は毎晩、病院の SS-MIX2 ストレージを読み込みます。夜の処理のためにクリックする操作はありません。"
    ),
    "fd.proc.first-night.step.2": (
        "翌朝、管理者が「{data_step}」を開きます。直近の夜を件数だけで示します。「完了」は行が取り込まれたこと"
        "を表します。"
    ),
    "fd.proc.first-night.step.3": (
        "「未完了」と表示されたら、その夜は失敗したか保留されています。保留された夜は失われず、機器は前の夜の"
        "データを使い続けます。判断はデータ管理責任者が行います。「{proc_held}」を参照してください。"
    ),
    "fd.proc.first-night.step.4": (
        "管理者は「{still_needed}」も開きます。「{backup_key}」が一覧にあれば、最初の夜はそこに警告が表示され"
        "、処理は続行します。病院のIT担当に鍵の作成を依頼してください。「{proc_backup}」を参照してください。"
    ),
    "fd.proc.first-night.step.5": (
        "データ管理責任者は「{data_ops}」を開き、最初の夜の行が取り込み済みになっていることを確認します。"
    ),
    "fd.proc.first-night.note": (
        "テストデータを実際の患者を扱う機器に入れてはいけません。これは TrialBox が止まる二つの場合の一つです。"
    ),
    "fd.proc.approve-study.title": "試験の承認",
    "fd.proc.approve-study.use": "試験の基準が整ったとき。承認は責任医師が行い、CRC が準備します。",
    "fd.proc.approve-study.step.1": (
        "「{home}」を開きます。承認待ちの基準があることを示す行があります。「{open_approval}」をクリックします。"
    ),
    "fd.proc.approve-study.step.2": (
        "各行が、機器が確認する基準一つ分です。黄色の行をすべて「{open_row}」で開き、「{read_row}」にチェック"
        "を入れます。"
    ),
    "fd.proc.approve-study.step.3": (
        "責任医師は、コードを確認した基準ごとに「{tick}」にチェックを入れます。CRC "
        "は下書きを整え、各基準に短い名称を付けて「{save_labels}」をクリックできます。"
    ),
    "fd.proc.approve-study.step.4": (
        "責任医師が「{approve_all}」をクリックします。誰がいつ承認したかが機器に記録されます。"
    ),
    "fd.proc.approve-study.step.5": (
        "試験を開始するには、試験のページで「{state_link}」を開き、「{move_to}」で「{open_state}」を選び、「{change_state}"
        "」をクリックします。"
    ),
    "fd.proc.approve-study.step.6": (
        "機器にバックアップ鍵がなく試験が開始できないときは、管理者に「{still_needed}」の「{backup_key}」の入"
        "力を依頼してください。鍵がないと試験は開始できません。"
    ),
    "fd.proc.approve-study.note": (
        "この承認は試験チームの確認であり、法令上の電子署名ではありません。チェックと承認は責任医師だけが行います。"
    ),
    "fd.proc.review-list.title": "リストの確認",
    "fd.proc.review-list.use": "毎週、また患者が待っているというメールが届いたとき。",
    "fd.proc.review-list.step.1": "「{week}」を開きます。試験に合う可能性のある患者と次回の受診日が並びます。",
    "fd.proc.review-list.step.2": "患者を開くと、基準ごとの内容とその根拠が見えます。",
    "fd.proc.review-list.step.3": (
        "ノートが基準に反するかもしれないと示す行は、確認を求めるものです。患者はリストに残ります。"
    ),
    "fd.proc.review-list.step.4": (
        "責任医師が判断を選びます。「{approach}」「{need_info}」「{not_suitable}」（理由が必要です）「{not_now}"
        "」「{ask_doctor}」。「{undo}」で判断を取り消せます。"
    ),
    "fd.proc.review-list.step.5": (
        "CRC は判断を付けません。責任医師が「{approach}」とするか情報を求めると、タスクが届きます。そのあとは"
        "「{proc_contact}」へ進みます。"
    ),
    "fd.proc.review-list.note": (
        "判断は決定の記録です。患者をリストから外すことはなく、ノートが患者をリストから外すこともありません。"
    ),
    "fd.proc.contact-consent.title": "連絡と同意",
    "fd.proc.contact-consent.use": "責任医師が患者を「{approach}」としたあと。CRC が記録し、責任医師が確認します。",
    "fd.proc.contact-consent.step.1": (
        "「{week}」を開き、患者を開きます。責任医師が「{approach}」とするまでは、待機中と表示され、連絡は記録"
        "できません。"
    ),
    "fd.proc.contact-consent.step.2": (
        "連絡したら「{record_call}」をクリックして結果を選びます。「{booked}」「{declined}」「{not_reached}」"
        "「{not_approached}」「{lost}」。メモは任意です。"
    ),
    "fd.proc.contact-consent.step.3": (
        "試験によっては、連絡の回数に上限があり、連絡の間隔の日数を求めます。上限に達したら、次の対応は責任医"
        "師が決めます。"
    ),
    "fd.proc.contact-consent.step.4": (
        "患者が同意したら「{record_consent}」をクリックして記録します。同意の取得は、これまでどおり正式な同意"
        "書で行います。"
    ),
    "fd.proc.contact-consent.step.5": (
        "同意後は被験者になります。次の段階（登録、来院、中止）は被験者のページに記録します。"
    ),
    "fd.proc.contact-consent.note": (
        "代諾の記録が有効なときは、同意時の年齢、代諾者の続柄、アセントも入力します。未入力は警告が出るだけで"
        "、保存は止まりません。アセントが拒否された場合は、担当者が理由を付けて先へ進めるまで、被験者は保留さ"
        "れます。"
    ),
    "fd.proc.backup-restore.title": "バックアップと復元",
    "fd.proc.backup-restore.use": (
        "管理者が病院のIT担当と行います。試験を開始する前、またバックアップがおかしいと感じたとき。"
    ),
    "fd.proc.backup-restore.step.1": (
        "「{ops}」を開き、「{backups_tab}」タブを開きます。保存先ごとに、最新のバックアップからの経過時間が表"
        "示されます。36時間バックアップがないと赤になります。"
    ),
    "fd.proc.backup-restore.step.2": "「{backup_now}」をクリックして確認します。サービスは動いたままです。",
    "fd.proc.backup-restore.step.3": (
        "「{backup_check}」をクリックします。途切れたファイルや書きかけのファイルが見つかります。中身まで確か"
        "められるのは、IT担当の封筒にある秘密鍵だけです。"
    ),
    "fd.proc.backup-restore.step.4": (
        "バックアップ鍵がないと表示されたら、病院のIT担当と作成します（RUNBOOK "
        "§5）。秘密鍵は機器の外に置きます。バックアップ鍵がないと試験は開始できません。"
    ),
    "fd.proc.backup-restore.step.5": (
        "バックアップの復元は、病院のIT担当が機器のホストから、封筒の鍵を使って行います（RUNBOOK "
        "§5）。このコンソールからは復元しません。"
    ),
    "fd.proc.backup-restore.step.6": (
        "復元が完了しなかった場合、機器は患者リストを保留します。メニューの「{restore_hold}」（ページ名は「{flags}"
        "」）を開き、バックアップのあとに記録された出来事（オプトアウト、削除、同意の変更）を入力し直してから"
        "、理由を付けて解除にします。"
    ),
    "fd.proc.backup-restore.note": (
        "バックアップは病院の鍵で暗号化されます。秘密鍵の入った封筒は封をしたまま、機器の外に保管してください。"
    ),
    "fd.proc.when-held.title": "保留されたときの対応",
    "fd.proc.when-held.use": "ページに、保留、待機、見合わせと表示されたとき。",
    "fd.proc.when-held.step.1": (
        "その行を読みます。何が、なぜ保留されたかが書かれています。失われるものはなく、機器は前の表示を保っています。"
    ),
    "fd.proc.when-held.step.2": (
        "病院データの夜（データ管理責任者）：「{data_ops}」を開き、「{held_nights}」で該当の夜を探し、「{accept}"
        "」か「{reject}」を選び、「{reason}」を書いて「{decide}」をクリックします。「{reject}」は前の夜を残し"
        "ます。「{accept}」が選べないときは、その夜を却下し、元のデータを直してから夜の処理をやり直します。"
    ),
    "fd.proc.when-held.step.3": (
        "施設の確認が記録されるまで保留されるリスト（データ管理責任者）：確認はデータ管理責任者が記録します。"
        "それまでは誰も載りません。"
    ),
    "fd.proc.when-held.step.4": "復元後に保留されたリスト（管理者）：「{proc_backup}」の最後の手順を参照してください。",
    "fd.proc.when-held.step.5": (
        "主治医の同意待ちの「声をかける」（CRC）：「{referrals}」に主治医の回答を記録します。主治医が同意して"
        "から患者に連絡します。"
    ),
    "fd.proc.when-held.step.6": "それ以外：施設の TrialBox 管理者に連絡してください。「{help}」に連絡先があります。",
    "fd.proc.when-held.note": "保留されたものは、人の判断を待ちます。機器全体が止まることはありません。",
}

ZH: dict[str, str] = {
    "fd.title": "第一天上手",
    "fd.link": "第一天上手：最初幾項工作的簡短步驟",
    "fd.intro": "最初幾項工作的簡短步驟。按鈕與頁面名稱都與畫面上的相同。做到該項工作時，再開啟對應的程序。",
    "fd.procs": "您的程序",
    "fd.rules": "請先知道的四件事",
    "fd.steps": "步驟",
    "fd.use": "使用時機",
    "fd.note": "請記得",
    "fd.back": "回到第一天上手",
    "fd.open": "開啟",
    "fd.today.investigator": "您決定本試驗要邀請哪些病人，並核准試驗的條件。",
    "fd.today.coordinator": "您準備試驗，聯絡主持人標記為「邀請」的病人，並記錄同意與訪視。",
    "fd.today.steward": "您負責醫院的夜間資料，並決定哪些資料要保留處理。",
    "fd.today.admin": "您讓機器持續運作：安裝、夜間資料傳入、備份，以及試驗尚需的資料。",
    "fd.rule.1": (
        "TrialBox 只會在兩種情況停止：軟體更新的簽章不符，以及測試資料進入存有真實病人的機器。其他情況只會顯示"
        "警告或自動修正。"
    ),
    "fd.rule.2": (
        "病歷記載不會讓病人退出名單，也沒有病人會從名單中消失。病歷記載可能與某項條件不符時，名單會標示，並請人員確認。"
    ),
    "fd.rule.3": "沒有備份金鑰，試驗無法開始。沒有備份金鑰的第一晚會顯示警告，並繼續進行。",
    "fd.rule.4": "由法定代理人同意（代理同意）的紀錄，日本的院所預設開啟，其他地區預設關閉。",
    "fd.proc.install-check.title": "安裝檢查",
    "fd.proc.install-check.use": "第一次在裝置上開啟 TrialBox 時。",
    "fd.proc.install-check.step.1": "{install}",
    "fd.proc.install-check.step.2": "在瀏覽器開啟主控台，使用管理者給您的帳號登入。",
    "fd.proc.install-check.step.3": "開啟「{home}」。應該不會出現憑證警告。",
    "fd.proc.install-check.step.4": (
        "瀏覽器若出現憑證警告，請先停止，並詢問醫院資訊人員：裝置必須信任醫院的憑證授權單位。"
    ),
    "fd.proc.install-check.step.5": "開啟「{help}」，再點「{help_guide}」，閱讀您角色的頁面。需要時可以列印。",
    "fd.proc.install-check.note": "這項檢查不會更動任何資料。",
    "fd.proc.first-night.title": "第一晚",
    "fd.proc.first-night.use": "機器安裝完成、醫院的資料傳入也已連接之後。適用管理者與資料管理員。",
    "fd.proc.first-night.step.1": "機器每晚讀取醫院的 SS-MIX2 儲存區。夜間作業不需要任何點選。",
    "fd.proc.first-night.step.2": (
        "隔天早上，管理者開啟「{data_step}」。頁面只以數量顯示最近一晚的結果。「完成」表示資料列已匯入。"
    ),
    "fd.proc.first-night.step.3": (
        "若顯示「未完成」，表示那一晚失敗或被保留。被保留的那一晚不會遺失，機器會繼續使用前一晚的資料。由資料"
        "管理員決定；請見「{proc_held}」。"
    ),
    "fd.proc.first-night.step.4": (
        "管理者也開啟「{still_needed}」。若列出「{backup_key}」，第一晚會在該處顯示警告，並繼續進行。請醫院資"
        "訊人員建立金鑰；請見「{proc_backup}」。"
    ),
    "fd.proc.first-night.step.5": "資料管理員開啟「{data_ops}」，確認第一晚的那一列顯示已匯入。",
    "fd.proc.first-night.note": "測試資料絕不可進入存有真實病人的機器。這是 TrialBox 會停止的兩種情況之一。",
    "fd.proc.approve-study.title": "核准試驗",
    "fd.proc.approve-study.use": "試驗的條件備妥時。由試驗主持人核准，研究護理師負責準備。",
    "fd.proc.approve-study.step.1": "開啟「{home}」。有一行說明有條件等待您核准。點選「{open_approval}」。",
    "fd.proc.approve-study.step.2": (
        "每一行是機器要檢查的一項條件。用「{open_row}」開啟每一條琥珀色的行，並勾選「{read_row}」。"
    ),
    "fd.proc.approve-study.step.3": (
        "試驗主持人對已確認代碼的每項條件勾選「{tick}」。研究護理師可先整理草稿，為每項條件加上簡短名稱，再點"
        "選「{save_labels}」。"
    ),
    "fd.proc.approve-study.step.4": "試驗主持人點選「{approve_all}」。機器會記錄誰在何時核准。",
    "fd.proc.approve-study.step.5": (
        "要開始試驗：在該試驗的頁面開啟「{state_link}」，在「{move_to}」選擇「{open_state}」，再點選「{change_state}"
        "」。"
    ),
    "fd.proc.approve-study.step.6": (
        "若機器沒有備份金鑰而無法開始試驗，請管理者在「{still_needed}」填寫「{backup_key}」。沒有備份金鑰，試"
        "驗無法開始。"
    ),
    "fd.proc.approve-study.note": "您的核准是試驗團隊的確認，不是法規上的電子簽章。只有試驗主持人勾選與核准。",
    "fd.proc.review-list.title": "查看名單",
    "fd.proc.review-list.use": "每週一次，以及收到通知有病人在等待時。",
    "fd.proc.review-list.step.1": "開啟「{week}」。名單列出可能符合試驗的病人及其下次門診。",
    "fd.proc.review-list.step.2": "開啟病人，可看到每項條件及其依據。",
    "fd.proc.review-list.step.3": "標示病歷記載可能與某項條件不符的那一行，是請您確認。病人仍留在名單中。",
    "fd.proc.review-list.step.4": (
        "試驗主持人選擇標記：「{approach}」「{need_info}」「{not_suitable}」（需填寫原因）「{not_now}」「{ask_doctor}"
        "」。「{undo}」可收回標記。"
    ),
    "fd.proc.review-list.step.5": (
        "研究護理師不做標記。試驗主持人標記為「{approach}」或要求查詢時，您會收到任務。接著請看「{proc_contact}」。"
    ),
    "fd.proc.review-list.note": "標記只是記錄一項決定。它不會把病人從名單中移除，病歷記載也不會讓病人退出名單。",
    "fd.proc.contact-consent.title": "聯絡與同意",
    "fd.proc.contact-consent.use": "試驗主持人將病人標記為「{approach}」之後。由研究護理師記錄，試驗主持人查閱。",
    "fd.proc.contact-consent.step.1": (
        "開啟「{week}」，再開啟病人。在試驗主持人標記「{approach}」之前，頁面會顯示等待中，且不能記錄聯絡。"
    ),
    "fd.proc.contact-consent.step.2": (
        "聯絡之後，點選「{record_call}」並選擇結果：「{booked}」「{declined}」「{not_reached}」「{not_approached}"
        "」「{lost}」。備註可填可不填。"
    ),
    "fd.proc.contact-consent.step.3": (
        "試驗可能限制聯絡次數，並要求兩次聯絡之間間隔數日。達到上限後，由試驗主持人決定後續。"
    ),
    "fd.proc.contact-consent.step.4": (
        "病人同意後，點選「{record_consent}」並填寫。取得同意仍依原有流程，使用正式的同意書。"
    ),
    "fd.proc.contact-consent.step.5": "同意後，此人成為受試者。下一個階段（已收案、訪視、退出）請記錄在受試者的頁面。",
    "fd.proc.contact-consent.note": (
        "開啟代理同意時，表單也會詢問同意時的年齡、代理人與受試者的關係，以及受試者本人的認可（assent）。漏填"
        "只會顯示警告，不會阻止儲存。若受試者拒絕認可，在有人填寫原因並讓其繼續之前，該受試者會被保留。"
    ),
    "fd.proc.backup-restore.title": "備份與還原",
    "fd.proc.backup-restore.use": "由管理者與醫院資訊人員進行。任何試驗開始之前，以及備份看起來不對時。",
    "fd.proc.backup-restore.step.1": (
        "開啟「{ops}」，再開啟「{backups_tab}」分頁。頁面列出每個備份目的地與最新備份的時間。超過 36 "
        "小時沒有備份會轉為紅色。"
    ),
    "fd.proc.backup-restore.step.2": "點選「{backup_now}」並確認。服務會持續運作。",
    "fd.proc.backup-restore.step.3": (
        "點選「{backup_check}」。它能找出被截斷或寫到一半的檔案。只有資訊人員信封中的私鑰，才能證明內容正確。"
    ),
    "fd.proc.backup-restore.step.4": (
        "若頁面顯示沒有備份金鑰，請與醫院資訊人員一起建立（RUNBOOK §5）。私鑰保存在機器以外。沒有備份金鑰，試"
        "驗無法開始。"
    ),
    "fd.proc.backup-restore.step.5": (
        "還原備份由醫院資訊人員在主機上，使用信封中的金鑰進行（RUNBOOK §5）。本主控台不會還原備份。"
    ),
    "fd.proc.backup-restore.step.6": (
        "還原未完成時，機器會保留病人名單。請開啟選單的「{restore_hold}」（頁面為「{flags}」），重新輸入備份之"
        "後記錄的事項（退出登記、刪除、同意的變更），再填寫原因並設為已解除。"
    ),
    "fd.proc.backup-restore.note": "備份以醫院的金鑰加密。存放私鑰的信封請保持封緘，並放在機器以外。",
    "fd.proc.when-held.title": "有項目被保留時怎麼辦",
    "fd.proc.when-held.use": "頁面顯示有項目被保留、等待或暫緩時。",
    "fd.proc.when-held.step.1": (
        "先讀那一行，它會說明什麼被保留、為什麼。不會有任何東西遺失，機器仍維持先前顯示的內容。"
    ),
    "fd.proc.when-held.step.2": (
        "一晚的醫院資料（資料管理員）：開啟「{data_ops}」，在「{held_nights}」找到那一晚，選擇「{accept}」或「"
        "{reject}」，填寫「{reason}」並點選「{decide}」。「{reject}」會保留前一晚的資料。若沒有「{accept}」可"
        "選，請拒絕該晚、修正來源，再重新執行該晚。"
    ),
    "fd.proc.when-held.step.3": (
        "在院所的檢查記錄之前被保留的名單（資料管理員）：由資料管理員記錄該項檢查。在此之前，名單中不會列出任何人。"
    ),
    "fd.proc.when-held.step.4": "還原後被保留的名單（管理者）：請見「{proc_backup}」的最後一個步驟。",
    "fd.proc.when-held.step.5": (
        "等待主治醫師同意的「邀請」（研究護理師）：在「{referrals}」記錄醫師的回覆。醫師同意後再聯絡病人。"
    ),
    "fd.proc.when-held.step.6": "其他情況：請詢問院所的 TrialBox 管理者。「{help}」提供聯絡方式。",
    "fd.proc.when-held.note": "被保留的項目是在等人處理，不會讓整台機器停止。",
}
