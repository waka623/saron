"""compliance.md 第0章の制約をコード化する検査ロジック。

方針(deny by default): 判定に必要な情報が不足している場合・卸直送を積極的に確認できない場合は、
安全側(deny)に倒す。「疑わしきは deny」であり、「疑わしきは通す」にはしない。

外部副作用(publish/price_change/withdraw/purchase の実行)は必ず `guardrails.gateway.execute_side_effect`
を経由すること。直接 EbayClient の書き込みメソッドを呼ぶ経路を作らない(`gateway.py` 参照)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from ebay_dropship.approval import WRITE_PROPOSAL_TYPES, ProposalType


class ComplianceError(Exception):
    """規約違反(小売アービトラージ疑い等)で提案を止めるべきときに送出する。"""


@dataclass(frozen=True)
class GuardrailResult:
    passed: bool
    reason: str = ""

    @classmethod
    def ok(cls) -> GuardrailResult:
        return cls(passed=True)

    @classmethod
    def deny(cls, reason: str) -> GuardrailResult:
        return cls(passed=False, reason=reason)


# 小売サイトから仕入れて転送する retail arbitrage を示唆する語(compliance.md 第1章)
RETAIL_ARBITRAGE_KEYWORDS: tuple[str, ...] = (
    "amazon",
    "walmart",
    "retail arbitrage",
    "小売アービトラージ",
    "小売から仕入れ",
    "小売サイトから仕入れ",
    "他所で買って",
    "小売で買って",
)

# 卸・サプライヤーからの直送であることを示す語。deny by default のため、これが確認できない限り通さない。
WHOLESALE_KEYWORDS: tuple[str, ...] = (
    "卸",
    "サプライヤー",
    "supplier",
    "wholesale",
    "direct-ship",
    "direct ship",
    "drop-ship",
    "drop ship",
    "ドロップシップ",
)


def check_not_retail_arbitrage(source_description: str) -> GuardrailResult:
    """仕入れが卸直送(サプライヤー)であることを確認する。小売アービトラージ疑い・確認不能はいずれも deny。"""
    text = (source_description or "").lower()

    for keyword in RETAIL_ARBITRAGE_KEYWORDS:
        if keyword.lower() in text:
            return GuardrailResult.deny(
                f"小売アービトラージの疑いのある表現('{keyword}')を検出。"
                "卸直送のサプライヤーに切り替える必要があります(compliance.md 第1章)。"
            )

    if not any(keyword.lower() in text for keyword in WHOLESALE_KEYWORDS):
        return GuardrailResult.deny(
            "卸・サプライヤーからの直送であることを記述から確認できません(deny by default)。"
        )

    return GuardrailResult.ok()


def check_requires_human_approval(proposal_type: ProposalType | str) -> bool:
    """publish/price_change/withdraw/purchase は必ず True。未知の値は ValueError で安全側に倒れる。"""
    normalized = ProposalType(proposal_type)
    return normalized in WRITE_PROPOSAL_TYPES


def check_profit_guard(estimated_profit: Decimal | None, min_net_profit: Decimal) -> GuardrailResult:
    """純利益が最低ラインを下回る値下げ・発注をブロックする。想定利益が計算できない場合も deny。"""
    if estimated_profit is None:
        return GuardrailResult.deny("想定純利益が計算できません(情報不足のため deny)。")
    if estimated_profit < min_net_profit:
        return GuardrailResult.deny(
            f"想定純利益 {estimated_profit} が最低ライン {min_net_profit} を下回るため deny(利益ガード)。"
        )
    return GuardrailResult.ok()


def check_rate_budget(calls_remaining: int, calls_needed: int) -> GuardrailResult:
    """eBay API のコールバジェットに、これから行う呼び出し分の余裕があるか検査する。"""
    if calls_needed <= 0:
        return GuardrailResult.deny("calls_needed は1以上を指定してください(不正な入力は deny)。")
    if calls_remaining < calls_needed:
        return GuardrailResult.deny(
            f"残コール数 {calls_remaining} が必要数 {calls_needed} に満たないため deny(レート制限)。"
        )
    return GuardrailResult.ok()


REQUIRED_PUBLISH_PAYLOAD_KEYS: tuple[str, ...] = (
    "title",
    "description",
    "category_id",
    "list_price",
    "handling_time_days",
    "item_specifics",
)


def check_publish_payload_complete(payload: dict) -> GuardrailResult:
    """実行直前の再検査(deny by default): 承認された時点の内容を鵜呑みにせず、必須項目の充足を再確認する。"""
    missing = [key for key in REQUIRED_PUBLISH_PAYLOAD_KEYS if not payload.get(key)]
    item_specifics = payload.get("item_specifics") or {}
    empty_specifics = [key for key, value in item_specifics.items() if not value]
    if missing or empty_specifics:
        return GuardrailResult.deny(
            f"publish実行直前の再検査で不備を検出: 不足キー={missing} 未入力item_specifics={empty_specifics}"
            "(deny by default)。"
        )
    return GuardrailResult.ok()


def check_supplier_data_freshness(
    as_of: datetime | None, max_age_minutes: int, now: datetime
) -> GuardrailResult:
    """サプライヤーデータ(在庫・原価・納期)の鮮度を検査する。

    無在庫ドロップシッピングの最悪の事故は「注文が入ったのに在庫が無い(古いデータで発注した)」こと。
    as_of が無い、または許容時間を超えて古い場合は deny by default で発注させない。
    """
    if as_of is None:
        return GuardrailResult.deny(
            "サプライヤーデータの取得時刻(as_of)が不明なため deny(deny by default)。"
        )
    age = now - as_of
    if age > timedelta(minutes=max_age_minutes):
        return GuardrailResult.deny(
            f"サプライヤーデータが古すぎます(as_of={as_of.isoformat()}、経過={age})。"
            f"許容{max_age_minutes}分を超過(deny by default: 陳腐化データでの発注を防ぐ)。"
        )
    return GuardrailResult.ok()


def check_supplier_stock(available_quantity: int, requested_quantity: int) -> GuardrailResult:
    """サプライヤー在庫が要求数量を満たせるか検査する。満たせなければ deny(hold扱い)。"""
    if requested_quantity <= 0:
        return GuardrailResult.deny("requested_quantity は1以上を指定してください(不正な入力は deny)。")
    if available_quantity < requested_quantity:
        return GuardrailResult.deny(
            f"サプライヤー在庫 {available_quantity} が要求数量 {requested_quantity} に満たないため deny(在庫不足)。"
        )
    return GuardrailResult.ok()
