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

    database_url: str = "sqlite:///./ebay_dropship.db"

    @property
    def excluded_categories_list(self) -> list[str]:
        return [c.strip() for c in self.excluded_categories.split(",") if c.strip()]


settings = Settings()
