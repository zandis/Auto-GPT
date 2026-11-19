# Security policy

This repository's maintained product is **TrialBox**, under [`trialbox/`](../trialbox/). The full vulnerability
disclosure policy is
[`trialbox/docs/security/11-vulnerability-disclosure.md`](../trialbox/docs/security/11-vulnerability-disclosure.md)
([日本語](../trialbox/docs/security/11-vulnerability-disclosure-ja.md),
[繁體中文](../trialbox/docs/security/11-vulnerability-disclosure-zh-tw.md)).

## Reporting a vulnerability

- **Email** the address in the `contact` field of
  [`trialbox/deploy/security/contact.json`](../trialbox/deploy/security/contact.json), or use GitHub's private
  vulnerability reporting ("Report a vulnerability" on the Security tab) when it is enabled. The address has not
  been chosen yet; until it is, report through IPA (Japan) or TWCERT/CC (Taiwan), which coordinate with us.
- **Never** open a public issue or pull request for a weakness.
- **Never** put real patient data in a report. **Never** test against a hospital's running TrialBox: test only on
  an installation you run yourself, with the synthetic data in this repository.
- We acknowledge within 2 working days, assess within 10 working days, and agree a publication date with you.
  Good-faith research on your own installation is welcome; the policy's safe-harbour section says what it covers.
- Supported: the newest TrialBox release. Fixes reach a box as a signed offline update bundle.

Code outside `trialbox/` comes from the upstream project this repository was forked from; report weaknesses in it to
that project.

## 脆弱性の報告（日本語）

上記の `contact` 欄のアドレス、または有効化後の GitHub の非公開脆弱性報告でお知らせください。IPA への届出（JPCERT/CC が調整し JVN で公表）もご利用いただけます。報告に実在の患者データを含めないでください。病院で稼働中のボックスでは試験をしないでください。受領の連絡は 2 営業日以内です。詳しくは日本語版ポリシーをご覧ください。

## 通報弱點（繁體中文）

請寄信到上述 `contact` 欄位的信箱，或在啟用後使用 GitHub 的私密弱點通報；也可以向 TWCERT/CC 通報。通報中請勿包含真實病人資料，也請勿對醫院正在運作的設備進行測試。我們會在 2 個工作天內確認收到。詳見繁體中文版政策。
