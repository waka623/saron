"""`GET /ui`(承認/却下ボタン付きの簡単なHTML画面)のテスト。

画面内のJavaScriptの実際の動作(fetch呼び出し等)はブラウザが無いと検証できないため、
ここではサーバ側の契約(認証必須・HTML応答・既存API呼び出しへの導線が埋め込まれていること)のみを
検証する。承認/却下そのもののロジックは`test_api.py`で別途検証済み(このエンドポイントは
既存の`/proposals`系エンドポイントを呼ぶだけで、新しいロジックを持たない)。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ebay_dropship.api import app
from ebay_dropship.config import settings
from ebay_dropship.store import Base, create_engine_from_settings

AUTH = ("alice", "secret1")


@pytest.fixture()
def api_db(tmp_path, monkeypatch):
    db_path = tmp_path / "api_ui_test.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "approval_api_users", "alice:secret1")
    engine = create_engine_from_settings(settings)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def client(api_db):
    return TestClient(app)


def test_ui_requires_auth(client):
    response = client.get("/ui")

    assert response.status_code == 401


def test_ui_returns_html_with_valid_auth(client):
    response = client.get("/ui", auth=AUTH)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "承認待ちの提案" in response.text


def test_ui_wires_approve_and_reject_to_existing_endpoints(client):
    """新しい実行経路を作らず、既存の/proposals系JSON APIを叩くだけであることの確認。"""
    response = client.get("/ui", auth=AUTH)

    body = response.text
    assert "/proposals" in body
    assert "/approve" in body
    assert "/reject" in body
    assert "class=\"approve\"" in body
    assert "class=\"reject\"" in body
