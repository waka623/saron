"""`GET|POST /ebay/account-deletion`(eBay Marketplace Account Deletion/Closure通知)のテスト。

実eBayへは接続しない。認証不要のエンドポイントであること(eBay側はBasic認証を送れない)、
challengeResponseの計算・JSONシリアライズ(BOM混入無し)・POSTの受信ログのみで副作用が
無いこと・verificationTokenのバリデーションを検証する。
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from ebay_dropship.api import app
from ebay_dropship.api.account_deletion import (
    compute_challenge_response,
    is_valid_verification_token,
)
from ebay_dropship.config import settings
from ebay_dropship.store import Base, create_engine_from_settings

VALID_TOKEN = "a" * 40  # 32〜80文字・英数字のみを満たす検証用の仮値
ENDPOINT_URL = "https://example.com/ebay/account-deletion"


@pytest.fixture()
def api_db(tmp_path, monkeypatch):
    db_path = tmp_path / "api_account_deletion_test.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "ebay_deletion_verification_token", VALID_TOKEN)
    monkeypatch.setattr(settings, "ebay_deletion_endpoint_url", ENDPOINT_URL)
    engine = create_engine_from_settings(settings)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def client(api_db):
    return TestClient(app)


# --- (a) ハッシュ計算が正しいこと ---


def test_compute_challenge_response_matches_manual_sha256():
    challenge_code = "abc123"
    expected = hashlib.sha256((challenge_code + VALID_TOKEN + ENDPOINT_URL).encode("utf-8")).hexdigest()

    result = compute_challenge_response(challenge_code, VALID_TOKEN, ENDPOINT_URL)

    assert result == expected


def test_compute_challenge_response_order_matters():
    """連結順序を誤る(token+code+endpoint等)と別のハッシュになることを確認し、順序厳守を担保する。"""
    challenge_code = "abc123"
    correct = compute_challenge_response(challenge_code, VALID_TOKEN, ENDPOINT_URL)
    wrong_order = hashlib.sha256((VALID_TOKEN + challenge_code + ENDPOINT_URL).encode("utf-8")).hexdigest()

    assert correct != wrong_order


# --- (b) GETが200・application/json・BOM無しで返ること ---


def test_get_challenge_returns_200_json_without_bom(client):
    response = client.get("/ebay/account-deletion", params={"challenge_code": "abc123"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert not response.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    expected = hashlib.sha256(("abc123" + VALID_TOKEN + ENDPOINT_URL).encode("utf-8")).hexdigest()
    assert response.json() == {"challengeResponse": expected}


def test_get_challenge_does_not_require_authentication(client):
    """eBay側はBasic認証ヘッダーを送れないため、認証無しでアクセスできる必要がある。"""
    response = client.get("/ebay/account-deletion", params={"challenge_code": "xyz"})

    assert response.status_code == 200


def test_get_challenge_fails_cleanly_when_verification_token_misconfigured(client, monkeypatch):
    monkeypatch.setattr(settings, "ebay_deletion_verification_token", "too-short")

    response = client.get("/ebay/account-deletion", params={"challenge_code": "abc123"})

    assert response.status_code == 500


def test_get_challenge_fails_cleanly_when_endpoint_url_missing(client, monkeypatch):
    monkeypatch.setattr(settings, "ebay_deletion_endpoint_url", "")

    response = client.get("/ebay/account-deletion", params={"challenge_code": "abc123"})

    assert response.status_code == 500


# --- (c) POSTが200/204で返ること ---


def test_post_notification_returns_204_and_does_not_require_auth(client):
    response = client.post(
        "/ebay/account-deletion",
        json={"metadata": {"topic": "MARKETPLACE_ACCOUNT_DELETION"}, "notification": {"data": {"userId": "u1"}}},
    )

    assert response.status_code == 204


def test_post_notification_logs_payload_without_raising(client, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="ebay_dropship.api"):
        response = client.post("/ebay/account-deletion", json={"notification": {"data": {"userId": "u1"}}})

    assert response.status_code == 204
    assert any("account deletion notification received" in record.message for record in caplog.records)


def test_post_notification_handles_non_json_body_without_error(client):
    response = client.post(
        "/ebay/account-deletion", content=b"not-json", headers={"Content-Type": "text/plain"}
    )

    assert response.status_code == 204


# --- (d) verificationTokenのバリデーション ---


@pytest.mark.parametrize(
    "token",
    [
        "a" * 31,  # 32文字未満
        "a" * 81,  # 80文字超
        "",
        "invalid token with spaces" + "a" * 20,
        "invalid!chars$$$$" + "a" * 20,
    ],
)
def test_is_valid_verification_token_rejects_invalid_formats(token):
    assert is_valid_verification_token(token) is False


@pytest.mark.parametrize("token", ["a" * 32, "a" * 80, "Abc123_-" * 4, "a" * 40])
def test_is_valid_verification_token_accepts_valid_formats(token):
    assert is_valid_verification_token(token) is True
