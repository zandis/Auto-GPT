# IRB amendment draft, Japan site: TrialBox research repository, patient profiles and whole-hospital pre-screening (TB-SITE-05)

| Field | Value |
| --- | --- |
| Document ID | TB-SITE-05 |
| Version | 0.1 draft (2026-11-09) for the 治験責任医師 and the 治験事務局 / 研究支援部門 to adapt to the committee's template (倫理審査委員会 or 治験審査委員会 as the site's rule requires) |
| File by | **2026-11-20** (owner decision, D-145) for the December meeting, or the January meeting if December is not held; withdraw the parts the committee confirms are already covered |
| Covers | the model-written cited patient profile; the vector store and "patients like this one"; cross-department identified candidate views by the PI and delegated 分担医師 before the 主治医 is asked; the clinician (主治医) role; the data steward's note access; the opt-out notice; the data-handling rule |
| Languages | 日本語 (the submission text) with the English source beside it; the English text is the same as TB-SITE-04 §B except for the hosting and steward lines |

## A. 日本語（提出文書）

### A.1 変更申請の表題

「TrialBox 研究用データベース、患者プロファイル、院内全体の事前スクリーニング」に関する研究計画書の変更（第 2 版、2026 年 11 月）。

### A.2 変更の目的

委員会は、臨床研究の参加条件に合う可能性のある患者を院内で事前にスクリーニングするために TrialBox を用いることを承認した。本変更は、2026 年 11 月 9 日に決定した以下の機能を承認範囲に加えるものである。（1）仮名化データによる院内全体の研究用データベース（OMOP CDM v5.4）、（2）院内の言語モデルが作成し各文がカルテを引用する患者プロファイル、（3）カルテ文章のベクトル索引と「類似患者」検索、（4）診療科をまたぐ識別可能な候補患者の閲覧、（5）主治医の役割、（6）データスチュワードによるカルテ全文の閲覧、（7）オプトアウト通知とデータ取扱規則。

### A.3 変更内容

| # | 項目 | 変更後の内容 |
| --- | --- | --- |
| 1 | **研究用データベース** | 当院の電子カルテ記録（構造化データとカルテ文章、保有する全年度）を、院内に設置した TrialBox 専用機（必要な間は当院が患者データ用に承認したプライベートクラウド）へ毎夜複製する。入口で患者番号を当院の鍵による仮名に置き換え、氏名、保険者番号、電話番号などの直接識別子はデータベースに入らない。形式は OMOP CDM v5.4、用途は当院が承認した研究に限り、院外に出ない。 |
| 2 | **患者プロファイル** | 研究対象患者について、院内 GPU 上の言語モデルが一頁のプロファイル（記録の要約、時系列、表現型、研究適格性）を作成する。各文はカルテ原文を引用し第二のモデルが照合する。引用できる文が 95 % 未満のときは作成しない。閲覧は研究スタッフ（責任医師、分担医師、CRC、データスチュワード）に限り、「研究用途、診断目的ではない」と表示する。誰も編集できない。医師は署名付きの注記を付けられる。個人別検査基準値層と「ギャップ規則」層は責任医師とスチュワードのみが研究用途で閲覧し、主治医には既定で表示しない。 |
| 3 | **ベクトル索引と類似患者** | カルテ文章を分割し埋め込みモデルでベクトル化して院内のデータベース（pgvector）に保存する。「類似患者」は構造化項目で照合したのちベクトルで並べ替え、各結果に説明を付す。検索範囲は利用者の研究または診療関係にある患者に限る。ベクトルは院外に出ない。 |
| 4 | **院内全体の識別可能な事前スクリーニングと診療科横断の候補閲覧** | 研究の参加条件を院内全患者の仮名化データに対して実行する。責任医師および分担医師・協力者リストで委任された分担医師は、スクリーニングで見つかった候補患者（他科の患者を含む）について判断に必要な情報（患者番号と引用されたカルテを含む）を、**主治医の了承を得る前に**閲覧できる。各閲覧は研究、目的、利用者とともに記録され、回数制限がある。患者への声かけは主治医の了承後に責任医師が行う。この診療科横断の識別可能な閲覧の根拠は、当院の診療関係と本委員会の承認である。 |
| 5 | **紹介（主治医への依頼）** | 責任医師または分担医師が TrialBox から主治医へ依頼を送る。主治医が不明な場合は職員名簿からの選択、手入力、「TrialBox 外で調整」、診療科連絡先のいずれかで進める。主治医の回答（紹介に同意／理由を付して辞退／相談）は CRC が記録する。各段階は記録され、スクリーニングログに計上される。 |
| 6 | **主治医の役割** | 研究メンバーでない主治医は、自身の患者（過去 24 か月に受診またはオーダーがある、または今後 90 日以内に予約がある患者。個人情報保護担当は病棟入院患者を加えられる）の記録、時系列、表現型、研究適格性の層を閲覧し、署名付き注記を付けられる。各閲覧は監査記録に残る。 |
| 7 | **データスチュワード** | 当院が指名するデータスチュワードは、コード対応、不一致の解消、データ品質の業務のためにカルテ文章の全文をいつでも閲覧できる。各閲覧は監査記録に残り 10 年保存する。 |
| 8 | **オプトアウト** | 当院は研究利用の拒否方法を（掲示場所）に掲示する。拒否後、数分以内にスクリーニング、プロファイル、ベクトル、今後の出力から除かれ、記録が残る。拒否した患者はいかなる一覧にも現れない。 |
| 9 | **データ取扱規則** | 実患者データは当院のハードウェア（専用機または当院承認のプライベートクラウド）でのみ処理する。供給者 Aimedics は患者データを保持しない。開発者および自動化エージェントは実データに触れず、合成データと当院のテーブル構造・コード一覧のみを用いる。研究チーム外へ出る集計は k = 5 で抑制する（TB-SITE-03）。 |
| 10 | **監査と保存** | 患者データの閲覧、患者番号の表示、出力、署名はすべて人物、役割、理由、時刻とともに記録し 10 年保存する。監査チェーンは毎日署名し、写しを院内共有に保存する。 |
| 11 | **非医療機器の表明** | TrialBox は診断、治療、研究適格性の判定、治療の推奨、医師への警告、患者への連絡を行わない。すべての出力は有資格者が確認する。本ソフトウェアは医療機器ではない。正式運用前に該当性に関する文書化された見解を取得する。 |

### A.4 リスクと保護措置

被験者へのリスクは個人情報に関するものに限られ、臨床的介入はない。保護措置：入口での仮名化、院内処理、役割権限と二要素サインイン、全閲覧の監査、回数制限、オプトアウト、k = 5 の抑制、データの院外不出、供給者による保持なし。

### A.5 添付

データフロー図、オプトアウト通知文、一枚のシステム説明（TB-SITE-02 §B）、データ取扱規則（TB-SITE-03）、スクリーニングログの項目定義。説明同意文書は変更しない（介入を伴わない）。

## B. English source

The English text is identical to TB-SITE-04 §B.1 to §B.5 with two differences: item 1 names the hospital's appliance (or, until it is ready, the hospital's private cloud approved for patient data) instead of the shared B200 platform; item 7 names the hospital's own steward (Makoto) without a second-reviewer clause, since the steward is hospital staff and not the vendor's owner. The data-handling rule (TB-SITE-03), the non-device statement and the audit and retention terms are the same at both sites.
