# DECISIONS.md — 設計判断の記録

各エントリ:日付は省略し、フェーズ単位で記録する。迷ったら安全側に倒す方針(CLAUDE.md/PROMPT.md 第1章)に基づく判断は理由を明記する。

## Phase 0

- **配置場所:** 新規リポジトリ作成をまず検討したが、GitHub 連携の権限不足で API 経由のリポジトリ作成が 403 になり、
  ユーザーが権限再設定を望まなかったため、`saron` リポジトリ内の独立ディレクトリ `ebay-dropship-agent/` として実装する方針に変更した。
  ルートの `CLAUDE.md`/`AGENTS.md`(Next.js サロン予約 SaaS 向け)とは無関係であることを、このディレクトリの `CLAUDE.md` 冒頭に明記した。
- **サプライヤー連携方式:** ユーザー回答は「適切な方」(一任)。API/CSV のどちらが来ても差し替えられるよう
  `supplier.SupplierAdapter` を抽象インターフェースにし、外部依存や検証コストが低い CSV アダプタを MVP の既定実装先(Phase 5)とした。
  API アダプタは同じ契約で後から追加できる。
- **承認 UI:** ユーザー回答「両方(CLIから始めてWebへ拡張)」。`approval/` の承認ロジックを UI 非依存にし、
  `cli/`(Phase 2)と `api/`(Phase 7)の両方から呼び出す設計にした。
- **PDCA サイクル頻度:** ユーザー回答「日次(1日1回)」。`PDCA_CYCLE=daily` を既定値にし、`orchestrator.run_cycle` は
  Phase 6 で APScheduler の日次スケジュールに接続する前提とした。
- **目標利益率・最低純利益・除外カテゴリ:** ユーザー確定値(2026-08-29)。目標純利益率 20% / 最低純利益 $5(1注文あたり) /
  除外カテゴリ = `luxury_brand_goods`(ブランド・高級品)、`authentication_required`(時計・スニーカー等の要鑑定品)、
  `hazmat`(危険物)、`food_supplements_pharma`(食品・サプリ・医薬品)、`adult`(アダルト)、`gift_cards`(ギフトカード)。
  すべて `.env`(`TARGET_MARGIN_PCT` / `MIN_NET_PROFIT` / `EXCLUDED_CATEGORIES`)に定数として置き、コードに直書きしない。
  `config.Settings` のデフォルト値も同じ値に揃えてある(`.env` が無くても同じ挙動になるように)。

## Phase 1

- **スコープ:** OAuth(トークン取得+自動リフレッシュ)、レート制限付きクライアント(コールバジェット・指数バックオフ)、
  読み取り系(`get_rate_limits` = Developer Analytics API)の疎通確認をモックで実施。
  Inventory/Fulfillment/Browse への書き込み・検索は Phase 3〜5 に先送り(スタブのまま)。
- **秘密情報:** `EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET`/`EBAY_REFRESH_TOKEN` の実値は未受領・未使用。`.env.example` はキー名のみで空値。
  `EbayClient.from_settings(settings)` が `config.settings`(= `.env`)からこれらを読む唯一の経路なので、
  実際の Sandbox キーを `.env` に書き込むだけでコード変更なしに実疎通へ切り替わる。
- **テスト方針:** `httpx.MockTransport` でトークンエンドポイントと Analytics のレート制限エンドポイントを模擬し、
  OAuth のキャッシュ/自動リフレッシュ・認証情報欠如時のエラー・コールバジェット枯渇・指数バックオフのリトライ挙動を検証。
  実キーが揃った後は同じコードパス(`EbayClient.from_settings` → `get_rate_limits()`)を実 Sandbox に向けて手動確認する想定
  (自動テストは実ネットワークを叩かない方針を維持)。
- **日次コール上限の初期値:** `CallBudget(daily_limit=5000)` を仮の目安として設定。実際の上限は `get_rate_limits()` の
  結果で都度確認し、必要なら Phase 2 以降で動的に調整する(ハードコードのままにはしない)。
- **技術スタック:** `references/architecture.md`(スキル)の提案どおり Python 3.11+ / FastAPI / SQLAlchemy+Alembic /
  APScheduler / pytest を採用。変更の必要が出たらここに追記する。
- **本コミットのスコープ:** ディレクトリ雛形・空インターフェース(ABC/pydanticモデル)・guardrails の TODO とスケルテストのみ。
  実際のロジック(guardrails の判定、DB、API 呼び出し)は Phase 1 以降で実装する。
