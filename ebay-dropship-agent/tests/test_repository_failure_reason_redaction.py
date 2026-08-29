"""F5の回帰テスト: `mark_failed`に渡された理由文字列に紛れ込んだ秘密情報らしき値の再発防止。

adversarial security review(2026-08-29)で、eBay APIの上流エラー本文(`response.text`)が
そのまま`EbayApiError`/`EbayAuthError`のメッセージに埋め込まれ、それが`repository.mark_failed`
経由で`proposal.payload["failure_reason"]`としてDB保存され、認証済みAPIの`GET /proposals`から
閲覧可能であることを指摘した(現状トークン自体が漏れている確認は取れていないが、サニタイズ層が
無いため、将来eBay側のレスポンスが偶然トークン風の文字列を含んだ場合に無防備)。

このファイルは、`mark_failed`に渡した理由文字列に含まれるBearerトークン/`access_token`等の
値がpayloadに生で保存されないことを検証する。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ebay_dropship.approval import Priority, Proposal, ProposalType, RiskLevel
from ebay_dropship.store import Base, SqlProposalRepository


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    return SqlProposalRepository(session)


def _seed_approved(repo) -> Proposal:
    proposal = Proposal(
        proposal_type=ProposalType.PRICE_CHANGE,
        priority=Priority.MEDIUM,
        summary="値下げ提案(テスト)",
        rationale="卸サプライヤー在庫を確認済み。",
        risk_level=RiskLevel.LOW,
        estimated_profit=Decimal("8.0"),
        requires_human_approval=True,
        payload={},
    )
    saved = repo.enqueue(proposal)
    return repo.approve(saved.id, decided_by="alice")


def test_mark_failed_redacts_bearer_token_in_reason(repo):
    proposal = _seed_approved(repo)
    reason = (
        "価格変更失敗: 401 Unauthorized. Authorization: Bearer abcDEF123secretTokenValue456"
    )

    result = repo.mark_failed(proposal.id, decided_by="orchestrator", reason=reason)

    assert "abcDEF123secretTokenValue456" not in result.payload["failure_reason"]
    assert "[REDACTED]" in result.payload["failure_reason"]


def test_mark_failed_redacts_access_token_field_in_reason(repo):
    proposal = _seed_approved(repo)
    reason = (
        '価格変更失敗: 500 {"access_token": "verySecretAccessToken789", "error": "server_error"}'
    )

    result = repo.mark_failed(proposal.id, decided_by="orchestrator", reason=reason)

    assert "verySecretAccessToken789" not in result.payload["failure_reason"]


def test_mark_failed_leaves_ordinary_reason_text_unchanged(repo):
    """秘密情報らしきパターンを含まない通常の理由文字列は、これまで通りそのまま保存される。"""
    proposal = _seed_approved(repo)

    result = repo.mark_failed(proposal.id, decided_by="orchestrator", reason="offer作成失敗: 429 Rate limit exceeded")

    assert result.payload["failure_reason"] == "offer作成失敗: 429 Rate limit exceeded"
