# PRODUCTION_READINESS.md — 本番切り替え(EBAY_ENV=production)チェックリスト

このファイルは `GO_LIVE.md`(段階有効化の詳細な判断基準)を補う、本番切り替え直前に
まとめて確認する短いチェックリストである。**現時点ではどの項目も未着手・未完了でよい。**
チェックを埋める判断は必ず人間が行い、Claude Code(このエージェント自身)が自己判断で
本番設定へ進めることはしない(`GO_LIVE.md`と同じ方針)。

---

## チェックリスト

- [ ] **本番キーセットの取得**(Sandboxとは別に、eBay開発者ポータルで本番用の
      `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` / `EBAY_REDIRECT_URI`(RuName)を取得する。
      Sandboxのキーとは別物であり、使い回せない)。
- [ ] **account deletion通知の登録**: `api/account_deletion.py`が提供する
      `GET|POST /ebay/account-deletion` のURL(外部からeBayが到達できる本番URL)と、
      `.env`の`EBAY_DELETION_VERIFICATION_TOKEN`に設定した値(32〜80文字、英数字と`_`/`-`のみ)を、
      eBay開発者ポータルの「Marketplace Account Deletion/Closure notifications」設定画面に登録する。
      登録時にeBay側がGETでチャレンジを送ってくるため、登録前にこのエンドポイントが外部から
      到達可能な状態(リバースプロキシ経由等)になっている必要がある。このエンドポイントは
      認証不要(eBay側がBasic認証ヘッダーを送れないため)。**外部公開する場合はこのパスだけを
      通し、`/proposals`等の他のエンドポイントは引き続き認証・ネットワーク制御で保護すること。**
- [ ] **本番のビジネスポリシー(支払い/返品/配送)+出荷元ロケーションの作成**:
      `ebay-dropship sandbox setup-selling`と同じロジック(`adapters/ebay/selling_setup.py`)を、
      本番キー・`EBAY_ENV=production`の状態で実行し、本番アカウント用の
      `EBAY_PAYMENT_POLICY_ID` / `EBAY_RETURN_POLICY_ID` / `EBAY_FULFILLMENT_POLICY_ID` /
      `EBAY_MERCHANT_LOCATION_KEY`を取得する(Sandbox用の値とは別に本番用の値が必要)。
      現状`setup-selling`コマンド自体はSandbox専用(`_require_sandbox_env`)のため、本番実行用の
      コマンド追加または一時的な迂回が別途必要(このリポジトリには未実装)。
- [ ] **本番refresh tokenの取得**: `ebay-dropship sandbox get-refresh-token`と同じ
      authorization codeフロー(`adapters/ebay/auth.py`)を`EBAY_ENV=production`で実行し、
      本番用の`EBAY_REFRESH_TOKEN`を取得する(`get-refresh-token`はSandbox/production両対応の
      唯一のsandboxサブコマンドなので、そのまま使える)。
- [ ] **`ENABLE_AUTOMATED_SUPPLIER_PURCHASE`はOFFのまま**にする。実サプライヤーへの自動発注APIは
      このコードベースに実装されていないため(`orders/purchase_channel.py`は
      `ManualOrderPurchaseChannel`=発注パケットの記録のみ)、フラグをTrueにしても何も変わらないが、
      誤解を招く設定変更として先に行わないこと。
- [ ] **発送可能なサプライヤー体制が整うまでpublishは保留する**。有料のサプライヤー連携
      (例: TopDawg等)を確定し、実際に受注が入った際に確実に発送できる体制が整うまで、
      本番アカウントでの`execute-publish --live`は実行しない。
- [ ] **本番投入は段階的に行う**: 最初は「出品1〜2点に限定・人間の承認必須・購入機能OFF」の
      状態で開始し、アラート・監査ログを観察しながら拡大する(詳細は`GO_LIVE.md` (c)(d)参照)。

---

## この段階でやらないこと

- `EBAY_ENV=production`への変更(このファイルのチェックが揃うまで)。
- `execute-publish --live`を本番アカウントに対して実行すること。
- `ENABLE_AUTOMATED_SUPPLIER_PURCHASE=true`への変更。
- 上記いずれも、対応するコード変更は無いため、フラグや値を変えるだけでは実行されない
  (`GO_LIVE.md`の「変更してはいけないこと」と同じ)。

このリポジトリの現在の状態は、上記チェックリストの前提となる**account deletion通知の
受け口を実装したところ**まで(2026-09-05時点)。`EBAY_ENV`は引き続き`sandbox`のまま。
