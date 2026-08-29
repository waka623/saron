# ebay-dropship-agent

eBay 上で **卸直送型の無在庫ドロップシッピング** を、承認ゲート付きで PDCA 自動化するエージェント。

> `saron` リポジトリ内の独立したサブプロジェクトです(Next.js サロン予約 SaaS 本体とは無関係)。
> このディレクトリ配下でだけ動作する Python プロジェクトとして構成しています。

## まず読むもの

1. `PROMPT.md` — システム全体の設計図(アーキテクチャ / PDCA / データモデル / eBay API 方針 / 開発フェーズ)
2. `AGENT_PROMPTS.md` — 4エージェントのプロンプトと共通提案エンベロープ
3. `compliance.md` — eBay の無在庫・ドロップシッピング規約とレート制限
4. `DECISIONS.md` — これまでの設計判断の記録

## 現在のステータス: Phase 0(プロジェクト初期化)完了

- ディレクトリ雛形・依存定義(`pyproject.toml`)・`.env.example` を作成。
- 各モジュールは空のインターフェース(ABC / pydantic モデル)のみ。ロジックは `NotImplementedError`。
- `guardrails/` はコンプライアンス制約の TODO と、スキップ付きテストスケルトンのみ(`tests/test_guardrails.py`)。

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
