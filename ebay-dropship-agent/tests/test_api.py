"""承認Web UI(api/)のテスト。認証必須・高リスク確認ステップ・decided_by記録・

クライアントを信用しない(status等の上書きを無視する)ことを検証する。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from ebay_dropship.api import app
from ebay_dropship.approval import Priority, Proposal, ProposalType, RiskLevel
from ebay_dropship.config import Settings, settings
from ebay_dropship.store import (
    Base,
    SqlProposalRepository,
    create_engine_from_settings,
    create_session_factory,
)

AUTH = ("alice", "secret1")


@pytest.fixture()
def api_db(tmp_path, monkeypatch):
    db_path = tmp_path / "api_test.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "approval_api_users", "alice:secret1,bob:secret2")
    engine = create_engine_from_settings(settings)
    Base.metadata.create_all(engine)
    return engine


def _seed(engine, **overrides) -> str:
    session = create_session_factory(engine)()
    defaults = {
        "proposal_type": ProposalType.PRICE_CHANGE,
        "priority": Priority.MEDIUM,
        "summary": "s",
        "rationale": "卸サプライヤーから直送",
        "risk_level": RiskLevel.LOW,
        "estimated_profit": Decimal("8.0"),
        "requires_human_approval": True,
    }
    defaults.update(overrides)
    saved = SqlProposalRepository(session).enqueue(Proposal(**defaults))
    session.commit()
    session.close()
    return saved.id


@pytest.fixture()
def client(api_db):
    return TestClient(app)


def test_default_bind_host_is_localhost():
    assert Settings().approval_api_host == "127.0.0.1"


def test_default_users_is_empty_fail_closed():
    assert Settings().approval_api_users == ""


def test_healthz_does_not_require_auth(client):
    response = client.get("/healthz")
    assert response.status_code == 200


def test_list_proposals_requires_auth(client, api_db):
    _seed(api_db)
    response = client.get("/proposals")
    assert response.status_code == 401


def test_list_proposals_with_valid_auth(client, api_db):
    _seed(api_db)
    response = client.get("/proposals", auth=AUTH)
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_invalid_credentials_rejected(client, api_db):
    _seed(api_db)
    response = client.get("/proposals", auth=("alice", "wrong-password"))
    assert response.status_code == 401


def test_unknown_username_rejected(client, api_db):
    _seed(api_db)
    response = client.get("/proposals", auth=("mallory", "anything"))
    assert response.status_code == 401


def test_no_users_configured_means_nobody_can_authenticate(client, api_db, monkeypatch):
    """fail-closed: APPROVAL_API_USERSが空なら誰も認証できない。"""
    monkeypatch.setattr(settings, "approval_api_users", "")
    _seed(api_db)

    response = client.get("/proposals", auth=AUTH)

    assert response.status_code == 401


def test_approve_records_authenticated_username_as_decided_by(client, api_db):
    proposal_id = _seed(api_db)

    response = client.post(f"/proposals/{proposal_id}/approve", json={}, auth=AUTH)

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    session = create_session_factory(api_db)()
    stored = SqlProposalRepository(session).get(proposal_id)
    session.close()
    assert stored.decided_by == "alice"  # クライアントはdecided_byを指定できない。認証情報からのみ決まる


def test_second_configured_user_can_also_authenticate_and_is_recorded(client, api_db):
    proposal_id = _seed(api_db)

    response = client.post(f"/proposals/{proposal_id}/approve", json={}, auth=("bob", "secret2"))

    assert response.status_code == 200
    session = create_session_factory(api_db)()
    stored = SqlProposalRepository(session).get(proposal_id)
    session.close()
    assert stored.decided_by == "bob"


def test_high_risk_approval_requires_confirmation(client, api_db):
    proposal_id = _seed(api_db, risk_level=RiskLevel.HIGH)

    without_confirm = client.post(f"/proposals/{proposal_id}/approve", json={}, auth=AUTH)
    assert without_confirm.status_code == 409

    with_confirm = client.post(f"/proposals/{proposal_id}/approve", json={"confirm": True}, auth=AUTH)
    assert with_confirm.status_code == 200
    assert with_confirm.json()["status"] == "approved"


def test_low_risk_approval_does_not_require_confirmation(client, api_db):
    proposal_id = _seed(api_db, risk_level=RiskLevel.LOW)

    response = client.post(f"/proposals/{proposal_id}/approve", json={}, auth=AUTH)

    assert response.status_code == 200


def test_reject_records_decided_by_and_reason(client, api_db):
    proposal_id = _seed(api_db)

    response = client.post(f"/proposals/{proposal_id}/reject", json={"reason": "利益率不足"}, auth=AUTH)

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_approve_twice_returns_conflict_not_double_approval(client, api_db):
    proposal_id = _seed(api_db)
    client.post(f"/proposals/{proposal_id}/approve", json={}, auth=AUTH)

    response = client.post(f"/proposals/{proposal_id}/approve", json={}, auth=AUTH)

    assert response.status_code == 409


def test_approve_unknown_proposal_returns_404(client, api_db):
    response = client.post("/proposals/does-not-exist/approve", json={}, auth=AUTH)
    assert response.status_code == 404


def test_client_supplied_extra_fields_are_ignored_not_honored(client, api_db):
    """クライアントがボディにstatus/estimated_profit等を混ぜても、サーバは受け付けたフィールドしか使わない。"""
    proposal_id = _seed(api_db)

    response = client.post(
        f"/proposals/{proposal_id}/approve",
        json={"confirm": True, "status": "executed", "estimated_profit": "999999.99", "decided_by": "mallory"},
        auth=AUTH,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"  # "executed"を混入させても無視される
    assert body["estimated_profit"] != "999999.99"  # クライアントの上書きは効かない
    session = create_session_factory(api_db)()
    stored = SqlProposalRepository(session).get(proposal_id)
    session.close()
    assert stored.decided_by == "alice"  # "mallory"は無視され、認証情報が優先される
