# 16. Site standard versions / 院方標準版本 / 医療機関向けの規格バージョン

## en

Plan for the two versions below when integrating with this build. If IT reports only “OMOP” and “FHIR R4”, both site versions remain unconfirmed. Please provide the installed CDM version (for example, `CDM_SOURCE.cdm_version`) and the versioned JP Core profile URL declared for the feed (for example, in `meta.profile`), or the package ID and version from its FHIR specification.

### OMOP CDM 5.4 (DDL `v5.4.2`) — Version used by this build

This build stores clinical facts in PostgreSQL using the OHDSI schema identified by the [DDL pin](../../services/omop/ddl/pin.json).

**OMOP CDM 5.5** adds seven optional fields and three vocabulary metadata tables. One new field, `OBSERVATION.value_as_date`, holds an observation result that is itself a date. The pinned schema has no corresponding column. If IT confirms 5.5, review the mappings that use the new fields before accepting the feed. In particular, check how the result date will be preserved separately from `observation_date`, the date of the observation. [OHDSI v5.5.0 (2026-08-25)](https://github.com/OHDSI/CommonDataModel/releases/tag/v5.5.0) · [Pinned 5.4 DDL](../../services/omop/ddl/OMOPCDM_postgresql_5.4_ddl.sql)

### JP Core (`jp-core.r4#1.1.0`) — Version used by this build

This build uses offline validation rules derived from the [pinned JP Core package](../../services/adapter/validate/jp_core_rules.json).

**JP Core 1.2.0** defines the prescription group number (`rpNumber`) directly in the oral/topical and injection MedicationRequest profiles. In 1.1.0 they inherit that slice from `JP_MedicationRequestBase`. The fixed `rpNumber.system` changes from an OID URN to a JAMI URL. Coverage now distinguishes two insurance identifier slices, `insuranceIdentifier` and `insuranceCsvIdentifier`. If IT declares 1.2.0, check the prescription and Coverage identifier mappings against those slices and review the validation rules before relying on a 1.1.0 validation result. [JAMI 1.2.0 guide (2025-07-30)](https://jpfhir.jp/fhir/core/1.2.0/)

D-417 lists the 1.1.0 value sets used by these rules as “gone” because the 1.2.0 package omits those definitions. The package includes other value sets. A code’s retirement status requires separate evidence. [JAMI 1.2.0 package](https://jpfhir.jp/fhir/core/1.2.0/jp-core.r4-1.2.0.tgz) · [D-417, item 4 (2026-11-11)](../decisions/D-417-standards-conformance-ci.md)

## zh-TW

與本版 TrialBox 整合時，請以下列兩個版本為規劃依據。若院方資訊部門僅提供「OMOP」及「FHIR R4」，院內採用的兩項標準版本都仍待確認。請提供已安裝的 CDM 版本（例如 `CDM_SOURCE.cdm_version`），以及介接資料宣告的 JP Core 設定檔網址與版本（例如含版本號的 `meta.profile`），或該規格指定的 FHIR 套件識別碼與版本。

### OMOP CDM 5.4 (DDL `v5.4.2`) — 本版採用的版本

本版使用 OHDSI 的資料庫結構，將臨床資料存於 PostgreSQL。[DDL 版本紀錄](../../services/omop/ddl/pin.json)

**OMOP CDM 5.5** 新增七個選填欄位及三張記錄詞彙中繼資料的資料表。其中，`OBSERVATION.value_as_date` 用於儲存本身就是日期的觀察結果。本版採用的結構沒有對應欄位。若院方確認使用 5.5，請在接收資料前檢查使用新欄位的對應規則，尤其要確認如何分別保留結果所表示的日期與進行觀察的日期（`observation_date`）。[OHDSI v5.5.0（2026-08-25）](https://github.com/OHDSI/CommonDataModel/releases/tag/v5.5.0) · [本版採用的 5.4 DDL](../../services/omop/ddl/OMOPCDM_postgresql_5.4_ddl.sql)

### JP Core (`jp-core.r4#1.1.0`) — 本版採用的版本

本版的離線驗證規則取自指定版本的 JP Core 套件。[套件版本與驗證規則](../../services/adapter/validate/jp_core_rules.json)

**JP Core 1.2.0** 在內服及外用藥、注射藥兩種 MedicationRequest 設定檔中，直接定義處方內的藥品群組編號（`rpNumber`）。在 1.1.0，這兩種設定檔從 `JP_MedicationRequestBase` 繼承該切片。新版將 `rpNumber.system` 的固定值由 OID URN 改為 JAMI 的 URL。Coverage 現在區分兩種被保險人識別碼切片：`insuranceIdentifier` 與 `insuranceCsvIdentifier`。若院方宣告使用 1.2.0，在採信 1.1.0 的驗證結果前，請依上述切片核對處方與 Coverage 識別碼的欄位對應，並檢視驗證規則。[JAMI 1.2.0 實作指引（2025-07-30）](https://jpfhir.jp/fhir/core/1.2.0/)

D-417 將這些規則使用的 1.1.0 值集列為「已移除」，原因是 1.2.0 套件未收錄這些定義。套件內仍有其他值集。個別代碼是否停用，需另行查證。[JAMI 1.2.0 套件](https://jpfhir.jp/fhir/core/1.2.0/jp-core.r4-1.2.0.tgz) · [D-417 第 4 項（2026-11-11）](../decisions/D-417-standards-conformance-ci.md)

## ja

本ビルドとの連携は、以下の二つのバージョンを前提に計画してください。院内の情報システム部門からの回答が「OMOP」「FHIR R4」のみであれば、どちらのバージョンも未確認です。導入済みの CDM バージョン（例：`CDM_SOURCE.cdm_version`）と、連携仕様で宣言している JP Core プロファイルの URL とバージョン（例：バージョン付きの `meta.profile`）、または同仕様で指定している FHIR パッケージの ID とバージョンを提示してください。

### OMOP CDM 5.4 (DDL `v5.4.2`) — 本ビルドの採用バージョン

本ビルドは OHDSI のスキーマを使い、臨床データを PostgreSQL に保存します。[採用した DDL のバージョン](../../services/omop/ddl/pin.json)

**OMOP CDM 5.5** では、任意項目が七つ、語彙のメタデータを格納するテーブルが三つ追加されました。新しい列 `OBSERVATION.value_as_date` には、観察結果そのものが日付である場合にその値を格納します。本ビルドのスキーマには対応する列がありません。院内で 5.5 の利用が確認された場合は、データを受け入れる前に新しい項目を使うマッピングを見直してください。特に、結果としての日付を観察の実施日（`observation_date`）と区別して保持できるか確認してください。[OHDSI v5.5.0（2026-08-25）](https://github.com/OHDSI/CommonDataModel/releases/tag/v5.5.0) · [本ビルドの 5.4 DDL](../../services/omop/ddl/OMOPCDM_postgresql_5.4_ddl.sql)

### JP Core (`jp-core.r4#1.1.0`) — 本ビルドの採用バージョン

本ビルドのオフライン検証には、指定バージョンの JP Core パッケージから生成したルールを使用します。[パッケージのバージョンと検証ルール](../../services/adapter/validate/jp_core_rules.json)

**JP Core 1.2.0** では、内服・外用薬剤処方と注射薬剤処方の各 MedicationRequest プロファイルが、処方箋内の剤グループを示す Rp 番号（`rpNumber`）を直接定義します。1.1.0 では両プロファイルがこのスライスを `JP_MedicationRequestBase` から継承します。新版では `rpNumber.system` の固定値が OID 形式の URN から JAMI の URL に変わります。Coverage では被保険者の識別子を `insuranceIdentifier` と `insuranceCsvIdentifier` の二つのスライスで区別します。院内の連携仕様が 1.2.0 を宣言している場合は、1.1.0 の検証結果を使う前に、処方と Coverage の識別子のマッピングをこれらのスライスと照合し、検証ルールを見直してください。[JAMI 1.2.0 実装ガイド（2025-07-30）](https://jpfhir.jp/fhir/core/1.2.0/)

D-417 の差分で、検証ルールが参照していた 1.1.0 の値セットが「削除」と表示されるのは、1.2.0 のパッケージにそれらの定義が含まれていないためです。同パッケージには他の値セットが含まれます。個々のコードが廃止されたかどうかは別途確認が必要です。[JAMI 1.2.0 パッケージ](https://jpfhir.jp/fhir/core/1.2.0/jp-core.r4-1.2.0.tgz) · [D-417 第4項（2026-11-11）](../decisions/D-417-standards-conformance-ci.md)
