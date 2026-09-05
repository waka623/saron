# GO_LIVE.md — 本番投入(go-live)チェックリスト

このファイルは、各フェーズの `DECISIONS.md` に積み上げた「本番投入前の必須ゲート」TODO を1つに集約したものである。
**実キー・実サプライヤーが整うまで、このファイルのチェックは1つも埋まらない想定でよい。**
チェックを埋める判断(段階有効化を含む)は必ず人間が行う。Claude Code(このエージェント自身)が
このチェックリストを自己判断で「完了」にして本番設定へ進めることはしない。

---

## (a) 各フェーズのTODOの集約(このリポジトリで積み上げてきたもの)

| # | 出典フェーズ | 内容 | 現状 |
|---|---|---|---|
| 1 | Phase 1/3/4/5 | OAuth・Browse・Inventory(publish/price_change)・Fulfillment(getOrders)の実Sandbox疎通 | 未実施(モックのみ) |
| 2 | Phase 5 | サプライヤーへの自動発注(`enable_automated_supplier_purchase`) | 未実装・フラグ`False`固定 |
| 3 | Phase 6 | 実 Analytics API(`get_rate_limits`含む)疎通 | 未実施(フィクスチャのみ)。上記1と合わせて実施 |

すべて `EBAY_ENV=production` および `ENABLE_AUTOMATED_SUPPLIER_PURCHASE=true` への変更を
正当化する前提条件であり、以下(b)〜(d)を順に完了させるまでは変更しない。

---

## (b) 実キー到着後にやること: モックで通した各E2Eを実Sandboxで通す

実 Sandbox 認証情報(`EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` / `EBAY_REFRESH_TOKEN`)を `.env` に設定した後、
**以下すべてを実 Sandbox に対して実行し、成功を確認する**(コードは実装済み。これまではモックで検証してきた)。
`ebay-dropship sandbox ...`(2026-08-31追加)が各項目を実行するCLIコマンドを提供する
(`EBAY_ENV=production`では全コマンドを拒否するSandbox専用。トークン自体は出力しない)。

**`EBAY_REFRESH_TOKEN`がまだ無い場合**: eBayの「Get a User Token」ツール(開発者ポータル)は
access token(2時間)のみを返しrefresh_token(18か月)は返さない。
`ebay-dropship sandbox get-refresh-token` がauthorization codeフローを対話的に実行し、
取得したrefresh_tokenを`.env`の`EBAY_REFRESH_TOKEN=`に自動保存する
(このコマンドのみ`EBAY_ENV`に応じてSandbox/production両対応。トークン値は出力しない)。

- [ ] **OAuth**: `ebay-dropship sandbox check-auth` がトークンを取得できる
      (`adapters/ebay/auth.py`。テストは `tests/test_ebay_auth.py` で仕組みをモック検証済み)。
- [ ] **Account / 出品前提のセットアップ**(2026-09-05追加): `ebay-dropship sandbox setup-selling` を実行する。
      SELLING_POLICY_MANAGEMENTへのオプトイン→支払い/返品/配送ポリシー(marketplaceId=EBAY_US、
      無ければ最小構成で作成・有れば再利用)→merchant location(既定`default`、無ければ米国ダミー住所で作成)
      を行い、`.env` に `EBAY_PAYMENT_POLICY_ID` / `EBAY_RETURN_POLICY_ID` / `EBAY_FULFILLMENT_POLICY_ID` /
      `EBAY_MERCHANT_LOCATION_KEY` を書き込む(冪等。何度実行しても重複作成しない。値自体は出力しない)。
      **`execute-publish --live` が成功するための前提であり、未実行だと listingPolicies が空のまま
      publishOffer が失敗する見込み。**
- [ ] **Inventory / publish**: 上記 `setup-selling` を実行済みの状態で、
      `ebay-dropship sandbox seed-test-item --category-id <実際のSandboxカテゴリID>` →
      `ebay-dropship proposals approve <id> --by <name>` → `ebay-dropship sandbox execute-publish <id>` の順で、
      Sandbox の自分のアカウントに対しテスト用SKUで実際に出品(Sandbox上)できる。
      既定は `dry_run`(何も送信しない)。`--live` を付けて初めて実送信する。
      `--live` 実行時、指定カテゴリの必須アスペクト(Taxonomy API)のうち item_specifics に無いものは
      プレースホルダ(`Unbranded`等)で自動補完される(ベストエフォート。Taxonomy取得に失敗した場合は
      既存の item_specifics のまま publish を試みる)。
      2026-09-05: 実Sandbox疎通で`errorId 25709 "Invalid value for header Content-Language"`が判明し
      修正済み。Inventory/Offer系の書き込み(`inventory_item`/`offer`/`publish`/`update_offer`/
      `location`)には`.env`の`EBAY_CONTENT_LANGUAGE`(既定`en-US`)を、Browse APIには
      `EBAY_MARKETPLACE_ID`(既定`EBAY_US`)を`X-EBAY-C-MARKETPLACE-ID`ヘッダーとして送る
      (DECISIONS.md参照)。
- [ ] **Inventory / price_change**: 上記で作成したSandbox出品に対し `execute_price_change` を実行し、
      価格変更が反映される(現時点ではCLIコマンド化していない。`execute_price_change`を直接呼ぶ、
      または今後 `sandbox execute-price-change` を追加する)。
- [ ] **Fulfillment / getOrders**: `ebay-dropship sandbox get-orders` がSandbox上の注文(あれば)を取得できる。
      Sandboxでテスト注文を発生させる手段がある場合はそれも使う。
- [ ] **Analytics / get_rate_limits**: `ebay-dropship sandbox rate-limits` が実際のレート状況を返す
      (`alerts.alert_for_rate_budget` の実データでの動作確認も兼ねる)。
- [ ] 上記すべてで、監査に必要な情報(`proposals.status`・`decided_by`・`decided_at`・payload中の
      `ebay_item_id`/`ebay_offer_id`/`ebay_listing_id`等)が正しく記録されていることを確認する。

**1つでも失敗する場合は、そこで止めて原因を修正する。次の (c) には進まない。**

---

## (c) 通過後も実publish/purchaseのフラグはOFFのまま: 低リスクの限定ライブ

(b) をすべて通過した後も、**フラグ(`EBAY_ENV=production`、`ENABLE_AUTOMATED_SUPPLIER_PURCHASE`)は
すぐには変更しない**。まず本番相当のごく小さいスコープで、監査ログとアラートを人間が観察する期間を設ける。

- [ ] 出品は1〜2点に限定する(実商品・実売買が発生する前提のリスクを最小化する)。
- [ ] 発注(purchase)は自動化フラグをOFFのまま、`ManualOrderPurchaseChannel` が生成する発注パケットを
      人間が確認し、手動で発注するか、個別に承認者が明示的に発注を行う運用にする。
- [ ] この期間中、以下を毎日観察する:
  - [ ] `alerts`(`stock_divergence` / `unprofitable` / `rate_limit`)が想定通りに、かつノイズなく発火しているか
        (`DedupingNotifier` の抑制ウィンドウが適切か)。
  - [ ] `proposals` テーブルの `status=failed` の理由(監査ログ相当。`payload.failure_reason`)に、
        想定外のエラーが無いか。
  - [ ] 実際の返品率・成約率が `analytics.KpiSummary` の想定(閾値)と大きく乖離していないか。
- [ ] 最低1サイクル(`pdca_cycle=daily` の1日以上)を問題なく回し切ったことを確認する。

---

## (d) 能力ごとの段階有効化(人間の明示的な go-live 判断)

以下は独立した能力として扱い、**それぞれ個別に、人間が明示的に「有効化してよい」と判断してから**
設定を変更する。一括で全部を有効化しない。

- [ ] **出品公開(publish)を本番で自動実行してよいか** — 承認は引き続き人間が行う前提で、
      Do フェーズ(`run_do`)の定期実行を本番Sandbox外(=実eBay)に向けてよいかの判断。
- [ ] **価格改定(price_change)を本番で自動実行してよいか** — 同上。
- [ ] **サプライヤーへの自動発注を有効化してよいか**
      (`ENABLE_AUTOMATED_SUPPLIER_PURCHASE=true` への変更)。
      **これは最も不可逆(実際のお金が動く)なため、実サプライヤー側に自動発注APIが用意でき、
      かつ (c) の限定ライブ運用で問題が無かったことを確認したうえで、最後に判断すること。**
      フラグを立てても、対応する自動発注チャネルの実装(`PurchaseChannel` の新しい実装)が
      別途追加されるまでは何も変わらない(`orders/purchase_channel.py` 参照)。
- [ ] **承認Web UI(`api/`)を127.0.0.1以外にバインドしてよいか** — 外部公開する場合は
      リバースプロキシ・TLS・ネットワーク制御(IP制限等)を別途用意し、`APPROVAL_API_USERS` の
      パスワードを強固なものに変更したうえで判断すること。

---

## 変更してはいけないこと(このチェックリストの目的が壊れるため)

- 上記チェックを飛ばして `EBAY_ENV=production` にしない。
- `ENABLE_AUTOMATED_SUPPLIER_PURCHASE` を、対応する実装が無いままTrueにしても意味は無いが、
  将来実装を追加する際もこのチェックリスト完了前に有効化しない。
- 承認Web UI・CLIのいずれであっても、`guardrails.gateway.execute_side_effect` の実行時再検査を
  迂回する新しい実行経路を作らない(Phase 2/4で確立した静的検査テストの対象を広げること)。
