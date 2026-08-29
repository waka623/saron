"""compliance.md 第0章の制約をコード化する検査ロジック。全ての外部副作用実行はここを通す(第2フェーズで実装)。"""

from dataclasses import dataclass


class ComplianceError(Exception):
    """規約違反(小売アービトラージ疑い等)で提案を止めるべきときに送出する。"""


@dataclass
class GuardrailResult:
    passed: bool
    reason: str = ""


RETAIL_ARBITRAGE_KEYWORDS = (
    "amazon",
    "walmart",
    "retail arbitrage",
    "小売アービトラージ",
    "小売から仕入れ",
    "他所で買って",
)


def check_not_retail_arbitrage(source_description: str) -> GuardrailResult:
    """仕入れが卸直送(サプライヤー)ではなく小売サイトからの転送を示唆していないか検査する。"""
    raise NotImplementedError("Phase 2 で実装")


def check_requires_human_approval(proposal_type: str) -> bool:
    """publish/price_change/withdraw/purchase は必ず True を返す。"""
    raise NotImplementedError("Phase 2 で実装")


def check_profit_guard(estimated_profit: float, min_net_profit: float) -> GuardrailResult:
    """純利益が最低ラインを下回る値下げ・発注をブロックする。"""
    raise NotImplementedError("Phase 2 で実装")


def check_rate_budget(calls_remaining: int, calls_needed: int) -> GuardrailResult:
    """eBay API のコールバジェットに余裕があるか検査する。"""
    raise NotImplementedError("Phase 2 で実装")


def check_supplier_stock(available_quantity: int, requested_quantity: int) -> GuardrailResult:
    """サプライヤー在庫が受注数量を満たせるか検査する。満たせなければ hold。"""
    raise NotImplementedError("Phase 2 で実装")
