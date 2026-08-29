from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ebay_env: str = "sandbox"
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_redirect_uri: str = ""
    ebay_refresh_token: str = ""

    supplier_integration_mode: str = "csv"  # csv | api
    supplier_csv_path: str = "./data/supplier_feed.csv"
    supplier_api_base_url: str = ""
    supplier_api_key: str = ""
    # サプライヤーデータ(在庫・原価・納期)の鮮度閾値。無在庫最大の事故(古いデータでの発注)を防ぐ。
    supplier_data_max_age_minutes: int = 1440  # 24時間

    # 実発注(自動)は実サプライヤー統合+明示的go-liveまでOFF固定。安易に変更しないこと(DECISIONS.md参照)。
    enable_automated_supplier_purchase: bool = False

    # 金額・率は Decimal 固定(float禁止)。pydantic-settings は .env の文字列から Decimal へ直接変換する。
    target_margin_pct: Decimal = Decimal(20)
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
