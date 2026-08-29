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

## Phase 3

- **`pricing.calculate_net_profit` の前倒し実装:** 当初 Phase 6 実装予定だったが、research/listing 双方が
  純利益計算を必要とするため Phase 3 で先に実装(`fee = price * fee_pct/100`、`net = price - cost - fee - shipping`)。
  Phase 6 の価格・次アクション判断エージェントもこの共通関数を再利用する。
- **リサーチ判断(`research/`)はルールベースで決定論的に実装。** `evaluate_candidate` は
  (1) 除外カテゴリ→hold、(2) 相場データ無し→hold(要確認、推測しない)、(3) 利益ガード未達(目標利益率20% or
  最低純利益$5)→none、(4) 需要弱(直近30日販売<3件)or競合過多(出品数>=30)→none、(5) それ以外→hold(候補を次段へ、
  `payload.recommended=True`)の5分岐。`AGENT_PROMPTS.md`のマッピング表どおり `proposal_type` は
  `none`/`hold` のみ(研究段階では書き込みを伴わないため)。
- **ゴールデンケースの扱い:** `AGENT_PROMPTS.md` にはリサーチ/出品ドラフトの具体的な数値入出力例が無い
  (価格・次アクション判断エージェントのみ具体例あり。これは Phase 6 で実装時に検算のうえゴールデンにする)。
  そのため Phase 3 は独自の現実的なフィクスチャ(相場中央値$29.99・原価$12〜$28・送料$3.50・手数料13%)を用意し、
  手計算で検算(例: 10.5913 = 29.99-12.00-3.8987-3.50)してから `tests/test_research.py`・`tests/test_listing.py`
  にゴールデンとして固定した。数値・判断(proposal_type/recommended/missing_item_specifics等)は完全一致、
  タイトル・説明文などの自由文は性質検証(必須キーワード含有・禁止表現不在・納期の正直な記載・
  必須item specifics充足)にとどめている。エッジケース(相場データ無し・需要薄い・競合過多・目標割れ原価)を
  すべて含めた。
- **Browse APIアダプタ:** `EbayClient.search_competitive_listings`(Browse API `item_summary/search`)を実装し、
  `research/market_data.py` に `MarketDataProvider` 抽象インターフェース + `MockMarketDataProvider`(テスト/開発用
  フィクスチャ)+ `EbayBrowseMarketDataProvider`(実API、`EbayClient.sandbox`でSandbox/本番を切替、コード変更不要)を
  用意。Phase 1と同じ方針で、実キー未着のため `httpx.MockTransport` でSandbox疎通を模擬してテスト。
  既知の制約: Browse APIは直近販売実績を提供しないため `recent_sales_30d` は常に `None`
  (売れ行きシグナルが必要な場合は将来 Analytics/Marketplace Insights 統合が必要、と明記)。
  Taxonomy API(カテゴリ・item specifics定義の自動取得)は今回未実装 — `required_item_specifics` は
  呼び出し側が指定する入力のまま(将来必要になれば同様のインターフェース越しに追加)。
- **LLM不使用の恒久ルールをコードで表現:** `listing/copy_generator.py` に `ListingCopyGenerator` 抽象
  インターフェースを置き、現時点の唯一の実装 `TemplateListingCopyGenerator` は決定論的なテンプレートのみで
  文面を生成する(判断は一切行わない)。`listing.generate_draft` 側は生成された文面に対して禁止表現チェック
  (`FORBIDDEN_CLAIM_WORDS`)を必ず実行し、違反があれば publish させず hold にする。将来 LLM 版の
  ジェネレータを追加しても、この構造(判断はルールベース/LLMは文面のみ/出力は必ずチェックを通す)は変わらない。
  research 側にも同様の恒久ルールをモジュールdocstringに明記した(候補可否は常にルールベース)。

## Phase 4

- **実装物:** `orchestrator/do.py`(`execute_publish` / `execute_price_change` / `run_do`)。
  `guardrails.gateway.execute_side_effect` の executor として `EbayClient` の Inventory 書き込み
  (`create_or_update_inventory_item` → `create_offer` → `publish_offer`、price_changeは`update_offer`)を
  実際に接続した。`tests/test_guardrail_gateway.py` の静的バイパス検査は `do.py` を許可済み接続点として
  更新し(`update_offer` も検査対象に追加)、それ以外のファイルからの書き込み呼び出しは引き続き検知する。
- **切り分け:** このフェーズは「承認済みproposalを実行するだけ」。価格・出品可否の判断は research/listing/pricing の
  責務のまま変更していない。price_changeのテストは承認済みの目標価格(`payload.proposed_price`)を持つ提案を
  入力にしており、価格の自動算出はしていない(Phase 6のスコープ)。
- **Inventory APIはフェイクで検証(実キー未着):** `tests/fakes/ebay_inventory_fake.py::FakeInventoryBackend` は
  成功専用ではなく、要求どおり4つの失敗モードを再現する:
  (1) publish拒否(item specifics不足/ポリシー違反、`errorId=25007`相当)、
  (2) レート制限(offer作成時に429を返し続け、リトライ上限後にEbayApiErrorとして扱われる)、
  (3) 部分成功(inventory_item・offerは成功するがpublishだけ失敗し、eBay側には実体が残るが
  proposalはFAILEDのまま=中途半端なEXECUTEDにしない)、
  (4) 重複(offer作成が「既に存在する」を返し、既存offer_idを再利用して公開まで進める=冪等)。
  いずれも `tests/test_orchestrator_do.py` でexecutorがエラー処理を正しく通ることを確認済み。
  **TODO(本番投入前の必須ゲート・未消化):** 実 Sandbox 認証情報が揃い次第、`EbayClient.from_settings()` で
  実際に `execute_publish`/`execute_price_change` をSandboxに対してエンドツーエンドで実行し、
  少なくとも1件の実出品・1件の実価格変更が成功することを人手で確認する。**このE2E検証が済むまで、
  本番(`EBAY_ENV=production`)には絶対に進まない。**
- **冪等性:**
  - `create_or_update_inventory_item` は PUT(仕様上べき等)。同じSKUへの再送は上書きになり重複を生まない。
  - `create_offer` が「既に存在する」を返した場合は `EbayOfferAlreadyExistsError` で既存offer_idを捕捉し
    再利用する(新規offerを作らない)。
  - 各ステップ成功のたびに `repository.update_payload` で `ebay_item_id`/`ebay_offer_id` を記録し、
    次回実行時(中断からの再開)はこれらが既にあるステップを再実行しない
    (`test_publish_retry_after_interrupted_attempt_skips_completed_steps` で検証)。
  - さらに上位のガードとして、proposalが一度 `EXECUTED`/`FAILED`(終端状態)になった後は
    `store/repository.py` の状態機械がどんな遷移も拒否するため、同一proposalの二重実行は構造的に不可能。
- **原子性と監査:** 全ステップ成功後にのみ `repository.mark_executed`(item/offer/listing idはpayloadに保存済み)。
  途中で失敗したら例外の直前に必ず `repository.mark_failed(reason=...)` を呼んでから再送出するため、
  「承認済みのまま実は失敗していた」という中途半端な状態は残らない。監査ログ専用テーブル(`audit/` 実装)は
  未着手のままだが、`status`・`decided_by`・`decided_at`・`payload`(失敗理由・生成id)が `proposals` テーブルに
  確定的に記録される点で、最低限の監査可能性(誰が・いつ・結果どうなったか)は現状も担保している。
  専用の `audit_log` テーブル化は将来必要になった時点で追加する。
- **実行時再検査(deny by default、承認済みでも鵜呑みにしない):** `guardrails.gateway.execute_side_effect` は
  実行の瞬間に毎回、(a) `status == APPROVED` か、(b) `requires_human_approval` の整合性、
  (c) 卸直送であること(`rationale`のretail arbitrage検知)、(d) レート予算、
  (e) price_change/purchaseなら利益ガードを**再計算**、(f) publishなら新設の
  `check_publish_payload_complete`(必須項目・item specifics充足を再確認)を通す。
  `test_price_change_blocked_by_profit_guard_reverification_at_execution_time` で、承認後に利益基準が
  厳しくなった場合に実行がブロックされ `update_offer` へ一切到達しないことを確認済み。
- **dry-runモード:** `dry_run=True` を渡すと、`EbayClient` へのHTTPアクセス(認証含む)を一切行わずに
  送信予定のリクエスト内容(`inventory_item_request`/`offer_request`/`update_offer_request`)を
  `payload.dry_run_preview` に記録するだけで終わる。proposalのstatusはAPPROVEDのまま変化しない。
  ただし dry-run もguardrailsチェック自体は通過が必須(deny対象の提案をdry-runでも先読みさせない設計)。
- **副次的なバグ修正:** `ProposalRecord.payload`(JSON列)に `Decimal` を直接保存しようとすると
  標準の`json`エンコーダがエラーになることが本フェーズのテストで発覚(listing.generate_draftの
  `list_price`は元々Decimalで、これまでのテストではpayloadに直接Decimalを入れていなかったため未発見だった)。
  `store/models.py::DecimalSafeJSON`(TypeDecorator)でDecimalをタグ付き表現({"__decimal__": "29.99"})に
  変換して保存し、読み出し時に自動でDecimalへ戻すようにした。DB上のカラム型はJSONのままでAlembicの
  マイグレーション変更は不要。
- **技術スタック:** `references/architecture.md`(スキル)の提案どおり Python 3.11+ / FastAPI / SQLAlchemy+Alembic /
  APScheduler / pytest を採用。変更の必要が出たらここに追記する。
- **本コミットのスコープ:** ディレクトリ雛形・空インターフェース(ABC/pydanticモデル)・guardrails の TODO とスケルテストのみ。
  実際のロジック(guardrails の判定、DB、API 呼び出し)は Phase 1 以降で実装する。
