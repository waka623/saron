# ebay-dropship-agent

eBay 上で **卸直送型の無在庫ドロップシッピング** を、承認ゲート付きで PDCA 自動化するエージェント。

> `saron` リポジトリ内の独立したサブプロジェクトです(Next.js サロン予約 SaaS 本体とは無関係)。
> このディレクトリ配下でだけ動作する Python プロジェクトとして構成しています。

## まず読むもの

1. `PROMPT.md` — システム全体の設計図(アーキテクチャ / PDCA / データモデル / eBay API 方針 / 開発フェーズ)
2. `AGENT_PROMPTS.md` — 4エージェントのプロンプトと共通提案エンベロープ
3. `compliance.md` — eBay の無在庫・ドロップシッピング規約とレート制限
4. `DECISIONS.md` — これまでの設計判断の記録
5. `GO_LIVE.md` — 本番投入前に必ず終わらせるチェックリスト(各フェーズのTODOを集約)

## Quickstart(デモ)

**実eBayキー不要・実発注OFFのまま、完成品を自分の手元で動かして確認できる。** 以下をこの順に
コピペで実行すればよい(初回だけ`.env`作成が必要。2回目以降は`cp .env.example .env`以降を省略可)。

```bash
cd ebay-dropship-agent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # 中身は既定値のままでよい(実キー欄は空のまま)

# 1) DBマイグレーション(sqlite。DATABASE_URLの既定値に対して実行)
alembic upgrade head

# 2) デモ用シードデータ投入(サプライヤーCSVを1行書くだけ。何度実行してもよい)
ebay-dropship demo seed

# 3) 「今すぐ実行」: Plan→Check→Actを1回まわし、proposalsが生成される様子を見る
ebay-dropship cycle run-once --demo

# 4) 承認CLIで一覧・承認・却下してみる(<id>は3)の出力からコピー)
ebay-dropship proposals list
ebay-dropship proposals approve <id> --by demo-user
ebay-dropship proposals reject <id> --by demo-user --reason "デモのため却下"

# 5) 最小Web UI(FastAPI)を起動して、ブラウザ/curlからも触ってみる
export APPROVAL_API_USERS="demo:demo-pass"   # username:password(カンマ区切りで複数可)
ebay-dropship api serve --port 8000
```

Web UI が起動している別ターミナルから(または起動前に`.env`へ`APPROVAL_API_USERS`を書いてもよい):

```bash
curl http://127.0.0.1:8000/healthz                              # 認証不要
curl -u demo:demo-pass http://127.0.0.1:8000/proposals           # 一覧(要Basic認証)
curl -u demo:demo-pass -X POST http://127.0.0.1:8000/proposals/<id>/approve \
     -H "Content-Type: application/json" -d '{}'
```
ブラウザから触る場合は `http://127.0.0.1:8000/proposals` にアクセスし、Basic認証ダイアログで
`demo` / `demo-pass`(上で設定した`APPROVAL_API_USERS`の値)を入力する(こちらはJSON表示)。

**承認/却下ボタン付きの簡単なHTML画面**も用意してある: `http://127.0.0.1:8000/ui` にアクセスすると
(同じくBasic認証)、承認待ちの提案が表として並び、各行に「承認」「却下」ボタンが付いた画面が開く。
ボタンは既存の`/proposals/{id}/approve`・`/proposals/{id}/reject`をブラウザ内のJavaScriptから
叩くだけで、新しい判断ロジック・新しい実行経路は追加していない(`risk_level=high`の提案を承認しようと
すると、既存の2段階確認どおり確認ダイアログが出る)。

### Windows(PowerShell、WSL不要)

上と同じ内容をWindowsネイティブのPowerShellで実行する場合のコマンド。**日本語Windows(cp932)でも
追加設定なしでそのまま通る**(`alembic.ini`等の設定ファイルを非ASCII文字なしにし、`.env`/ロギング
設定の読み込みを`encoding="utf-8"`で明示しているため。手動での文字コード修正は不要)。

```powershell
cd ebay-dropship-agent
py -m venv .venv
.venv\Scripts\Activate.ps1
```
もし「このシステムではスクリプトの実行が無効になっています」と出たら、次を実行してから
`Activate.ps1`をやり直す(このPowerShellウィンドウだけに効く一時的な変更):
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```
```powershell
pip install -e ".[dev]"
Copy-Item .env.example .env

alembic upgrade head
ebay-dropship demo seed
ebay-dropship cycle run-once --demo
ebay-dropship proposals list

$env:APPROVAL_API_USERS = "demo:demo-pass"
ebay-dropship api serve --port 8000
```
ブラウザで **http://127.0.0.1:8000/ui** を開き、Basic認証で `demo` / `demo-pass`。
承認/却下ボタン付きの画面が表示される。止めるときは `Ctrl+C`。

**手順3)で何が起きているか:** `demo.py` の固定フィクスチャ(架空SKU「DEMO-SKU-1」・架空listing
「DEMO-LISTING-1」)を使い、`research.evaluate_candidate`→`listing.generate_draft`(Plan)と
`pricing.evaluate_next_action`(Check→Act)という既存のルールベース判断ロジックを実際に呼び出す。
LLMは一切使わない。結果として `hold`(出品候補として次段へ)・`publish`(出品ドラフト)・
`price_change`(値下げ提案)の3件がそのまま承認キューに積まれるのを確認できる。

**デモ中に外部へ副作用が絶対に出ない理由(3重):**
1. `cycle run-once --demo`は`orchestrator/cycle.py::run_cycle`しか呼ばない。これは提案を
   承認キュー(DB)に積むだけの関数で、eBay/サプライヤーへの書き込みAPIを一切import/呼び出ししない
   (`tests/test_orchestrator_cycle.py::test_cycle_module_never_references_do_phase_execution`で
   静的に保証)。
2. publish/price_change/purchaseの実行(`orchestrator/do.py`の`execute_*`関数)はCLI/Web UIの
   どちらからも呼び出す経路が今は存在しない(承認/却下のみ)。手順4)5)で承認しても、それだけでは
   何もeBayへ送信されない。
3. 仮に将来Doフェーズを呼ぶコードを書いたとしても、`.env`のeBay認証情報(`EBAY_CLIENT_ID`等)は
   空のままなのでOAuthトークン取得自体が失敗する。さらに自動発注は
   `ENABLE_AUTOMATED_SUPPLIER_PURCHASE=false`(既定・go-live判断まで変更しない)でも二重にブロックされる。

## 現在のステータス: Phase 7(ダッシュボード+運用)完了・開発フェーズ最終回

- `api/`: 承認Web UI(FastAPI)。CLIと同じ `SqlProposalRepository` を共有(承認ロジックの再実装なし)。
  `/healthz` 以外は HTTP Basic 認証必須(`APPROVAL_API_USERS`、未設定なら誰も認証できないfail-closed)。
  認証されたusernameのみが`decided_by`になる(クライアントは指定不可)。`risk_level=high`の承認は
  `confirm=true`の2段階確認が必須。既定でlocalhost(127.0.0.1)のみバインド。実行(publish/price_change/
  purchase)はこのAPIでは一切行わない(承認/却下のみ)。`ebay-dropship api serve`で起動。
- `alerts/`: `Notifier`抽象インターフェース + `LoggingNotifier`(既定、ログ出力のみ)+
  `DedupingNotifier`(重複抑制/レート制限、抑制ウィンドウで同一対象への連続通知を抑える)。
  在庫乖離・不採算アラートはhold/withdraw判断の`rationale`をそのまま`reason`に転記し、
  「なぜ止まったか」が見えるようにしてある。`orchestrator/cycle.py::run_cycle`に`notifier`引数として接続。
- `GO_LIVE.md`: 各フェーズのTODOを1つのgo-liveチェックリストに集約。(a)TODO集約 →
  (b)実キー到着後に各E2Eを実Sandboxで通す → (c)フラグOFFのまま低リスク限定ライブで監査ログ/アラートを
  観察 → (d)能力ごとに人間が明示的にgo-live判断、の順で構成。
- 副次的に発見・修正したバグ: Alembicの`fileConfig`が既定で`disable_existing_loggers=True`のため、
  同一プロセス内で`alembic upgrade`を呼ぶと`ebay_dropship.alerts`等の既存ロガーが無効化されてしまう
  問題を`migrations/env.py`で修正(`disable_existing_loggers=False`)。

## 過去のステータス: Phase 6(Check+Act: PDCAを閉じる)完了

- `analytics/`: `summarize_listing_metrics`(フィクスチャ経由。実eBay Analytics API疎通は今回スコープ外、
  実キーSandbox E2Eゲートにまとめて実施)。成約率・ウォッチ率・返品率・サンプル充足・返品率乖離を計算。
- `pricing.evaluate_next_action`: AGENT_PROMPTS.mdの例を検算のうえ、数値の不一致を訂正して採用
  (詳細はDECISIONS.md参照)。price_change(クランプあり/なし)・withdraw・hold(在庫消失/データ陳腐化)・
  none(据え置き/サンプル不足/クールダウン/重複排除)をすべてルールベースで判断。
  クールダウン・最小サンプル・重複排除のフィードバック安定化ガードを実装。
- `orchestrator/cycle.py::run_cycle`: Plan→Actを1回回す直接呼べる関数(タイマー待ち不要でテスト可能)。
  `proposal_type=none`は承認キューに積まない。**publish/price_change/purchaseの実行は一切行わない**
  (承認キューに積むところまで。ソース走査で静的に保証)。
  `orchestrator/scheduler.py::CycleScheduler`がsingle-flightな薄いトリガー層(APScheduler登録は
  Phase 7予定のAPIアプリ起動時に行う)。`ebay-dropship cycle run-once`で手動実行可能。

## 過去のステータス: Phase 5(受注+サプライヤー同期)完了

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
- **`execute-publish --live` を実行する前に**、`ebay-dropship sandbox setup-selling` を一度実行しておくこと
  (支払い/返品/配送ポリシーとmerchant locationを準備する。未実行だと `listingPolicies` が空のまま
  `publishOffer` が失敗する。詳細は `GO_LIVE.md` (b) 参照)。
  必須カテゴリアスペクト(Taxonomy API)のうち `--brand` 等で未指定のものはプレースホルダで自動補完されるが、
  カテゴリによっては選択肢が限定された必須アスペクト(バリエーション必須のカテゴリ等)があり自動補完では
  通らない場合がある。Sandbox検証では、このリポジトリのテストでも使っている `--category-id 9355`
  (Cell Phones & Smartphones)のような一般的なカテゴリで試し、`execute-publish --live` が失敗する場合は
  eBay Developer Program の Taxonomy API(`getItemAspectsForCategory`)で当該カテゴリの必須アスペクトを
  確認し、`seed-test-item` のオプション追加や `item_specifics` の手動調整で対応すること。

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

`PROMPT.md` 第9章参照。第0(初期化)→第1(eBayアダプタ/Sandbox)→第2(データモデル/承認基盤)→
第3(Plan)→第4(Do)→第5(受注/サプライヤー同期)→第6(Check/Act)→第7(ダッシュボード/運用)ですべて完了。
本番投入(実キー・実publish・実自動発注)に進む前には、必ず `GO_LIVE.md` のチェックリストに従うこと。

## 最優先ルール

- 仕入れは卸・サプライヤー直送のみ。小売アービトラージは扱わない。
- publish / price_change / withdraw / purchase は必ず「提案 → 人間の承認 → 実行」。
- 公式 eBay Sell API のみ使用し、レート制限を尊重する。
- 純利益が目標を下回る値下げ・発注は自動提案しない(利益ガード)。

詳細は `CLAUDE.md` / `PROMPT.md` を参照。
