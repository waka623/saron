from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_file_encoding="utf-8": 明示しておく(pydantic-settings/python-dotenvの既定も実質UTF-8だが、
    # 日本語コメントを含む.env/.env.exampleをロケール依存で読まれる余地を残さないため明示にする)。
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # S0(2026-09-06、DECISIONS.md参照): どの販路(SalesChannel実装)を使うかの選択。既定はeBay
    # (誤爆防止。Shopifyは明示的に"shopify"を設定した場合のみ選ばれる)。
    channel: str = "ebay"

    # --- Shopify Admin API(S1、channels/shopify.py) ---
    # カスタムアプリのAdmin APIアクセストークンで認証する(OAuthアプリではない)。
    shopify_store_domain: str = ""  # 例: "my-store.myshopify.com"
    shopify_access_token: str = ""
    # 仮定の既定値は置かない(明示設定必須)。https://shopify.dev/docs/api/usage/versioning で
    # 現在のstableバージョンを確認して設定すること。
    shopify_api_version: str = ""

    # --- Printify(POD、S2、pod/・adapters/printify/) ---
    printify_api_token: str = ""
    printify_shop_id: str = ""
    # レベルB(承認必須)の deny-by-default ガード: 原価がこれを超える発注提案はhold(自動発注しない)。
    # 仮の初期値(要ユーザー確認・調整。安全側=低めに設定してある)。
    max_supplier_order_cost: Decimal = Decimal("50.00")

    ebay_env: str = "sandbox"
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_redirect_uri: str = ""
    ebay_refresh_token: str = ""
    # `sandbox setup-selling` が作成/取得して書き込む値(execute_publish の offer 作成に使う)。
    # 未設定のままだと listingPolicies が空になり、--live の publishOffer が失敗する(DECISIONS.md参照)。
    ebay_payment_policy_id: str = ""
    ebay_return_policy_id: str = ""
    ebay_fulfillment_policy_id: str = ""
    ebay_merchant_location_key: str = "default"
    # Inventory/Offer系の書き込み呼び出しに必須のヘッダー(errorId 25709等の回避)。
    # marketplaceに対応する値へ変更する場合は、両方をあわせて変更すること(組み合わせが不整合だと
    # eBay側で別のエラーになりうる)。
    ebay_marketplace_id: str = "EBAY_US"
    ebay_content_language: str = "en-US"

    # --- eBay Marketplace Account Deletion/Closure 通知(api/account_deletion.py) ---
    # eBay開発者ポータルにこのアプリのエンドポイントURLとverificationTokenを登録すると、
    # eBayがGETでチャレンジを送ってくる(challengeResponse検証)。値は本番投入準備が整うまで空でよい。
    ebay_deletion_verification_token: str = ""
    ebay_deletion_endpoint_url: str = ""

    supplier_integration_mode: str = "csv"  # csv | api
    supplier_csv_path: str = "./data/supplier_feed.csv"
    supplier_api_base_url: str = ""
    supplier_api_key: str = ""
    # サプライヤーデータ(在庫・原価・納期)の鮮度閾値。無在庫最大の事故(古いデータでの発注)を防ぐ。
    supplier_data_max_age_minutes: int = 1440  # 24時間

    # 実発注(自動)は実サプライヤー統合+明示的go-liveまでOFF固定。安易に変更しないこと(DECISIONS.md参照)。
    enable_automated_supplier_purchase: bool = False

    # --- S3: スケジュール自走(オプトイン、レベルB。DECISIONS.md参照) ---
    # 既定はすべて安全側(自走オフ)。何も設定しなければ人間の承認なしに何も自動実行されない。
    autonomy_enabled: bool = False
    # "お金が動かない"publish系のみが対象(guardrails/autonomy.pyのAUTO_APPROVABLE_TYPESでコード固定。
    # このフラグをTrueにしても、supplier_purchase等の金銭・破壊系が自動承認されることはない)。
    auto_approve_publish: bool = False
    # 1回のrun-cycleで自動承認してよい件数の上限(暴走防止。小さめの既定値)。
    max_auto_actions_per_run: int = 3
    # 緊急停止スイッチ。Trueの間はautonomy_enabledの値に関わらず自動承認を一切行わない
    # (autonomy_enabledと分離しているのは、「これだけ倒せば確実に止まる」独立した経路を残すため)。
    autonomy_kill_switch: bool = False

    # 金額・率は Decimal 固定(float禁止)。pydantic-settings は .env の文字列から Decimal へ直接変換する。
    # 2026-09-06: 経営判断により20%→15%へ引き下げ(DECISIONS.md参照)。min_net_profit($5)は不変。
    target_margin_pct: Decimal = Decimal(15)
    min_net_profit: Decimal = Decimal("5.0")
    excluded_categories: str = (
        "luxury_brand_goods,authentication_required,hazmat,"
        "food_supplements_pharma,adult,gift_cards"
    )

    approval_ui_mode: str = "both"  # cli | web | both
    approval_high_risk_discount_pct: Decimal = Decimal(15)

    pdca_cycle: str = "daily"

    # --- pricing(Act)のフィードバック安定化ガード ---
    pricing_cooldown_days: int = 7  # 同一listingへの変更提案は直近この日数以内は再提案しない
    pricing_min_sample_views: int = 30  # これ未満のview数ではactionせずnone(データが薄いうちは動かさない)
    pricing_discount_step_pct: Decimal = Decimal(10)  # 値下げ検討時の初手の下げ幅(%)

    database_url: str = "sqlite:///./ebay_dropship.db"

    # --- 承認Web UI(api/) ---
    # "username:password" のカンマ区切り。未設定(空文字)なら誰も認証できない(fail-closed)。
    approval_api_users: str = ""
    approval_api_host: str = "127.0.0.1"  # 既定でlocalhostのみ。外部公開はリバースプロキシ+TLS必須
    approval_api_port: int = 8000

    @property
    def excluded_categories_list(self) -> list[str]:
        return [c.strip() for c in self.excluded_categories.split(",") if c.strip()]


settings = Settings()
