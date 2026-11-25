# TrialBox：在醫院安裝

**Reader:** hospital IT（醫院資訊人員），接著是 the box owner（主機負責人）。

安裝只需要這一頁。要輸入的只有一行。其餘由主機自己完成，只詢問它自己查不到的事。畫面和本頁不同時，以畫面為準，
並請告訴供應商。

## 開始前要準備的東西

- 供應商準備好的機器，接上電源和醫院的網路。
- 供應商的 USB 隨身碟。
- 紙本的交貨單。它和隨身碟分開送達。
- 機器的管理員登入帳號。
- 機器磁碟上 500 GB 的剩餘空間。
- 第二部分需要主機負責人。負責人是之後照管主機和其資料的人。

## 安裝需要多少磁碟空間

- 隨身碟上有兩個套件：軟體套件和模型套件。第一次安裝會讀取兩者；更新只帶來軟體套件。
- 隨身碟上的內容不會先複製到磁碟：每個部分在隨身碟上檢查後才載入。載入前，畫面會顯示三個大小：安裝後主機的
  大小、載入時最多使用的空間（絕不超過安裝後的大小再加上它的一成），以及隨身碟上的容量。
- 2026 年 11 月 23 日的版本在隨身碟上佔 60.7 GB。上面要求的 500 GB 剩餘空間，也為主機收集的資料留下空間。

## 醫院資訊人員：從隨身碟到登入

1. 把隨身碟插入機器。以管理員登入，打開終端機。
2. 輸入交貨單上印的那一行，一字不差。它看起來像這樣：
   ```
   sudo install -m 0700 /media/<user>/TRIALBOX/install /root/trialbox-install && sudo sha256sum /root/trialbox-install | cut -c1-24 | sed 's/..../& /g' && read -r -p 'Same as the sheet? Type yes: ' a && [ "$a" = yes ] && sudo bash /root/trialbox-install /media/<user>/TRIALBOX
   ```
3. 畫面顯示一組代碼，共六組、每組四個字元。和交貨單上安裝程式的代碼比對。相同就輸入 yes。不同就按 Enter，
   並聯絡供應商。
4. 畫面顯示 `Vendor key fingerprint:`。和交貨單上供應商金鑰的代碼比對。相同就輸入 yes。不同就輸入 no，
   並聯絡供應商。
5. 畫面以 `this machine` 顯示機器的顯示卡、記憶體和磁碟剩餘空間，接著詢問四件事：語言、時區（正確就按 Enter）、
   第一位管理員的郵件地址與姓名，以及只有在機器沒有安全晶片時，一組至少 12 個字元的密語（輸入兩次，不顯示）。
   請把密語存放在安全的地方：每次重新開機，主機都會詢問它。
6. 等待。載入需要 10 到 20 分鐘。之後不再詢問任何事。畫面會列出目前為預設值、之後可以填寫的項目。
7. 畫面只顯示一次管理員的第一組密碼與註冊碼，接著顯示 `TrialBox is ready:` 和位址。把這三樣親手交給管理員。

## 管理員：第一次登入

1. 在醫院網路上的電腦，用瀏覽器打開該位址。資訊室讓電腦信任本機之前，瀏覽器會出現警告，但仍可登入。
2. 用第一組密碼以 admin 登入，並設定自己的密碼。
3. 用註冊碼把本機加入驗證器。註冊碼 24 小時內有效。
4. 在管理頁面打開「尚需填寫的資料」。
5. 填寫您知道的項目。每一項都寫明需要的原因與通常由誰提供。本機會檢查，一兩分鐘內該項目就會從清單消失。
6. 其餘可以之後再填。只有需要該項目的步驟會等待。示範用的主機從不需要真實的病人資料：它顯示示範醫院。

## 畫面停止時

下面每一行是畫面顯示的內容，以及該做的事。「Nothing was changed」表示機器維持原狀。

| 畫面顯示 | 該做的事 |
| --- | --- |
| `run it as the administrator` | 以管理員登入，再輸入一次交貨單上的那一行 |
| `the fingerprint was not confirmed: stopped. Nothing was changed.` | 聯絡供應商 |
| `the vendor key on the stick is not the key this installer was made for` | 聯絡供應商 |
| `the installer on the stick is not signed by this key` | 聯絡供應商 |
| `the stick's name has a space or a sign the installer cannot use` | 把隨身碟改名為 TRIALBOX，再輸入一次交貨單上的那一行 |
| `the stick must hold exactly one TrialBox release` | 聯絡供應商 |
| `no answer: stopped. Nothing was changed.` | 再輸入一次交貨單上的那一行，並回答 yes 或 no |
| `the bundle's signature does not check with the vendor key` | 聯絡供應商 |
| `Docker is missing on this machine` | 機器尚未準備好。聯絡供應商 |
| `the questions were not answered (above): nothing was changed` | 再輸入交貨單上的那一行，並回答四個問題 |
| `the install stopped` | 聯絡供應商。機器保持原狀 |
| `the code was voided (five wrong codes): a new one` | 使用畫面顯示的新代碼 |
| `the set-up is not finished` | 聯絡供應商。機器保持原狀 |
| 其他使安裝停止的訊息 | 聯絡供應商。機器保持原狀 |
