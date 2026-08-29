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

    target_margin_pct: float = 20.0
    min_net_profit: float = 5.0
    excluded_categories: str = (
        "luxury_brand_goods,authentication_required,hazmat,"
        "food_supplements_pharma,adult,gift_cards"
    )

    approval_ui_mode: str = "both"  # cli | web | both
    approval_high_risk_discount_pct: float = 15.0

    pdca_cycle: str = "daily"

    database_url: str = "sqlite:///./ebay_dropship.db"

    @property
    def excluded_categories_list(self) -> list[str]:
        return [c.strip() for c in self.excluded_categories.split(",") if c.strip()]


settings = Settings()
