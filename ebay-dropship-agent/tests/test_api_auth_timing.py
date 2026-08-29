"""F6の回帰テスト: Basic認証(`require_auth`)の未知usernameによるタイミングサイドチャネル。

adversarial security review(2026-08-29)で、`require_auth`が未知のusernameのとき
`secrets.compare_digest`を一切呼ばずに短絡評価しており(`expected_password is not None and ...`)、
既知usernameでは必ず`compare_digest`(定時間比較)を通ることとの応答時間差から、
usernameの存在を推測できる可能性があることを指摘した。

実際のwall-clockタイミングを測る形のテストはCI環境依存でflakyになるため、代わりに
「`secrets.compare_digest`が既知/未知いずれのusernameでも必ず同じ回数呼ばれる」という
構造的な性質を検証する(呼ばれる/呼ばれないの非対称性そのものがタイミング差の原因であるため)。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

from ebay_dropship.api import require_auth
from ebay_dropship.config import Settings


def _settings() -> Settings:
    return Settings(approval_api_users="alice:secret1,bob:secret2")


def test_compare_digest_is_called_for_known_username_with_wrong_password():
    with patch("ebay_dropship.api.secrets.compare_digest", wraps=__import__("secrets").compare_digest) as spy:
        with pytest.raises(HTTPException):
            require_auth(HTTPBasicCredentials(username="alice", password="wrong"), _settings())
        assert spy.call_count == 1


def test_compare_digest_is_also_called_for_unknown_username():
    """修正前はここで呼ばれず(短絡評価)call_count==0になり、既知usernameとの非対称性が生じていた。"""
    with patch("ebay_dropship.api.secrets.compare_digest", wraps=__import__("secrets").compare_digest) as spy:
        with pytest.raises(HTTPException):
            require_auth(HTTPBasicCredentials(username="unknown-user", password="whatever"), _settings())
        assert spy.call_count == 1


def test_valid_credentials_still_authenticate():
    """回帰防止: 正常系(既知username+正しいpassword)が壊れていないこと。"""
    result = require_auth(HTTPBasicCredentials(username="alice", password="secret1"), _settings())
    assert result == "alice"
