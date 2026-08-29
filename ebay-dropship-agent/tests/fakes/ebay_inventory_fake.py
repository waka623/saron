"""Inventory API の擬似バックエンド。成功のみを返すモックは禁止という方針に従い、

publish拒否(item specifics不足/ポリシー違反)・レート制限・部分成功・重複の4種の
失敗シナリオを明示的に再現できるようにする。フラグで挙動を切り替える。
"""

from __future__ import annotations

import json

import httpx


class FakeInventoryBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.inventory_items: dict[str, bytes] = {}
        self.offers: dict[str, str] = {}
        self.published_offer_ids: set[str] = set()
        self.updated_offers: dict[str, bytes] = {}

        # 失敗シナリオの切り替えフラグ
        self.reject_publish_missing_specifics = False
        self.rate_limit_offer_creation = False
        self.fail_publish_with_status: int | None = None
        self.duplicate_offer_sku: str | None = None
        self.duplicate_offer_existing_id = "existing-offer-1"

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))

        if path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 7200})

        if path.startswith("/sell/inventory/v1/inventory_item/") and request.method == "PUT":
            sku = path.rsplit("/", 1)[-1]
            self.inventory_items[sku] = request.content
            return httpx.Response(204)

        if path == "/sell/inventory/v1/offer" and request.method == "POST":
            body = json.loads(request.content)
            sku = body["sku"]
            if self.rate_limit_offer_creation:
                return httpx.Response(
                    429, json={"errors": [{"errorId": 218050, "message": "Rate limit exceeded"}]}
                )
            if sku == self.duplicate_offer_sku:
                return httpx.Response(
                    400,
                    json={
                        "errors": [
                            {
                                "errorId": 25002,
                                "message": "Offer entity already exists",
                                "parameters": [{"name": "offerId", "value": self.duplicate_offer_existing_id}],
                            }
                        ]
                    },
                )
            offer_id = f"offer-{sku}"
            self.offers[sku] = offer_id
            return httpx.Response(201, json={"offerId": offer_id})

        if path.endswith("/publish") and request.method == "POST":
            offer_id = path.split("/")[-2]
            if self.reject_publish_missing_specifics:
                return httpx.Response(
                    400,
                    json={
                        "errors": [
                            {"errorId": 25007, "message": "A value is required for the aspect: Color"}
                        ]
                    },
                )
            if self.fail_publish_with_status is not None:
                status = self.fail_publish_with_status
                return httpx.Response(status, json={"errors": [{"message": "Internal error"}]})
            self.published_offer_ids.add(offer_id)
            return httpx.Response(200, json={"listingId": f"listing-{offer_id}"})

        if path.startswith("/sell/inventory/v1/offer/") and request.method == "PUT":
            offer_id = path.rsplit("/", 1)[-1]
            self.updated_offers[offer_id] = request.content
            return httpx.Response(200, json={"offerId": offer_id})

        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
