"""F1の回帰テスト: `check_not_retail_arbitrage` のキーワード充足による実質すり抜け。

adversarial security review(2026-08-29)で、卸キーワードが1語入っているだけで、仕入れ経路が
実質的に曖昧・非該当を示唆する言い回し(「緊急時は通常ルートで確保」等)でも通過してしまうことを
実証した。「疑わしきは deny」という compliance.md の方針(guardrails/__init__.py 冒頭のdocstring)に
反する。このファイルはその反例をそのまま自動テストとして固定する。
"""

from __future__ import annotations

from ebay_dropship import guardrails


def test_ambiguous_sourcing_hedge_with_incidental_wholesale_keyword_denies():
    """卸キーワード('サプライヤー')は含むが、'緊急時は通常ルートで確保'という

    仕入れ経路を曖昧にする言い回しを伴う場合はdenyする(単純なキーワード充足だけで通さない)。
    """
    rationale = "サプライヤー在庫が薄いため、緊急時は通常ルートで確保します。詳細は別途。"
    result = guardrails.check_not_retail_arbitrage(rationale)
    assert result.passed is False


def test_still_allows_unambiguous_wholesale_direct_ship_wording():
    """既存の正常系(曖昧な言い回しを含まない卸直送の記述)は今回の変更後も通ること。"""
    result = guardrails.check_not_retail_arbitrage("卸サプライヤーが顧客へ直送する")
    assert result.passed is True
