"""Phase 4/5: 承認済み proposal の実行(Do)。

このモジュールが `guardrails.gateway.execute_side_effect` の executor として実際に
eBay Sell API(Inventory)の書き込みメソッドを呼ぶ、唯一の場所である
(`tests/test_guardrail_gateway.py::test_ebay_write_methods_are_only_called_through_guardrail_gateway`
の許可リストに本ファイルが含まれる)。purchaseの発注実行(`orders/purchase_channel.py`)も同様にここが
唯一の接続点。

スコープの切り分け: このモジュールは「承認済みproposalを実行するだけ」。
どの価格にするか・出品すべきか・発注してよいかの判断は research/listing/pricing/orders の仕事であり、
ここでは判断しない(purchaseの実行時再検査=現在原価での利益再計算・在庫再確認は例外。
実行の瞬間に外部の最新状態を問い合わせる必要があるためここで行う。詳細は execute_purchase docstring)。

冪等性・原子性の設計:
- inventory_item は PUT(仕様上べき等)。offer は POST だが、既存offerがあれば
  EbayOfferAlreadyExistsError を捕捉して既存IDを再利用する(重複出品を作らない)。
- 各ステップが成功するたびに repository.update_payload で proposal.payload に
  ebay_item_id / ebay_offer_id / ebay_listing_id / purchase_reference_id を記録してから次のステップに進む。
  途中で失敗・中断しても、次回の実行は payload に記録済みのIDを見て完了済みステップを飛ばす。
- 最終的に全ステップが成功したときだけ repository.mark_executed を呼ぶ。
  途中で失敗したら repository.mark_failed で理由を記録し、例外を再送出する
  (proposals.status が EXECUTED と FAILED の中間の状態のまま残ることはない)。
- proposal は一度 EXECUTED/FAILED になると `store/repository.py` の状態機械により
  二度と実行され得ない。ただし publish/price_change はこの状態機械を get-then-set
  (`_transition`)で更新しており、並行実行(同一proposalへの同時呼び出し)そのものを
  防ぐ排他制御ではない(既知の残課題。DECISIONS.md参照)。
  purchase(execute_purchase)は `repository.claimed_execution` によるDBレベルの
  原子的な条件付き更新(compare-and-set)で実行権を獲得してから発注するため、
  並行実行下でも `purchase_channel.submit_purchase` が二重に呼ばれることはない。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ebay_dropship.adapters.ebay import EbayApiError, EbayClient, EbayOfferAlreadyExistsError
from ebay_dropship.adapters.ebay.taxonomy import complete_required_aspects, required_aspect_names
from ebay_dropship.approval import Proposal, ProposalStatus, ProposalType
from ebay_dropship.config import Settings
from ebay_dropship.guardrails import ComplianceError, GuardrailResult, check_supplier_data_freshness
from ebay_dropship.guardrails.gateway import GuardrailDenied, execute_side_effect
from ebay_dropship.orders import DEFAULT_EBAY_FEE_PCT
from ebay_dropship.orders.purchase_channel import PurchaseChannel, PurchaseOrderPacket
from ebay_dropship.pricing import calculate_net_profit
from ebay_dropship.store.repository import AlreadyClaimedError, SqlProposalRepository
from ebay_dropship.supplier import SupplierAdapter


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


def _offer_payload(payload: Mapping[str, Any], settings: Settings) -> dict:
    # listingPolicies/merchantLocationKey/marketplaceId は `sandbox setup-selling` が .env に
    # 書き込んだ値、またはmarketplaceの既定設定値を使う。未設定(空文字)のポリシーは省略する
    # (eBay側で「値なし」と「無効なID」を区別させないため)。
    # marketplaceId・format はcreateOfferの必須フィールド(errorId 25709 "Invalid value for
    # marketplaceId."の原因だった。実Sandbox疎通で確認済み)。ヘッダーのmarketplace指定だけでは
    # 不足しており、body自体に含める必要がある。
    listing_policies = {}
    if settings.ebay_fulfillment_policy_id:
        listing_policies["fulfillmentPolicyId"] = settings.ebay_fulfillment_policy_id
    if settings.ebay_payment_policy_id:
        listing_policies["paymentPolicyId"] = settings.ebay_payment_policy_id
    if settings.ebay_return_policy_id:
        listing_policies["returnPolicyId"] = settings.ebay_return_policy_id
    return {
        "sku": payload.get("sku"),
        "marketplaceId": settings.ebay_marketplace_id,
        "format": "FIXED_PRICE",
        "categoryId": payload.get("category_id"),
        "pricingSummary": {"price": {"value": str(payload.get("list_price")), "currency": "USD"}},
        "listingPolicies": listing_policies,
        "merchantLocationKey": settings.ebay_merchant_location_key or "default",
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
                "offer_request": _offer_payload(payload, settings),
            }
            repository.update_payload(p.id, payload)
            return

        if "ebay_item_id" not in payload:
            # カテゴリ必須アスペクトの自動補完(Taxonomy API)。ベストエフォート: 取得に失敗しても
            # 既存の item_specifics のまま publish 自体は試みる(dry_run はネットワーク無しを維持する
            # ため、ここは live 実行時のみ)。
            try:
                aspects = ebay_client.get_item_aspects_for_category(payload.get("category_id"))
                payload["item_specifics"] = complete_required_aspects(
                    payload.get("item_specifics") or {}, required_aspect_names(aspects)
                )
            except EbayApiError:
                pass
            try:
                ebay_client.create_or_update_inventory_item(sku, _inventory_item_payload(payload))
            except EbayApiError as exc:
                repository.mark_failed(p.id, decided_by="orchestrator", reason=f"inventory_item失敗: {exc}")
                raise
            payload["ebay_item_id"] = sku
            repository.update_payload(p.id, payload)

        if "ebay_offer_id" not in payload:
            try:
                offer = ebay_client.create_offer(sku, _offer_payload(payload, settings))
                payload["ebay_offer_id"] = offer["offerId"]
            except EbayOfferAlreadyExistsError as exc:
                payload["ebay_offer_id"] = exc.existing_offer_id
                payload["ebay_offer_reused"] = True
            except EbayApiError as exc:
                repository.mark_failed(p.id, decided_by="orchestrator", reason=f"offer作成失敗: {exc}")
                raise
            repository.update_payload(p.id, payload)

        # F4: item/offer作成(PUT/duplicate検知で既にidempotentな2ステップ)とは別に、最後の
        # publish_offer呼び出しとexecutedへの確定は F3(execute_purchase)と同じ原子的な条件付き
        # 更新(claimed_execution、SAVEPOINT)で直列化する。実行権を獲得できなければ
        # AlreadyClaimedError が送出され、publish_offer は一切呼ばれない。
        try:
            with repository.claimed_execution(p.id, decided_by="orchestrator"):
                result = ebay_client.publish_offer(payload["ebay_offer_id"])
                payload["ebay_listing_id"] = result.get("listingId")
                repository.update_payload(p.id, payload)
        except AlreadyClaimedError:
            raise
        except EbayApiError as exc:
            repository.mark_failed(p.id, decided_by="orchestrator", reason=f"publish失敗: {exc}")
            raise

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

        # F4: execute_publishと同様、外部呼び出し(update_offer)とexecutedへの確定を
        # claimed_execution(SAVEPOINT)で直列化する。
        try:
            with repository.claimed_execution(p.id, decided_by="orchestrator"):
                ebay_client.update_offer(
                    offer_id,
                    {"pricingSummary": {"price": {"value": str(proposed_price), "currency": "USD"}}},
                )
                payload["applied_price"] = proposed_price
                repository.update_payload(p.id, payload)
        except AlreadyClaimedError:
            raise
        except EbayApiError as exc:
            repository.mark_failed(p.id, decided_by="orchestrator", reason=f"価格変更失敗: {exc}")
            raise

    execute_side_effect(
        proposal,
        executor,
        settings=settings,
        calls_remaining=calls_remaining,
        calls_needed=1,
        source_description=source_description or proposal.rationale,
    )
    return repository.get(proposal.id)


def execute_purchase(
    proposal: Proposal,
    *,
    repository: SqlProposalRepository,
    supplier: SupplierAdapter,
    purchase_channel: PurchaseChannel,
    settings: Settings,
    calls_remaining: int,
    fee_pct: Decimal = DEFAULT_EBAY_FEE_PCT,
    shipping_cost: Decimal = Decimal(0),
    dry_run: bool = False,
    now: datetime | None = None,
) -> Proposal:
    """承認済み purchase 提案を実行する。

    実行時再検査(deny by default、承認時点の数字を信用しない):
    発注の瞬間にサプライヤーへ再度問い合わせ、(1) データが陳腐化していないか、(2) 現在原価で
    利益を再計算してガードを満たすか、(3) 現在の在庫が要求数量を満たすか、を確認する。
    いずれかに問題があれば発注(purchase_channel.submit_purchase)を一切呼ばずに失敗として扱う。

    (a) 実発注は `settings.enable_automated_supplier_purchase` が False の間、常に
        `purchase_channel`(既定は ManualOrderPurchaseChannel = 発注パケットの記録のみ、実送信なし)
        に対してのみ行う。実サプライヤーへの自動発注APIはこのコードベースに存在しない
        (DECISIONS.md の Phase 5 節を参照。フラグをTrueにしても実装が無いため何も起きない)。
    """
    if proposal.proposal_type is not ProposalType.PURCHASE:
        raise ValueError(f"execute_purchase は purchase 提案専用です(proposal_type={proposal.proposal_type})")

    if proposal.status != ProposalStatus.APPROVED:
        raise ComplianceError(
            f"承認されていない提案(status={proposal.status})は実行できません。承認ワークフローを経由してください。"
        )

    now = now or datetime.now(UTC)
    sku = proposal.payload["sku"]
    requested_quantity = proposal.payload.get("quantity", 1)

    try:
        stock = supplier.fetch_stock(sku)
    except KeyError as exc:
        reason = f"実行時再検査: サプライヤーにSKU={sku}が見つからず在庫消失の疑い。"
        repository.mark_failed(proposal.id, decided_by="orchestrator", reason=reason)
        raise GuardrailDenied([GuardrailResult.deny(reason)]) from exc

    freshness = check_supplier_data_freshness(stock.as_of, settings.supplier_data_max_age_minutes, now)
    if not freshness.passed:
        reason = f"実行時再検査(同期ラグ): {freshness.reason}"
        repository.mark_failed(proposal.id, decided_by="orchestrator", reason=reason)
        raise GuardrailDenied([freshness])

    current_profit = calculate_net_profit(
        Decimal(str(proposal.payload["customer_paid"])), stock.cost, fee_pct, shipping_cost
    )

    def executor(p: Proposal) -> None:
        payload = dict(p.payload)

        if dry_run:
            payload["dry_run_preview"] = {
                "purchase_packet": {
                    "order_id": payload["order_id"],
                    "sku": sku,
                    "quantity": requested_quantity,
                    "unit_cost": str(stock.cost),
                    "ship_to_country": payload.get("ship_to_country"),
                }
            }
            repository.update_payload(p.id, payload)
            return

        if payload.get("purchase_reference_id"):
            # 中断からの再開: 既に発注パケットを記録済み(冪等。submit_purchaseは呼ばない)。
            # 実行権の獲得(executedへの遷移)自体は他の実行者と競合しうるため、ここも
            # claimed_execution 経由の原子的な条件付き更新で行う。
            with repository.claimed_execution(p.id, decided_by="orchestrator"):
                pass
            return

        # F3: 発注権の獲得(DBレベルの原子的な条件付き更新)と実際の発注呼び出しを
        # 1つのSAVEPOINTとして直列化する。実行権を獲得できなければ AlreadyClaimedError が
        # 送出され、submit_purchase は一切呼ばれない(二重発注防止の主保証)。
        # 発注呼び出し自体が失敗した場合は、このSAVEPOINT(claimによるexecutedへの変更を含む)
        # がまるごとロールバックされ status は approved に戻るため、その後 mark_failed で
        # 理由付きの failed へ遷移させる。
        try:
            with repository.claimed_execution(p.id, decided_by="orchestrator"):
                packet = PurchaseOrderPacket(
                    order_id=payload["order_id"],
                    sku=sku,
                    quantity=requested_quantity,
                    unit_cost=stock.cost,
                    supplier_name="csv_supplier",
                    ship_to_country=payload.get("ship_to_country", ""),
                )
                result = purchase_channel.submit_purchase(packet)
                if result.status == "failed":
                    raise RuntimeError(result.detail)

                payload["purchase_reference_id"] = result.reference_id
                payload["purchase_status"] = result.status
                payload["supplier_cost"] = stock.cost
                payload["recalculated_profit"] = current_profit
                repository.update_payload(p.id, payload)
        except AlreadyClaimedError:
            # 既に他の実行者が実行権を獲得済み(勝者側がexecuted/failedを確定させている)。
            # ここでは副作用を何も呼んでおらず、追加の状態遷移も行わない。
            raise
        except Exception as exc:
            # 発注権は獲得できたが発注呼び出し自体が失敗した(SAVEPOINTロールバック済みでstatusはapproved)。
            repository.mark_failed(p.id, decided_by="orchestrator", reason=f"発注記録失敗: {exc}")
            raise

    execute_side_effect(
        proposal,
        executor,
        settings=settings,
        calls_remaining=calls_remaining,
        calls_needed=1,
        available_quantity=stock.quantity,
        requested_quantity=requested_quantity,
        current_profit_override=current_profit,
    )
    return repository.get(proposal.id)


class WithdrawNotImplementedError(Exception):
    """F7: withdraw提案は承認ゲートを通過するが、実行するeBay API連携がまだ実装されていない。

    承認済みのまま run_do から見えなくなる(サイレントに放置される)ことを防ぐため、
    実行を試みる代わりにこの例外を run_do の結果へ明示的に積む。status は approved のまま
    変更しない(実行していないため executed/failed のいずれにも倒さない)。
    """


def run_do(
    *,
    repository: SqlProposalRepository,
    ebay_client: EbayClient,
    settings: Settings,
    calls_remaining: int,
    dry_run: bool = False,
    supplier: SupplierAdapter | None = None,
    purchase_channel: PurchaseChannel | None = None,
) -> list[Proposal | Exception]:
    """承認済み(APPROVED)の publish/price_change/purchase をすべて実行する。

    1件の失敗が他の提案の処理を止めないよう、例外はここで捕捉して結果リストに含める
    (各提案自身の成否は repository に確定的に記録済みなので、ここで握りつぶしても実害はない)。
    supplier/purchase_channel が未指定の場合、purchase 提案はスキップする。
    withdraw は実行するeBay API連携が未実装のため、承認済みでも実行はせず
    `WithdrawNotImplementedError` を結果に積んで可視化する(F7、DECISIONS.md参照)。
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
            elif proposal.proposal_type is ProposalType.PURCHASE and supplier and purchase_channel:
                results.append(
                    execute_purchase(
                        proposal,
                        repository=repository,
                        supplier=supplier,
                        purchase_channel=purchase_channel,
                        settings=settings,
                        calls_remaining=calls_remaining,
                        dry_run=dry_run,
                    )
                )
            elif proposal.proposal_type is ProposalType.WITHDRAW:
                raise WithdrawNotImplementedError(
                    f"proposal {proposal.id} はwithdrawですが実行するeBay API連携が未実装のため、"
                    "何も実行していません(承認済みのまま残ります。実装まではDECISIONS.md参照)。"
                )
        except Exception as exc:  # noqa: BLE001 - バッチ全体を止めないための意図的な広い捕捉
            results.append(exc)
    return results
