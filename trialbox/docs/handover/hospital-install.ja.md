# TrialBox: 病院でのインストール

**Reader:** hospital IT（病院のIT担当者）、続いて the box owner（本体の所有者）。

インストールはこのページですべてです。入力するのは 1 行だけです。残りは本体が行い、自分で調べられないことだけを
たずねます。画面とこのページが違うときは画面が正しいので、ベンダーに知らせてください。

## 始める前に用意するもの

- ベンダーが準備した機器。電源と病院のネットワークにつないでおきます。
- ベンダーの USB メモリー。
- 紙の納品書。USB メモリーとは別に届きます。
- 機器の管理者のログイン。
- 機器のディスクの空き 500 GB。
- 後半のための本体の所有者。所有者は、本体とそのデータを管理する人です。

## 病院のIT担当者: USB メモリーからコードまで

1. USB メモリーを機器に差します。管理者でサインインし、端末を開きます。
2. 納品書に印刷された 1 行を、印刷のとおりに入力します。次のような行です。
   ```
   sudo install -m 0700 /media/<user>/TRIALBOX/install /root/trialbox-install && sudo sha256sum /root/trialbox-install | cut -c1-24 | sed 's/..../& /g' && read -r -p 'Same as the sheet? Type yes: ' a && [ "$a" = yes ] && sudo bash /root/trialbox-install /media/<user>/TRIALBOX
   ```
3. 画面に 4 文字ずつ 6 組のコードが表示されます。納品書のインストーラーのコードと比べます。同じなら yes と
   入力します。違うときは Enter を押し、ベンダーに連絡します。
4. 画面に `Vendor key fingerprint:` が表示されます。納品書のベンダー鍵のコードと比べます。同じなら yes と
   入力します。違うときは no と入力し、ベンダーに連絡します。
5. 画面に機器のグラフィックスカード、メモリー、ディスクの空きが表示され、
   `Is this the machine to install TrialBox on? [Y/n]` とたずねられます。この機器で正しければ Enter を押します。
6. 待ちます。読み込みに 10 分から 20 分かかります。その間は何もたずねられません。
7. 画面に `TrialBox set-up:` とアドレス、`One-time code:` が表示されます。両方を本体の所有者に渡します。

## 本体の所有者: 初期設定のページ

1. 病院のネットワーク上のコンピューターのブラウザーで、そのアドレスを開きます。
2. 本体の画面に表示されたコードを入力します。
3. ページの質問に答えます。デモ用の本体に本物の患者データは要りません。
4. パスフレーズをたずねられたら、その機器にはセキュリティチップがありません。12 文字以上のものを決めます。
   安全な場所に保管してください。再起動のたびに本体がたずねます。
5. 「アカウントを作成して完了」を押します。数分待ちます。
6. 本体の画面に `TrialBox is ready:` とアドレスが表示されます。作ったアカウントでログインします。

## 画面が止まったとき

下の各行は、画面の表示と、そのときにすることです。「Nothing was changed」は、機器が元のままだという意味です。

| 画面の表示 | すること |
| --- | --- |
| `run it as the administrator` | 管理者でサインインし、納品書の 1 行をもう一度入力します |
| `the fingerprint was not confirmed: stopped. Nothing was changed.` | ベンダーに連絡します |
| `the vendor key on the stick is not the key this installer was made for` | ベンダーに連絡します |
| `the installer on the stick is not signed by this key` | ベンダーに連絡します |
| `the stick's name has a space or a sign the installer cannot use` | USB メモリーの名前を TRIALBOX に変え、納品書の 1 行をもう一度入力します |
| `the stick must hold exactly one TrialBox release` | ベンダーに連絡します |
| `no answer: stopped. Nothing was changed.` | 納品書の 1 行をもう一度入力し、yes か no で答えます |
| `the bundle's signature does not check with the vendor key` | ベンダーに連絡します |
| `Docker is missing on this machine` | 機器が準備されていません。ベンダーに連絡します |
| `stopped: nothing was changed` | 機器の質問に n と答えました。正しい機器で納品書の 1 行をもう一度入力します |
| `the install stopped` | ベンダーに連絡します。機器はそのままにしておきます |
| `the code was voided (five wrong codes): a new one` | 画面に表示された新しいコードを使います |
| `the set-up is not finished` | ベンダーに連絡します。機器はそのままにしておきます |
| インストールを止めるそのほかの表示 | ベンダーに連絡します。機器はそのままにしておきます |
