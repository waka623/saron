"""Phase 4: 承認済み proposal の実行(Do)。

このモジュールが `guardrails.gateway.execute_side_effect` の executor として実際に
eBay Sell API(Inventory)の書き込みメソッドを呼ぶ、唯一の場所である
(`tests/test_guardrail_gateway.py::test_ebay_write_methods_are_only_called_through_guardrail_gateway`
の許可リストに本ファイルが含まれる)。

スコープの切り分け: このモジュールは「承認済みproposalを実行するだけ」。
どの価格にするか・出品すべきかの判断は research/listing/pricing の仕事であり、ここでは判断しない。

冪等性・原子性の設計:
- inventory_item は PUT(仕様上べき等)。offer は POST だが、既存offerがあれば
  EbayOfferAlreadyExistsError を捕捉して既存IDを再利用する(重複出品を作らない)。
- 各ステップが成功するたびに repository.update_payload で proposal.payload に
  ebay_item_id / ebay_offer_id / ebay_listing_id を記録してから次のステップに進む。
  途中で失敗・中断しても、次回の実行は payload に記録済みのIDを見て完了済みステップを飛ばす。
- 最終的に全ステップが成功したときだけ repository.mark_executed を呼ぶ。
  途中で失敗したら repository.mark_failed で理由を記録し、例外を再送出する
  (proposals.status が EXECUTED と FAILED の中間の状態のまま残ることはない)。
- proposal は一度 EXECUTED/FAILED になると `store/repository.py` の状態機械により
  二度と実行され得ない(同じ提案の二重実行はここでも構造的に防止される)。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ebay_dropship.adapters.ebay import EbayApiError, EbayClient, EbayOfferAlreadyExistsError
from ebay_dropship.approval import Proposal, ProposalType
from ebay_dropship.config import Settings
from ebay_dropship.guardrails.gateway import execute_side_effect
from ebay_dropship.store.repository import SqlProposalRepository


def _inventory_item_payload(payload: Mapping[str, Any]) -> dict:
    item_specifics = payload.get("item_specifics") or {}
    return {
        "availability": {"shipToLocationAvailability": {"quantity": 1}},
        "condition": "NEW",
        "product": {
            "title": payload.get("title"),
            "description": payload.get("description"),
            "aspects": {key: [value] for key, value in item_specifics.items()},
        },
    }


def _offer_payload(payload: Mapping[str, Any]) -> dict:
    return {
        "categoryId": payload.get("category_id"),
        "pricingSummary": {"price": {"value": str(payload.get("list_price")), "currency": "USD"}},
        "listingPolicies": {},
        "merchantLocationKey": "default",
        "availableQuantity": 1,
    }


def execute_publish(
    proposal: Proposal,
    *,
    repository: SqlProposalRepository,
    ebay_client: EbayClient,
    settings: Settings,
    calls_remaining: int,
    dry_run: bool = False,
    source_description: str = "",
) -> Proposal:
    if proposal.proposal_type is not ProposalType.PUBLISH:
        raise ValueError(f"execute_publish は publish 提案専用です(proposal_type={proposal.proposal_type})")

    def executor(p: Proposal) -> None:
        payload = dict(p.payload)
        sku = payload["sku"]

        if dry_run:
            payload["dry_run_preview"] = {
                "inventory_item_request": _inventory_item_payload(payload),
                "offer_request": _offer_payload(payload),
            }
            repository.update_payload(p.id, payload)
            return

        if "ebay_item_id" not in payload:
            try:
                ebay_client.create_or_update_inventory_item(sku, _inventory_item_payload(payload))
            except EbayApiError as exc:
                repository.mark_failed(p.id, decided_by="orchestrator", reason=f"inventory_item失敗: {exc}")
                raise
            payload["ebay_item_id"] = sku
            repository.update_payload(p.id, payload)

        if "ebay_offer_id" not in payload:
            try:
                offer = ebay_client.create_offer(sku, _offer_payload(payload))
                payload["ebay_offer_id"] = offer["offerId"]
            except EbayOfferAlreadyExistsError as exc:
                payload["ebay_offer_id"] = exc.existing_offer_id
                payload["ebay_offer_reused"] = True
            except EbayApiError as exc:
                repository.mark_failed(p.id, decided_by="orchestrator", reason=f"offer作成失敗: {exc}")
                raise
            repository.update_payload(p.id, payload)

        try:
            result = ebay_client.publish_offer(payload["ebay_offer_id"])
        except EbayApiError as exc:
            repository.mark_failed(p.id, decided_by="orchestrator", reason=f"publish失敗: {exc}")
            raise
        payload["ebay_listing_id"] = result.get("listingId")
        repository.update_payload(p.id, payload)
        repository.mark_executed(p.id, decided_by="orchestrator")

    execute_side_effect(
        proposal,
        executor,
        settings=settings,
        calls_remaining=calls_remaining,
        calls_needed=3,
        source_description=source_description or proposal.rationale,
    )
    # gateway は渡された proposal をそのまま返すため、確定した最終状態(status/payload)を repository から取り直す。
    return repository.get(proposal.id)


def execute_price_change(
    proposal: Proposal,
    *,
    repository: SqlProposalRepository,
    ebay_client: EbayClient,
    settings: Settings,
    calls_remaining: int,
    dry_run: bool = False,
    source_description: str = "",
) -> Proposal:
    if proposal.proposal_type is not ProposalType.PRICE_CHANGE:
        raise ValueError(
            f"execute_price_change は price_change 提案専用です(proposal_type={proposal.proposal_type})"
        )

    def executor(p: Proposal) -> None:
        payload = dict(p.payload)
        offer_id = payload.get("ebay_offer_id")
        proposed_price = payload.get("proposed_price")

        if not offer_id:
            reason = "ebay_offer_id が proposal.payload に無いため価格変更を実行できません。"
            repository.mark_failed(p.id, decided_by="orchestrator", reason=reason)
            raise ValueError(reason)

        if dry_run:
            payload["dry_run_preview"] = {
                "update_offer_request": {
                    "pricingSummary": {"price": {"value": str(proposed_price), "currency": "USD"}}
                }
            }
            repository.update_payload(p.id, payload)
            return

        try:
            ebay_client.update_offer(
                offer_id,
                {"pricingSummary": {"price": {"value": str(proposed_price), "currency": "USD"}}},
            )
        except EbayApiError as exc:
            repository.mark_failed(p.id, decided_by="orchestrator", reason=f"価格変更失敗: {exc}")
            raise
        payload["applied_price"] = proposed_price
        repository.update_payload(p.id, payload)
        repository.mark_executed(p.id, decided_by="orchestrator")

    execute_side_effect(
        proposal,
        executor,
        settings=settings,
        calls_remaining=calls_remaining,
        calls_needed=1,
        source_description=source_description or proposal.rationale,
    )
    return repository.get(proposal.id)


def run_do(
    *,
    repository: SqlProposalRepository,
    ebay_client: EbayClient,
    settings: Settings,
    calls_remaining: int,
    dry_run: bool = False,
) -> list[Proposal | Exception]:
    """承認済み(APPROVED)の publish/price_change をすべて実行する。

    1件の失敗が他の提案の処理を止めないよう、例外はここで捕捉して結果リストに含める
    (各提案自身の成否は repository に確定的に記録済みなので、ここで握りつぶしても実害はない)。
    withdraw/purchase は Phase 5 のスコープのため、ここでは処理しない。
    """
    results: list[Proposal | Exception] = []
    for proposal in repository.list_approved():
        try:
            if proposal.proposal_type is ProposalType.PUBLISH:
                results.append(
                    execute_publish(
                        proposal,
                        repository=repository,
                        ebay_client=ebay_client,
                        settings=settings,
                        calls_remaining=calls_remaining,
                        dry_run=dry_run,
                    )
                )
            elif proposal.proposal_type is ProposalType.PRICE_CHANGE:
                results.append(
                    execute_price_change(
                        proposal,
                        repository=repository,
                        ebay_client=ebay_client,
                        settings=settings,
                        calls_remaining=calls_remaining,
                        dry_run=dry_run,
                    )
                )
        except Exception as exc:  # noqa: BLE001 - バッチ全体を止めないための意図的な広い捕捉
            results.append(exc)
    return results
