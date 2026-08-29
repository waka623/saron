"""guardrails.gateway.execute_side_effect が唯一の副作用実行経路であることのテスト。

(a) 承認済み+全guardrail通過でのみ executor が呼ばれる
(b) 各guardrailのいずれかが deny なら executor は一切呼ばれない(deny by default)
(c) EbayClient の書き込みメソッドが gateway 以外から呼ばれていないことを静的に検査する(バイパス経路が無いことの機械的な証拠)
"""

from __future__ import annotations

import ast
import pathlib
from decimal import Decimal

import pytest

from ebay_dropship.approval import Priority, Proposal, ProposalStatus, ProposalType, RiskLevel
from ebay_dropship.config import Settings
from ebay_dropship.guardrails.gateway import GuardrailDenied, execute_side_effect

SETTINGS = Settings(min_net_profit=Decimal("5.0"))


def _proposal(**overrides) -> Proposal:
    defaults = {
        "proposal_type": ProposalType.PRICE_CHANGE,
        "priority": Priority.MEDIUM,
        "summary": "値下げ提案",
        "rationale": "卸サプライヤーからの直送。純利益を再計算。",
        "risk_level": RiskLevel.LOW,
        "estimated_profit": Decimal("8.0"),
        "requires_human_approval": True,
        "status": ProposalStatus.APPROVED,
    }
    defaults.update(overrides)
    return Proposal(**defaults)


def test_executes_when_approved_and_all_guardrails_pass():
    calls: list[Proposal] = []

    result = execute_side_effect(
        _proposal(), calls.append, settings=SETTINGS, calls_remaining=10, calls_needed=1
    )

    assert len(calls) == 1
    assert result.status == ProposalStatus.APPROVED  # ステータス遷移自体は repository の仕事(Phase 2 の別モジュール)


def test_blocks_when_not_approved():
    calls: list[Proposal] = []
    proposal = _proposal(status=ProposalStatus.PENDING)

    with pytest.raises(Exception, match="承認されていない"):
        execute_side_effect(proposal, calls.append, settings=SETTINGS, calls_remaining=10)

    assert calls == []


def test_blocks_on_retail_arbitrage_wording():
    calls: list[Proposal] = []
    proposal = _proposal(rationale="Amazonで買って発送する想定")

    with pytest.raises(GuardrailDenied):
        execute_side_effect(proposal, calls.append, settings=SETTINGS, calls_remaining=10)

    assert calls == []


def test_blocks_on_insufficient_rate_budget():
    calls: list[Proposal] = []

    with pytest.raises(GuardrailDenied):
        execute_side_effect(_proposal(), calls.append, settings=SETTINGS, calls_remaining=0, calls_needed=1)

    assert calls == []


def test_blocks_on_profit_below_guard_for_price_change():
    calls: list[Proposal] = []
    proposal = _proposal(estimated_profit=Decimal("1.0"))

    with pytest.raises(GuardrailDenied):
        execute_side_effect(proposal, calls.append, settings=SETTINGS, calls_remaining=10)

    assert calls == []


def test_blocks_purchase_on_insufficient_stock():
    calls: list[Proposal] = []
    proposal = _proposal(
        proposal_type=ProposalType.PURCHASE,
        rationale="卸サプライヤーへ発注する",
        estimated_profit=Decimal("8.0"),
    )

    with pytest.raises(GuardrailDenied):
        execute_side_effect(
            proposal,
            calls.append,
            settings=SETTINGS,
            calls_remaining=10,
            available_quantity=0,
            requested_quantity=1,
        )

    assert calls == []


def test_blocks_purchase_when_stock_info_missing():
    """deny by default: 数量情報が無ければ在庫があるかもしれなくても実行しない。"""
    calls: list[Proposal] = []
    proposal = _proposal(proposal_type=ProposalType.PURCHASE, rationale="卸サプライヤーへ発注する")

    with pytest.raises(GuardrailDenied):
        execute_side_effect(proposal, calls.append, settings=SETTINGS, calls_remaining=10)

    assert calls == []


def test_blocks_when_requires_human_approval_flag_is_inconsistent():
    calls: list[Proposal] = []
    proposal = _proposal(requires_human_approval=False)

    with pytest.raises(GuardrailDenied):
        execute_side_effect(proposal, calls.append, settings=SETTINGS, calls_remaining=10)

    assert calls == []


#: このリポジトリで唯一 eBay 書き込みメソッドの呼び出しが許されている接続点(src/ からの相対パス)。
#: F2(adversarial security review, 2026-08-29): 以前はファイル名(basename)だけで判定しており、
#: `src/どこか/do.py` のような無関係な同名ファイルが誤って除外される穴があった。フルパスで判定する。
ALLOWED_WRITE_CALL_RELPATHS = {
    "ebay_dropship/adapters/ebay/client.py",
    "ebay_dropship/guardrails/gateway.py",
    "ebay_dropship/orchestrator/do.py",
}


def _scan_for_bypassing_write_calls(
    src_root: pathlib.Path, write_methods: tuple[str, ...], allowed_relpaths: set[str]
) -> list[str]:
    """`allowed_relpaths` 以外の *.py で `write_methods` のいずれかへの属性アクセスを検出する。

    F2: 以前は `f".{method}("` という素朴な部分文字列一致だったため、
    `bound = client.create_offer; bound(...)` のようなエイリアス代入や
    `getattr(client, 'publish_offer')(...)` のようなreflectionをすり抜けた。
    ASTベースで (a) 属性アクセスそのもの(呼び出しの形を問わない)と (b) `getattr(obj, '<method>')`
    の第2引数の文字列リテラルの両方を検出する(deny by defaultの精神: 誤検知の可能性より見逃しを避ける)。
    """
    offending: list[str] = []
    for path in src_root.rglob("*.py"):
        relpath = path.relative_to(src_root).as_posix()
        if relpath in allowed_relpaths:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in write_methods:
                offending.append(f"{relpath}::{node.attr}(属性アクセス、行{node.lineno})")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in write_methods
            ):
                offending.append(f"{relpath}::{node.args[1].value}(getattr経由、行{node.lineno})")
    return offending


def test_ebay_write_methods_are_only_called_through_guardrail_gateway():
    """静的検査: EbayClient の書き込みメソッド呼び出しは、定義箇所と gateway 自身を除いてコードベースに存在しないこと。

    Phase 4 で実際の eBay 書き込みを実装する際、guardrails.gateway.execute_side_effect の
    executor コールバック以外から EbayClient.create_offer 等を呼ぶコードを追加すると、このテストが失敗する。
    """
    write_methods = ("create_or_update_inventory_item", "create_offer", "publish_offer", "update_offer")
    src_root = pathlib.Path(__file__).resolve().parents[1] / "src"

    offending = _scan_for_bypassing_write_calls(src_root, write_methods, ALLOWED_WRITE_CALL_RELPATHS)

    assert offending == [], f"guardrails.gateway を経由しない eBay 書き込み呼び出しを検出: {offending}"
