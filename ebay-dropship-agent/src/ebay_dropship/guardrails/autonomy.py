"""S3: スケジュール自走(オプトイン)における自動承認の対象範囲を定義する。

レベルB方針(厳守): "お金が動かない"publish系の副作用だけが自動承認の対象になりうる。
supplier_purchase(発注=お金が動く)・price_change/withdraw/purchase等、その他の書き込み系
proposal_typeは、`settings`の値に関わらずコードレベルで自動承認の対象外とする。

`AUTO_APPROVABLE_TYPES`は設定ファイルや環境変数から読み込む値ではなく、このモジュール内に
ハードコードされたfrozensetである。これにより「.envの書き間違い・設定ミスでsupplier_purchase等
まで自動承認対象に広がってしまう」事故を構造的に防ぐ(deny-by-defaultの精神を自動承認の
対象範囲そのものにも適用する)。
"""

from __future__ import annotations

from ebay_dropship.approval import ProposalType
from ebay_dropship.config import Settings

# レベルBの許可リスト(コード固定・設定不可)。publish以外を絶対に追加しないこと。
AUTO_APPROVABLE_TYPES = frozenset({ProposalType.PUBLISH})


def is_auto_approvable(proposal_type: ProposalType) -> bool:
    """この proposal_type が自動承認の対象になりうるか(コードレベルの許可リストのみで判定)。"""
    return proposal_type in AUTO_APPROVABLE_TYPES


def autonomy_active(settings: Settings) -> bool:
    """自走(自動承認)が実際に有効かどうか。

    kill-switch(`autonomy_kill_switch`)が最優先: True の間は `autonomy_enabled` の値に関わらず
    問答無用で自動承認を無効化する(緊急停止用の独立したフラグ。`autonomy_enabled`を誤って
    Trueのままにしていても、kill-switchだけ倒せば止まる、という運用を可能にするため)。
    """
    if settings.autonomy_kill_switch:
        return False
    return settings.autonomy_enabled


def auto_approve_publish_active(settings: Settings) -> bool:
    """publish系の自動承認が有効かどうか(自走全体が有効、かつauto_approve_publishも有効)。"""
    return autonomy_active(settings) and settings.auto_approve_publish
