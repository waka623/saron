"""eBay Sell API クライアント。OAuth・レート制限・リトライを内包する(Phase 1 で実装)。

想定 API 群(compliance.md 第3章 / PROMPT.md 第5章):
Browse(相場) / Taxonomy(カテゴリ) / Inventory(出品) / Fulfillment(受注) / Analytics(実績・レート) / Account(手数料)。
"""

from dataclasses import dataclass


@dataclass
class RateLimitStatus:
    api_name: str
    calls_remaining: int
    daily_limit: int


class EbayClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str, sandbox: bool = True):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.sandbox = sandbox

    def get_access_token(self) -> str:
        raise NotImplementedError("Phase 1 で OAuth 実装")

    def get_rate_limits(self) -> list[RateLimitStatus]:
        raise NotImplementedError("Phase 1 で Analytics API 実装")

    # --- Browse / Taxonomy (Phase 3) ---
    def search_competitive_listings(self, keywords: str, category_id: str | None = None) -> list[dict]:
        raise NotImplementedError("Phase 3 で実装")

    # --- Inventory (Phase 4) ---
    def create_or_update_inventory_item(self, sku: str, payload: dict) -> dict:
        raise NotImplementedError("Phase 4 で実装")

    def create_offer(self, sku: str, payload: dict) -> dict:
        raise NotImplementedError("Phase 4 で実装")

    def publish_offer(self, offer_id: str) -> dict:
        raise NotImplementedError("Phase 4 で実装")

    # --- Fulfillment (Phase 5) ---
    def get_orders(self, since: str | None = None) -> list[dict]:
        raise NotImplementedError("Phase 5 で実装")
