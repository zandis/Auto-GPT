# Opt-out notice (オプトアウト通知 / 退出機制公告)

| Field | Value |
| --- | --- |
| Document ID | TB-PRV-05 |
| Version | 0.1 (2026-11-11, T-318, D-411): replaces the notices of `docs/plan/design/14-ethics-pack.md` §4 for the full scope |
| For | the hospital's privacy office and the PI; the hospital publishes its own adapted text |
| Closes | REG-009 (the notice describes every function; the filing place exists) |
| Do not publish before | the opt-out worker (T-206a, T-206b) passes its test on the box: the notice promises that an opted-out patient's records are no longer used, and the box must keep that promise on every path (CR-019, CR-027) |
| Tested by | `tests/unit/test_privacy_docs.py` (each function N1 to N8 has a line in each language) |

The old notices described only "counting and listing candidates". The review found seven functions missing
(REG-009). Each line of the notices below is numbered N1 to N8 so the hospital can check its adapted text against the
list:

| Line | Function the patient is told about |
| --- | --- |
| N1 | the whole-hospital research repository, built from all years of records the hospital names |
| N2 | reading of clinical notes by a language model that runs only inside the hospital |
| N3 | an index of note passages for search (when the hospital turns it on) |
| N4 | a summary per patient (profile) for research staff |
| N5 | identified lists seen by an investigator of another department, after the IRB approves it |
| N6 | the data steward's access to all records to check the data |
| N7 | how long each kind of data is kept |
| N8 | how to opt out, what stops and what cannot be undone |

Placeholders are in brackets. The hospital adds its own logo, numbering and contact lines.

## 1. English (reference)

> **Use of your medical records for finding participants for research**
>
> [Hospital] uses its own medical records to support clinical research at this hospital.
>
> - **N1 What is used.** Records of patients seen at [Hospital] from [first year] onwards (age, sex, conditions,
>   prescriptions, test results, appointments and clinical notes), copied each night into a research database that
>   stays on the hospital's own computers. Names and chart numbers are replaced by codes.
> - **N2 Reading notes.** A computer program (a language model) that runs only inside the hospital reads clinical
>   notes to find the passages that relate to a study's conditions. Nothing is sent outside the hospital.
> - **N3 Search index.** [If turned on:] the database keeps an index of note passages so that staff can search them.
>   The index stays in the hospital and is deleted with the notes.
> - **N4 Summaries.** Research staff may see a short summary of your records, with references to the original
>   passages, when preparing a study visit.
> - **N5 Who sees your name.** A study doctor, also from another department, may see that you are a possible
>   candidate and your chart number, only where the ethics committee approved this for the study. Your own doctor
>   is asked before anyone contacts you. Every such view is recorded.
> - **N6 Data checking.** A data steward named by the hospital may read records to check that the data is correct.
>   Every reading is recorded.
> - **N7 How long.** Lists and reports: [1 year]. Research database copies: [3 nightly and 36 monthly copies].
>   Records of who saw what: [10 years]. Study records that the law requires: as long as the law requires.
> - **N8 Opting out.** If you do not want your records used for this, tell [contact]. From the next night your
>   records are no longer used for counts, lists or summaries. Counts already reported and study records already
>   made cannot be changed. Opting out does not affect your care.
>
> Approved by the [Hospital] [ethics committee / IRB], approval [number], [date].

## 2. 日本語

> **研究参加候補者を探すための診療情報の利用について**
>
> [病院名]では、当院における臨床研究を支援するため、当院の診療情報を利用します。
>
> - **N1 利用する情報** 　[開始年]以降に当院を受診された患者さんの診療情報（年齢、性別、病名、処方、検査結果、
>   受診予定、診療記録）を、毎晩、当院内のコンピュータにある研究用データベースに複製します。氏名とカルテ番号は
>   記号に置き換えます。
> - **N2 診療記録の読み取り** 　当院内だけで動くプログラム（言語モデル）が、研究の参加条件に関係する記載を
>   見つけるために診療記録を読み取ります。院外には何も送りません。
> - **N3 検索用の索引** 　［導入する場合］診療記録の記載を検索するための索引を作成します。索引は院内に置き、
>   記録とともに削除します。
> - **N4 要約** 　研究担当者が来院準備のために、元の記載への参照付きの要約を見ることがあります。
> - **N5 氏名が分かる情報を見る人** 　倫理審査委員会がその研究について承認した場合に限り、他の診療科の研究担当
>   医師を含む研究担当医師が、候補の可能性があることとカルテ番号を見ることがあります。ご連絡の前に必ず主治医の
>   了承を得ます。この閲覧はすべて記録されます。
> - **N6 データの確認** 　病院が指名したデータ管理者が、データが正しいかを確認するために記録を読むことがあり
>   ます。読み取りはすべて記録されます。
> - **N7 保存期間** 　一覧と報告書：[1年]。研究用データベースの複製：[毎晩の3世代と月末の36か月分]。閲覧の記録：
>   [10年]。法令で保存が求められる研究の記録：法令の定める期間。
> - **N8 利用を希望されない場合** 　[連絡先]までお申し出ください。お申し出の翌晩から、人数の集計、一覧、要約に
>   あなたの情報を使いません。すでに報告した人数と作成済みの研究の記録は変更できません。お申し出によって診療上の
>   不利益を受けることはありません。
>
> 本研究は[病院名]倫理審査委員会の承認（承認番号[番号]、[日付]）を得て、病院長の許可のもと実施しています。

## 3. 繁體中文

> **關於使用病歷資料尋找研究參加者之公告**
>
> [醫院名稱]為支援本院的臨床研究，將使用本院自身的病歷資料。
>
> - **N1 使用的資料** 　[起始年份]起於本院就診病人的病歷資料（年齡、性別、疾病、用藥、檢驗結果、預約門診、
>   病歷紀錄），每晚複製到存放於本院電腦內的研究資料庫。姓名與病歷號以代碼取代。
> - **N2 讀取病歷文字** 　僅在本院內運作的電腦程式（語言模型）會讀取病歷紀錄，以找出與研究收案條件相關的段落。
>   不會傳送任何資料到院外。
> - **N3 搜尋索引** 　［如啟用］資料庫會建立病歷段落的搜尋索引，供研究人員搜尋。索引存放於院內，並隨紀錄一併
>   刪除。
> - **N4 摘要** 　研究人員在準備研究訪視時，可能看到附有原始段落出處的病歷摘要。
> - **N5 誰會看到可識別您的資料** 　僅在 IRB 核准該研究這樣做時，研究醫師（包括其他科別的研究醫師）可能看到您
>   是可能的候選人以及您的病歷號。任何人與您聯絡之前，都會先取得您的主治醫師同意。每一次查看都有紀錄。
> - **N6 資料檢查** 　醫院指定的資料管理人可能為確認資料正確而查閱紀錄。每一次查閱都有紀錄。
> - **N7 保存期間** 　名單與報告：[1 年]。研究資料庫的副本：[每晚 3 份及月底 36 個月份]。查看紀錄：[10 年]。
>   法規要求保存的研究紀錄：依法規所定期間。
> - **N8 不同意使用** 　請與[聯絡人]聯繫。自提出後的次日晚上起，您的資料不再用於人數統計、名單或摘要。已報告的
>   人數與已完成的研究紀錄無法變更。不同意使用不會影響您的醫療照護。
>
> 本計畫經[醫院名稱]人體研究倫理審查委員會（IRB）核准（核准編號[編號]，[日期]）。
