# ebay-dropship-agent

eBay 上で **卸直送型の無在庫ドロップシッピング** を、承認ゲート付きで PDCA 自動化するエージェント。

> `saron` リポジトリ内の独立したサブプロジェクトです(Next.js サロン予約 SaaS 本体とは無関係)。
> このディレクトリ配下でだけ動作する Python プロジェクトとして構成しています。

## まず読むもの

1. `PROMPT.md` — システム全体の設計図(アーキテクチャ / PDCA / データモデル / eBay API 方針 / 開発フェーズ)
2. `AGENT_PROMPTS.md` — 4エージェントのプロンプトと共通提案エンベロープ
3. `compliance.md` — eBay の無在庫・ドロップシッピング規約とレート制限
4. `DECISIONS.md` — これまでの設計判断の記録

## 現在のステータス: Phase 2(データモデル+承認基盤)完了

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
