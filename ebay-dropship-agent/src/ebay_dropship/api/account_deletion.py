"""eBay Marketplace Account Deletion/Closure notification のロジック(ネットワーク非依存)。

eBay開発者ポータルにエンドポイントURLとverificationTokenを登録すると、eBayはまずGETで
チャレンジコード(`challenge_code`)を送り、`challengeResponse = SHA-256(challengeCode +
verificationToken + endpoint)`(16進文字列)を正しく返せるか検証する。検証に通って初めて、
実際の削除/退会通知がPOSTで送られてくるようになる。

ここでは検証・ハッシュ計算という純粋なロジックだけを提供し、HTTPの配線(`api/__init__.py`)から
分離してユニットテストしやすくしている。
"""

from __future__ import annotations

import hashlib
import re

# eBay公式仕様: verificationTokenは32〜80文字、英数字と `_` `-` のみ。
_VERIFICATION_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,80}$")


def is_valid_verification_token(token: str) -> bool:
    return bool(_VERIFICATION_TOKEN_PATTERN.fullmatch(token))


def compute_challenge_response(challenge_code: str, verification_token: str, endpoint: str) -> str:
    """challengeResponseを計算する(SHA-256のhex文字列)。

    連結順序は `challengeCode + verificationToken + endpoint` で厳守する(eBay公式仕様どおり。
    順序を誤ると検証チャレンジに失敗する)。
    """
    hasher = hashlib.sha256()
    hasher.update(challenge_code.encode("utf-8"))
    hasher.update(verification_token.encode("utf-8"))
    hasher.update(endpoint.encode("utf-8"))
    return hasher.hexdigest()
