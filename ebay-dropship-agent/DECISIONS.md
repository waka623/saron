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

## Phase 7後: アドバーサリアルセキュリティレビューとF3(HIGH)の修正(2026-08-29)

Phase 7完了後、ユーザー指示で `guardrails/` を中心にコード無変更のアドバーサリアルレビューを実施した
(6観点: deny by default / バイパス経路 / 実行時再検証 / 冪等性・並行実行 / 利益ガード正しさ / 秘密情報)。
各観点につき実際に反例(悪意ある入力・並行実行等)を試行し、7件のfindingsを報告した
(F1〜F7、severity: HIGH×1 / MEDIUM×3 / LOW×3)。ユーザーはレビューを承認のうえ、**今回のタスクスコープを
F3(HIGH)の修正のみに限定**し、F1/F2/F4〜F7は次タスクへの残課題としてここに記録するよう指示した。

### F3(解消済み): 承認済みpurchase提案の並行実行による二重発注

- **問題**: `orchestrator/do.py::execute_purchase`は、`guardrails/gateway.py::execute_side_effect`の
  `proposal.status != APPROVED`チェックが呼び出し元スナップショットに対する判定でしかなく、
  `store/repository.py::_transition`(get-then-set、DBロック無し)も状態遷移を原子的に保証していなかった。
  このため、同一の承認済みproposalに対して`execute_purchase`が(手動実行の重複・cronとAPIトリガーの
  重なり等の運用上の偶発を含め)並行に呼ばれると、両方が`purchase_channel.submit_purchase`まで到達し、
  同一order_idに対する発注が実際に2回発行されてしまう(状態機械の`InvalidTransitionError`は2回目の
  `mark_executed`でしか衝突を検知せず、その時点で外部副作用は既に2回実行済み)。
  レビュー時に`race_repro.py`(スクラッチ、実コードを2スレッドから独立セッションで並行実行)で実証済み。
- **回帰テスト(先に作成しred確認)**: `tests/test_orchestrator_purchase_concurrency.py`
  - `test_concurrent_execute_purchase_from_two_threads_only_one_actually_purchases`
    (2スレッド・各自独立したDBセッション/サプライヤー/発注チャネルインスタンスで`threading.Barrier`により
    完全同時到達を強制)
  - `test_concurrent_execute_purchase_from_two_processes_only_one_actually_purchases`
    (2プロセス、`multiprocessing`(forkコンテキスト)+`multiprocessing.Barrier`。インプロセスロックが
    一切効かない、より強い並行性の証明)
    修正前のコードに対してこの2テストと同等のロジックを実行し、両方とも`submit_purchase`が
    2回呼ばれること(二重発注)を確認した(scratch上で実行。テストファイル自体は修正後APIに依存する
    ため、pre-fix確認はスクラッチ複製で実施。手順・結果は本セッションの会話ログ参照)。
- **修正方針**: DBレベルの原子的な条件付き更新(compare-and-set)を主保証とした。
  - `store/repository.py`: `SqlProposalRepository.claim_for_execution(proposal_id, decided_by) -> bool`
    (`UPDATE proposals SET status='executed' WHERE id=? AND status='approved'`、影響行数==1のみTrue)。
  - `store/repository.py`: `SqlProposalRepository.claimed_execution(proposal_id, decided_by)`
    (contextmanager)。`claim_for_execution`と実際の副作用(発注)呼び出しを1つのSAVEPOINT
    (`session.begin_nested()`)として直列化する。実行権を獲得できなければ`AlreadyClaimedError`
    (新規、`InvalidTransitionError`のサブクラス)を送出し中身を一切実行しない。副作用が失敗した場合は
    claimによる`executed`への変更を含めてSAVEPOINT全体がロールバックされ、`status`は`approved`に戻る
    (その後`mark_failed`で理由付き`failed`へ遷移させるのは呼び出し側=`execute_purchase`の責務)。
  - `orchestrator/do.py::execute_purchase`のexecutorクロージャを、`purchase_channel.submit_purchase`
    呼び出し(および冪等再開パスの`mark_executed`相当処理)が`repository.claimed_execution`を経由する
    よう再構成した。`AlreadyClaimedError`は再送出のみ(追加の状態遷移をしない=勝者側の確定状態を壊さない)、
    それ以外の例外は`mark_failed`で理由を記録してから再送出する(挙動は修正前と同じ)。
  - **多層防御**: `purchase_channel.submit_purchase`への発注は`PurchaseOrderPacket.order_id`を鍵とした
    冪等キーとして扱われており(`ManualOrderPurchaseChannel`は同一order_idを`duplicate`として扱う、
    既存の`test_purchase_channel_itself_treats_duplicate_submission_idempotently`で検証済み)、これは
    そのまま維持した(主保証はDBレベルCASであり、チャネル側の冪等性は補助的な多層防御と位置づける)。
  - in-processのロック/single-flightは追加していない(ユーザー指示どおり「補助に留め主保証にしない」
    ため。DBレベルCASのみで複数プロセスでも正しく機能することを上記2テストで実証済み)。
  - `gateway.py`・publish/price_change側のコードは一切変更していない(F3のみに変更範囲を限定)。
- **修正後の検証**: 上記2つの回帰テストがgreen(5回連続実行で安定)。
  全170テスト(既存168+新規2)がpass。`ruff check`もクリーン。
  並行実行のたびに「実発注はちょうど1回・敗者側は`AlreadyClaimedError`というクリーンな拒否
  (クラッシュや無関係な例外ではない)」であることを両テストで確認した。

## MEDIUM(F1/F2/F4)の修正(2026-08-29、F3クローズ後の続き)

ユーザー指示で、adversarial security reviewのMEDIUM findings(F1/F2/F4)を修正した。各件について
(1)まず失敗する回帰テストを書き(red)、(2)最小修正、(3)green化、の順を守り、F1/F2/F4以外の
コードは変更していない。修正前に各件を GO_LIVE.md (d)(能力ごとの段階有効化)のブロッカーか
非ブロッカーかに分類した(深刻度と本番投入前必須かは別軸として判断)。LOW(F5/F6/F7)と
テスト欠落は今回も未着手(残課題のまま)。

### F1: `check_not_retail_arbitrage`のキーワード充足による実質すり抜け

- **GO_LIVE(d)判定: 非ブロッカー。** 理由: (1) publish/price_change/purchaseの実行は
  この判定結果だけでなく、常に人間の承認(`requires_human_approval`)を主たる防波堤として
  経由しており、このcomplianceチェックは自動化された副次的な防御(defense-in-depth)にすぎない。
  (2) `rationale`は現状、研究/出品/価格ロジック(ルールベース、LLM不使用)がテンプレートから
  機械的に生成しており、悪意ある人間が自由記述するフィールドではない。したがって今回のGO_LIVE(d)
  判断(出品/価格改定/自動発注/API公開の各自動実行フラグを立てるか)には影響しない。
  ただし卸直送限定はプロジェクトの最優先ルールであるため、修正自体は今回のタスクとして実施した。
- **回帰テスト**: `tests/test_guardrails_compliance_gaming.py`
  - `test_ambiguous_sourcing_hedge_with_incidental_wholesale_keyword_denies`
    (「サプライヤー在庫が薄いため、緊急時は通常ルートで確保します。詳細は別途。」がdenyされることを検証。
    修正前は`passed=True`でred確認済み)
  - `test_still_allows_unambiguous_wholesale_direct_ship_wording`(既存の正常系が壊れないことの確認)
- **修正**: `src/ebay_dropship/guardrails/__init__.py`
  - `AMBIGUOUS_SOURCING_MARKERS`("通常ルート"/"別ルート"/"他のルート"/"緊急時は"/"臨時で")を追加し、
    `check_not_retail_arbitrage`で卸キーワードの有無に関わらず、これらの表現が含まれる場合はdeny
    するチェックを、小売キーワードチェックと卸キーワードチェックの間に追加した。
  - 既存の`test_guardrails.py`(3件)・`test_guardrail_gateway.py`(全件)は無変更のまま green。

### F2: バイパス検知の静的テスト自体の2つの盲点

- **GO_LIVE(d)判定: 非ブロッカー。** 理由: この問題はテスト/CIの検知力(将来コードがバイパス経路を
  作ってしまったときに気付けるか)の話であり、現在のコードのランタイム挙動を一切変えない。
  レビュー時点で実際のバイパスが無いことは直接grepで別途確認済みであり、GO_LIVE(d)の各フラグを
  立てても、この修正の有無で本番の振る舞いは変わらない。
- **回帰テスト**: `tests/test_guardrail_gateway_static_check_robustness.py`
  - `test_legacy_scan_misses_basename_collision_bypass` /
    `test_legacy_scan_misses_alias_and_getattr_bypass`
    (修正前アルゴリズムのコピーに対して合成ツリーで反例を再現。当初は`offending != []`をassertして
    redを確認し、修正後はこの2件を「修正前の実際の挙動を恒久的に記録する」形に反転して残した
    ―― `offending == []`をassertし、"盲点が実在した証拠"として green のまま保持)
  - `test_fixed_scan_detects_basename_collision_bypass` /
    `test_fixed_scan_detects_alias_and_getattr_bypass` /
    `test_fixed_scan_still_ignores_the_real_allowed_files`(修正後の実物関数が同じ合成ツリーで
    正しく検出し、かつ本来の許可ファイルは引き続き除外することを検証)
- **修正**: `tests/test_guardrail_gateway.py`
  - 走査ロジックを`_scan_for_bypassing_write_calls(src_root, write_methods, allowed_relpaths)`
    として関数化。(a) 許可判定をbasenameからフルパス(`src/`相対、`ALLOWED_WRITE_CALL_RELPATHS`)に
    変更、(b) 素朴な部分文字列一致をASTベースの検出(`ast.Attribute`属性アクセス全般+
    `getattr(obj, '<method>')`の文字列リテラル引数)に置き換えた。
  - `test_ebay_write_methods_are_only_called_through_guardrail_gateway`は同じ関数を呼ぶよう更新。
    実コードに対する結果(バイパス無し)は修正前後で変わらず green。
  - `src/`側のコード変更は無し(F2はテスト/CI側だけの問題だったため)。

### F4: publish/price_changeの並行実行による重複実行(F3と同型)

- **GO_LIVE(d)判定: ブロッカー。** 理由: F3(purchase)がHIGHとして修正済みなのに対し、
  publish/price_changeの自動実行を本番で有効化する判断はGO_LIVE(d)がまさに問うている内容そのもの
  ("出品公開(publish)を本番で自動実行してよいか"/"価格改定(price_change)を本番で自動実行してよいか")。
  同じ構造的欠陥(状態遷移がget-then-set、実行時のAPPROVEDチェックが呼び出し元スナップショット依存)
  を残したまま自動実行を有効化すると、cronとAPIトリガーの重なり等の通常運用でも実際に
  outbound API呼び出し(publish_offer/update_offer)が二重発行されうる(実際に2スレッドで再現し、
  修正前は両方とも成功していたことを確認)。したがって修正必須と判断し、今回のタスクとして実施した。
- **回帰テスト**: `tests/test_orchestrator_do_concurrency.py`
  - `test_concurrent_execute_publish_from_two_threads_only_one_actually_publishes`
  - `test_concurrent_execute_price_change_from_two_threads_only_one_actually_applies`
    (いずれも2スレッド・独立DBセッション。修正前は両方とも`publish_offer`/`update_offer`まで到達して
    成功し、状態機械の`InvalidTransitionError`は2回目の`mark_executed`でしか衝突を検知しなかった
    ―― F3と全く同じパターンをここでも実証し、redを確認済み)
- **修正**: `src/ebay_dropship/orchestrator/do.py`
  - `execute_publish`: item/offer作成(PUT/duplicate検知で既にidempotentな2ステップ、未変更)の後、
    最後の`publish_offer`呼び出し+`ebay_listing_id`のpayload更新+executedへの確定を
    `repository.claimed_execution`(F3で追加済みのSAVEPOINTベースの原子的claim)で直列化した。
    `AlreadyClaimedError`は再送出のみ、`EbayApiError`は従来通り`mark_failed`で理由を記録してから
    再送出する(例外の型・メッセージは変更していないため、既存の4失敗モードテストは無変更で green)。
  - `execute_price_change`: 同様に`update_offer`呼び出し+payload更新+executedへの確定を
    `claimed_execution`で直列化した。
  - `store/repository.py`・`guardrails/gateway.py`は無変更(F3で追加済みの`claimed_execution`を
    再利用しただけ)。item/offer作成ステップ自体は意図的に未保護のまま残した(PUTの冪等性・
    `EbayOfferAlreadyExistsError`捕捉による重複吸収で既に安全なため、保護対象を実際にリスクのある
    最後の1手に絞ることで、中断後の再開(resumability、`update_payload`による段階的な進捗記録)を
    壊さないようにした)。

### 検証結果(F1/F2/F4共通)

- 全体テスト: `179 passed`(F3クローズ時点の170 + 今回追加9件)。`ruff check`もクリーン。
- 並行実行の回帰テスト(F3の2件+F4の2件、計4件)は5回連続実行で安定。

## LOW(F5/F6/F7)とテスト欠落の解消(2026-08-29、空き時間の仕上げ)

本番ブロッカー(F3/F4)解消後、残っていたLOW findings(F5/F6/F7)と、境界値・並行実行系の
テスト欠落を解消した。各件について再現/失敗テスト先行(red)→最小修正→green の順を守り、
対象ファイル以外は変更していない。

### F5: eBay APIの上流エラー本文が`payload.failure_reason`としてDB保存され閲覧可能

- **回帰テスト**: `tests/test_repository_failure_reason_redaction.py`
  - `test_mark_failed_redacts_bearer_token_in_reason`("Bearer <token>"を含む理由文字列。
    修正前は生保存されておりred確認済み)
  - `test_mark_failed_redacts_access_token_field_in_reason`(`"access_token": "<値>"`形式)
  - `test_mark_failed_leaves_ordinary_reason_text_unchanged`(通常の理由文字列は無変更のまま保存されることの回帰防止)
- **修正**: `src/ebay_dropship/store/repository.py`
  - `_SECRET_LIKE_PATTERN`(Bearerトークン/`access_token`・`refresh_token`・`client_secret`の
    キー値パターン)と`_redact_secret_like_values`を追加し、`mark_failed`が`payload.failure_reason`
    へ保存する直前にこれを通す。`adapters/ebay/`側(上流エラー文字列を組み立てている箇所)は
    無変更 ―― 保存直前の1箇所でサニタイズする方が、複数箇所に散らばったf-string全てを
    個別に直すより保守しやすいと判断した。
  - 既存の`test_store_repository.py`の完全一致アサーション(`"eBay API error"`等)は
    秘密情報らしきパターンを含まないため無変更のまま green。

### F6: 承認Web UIのBasic認証にタイミングサイドチャネル

- **回帰テスト**: `tests/test_api_auth_timing.py`
  - `test_compare_digest_is_also_called_for_unknown_username`(未知usernameでも
    `secrets.compare_digest`が必ず1回呼ばれることを検証。修正前は短絡評価により0回でred確認済み)
  - `test_compare_digest_is_called_for_known_username_with_wrong_password`(既知usernameとの対称性)
  - `test_valid_credentials_still_authenticate`(正常系の回帰防止)
  - wall-clockタイミングの直接計測はCI環境依存でflakyになるため、「常に同じ回数
    `compare_digest`を呼ぶ」という構造的性質で検証した(呼ぶ/呼ばないの非対称性そのものが
    タイミング差の原因であるため、これを閉じれば十分)。
- **修正**: `src/ebay_dropship/api/__init__.py::require_auth`
  - `expected_password = users.get(credentials.username, "")`(未知usernameでもダミー値を用意)
  - `password_matches = secrets.compare_digest(...)`を先に必ず実行し、その後
    `is_valid = credentials.username in users and password_matches`で判定する(username自体の
    正誤で処理経路が分岐しないようにした)。既存の`test_api.py`(fail-closed・decided_by記録等)は
    全件無変更のまま green。

### F7: 承認済みwithdraw提案が`run_do`から不可視のまま放置される

- **回帰テスト**: `tests/test_orchestrator_do_withdraw_visibility.py`
  - `test_run_do_surfaces_approved_withdraw_as_not_implemented_instead_of_vanishing`
    (修正前は`run_do`の結果が`[]`になり、承認済みwithdrawがどこにも現れないことを実行して確認済み。red)
  - `test_run_do_still_processes_other_proposals_alongside_pending_withdraw`
    (withdrawの可視化がpublish/price_changeの通常処理を壊さないことの回帰防止)
- **修正**: `src/ebay_dropship/orchestrator/do.py`
  - `WithdrawNotImplementedError`を追加し、`run_do`に`ProposalType.WITHDRAW`の分岐を追加。
    実行(eBay側API呼び出し)は依然として実装せず、この例外を`results`に積んで可視化するのみ
    (statusはapprovedのまま変更しない ―― 実行していないためexecuted/failedのいずれにも倒さない)。
  - 実際のwithdraw実行機能の実装(新しいeBay API連携・実Sandbox検証)は行っていない。
    これは意図的: 新しい外部I/Oを追加すると「実Sandbox E2E待ちのみ」という状態から後退するため、
    今回は「承認済みのまま見えなくなる」という可視性の問題だけを閉じた。実装自体は
    引き続き将来タスク(下記の残課題ではなく、機能未実装として区別する)。

### 境界値・並行実行系のテスト欠落

- **利益ガードの境界値**: `tests/test_guardrails_boundary_values.py`
  - `test_profit_guard_exactly_at_target_allows`(ちょうど目標`min_net_profit`と同額 → 許可)
  - `test_profit_guard_one_cent_below_target_denies`(下限直下・1セント下 → deny)
  - `test_profit_guard_one_cent_above_target_allows`(1セント上、対称性確認)
  - 併せて`check_rate_budget`(残数==必要数/1不足)・`check_supplier_stock`(在庫==要求数/1不足)・
    `check_supplier_data_freshness`(経過時間==許容時間ちょうど/1秒超過)の境界値テストも追加。
  - いずれも実装は変更していない(手動検証で既にoff-by-oneが無いことは確認済みだった)。
    9件すべて追加時点で green ―― 既存の正しい実装にテストカバレッジを追いつかせただけ。
- **並行実行系**: 追加のテストは無し。F3(`tests/test_orchestrator_purchase_concurrency.py`、
  purchase、スレッド+プロセス)とF4(`tests/test_orchestrator_do_concurrency.py`、publish/
  price_change、スレッド)で、副作用を持つ3つの実行系(publish/price_change/purchase)すべての
  並行実行シナリオを既にカバー済みと判断し、この時点で「並行系のテスト欠落」は解消済みとした。

### 検証結果

- 全体テスト: `196 passed`(F1/F2/F4修正時点の179 + 今回追加17件)。`ruff check`もクリーン。
- 並行実行系(F3 2件+F4 2件、計4件)は5回連続実行で安定(再確認済み)。

## 残タスク: ゼロ(コード側は完了。残るのは実Sandbox E2Eのみ)

adversarial security reviewで報告した7件(F1〜F7)はすべて対応済み(F1/F2/F4/F5/F6/F7を修正、
F3は別途修正・クローズ済み)。境界値・並行実行系のテスト欠落も解消した。

コード側でこれ以上着手すべき既知の項目は無い。残っているのは`GO_LIVE.md`のとおり
**実Sandbox認証情報が届いてからでないと着手できないこと**だけである:

- (a) OAuth・Inventory(publish/price_change)・Fulfillment(getOrders)・Analytics(get_rate_limits)の
  実Sandbox疎通確認。
- (b) 上記を通過した後の、フラグOFFのままの低リスク限定ライブ運用(監査ログ・アラート観察)。
- (c) 能力ごと(publish自動実行/price_change自動実行/自動発注/API外部公開)の、人間による
  明示的なgo-live判断。

withdraw実行機能自体の実装(F7で可視化のみ行い、機能追加はしていない)も、新しいeBay API連携が
必要になるため実質的に実Sandbox統合待ちの一部として扱う。

## Quickstart(デモ)の追加(2026-08-29)

ユーザーが実キー無し・実発注OFFのまま完成品を自分で触って確認できるよう、READMEに
「Quickstart(デモ)」節と、それを動かすための最小限のコード(`demo.py`)を追加した。

- **`src/ebay_dropship/demo.py`(新規)**: 判断ロジックは一切持たず、research/listing/pricingの
  既存ルールベースロジックへ固定フィクスチャ(架空SKU「DEMO-SKU-1」・架空listing
  「DEMO-LISTING-1」)を渡す`plan_tasks`/`act_tasks`を組み立てるだけ。`orchestrator/cycle.py::run_cycle`
  にそのまま渡せる形にしてあり、`run_cycle`自体は無変更(publish/price_change/purchaseの実行を
  一切呼ばないという既存の静的保証もそのまま有効)。
  - `seed_demo_supplier_csv`: `CsvSupplierAdapter`が読める形式でCSVを書く。`as_of`は実行時刻を
    使うため、いつ実行しても鮮度チェックに引っかからない(固定の過去日時をコミットしない)。
- **`cli/__init__.py`**: 既存動作は無変更のまま、2点だけ追加した。
  - `ebay-dropship cycle run-once`に`--demo`フラグを追加(既定Falseで従来通り空タスク実行のまま。
    `test_cycle_run_once_reports_zero_when_no_tasks_wired`は無変更でgreen)。付けるとdemo.pyの
    タスクでPlan→Actを実行する。
  - `ebay-dropship demo seed`コマンドを新設(`demo`という新しいclickグループ)。
- 生成される3件の提案(`hold`/`publish`/`price_change`)の数値はすべて実際にresearch/listing/
  pricingのコードを呼んで検算済み(README本文にも同じ数値を記載)。

**変更しなかったもの(意図的)**: `orchestrator/do.py`の実行関数(`execute_publish`等)をCLI/APIから
呼び出す経路は追加していない。今回のデモ要求(Plan/Check/Actの可視化・承認CLI/Web UIの操作)には
不要であり、追加すると実Sandbox統合前に新しい実行経路を増やすことになるため。現状、承認後の
実行はCLI/API双方から呼び出す手段がそもそも存在しない(`GO_LIVE.md`の(a)以降を参照)。

**検証**: 新規5テスト(`tests/test_demo.py`)+3テスト(`tests/test_cli_demo.py`)を追加。
既存の`tests/test_cli.py`・`tests/test_orchestrator_cycle.py`は無変更のままgreen。
さらに、フレッシュな`.venv`+`.env.example`のコピーからREADME記載のコマンド列を実際に
1行ずつ最後まで(alembic→seed→run-once --demo→proposals list/approve/reject→api serve→curl)
実行し、記載通りに動くことを確認した。全体テスト: `204 passed`。`ruff check`もクリーン。

## 承認/却下ボタン付きの簡単なHTML画面を追加(2026-08-31)

ユーザー要望で、承認Web UIに`GET /ui`を追加した。既存の`/proposals`(JSON)はAPI契約を壊さない
ため無変更のまま残し、`/ui`は別ルートとして新設(ブラウザで直接見るのは`/proposals`ではなく`/ui`)。

- `src/ebay_dropship/api/__init__.py`: 静的HTML文字列(`_UI_PAGE_HTML`、外部ライブラリ・CDN読み込み
  無し)を返すだけの`GET /ui`を追加。認証は他のエンドポイントと同じ`require_auth`を経由するため、
  `/healthz`以外は認証必須という既存方針を維持している。画面内の素のJavaScriptが、承認/却下時に
  既存の`/proposals/{id}/approve`・`/proposals/{id}/reject`をそのまま叩くだけで、サーバ側に新しい
  判断ロジック・新しい実行経路は一切追加していない。`risk_level=high`の2段階確認(`confirm=true`)も
  既存の409応答の挙動をそのまま踏襲し、ボタン側で`risk_level`を見て確認ダイアログを出してから送る。
- ブラウザのHTTP Basic認証はオリジン単位でキャッシュされるため、`/ui`にアクセスして一度認証すれば、
  画面内の`fetch('/proposals')`等は追加のログイン操作なしに同じ資格情報を再利用する(標準的な
  ブラウザの挙動であり、こちら側で何か実装したわけではない)。
- 既存の`tests/test_api.py`は無変更のままgreen。新規`tests/test_api_ui.py`
  (`test_ui_requires_auth`/`test_ui_returns_html_with_valid_auth`/
  `test_ui_wires_approve_and_reject_to_existing_endpoints`)で、認証必須・HTML応答・既存APIへの
  導線が埋め込まれていることを検証した(画面内JSの実挙動はブラウザが無いと検証できないため対象外。
  実際に`ebay-dropship demo seed`→`cycle run-once --demo`→APIサーバ起動→
  `curl -u demo:demo-pass http://127.0.0.1:.../ui`→承認ボタンが叩くのと同じリクエストをcurlで
  再現、まで通しで動作確認済み)。
- 全体テスト: `207 passed`(前回の204 + 新規3件)。`ruff check`もクリーン。

## 日本語Windows(cp932)での`alembic upgrade head`失敗を根本修正(2026-08-31)

ユーザーから、日本語Windows環境で`alembic upgrade head`実行時に`alembic.ini`の文字コードエラーが
出て手動修正が必要だった、という報告を受けた。原因を調査し、対症療法ではなく根本原因を特定して
修正した。

**根本原因**: Alembic自身(このプロジェクトのコードではなく`alembic`パッケージ内部)が
`alembic.ini`を`configparser.read(path, encoding="locale")`で読んでいる
(`alembic/util/compat.py::read_config_parser`、alembicのCLIエントリポイントから
`migrations/env.py`が実行される**前**に呼ばれる)。Pythonの`encoding="locale"`は
`locale.getencoding()`にフォールバックし、日本語WindowsではUTF-8ではなくcp932になる。
このリポジトリの`alembic.ini`にはUTF-8で書かれた日本語コメントが含まれていたため、
cp932としてデコードしようとして`UnicodeDecodeError`が発生していた(実際にファイルの生バイト列を
cp932でデコードして再現・確認済み)。この読み込み経路はAlembic内部にあり、このプロジェクトの
コードからは変更できない。

**修正**:
- `alembic.ini`: 日本語コメントを英語に書き換え、ファイル全体を非ASCIIバイト0個にした
  (確認済み)。ASCIIバイトはcp932でもUTF-8でも同一にデコードされるため、ユーザー側のロケール設定に
  一切依存せずミスマッチ自体が起こらなくなる。
- `migrations/env.py`: `logging.config.fileConfig(...)`呼び出しに`encoding="utf-8"`を明示追加。
  こちらはこのプロジェクトのコードが直接呼んでいる読み込み経路であり、`encoding`未指定だと
  Pythonの`io.text_encoding(None)`が同じくOSロケール(日本語Windowsでcp932)にフォールバックする
  ため、alembic.ini自体をASCII化した後も念のため明示した(二重の安全策)。
- `src/ebay_dropship/config.py`: `Settings.model_config`に`env_file_encoding="utf-8"`を明示追加。
  調査の結果、pydantic-settings/python-dotenvは`.env`読み込みの既定値が実質UTF-8固定
  (`dotenv_values(..., encoding='utf8')`)であり、`.env`/`.env.example`自体はロケール依存の
  問題は無いことを確認済みだが、将来のライブラリ挙動変更に備えて明示にした。
- `pyproject.toml`の`description`フィールド(日本語を含む)は**意図的に変更していない**:
  TOML仕様上パーサーは常にUTF-8として読むと規定されており(Pythonの`tomllib`もこれに従う)、
  ロケール依存の読み込み経路が無いため、今回の障害とは無関係と判断した。
- `src/`配下の`.py`ファイル内の日本語コメント・docstringも変更していない: Pythonのソースファイルは
  PEP 3120によりインタプリタが常にUTF-8として解釈するため(OSロケールに依存しない)、対象外。

**回帰テスト**: `tests/test_windows_encoding_safety.py`
- `test_alembic_ini_contains_only_ascii_bytes`(alembic.iniの非ASCIIバイト混入を将来も検出)
- `test_migrations_env_py_specifies_utf8_encoding_for_fileconfig`(env.pyのfileConfig呼び出しに
  `encoding="utf-8"`が明示されていることを静的に確認)
- `test_settings_env_file_encoding_is_explicitly_utf8`

**検証**: 実際に`alembic.ini`の生バイト列をcp932でデコードするテストを行い、修正前(日本語コメント
入り)は`UnicodeDecodeError`、修正後(ASCII化後)は正常にデコードできることを確認した。
実際に`alembic upgrade head`を実行し、マイグレーションが通ることも確認済み(Linux環境のため
cp932環境そのものの再現はできないが、根本原因の特定はAlembic自身のソースコードを直接読んで確認した
ものであり、憶測ではない)。全体テスト: `210 passed`(前回の207 + 新規3件)。`ruff check`もクリーン。

## タスク3(実eBay Sandbox E2E)着手 — このセッションからは実eBayへ接続不可(2026-08-31)

ユーザーから実Sandboxキー・テストユーザーが準備でき、GO_LIVE.md (b)の実疎通確認に進みたいとの依頼を
受けたが、着手前に本セッション(Claude Codeの実行コンテナ)から`api.sandbox.ebay.com`・
`developer.ebay.com`への送信をそれぞれ試したところ、両方とも組織のエグレスポリシーにより
`connect_rejected`(403)で拒否されることを確認した。プロキシの手順書
(`/root/.ccr/README.md`)には「403/407は組織ポリシーによる拒否であり、リトライ・回避をせず報告する
こと」と明記されているため、これ以上の接続試行はしていない。コード・認証情報の問題ではなく、
このセッションのネットワークポリシー(環境作成時に選択されるもの)がeBayのドメインを許可していない
ことが原因である。

ユーザーに状況を説明し、(a)このセッションのネットワークポリシーを見直して許可する、
(b)ユーザー自身のPC上で実疎通確認を行い、結果(secrets自体は含まない出力)をこのセッションに
共有してコード修正を行う、の2択を提示したところ、**(b)自分のPCで実行**を選択された。

これを受けて、実Sandboxキーを一切このセッション(チャット)に入力せずに済むよう、
`ebay-dropship sandbox ...` というCLIコマンド群を新設した。ユーザーが自分のPC上でこれらを実行し、
出力(トークン値やcert idそのものは含まれない設計)を共有すれば、そこから差異の分析・修正に移れる。

- `sandbox check-auth`: OAuth(refresh_tokenフロー)でアクセストークンが取得できるか確認する。
  取得したトークンの値自体は一切出力しない(長さのみ表示)。
- `sandbox rate-limits`: Developer Analytics API の`getRateLimits`(読み取り専用)。
- `sandbox get-orders [--since ...]`: Fulfillment API の`getOrders`(読み取り専用)。購入者の個人情報
  (氏名・住所等)は出力せず、orderId・ステータス・合計金額のみ要約して出力する。
- `sandbox seed-test-item --category-id <id> [--sku/--title/--description/--list-price/...]`:
  Sandbox検証用のpublish提案を承認キューに積む(この時点では何もeBayへ送信しない)。
  その後は通常通り`proposals approve`で承認する。
- `sandbox execute-publish <id> [--live] [--calls-remaining N]`: 承認済みの検証用publish提案を実行する。
  **既定はdry_run(何も送信しない)**。`--live`を明示して初めて実際にSandboxへ送信する
  (`orchestrator/do.py::execute_publish`をそのまま呼ぶだけで、判断ロジック・guardrailsは無変更)。
- いずれのコマンドも`EBAY_ENV=production`では実行そのものを拒否する(`_require_sandbox_env`、
  タスク要件「本番キー・実発注フラグは有効化しない」を構造的に強制)。

price_changeのCLI化(`sandbox execute-price-change`)は今回のタスクの範囲(a-d)に含まれていなかったため
未実装のまま。GO_LIVE.mdに次回タスクの候補として明記した。

**事前に発見した懸念(コードレビューベース、実疎通での確認はまだ)**: `adapters/ebay/auth.py`の
`EbayOAuthClient`が常に固定スコープ`https://api.ebay.com/oauth/api_scope`(基本スコープ)のみで
トークンをリフレッシュしている。Inventory/Fulfillment/Analytics(Sell API群)は本来
`sell.inventory`/`sell.fulfillment`/`sell.analytics.readonly`等の個別スコープが必要なはずで、
実際に401(insufficient scope)になる可能性がある。実疎通の結果を見てから対応する(判断ロジックの
変更ではなくスコープ設定の問題であり、`sandbox check-auth`/各コマンドの実行結果で確認できる)。

**テスト**: `tests/test_cli_sandbox.py`(12件)。実ネットワークは一切使わず、Inventory/Fulfillment/
Analyticsの最小限のルートをまとめたローカル完結のフェイクトランスポートで、
(1) `EBAY_ENV=production`では全コマンドが拒否されること、(2) `check-auth`が成功時にトークン値を
一切出力しないこと・失敗時にクリーンにエラー終了すること、(3) `rate-limits`/`get-orders`が期待した
要約を出力すること、(4) `seed-test-item`→`proposals approve`→`execute-publish`(dry-run/`--live`
両方)の一連の流れが正しく動作し、dry-runでは実送信が0件、`--live`ではInventory PUT→offer POST→
publish POSTが実際に(フェイクへ)発行されること、を検証した。

**検証**: 全体テスト`222 passed`(前回の210 + 新規12件)。`ruff check`もクリーン。
実eBay Sandboxそのものへの疎通は、本セッションからは上記の理由により未実施。ユーザーが自分のPCで
`sandbox`コマンド群を実行し、その出力(secrets自体を含まない)を共有した時点で、
タスク3の(2)(3)(GO_LIVE.md (b)の実施・差異の洗い出しと修正)を再開する。

## 次タスクへの残課題(更新)

- **タスク3継続**: ユーザーが自分のPCで`ebay-dropship sandbox check-auth`/`rate-limits`/
  `get-orders`/`seed-test-item`→`proposals approve`→`execute-publish [--live]`を実行し、
  出力(secrets自体を除く)を共有すること待ち。共有され次第、モックとの差異を
  「再現/失敗テスト→最小修正→green」の順で対応する。
- `sandbox execute-price-change`(price_changeのSandbox実行CLI化)は未実装。
- 従来からの残課題(F5/F6/F7のLOW findings、GO_LIVE.md (a)の残り3項目、境界値テスト等)は変更なし。

## OAuthスコープ不足を実401を待たずに修正(2026-09-01)

前回記録した懸念(`EbayOAuthClient`が基本スコープ固定でSell API群の個別スコープを要求していない)
について、ユーザーから「eBay公式で必須スコープが明記されているので実401を待たずに直してほしい」との
指示を受け、対応した。判断ロジック(利益ガード・承認ゲート・卸直送限定)は一切変更していない。

**方針**: ユーザートークン(refresh_tokenフロー、Sell API群用)とアプリケーショントークン
(client_credentialsフロー、ユーザー同意不要な読み取り専用API用)を明確に分け、それぞれに
適切なスコープだけを要求する。

- `src/ebay_dropship/adapters/ebay/auth.py`:
  - eBay公式のOAuthスコープURIを定数化(`BASE_SCOPE`/`SELL_INVENTORY_SCOPE`/
    `SELL_FULFILLMENT_SCOPE`/`SELL_ACCOUNT_SCOPE`/`SELL_ANALYTICS_READONLY_SCOPE`)。
  - `EbayOAuthClient`(ユーザートークン)の`DEFAULT_SCOPES`を、上記5つすべてを含む
    スペース区切り文字列に変更(1つのアクセストークンに複数スコープを持たせるのはeBay OAuthの
    標準的な使い方であり、`EbayOAuthClient`自体の構造・キャッシュ方式は変更していない)。
  - 新規`EbayApplicationOAuthClient`クラスを追加(client_credentialsフロー、`BASE_SCOPE`のみ要求)。
    既存の`EbayOAuthClient`は無変更のまま残し、重複コードは許容してリスクの低い追加とした。
  - **運用上の重要な注意**: refresh_token自体が、Sandboxの同意画面(「Get A Token」等)で
    Inventory/Fulfillment/Account/Analyticsのスコープを許可されていない場合、コード側でいくら
    要求しても`invalid_scope`で拒否される。その場合は同意をやり直してrefresh_tokenを再発行する
    必要がある(コード修正だけでは解決しない)。
- `src/ebay_dropship/adapters/ebay/client.py`:
  - `EbayClient.__init__`に`self._app_auth`(`EbayApplicationOAuthClient`)を追加。
  - `_authorized_headers`/`_request`/`_get`に`use_app_token: bool = False`引数を追加
    (**既定Falseで既存の全呼び出し箇所の挙動は無変更**)。
  - `search_competitive_listings`(Browse、特定の出品者データを扱わない読み取り専用API)のみ
    `use_app_token=True`に変更。Inventory/Fulfillment/Analyticsは引き続きユーザートークンを使う。

**回帰テスト**: `tests/test_ebay_auth_scopes.py`(新規4件、grant_typeごとに`scope`パラメータと
`Authorization`ヘッダーを記録するローカル完結のフェイクを使用)
- `test_user_token_refresh_requests_all_required_sell_scopes`(refresh_tokenの`scope`に
  5つ全部が含まれること。修正前はBASE_SCOPEのみでred)
- `test_search_competitive_listings_uses_application_token_not_user_token`(Browse呼び出しの
  `Authorization`がアプリケーショントークンであること。修正前はユーザートークンを使っておりred)
- `test_application_token_requests_only_base_scope`(アプリケーショントークンはBASE_SCOPEのみ要求)
- `test_sell_apis_continue_to_use_the_user_token`(Inventory/Fulfillment/Analyticsが
  引き続きユーザートークンを使うことの回帰防止)

**検証**: 全体テスト`226 passed`(前回の222 + 新規4件)。既存の`test_ebay_auth.py`・
`test_ebay_client.py`・`test_research_market_data.py`(Browseのテストを含む)はすべて無変更のまま
green(いずれも`grant_type`やスコープの中身までは検証しておらず、レスポンス内容のみ検証していた
ため、今回の変更と衝突しなかった)。`ruff check`もクリーン。
実eBay Sandboxでの最終確認(スコープが実際に受理されるか、refresh_token自体に必要なスコープの
同意が済んでいるか)はユーザーが自分のPCで`ebay-dropship sandbox check-auth`等を実行し、
出力を共有した時点で行う。

## `sandbox get-refresh-token`(refresh_token取得ヘルパー)を追加(2026-09-01)

ユーザーから、eBayの「Get a User Token」ツール(開発者ポータル)がaccess token(2時間)のみを
返しrefresh_token(18か月)を返さないため、authorization codeフローを自前で回してrefresh_tokenを
取得するCLIヘルパーが欲しいとの依頼を受けた。

- `src/ebay_dropship/adapters/ebay/auth.py`: 純粋なロジック関数を3つ追加(ネットワーク以外の副作用
  なし、ユニットテストしやすい設計)。
  - `build_authorization_url(client_id, redirect_uri, sandbox, scopes)`: 認可URLを組み立てる。
    `SANDBOX_AUTHORIZE_URL`(`auth.sandbox.ebay.com`)/`PRODUCTION_AUTHORIZE_URL`(`auth.ebay.com`)
    を新規定数化。スコープは既存の`DEFAULT_SCOPES`(前回追加したsell.inventory等5種)を再利用する
    (ユーザー要望どおり「既存のスコープ定義があれば再利用する」を満たす)。
  - `extract_authorization_code(redirected_url)`: リダイレクト後のURLから`code`を抽出(URLデコード
    込み)。eBayが`error`/`error_description`付きで返した場合(同意拒否等)はその内容をそのまま
    例外メッセージにする。
  - `exchange_authorization_code_for_refresh_token(http_client, client_id, client_secret, code,
    redirect_uri, sandbox)`: `grant_type=authorization_code`でトークンURLにPOSTし、レスポンスの
    dict(`refresh_token`を含む)をそのまま返す。失敗時はeBayの`error`/`error_description`を
    そのまま例外メッセージにする。`http_client`を引数で受け取る既存パターン(`EbayOAuthClient`等)を
    踏襲し、実ネットワーク無しでユニットテスト可能にした。
  - 既存の`EbayOAuthClient`/`EbayApplicationOAuthClient`は無変更。
- `src/ebay_dropship/envfile.py`(新規): `.env`ファイルの特定キーだけを書き換える最小限のヘルパー
  `upsert_env_var(path, key, value)`。既存行の中身のみ置換(無ければ追記)し、他の行・コメントは
  保持する。python-dotenv等の外部ライブラリには依存させず、単純な実装のまま個別にテストできるよう
  独立モジュールにした。
- `src/ebay_dropship/cli/__init__.py`: `sandbox get-refresh-token`コマンドを追加(対話式)。
  - `.env`から`EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET`/`EBAY_REDIRECT_URI`(RuName)/`EBAY_ENV`を読み、
    `EBAY_ENV=production`なら`auth.ebay.com`/`api.ebay.com`、それ以外はSandboxのエンドポイントを使う
    (このコマンドだけは、他の`sandbox`サブコマンドと違い意図的に`_require_sandbox_env`を適用していない
    ―― ユーザー要望どおり本番用refresh_token取得にも使える汎用ヘルパーとして設計したため)。
  - 認可URLを画面表示 → リダイレクト後のURL全体を`click.prompt`で受け取る → `code`抽出 →
    トークン交換 → `upsert_env_var`で`.env`の`EBAY_REFRESH_TOKEN=`を書き換え、という対話フロー。
  - refresh_token/client_secret/access_tokenは標準出力に一切出さない。成功時は
    `先頭 v^1.1#... / 長さ NNN文字`という形でマスクした要約のみ表示する
    (eBayのrefresh_tokenは`v^1.1#`という6文字の版数プレフィックスを持つ形式が一般的で、
    この6文字だけの露出はリスクが無い)。
  - `--env-file`オプション(既定`.env`)でテスト時に別ファイルを指定できるようにした。

**テスト**: `tests/test_ebay_refresh_token_flow.py`(11件、純粋ロジック単体)+
`tests/test_cli_sandbox_get_refresh_token.py`(5件、`httpx.Client`をローカルフェイクに差し替えた
CLI統合テスト)。
- URL組み立て(Sandbox/production切り替え、必須パラメータの中身)
- code抽出(正常系のURLデコード、eBayエラー時、code欠落時)
- トークン交換(成功時のrefresh_token取得、失敗時のeBayエラーそのままの表示)
- `.env`書き込み(新規作成・既存行の置換・他行の保持・キー未存在時の追記)
- CLI統合: 対話入力からの一連の流れが`.env`に正しく反映されること、出力にトークン値が一切
  含まれないこと(先頭6文字とマスク文言のみ)、`EBAY_ENV=production`ではproduction側のホストを
  使うこと、認証情報未設定・同意拒否・トークン交換失敗の各エラーがクリーンに終了すること

**検証**: 全体テスト`242 passed`(前回の226 + 新規16件)。`ruff check`もクリーン。
`--help`表示も確認済み。実eBayへの接続は本セッションからは行っていない(引き続きユーザーが
自分のPCで実行し、結果を共有する前提)。

---

## `execute-publish --live` を成功させるための準備(setup-selling・アスペクト自動補完)を追加(2026-09-05)

**背景**: dry-runは通っていたが、`--live`ではpublishOfferが以下の理由で失敗する見込みだった。
1. offerの`listingPolicies`が常に空({})だった(支払い/返品/配送ポリシーが未設定)。
2. `merchantLocationKey='default'`が実Sandboxアカウント上に作られていない。
3. カテゴリごとの必須item aspect(Taxonomy APIの`getItemAspectsForCategory`)が未充足だと
   publishOfferがエラーになる(`seed-test-item`は`--brand`しか埋めない)。

いずれもコードのバグではなく「Sandboxアカウント側の一度きりの初期設定」と「カテゴリ依存の
必須項目」であるため、既存の`execute_publish`のロジック(利益ガード・承認ゲート・卸直送の判断)
には一切手を入れず、以下を追加した。

### A) `ebay-dropship sandbox setup-selling`(新規、Sandbox限定)

- `src/ebay_dropship/adapters/ebay/client.py`: Account API(`opt_in_selling_policy_management`
  /`list_payment_policies`/`create_payment_policy`/`list_return_policies`/`create_return_policy`
  /`list_fulfillment_policies`/`create_fulfillment_policy`)とInventory location
  (`get_merchant_location`/`create_merchant_location`)を追加。
  - `opt_in_selling_policy_management`は「既にオプトイン済み」エラー(想定errorId=20404。
    eBay公式ドキュメントに基づく想定値で、実Sandboxで異なる場合はTask 3の実疎通で修正する)を
    握りつぶしてFalseを返す(冪等)。
  - これらはproposal(承認が必要な個別の出品/価格変更/発注)に紐づく副作用ではなく、
    アカウント全体に対する一度きりの設定操作のため、`guardrails.gateway.execute_side_effect`
    は経由させていない(意図的。既存の書き込みメソッド静的検査`test_ebay_write_methods_are_
    only_called_through_guardrail_gateway`が対象とする`create_or_update_inventory_item`等の
    4メソッドとは別名にしてあり、検査対象を広げる必要も無い)。安全策は`_require_sandbox_env()`
    (production拒否)のみで十分と判断した(D方針どおり)。
- `src/ebay_dropship/adapters/ebay/selling_setup.py`(新規): 「名前で既存ポリシー/ロケーションを
  探し、無ければ最小構成ペイロードで作成する」冪等ロジック(`run_setup_selling`)。3つのポリシーは
  `ebay-dropship-agent Default {Payment,Return,Fulfillment} Policy`という固定名で識別する。
  支払いポリシーはEBAY_USがManaged Payments前提のため`paymentMethods`を含めない最小構成にした
  (eBay公式ドキュメントの記載に基づく判断。実Sandboxでの検証待ち)。取得した4つの値
  (`EBAY_PAYMENT_POLICY_ID`/`EBAY_RETURN_POLICY_ID`/`EBAY_FULFILLMENT_POLICY_ID`/
  `EBAY_MERCHANT_LOCATION_KEY`)は既存の`envfile.upsert_env_var`で`.env`に書き込む。
- `cli/__init__.py`: `sandbox setup-selling`コマンド。`_require_sandbox_env()`必須。
  policyId/location keyの値自体は出力せず、「新規作成/既存を再利用」という状態と
  先頭数文字+長さのマスク要約のみ表示する(get-refresh-tokenと同じ方針)。

### B) `execute_publish`のoffer作成に`.env`の設定値を反映

- `orchestrator/do.py::_offer_payload`にsettings引数を追加し、`listingPolicies`に
  `EBAY_FULFILLMENT_POLICY_ID`/`EBAY_PAYMENT_POLICY_ID`/`EBAY_RETURN_POLICY_ID`(設定されている
  ものだけ)を、`merchantLocationKey`に`EBAY_MERCHANT_LOCATION_KEY`(未設定なら従来通り'default')
  を入れるようにした。dry-run/live両方の`_offer_payload`呼び出しに同じ関数を使うため、
  dry-runのプレビュー表示にも設定値がそのまま反映される(ネットワーク呼び出しは増やしていない
  ので、dry-runが「何も送信しない」という既存の不変条件は維持している)。

### C) カテゴリ必須アスペクトの自動補完

- `src/ebay_dropship/adapters/ebay/taxonomy.py`(新規): `getItemAspectsForCategory`のレスポンスから
  必須アスペクト名を抽出する`required_aspect_names`と、未指定分にプレースホルダ(既定`Unbranded`)
  を補う`complete_required_aspects`。ネットワークI/Oを持たない純粋関数として独立させ、
  ユニットテストしやすくした。
- `EbayClient.get_item_aspects_for_category`: Taxonomy APIは`get_default_category_tree_id`で
  カテゴリツリーIDを引いてから`get_item_aspects_for_category`を呼ぶ2段構成(公式仕様どおり)。
  特定の出品者データを扱わないためアプリケーショントークン(`use_app_token=True`)を使う
  (Browseと同じ扱い)。
- **適用範囲を`execute_publish`のlive実行時(`"ebay_item_id" not in payload`の初回ステップ内)に
  限定し、`seed-test-item`には追加しなかった**(要件の文面は「seed-test-item / execute-publishで」
  だったが、以下の理由で意図的に絞った):
  - `seed-test-item`は現状ネットワークI/Oを一切持たない(プロポーザルをDBに積むだけ)設計になって
    おり、承認前の段階でSandboxへの疎通を必須にする理由が無い。
  - `execute_publish`はどのみち`ebay_item_id`確定前に一度だけ通る、副作用未確定の安全な地点であり、
    ここで完結させれば`seed-test-item`経由でも他の経路(将来のPlanエージェント発の出品提案等)でも
    等しく必須アスペクトが補完される。`"ebay_item_id" not in payload`という既存の冪等ガードに
    相乗りさせているため、リトライ時に二重にTaxonomyへ問い合わせることもない。
  - Taxonomy取得はベストエフォート(`EbayApiError`を捕捉して無視)。取得に失敗しても既存の
    `item_specifics`のまま publish 自体は試みる(従来の挙動からの後退にしない)。
  - dry-runはこのブロックの手前(`if dry_run: ... return`)で復帰するため、引き続きネットワーク
    呼び出しゼロを維持する。

**変更していないもの**: 利益ガード・承認ゲート・卸直送チェック(`guardrails/`)、
`execute_price_change`・`execute_purchase`のロジック、既存の4つの書き込みメソッド静的検査の対象。

**テスト**(26件追加):
- `tests/test_taxonomy_aspects.py`(6件): 必須アスペクト抽出・プレースホルダ補完の純粋ロジック。
- `tests/test_ebay_client_selling_setup.py`(11件): 新規Account/Inventory location/Taxonomy
  メソッドの実HTTPパス・パラメータ・オプトイン済み時の冪等な振る舞い。
- `tests/test_ebay_selling_setup.py`(3件): `run_setup_selling`の初回作成・2回目冪等再利用・
  `.env`上書きを、フェイクの`EbayClient`スタブで検証。
- `tests/test_cli_sandbox.py`(既存ファイルに追加): `setup-selling`のproduction拒否・初回作成
  (マスク表示・`.env`書き込み)・2回目冪等・`execute-publish --live`でのlistingPolicies/
  merchantLocationKey注入・必須アスペクト自動補完(`Brand`指定は上書きしない)を追加。
  既存の`SandboxFakeBackend`にAccount/Inventory location/Taxonomyのルートを拡張した
  (状態を保持し、実Sandboxの「無ければ作成・有れば再利用」を模す)。

**検証**: 全体テスト`268 passed`(前回の242 + 新規26件)。`ruff check`もクリーン。
`ebay-dropship sandbox --help`/`setup-selling --help`表示も確認済み。実eBayへの接続は本セッション
からは行っていない(このコードはTask 3として引き続きユーザーが自分のPCの実Sandboxで検証する)。

**残課題**: `paymentMethods`省略や`ALREADY_OPTED_IN_ERROR_ID=20404`はeBay公式ドキュメントに基づく
想定であり、実Sandboxでの実疎通で異なることが判明した場合はTask 3の枠組み(再現/失敗テスト→
最小修正→green)で修正する。

---

## 実Sandbox疎通で判明した差異の修正: `Content-Language`/`X-EBAY-C-MARKETPLACE-ID`ヘッダー不足(2026-09-05)

**事象**: ユーザーが自分のPCで`execute-publish --live`を実行したところ、
`createOrReplaceInventoryItem`(PUT inventory_item)で`errorId 25709 "Invalid value for header
Content-Language"`が発生。モック(`SandboxFakeBackend`等)はヘッダーを検証しないため、
このコードベースには実装漏れがあってもテストがgreenのままになっていた、実Sandbox疎通で
初めて顕在化したモックと実APIの乖離(Task 3で想定していたパターンそのもの)。

**修正内容**(判断ロジック=利益ガード・承認ゲート・卸直送チェックには一切手を入れていない):

- `config.py`: `ebay_marketplace_id: str = "EBAY_US"` / `ebay_content_language: str = "en-US"` を追加
  (ハードコード禁止。marketplace変更時は`.env`の編集のみで対応できるようにする)。
- `adapters/ebay/client.py`:
  - `EbayClient.__init__`/`from_settings`が`marketplace_id`/`content_language`を受け取り、
    `self.marketplace_id`/`self.content_language`として保持するようにした。
  - `_request`/`_get`に`extra_headers`パラメータを追加(既存の`use_app_token`と同様、呼び出し側が
    必要なヘッダーだけ明示的に指定する設計。全呼び出しに無条件で付けると不要な箇所にまで
    ヘッダーが付き、実Sandboxでの別の予期しない挙動を招くリスクがあるため)。
  - `Content-Language`ヘッダーを付与: `create_or_update_inventory_item`(今回の直接原因)、
    `create_offer`・`publish_offer`・`update_offer`・`create_merchant_location`
    (いずれも Inventory API 配下の書き込み呼び出しで、同種のロケール依存フィールドを扱うため
    同じ要件が課される可能性が高いと判断し、要求どおり「同様に必要な呼び出しにも」広げた)。
  - `X-EBAY-C-MARKETPLACE-ID`ヘッダーを付与: `search_competitive_listings`(Browse API)。
    Browse APIはeBay公式ドキュメントでこのヘッダーが必須と明記されている数少ない箇所であり、
    確度が高いためこの1箇所に絞った。Account API(business policies)・Taxonomy APIは
    `marketplace_id`をクエリパラメータまたはボディの`marketplaceId`フィールドで渡す方式に
    既に対応済みのため、ここでは追加のヘッダーを付けていない(重複してヘッダーとパラメータの
    両方を要求されるとは考えにくいため、確認できていないところへの憶測でのヘッダー追加は避けた)。
  - opt_in/policy作成(Account API)・merchant location取得(GET)・Taxonomy APIには
    `Content-Language`を付けていない(書き込みでも英語以外のロケール依存テキストを持たない
    API、または読み取り専用のため不要と判断)。

**テスト**: `tests/test_ebay_client_headers.py`(新規、10件)。
- 既定値(`EBAY_US`/`en-US`)がヘッダーに使われること
- `create_or_update_inventory_item`/`create_offer`/`publish_offer`/`update_offer`/
  `create_merchant_location`が`Content-Language`を送ること
- `search_competitive_listings`が`X-EBAY-C-MARKETPLACE-ID`を送ること
- `marketplace_id`/`content_language`をカスタム値に変更した場合にヘッダーへ反映されること
- `EbayClient.from_settings`が`Settings`の値(カスタム値・既定値の両方)を正しく引き継ぐこと

**検証**: 全体テスト`278 passed`(前回の268 + 新規10件)。`ruff check`もクリーン。
実eBayへの接続は本セッションからは行っていない(ユーザーが自分のPCで`git pull`後に
`execute-publish --live`を再実行して確認する)。

**残課題**: 今回追加した2箇所以外の呼び出し(Account API/Taxonomy API/Fulfillment API)で
同種のヘッダー不足エラーが実Sandboxで判明した場合は、同じ枠組み(再現/失敗テスト→最小修正→green)
で個別に対応する。

---

## 実Sandbox疎通で判明した差異の修正: createOfferのbodyに`marketplaceId`等が不足(2026-09-05)

**事象**: Content-Languageヘッダー修正後、`execute-publish --live`のcreateOfferで
`errorId 25709 "Invalid value for marketplaceId."`が発生。`_offer_payload`が組み立てるofferの
bodyに`marketplaceId`(必須フィールド)が無かった(ヘッダーのmarketplace指定=Browse APIの
`X-EBAY-C-MARKETPLACE-ID`とは別物で、Inventory APIのcreateOfferはbody側にこのフィールドを
要求する)。これも実Sandbox疎通で初めて顕在化したモックとの乖離。

**修正内容**(判断ロジックには手を入れていない): `orchestrator/do.py::_offer_payload`に
以下を追加。
- `"sku": payload.get("sku")` — dry-runプレビューが実際に送信される内容(clientの
  `create_offer`が`{**payload, "sku": sku}`でsku引数を上書きするのと同じ値)を正しく表示できるようにした。
- `"marketplaceId": settings.ebay_marketplace_id` — 今回の直接原因。既存の`EBAY_MARKETPLACE_ID`
  設定(Content-Languageヘッダー修正時に追加済み)をそのまま流用し、新しい設定項目は増やしていない。
- `"format": "FIXED_PRICE"` — createOfferのもう1つの必須フィールド(このエージェントは即決価格の
  固定価格出品のみを扱うため、他フォーマット(オークション等)を切り替える設定は設けず固定値にした)。

`listingPolicies`/`merchantLocationKey`は前回修正済みのため変更なし。dry-run/live共通の
`_offer_payload`を経由するため、dry-runのプレビュー表示にも`marketplaceId`/`format`がそのまま
反映される(ネットワーク呼び出しは増えていない)。

**テスト**: `tests/test_cli_sandbox.py`に追加。
- `test_execute_publish_live_injects_listing_policies_and_merchant_location_from_settings`に
  `marketplaceId`/`format`/`sku`のアサーションを追加。
- `test_execute_publish_live_uses_configured_marketplace_id_in_offer_body`(新規): 
  `EBAY_MARKETPLACE_ID`をカスタム値(`EBAY_GB`)にした場合にofferのbodyへ反映されること。
- `test_execute_publish_dry_run_preview_reflects_configured_listing_policies`に
  `marketplaceId`/`format`がdry-runプレビュー文字列に含まれること、かつdry-runは引き続き
  ネットワーク呼び出しゼロ(`backend.calls == []`)であることのアサーションを追加。

**検証**: 全体テスト`279 passed`(前回の278 + 新規1件、既存2件の拡張)。`ruff check`もクリーン。
実eBayへの接続は本セッションからは行っていない(ユーザーが`git pull`後に
`execute-publish --live`を再実行して確認する)。
