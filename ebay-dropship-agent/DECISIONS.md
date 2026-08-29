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

## Phase 2

- **金額型:** `float` 禁止の指示を受け、共通エンベロープ `approval.Proposal.estimated_profit` と
  `config.Settings`(`target_margin_pct` / `min_net_profit` / `approval_high_risk_discount_pct`)を
  すべて `Decimal` に変更。DBは `sqlalchemy.Numeric(12, 2)` で保存する。`pricing.calculate_net_profit` の型ヒントも
  Decimal に更新(実装自体は Phase 6)。
- **DB非依存:** `store/models.py` は SQLite固有機能に依存しない標準 SQLAlchemy 型のみを使用
  (`Enum(..., native_enum=False)` で VARCHAR+CHECK 制約化、`JSON` 型、`Numeric`、`DateTime(timezone=True)`)。
  `store/db.py` の `check_same_thread` 分岐だけが sqlite 向けの接続オプションで、スキーマ自体には影響しない。
  Alembic (`migrations/`) で `alembic upgrade head` を実際に実行し、SQLite上に `proposals` テーブルが作成されることを
  `tests/test_alembic_migrations.py` で検証済み(estimated_profit=NUMERIC(12,2)、payload=JSON であることを確認)。
  `migrations/env.py` は `Settings()` を都度インスタンス化して `DATABASE_URL` を読むため、PostgreSQL 等への切り替えは
  `.env` の変更のみで完結する(env.py 側の変更は不要)。
- **承認CLI:** `ebay-dropship proposals list/approve/reject` を実装(`pyproject.toml` の `[project.scripts]` で
  コンソールスクリプト化)。承認/却下は `decided_by`・`decided_at` を記録し、状態遷移は
  `store/repository.py` の `_ALLOWED_TRANSITIONS`(`pending→approved/rejected`、`approved→executed/failed`、
  それ以外は全面禁止)で強制。不正遷移は `InvalidTransitionError` で弾かれ、CLIは非ゼロ終了・エラーメッセージ表示になる
  (`tests/test_store_repository.py`・`tests/test_cli.py` で検証)。Web(`api/`)は第7フェーズのまま。
- **guardrails(deny by default):** 4つの検査関数(小売アービトラージ検知・利益ガード・レート予算・在庫確認)を実装し、
  スキップしていた10件(+追加した検証ケース)をすべて green にした。以下の方針を徹底:
  - 判定に必要な情報が欠けている場合(想定利益が None、在庫確認用の数量が無い等)は deny。
  - 卸直送を示す語(卸/サプライヤー/wholesale/drop-ship 等)を確認できない記述は、小売アービトラージの語が
    無くても deny(「疑わしきは deny」であり「疑わしきは通す」にはしない)。
  - 対応テスト:`tests/test_guardrails.py`(各関数の許可/拒否/情報不足時の挙動)。
- **副作用実行のバイパス防止:** `guardrails/gateway.py` の `execute_side_effect` を、外部副作用(publish/price_change/
  withdraw/purchase)を実行する唯一の入口として実装。承認済み(`status=APPROVED`)であること、
  `requires_human_approval` フラグの整合性、小売アービトラージでないこと、レート予算、
  (price_change/purchase の場合)利益ガード、(purchase の場合)在庫充足のすべてを満たさない限り
  `executor` コールバックを呼ばない。バイパス経路が無いことは2通りで示した:
  1. `tests/test_guardrail_gateway.py` の各テストで、いずれか1つの guardrail が deny なら executor が
     一度も呼ばれないことを確認(呼び出しリストが空のままであることをアサート)。
  2. `test_ebay_write_methods_are_only_called_through_guardrail_gateway` で、`EbayClient` の書き込みメソッド
     (`create_or_update_inventory_item`/`create_offer`/`publish_offer`)の呼び出しが `client.py`(定義)と
     `gateway.py` 以外のソースファイルに存在しないことを静的に検査。Phase 4 で実際の eBay 書き込みを実装する際、
     このゲートウェイを経由しないコードを追加すると、このテストが失敗して検知する。
  - 注意点(スコープの正直な記録): Phase 4(実際の eBay 書き込み)がまだ存在しないため、「実行」は現時点では
    `executor: Callable[[Proposal], None]` という抽象コールバックに対してのみ検証している。Phase 4 で
    `EbayClient` の書き込みメソッドをこの `executor` の実装として接続し、上記の静的検査テストを維持することで、
    実際の副作用についても同じ保証が続く設計にしている。
- **proposals テーブル:** 共通エンベロープの全フィールド(`proposal_type/priority/summary/rationale/risk_level/
  estimated_profit/requires_human_approval/payload`)に加えて `status/decided_by/decided_at/created_at/id` を持つ
  (`store/models.py::ProposalRecord`)。
- **技術スタック:** `references/architecture.md`(スキル)の提案どおり Python 3.11+ / FastAPI / SQLAlchemy+Alembic /
  APScheduler / pytest を採用。変更の必要が出たらここに追記する。
- **本コミットのスコープ:** ディレクトリ雛形・空インターフェース(ABC/pydanticモデル)・guardrails の TODO とスケルテストのみ。
  実際のロジック(guardrails の判定、DB、API 呼び出し)は Phase 1 以降で実装する。
