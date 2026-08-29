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

## Phase 5

- **SupplierAdapter(CSV)の具体実装 + データ鮮度必須化:** `supplier.SupplierStock` に `as_of`
  (データがいつ時点のものか)を必須フィールドとして追加した。`CsvSupplierAdapter.sync()` は各行を
  独立してパースし、不正行(必須列欠落・cost/quantity/lead_time_daysの型不正・負数・as_ofのISO形式不正)は
  `CsvRowError` として隔離してsync全体を落とさない(`tests/test_supplier_csv_adapter.py`)。
  内部モデル(`SupplierStock`)は供給元非依存のままで、`supplier/api_adapter.py`(未実装スタブ、契約は同じ)へ
  差し替え可能な設計を維持している。
  新設の `guardrails.check_supplier_data_freshness`(deny by default: `as_of` が無い、または
  `SUPPLIER_DATA_MAX_AGE_MINUTES`(既定24時間)を超えて古い場合はdeny)を `orders.evaluate_purchase` と
  `orchestrator/do.py::execute_purchase` の両方(判断時・実行時の両方)で使用する。
- **Fulfillment APIはフェイクで検証(実キー未着):** `EbayClient.get_orders`(Fulfillment API
  `getOrders`、読み取り専用)を実装し、`tests/fakes/ebay_fulfillment_fake.py::FakeFulfillmentBackend` +
  `httpx.MockTransport` でSandbox疎通をモック(Phase1/3と同じ方針)。
  要求どおり5つの乖離モードをすべて再現・検証した(このフェーズの主目的=乖離検知→hold):
  1. **在庫消失** — `supplier.fetch_stock` がKeyErrorまたは数量0を返す → hold
     (`test_holds_when_stock_lost` / `test_holds_when_quantity_insufficient`)。
  2. **原価上昇(margin超え)** — 受注時想定原価ではなく現在原価で純利益を再計算し、
     利益ガード割れならhold(`test_holds_when_cost_increased_beyond_margin`)。
  3. **発送不可地域** — 除外国コード(輸出規制想定)なら発注せずhold(`test_holds_for_non_shippable_destination`)。
  4. **部分成功・重複受注** — `orders.ingest_orders` が、Fulfillment APIレスポンス中の不正レコードを
     隔離しつつ(部分成功)、同じ`order_id`が2回現れた場合は2件目以降を`duplicate_order_ids`に振り分けて
     二重処理しない(`test_ingest_orders_isolates_malformed_records_without_failing` /
     `test_ingest_orders_deduplicates_repeated_order_id` /
     `tests/test_ebay_fulfillment.py::test_get_orders_mocked_sandbox_connectivity_and_ingest_isolates_duplicates_and_bad_rows`)。
  5. **同期ラグ** — サプライヤーデータの`as_of`が閾値より古ければhold(上記の鮮度ガードを再利用。
     `test_holds_when_supplier_data_is_stale`)。
  加えて納期超過(サプライヤー納期が約束納期に間に合わない)もhold対象にした(`test_holds_when_lead_time_exceeds_due_date`)。
- **受注処理(orders/)は判断のみルールベース:** `evaluate_purchase` はLLMを使わず、上記5+1の条件を
  順に確認し、すべて通過した場合のみ `proposal_type=purchase` を返す(AGENT_PROMPTS.md 4章どおり
  `purchase | hold` のみ)。
- **purchase の実行(orchestrator/do.py::execute_purchase)は要求どおり厳重にゲーティングした:**
  - **(a) 実発注は常にフェイク/手動チャネルのみに接続。** `config.Settings.enable_automated_supplier_purchase`
    は既定 `False` で固定。**TODO(本番投入前の必須ゲート・未消化):** 実サプライヤーの自動発注APIとの統合、
    および人間による明示的なgo-live判断が完了するまで、このフラグをTrueにしても対応する実装（自動発注チャネル）
    はコードベースに存在しない。誰かが将来 `AutomatedSupplierPurchaseChannel` のような実装を追加する際は、
    必ずこのフラグでゲートし、実キー・実サプライヤー契約が整うまでデフォルトを変更しないこと。
  - **(b) 発注パケット生成方式。** `orders/purchase_channel.py::ManualOrderPurchaseChannel`(既定実装)は
    どこにも自動送信せず、`PurchaseOrderPacket`(何を・どこから・いくらで・送り先)を記録するだけ。
    実際の発注は人間が手動で行う想定。将来、真の自動発注APIを持つサプライヤーと統合する場合は
    `PurchaseChannel` インターフェースの新しい実装に差し替えるだけでよく、`execute_purchase` 側の変更は不要。
  - **(c) 冪等性。** 同じ`order_id`の`PurchaseOrderPacket`を2回`submit_purchase`すると2回目は
    `status="duplicate"`を返す(`test_purchase_channel_itself_treats_duplicate_submission_idempotently`)。
    加えて、`repository.update_payload`で`purchase_reference_id`を記録済みなら、中断からの再実行時に
    `submit_purchase`自体を一切呼ばずに完了扱いにする(`test_purchase_retry_after_interrupted_attempt_does_not_resubmit`)。
    さらに上位のガードとして、状態機械上EXECUTED/FAILEDは終端状態のため同一proposalの二重実行は構造的に不可能
    (Phase4と同じ保証)。
  - **(d) 実行時再検査(deny by default、受注時点の数字を信用しない)。** `execute_purchase` は実行の瞬間に
    `supplier.fetch_stock`を再度呼び、(1) データ鮮度、(2) 現在原価での純利益再計算、(3) 現在在庫での数量充足、
    をすべて再確認する。承認時点でOKだった提案でも、実行直前にこれらが崩れていれば
    `guardrails.gateway.execute_side_effect`に発注させず`GuardrailDenied`で止める
    (`test_purchase_blocked_when_stock_lost_at_execution_time` /
    `test_purchase_blocked_when_current_cost_exceeds_margin_at_execution_time` /
    `test_purchase_blocked_when_supplier_data_stale_at_execution_time` /
    `test_purchase_blocked_when_stock_insufficient_at_execution_time`)。
    現在原価での利益再計算を通すため、`guardrails.gateway.execute_side_effect` に
    `current_profit_override` パラメータを追加した(承認時点の`proposal.estimated_profit`ではなく、
    実行直前に計算した値でprofit_guardを検査できるようにする拡張)。

## Phase 6

- **analytics/(Check)はフィクスチャの延長で実装。実eBay Analytics API疎通は今回のスコープ外。**
  `MetricsProvider`抽象インターフェース + `FixtureMetricsProvider`(既定実装)で `KpiSummary`
  (成約率・ウォッチ率・返品率・サンプル充足・返品率乖離フラグ)を計算する。research/market_data.pyや
  supplier/csv_adapter.pyと同じ「インターフェース越しに実装差し替え」方針を踏襲しており、将来
  `EbayAnalyticsMetricsProvider`を追加する際もこの契約に合わせるだけでよい。
  **TODO(本番投入前の必須ゲート・未消化):** 実 Analytics API への実疎通確認は、Phase 1/4/5で積み上げてきた
  「実Sandboxキーでのエンドツーエンド検証」ゲート(DECISIONS.md Phase 4節)に統合する。実キー到着後、
  Inventory/Fulfillmentの実疎通と合わせて一度に確認し、個別に先行実施はしない。
  エッジケース(売上ゼロ・サンプル不足・view自体が0・返品率乖離あり/なし)をすべてテストで検証済み
  (`tests/test_analytics.py`)。
- **pricing.evaluate_next_action(Act)はAGENT_PROMPTS.mdの例を検算のうえ採用、数値を訂正して固定:**
  元の例(listing_id=A123, price=$40, cost=$22, fee=13%, shipping=$6)の「$38へ値下げ、純利益$4.66
  (12%)」という記述を、同じ前提(fee_pct=13%、shipping=$6)で再計算したところ数値が一致しなかった
  (`$38`での正しい純利益は`38-22-38*0.13-6=$5.06`であり、`$4.66`にはならない。$36 案の`$3.32`は
  一致し、利益ガード割れである点も一致)。**ユーザー指示どおり、採用前の検算で不一致を検出したため、
  そのままの数値では固定せず、同じ判断ロジック(まず10%引きの$36を試し、利益ガード割れのため、
  純利益がちょうど最低ライン$5になる価格までクランプする)を再計算し直した数値
  ($37.94・純利益$5.0078)をゴールデンとして採用した。** 判断の構造(値下げ→ガード割れ→クランプ)は
  元の例と同一。詳細な検算過程は `tests/test_pricing.py` のモジュールdocstringに記録した。
  数値・判断(proposal_type/proposed_price/estimated_profit)は完全一致、自由文(rationale/action_detail)
  は性質検証にとどめている。要求どおりhard caseをすべて含めた: price_change(クランプあり/なし)・
  withdraw(不採算・値下げ余地なし)・hold(在庫消失・データ陳腐化。supplier併用)・
  none(据え置き/サンプル不足/クールダウン中/重複排除)。
- **フィードバック安定化ガード(ループを閉じるため必須)を`pricing.evaluate_next_action`に実装:**
  - クールダウン/ヒステリシス: `settings.pricing_cooldown_days`(既定7日)以内に価格変更済みの
    listingは`none`(`test_none_when_within_cooldown_period` / `test_price_change_proposed_after_cooldown_period_elapsed`
    で境界の両側を確認)。
  - 最小サンプル: `settings.pricing_min_sample_views`(既定30)未満のview数では`none`
    (`test_none_when_sample_insufficient`)。
  - 重複排除: 呼び出し側が`ListingSnapshot.has_pending_proposal`で「既に承認待ちがある」ことを伝えると
    `none`になり、積み増さない(`test_none_when_pending_proposal_already_exists`)。
  - 加えて `orchestrator/cycle.py::run_cycle` 自体も `proposal_type=none` の結果を承認キューに
    積まない設計にしており(下記)、二重に重複防止が効く。
- **orchestrator.run_cycle: サイクルのロジックとトリガー(スケジューラ)を分離した。**
  - `orchestrator/cycle.py::run_cycle` は直接呼べる純粋関数で、`plan_tasks`/`act_tasks`
    (research/listing/pricingのevaluate_*呼び出しを包んだcallableのリスト)を受け取り、
    `proposal_type=none`以外を`repository.enqueue`する。テストはタイマー待ちでなく直接呼び出しで行った
    (`tests/test_orchestrator_cycle.py`)。
  - `orchestrator/scheduler.py::CycleScheduler` は`run_cycle`を叩くだけの薄いトリガーで、
    `threading.Lock`によるsingle-flight(前サイクル未完なら`tick()`が即座に`None`を返してスキップ)を
    実装(`tests/test_orchestrator_scheduler.py`、`threading.Event`で実際に並行呼び出しを再現して検証)。
    実際のAPScheduler登録(`scheduler.add_job(cycle_scheduler.tick, "interval", hours=24)`等)は、
    将来 `api/`(Phase 7予定のFastAPIアプリ)の起動処理で行う想定。今回は登録先となる薄いトリガー
    (`CycleScheduler`)とその動作保証(single-flight)までを実装した。
  - `ebay-dropship cycle run-once` CLIコマンドで手動「今すぐ1回実行」を提供(`tests/test_cli.py`)。
  - **最重要の境界を維持:** `run_cycle`は承認キューに積むところまでで、`publish`/`price_change`/
    `purchase`の実行は一切行わない。`orchestrator/cycle.py`が`orchestrator/do.py`をimportすら
    していないことを`tests/test_orchestrator_cycle.py::test_cycle_module_never_references_do_phase_execution`
    でソース走査により静的に検査している(Phase2/4の静的バイパス検査と同じ方針)。
  - **スコープの正直な記録:** `plan_tasks`/`act_tasks`の中身(どのSKU/listingを評価対象にするかの
    自動列挙)はまだ統合していない。CLIの`cycle run-once`は現時点で空のタスクリストを渡し、
    サイクル機構(enqueue/skip判定・single-flight)自体の疎通を確認するだけに留めている。
    実運用に向けては、supplier全件走査→research、対象listing全件→pricingのタスク組み立てを
    別途統合する必要がある(将来のフェーズまたは追加対応)。

## Phase 7(開発フェーズ最終回)

- **api/(承認Web UI)は CLI と同一の `SqlProposalRepository`/`ApprovalQueue` を共有し、承認ロジックを
  再実装していない。** エンドポイントは list/detail/approve/reject のみ(healthz除く)。
  - **認証:** HTTP Basic。`.env` の `APPROVAL_API_USERS`(`username:password` カンマ区切り、複数運用者可)。
    **未設定(空文字)なら誰も認証できない(fail-closed)** — `test_no_users_configured_means_nobody_can_authenticate`
    で確認済み。認証されたusernameだけが`decided_by`になり、リクエストボディで`decided_by`や`status`、
    `estimated_profit`等を送っても無視される(`test_client_supplied_extra_fields_are_ignored_not_honored`)。
  - **高リスク確認ステップ:** `risk_level=high`の提案は`confirm=true`を明示しない限り承認できず409を返す
    (`test_high_risk_approval_requires_confirmation`)。低リスクは即時承認可(`test_low_risk_approval_does_not_require_confirmation`)。
  - **localhostバインド:** `Settings.approval_api_host`の既定値は`127.0.0.1`(`test_default_bind_host_is_localhost`)。
    `ebay-dropship api serve`で起動。外部公開する場合のリバースプロキシ・TLS・追加認証は`GO_LIVE.md`の
    段階有効化チェックリストに委ねる(このアプリ単体ではネットワークバインドの強制はできないため)。
  - **「実行時ガード再検査はサーバ側で行いクライアントを信用しない」の実装上の意味:** このAPIは
    publish/price_change/purchaseの実行(外部副作用)を一切公開しない設計にした
    (`orchestrator/do.py`の実行関数を`api/`からimportしていない)。理由は次の2点:
    (1) ユーザー要求が「最小Web UI(承認api/)」と明示的に承認・却下に限定されていたこと、
    (2) 実行は引き続き`run_do`(バッチ)や個別の`execute_*`呼び出しが担い、そこでの実行時再検査
    (Phase4/5で実装済みの`current_profit_override`・`check_publish_payload_complete`・鮮度再確認等)は
    Web層の存在と完全に無関係であり、Web UIが何を送ってもこれをバイパスする経路が構造的に無い
    (承認とは別の、独立したコードパスであるため)。将来「Webから実行もトリガーしたい」場合は、
    別途エンドポイントを追加検討する(この段階では追加していない)。
- **alerts/(アラート)は既定でログ出力のみ、`Notifier`インターフェースの背後に実装を置いた。**
  - `LoggingNotifier`(既定)はメッセージ・重大度・関連proposal_id・理由(rationale転記)をログに出す。
    `AlertSeverity.CRITICAL`は`logging.ERROR`にマップ(`test_logging_notifier_uses_error_level_for_critical`)。
  - `DedupingNotifier`は`(category, related_proposal_id)`単位で抑制ウィンドウ(既定30分)を持ち、
    重複抑制とレート制限を同じ機構で扱う(要求の「重複抑制/レート制限する」を1つのシンプルな
    cooldown方式で満たした。設計判断として明記)。
  - 在庫乖離(`stock_divergence`)・不採算(`unprofitable`)アラートは、対応する`hold`/`withdraw`
    Proposalの`rationale`を`Alert.reason`にそのまま転記するため、アラート自体に「なぜ止まったか」が
    含まれる(判断ロジック側とアラート文言側を二重管理しない)。レート逼迫(`rate_limit`)は
    `CallBudget.is_near_limit()`から`alert_for_rate_budget`で組み立てる。
  - `orchestrator/cycle.py::run_cycle`に`notifier`引数を追加し、hold/withdrawとして承認キューに
    積まれた提案について自動的に通知する(`test_run_cycle_notifies_for_hold_proposals`)。CLIの
    `cycle run-once`は`LoggingNotifier()`を既定で使う。
- **実Sandbox E2Eゲートの最終化: `GO_LIVE.md`を新設し、各フェーズのDECISIONS.md TODOを集約した。**
  ユーザー指定の(a)〜(d)の構成で書いた: (a)TODO一覧の表、(b)実キー到着後にOAuth/Inventory publish/
  Inventory price_change/Fulfillment getOrders/Analytics get_rate_limitsを実Sandboxで通すチェックリスト、
  (c)通過後もフラグOFFのまま1〜2出品・手動発注の限定ライブで監査ログとアラートを観察する期間、
  (d)出品自動実行/価格改定自動実行/自動発注/API外部公開のそれぞれを独立した能力として、
  人間が個別に明示的なgo-live判断を下すまで有効化しないこと。このチェックリストの実施(実キー投入・
  フラグ変更)自体は本セッションのスコープ外(実キーが存在しないため)であり、あくまで次にやることの
  一本化が今回の成果物である。
- **副次的なバグ修正: `migrations/env.py`の`fileConfig`が既定で`disable_existing_loggers=True`だったため、**
  同一プロセス内(将来のFastAPIアプリ起動時やCLI経由)で`alembic upgrade`を呼ぶと、その時点で既に
  importされていたアプリ側ロガー(`ebay_dropship.alerts`等)が無効化され、以降ログが一切出なくなる
  問題があった。テストスイート全体を実行した際に(`test_alembic_migrations.py`が`test_alerts.py`より先に
  収集・実行されることで)顕在化して発覚。`fileConfig(..., disable_existing_loggers=False)`に修正した。
