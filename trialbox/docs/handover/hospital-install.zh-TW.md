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

## 醫院資訊人員：從隨身碟到代碼

1. 把隨身碟插入機器。以管理員登入，打開終端機。
2. 輸入交貨單上印的那一行，一字不差。它看起來像這樣：
   ```
   sudo install -m 0700 /media/<user>/TRIALBOX/install /root/trialbox-install && sudo sha256sum /root/trialbox-install | cut -c1-24 | sed 's/..../& /g' && read -r -p 'Same as the sheet? Type yes: ' a && [ "$a" = yes ] && sudo bash /root/trialbox-install /media/<user>/TRIALBOX
   ```
3. 畫面顯示一組代碼，共六組、每組四個字元。和交貨單上安裝程式的代碼比對。相同就輸入 yes。不同就按 Enter，
   並聯絡供應商。
4. 畫面顯示 `Vendor key fingerprint:`。和交貨單上供應商金鑰的代碼比對。相同就輸入 yes。不同就輸入 no，
   並聯絡供應商。
5. 畫面顯示機器的顯示卡、記憶體和磁碟剩餘空間，並詢問
   `Is this the machine to install TrialBox on? [Y/n]`。若是這台機器，就按 Enter。
6. 等待。載入需要 10 到 20 分鐘。這段期間不會詢問任何事。
7. 畫面顯示 `TrialBox set-up:` 和一個位址，以及 `One-time code:`。把兩者交給主機負責人。

## 主機負責人：設定頁面

1. 在醫院網路上的電腦，用瀏覽器打開該位址。
2. 輸入本機螢幕上的代碼。
3. 回答頁面上的問題。示範用的主機從不需要真實的病人資料。
4. 若頁面詢問密語，表示這台機器沒有安全晶片。設定一組至少 12 個字元的密語。請存放在安全的地方：每次重新開機，
   主機都會詢問它。
5. 按「建立我的帳號並完成」。等待幾分鐘。
6. 主機螢幕顯示 `TrialBox is ready:` 和位址。用剛建立的帳號登入。

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
| `stopped: nothing was changed` | 您對機器的問題回答了 n。在正確的機器上再輸入一次交貨單上的那一行 |
| `the install stopped` | 聯絡供應商。機器保持原狀 |
| `the code was voided (five wrong codes): a new one` | 使用畫面顯示的新代碼 |
| `the set-up is not finished` | 聯絡供應商。機器保持原狀 |
| 其他使安裝停止的訊息 | 聯絡供應商。機器保持原狀 |
