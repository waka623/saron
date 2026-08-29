# ebay-dropship-agent

eBay 上で **卸直送型の無在庫ドロップシッピング** を、承認ゲート付きで PDCA 自動化するエージェント。

> `saron` リポジトリ内の独立したサブプロジェクトです(Next.js サロン予約 SaaS 本体とは無関係)。
> このディレクトリ配下でだけ動作する Python プロジェクトとして構成しています。

## まず読むもの

1. `PROMPT.md` — システム全体の設計図(アーキテクチャ / PDCA / データモデル / eBay API 方針 / 開発フェーズ)
2. `AGENT_PROMPTS.md` — 4エージェントのプロンプトと共通提案エンベロープ
3. `compliance.md` — eBay の無在庫・ドロップシッピング規約とレート制限
4. `DECISIONS.md` — これまでの設計判断の記録

## 現在のステータス: Phase 5(受注+サプライヤー同期)完了

- `supplier/csv_adapter.py`: `SupplierStock` に `as_of`(データ鮮度)を必須化。不正なCSV行はsyncを
  落とさず隔離。`guardrails.check_supplier_data_freshness`(deny by default)で古いデータでの発注を防ぐ。
- `EbayClient.get_orders`(Fulfillment API、読み取り専用)を実装。`orders.ingest_orders` が不正レコードの
  隔離と重複`order_id`の検知を行う。
- `orders.evaluate_purchase`: ルールベースのみで在庫消失・原価上昇(margin超え)・発送不可地域・
  同期ラグ・納期超過を検知して`hold`(すべて実データに近いフェイクで再現・検証済み)。
- `orchestrator/do.py::execute_purchase`: 発注実行は既定で `ManualOrderPurchaseChannel`
  (発注パケットの記録のみ、実送信なし)に対してのみ行う。実自動発注は
  `enable_automated_supplier_purchase`(既定False固定)でゲート。冪等性(同一order_id再送は
  duplicate扱い)・実行時再検査(発注の瞬間に現在原価・在庫・鮮度を再確認)を実装。
- **重要(TODO・未消化):** 実サプライヤーとの自動発注API統合、および明示的なgo-live判断が済むまで
  自動発注は有効化しない。`DECISIONS.md` の Phase 5 節参照。

## 過去のステータス: Phase 4(Do: 承認→出品/価格改定)完了

- `orchestrator/do.py`: 承認済み(APPROVED)の publish/price_change を実行する `execute_publish` /
  `execute_price_change` / `run_do`。`guardrails.gateway.execute_side_effect` の executor として
  `EbayClient` のInventory書き込みを接続。冪等性(PUTの性質+重複offer再利用+終端状態による二重実行防止)・
  原子性(全ステップ成功後にのみ`executed`、失敗時は理由付きで`failed`)・実行時再検査(deny by default)・
  dry-runモードを実装。
- 実キー未着のため `tests/fakes/ebay_inventory_fake.py` のフェイクでテスト(成功専用ではなく、
  publish拒否・レート制限・部分成功・重複の4失敗モードを再現)。
- **重要(TODO・未消化):** 実 Sandbox 認証情報でのエンドツーエンドE2Eは本番投入前の必須ゲート。
  `DECISIONS.md` の Phase 4 節参照。これが済むまで `EBAY_ENV=production` には進まない。

## 過去のステータス: Phase 3(Plan: リサーチ+出品ドラフト生成)完了

- `research/`: `evaluate_candidate`(ルールベース、LLM不使用)+ `MarketDataProvider`(Mock/Browse API、
  Sandbox/本番切替可能)。除外カテゴリ・相場データ無し・需要薄い・競合過多・目標割れ原価のケースを含む。
- `listing/`: `generate_draft`(ルールベース)+ `ListingCopyGenerator`(現状はテンプレート実装。将来 LLM 実装に
  差し替え可能だが、判断は常にルールベースのまま・出力は禁止表現チェックを必ず通す)。
- `pricing.calculate_net_profit` を実装(Decimal固定)。research/listingで共有。

- Phase 0:ディレクトリ雛形・依存定義(`pyproject.toml`)・`.env.example` を作成。利益ガードの数値(目標利益率20%/最低純利益$5)と
  除外カテゴリ(6項目)は `.env` に定数として確定済み(`DECISIONS.md` 参照)。
- Phase 1:`adapters/ebay/` に OAuth(自動リフレッシュ付き)・レート制限クライアント(コールバジェット+指数バックオフ)・
  読み取り系疎通確認(`get_rate_limits`)を実装。実 Sandbox キー未投入のためテストは `httpx.MockTransport` でモック。
  `EbayClient.from_settings()` が `.env` から認証情報を読むため、実キーを書き込むだけでコード変更なしに実疎通へ切り替わる。
- Phase 2:金額を `Decimal` 化(float禁止)。`guardrails/` を実装し deny-by-default を徹底(小売アービトラージ検知・
  利益ガード・レート予算・在庫確認)。`guardrails/gateway.py` を副作用実行の唯一の入口にし、バイパスが無いことを
  静的検査テストで担保。`store/`(SQLAlchemy、DB非依存)+ Alembic で `proposals` テーブルを作成。
  承認CLI(`ebay-dropship proposals list/approve/reject`)で `pending→approved/rejected→executed/failed` の
  状態遷移を強制。

### 承認CLIの使い方

```bash
pip install -e ".[dev]"
alembic upgrade head          # .env の DATABASE_URL に対して proposals テーブルを作成
ebay-dropship proposals list
ebay-dropship proposals approve <id> --by <名前>
ebay-dropship proposals reject <id> --by <名前> --reason "理由"
```

## セットアップ

```bash
cd ebay-dropship-agent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # 値を編集(トークン類はコミットしない)
pytest
```

## 開発フェーズ

`PROMPT.md` 第9章参照。第0(本コミット)→第1(eBayアダプタ/Sandbox)→第2(データモデル/承認基盤)→
第3(Plan)→第4(Do)→第5(受注/サプライヤー同期)→第6(Check/Act)→第7(ダッシュボード)の順に進める。

## 最優先ルール

- 仕入れは卸・サプライヤー直送のみ。小売アービトラージは扱わない。
- publish / price_change / withdraw / purchase は必ず「提案 → 人間の承認 → 実行」。
- 公式 eBay Sell API のみ使用し、レート制限を尊重する。
- 純利益が目標を下回る値下げ・発注は自動提案しない(利益ガード)。

詳細は `CLAUDE.md` / `PROMPT.md` を参照。
